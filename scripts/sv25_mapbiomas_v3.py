"""SV-25 — V3 (contexto de cobertura): amostra o raster de label MapBiomas (Earth Engine) num
raio de 500 m em volta de cada coordenada candidata resolvida pela cascata (ver
`scripts/validar_coordenadas_sv25.py`).

Aprova se `construida_urbana + solo_exposto_obras >= 30%` dos pixels válidos — um data center está
sobre área construída ou canteiro; reprova se o entorno for predominantemente vegetação/água (ponto
errado, não data center). Fora de escopo (explícito na tarefa): não baixa a série temporal
completa, só este histograma pontual, do ano mais recente da Coleção 9 (`config/params.yml`,
`labels.ano_mapbiomas_max`) — mesma coleção/remap de `sentinela.classes` usados pelo SV-07.

Grava `data/interim/sv25_v3_mapbiomas.json`, que `scripts/validar_coordenadas_sv25.py` lê para
preencher `v3_aprovado`/`v3_pct_construida_solo_500m` em `config/sites.geojson`.

Rodar: `.venv\\Scripts\\python.exe scripts\\sv25_mapbiomas_v3.py`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import ee

from sentinela.classes import REMAPS
from sentinela.config import SETTINGS
from sentinela.gee.auth import init_ee

OUT_PATH = REPO_ROOT / "data" / "interim" / "sv25_v3_mapbiomas.json"
RAIO_M = 500
LIMIAR_PCT = 30.0
CLASSES_CONSTRUIDA_SOLO = (3, 4)  # solo_exposto_obras, construida_urbana (config/classes.yml)

# Mesmas coordenadas candidatas de scripts/validar_coordenadas_sv25.py (COORD_EXISTENTE + COORD_NOVA).
PONTOS = {
    "ascenty-vinhedo": (-23.0700044, -47.0118926),
    "odata-hortolandia": (-22.8995299, -47.1952611),
    "scala-tambore": (-23.4948321, -46.8130769),
    "ascenty-hortolandia": (-22.896022, -47.179246),
    "ascenty-sumare": (-22.8069862, -47.2200481),
    "ascenty-osasco": (-23.492259, -46.777232),
    "equinix-santana-parnaiba": (-23.460369, -46.859912),
    "scala-sgigsm01": (-22.799883, -43.353842),
    "scala-spoapa01": (-30.002768, -51.198149),
    "angonap-fortaleza": (-3.734736, -38.462636),
    "ascenty-maracanau": (-3.830803, -38.611253),
    "everest-goiania": (-16.6915189, -49.2371899),
    "clickip-manaus": (-3.055564, -59.989801),
    "ascenty-paulinia": (-22.7974087, -47.1345476),
    "ascenty-jundiai": (-23.191744, -46.974604),
    "hostdime-joao-pessoa": (-7.117382, -34.856902),
}


def main() -> None:
    init_ee()

    cfg = SETTINGS.params()["labels"]
    ano_max = cfg["ano_mapbiomas_max"]
    banda = f"classification_{ano_max}"
    img = ee.Image(cfg["colecao_mapbiomas"]).select(banda)
    tabela = REMAPS["mapbiomas"]

    out: dict[str, dict] = {}
    for site_id, (lat, lon) in PONTOS.items():
        pt = ee.Geometry.Point([lon, lat])
        buf = pt.buffer(RAIO_M)
        hist = img.reduceRegion(
            reducer=ee.Reducer.frequencyHistogram(), geometry=buf, scale=30, maxPixels=1e9
        ).get(banda)
        hist = hist.getInfo() or {}
        total = sum(hist.values())
        construida_solo = 0.0
        detalhe_classe: dict[int, float] = {}
        for codigo_str, count in hist.items():
            classe = tabela.get(int(codigo_str), 0)
            detalhe_classe[classe] = detalhe_classe.get(classe, 0) + count
            if classe in CLASSES_CONSTRUIDA_SOLO:
                construida_solo += count
        pct = round(100.0 * construida_solo / total, 2) if total else None
        aprovado = (pct is not None) and (pct >= LIMIAR_PCT)
        out[site_id] = {
            "ano_mapbiomas": ano_max,
            "raio_m": RAIO_M,
            "total_pixels_validos": round(total, 1),
            "pct_construida_solo_exposto": pct,
            "aprovado": aprovado,
            "histograma_por_classe": detalhe_classe,
        }
        print(f"{site_id}: pct={pct} aprovado={aprovado} detalhe_classe={detalhe_classe}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gravado {OUT_PATH}.")


if __name__ == "__main__":
    main()
