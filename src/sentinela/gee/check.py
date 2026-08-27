"""Smoke test do Earth Engine. Rode com: python -m sentinela.gee.check --site <site_id>

Inicializa o EE, conta imagens Sentinel-2 disponíveis na AOI para cada ano da Faixa A (janela
jun-set), confirma acesso às coleções de máscara de nuvem e labels, e salva um thumbnail RGB para
inspeção visual. Não baixa/exporta raster de verdade — isso é SV-06.
"""

from __future__ import annotations

import argparse
import sys

import ee
import requests

from ..config import REPO_ROOT, SETTINGS, ConfigError
from .auth import init_ee

DEFAULT_BBOX = {
    # bbox de fallback (~5km em torno de um ponto na região de Campinas/SP) — usado só se
    # config/sites.geojson não existir ainda ou não tiver o site pedido.
    "site_id": "default-fallback",
    "lat": -22.9,
    "lon": -47.05,
    "buffer_km": 5,
}


def _load_site(site_id: str) -> dict:
    sites_path = REPO_ROOT / "config" / "sites.geojson"
    if sites_path.exists():
        import geopandas as gpd

        gdf = gpd.read_file(sites_path)
        row = gdf[gdf["site_id"] == site_id]
        if not row.empty:
            r = row.iloc[0]
            return {
                "site_id": site_id,
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "buffer_km": float(r["buffer_km"]),
            }
        print(
            f"AVISO: site_id '{site_id}' não encontrado em {sites_path}. "
            f"Sites disponíveis: {list(gdf['site_id'])}. Usando bbox default.",
            file=sys.stderr,
        )
    else:
        print(
            f"AVISO: {sites_path} não existe (SV-02 ainda não rodou?). Usando bbox default.",
            file=sys.stderr,
        )
    return DEFAULT_BBOX


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test do acesso ao Earth Engine.")
    parser.add_argument("--site", required=True, help="site_id de config/sites.geojson")
    args = parser.parse_args()

    try:
        init_ee()
    except ConfigError as e:
        print(f"ERRO DE CONFIGURAÇÃO:\n{e}", file=sys.stderr)
        return 1

    site = _load_site(args.site)
    point = ee.Geometry.Point(site["lon"], site["lat"])
    aoi = point.buffer(site["buffer_km"] * 1000)

    print(f"Site: {site['site_id']} (lat={site['lat']}, lon={site['lon']}, buffer={site['buffer_km']}km)")
    print()

    # --- Confirma acesso às coleções auxiliares ---
    for collection_id in ["GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED", "ESA/WorldCover/v200"]:
        try:
            ee.ImageCollection(collection_id).limit(1).first().getInfo()
            print(f"OK  acesso a {collection_id}")
        except ee.EEException as e:
            print(f"FALHA acesso a {collection_id}: {e}", file=sys.stderr)
            return 1
    print()

    # --- Conta imagens Sentinel-2 por ano da Faixa A, janela jun-set ---
    params = SETTINGS.params()
    faixa_a = params["faixa_a"]
    mes_inicio, mes_fim = params["mes_inicio"], params["mes_fim"]
    anos = faixa_a["anos"]

    print("ano | n_imagens (Sentinel-2 SR, janela jun-set)")
    print("----|----------")
    contagens: dict[int, int] = {}
    for ano in anos:
        start = f"{ano}-{mes_inicio:02d}-01"
        end = f"{ano}-{mes_fim:02d}-30"
        n = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filterDate(start, end)
            .size()
            .getInfo()
        )
        contagens[ano] = n
        flag = "  <-- cobertura fraca (< 8)" if n < 8 else ""
        print(f"{ano} | {n}{flag}")
    print()

    anos_fracos = [a for a, n in contagens.items() if n < 8]
    if anos_fracos:
        print(
            f"ACHADO: {len(anos_fracos)} ano(s) com cobertura Sentinel-2 fraca (<8 imagens): "
            f"{anos_fracos}. Isso é insumo para SV-06, não falha desta tarefa.",
        )

    # --- Thumbnail RGB (ano Sentinel-2 mais recente com imagens) ---
    anos_s2_com_dados = [a for a in anos if faixa_a["sensor_por_ano"].get(a) == "sentinel2" and contagens.get(a, 0) > 0]
    if anos_s2_com_dados:
        ano_thumb = max(anos_s2_com_dados)
        start = f"{ano_thumb}-{mes_inicio:02d}-01"
        end = f"{ano_thumb}-{mes_fim:02d}-30"
        composite = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filterDate(start, end)
            .median()
            .select(["B4", "B3", "B2"])
        )
        thumb_url = composite.getThumbURL(
            {"region": aoi, "dimensions": 512, "min": 0, "max": 3000, "format": "png"}
        )
        out_dir = REPO_ROOT / "reports" / "figures"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"smoke_test_{site['site_id']}.png"
        resp = requests.get(thumb_url, timeout=60)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        print(f"Thumbnail salvo em {out_path} (composto {ano_thumb}, RGB natural)")
    else:
        print("AVISO: nenhum ano com dados Sentinel-2 disponível para gerar thumbnail.", file=sys.stderr)
        return 1

    print()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
