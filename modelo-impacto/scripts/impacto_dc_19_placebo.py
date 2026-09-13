"""Passo 19 — teste placebo: o método acha efeito onde NÃO houve data center?

Rode com (nesta ordem):

    python modelo-impacto/scripts/impacto_dc_19_placebo.py --fase selecao
    python modelo-impacto/scripts/impacto_dc_19_placebo.py --fase classificar
    python modelo-impacto/scripts/impacto_dc_19_placebo.py --fase analise

## Por que este passo existe

Os passos 12-15 medem excesso de conversão do tratamento sobre o controle e encontram 12/14 pares
positivos (p=0,0065). O passo 18 (estudo de evento) deu um resultado mais fraco e não sustentado.
Falta a pergunta que decide entre "efeito real, medida ruidosa" e "método que produz sinal do nada":

    **Aplicando exatamente o mesmo método a um par onde NENHUM data center foi construído,
    ele acha excesso?**

Se achar, o 12/14 dos passos anteriores perde o significado — seria a taxa de falso positivo do
método, não efeito de data center. Se não achar, o achado ganha a validação que mais falta.

## O desenho

Para cada campus, o passo 3 avaliou ~5 candidatos a controle e escolheu 1. Os **não escolhidos**
passaram pelos mesmos filtros (distância 15-40 km, mesmo estado, mesmo bioma, sem data center) e
são, por construção, lugares comparáveis onde nada foi construído.

O par placebo é, então, **(controle escolhido, melhor candidato não escolhido)** — dois lugares sem
data center, na mesma região, com a mesma janela de anos e o mesmo ano de obra FICTÍCIO do par real.
Roda-se o método idêntico. A expectativa é nada.

**O parceiro placebo NÃO é simplesmente o vice do ranking.** Aquele ranking mede distância ao
*tratamento*; aqui o que importa é a distância ao *controle*, que é a outra ponta do par placebo.
A fase `selecao` recalcula isso a partir dos rasters do ano de referência, que já estão em disco
para todos os 44 candidatos não escolhidos.

## Custo

A fase `selecao` é gratuita (lê rasters locais). A fase `classificar` roda GEE para a janela
completa dos parceiros escolhidos — é a única parte cara, e é idempotente: reinterromper e rodar
de novo não refaz o que já existe.

Saídas:
  - `raw/controles-rf/placebo_pares.csv`   — o par placebo de cada campus e sua qualidade
  - `raw/controles-rf/placebo_resultado.csv` — excesso por par placebo, por zona
  - `raw/controles-rf/placebo_resumo.csv`  — teste de sinal placebo vs. teste de sinal real
  - `raw/controles-rf/figuras/fig_12_placebo.png`
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_12_trajetoria_pixel as P12  # noqa: E402

SAIDA_PARES = C.DIR_SAIDA / "placebo_pares.csv"
SAIDA_RESULTADO = C.DIR_SAIDA / "placebo_resultado.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "placebo_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_12_placebo.png"

RAIOS_KM = [0.5, 1.0, 2.0]


def _proporcoes(sensor: str, site_id: str, ano: int) -> np.ndarray | None:
    """Distribuição de classes (5 valores somando 1) de um ponto num ano, do raster classificado."""
    tif = Path(C.caminho_classificado(sensor, site_id, ano))
    if not tif.exists():
        return None
    with rasterio.open(tif) as src:
        arr = src.read(1)
    valido = arr > 0
    n = int(valido.sum())
    if n == 0:
        return None
    return np.array([float((arr == c).sum()) / n for c in C.CLASS_IDS])


def fase_selecao() -> pd.DataFrame:
    """Escolhe, para cada campus, o parceiro placebo mais parecido com o CONTROLE."""
    pareamento = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    candidatos = pd.read_csv(C.DIR_SAIDA / "candidatos_avaliados_rf.csv")

    linhas = []
    for _, par in pareamento.iterrows():
        site = par.site_id
        controle = par.site_id_controle
        if not isinstance(controle, str) or not controle:
            continue
        sensor, ano_ref = par.sensor, int(par.ano_referencia_pareamento)

        p_ctrl = _proporcoes(sensor, controle, ano_ref)
        if p_ctrl is None:
            print(f"  ! {site}: controle {controle} sem raster em {ano_ref}, fora do placebo")
            continue

        melhor = None
        for _, cand in candidatos[candidatos.site_id == site].iterrows():
            cid = cand.site_id_controle
            if cid == controle:
                continue
            p_cand = _proporcoes(sensor, cid, ano_ref)
            if p_cand is None:
                continue
            l1 = float(np.abs(p_ctrl - p_cand).sum())
            if melhor is None or l1 < melhor[0]:
                melhor = (l1, cid, cand)
        if melhor is None:
            print(f"  ! {site}: nenhum candidato alternativo com raster, fora do placebo")
            continue

        l1, cid, cand = melhor
        linhas.append(
            {
                "campus_de_origem": site,
                "placebo_a": controle,          # o controle real do par
                "placebo_b": cid,               # o parceiro, também sem data center
                "sensor": sensor,
                "ano_obra_ficticio": int(par.ano_inicio_obra),
                "ano_referencia": ano_ref,
                "l1_entre_os_dois": round(l1, 4),
                "qualidade_par_placebo": C.qualidade_l1(l1),
                "lat_b": float(cand.lat),
                "lon_b": float(cand.lon),
                "dist_b_ao_tratamento_km": float(cand.dist_ao_tratamento_km),
            }
        )

    pares = pd.DataFrame(linhas)
    C.salvar_csv(pares, SAIDA_PARES)
    if not pares.empty:
        print("\nqualidade dos pares placebo:")
        print(pares.qualidade_par_placebo.value_counts().to_string())
    return pares


def fase_classificar() -> None:
    """Classifica a janela completa de cada parceiro placebo. Idempotente."""
    pares = pd.read_csv(SAIDA_PARES)
    C.iniciar_ee()
    pacote = C.carregar_modelo()

    total = 0
    for _, p in pares.iterrows():
        anos = C.janela_anos(int(p.ano_obra_ficticio))
        ponto = {"site_id": p.placebo_b, "lat": p.lat_b, "lon": p.lon_b, "buffer_km": C.BUFFER_KM}
        print(f"  {p.placebo_b} ({p.sensor}, {anos[0]}-{anos[-1]}, {len(anos)} anos)")
        for ano in anos:
            if Path(C.caminho_classificado(p.sensor, p.placebo_b, ano)).exists():
                continue
            C.rodar_ponto(ponto, ano, p.sensor, pacote, descartar_apos=True)
            total += 1
    print(f"\n{total} ponto-ano novos classificados")


def fase_analise() -> None:
    """Roda o método dos passos 12/14 sobre os pares placebo e compara com o resultado real."""
    pares = pd.read_csv(SAIDA_PARES)

    registros = []
    for _, p in pares.iterrows():
        anos = C.janela_anos(int(p.ano_obra_ficticio))
        for papel, pid in (("placebo_a", p.placebo_a), ("placebo_b", p.placebo_b)):
            faltando = [a for a in anos
                        if not Path(C.caminho_classificado(p.sensor, pid, a)).exists()]
            if faltando:
                print(f"  ! {pid}: faltam anos {faltando} — par fora")
                registros = [r for r in registros if r["campus_de_origem"] != p.campus_de_origem]
                break
            pilha = P12.empilhar(pid, p.sensor, anos)
            primeiro = Path(C.caminho_classificado(p.sensor, pid, anos[0]))
            lat, lon = (p.lat_b, p.lon_b) if papel == "placebo_b" else _latlon_controle(p)
            raios = P11.mascaras_por_raio(primeiro, lat, lon)
            for raio in RAIOS_KM:
                cont = P12.contar_assinaturas(pilha, raios[raio])
                n = cont["pixels_validos_mascara"]
                registros.append(
                    {
                        "campus_de_origem": p.campus_de_origem, "papel": papel, "site_id": pid,
                        "sensor": p.sensor, "raio_km": raio,
                        "qualidade_par_placebo": p.qualidade_par_placebo,
                        **cont,
                        **{f"pct_{a}": (100.0 * cont[a] / n if n else np.nan)
                           for a in P12.ASSINATURAS},
                    }
                )

    res = pd.DataFrame(registros)
    C.salvar_csv(res, SAIDA_RESULTADO)

    # --------------------------------------------------------------- teste de sinal placebo
    real = pd.read_csv(C.DIR_SAIDA / "trajetoria_pixel_resumo.csv")
    linhas = []
    for raio, g in res.groupby("raio_km"):
        for assinatura in P12.ASSINATURAS:
            col = f"pct_{assinatura}"
            difs = []
            for _, par in g.groupby("campus_de_origem"):
                a = par[par.papel == "placebo_a"][col]
                b = par[par.papel == "placebo_b"][col]
                if a.empty or b.empty or a.isna().all() or b.isna().all():
                    continue
                difs.append(float(a.iloc[0] - b.iloc[0]))
            if not difs:
                continue
            d = np.asarray(difs)
            k, n = int((d > 0).sum()), len(d)
            p_uni = sum(math.comb(n, i) * 0.5**n for i in range(k, n + 1))
            r = real[(real.raio_km == raio) & (real.assinatura == assinatura)]
            linhas.append(
                {
                    "raio_km": raio, "assinatura": assinatura,
                    "placebo_n_pares": n, "placebo_n_positivo": k,
                    "placebo_frac_positivo": round(k / n, 3),
                    "placebo_p_unilateral": round(p_uni, 4),
                    "placebo_excesso_mediano_pp": round(float(np.median(d)), 4),
                    "real_frac_positivo": float(r.frac_positivo.iloc[0]) if not r.empty else np.nan,
                    "real_p_unilateral": float(r.p_unilateral.iloc[0]) if not r.empty else np.nan,
                    "real_excesso_mediano_pp": float(r.excesso_mediano_pp.iloc[0]) if not r.empty else np.nan,
                }
            )
    resumo = pd.DataFrame(linhas)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    print("\n--- placebo vs. real (assinatura principal) ---")
    principal = resumo[resumo.assinatura == "virou_construida"]
    for _, r in principal.iterrows():
        print(f"  raio {r.raio_km} km")
        print(f"    PLACEBO  {r.placebo_n_positivo}/{r.placebo_n_pares} positivos  "
              f"p={r.placebo_p_unilateral:.4f}  mediana {r.placebo_excesso_mediano_pp:+.3f} pp")
        print(f"    REAL     frac {r.real_frac_positivo:.3f}  "
              f"p={r.real_p_unilateral:.4f}  mediana {r.real_excesso_mediano_pp:+.3f} pp")

    # --------------------------------------------------------------- figura
    fig, ax = plt.subplots(figsize=(10, 5))
    largura = 0.35
    x = np.arange(len(principal))
    ax.bar(x - largura / 2, principal.placebo_excesso_mediano_pp, largura,
           label="placebo (dois lugares SEM data center)", color="#95A5A6")
    ax.bar(x + largura / 2, principal.real_excesso_mediano_pp, largura,
           label="real (data center vs. controle)", color="#1A5276")
    for i, (_, r) in enumerate(principal.iterrows()):
        ax.text(i - largura / 2, r.placebo_excesso_mediano_pp,
                f"p={r.placebo_p_unilateral:.2f}", ha="center", va="bottom", fontsize=8)
        ax.text(i + largura / 2, r.real_excesso_mediano_pp,
                f"p={r.real_p_unilateral:.3f}", ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="#333", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r} km" for r in principal.raio_km])
    ax.set_xlabel("raio")
    ax.set_ylabel("excesso mediano de conversão (p.p.)")
    ax.set_title("Passo 19 — teste placebo: o método acha efeito onde não houve data center?\n"
                 "assinatura `virou_construida`", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")


def _latlon_controle(p: pd.Series) -> tuple[float, float]:
    pareamento = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    r = pareamento[pareamento.site_id == p.campus_de_origem].iloc[0]
    return float(r.lat_controle), float(r.lon_controle)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True, choices=["selecao", "classificar", "analise"])
    args = ap.parse_args()
    if args.fase == "selecao":
        fase_selecao()
    elif args.fase == "classificar":
        fase_classificar()
    else:
        fase_analise()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
