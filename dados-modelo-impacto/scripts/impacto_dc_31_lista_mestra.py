"""Passo 31 — a lista mestra de campi: Brasil + EUA, com procedência por linha.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_31_lista_mestra.py --fase montar

## O que este passo entrega

Um CSV único com todo campus candidato do estudo de impacto, nos dois países, com a
proveniência e as limitações marcadas **por linha** — não numa nota de rodapé.

## A assimetria de fonte, que é o problema central desta lista

As duas metades vêm de fontes diferentes, e não por escolha:

| | Brasil | EUA |
|---|---:|---:|
| OpenStreetMap | **45** elementos | **1.649** elementos |
| datacentermap | 242 registros | bloqueado (HTTP 429 / anti-bot) |

O OSM mal cobre o Brasil; o datacentermap não é raspável para os EUA sem Selenium e
dezenas de horas. Então cada país entra pela melhor fonte disponível **para ele**, e a
coluna `fonte` carrega isso.

**A consequência precisa acompanhar qualquer comparação entre países:** a lista brasileira
e a americana não têm o mesmo critério de inclusão. Diferença medida entre Brasil e EUA
pode ser diferença de cobertura de cadastro, não de território. Comparação BR x EUA exige
estrato ou uma fonte comum — não está resolvido aqui, e fingir que está seria pior que
declarar.

## O que a lista NÃO decide

Não filtra por data, não pareia e não julga elegibilidade. É o universo de partida; os
cortes (data da obra, janela utilizável, controle pareável) são passos seguintes e cada um
tem seu próprio critério registrado. Manter o universo separado dos cortes é o que permite
dizer, depois, quanto cada critério custou.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

URL_DCMAP = (
    "https://raw.githubusercontent.com/Sentinela-Verde/data-pipeline-model/main/"
    "data/raw/outputs_extraction/datacentermap_datacenters.csv"
)
CACHE_DCMAP = C.DIR_SAIDA / "datacentermap_br.csv"
CACHE_OSM_BR = C.DIR_SAIDA / "br_osm_bruto.json"
CACHE_OSM_US = C.DIR_SAIDA / "eua_osm_bruto.json"
SAIDA = C.DIR_SAIDA / "lista_mestra_campi.csv"

RAIO_CAMPUS_KM = 2.0
CELL_GRAU = 0.02


def _dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _agrupar(pontos: list[dict]) -> list[list[int]]:
    """Single-linkage < 2 km — mesma regra do passo 25, para os campi serem comparaveis."""
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, p in enumerate(pontos):
        grid[(int(p["lat"] / CELL_GRAU), int(p["lon"] / CELL_GRAU))].append(i)

    pai = list(range(len(pontos)))

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
                if i < j and _dist_km(
                    (pontos[i]["lat"], pontos[i]["lon"]), (pontos[j]["lat"], pontos[j]["lon"])
                ) < RAIO_CAMPUS_KM:
                    ri, rj = raiz(i), raiz(j)
                    if ri != rj:
                        pai[rj] = ri

    grupos: dict[int, list[int]] = defaultdict(list)
    for i in range(len(pontos)):
        grupos[raiz(i)].append(i)
    return [membros for _, membros in sorted(grupos.items())]


def _pontos_osm(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    pontos = []
    for e in json.loads(caminho.read_text(encoding="utf-8")):
        if "center" in e:
            lat, lon = e["center"]["lat"], e["center"]["lon"]
        elif "lat" in e:
            lat, lon = e["lat"], e["lon"]
        else:
            continue
        t = e.get("tags", {})
        pontos.append({
            "lat": lat, "lon": lon,
            "nome": t.get("name"), "operadora": t.get("operator"),
            "fonte": "osm",
        })
    return pontos


def _pontos_dcmap() -> list[dict]:
    if not CACHE_DCMAP.exists():
        print("  baixando datacentermap (Brasil)...")
        CACHE_DCMAP.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL_DCMAP, timeout=120) as r:
            CACHE_DCMAP.write_bytes(r.read())
    df = pd.read_csv(CACHE_DCMAP, sep=";", encoding="utf-8-sig")
    df = df[df.latitude.notna() & df.longitude.notna()]
    return [{
        "lat": float(r.latitude), "lon": float(r.longitude),
        "nome": r.nome_datacenter, "operadora": r.operadora,
        "ano_operacional": (int(r.ano_operacional) if pd.notna(r.ano_operacional) else None),
        "municipio": r.cidade, "uf": r.estado,
        "fonte": "datacentermap",
    } for r in df.itertuples()]


def _campi(pontos: list[dict], pais: str, prefixo: str) -> list[dict]:
    linhas = []
    for k, membros in enumerate(_agrupar(pontos), start=1):
        m = [pontos[i] for i in membros]
        anos = [x.get("ano_operacional") for x in m if x.get("ano_operacional")]
        fontes = sorted({x["fonte"] for x in m})
        linhas.append({
            "campus_id": f"{prefixo}-{k:04d}",
            "pais": pais,
            "lat": sum(x["lat"] for x in m) / len(m),
            "lon": sum(x["lon"] for x in m) / len(m),
            "n_predios": len(m),
            "nome": next((x["nome"] for x in m if x.get("nome")), None),
            "operadora": next((x["operadora"] for x in m if x.get("operadora")), None),
            "municipio": next((x.get("municipio") for x in m if x.get("municipio")), None),
            "uf": next((x.get("uf") for x in m if x.get("uf")), None),
            "ano_operacional": min(anos) if anos else None,
            "fonte": "+".join(fontes),
        })
    return linhas


def fase_montar() -> None:
    # --- Brasil: datacentermap (242 registros) + OSM (45), fundidos por proximidade -----
    br_pontos = _pontos_dcmap() + _pontos_osm(CACHE_OSM_BR)
    br = _campi(br_pontos, "BR", "br")
    print(f"  Brasil : {len(br_pontos)} pontos -> {len(br)} campi")

    # --- EUA: só OSM; o datacentermap responde 429 a requisição simples ----------------
    us_pontos = _pontos_osm(CACHE_OSM_US)
    us = _campi(us_pontos, "US", "us")
    print(f"  EUA    : {len(us_pontos)} pontos -> {len(us)} campi")

    df = pd.DataFrame(br + us)

    # As datas americanas nao vem de cadastro (o datacentermap nao e raspavel la): vem do
    # passo 28, derivadas da virada para construida DENTRO do footprint, via Dynamic World.
    # A coluna `origem_data` guarda essa diferenca, que e grande: uma e data declarada, a
    # outra e estimada por imagem e so existe para obras de ~2017 em diante (o DW comeca em
    # jun/2015).
    df["origem_data"] = df.ano_operacional.notna().map(
        {True: "declarada_datacentermap", False: None}
    )
    derivadas = C.DIR_SAIDA / "eua_datas_derivadas.csv"
    if derivadas.exists():
        dd = pd.read_csv(derivadas)
        dd = dd[dd.ano_obra_dw.notna()]
        por_coord = {(round(r.lat, 4), round(r.lon, 4)): r.ano_obra_dw for r in dd.itertuples()}
        for i, r in df.iterrows():
            if r.pais != "US" or pd.notna(r.ano_operacional):
                continue
            for (la, lo), ano in por_coord.items():
                if _dist_km((r.lat, r.lon), (la, lo)) < 1.0:
                    df.at[i, "ano_operacional"] = int(ano)
                    df.at[i, "origem_data"] = "derivada_dynamic_world"
                    break

    # marca quem ja esta no estudo atual, para nao reprocessar nem perder a rastreabilidade
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    atuais = [(float(r.lat), float(r.lon)) for r in par.itertuples()]
    df["no_estudo_atual"] = [
        any(_dist_km((r.lat, r.lon), a) < 3.0 for a in atuais) for r in df.itertuples()
    ]

    df["tem_data"] = df.ano_operacional.notna()
    df = df.sort_values(["pais", "campus_id"])
    C.salvar_csv(df, SAIDA)

    print()
    print("--- lista mestra ---")
    for pais, g in df.groupby("pais"):
        print(f"  {pais}: {len(g):>4} campi | com data: {int(g.tem_data.sum()):>3} | "
              f"ja no estudo: {int(g.no_estudo_atual.sum()):>2}")
    print(f"  {'TOTAL':<4}{len(df):>5} campi")
    print()
    print("  ATENCAO: as duas metades vem de fontes diferentes (OSM tem 45 elementos no")
    print("  Brasil contra 1.649 nos EUA). Comparacao BR x EUA carrega diferenca de")
    print("  cobertura de cadastro, nao so de territorio.")
    print()
    print(f"  -> {SAIDA.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("montar",), required=True)
    ap.parse_args()
    fase_montar()


if __name__ == "__main__":
    main()
