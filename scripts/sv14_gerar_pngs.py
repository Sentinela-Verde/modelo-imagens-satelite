"""Script ad-hoc (SV-14) — gera os PNGs de conferência a partir dos rasters classificados já
prontos em disco (não reclassifica nada, só lê e desenha).

Gera, para cada site ativo:
  - reports/figures/mapa_landsat_{site}_2013.png (se existir)
  - reports/figures/mapa_s2_{site}_2025.png (se existir)

E, para os sites usados nas checagens de sanidade/continuidade (ascenty-vinhedo, scala-tambore),
um painel de comparação cronológica completo (2013-2025, um ano por sensor "canônico" daquele ano
— landsat até 2018, s2 de 2019 em diante, evitando duplicar os anos de sobreposição) em
reports/figures/mapa_comparacao_2013_2025_{site}.png.
"""

from __future__ import annotations

import json

import rasterio

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.predict import gerar_png_comparacao, gerar_png_conferencia

SITES_COMPARACAO_COMPLETA = ["ascenty-vinhedo", "scala-tambore"]


def _sites_ativos() -> list[str]:
    data = json.loads((REPO_ROOT / "config" / "sites.geojson").read_text(encoding="utf-8"))
    return sorted(f["properties"]["site_id"] for f in data["features"] if f["properties"]["ativo"])


def _ler_classe(sensor_token: str, site_id: str, ano: int):
    path = SETTINGS.processed_dir / "classificado" / sensor_token / site_id / f"{ano}.tif"
    if not path.exists():
        return None
    with rasterio.open(path) as ds:
        return ds.read(1)


def main() -> None:
    sites = _sites_ativos()
    print(f"{len(sites)} sites ativos: {sites}")

    gerados = []
    faltando = []
    for site_id in sites:
        arr_2013 = _ler_classe("landsat", site_id, 2013)
        if arr_2013 is not None:
            p = gerar_png_conferencia("landsat", site_id, 2013, arr_2013)
            gerados.append(str(p))
        else:
            faltando.append(f"landsat/{site_id}/2013")

        arr_2025 = _ler_classe("s2", site_id, 2025)
        if arr_2025 is not None:
            p = gerar_png_conferencia("s2", site_id, 2025, arr_2025)
            gerados.append(str(p))
        else:
            faltando.append(f"s2/{site_id}/2025")

    for site_id in SITES_COMPARACAO_COMPLETA:
        pares = []
        for ano in range(2013, 2019):
            arr = _ler_classe("landsat", site_id, ano)
            if arr is not None:
                pares.append(("landsat", ano, arr))
        for ano in range(2019, 2026):
            arr = _ler_classe("s2", site_id, ano)
            if arr is not None:
                pares.append(("s2", ano, arr))
        if len(pares) >= 2:
            caminho = REPO_ROOT / "reports" / "figures" / f"mapa_comparacao_2013_2025_{site_id}.png"
            gerar_png_comparacao(site_id, pares, caminho)
            gerados.append(str(caminho))
            print(f"[comparacao] {site_id}: {len(pares)} anos -> {caminho}")
        else:
            print(f"[comparacao] {site_id}: só {len(pares)} ano(s) disponível(is), pulando painel.")

    print(f"\nTotal PNGs gerados: {len(gerados)}")
    if faltando:
        print(f"Faltando (raster classificado ainda não pronto): {faltando}")


if __name__ == "__main__":
    main()
