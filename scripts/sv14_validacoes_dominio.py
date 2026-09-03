"""Script ad-hoc (SV-14) — sanidade de domínio (Ascenty Vinhedo 2025) + continuidade 2018->2019."""

from __future__ import annotations

import json

import numpy as np
import rasterio

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.predict import checar_continuidade_eras, checar_sanidade_data_center


def main() -> None:
    sites = json.loads((REPO_ROOT / "config" / "sites.geojson").read_text(encoding="utf-8"))
    vinhedo = next(f["properties"] for f in sites["features"] if f["properties"]["site_id"] == "ascenty-vinhedo")
    lon, lat = vinhedo["lon"], vinhedo["lat"]

    print("=" * 80)
    print("SANIDADE DE DOMÍNIO — ascenty-vinhedo 2025 (s2)")
    print("=" * 80)
    tif_2025 = SETTINGS.processed_dir / "classificado" / "s2" / "ascenty-vinhedo" / "2025.tif"
    with rasterio.open(tif_2025) as ds:
        arr = ds.read(1)
        crs, transform = ds.crs, ds.transform
    resultado = checar_sanidade_data_center(arr, crs, transform, lon, lat, raio_px=3)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    print(f"PASSOU: {resultado['passou']}")

    print()
    print("=" * 80)
    print("CONTINUIDADE ENTRE ERAS — ascenty-vinhedo 2018 (landsat) vs 2019 (s2)")
    print("=" * 80)
    tif_2018 = SETTINGS.processed_dir / "classificado" / "landsat" / "ascenty-vinhedo" / "2018.tif"
    tif_2019 = SETTINGS.processed_dir / "classificado" / "s2" / "ascenty-vinhedo" / "2019.tif"
    with rasterio.open(tif_2018) as ds:
        arr_2018 = ds.read(1)
        crs_2018, transform_2018 = ds.crs, ds.transform
    with rasterio.open(tif_2019) as ds:
        arr_2019 = ds.read(1)
        crs_2019, transform_2019 = ds.crs, ds.transform

    resultado_cont = checar_continuidade_eras(arr_2018, crs_2018, transform_2018, arr_2019, crs_2019, transform_2019)
    print(json.dumps(resultado_cont, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
