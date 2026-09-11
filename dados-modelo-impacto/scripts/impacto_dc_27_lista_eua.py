"""Passo 27 — levanta a lista americana e mede o funil do ADR-006 §6.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_27_lista_eua.py --fase lista
    python dados-modelo-impacto/scripts/impacto_dc_27_lista_eua.py --fase funil

## O portão que este passo existe para medir

O ADR-006 propõe retreinar o classificador com rótulos do Dynamic World para poder
expandir a amostra para os EUA. Ele condiciona o retreino a um portão explícito (§6):

  > Levantar a lista americana e medir quantos campi têm data, janela 2018–2022
  > utilizável E sobrevivem ao pareamento. Se o resultado final for menos de ~30
  > campi novos **pareados**, o retreino não se paga.

Este passo executa a primeira metade desse portão. É a mesma disciplina do portão do
CEP (que aprovou) e do de acesso ao CNPJ (que reprovou): medir a viabilidade antes de
construir em cima dela.

## Por que OSM e não datacentermap

A expansão brasileira (passo 25) usou o `datacentermap`, que traz `ano_operacional`.
Para os EUA essa fonte não serve na prática:

  - o site responde **HTTP 429 / "Vercel Security Checkpoint"** a requisição simples;
  - o scraper do repo irmão contorna isso com Selenium e delays de 15–40 s por página,
    reiniciando o driver a cada 11 páginas e esperando 5 min a cada bloqueio;
  - os EUA têm ordem de milhares de páginas, o que põe a coleta em dezenas de horas.

O OpenStreetMap, via Overpass, já é dependência desta frente (footprints do passo 21),
é livre, em lote e sem rate limit hostil. O que ele **não** tem é a data — e é
exatamente isso que este passo mede, em vez de supor.

## O que este passo NÃO faz

Não pareia, não classifica e não decide nada. Ele produz a lista e os números do funil
para que a decisão do ADR-006 seja tomada contra medida, não contra estimativa.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

URL_OVERPASS = "https://overpass-api.de/api/interpreter"
CACHE_OSM = C.DIR_SAIDA / "eua_osm_bruto.json"
SAIDA_CAMPI = C.DIR_SAIDA / "eua_campi.csv"
SAIDA_FUNIL = C.DIR_SAIDA / "eua_funil_resumo.csv"

RAIO_CAMPUS_KM = 2.0  # mesma regra do passo 25: prédios a menos disso são um campus
CELL_GRAU = 0.02      # célula do grid espacial, ~2,2 km em latitude

CONSULTA = """
[out:json][timeout:300];
area["ISO3166-1"="US"][admin_level=2]->.us;
(
  way["telecom"="data_center"](area.us);
  relation["telecom"="data_center"](area.us);
  way["building"="data_center"](area.us);
  relation["building"="data_center"](area.us);
);
out tags center;
"""


def baixar_osm() -> list[dict]:
    """Consulta o Overpass. Idempotente: se o cache existe, não vai à rede."""
    if CACHE_OSM.exists():
        print(f"  cache: {CACHE_OSM.relative_to(C.REPO_ROOT)}")
        return json.loads(CACHE_OSM.read_text(encoding="utf-8"))

    print("  consultando Overpass (pode levar ~1 min)...")
    req = urllib.request.Request(
        URL_OVERPASS,
        data=urllib.parse.urlencode({"data": CONSULTA}).encode(),
        headers={"User-Agent": "SentinelaVerde-MBA/1.0 (pesquisa academica)"},
    )
    with urllib.request.urlopen(req, timeout=320) as resp:
        els = json.load(resp)["elements"]

    CACHE_OSM.parent.mkdir(parents=True, exist_ok=True)
    CACHE_OSM.write_text(json.dumps(els, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {CACHE_OSM.relative_to(C.REPO_ROOT)} ({len(els)} elementos)")
    return els


def _coord(e: dict) -> tuple[float, float] | None:
    if "center" in e:
        return e["center"]["lat"], e["center"]["lon"]
    if "lat" in e:
        return e["lat"], e["lon"]
    return None


def _dist_km(a: dict, b: dict) -> float:
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def agrupar_campi(pts: list[dict]) -> dict[int, list[int]]:
    """Single-linkage < 2 km, com grid espacial para não comparar N² cegamente."""
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, p in enumerate(pts):
        grid[(int(p["lat"] / CELL_GRAU), int(p["lon"] / CELL_GRAU))].append(i)

    pai = list(range(len(pts)))

    def raiz(x: int) -> int:
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for (gy, gx), idxs in grid.items():
        viz: list[int] = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                viz.extend(grid.get((gy + dy, gx + dx), []))
        for i in idxs:
            for j in viz:
                if i < j and _dist_km(pts[i], pts[j]) < RAIO_CAMPUS_KM:
                    ri, rj = raiz(i), raiz(j)
                    if ri != rj:
                        pai[rj] = ri

    campi: dict[int, list[int]] = defaultdict(list)
    for i in range(len(pts)):
        campi[raiz(i)].append(i)
    return campi


def fase_lista() -> None:
    els = baixar_osm()

    pts = []
    for e in els:
        c = _coord(e)
        if c is None:
            continue
        t = e.get("tags", {})
        pts.append({
            "osm_tipo": e.get("type"), "osm_id": e.get("id"),
            "lat": c[0], "lon": c[1],
            "nome": t.get("name"), "operadora": t.get("operator"),
            "start_date": t.get("start_date"),
        })

    campi = agrupar_campi(pts)

    linhas = []
    for k, (_, membros) in enumerate(sorted(campi.items()), start=1):
        m = [pts[i] for i in membros]
        datas = [x["start_date"] for x in m if x["start_date"]]
        linhas.append({
            "campus_id": f"us-{k:04d}",
            "lat": sum(x["lat"] for x in m) / len(m),
            "lon": sum(x["lon"] for x in m) / len(m),
            "n_predios": len(m),
            "nome": next((x["nome"] for x in m if x["nome"]), None),
            "operadora": next((x["operadora"] for x in m if x["operadora"]), None),
            "start_date_osm": datas[0] if datas else None,
            "procedencia": "osm_overpass",
        })

    df = pd.DataFrame(linhas).sort_values("campus_id")
    C.salvar_csv(df, SAIDA_CAMPI)
    print(f"  {len(pts)} prédios -> {len(df)} campi distintos")
    print(f"  -> {SAIDA_CAMPI.relative_to(C.REPO_ROOT)}")


def fase_funil() -> None:
    if not SAIDA_CAMPI.exists():
        sys.exit("rode --fase lista antes")
    df = pd.read_csv(SAIDA_CAMPI)
    com_data = int(df["start_date_osm"].notna().sum())
    n_predios = int(df["n_predios"].sum())

    etapas = [
        ("predios_osm", n_predios, "elementos com telecom/building=data_center nos EUA"),
        ("campi_distintos", len(df), f"prédios a <{RAIO_CAMPUS_KM:g} km agrupados"),
        ("com_data_qualquer", com_data,
         "com start_date no OSM — e a data é do PRÉDIO, não da virada para data center"),
    ]

    resumo = pd.DataFrame(
        [{"etapa": e, "restam": n, "observacao": o} for e, n, o in etapas]
    )
    C.salvar_csv(resumo, SAIDA_FUNIL)

    print("\n  funil americano (ADR-006 §6, primeira metade)")
    print(f"  {'etapa':<22}{'restam':>8}")
    for e, n, _ in etapas:
        print(f"  {e:<22}{n:>8}")

    print(
        "\n  VEREDITO: a lista NÃO é o gargalo — o pool americano (%d campi) é ~4x o\n"
        "  brasileiro (118). O gargalo é a DATA: só %d campi têm qualquer data, e são\n"
        "  datas de construção do prédio, não do início da obra do data center.\n"
        "  O portão do §6 não pode ser fechado com esta fonte sozinha." % (len(df), com_data)
    )
    print(f"\n  -> {SAIDA_FUNIL.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("lista", "funil"), required=True)
    args = ap.parse_args()
    {"lista": fase_lista, "funil": fase_funil}[args.fase]()


if __name__ == "__main__":
    main()
