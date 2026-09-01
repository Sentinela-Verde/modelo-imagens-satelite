"""SV-25 — V2 (coerência município/UF): reverse-geocode Nominatim de todas as coordenadas
candidatas resolvidas pela cascata (ver `scripts/validar_coordenadas_sv25.py`).

Respeita o rate limit do Nominatim (1 req/s) e identifica o User-Agent. Grava
`data/interim/sv25_v2_reverse_geocode.json`, que `scripts/validar_coordenadas_sv25.py` lê para
preencher `v2_aprovado`/`v2_municipio_geocodificado` em `config/sites.geojson` — não é
recomputado a cada rodada do pipeline principal, só quando as coordenadas candidatas mudam.

Inclui também o ponto de cross-check de `ascenty-vinhedo` (cenário de teste 6 do enunciado): a
coordenada que a cascata A/B encontrou via OSM, usada só para confirmar o casamento de nome antes
de confiar nas outras 13 AOIs — nunca gravada como coordenada oficial.

Rodar: `.venv\\Scripts\\python.exe scripts\\sv25_reverse_geocode_v2.py`
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "interim" / "sv25_v2_reverse_geocode.json"
HEADERS = {"User-Agent": "sentinela-verde-mba-mackenzie-tcc/1.0 (contato: consignadouniverso@gmail.com)"}

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
    "_crosscheck_ascenty-vinhedo_OSM": (-23.0700247, -47.0118315),
}


def main() -> None:
    out: dict[str, dict] = {}
    for site_id, (lat, lon) in PONTOS.items():
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 12, "addressdetails": 1},
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        addr = d.get("address", {})
        municipio = (
            addr.get("city") or addr.get("town") or addr.get("municipality")
            or addr.get("village") or addr.get("county")
        )
        uf = addr.get("state")
        out[site_id] = {
            "lat": lat, "lon": lon,
            "municipio_geocodificado": municipio, "uf_geocodificado": uf,
            "display_name": d.get("display_name"),
        }
        print(site_id, "->", municipio, "|", uf)
        time.sleep(1.05)  # 1 req/s — respeita o rate limit do Nominatim

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gravado {OUT_PATH}.")


if __name__ == "__main__":
    main()
