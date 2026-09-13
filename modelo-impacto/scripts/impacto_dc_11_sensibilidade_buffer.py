"""Passo 11 — teste de sensibilidade ao raio do buffer: em que escala o sinal de obra aparece?

Rode com:

    python modelo-impacto/scripts/impacto_dc_11_sensibilidade_buffer.py

## A pergunta

No buffer de 5 km, o efeito de obra medido (diferença-em-diferenças da classe "solo exposto") tem
magnitude da mesma ordem da variação interanual **antes de a obra começar**. A suspeita inicial era
aritmética: o whitespace construído destes data centers vai de **0,2 a 2,3 ha** e o buffer de 5 km
tem **7.854 ha** — 0,003% a 0,03% da área medida. Mesmo um campus inteiro de 20 ha seria 0,25%. Se
o objeto for pequeno demais para a janela, encolher a janela deveria fazer o sinal emergir.

Este script testa isso em seis raios, de 0,5 a 5 km.

## A resposta: não

Em nenhum raio testado o sinal se distingue de acaso. A fração de pares em que o tratamento sobe
mais que o controle fica entre 0,40 e 0,53 para "solo exposto" — cara ou coroa — e nenhum p-valor
sobrevive. **Encolher o buffer não resolve; o problema não é a escala da janela.**

`construida_urbana` é o único caso com tendência consistente na direção esperada (0,60 a 0,67 dos
pares, DiD mediano positivo em todos os raios de 1 km para cima), mas com N=15 isso dá p entre 0,30
e 0,61 — seria preciso 12 de 15 para cruzar 0,05. É uma pista, não um achado.

**Atenção ao p=0,035** que aparece em `solo_exposto_obras` a 5 km: ele é (a) na direção CONTRÁRIA
(só 3 de 15 pares positivos, ou seja, o tratamento sobe MENOS que o controle) e (b) um entre 18
combinações testadas (3 classes x 6 raios) — exatamente o que se espera do acaso nesse volume de
testes. Não é evidência de nada.

## Por que "razão efeito/ruído" seria a métrica errada

A primeira versão deste script comparava a mediana de |efeito| com a mediana do ruído. Isso é
enganoso: |efeito| é sempre positivo, então ruído puro produz razões acima de 1 com facilidade — e
de fato produziu "sinal emerge a partir de 3 km" a partir de dados sem sinal nenhum. O que separa
efeito real de ruído é a **direção**, não a magnitude, e é por isso que o veredito aqui vem de um
teste de sinal.

## Por que isto NÃO precisa reingerir nada

Todas as etapas do pipeline são **por pixel**: o composto mediano da estação seca, a harmonização
Landsat/Sentinel-2, os 7 índices e a inferência do Random Forest. Nenhuma delas olha para os
vizinhos nem para a extensão da AOI. Logo, o valor de classe de um pixel a 800 m do data center é
o mesmo se ele foi processado dentro de uma AOI de 1 km ou de 5 km.

Recortar o raster já classificado no círculo interno de raio `r` é, portanto, **idêntico** a ter
ingerido com `buffer_km=r`, e não aproximadamente idêntico. De quebra é melhor para comparar: a
grade de pixels fica fixa entre os raios, então nenhuma diferença medida vem de realinhamento de
grade (uma ingestão nova em 1 km teria origem de grade própria, com deslocamento sub-pixel).

## Máscara geodésica, não planar

Os rasters estão todos em EPSG:31983 (UTM 23S), inclusive Manaus e Fortaleza, que ficam muito fora
dessa zona — ali a escala do plano projetado distorce. Por isso a distância de cada pixel ao centro
é calculada em **geodésia WGS84 exata** (`pyproj.Geod`), reprojetando os centros de pixel de volta
para lat/lon, e não com distância euclidiana no plano. A máscara é calculada uma vez por ponto (a
grade é a mesma em todos os anos daquele ponto) e reusada.

Saídas:
  - `raw/controles-rf/sensibilidade_buffer.csv` — área/proporção por classe, por ponto, ano e raio
  - `raw/controles-rf/sensibilidade_buffer_resumo.csv` — teste de sinal, efeito e ruído por raio
  - `raw/controles-rf/figuras/fig_06_sensibilidade_buffer.png`
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
from pyproj import Geod, Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C

RAIOS_KM = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]
CLASSE_FOCO = "solo_exposto_obras"
CLASSES_REPORTADAS = ["solo_exposto_obras", "construida_urbana", "vegetacao_densa"]

SAIDA_LONGO = C.DIR_SAIDA / "sensibilidade_buffer.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "sensibilidade_buffer_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_06_sensibilidade_buffer.png"

_geod = Geod(ellps="WGS84")


def grade_distancia_km(tif_path: Path, lat: float, lon: float) -> np.ndarray:
    """Distância geodésica em km de cada pixel do raster até (lat, lon).

    Depende só da grade do raster (origem, resolução, tamanho), que é idêntica em todos os anos
    de um mesmo ponto/sensor — por isso é calculada uma vez e reusada.

    Era o miolo de `mascaras_por_raio` e não tinha nome próprio. Ganhou um quando o passo 40
    passou a precisar da distância **contínua** (como feature por pixel), não do recorte em
    anéis: sem isso, o passo 40 chamava uma função que não existia e sua fase `dataset` não
    reproduzia.
    """
    with rasterio.open(tif_path) as src:
        transform, largura, altura, crs = src.transform, src.width, src.height, src.crs

    # Centro de cada pixel direto pela affine. Os rasters são north-up e sem rotação
    # (`rasterio.transform.from_origin` em `sentinela.gee.landsat.calcular_grade`), então
    # x = origem_x + (col+0.5)*passo_x e y = origem_y + (lin+0.5)*passo_y — com passo_y negativo.
    colunas = np.arange(largura, dtype=float) + 0.5
    linhas = np.arange(altura, dtype=float) + 0.5
    x = transform.c + colunas * transform.a
    y = transform.f + linhas * transform.e
    malha_x, malha_y = np.meshgrid(x, y)

    para_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lons, lats = para_wgs.transform(malha_x.ravel(), malha_y.ravel())
    _, _, dist_m = _geod.inv(
        np.full(lons.shape, lon), np.full(lats.shape, lat), np.asarray(lons), np.asarray(lats)
    )
    return (dist_m / 1000.0).reshape(altura, largura)


def mascaras_por_raio(tif_path: Path, lat: float, lon: float) -> dict[float, np.ndarray]:
    """{raio_km: máscara booleana} dos pixels a até `raio_km` do centro, por geodésia exata."""
    dist_km = grade_distancia_km(tif_path, lat, lon)
    return {r: dist_km <= r for r in RAIOS_KM}


def medir_ponto(linha_painel: pd.Series, mascaras: dict[float, np.ndarray]) -> list[dict[str, Any]]:
    tif = C.caminho_classificado(linha_painel["sensor"], linha_painel["site_id"], int(linha_painel["ano"]))
    with rasterio.open(tif) as src:
        arr = src.read(1)
    # A máscara é calculada uma vez por ponto e reusada em todos os anos, o que só vale porque
    # `calcular_grade` depende só de (lon, lat, buffer_km, resolução) — nunca do ano. Se algum ano
    # divergir, é sinal de que a grade mudou e a reutilização estaria comparando recortes
    # diferentes: falha alto em vez de produzir número errado em silêncio.
    esperado = next(iter(mascaras.values())).shape
    if arr.shape != esperado:
        raise RuntimeError(
            f"{tif} tem grade {arr.shape}, mas a máscara do ponto foi montada em {esperado} — "
            "grade inconsistente entre anos do mesmo ponto."
        )

    resolucao = float(linha_painel["resolucao_m"])
    saida = []
    for raio, mascara in mascaras.items():
        recorte = arr[mascara]
        valores, contagens = np.unique(recorte, return_counts=True)
        contagem = dict(zip(valores.tolist(), contagens.tolist(), strict=True))
        pixels = {cid: int(contagem.get(cid, 0)) for cid in C.CLASS_IDS}
        total = sum(pixels.values())
        registro: dict[str, Any] = {
            "site_id": linha_painel["site_id"], "tipo": linha_painel["tipo"],
            "pareado_com": linha_painel["pareado_com"], "ano": int(linha_painel["ano"]),
            "fase": linha_painel["fase"], "sensor": linha_painel["sensor"],
            "raio_km": raio, "area_buffer_ha": round(np.pi * raio**2 * 100, 2),
            "pixels_validos": total,
        }
        for cid in C.CLASS_IDS:
            nome = C.CLASSE_NOME[cid]
            registro[f"area_ha_{nome}"] = round(pixels[cid] * resolucao * resolucao / 10_000.0, 4)
            registro[f"prop_{nome}"] = round(pixels[cid] / total, 6) if total else np.nan
        saida.append(registro)
    return saida


def p_binomial_bilateral(sucessos: int, n: int) -> float:
    """p-valor exato bilateral de um teste de sinal contra p=0,5.

    Implementado com `math.comb` em vez de `scipy.stats.binomtest` porque scipy não está em
    `requirements.txt` — não vale acrescentar uma dependência ao projeto por uma função de cinco
    linhas. Sob p=0,5 a binomial é simétrica, então o bilateral é 2x a cauda do lado mais extremo.
    """
    if n == 0:
        return float("nan")
    k = max(sucessos, n - sucessos)
    cauda = sum(math.comb(n, i) for i in range(k, n + 1)) / (2**n)
    return min(1.0, 2 * cauda)


def resumir(longo: pd.DataFrame) -> pd.DataFrame:
    """Por raio e classe: o TESTE DE SINAL, mais o tamanho do efeito e do ruído como contexto.

    - **efeito** = diferença-em-diferenças: (durante − pré) do tratamento menos o mesmo do
      controle. É o que um desenho de impacto atribuiria à obra.
    - **ruído** = desvio-padrão da série do TRATAMENTO nos anos pré-obra: quanto a medida varia
      sozinha, sem obra nenhuma acontecendo.

    **O veredito vem do teste de sinal, não da razão efeito/ruído.** Comparar a mediana de
    |efeito| com a mediana do ruído é enganoso: |efeito| é sempre positivo, então ruído puro
    produz razões acima de 1 com facilidade — foi o que aconteceu na primeira versão deste
    script, que chegou a "sinal emerge a partir de 3 km" a partir de dados sem sinal nenhum. O que
    distingue efeito real de ruído é a **direção**: se a obra expõe solo, o tratamento tem que
    subir mais que o controle na MAIORIA dos pares. `frac_positivo` mede isso, e
    `p_binomial` diz se a fração se distingue de cara-ou-coroa.
    """
    linhas = []
    for raio, g_raio in longo.groupby("raio_km"):
        for classe in CLASSES_REPORTADAS:
            col_area, col_prop = f"area_ha_{classe}", f"prop_{classe}"
            dids_pp, efeitos_ha, efeitos_pp, ruidos_ha, ruidos_pp = [], [], [], [], []
            for _, par in g_raio.groupby("pareado_com"):
                dif = {}
                for tipo in ("tratamento", "controle"):
                    s = par[par["tipo"] == tipo]
                    pre, dur = s[s["fase"] == "pre"], s[s["fase"] == "durante"]
                    if pre.empty or dur.empty:
                        dif = {}
                        break
                    dif[tipo] = (dur[col_area].mean() - pre[col_area].mean(),
                                 dur[col_prop].mean() - pre[col_prop].mean())
                if not dif:
                    continue
                did_pp = (dif["tratamento"][1] - dif["controle"][1]) * 100
                dids_pp.append(did_pp)
                efeitos_ha.append(abs(dif["tratamento"][0] - dif["controle"][0]))
                efeitos_pp.append(abs(did_pp))
                pre_trat = par[(par["tipo"] == "tratamento") & (par["fase"] == "pre")]
                if len(pre_trat) > 1:
                    ruidos_ha.append(pre_trat[col_area].std())
                    ruidos_pp.append(pre_trat[col_prop].std() * 100)
            if not dids_pp or not ruidos_ha:
                continue
            n = len(dids_pp)
            positivos = int(sum(1 for v in dids_pp if v > 0))
            ef_ha, ru_ha = float(np.median(efeitos_ha)), float(np.median(ruidos_ha))
            ef_pp, ru_pp = float(np.median(efeitos_pp)), float(np.median(ruidos_pp))
            linhas.append({
                "raio_km": raio, "classe": classe,
                "area_buffer_ha": round(np.pi * raio**2 * 100, 1),
                "n_pares": n,
                "n_did_positivo": positivos,
                "frac_positivo": round(positivos / n, 3),
                "p_binomial": round(p_binomial_bilateral(positivos, n), 4),
                "did_mediano_pp": round(float(np.median(dids_pp)), 4),
                "efeito_absoluto_mediano_ha": round(ef_ha, 3),
                "ruido_pre_obra_mediano_ha": round(ru_ha, 3),
                "efeito_absoluto_mediano_pp": round(ef_pp, 4),
                "ruido_pre_obra_mediano_pp": round(ru_pp, 4),
            })
    return pd.DataFrame(linhas)


def desenhar(resumo: pd.DataFrame, destino: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    cores = {"solo_exposto_obras": "#F5A623", "construida_urbana": "#C0392B",
             "vegetacao_densa": "#1B5E20"}

    ax = axes[0]
    for classe, g in resumo.groupby("classe"):
        g = g.sort_values("raio_km")
        ax.plot(g["raio_km"], g["frac_positivo"], "o-", linewidth=2.2, markersize=7,
                color=cores.get(classe, "#5D6D7E"), label=classe)
    ax.axhline(0.5, color="gray", linestyle="--", linewidth=1.4)
    ax.annotate("0,5 = cara ou coroa", (resumo["raio_km"].max(), 0.5),
                xytext=(-6, 8), textcoords="offset points", ha="right", fontsize=9, color="dimgray")
    ax.set_ylim(0, 1)
    ax.set_xlabel("Raio do buffer (km)")
    ax.set_ylabel("fração dos pares em que o tratamento sobe mais que o controle")
    ax.set_title("Teste de sinal — a obra empurra a classe para cima?\n"
                 "longe de 0,5 seria sinal; em cima de 0,5 é acaso", fontsize=11.5)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(alpha=0.25)

    ax2 = axes[1]
    foco = resumo[resumo["classe"] == CLASSE_FOCO].sort_values("raio_km")
    ax2.plot(foco["raio_km"], foco["efeito_absoluto_mediano_pp"], "o-", color="#F5A623",
             linewidth=2.4, markersize=7, label="|efeito| medido (diff-in-diff)")
    ax2.plot(foco["raio_km"], foco["ruido_pre_obra_mediano_pp"], "s--", color="#5D6D7E",
             linewidth=2.4, markersize=6, label="ruído interanual pré-obra")
    ax2.set_xlabel("Raio do buffer (km)")
    ax2.set_ylabel("pontos percentuais da área do buffer")
    ax2.set_title(f"Classe crítica ({CLASSE_FOCO})\nefeito e ruído lado a lado", fontsize=11.5)
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.25)

    fig.suptitle(
        "Em que raio o sinal de obra aparece? — teste de sensibilidade de buffer\n"
        "resposta: em nenhum dos testados",
        fontsize=13, y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")


def main() -> int:
    painel = pd.read_csv(C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv")
    print(f"Passo 11 — {len(painel)} ponto-ano x {len(RAIOS_KM)} raios "
          f"({', '.join(str(r) for r in RAIOS_KM)} km), sem rede")

    registros: list[dict[str, Any]] = []
    for (site_id, sensor), grupo in painel.groupby(["site_id", "sensor"]):
        primeiro = grupo.iloc[0]
        tif = C.caminho_classificado(sensor, site_id, int(primeiro["ano"]))
        mascaras = mascaras_por_raio(tif, float(primeiro["lat"]), float(primeiro["lon"]))
        for _, linha in grupo.iterrows():
            registros.extend(medir_ponto(linha, mascaras))
        print(f"  {site_id} ({sensor}): {len(grupo)} anos")

    longo = pd.DataFrame(registros).sort_values(["pareado_com", "tipo", "raio_km", "ano"])
    C.salvar_csv(longo.reset_index(drop=True), SAIDA_LONGO)

    resumo = resumir(longo)
    C.salvar_csv(resumo, SAIDA_RESUMO)
    desenhar(resumo, SAIDA_FIGURA)

    print()
    foco = resumo[resumo["classe"] == CLASSE_FOCO].sort_values("raio_km")
    print(f"Classe crítica ({CLASSE_FOCO}) — {int(foco['n_pares'].iloc[0])} pares:")
    print(f"{'raio':>6} {'área (ha)':>11} {'did>0':>9} {'fração':>8} {'p':>8} "
          f"{'|efeito| pp':>12} {'ruído pp':>10}")
    for _, r in foco.iterrows():
        did = f"{int(r['n_did_positivo'])}/{int(r['n_pares'])}"
        print(f"{r['raio_km']:>5.1f}k {r['area_buffer_ha']:>11.0f} {did:>9} "
              f"{r['frac_positivo']:>8.2f} {r['p_binomial']:>8.3f} "
              f"{r['efeito_absoluto_mediano_pp']:>12.4f} {r['ruido_pre_obra_mediano_pp']:>10.4f}")

    significativos = foco[(foco["p_binomial"] < 0.05) & (foco["frac_positivo"] > 0.5)]
    if len(significativos):
        r = significativos.sort_values("raio_km").iloc[0]
        print(f"\nO sinal aparece a partir de {r['raio_km']} km "
              f"(fração {r['frac_positivo']:.2f}, p={r['p_binomial']:.3f}).")
    else:
        print("\nACHADO: em NENHUM raio de 0,5 a 5 km o sinal de obra se distingue de acaso.")
        print("A fração de pares em que o tratamento sobe mais que o controle fica em torno de 0,5")
        print("em toda a faixa, e nenhum p-valor sobrevive. Reduzir o buffer NÃO resolve — o")
        print("problema não é a escala da janela, é não haver sinal detectável nesta medida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
