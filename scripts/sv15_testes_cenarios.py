"""Script ad-hoc — cenários de teste de SV-15 sobre o CSV/GeoJSON regenerados com rf_v1.0-tuned."""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd

from sentinela.config import REPO_ROOT

CSV_PATH = REPO_ROOT / "outputs" / "indicadores" / "area_por_classe.csv"


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    print(f"CSV: {len(df)} linhas, {df['site_id'].nunique()} sites.")

    # 1. soma de pct_area_valida == 100 por grupo
    soma = df.groupby(["site_id", "ano", "sensor"])["pct_area_valida"].sum()
    fora = soma[(soma - 100.0).abs() > 0.01]
    print(f"\n[1] soma pct_area_valida fora da tolerância: {len(fora)} grupo(s) (esperado 0)")
    if len(fora):
        print(fora.head(10))

    # 2. area_ha == area_m2/10000
    diff_ha = (df["area_ha"] - df["area_m2"] / 10000.0).abs()
    print(f"[2] max |area_ha - area_m2/10000|: {diff_ha.max():.10f} (esperado ~0)")

    # 3. pixels_validos * resolucao_m^2 == soma area_m2 do grupo
    grp = df.groupby(["site_id", "ano", "sensor"]).agg(
        pixels_validos=("pixels_validos", "first"),
        resolucao_m=("resolucao_m", "first"),
        soma_area_m2=("area_m2", "sum"),
    )
    grp["esperado_m2"] = grp["pixels_validos"] * grp["resolucao_m"] ** 2
    grp["diff"] = (grp["esperado_m2"] - grp["soma_area_m2"]).abs()
    fora_coerencia = grp[grp["diff"] > 1.0]
    print(f"[3] grupos com pixels_validos*resolucao^2 != soma(area_m2): {len(fora_coerencia)} (esperado 0)")
    if len(fora_coerencia):
        print(fora_coerencia.head(10))

    # 4. sensor / resolucao_m preenchidos em 100%
    n_sensor_vazio = df["sensor"].isna().sum()
    n_resolucao_vazio = df["resolucao_m"].isna().sum()
    print(f"[4] linhas sem sensor: {n_sensor_vazio}, sem resolucao_m: {n_resolucao_vazio} (esperado 0, 0)")

    # 5. contagem esperada: 256 combos * 5 classes = 1280
    print(f"[5] linhas totais: {len(df)} (esperado 1280)")

    # 6. modelo_versao == rf_v1.0-tuned em 100% das linhas
    versoes = df["modelo_versao"].unique()
    print(f"[6] modelo_versao únicos no CSV: {list(versoes)} (esperado só ['rf_v1.0-tuned'])")

    # 7. GeoJSON de amostra abre em EPSG:4326 e sobre o site certo
    amostra = REPO_ROOT / "outputs" / "indicadores" / "classes_ascenty-vinhedo_2025_sentinel2.geojson"
    gdf = gpd.read_file(amostra)
    print(f"\n[7] {amostra.name}: crs={gdf.crs}, n_features={len(gdf)}, colunas={list(gdf.columns)}")
    sites = json.loads((REPO_ROOT / "config" / "sites.geojson").read_text(encoding="utf-8"))
    vinhedo = next(f["properties"] for f in sites["features"] if f["properties"]["site_id"] == "ascenty-vinhedo")
    lon, lat = vinhedo["lon"], vinhedo["lat"]
    from shapely.geometry import Point
    pt = Point(lon, lat)
    contem = gdf[gdf.contains(pt)]
    print(f"    ponto do site ({lon},{lat}) cai dentro de {len(contem)} polígono(s) — classe: {contem['classe_nome'].tolist() if len(contem) else 'NENHUM'}")

    print("\nTodos os cenários de teste executados — ver acima por reprovações (esperado 0 em todos os itens numéricos).")


if __name__ == "__main__":
    main()
