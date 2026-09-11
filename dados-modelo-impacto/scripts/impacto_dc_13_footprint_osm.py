"""Passo 13 — footprint real do data center pelo OpenStreetMap, e o que ele revela.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_13_footprint_osm.py [--force]

## Por que

O passo 12 achou sinal contando trajetórias de pixel num disco: 13 de 15 pares, excesso mediano de
1,53 ha num raio de 500 m. Mas um disco de 500 m tem 78 ha — o data center é uma fração dele, e o
resto é vizinhança. Duas perguntas ficaram em aberto:

1. **O classificador enxerga o prédio?** Se o terreno do data center não é classificado como
   "construída" depois da obra, o sinal do passo 12 vem de outra coisa e a interpretação muda.
2. **O excesso é o prédio ou é desenvolvimento induzido em volta?** São afirmações diferentes:
   "o data center ocupa N hectares" é trivial; "o data center puxa urbanização no entorno" é a
   afirmação que interessa ao modelo de impacto.

Com o polígono real dá para separar as duas, medindo **dentro** do footprint e no **anel** em volta.

## Como o footprint é escolhido

Consulta ao Overpass num raio de 600 m do ponto validado, com prioridade explícita:

1. `building=data_center` ou `telecom=data_center` — identificação inequívoca;
2. `landuse=industrial`/`commercial` que contenha ou esteja mais perto do ponto — o terreno;
3. edificação mais próxima dentro de 300 m — aproximação;
4. nada.

O nível usado fica gravado em `metodo_footprint`, porque a força da conclusão depende dele: um
`building=data_center` é evidência direta; uma "edificação mais próxima" é palpite geométrico e
está marcado como tal. **Nada é inventado**: site sem feição adequada fica sem footprint e é
reportado.

A resposta crua de cada site é cacheada em `raw/controles-rf/osm/` — o Overpass tem limite de taxa
(HTTP 429) e não deve ser rebaixado a cada execução.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import truststore

truststore.inject_into_ssl()
import impacto_dc_comum as C
import requests

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "sentinela-verde-mba/1.0 (MBA Eng. Dados Mackenzie; uso academico; contato via repo)"
RAIO_BUSCA_M = 600
RAIO_FALLBACK_EDIFICACAO_M = 300
ESPERA_S = 12.0          # cortesia com a API pública; o Overpass devolve 429 abaixo disso
ESPERA_APOS_429_S = 90.0
TENTATIVAS = 4

DIR_OSM = C.DIR_SAIDA / "osm"
SAIDA = C.DIR_SAIDA / "footprints_osm.csv"


def consultar_overpass(lat: float, lon: float) -> dict[str, Any]:
    consulta = f"""[out:json][timeout:90];
(
  way(around:{RAIO_BUSCA_M},{lat},{lon})["building"];
  way(around:{RAIO_BUSCA_M},{lat},{lon})["landuse"~"industrial|commercial"];
  way(around:{RAIO_BUSCA_M},{lat},{lon})["telecom"];
  relation(around:{RAIO_BUSCA_M},{lat},{lon})["building"];
  relation(around:{RAIO_BUSCA_M},{lat},{lon})["landuse"~"industrial|commercial"];
);
out tags geom;"""
    for tentativa in range(1, TENTATIVAS + 1):
        resposta = requests.post(
            OVERPASS, data={"data": consulta},
            headers={"User-Agent": USER_AGENT}, timeout=180,
        )
        if resposta.status_code == 200:
            return resposta.json()
        if resposta.status_code in (429, 504):
            espera = ESPERA_APOS_429_S * tentativa
            print(f"    HTTP {resposta.status_code} — aguardando {espera:.0f}s "
                  f"(tentativa {tentativa}/{TENTATIVAS})")
            time.sleep(espera)
            continue
        raise RuntimeError(f"Overpass HTTP {resposta.status_code}: {resposta.text[:200]}")
    raise RuntimeError("Overpass não respondeu 200 dentro do limite de tentativas")


def area_ha(anel: list[dict[str, float]]) -> float:
    """Área do polígono em hectares, por fórmula do shoelace sobre coordenadas projetadas
    localmente (equirretangular centrada no próprio polígono — erro desprezível na escala de
    algumas centenas de metros)."""
    import math

    if len(anel) < 3:
        return 0.0
    lat0 = sum(p["lat"] for p in anel) / len(anel)
    k = math.cos(math.radians(lat0))
    xs = [p["lon"] * 111_320.0 * k for p in anel]
    ys = [p["lat"] * 110_540.0 for p in anel]
    soma = sum(xs[i] * ys[(i + 1) % len(anel)] - xs[(i + 1) % len(anel)] * ys[i]
               for i in range(len(anel)))
    return abs(soma) / 2.0 / 10_000.0


def centroide(anel: list[dict[str, float]]) -> tuple[float, float]:
    return (sum(p["lat"] for p in anel) / len(anel), sum(p["lon"] for p in anel) / len(anel))


def escolher_footprint(elementos: list[dict], lat: float, lon: float) -> dict[str, Any] | None:
    """Aplica a prioridade documentada no cabeçalho e devolve a feição escolhida."""
    candidatos = []
    for elemento in elementos:
        geom = elemento.get("geometry")
        if not geom or len(geom) < 3:
            continue
        tags = elemento.get("tags", {})
        clat, clon = centroide(geom)
        candidatos.append({
            "tags": tags, "geom": geom,
            "dist_km": C.distancia_km(lat, lon, clat, clon),
            "area_ha": area_ha(geom),
            "osm_id": f"{elemento.get('type')}/{elemento.get('id')}",
        })
    if not candidatos:
        return None

    def marcar(cand: dict, metodo: str) -> dict:
        return {**cand, "metodo_footprint": metodo}

    explicitos = [c for c in candidatos
                  if c["tags"].get("building") == "data_center"
                  or c["tags"].get("telecom") == "data_center"
                  or "data_center" in str(c["tags"].get("telecom", ""))]
    if explicitos:
        return marcar(min(explicitos, key=lambda c: c["dist_km"]), "osm_data_center_explicito")

    terrenos = [c for c in candidatos if c["tags"].get("landuse") in ("industrial", "commercial")]
    if terrenos:
        return marcar(min(terrenos, key=lambda c: c["dist_km"]), "osm_landuse_industrial")

    edificacoes = [c for c in candidatos
                   if c["tags"].get("building")
                   and c["dist_km"] * 1000 <= RAIO_FALLBACK_EDIFICACAO_M]
    if edificacoes:
        return marcar(min(edificacoes, key=lambda c: c["dist_km"]), "osm_edificacao_mais_proxima")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Footprint OSM dos data centers (passo 13).")
    parser.add_argument("--force", action="store_true", help="reconsulta o Overpass mesmo com cache")
    args = parser.parse_args(argv)

    DIR_OSM.mkdir(parents=True, exist_ok=True)
    campi = C.carregar_campi()
    print(f"Passo 13 — footprint OSM de {len(campi)} campi (raio {RAIO_BUSCA_M} m)")

    linhas: list[dict[str, Any]] = []
    for i, campus in enumerate(campi, 1):
        cache = DIR_OSM / f"{campus['site_id']}.json"
        if cache.exists() and not args.force:
            dados = json.loads(cache.read_text(encoding="utf-8"))
        else:
            print(f"[{i}/{len(campi)}] consultando {campus['site_id']}...")
            try:
                dados = consultar_overpass(campus["lat"], campus["lon"])
            except Exception as exc:  # noqa: BLE001 — falha de rede não mata o lote
                print(f"    FALHOU: {exc!r}")
                linhas.append({"site_id": campus["site_id"], "metodo_footprint": "erro_consulta",
                               "erro": repr(exc)})
                continue
            cache.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            time.sleep(ESPERA_S)

        elementos = dados.get("elements", [])
        escolhido = escolher_footprint(elementos, campus["lat"], campus["lon"])
        if escolhido is None:
            print(f"    {campus['site_id']}: {len(elementos)} feições, nenhuma adequada")
            linhas.append({"site_id": campus["site_id"], "n_feicoes_osm": len(elementos),
                           "metodo_footprint": "sem_footprint"})
            continue

        clat, clon = centroide(escolhido["geom"])
        linhas.append({
            "site_id": campus["site_id"],
            "n_feicoes_osm": len(elementos),
            "metodo_footprint": escolhido["metodo_footprint"],
            "osm_id": escolhido["osm_id"],
            "osm_name": escolhido["tags"].get("name"),
            "osm_operator": escolhido["tags"].get("operator"),
            "osm_building": escolhido["tags"].get("building"),
            "osm_landuse": escolhido["tags"].get("landuse"),
            "area_footprint_ha": round(escolhido["area_ha"], 4),
            "dist_ponto_ao_footprint_km": round(escolhido["dist_km"], 4),
            "lat_centroide": round(clat, 6),
            "lon_centroide": round(clon, 6),
            "n_vertices": len(escolhido["geom"]),
        })
        print(f"    {campus['site_id']}: {escolhido['metodo_footprint']} "
              f"{escolhido['osm_id']} — {escolhido['area_ha']:.2f} ha a "
              f"{escolhido['dist_km'] * 1000:.0f} m do ponto")

    df = pd.DataFrame(linhas)
    C.salvar_csv(df, SAIDA)

    print()
    print("cobertura por método:")
    for metodo, n in df["metodo_footprint"].value_counts().items():
        print(f"  {metodo:32} {n}")
    com = df[df["metodo_footprint"].str.startswith("osm_", na=False)]
    if len(com):
        print()
        print(f"footprints obtidos: {len(com)} de {len(campi)} campi")
        print(f"área: mediana {com['area_footprint_ha'].median():.2f} ha "
              f"(faixa {com['area_footprint_ha'].min():.2f}–{com['area_footprint_ha'].max():.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
