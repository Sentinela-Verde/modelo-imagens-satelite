"""Passo 24 — o achado sobrevive a um classificador COMPLETAMENTE diferente?

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_24_validacao_dynamic_world.py --fase baixar
    python dados-modelo-impacto/scripts/impacto_dc_24_validacao_dynamic_world.py --fase analise

## A pergunta

Todo número desta frente vem de **um** classificador: `rf_v1.0-tuned`, treinado com rótulos do
MapBiomas. O passo 19 (placebo) provou que a *estatística* não produz falso positivo, mas não
responde à outra objeção possível: **e se o viés estiver no classificador?**

Este passo refaz a medição com o **Google Dynamic World** — outro classificador, outra fonte de
treino, outra resolução (10 m contra 30 m), produzido por outra equipe. Se o excesso de conversão
no anel reaparecer, é validação cruzada de instrumento, que é muito mais forte que qualquer
p-valor. Se não reaparecer, precisamos saber disso antes de apresentar, não depois.

## Por que o Dynamic World, especificamente

Três razões, e a terceira é a que mais importa:

1. **É global** (10 m, jun/2015 até hoje). O mesmo código serve para o Brasil e para os EUA — é a
   ponte para a expansão da amostra, e não só uma checagem.
2. **É independente de verdade.** Não compartilha rótulo, arquitetura nem equipe com o nosso RF.
3. **Tem uma classe `bare` nativa.** A classe 3 do nosso classificador é a pior (F1 0,579)
   justamente porque o MapBiomas **não tem** classe de canteiro de obras (ADR-004) — os rótulos são
   um proxy de solo nu natural. O DW não tem esse defeito de origem.

## O limite, e quem entra

A série do DW começa em **junho de 2015**. Com a janela `obra-3 .. obra+3`, só campi com obra entre
**2018 e 2022** cabem — **9 dos 15**. É amostra suficiente para a checagem, e não é escolha nossa:
é o que o instrumento permite.

## Uma diferença deliberada

O DW é baixado na resolução **nativa de 10 m**, não reamostrado para os 30 m do nosso raster. As
máscaras de anel e de footprint são recalculadas nessa grade. Isso torna a comparação *menos*
pareada de propósito: se o achado sobrevive a outro sensor, outro classificador **e** outra
resolução, a independência é maior. A contrapartida — pixel misto se comporta diferente em 10 m e
30 m — está declarada na saída.

## Mapeamento DW -> nossas 5 classes

    water(0), flooded_vegetation(3), snow_and_ice(8) -> 5 agua
    trees(1)                                          -> 1 vegetacao_densa
    grass(2), crops(4), shrub_and_scrub(5)            -> 2 vegetacao_rala
    built(6)                                          -> 4 construida_urbana
    bare(7)                                           -> 3 solo_exposto_obras

Saídas:
  - `raw/controles-rf/dw_trajetoria.csv`  — contagens por ponto e raio, com DW
  - `raw/controles-rf/dw_comparacao.csv`  — DW contra `rf_v1.0-tuned`, lado a lado
  - `raw/controles-rf/figuras/fig_17_validacao_dw.png`
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

import ee  # noqa: E402
from sentinela.config import SETTINGS  # noqa: E402
from sentinela.gee import landsat as mod_landsat  # noqa: E402

DIR_DW = C.DIR_SAIDA / "dynamic_world"
RESOLUCAO_DW = 10
DW_ANO_MIN = 2016  # 1o ano cheio; a colecao comeca em jun/2015
RAIOS_KM = [0.5, 1.0, 2.0]
N_PONTA = 2

# DW label -> classe do projeto
REMAP_DW = {0: 5, 1: 1, 2: 2, 3: 5, 4: 2, 5: 2, 6: 4, 7: 3, 8: 5}

SAIDA = C.DIR_SAIDA / "dw_trajetoria.csv"
SAIDA_COMP = C.DIR_SAIDA / "dw_comparacao.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_17_validacao_dw.png"


def campi_elegiveis() -> pd.DataFrame:
    """Campi cuja janela inteira cabe na série do Dynamic World."""
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")].copy()
    par["anos"] = par.ano_inicio_obra.astype(int).map(lambda o: C.janela_anos(o))
    cabe = par[par.anos.map(lambda a: min(a) >= DW_ANO_MIN)]
    return cabe


def _grade_10m(lat: float, lon: float) -> dict:
    return mod_landsat.calcular_grade(lon, lat, C.BUFFER_KM, resolucao_m=RESOLUCAO_DW)


def _baixar_dw(lat: float, lon: float, ano: int, destino: Path) -> bool:
    params = SETTINGS.params()
    grade = _grade_10m(lat, lon)
    aoi = ee.Geometry.Rectangle(
        [grade["origin_x"], grade["origin_y"] - grade["height"] * RESOLUCAO_DW,
         grade["origin_x"] + grade["width"] * RESOLUCAO_DW, grade["origin_y"]],
        proj=mod_landsat.CRS, geodesic=False,
    )
    col = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(aoi)
        .filterDate(f"{ano}-{params['mes_inicio']:02d}-01", f"{ano}-{params['mes_fim']:02d}-30")
        .select("label")
    )
    # moda anual: a classe mais frequente do pixel na estação seca. Para dado categórico é o
    # equivalente do composto mediano que a pipeline usa para reflectância.
    composto = col.mode().unmask(255).toUint8()
    crs_transform = [RESOLUCAO_DW, 0, grade["origin_x"], 0, -RESOLUCAO_DW, grade["origin_y"]]

    def _url() -> str:
        return composto.getDownloadURL({
            "crs": mod_landsat.CRS, "crsTransform": crs_transform,
            "dimensions": f"{grade['width']}x{grade['height']}",
            "region": aoi, "format": "GEO_TIFF",
        })

    url = mod_landsat._com_retry(_url)
    for t in range(4):
        r = requests.get(url, timeout=300)
        if r.status_code == 200:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(r.content)
            return True
        time.sleep(10 * (t + 1))
    return False


def fase_baixar() -> None:
    cabe = campi_elegiveis()
    C.iniciar_ee()
    print(f"{len(cabe)} campi cabem na serie do Dynamic World (obra >= {DW_ANO_MIN + 3})")
    total = 0
    for _, r in cabe.iterrows():
        for pid, lat, lon in ((r.site_id, float(r.lat), float(r.lon)),
                              (r.site_id_controle, float(r.lat_controle), float(r.lon_controle))):
            for ano in r.anos:
                destino = DIR_DW / pid / f"{ano}.tif"
                if destino.exists():
                    continue
                ok = _baixar_dw(lat, lon, ano, destino)
                print(f"  {'OK ' if ok else 'FALHOU'} {pid}/{ano}")
                total += ok
    print(f"\n{total} rasters DW baixados")


def _mascaras_raio(caminho: Path, lat: float, lon: float) -> dict[float, np.ndarray]:
    """Máscaras de disco na grade do próprio raster (10 m aqui, não 30 m)."""
    with rasterio.open(caminho) as src:
        transform, largura, altura, crs = src.transform, src.width, src.height, src.crs
    cols = np.arange(largura, dtype=float) + 0.5
    lins = np.arange(altura, dtype=float) + 0.5
    x = transform.c + cols * transform.a
    y = transform.f + lins * transform.e
    mx, my = np.meshgrid(x, y)
    para_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lons, lats = para_wgs.transform(mx, my)
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    _, _, dist = geod.inv(np.full_like(lons, lon), np.full_like(lats, lat), lons, lats)
    return {r: dist <= r * 1000 for r in RAIOS_KM}


def _empilhar_dw(pid: str, anos: list[int]) -> np.ndarray | None:
    pilha = []
    for ano in anos:
        p = DIR_DW / pid / f"{ano}.tif"
        if not p.exists():
            return None
        with rasterio.open(p) as src:
            arr = src.read(1)
        remap = np.zeros_like(arr, dtype=np.uint8)
        for origem, destino in REMAP_DW.items():
            remap[arr == origem] = destino
        pilha.append(remap)  # 0 = invalido (era 255)
    return np.stack(pilha)


def _assinaturas(pilha: np.ndarray, mascara: np.ndarray) -> dict:
    """Mesma definição do passo 12: não-construída nos 2 primeiros, construída nos 2 últimos."""
    valido = np.all(pilha > 0, axis=0) & mascara
    nao_constr_inicio = np.all(pilha[:N_PONTA] != 4, axis=0)
    constr_fim = np.all(pilha[-N_PONTA:] == 4, axis=0)
    era_veg = np.all(np.isin(pilha[:N_PONTA], (1, 2)), axis=0)
    passou_solo = np.any(pilha[N_PONTA:-N_PONTA] == 3, axis=0) if pilha.shape[0] > 2 * N_PONTA \
        else np.zeros_like(valido)
    return {
        "pixels_validos_mascara": int(valido.sum()),
        "virou_construida": int((nao_constr_inicio & constr_fim & valido).sum()),
        "virou_construida_via_solo": int((nao_constr_inicio & constr_fim & passou_solo & valido).sum()),
        "vegetacao_para_construida": int((era_veg & constr_fim & valido).sum()),
    }


def fase_analise() -> None:
    cabe = campi_elegiveis()
    registros = []
    for _, r in cabe.iterrows():
        anos = r.anos
        for tipo, pid, lat, lon in (
            ("tratamento", r.site_id, float(r.lat), float(r.lon)),
            ("controle", r.site_id_controle, float(r.lat_controle), float(r.lon_controle)),
        ):
            pilha = _empilhar_dw(pid, anos)
            if pilha is None:
                print(f"  ! {pid}: faltam anos de DW, par fora")
                registros = [x for x in registros if x["campus"] != r.site_id]
                break
            raios = _mascaras_raio(DIR_DW / pid / f"{anos[0]}.tif", lat, lon)
            for raio in RAIOS_KM:
                cont = _assinaturas(pilha, raios[raio])
                n = cont["pixels_validos_mascara"]
                registros.append({
                    "campus": r.site_id, "site_id": pid, "tipo": tipo, "raio_km": raio,
                    "resolucao_m": RESOLUCAO_DW, "classificador": "dynamic_world",
                    "ano_inicio": anos[0], "ano_fim": anos[-1], **cont,
                    **{f"pct_{a}": (100.0 * cont[a] / n if n else np.nan)
                       for a in ("virou_construida", "virou_construida_via_solo",
                                 "vegetacao_para_construida")},
                })
            print(f"  {pid} ({tipo}) ok")

    dw = pd.DataFrame(registros)
    C.salvar_csv(dw, SAIDA)

    # ---------------------------------------------------------------- DW vs. rf_v1.0-tuned
    rf = pd.read_csv(C.DIR_SAIDA / "trajetoria_pixel.csv")
    campi_dw = set(dw.campus.unique())
    linhas = []
    for raio in RAIOS_KM:
        for assin in ("virou_construida", "vegetacao_para_construida"):
            col = f"pct_{assin}"
            for nome, tab, chave in (("dynamic_world", dw, "campus"),
                                     ("rf_v1.0-tuned", rf, "pareado_com")):
                g = tab[(tab.raio_km == raio) & (tab[chave].isin(campi_dw))]
                difs = []
                for _, par in g.groupby(chave):
                    t = par[par.tipo == "tratamento"][col]
                    c = par[par.tipo == "controle"][col]
                    if t.empty or c.empty or t.isna().all() or c.isna().all():
                        continue
                    difs.append(float(t.iloc[0] - c.iloc[0]))
                if not difs:
                    continue
                d = np.asarray(difs)
                n, k = len(d), int((d > 0).sum())
                p = sum(math.comb(n, i) * 0.5**n for i in range(k, n + 1))
                linhas.append({
                    "classificador": nome, "raio_km": raio, "assinatura": assin,
                    "n_pares": n, "n_positivo": k, "frac_positivo": round(k / n, 3),
                    "p_unilateral": round(p, 4),
                    "excesso_mediano_pp": round(float(np.median(d)), 4),
                })
    comp = pd.DataFrame(linhas)
    C.salvar_csv(comp, SAIDA_COMP)

    # ---------------------------------------------------------------- figura
    prin = comp[comp.assinatura == "virou_construida"]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    x = np.arange(len(RAIOS_KM))
    larg = 0.36
    for i, (nome, cor) in enumerate((("rf_v1.0-tuned", "#1A5276"),
                                     ("dynamic_world", "#E67E22"))):
        s = prin[prin.classificador == nome].sort_values("raio_km")
        ax.bar(x + (i - 0.5) * larg, s.excesso_mediano_pp, larg,
               label=f"{nome} ({'30 m' if i == 0 else '10 m'})", color=cor)
        for j, (_, r0) in enumerate(s.iterrows()):
            ax.text(j + (i - 0.5) * larg, r0.excesso_mediano_pp,
                    f"{int(r0.n_positivo)}/{int(r0.n_pares)}\np={r0.p_unilateral:.3f}",
                    ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="#333", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r} km" for r in RAIOS_KM])
    ax.set_xlabel("raio")
    ax.set_ylabel("excesso mediano de conversão vs. controle (p.p.)")
    ax.set_title("Passo 24 — validação cruzada de instrumento\n"
                 "o mesmo achado, medido por dois classificadores independentes "
                 f"(n={len(campi_dw)} campi que cabem na série do DW)", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print(f"\n--- DW vs rf_v1.0-tuned, nos mesmos {len(campi_dw)} campi ---")
    for raio in RAIOS_KM:
        print(f"  raio {raio} km")
        for _, r0 in prin[prin.raio_km == raio].iterrows():
            print(f"    {r0.classificador:16s} {int(r0.n_positivo)}/{int(r0.n_pares)}  "
                  f"p={r0.p_unilateral:.4f}  mediana {r0.excesso_mediano_pp:+.3f} pp")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True, choices=["baixar", "analise"])
    args = ap.parse_args()
    fase_baixar() if args.fase == "baixar" else fase_analise()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
