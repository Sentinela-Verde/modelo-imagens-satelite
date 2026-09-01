"""SV-25 — validação de coordenadas em escala: funções puras de verificação + carregamento.

Fonte única das verificações V1 (caixa do Brasil), V4 (colisão de AOI) e V5 (distância a uma
coordenada de referência já conhecida) — usadas tanto pelo pipeline
(`scripts/validar_coordenadas_sv25.py`) quanto por `tests/test_sites.py`, para não haver duas
implementações do mesmo critério que possam divergir.

V2 (coerência município/UF) e V3 (contexto MapBiomas) dependem de rede (Nominatim reverse-geocode
e Earth Engine, respectivamente) e por isso são calculadas **uma vez**, no momento em que o
pipeline resolve cada coordenada, e o resultado fica gravado nas properties de
`config/sites.geojson` (`v2_aprovado`, `v3_aprovado`/`v3_nao_aplicavel`) — os testes verificam essas
propriedades já gravadas, não recomputam a chamada de rede a cada `pytest` (mesmo padrão que
`tests/test_candidatos.py` já usa para os artefatos de SV-09).
"""

from __future__ import annotations

import math
from pathlib import Path

from .config import REPO_ROOT

SITES_PATH = REPO_ROOT / "config" / "sites.geojson"

# V1 — caixa do Brasil (pega troca de lat/lon e sinal invertido).
BR_LAT_MIN, BR_LAT_MAX = -34.0, 6.0
BR_LON_MIN, BR_LON_MAX = -74.0, -34.0

# V4 — nenhum par de AOIs a menos de 5 km (mesmo buffer_km do ADR-001).
V4_COLISAO_KM = 5.0

# V5 — discordância entre a coordenada resolvida e uma já conhecida (lista_20/PeeringDB citado em
# SV-24) acima disso é erro de fonte, não ruído de geocodificação.
V5_DISTANCIA_MAX_KM = 2.0

CAMPOS_PROVENIENCIA_OBRIGATORIOS = (
    "metodo_coordenada",
    "precisao_coordenada",
    "fonte_coordenada",
    "data_consulta",
)

METODOS_VALIDOS = {"peeringdb", "osm", "geocode", "manual"}
PRECISOES_VALIDAS = {"exata", "aproximada", "inferida"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância geodésica aproximada (esfera de raio médio da Terra) entre dois pontos, em km."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def v1_caixa_brasil(lat: float, lon: float) -> bool:
    """(V1) `lat` em [-34, 6], `lon` em [-74, -34] — pega troca de lat/lon e sinal invertido."""
    return BR_LAT_MIN <= lat <= BR_LAT_MAX and BR_LON_MIN <= lon <= BR_LON_MAX


def v4_colisoes(sites: list[dict], limiar_km: float = V4_COLISAO_KM) -> dict[str, list[tuple[str, float]]]:
    """(V4) Para cada `site_id`, lista de `(outro_site_id, distancia_km)` para pares < `limiar_km`.

    `sites` é uma lista de dicts com pelo menos `site_id`, `lat`, `lon`. Não decide fusão — só
    relata; a decisão caso a caso é humana/do pipeline (ver docstring do módulo e ADR-005).
    """
    out: dict[str, list[tuple[str, float]]] = {s["site_id"]: [] for s in sites}
    for i, a in enumerate(sites):
        for b in sites[i + 1 :]:
            d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if d < limiar_km:
                out[a["site_id"]].append((b["site_id"], round(d, 3)))
                out[b["site_id"]].append((a["site_id"], round(d, 3)))
    return out


def v5_distancia(lat: float, lon: float, lat_ref: float, lon_ref: float) -> tuple[float, bool]:
    """(V5) Distância (km) entre a coordenada resolvida e uma referência já conhecida, e se passa."""
    d = haversine_km(lat, lon, lat_ref, lon_ref)
    return round(d, 3), d < V5_DISTANCIA_MAX_KM


def carregar_sites(path: Path | None = None):
    """Carrega `config/sites.geojson` como GeoDataFrame (EPSG:4326, geometrias Point)."""
    import geopandas as gpd

    return gpd.read_file(path or SITES_PATH)
