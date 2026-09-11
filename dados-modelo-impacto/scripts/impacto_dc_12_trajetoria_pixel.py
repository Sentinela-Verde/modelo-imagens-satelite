"""Passo 12 — detecção por TRAJETÓRIA de pixel, em vez de área agregada.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_12_trajetoria_pixel.py

## Por que trocar de estatística

Os passos 10 e 11 mediram **área da classe no disco** e não acharam nada: o teste de sinal fica em
torno de 0,5 em todos os raios de 0,5 a 5 km, e o pico de "solo exposto" cai na fase de obra menos
vezes que o acaso previria.

Somar área é frágil aqui por um motivo específico: a classe 3 (solo exposto/obras) é a pior do
classificador — F1 0,579, precisão 0,587, recall 0,572 (`reports/avaliacao_rf_v1.0-tuned.md`).
Numa soma de área, cada falso positivo entra com o mesmo peso de um pixel verdadeiro, e num disco
de milhares de pixels o ruído de 41% de falsos positivos afoga uma obra de algumas dezenas.

Uma **trajetória** é muito mais exigente. Para um pixel contar aqui, ele precisa:

1. **não** ser construída nos 2 primeiros anos da janela,
2. **ser** construída nos 2 últimos anos — e permanecer,
3. (na variante estrita) ter passado por solo exposto em algum ano intermediário.

Um falso positivo isolado não satisfaz uma sequência ordenada e persistente; três anos coerentes
satisfazem. É a mesma lógica de exigir confirmação em série em vez de confiar numa medida pontual.

O controle dá a hipótese nula: quantos pixels fazem essa mesma trajetória, no mesmo período e na
mesma região, **sem** data center nenhum. O que interessa é o excesso do tratamento sobre o
controle, par a par.

## Custo

Zero de rede. Os rasters classificados dos 30 pontos já estão em disco desde o passo 4 — foi por
isso que o descarte de intermediários preservou justamente os classificados.

Saídas:
  - `raw/controles-rf/trajetoria_pixel.csv` — contagens por ponto e raio
  - `raw/controles-rf/trajetoria_pixel_resumo.csv` — teste de sinal por raio e assinatura
  - `raw/controles-rf/figuras/fig_07_trajetoria_pixel.png`
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_11_sensibilidade_buffer as P11
import impacto_dc_comum as C

RAIOS_KM = [0.5, 1.0, 2.0, 5.0]
ANOS_BORDA = 2  # quantos anos de cada ponta definem o estado "antes" e o estado "depois"

VEGETACAO = (1, 2)
SOLO_EXPOSTO = 3
CONSTRUIDA = 4

ASSINATURAS = {
    "virou_construida": "não era construída no início, é construída no fim (e persiste)",
    "virou_construida_via_solo": "o mesmo, e passou por solo exposto num ano intermediário",
    "vegetacao_para_construida": "era vegetação no início, é construída no fim",
}

SAIDA_LONGO = C.DIR_SAIDA / "trajetoria_pixel.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "trajetoria_pixel_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_07_trajetoria_pixel.png"


def empilhar(site_id: str, sensor: str, anos: list[int]) -> np.ndarray:
    """(n_anos, altura, largura) com as classes de cada ano, na ordem cronológica."""
    camadas = []
    for ano in sorted(anos):
        with rasterio.open(C.caminho_classificado(sensor, site_id, ano)) as src:
            camadas.append(src.read(1))
    return np.stack(camadas)


def contar_assinaturas(pilha: np.ndarray, mascara: np.ndarray) -> dict[str, int]:
    """Conta pixels que satisfazem cada assinatura, dentro da máscara de raio."""
    inicio = pilha[:ANOS_BORDA]
    fim = pilha[-ANOS_BORDA:]
    meio = pilha[ANOS_BORDA:-ANOS_BORDA] if pilha.shape[0] > 2 * ANOS_BORDA else pilha[0:0]

    # Pixel só conta se tem classe válida (1-5) em TODOS os anos: um ano mascarado por nuvem
    # inventaria transição onde só houve dado faltante.
    valido = np.all(pilha > 0, axis=0) & mascara

    nao_construida_inicio = np.all(inicio != CONSTRUIDA, axis=0)
    construida_fim = np.all(fim == CONSTRUIDA, axis=0)
    virou = nao_construida_inicio & construida_fim & valido

    passou_solo = np.any(meio == SOLO_EXPOSTO, axis=0) if meio.size else np.zeros_like(virou)
    era_vegetacao = np.all(np.isin(inicio, VEGETACAO), axis=0)

    return {
        "pixels_validos_mascara": int(valido.sum()),
        "virou_construida": int(virou.sum()),
        "virou_construida_via_solo": int((virou & passou_solo).sum()),
        "vegetacao_para_construida": int((era_vegetacao & construida_fim & valido).sum()),
    }


def p_bin_superior(k: int, n: int, p0: float = 0.5) -> float:
    """P(X >= k) sob Binomial(n, p0) — cauda superior exata, teste unilateral.

    Unilateral de propósito: a hipótese tem direção. Se a obra constrói, o tratamento tem que ter
    MAIS pixels virando construída que o controle, nunca menos. Um resultado forte na direção
    contrária seria sinal de erro de desenho, não de efeito, e aparece na coluna `n_negativo`.
    """
    return sum(math.comb(n, i) * p0**i * (1 - p0) ** (n - i) for i in range(k, n + 1))


def teste_localizacao(longo: pd.DataFrame, assinatura: str) -> pd.DataFrame:
    """O excesso é LOCALIZADO no site ou é tendência REGIONAL de urbanização?

    Discriminante: converter o excesso de pontos percentuais para hectares absolutos e ver como
    ele escala com o raio. Se o que muda é o terreno do data center, a área do excesso fica
    aproximadamente constante enquanto o disco cresce. Se o tratamento só está numa região que
    urbaniza mais rápido, o excesso cresce junto com a área do disco (100x de 0,5 km para 5 km).
    """
    linhas = []
    base = None
    for raio, g in longo.groupby("raio_km"):
        excessos_ha, excessos_pp = [], []
        for _, par in g.groupby("pareado_com"):
            t = par[par["tipo"] == "tratamento"]
            c = par[par["tipo"] == "controle"]
            if t.empty or c.empty:
                continue
            resolucao = 30.0 if t["sensor"].iloc[0] == "landsat" else 10.0
            pp = float(t[f"pct_{assinatura}"].iloc[0] - c[f"pct_{assinatura}"].iloc[0])
            excessos_pp.append(pp)
            excessos_ha.append(pp / 100 * float(t["pixels_validos_mascara"].iloc[0])
                               * resolucao**2 / 1e4)
        if not excessos_ha:
            continue
        ha = float(np.median(excessos_ha))
        if base is None:
            base = ha
        linhas.append({
            "assinatura": assinatura, "raio_km": raio,
            "area_disco_ha": round(np.pi * raio**2 * 100, 1),
            "excesso_mediano_pp": round(float(np.median(excessos_pp)), 4),
            "excesso_mediano_ha": round(ha, 2),
            "crescimento_vs_menor_raio": round(ha / base, 2) if base else np.nan,
            "crescimento_do_disco": round((np.pi * raio**2 * 100) / (np.pi * RAIOS_KM[0] ** 2 * 100), 1),
        })
    return pd.DataFrame(linhas)


def teste_tendencias_paralelas(painel: pd.DataFrame, coluna: str = "prop_construida_urbana") -> pd.DataFrame:
    """Pré-teste de tendências paralelas — a hipótese identificadora de diferença-em-diferenças.

    Pergunta: **antes** de a obra começar, o tratamento já crescia em área construída mais rápido
    que o controle? Se sim, o excesso medido depois não é do data center, é de o data center ter
    sido construído justamente onde a região já estava urbanizando (viés de localização).

    Ajusta uma reta em cada série pré-obra e compara as inclinações, par a par.
    """
    linhas = []
    for site_id, g in painel.groupby("pareado_com"):
        inclinacoes = {}
        for tipo in ("tratamento", "controle"):
            s = g[(g["tipo"] == tipo) & (g["fase"] == "pre")].sort_values("ano")
            if len(s) < 3:
                inclinacoes = {}
                break
            inclinacoes[tipo] = float(np.polyfit(s["ano"], s[coluna] * 100, 1)[0])
        if inclinacoes:
            linhas.append({
                "pareado_com": site_id,
                "inclinacao_tratamento_pp_ano": round(inclinacoes["tratamento"], 4),
                "inclinacao_controle_pp_ano": round(inclinacoes["controle"], 4),
                "diferenca_pp_ano": round(inclinacoes["tratamento"] - inclinacoes["controle"], 4),
            })
    return pd.DataFrame(linhas)


def main() -> int:
    painel = pd.read_csv(C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv")
    print(f"Passo 12 — trajetória de pixel, {painel.pareado_com.nunique()} pares x "
          f"{len(RAIOS_KM)} raios, sem rede")

    registros: list[dict[str, Any]] = []
    for (site_id, sensor), grupo in painel.groupby(["site_id", "sensor"]):
        anos = sorted(grupo["ano"].tolist())
        if len(anos) < 2 * ANOS_BORDA + 1:
            print(f"  {site_id}: só {len(anos)} anos — precisa de {2 * ANOS_BORDA + 1}, pulando")
            continue
        primeiro = grupo.iloc[0]
        tif = C.caminho_classificado(sensor, site_id, anos[0])
        mascaras = {
            r: m for r, m in P11.mascaras_por_raio(
                tif, float(primeiro["lat"]), float(primeiro["lon"])
            ).items() if r in RAIOS_KM
        }
        pilha = empilhar(site_id, sensor, anos)

        for raio, mascara in mascaras.items():
            contagens = contar_assinaturas(pilha, mascara)
            registros.append({
                "site_id": site_id, "tipo": primeiro["tipo"], "pareado_com": primeiro["pareado_com"],
                "sensor": sensor, "raio_km": raio, "ano_inicio": anos[0], "ano_fim": anos[-1],
                "n_anos": len(anos), **contagens,
            })
        print(f"  {site_id} ({sensor}, {len(anos)} anos)")

    longo = pd.DataFrame(registros)
    # Normaliza por pixels válidos: os buffers de tratamento e controle têm contagens ligeiramente
    # diferentes (grade e nodata), então comparar contagem crua enviesaria o par.
    for assinatura in ASSINATURAS:
        longo[f"pct_{assinatura}"] = (
            100.0 * longo[assinatura] / longo["pixels_validos_mascara"].replace(0, np.nan)
        )
    C.salvar_csv(longo, SAIDA_LONGO)

    linhas = []
    for raio, g_raio in longo.groupby("raio_km"):
        for assinatura in ASSINATURAS:
            col = f"pct_{assinatura}"
            difs = []
            for _, par in g_raio.groupby("pareado_com"):
                t = par[par["tipo"] == "tratamento"][col]
                c = par[par["tipo"] == "controle"][col]
                if t.empty or c.empty or t.isna().all() or c.isna().all():
                    continue
                difs.append(float(t.iloc[0] - c.iloc[0]))
            if not difs:
                continue
            n = len(difs)
            pos = sum(1 for v in difs if v > 0)
            linhas.append({
                "raio_km": raio, "assinatura": assinatura, "n_pares": n,
                "n_positivo": pos, "n_negativo": n - pos, "frac_positivo": round(pos / n, 3),
                "p_unilateral": round(p_bin_superior(pos, n), 4),
                "excesso_mediano_pp": round(float(np.median(difs)), 4),
                "excesso_medio_pp": round(float(np.mean(difs)), 4),
            })
    resumo = pd.DataFrame(linhas)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    cores = {"virou_construida": "#C0392B", "virou_construida_via_solo": "#F5A623",
             "vegetacao_para_construida": "#1B5E20"}
    ax = axes[0]
    for assinatura, g in resumo.groupby("assinatura"):
        g = g.sort_values("raio_km")
        ax.plot(g["raio_km"], g["frac_positivo"], "o-", linewidth=2.2, markersize=7,
                color=cores.get(assinatura, "#5D6D7E"), label=assinatura)
    ax.axhline(0.5, color="gray", linestyle="--", linewidth=1.4)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Raio (km)")
    ax.set_ylabel("fração dos pares com excesso no tratamento")
    ax.set_title("Teste de sinal — o tratamento tem mais pixels\nfazendo a trajetória que o controle?",
                 fontsize=11.5)
    ax.legend(fontsize=8.5, loc="lower right")
    ax.grid(alpha=0.25)

    ax2 = axes[1]
    for assinatura, g in resumo.groupby("assinatura"):
        g = g.sort_values("raio_km")
        ax2.plot(g["raio_km"], g["excesso_mediano_pp"], "o-", linewidth=2.2, markersize=7,
                 color=cores.get(assinatura, "#5D6D7E"), label=assinatura)
    ax2.axhline(0.0, color="gray", linestyle="--", linewidth=1.4)
    ax2.set_xlabel("Raio (km)")
    ax2.set_ylabel("excesso do tratamento (pontos percentuais dos pixels)")
    ax2.set_title("Tamanho do excesso\npositivo = mais conversão para construída no tratamento",
                  fontsize=11.5)
    ax2.legend(fontsize=8.5)
    ax2.grid(alpha=0.25)
    fig.suptitle("Detecção por trajetória de pixel — exige sequência ordenada e persistente",
                 fontsize=13, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    SAIDA_FIGURA.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=140)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print()
    for assinatura, descricao in ASSINATURAS.items():
        print(f"=== {assinatura}: {descricao}")
        g = resumo[resumo["assinatura"] == assinatura].sort_values("raio_km")
        print(f"{'raio':>6} {'trat>ctrl':>10} {'fração':>8} {'p':>8} {'excesso pp':>12}")
        for _, r in g.iterrows():
            marca = f"{int(r['n_positivo'])}/{int(r['n_pares'])}"
            print(f"{r['raio_km']:>5.1f}k {marca:>10} {r['frac_positivo']:>8.2f} "
                  f"{r['p_unilateral']:>8.3f} {r['excesso_mediano_pp']:>12.4f}")
        print()

    sig = resumo[resumo["p_unilateral"] < 0.05]
    n_testes = len(resumo)
    if len(sig):
        print("SINAL ENCONTRADO em:")
        for _, r in sig.sort_values("p_unilateral").iterrows():
            bonf = min(1.0, r["p_unilateral"] * n_testes)
            print(f"  {r['assinatura']} a {r['raio_km']} km — {int(r['n_positivo'])}/"
                  f"{int(r['n_pares'])} pares, p={r['p_unilateral']:.4f} "
                  f"(Bonferroni x{n_testes} = {bonf:.3f}), "
                  f"excesso mediano {r['excesso_mediano_pp']:+.4f} pp")
    else:
        print("ACHADO: nenhuma assinatura de trajetória se distingue de acaso em nenhum raio.")

    # ---- validação 1: o excesso está no site ou é tendência regional? ----
    print()
    print("=== VALIDAÇÃO 1 — localização do excesso ===")
    localizacao = pd.concat([teste_localizacao(longo, a) for a in ASSINATURAS], ignore_index=True)
    C.salvar_csv(localizacao, C.DIR_SAIDA / "trajetoria_pixel_localizacao.csv")
    foco = localizacao[localizacao["assinatura"] == "virou_construida"]
    print("assinatura 'virou_construida':")
    print(f"{'raio':>6} {'disco (ha)':>11} {'excesso pp':>12} {'excesso ha':>12} "
          f"{'cresc. excesso':>15} {'cresc. disco':>13}")
    for _, r in foco.iterrows():
        print(f"{r['raio_km']:>5.1f}k {r['area_disco_ha']:>11.0f} {r['excesso_mediano_pp']:>12.4f} "
              f"{r['excesso_mediano_ha']:>12.2f} {r['crescimento_vs_menor_raio']:>14.1f}x "
              f"{r['crescimento_do_disco']:>12.0f}x")
    print("Excesso crescendo MUITO menos que o disco = concentrado perto do site.")

    # ---- validação 2: tendências paralelas antes da obra ----
    print()
    print("=== VALIDAÇÃO 2 — tendências paralelas pré-obra ===")
    paralelas = teste_tendencias_paralelas(painel)
    C.salvar_csv(paralelas, C.DIR_SAIDA / "trajetoria_pixel_tendencias_paralelas.csv")
    n_par = len(paralelas)
    pos_par = int((paralelas["diferenca_pp_ano"] > 0).sum())
    p_par = p_bin_superior(pos_par, n_par)
    print(f"Tratamento com inclinação pré-obra MAIOR que o controle: {pos_par} de {n_par} "
          f"(p unilateral = {p_par:.3f})")
    print(f"Diferença mediana de inclinação: {paralelas['diferenca_pp_ano'].median():+.4f} pp/ano")
    if p_par < 0.05:
        print("ACHADO GRAVE: as tendências pré-obra NÃO são paralelas. O excesso medido acima é")
        print("compatível com viés de localização (o data center foi construído onde a região já")
        print("urbanizava mais rápido), não necessariamente com efeito do empreendimento.")
    else:
        print("As tendências pré-obra são estatisticamente paralelas: não há evidência de que os")
        print("data centers tenham sido construídos em áreas que já urbanizavam mais rápido que")
        print("seus controles. É a hipótese identificadora do desenho, e ela se sustenta aqui.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
