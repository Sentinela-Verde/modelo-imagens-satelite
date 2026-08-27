"""Passo 3 do spike SV-02b: mede o resíduo real entre Landsat e Sentinel-2 harmonizados.

Rode com: python -m sentinela.gee.medir_residuo_harmonizacao --site ascenty-vinhedo

Gera o composto sazonal (jun-set) dos anos de sobreposição (2019-2021, `config/params.yml`) pelos
dois sensores, agrega o Sentinel-2 para a grade Landsat de 30 m (só para esta comparação — a
ingestão de produção mantém cada era na resolução nativa, ver ADR-003), amostra pontos pareados na
AOI e calcula viés, RMSE e R² por banda e para NDVI/BSI/NDBI — com e sem o ajuste de bandpass, para
também servir de checagem de sanidade invertida (cenário 5 do spike). Salva um scatter plot por
banda em `reports/figures/harmonizacao/` e imprime a tabela de resíduo usada no ADR-003.

Não escreve nenhum raster/artefato de produção — é só o instrumento de medição do spike.
"""

from __future__ import annotations

import argparse
import sys

import ee
import numpy as np
import pandas as pd

from ..config import REPO_ROOT, SETTINGS, ConfigError
from .auth import init_ee
from .harmonizacao import (
    bandas_harmonizadas,
    harmonizar_landsat,
    harmonizar_s2,
    mascara_nuvem,
)

N_AMOSTRAS = 1500
SEED = 42  # seed fixo do projeto (config/params.yml)


def _load_site(site_id: str) -> dict:
    import geopandas as gpd

    sites_path = REPO_ROOT / "config" / "sites.geojson"
    gdf = gpd.read_file(sites_path)
    row = gdf[gdf["site_id"] == site_id]
    if row.empty:
        raise SystemExit(f"site_id '{site_id}' não encontrado em {sites_path}.")
    r = row.iloc[0]
    return {"site_id": site_id, "lat": float(r["lat"]), "lon": float(r["lon"]), "buffer_km": float(r["buffer_km"])}


def _adicionar_indices(img: ee.Image) -> ee.Image:
    """NDVI, BSI (Rikimaru et al. 2002) e NDBI (Zha et al. 2003) a partir das bandas canônicas."""
    ndvi = img.normalizedDifference(["nir", "red"]).rename("ndvi")
    ndbi = img.normalizedDifference(["swir1", "nir"]).rename("ndbi")
    bsi = (
        img.select("swir1")
        .add(img.select("red"))
        .subtract(img.select("nir").add(img.select("blue")))
        .divide(
            img.select("swir1")
            .add(img.select("red"))
            .add(img.select("nir"))
            .add(img.select("blue"))
        )
        .rename("bsi")
    )
    return img.addBands([ndvi, ndbi, bsi])


def _composto_landsat(aoi: ee.Geometry, ano_ini: int, ano_fim: int, mes_ini: int, mes_fim: int) -> ee.Image:
    def _prep(img: ee.Image) -> ee.Image:
        return harmonizar_landsat(mascara_nuvem(img, "landsat"))

    l8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
    l9 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
    colecao = (
        l8.merge(l9)
        .filterBounds(aoi)
        .filterDate(f"{ano_ini}-01-01", f"{ano_fim}-12-31")
        .filter(ee.Filter.calendarRange(mes_ini, mes_fim, "month"))
        .map(_prep)
    )
    proj = colecao.first().select("blue").projection()
    composto = colecao.median().setDefaultProjection(proj)
    return _adicionar_indices(composto)


def _composto_s2(
    aoi: ee.Geometry, ano_ini: int, ano_fim: int, mes_ini: int, mes_fim: int, aplicar_bandpass: bool
) -> ee.Image:
    def _prep(img: ee.Image) -> ee.Image:
        return harmonizar_s2(mascara_nuvem(img, "sentinel2"), aplicar_bandpass=aplicar_bandpass)

    colecao = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(f"{ano_ini}-01-01", f"{ano_fim}-12-31")
        .filter(ee.Filter.calendarRange(mes_ini, mes_fim, "month"))
        .map(_prep)
    )
    proj = colecao.first().select("blue").projection()
    composto = colecao.median().setDefaultProjection(proj)
    return _adicionar_indices(composto)


def _amostrar_pares(
    landsat: ee.Image, s2_30m: ee.Image, aoi: ee.Geometry, colunas: list[str]
) -> pd.DataFrame:
    landsat_renom = landsat.select(colunas, [f"l_{c}" for c in colunas])
    s2_renom = s2_30m.select(colunas, [f"s_{c}" for c in colunas])
    stack = landsat_renom.addBands(s2_renom)

    amostra = stack.sample(
        region=aoi,
        scale=30,
        numPixels=N_AMOSTRAS,
        seed=SEED,
        geometries=False,
        dropNulls=True,
    )
    feats = amostra.getInfo()["features"]
    linhas = [f["properties"] for f in feats]
    return pd.DataFrame(linhas)


def _estatisticas(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    linhas = []
    for c in colunas:
        x = df[f"l_{c}"].to_numpy(dtype=float)  # Landsat = referência
        y = df[f"s_{c}"].to_numpy(dtype=float)  # Sentinel-2 = comparado
        diff = y - x
        vies = float(np.mean(diff))
        desvio = float(np.std(diff))
        rmse = float(np.sqrt(np.mean(diff**2)))
        if np.std(x) > 0 and np.std(y) > 0:
            r2 = float(np.corrcoef(x, y)[0, 1] ** 2)
        else:
            r2 = float("nan")
        linhas.append(
            {"variavel": c, "n": len(x), "vies": vies, "desvio": desvio, "rmse": rmse, "r2": r2}
        )
    return pd.DataFrame(linhas)


def _scatter(df: pd.DataFrame, colunas_bandas: list[str], out_dir) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    for c in colunas_bandas:
        x = df[f"l_{c}"].to_numpy(dtype=float)
        y = df[f"s_{c}"].to_numpy(dtype=float)
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.scatter(x, y, s=4, alpha=0.3)
        lo, hi = float(min(x.min(), y.min())), float(max(x.max(), y.max()))
        ax.plot([lo, hi], [lo, hi], "r--", linewidth=1, label="1:1")
        ax.set_xlabel(f"Landsat (referência) — {c}")
        ax.set_ylabel(f"Sentinel-2 (harmonizado) — {c}")
        ax.set_title(f"Resíduo Landsat x Sentinel-2 — {c}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / f"scatter_{c}.png", dpi=150)
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mede o resíduo Landsat x Sentinel-2 (SV-02b).")
    parser.add_argument("--site", required=True, help="site_id de config/sites.geojson")
    args = parser.parse_args()

    try:
        init_ee()
    except ConfigError as e:
        print(f"ERRO DE CONFIGURAÇÃO:\n{e}", file=sys.stderr)
        return 1

    site = _load_site(args.site)
    ponto = ee.Geometry.Point(site["lon"], site["lat"])
    aoi = ponto.buffer(site["buffer_km"] * 1000)

    params = SETTINGS.params()
    faixa_a = params["faixa_a"]
    anos_sobrep = faixa_a["anos_sobreposicao"]
    ano_ini, ano_fim = min(anos_sobrep), max(anos_sobrep)
    mes_ini, mes_fim = params["mes_inicio"], params["mes_fim"]

    print(f"Site: {site['site_id']} | anos de sobreposição: {anos_sobrep} | janela: {mes_ini}-{mes_fim}")

    colunas_bandas = bandas_harmonizadas()
    colunas_indices = ["ndvi", "ndbi", "bsi"]
    todas_colunas = colunas_bandas + colunas_indices

    landsat = _composto_landsat(aoi, ano_ini, ano_fim, mes_ini, mes_fim)

    resultados = {}
    for aplicar_bandpass in (True, False):
        s2 = _composto_s2(aoi, ano_ini, ano_fim, mes_ini, mes_fim, aplicar_bandpass=aplicar_bandpass)
        s2_30m = s2.reduceResolution(ee.Reducer.mean(), maxPixels=1024).reproject(landsat.select("blue").projection())
        df = _amostrar_pares(landsat, s2_30m, aoi, todas_colunas)
        stats = _estatisticas(df, todas_colunas)
        resultados[aplicar_bandpass] = (df, stats)
        tag = "COM ajuste de bandpass" if aplicar_bandpass else "SEM ajuste de bandpass (sanidade invertida)"
        print(f"\n=== {tag} — n amostras pareadas: {len(df)} ===")
        print(stats.to_string(index=False))

    df_com, stats_com = resultados[True]
    out_dir = REPO_ROOT / "reports" / "figures" / "harmonizacao"
    _scatter(df_com, colunas_bandas, out_dir)
    print(f"\nScatter plots salvos em {out_dir}")

    tolerancia_ok = bool(
        (stats_com.loc[stats_com["variavel"].isin(colunas_bandas), "vies"].abs() < 0.02).all()
        and (stats_com.loc[stats_com["variavel"].isin(colunas_bandas), "r2"] > 0.85).all()
    )
    print(f"\nTolerância do spike (|viés|<0.02 e R²>0.85, por banda, COM ajuste): {'OK' if tolerancia_ok else 'NÃO atingida'}")

    stats_com.to_csv(out_dir / "tabela_residuo.csv", index=False)
    print(f"Tabela de resíduo salva em {out_dir / 'tabela_residuo.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
