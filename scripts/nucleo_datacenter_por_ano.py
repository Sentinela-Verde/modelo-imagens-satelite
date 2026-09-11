"""Script ad-hoc — série 2013-2025 de % por classe num *núcleo* de raio pequeno em torno do ponto
do site, em vez do buffer de 5 km do AOI (`config/sites.geojson`).

Motivação: o footprint de um data center tem ordem de 10-40 ha; o AOI de 5 km tem ~7.850 ha. No
agregado do AOI (`outputs/indicadores/area_por_classe.csv`) a obra é ~0,3% da área e some no ruído.
Recortando num raio de 500 m o prédio passa a ser dezenas de % da área e a transição
solo exposto -> construída fica visível.

NÃO reclassifica nada — só lê os polígonos por classe já prontos em
`outputs/indicadores/classes_{site}_{ano}_{sensor}.geojson` (SV-14/SV-15) e intersecta com o buffer.

Emite TODAS as combinações site x ano x sensor disponíveis (Landsat 2013-2021 e Sentinel-2
2019-2025), com a coluna `faixa_oficial` marcando quais compõem a série oficial de SV-15 (Landsat
até 2018, Sentinel-2 de 2019 em diante). Emitir as duas eras inteiras é proposital: permite montar
uma série **de sensor único** (Landsat 2013-2021) e comparar com a série mista, isolando o degrau
de instrumento.

ATENÇÃO ao ler o resultado: o degrau Landsat->Sentinel-2 em 2019 é grande (a classe
`solo_exposto_obras` é sub-representada na era Landsat — 2,9% das linhas de treino contra 17,3% no
S2, efeito do teto de amostragem por pixel de `dataset.py`) e NÃO é evento de obra — ver a seção de
risco de docs/tarefas/SV-30-perfil-pre-durante-pos.md. Comparações só valem dentro da mesma era.

Uso:  python scripts/nucleo_datacenter_por_ano.py [raio_m]   (padrão 500)
Gera: outputs/nucleo_{raio}m_por_ano.csv
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

RAIZ = Path(__file__).resolve().parents[1]
DIR_CLASSES = RAIZ / "outputs" / "indicadores"
CLASSES = [
    "vegetacao_densa",
    "vegetacao_rala",
    "solo_exposto_obras",
    "construida_urbana",
    "agua",
]


def na_faixa_oficial(ano: int, sensor: str) -> bool:
    """Landsat 8/9 até 2018, Sentinel-2 de 2019 em diante (ADR-001/ADR-003)."""
    return (ano <= 2018 and sensor == "landsat") or (ano >= 2019 and sensor == "sentinel2")


def main(raio_m: int = 500) -> None:
    sites = json.loads((RAIZ / "config" / "sites.geojson").read_text(encoding="utf-8"))
    meta = {f["properties"]["site_id"]: f["properties"] for f in sites["features"]}

    linhas = []
    for path in sorted(glob.glob(str(DIR_CLASSES / "classes_*.geojson"))):
        m = re.match(r"classes_(.+)_(\d{4})_(landsat|sentinel2)\.geojson$", Path(path).name)
        if not m:
            continue
        site, ano, sensor = m.group(1), int(m.group(2)), m.group(3)
        gdf = gpd.read_file(path)
        if gdf.empty:
            continue
        utm = gdf.estimate_utm_crs()
        gdf = gdf.to_crs(utm)
        p = meta[site]
        nucleo = (
            gpd.GeoSeries([Point(p["lon"], p["lat"])], crs="EPSG:4326")
            .to_crs(utm)
            .buffer(raio_m)
            .iloc[0]
        )

        areas: dict[str, float] = {}
        for _, row in gdf.iterrows():
            a = row.geometry.intersection(nucleo).area
            areas[row["classe_nome"]] = areas.get(row["classe_nome"], 0.0) + a
        total = sum(areas.values())
        if total <= 0:
            continue

        linhas.append(
            {
                "site_id": site,
                "ano": ano,
                "sensor": sensor,
                "faixa_oficial": na_faixa_oficial(ano, sensor),
                "raio_m": raio_m,
                "area_valida_m2": round(total, 1),
                "ano_inicio_obra": p.get("ano_inicio_obra"),
                "ano_inicio_operacao_estimado": p.get("ano_inicio_operacao_estimado"),
                **{f"pct_{c}": round(100 * areas.get(c, 0.0) / total, 2) for c in CLASSES},
            }
        )

    df = pd.DataFrame(linhas).sort_values(["site_id", "sensor", "ano"])
    destino = RAIZ / "outputs" / f"nucleo_{raio_m}m_por_ano.csv"
    df.to_csv(destino, index=False, encoding="utf-8")
    print(f"escrito: {destino} ({len(df)} linhas, {df['site_id'].nunique()} sites)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500)
