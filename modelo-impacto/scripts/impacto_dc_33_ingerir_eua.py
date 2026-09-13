"""Passo 33 — ingere o datacentermap americano e refaz o funil com greenfield explícito.

Rode com:

    python modelo-impacto/scripts/impacto_dc_33_ingerir_eua.py --fase ingerir
    python modelo-impacto/scripts/impacto_dc_33_ingerir_eua.py --fase funil

## De onde vem o dado

`datacentermap_datacenters_usa.csv`, produzido pelo scraper do repo irmão
(`data-pipeline-model/extract/scraping_datacentermap`) com `PAIS = "usa"`. É a única
fonte de **data de obra** para os EUA que sobreviveu a teste:

  - busca na web não escala e enviesa para sites famosos, grandes e antigos (medido em
    4 sondagens: a Amazon não publica localização nem data);
  - datação por Landsat foi validada contra as 75 datas do Dynamic World e **reprovou**
    (sigma 2,80 anos, 33% dentro de +-1) — ver passo 32.

## As três fontes que este passo cruza

| fonte | traz | cobertura |
|---|---|---|
| datacentermap (scraper) | **ano**, MW, endereço | ~42% têm ano, ~55% têm MW |
| OpenStreetMap (passo 27/28) | **footprint** | 488 campi |
| Dynamic World (passo 28) | **% já construído antes** | 458 campi |

O cruzamento é por proximidade: um registro do datacentermap e um footprint do OSM a
menos de `RAIO_MATCH_KM` são o mesmo empreendimento. Não há id comum entre as fontes.

## Por que `greenfield` é coluna, e não filtro

O achado brasileiro vive em greenfield: **6 de 6** pares positivos (p=0,016, +2,40 p.p.)
contra 5 de 7 no brownfield (p=0,227, +0,77 p.p.). E os dois únicos pares negativos do
estudo inteiro são os sítios mais saturados (86% e 88% já construídos).

Mas restringir a greenfield **muda o que o estudo estima**: deixa de ser "o impacto de um
data center" e passa a ser "o impacto de um data center construído em terreno livre".
É uma pergunta legítima — e mais útil para zoneamento, que só decide sobre terreno livre
— mas precisa ser declarada, não escondida numa seleção.

Por isso `greenfield` entra como **coluna** e a análise roda nos dois recortes, exatamente
como a `procedencia` do passo 25 faz com os campi não validados.

**E não é circular:** greenfield é medido DENTRO do footprint; o efeito é medido no anel
de 0,5–1 km, FORA dele. Conjuntos de pixels disjuntos.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

CSV_SCRAPER = (
    C.REPO_ROOT.parent / "data-pipeline-model" / "data" / "raw" / "outputs_extraction"
    / "datacentermap_datacenters_usa.csv"
)
DATAS_DW = C.DIR_SAIDA / "eua_datas_derivadas.csv"
SAIDA = C.DIR_SAIDA / "eua_campi_datacentermap.csv"
SAIDA_FUNIL = C.DIR_SAIDA / "eua_funil_datacentermap.csv"

RAIO_CAMPUS_KM = 2.0       # mesma regra do passo 25
RAIO_MATCH_KM = 1.5        # datacentermap <-> footprint OSM
CELL_GRAU = 0.02
LIMIAR_GREENFIELD = 0.50   # fração do footprint já construída antes da obra
ANO_MIN, ANO_MAX = 2015, 2022   # janela com pré e pós dentro da série disponível


def _dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _agrupar(pontos: list[dict]) -> list[list[int]]:
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
    return [m for _, m in sorted(grupos.items())]


def fase_ingerir() -> None:
    if not CSV_SCRAPER.exists():
        sys.exit(
            f"CSV do scraper não encontrado:\n  {CSV_SCRAPER}\n"
            "Rode o scraper do repo irmão com PAIS='usa' antes deste passo."
        )

    df = pd.read_csv(CSV_SCRAPER, sep=";", encoding="utf-8-sig")
    df = df[df.latitude.notna() & df.longitude.notna()]
    print(f"  {len(df)} registros com coordenada no CSV do scraper")

    pontos = [{
        "lat": float(r.latitude), "lon": float(r.longitude),
        "nome": r.nome_datacenter, "operadora": r.operadora,
        "cidade": r.cidade, "uf": r.estado,
        "ano": (int(r.ano_operacional) if pd.notna(r.ano_operacional) else None),
        "mw": (float(r.mw_construido) if pd.notna(r.mw_construido) else None),
    } for r in df.itertuples()]

    # --- agrupa em campi; o ano do campus é o MENOR dos prédios ---------------------
    # Um campus cresce por fases (Google Jackson County tem 3 prédios); o que interessa
    # ao desenho antes/depois é quando a PRIMEIRA obra apareceu no terreno.
    linhas = []
    for k, membros in enumerate(_agrupar(pontos), start=1):
        m = [pontos[i] for i in membros]
        anos = [x["ano"] for x in m if x["ano"]]
        mws = [x["mw"] for x in m if x["mw"]]
        linhas.append({
            "campus_id": f"dcm-us-{k:04d}",
            "lat": sum(x["lat"] for x in m) / len(m),
            "lon": sum(x["lon"] for x in m) / len(m),
            "n_predios": len(m),
            "nome": next((x["nome"] for x in m if x["nome"]), None),
            "operadora": next((x["operadora"] for x in m if x["operadora"]), None),
            "cidade": next((x["cidade"] for x in m if x["cidade"]), None),
            "uf": next((x["uf"] for x in m if x["uf"]), None),
            "ano_obra": min(anos) if anos else None,
            "mw_total": sum(mws) if mws else None,
        })
    campi = pd.DataFrame(linhas)
    print(f"  {len(pontos)} prédios -> {len(campi)} campi (<{RAIO_CAMPUS_KM:g} km)")

    # --- cruza com o footprint do OSM para herdar a classificação greenfield --------
    if DATAS_DW.exists():
        dw = pd.read_csv(DATAS_DW)
        dw = dw[dw.frac_built_inicio.notna()]
        ref = [(r.lat, r.lon, r.frac_built_inicio, r.campus_id) for r in dw.itertuples()]
        fracs, ids = [], []
        for r in campi.itertuples():
            melhor, melhor_d = None, RAIO_MATCH_KM
            for la, lo, fr, cid in ref:
                d = _dist_km((r.lat, r.lon), (la, lo))
                if d < melhor_d:
                    melhor, melhor_d = (fr, cid), d
            fracs.append(melhor[0] if melhor else None)
            ids.append(melhor[1] if melhor else None)
        campi["frac_construida_antes"] = fracs
        campi["campus_osm"] = ids
    else:
        campi["frac_construida_antes"] = None
        campi["campus_osm"] = None

    campi["greenfield"] = campi.frac_construida_antes.map(
        lambda v: None if pd.isna(v) else bool(v < LIMIAR_GREENFIELD)
    )
    campi["tem_data"] = campi.ano_obra.notna()
    campi["na_janela"] = campi.ano_obra.between(ANO_MIN, ANO_MAX)

    C.salvar_csv(campi.sort_values("campus_id"), SAIDA)
    print(f"  com footprint OSM casado : {campi.campus_osm.notna().sum()}")
    print(f"  -> {SAIDA.relative_to(C.REPO_ROOT)}")


def fase_funil() -> None:
    if not SAIDA.exists():
        sys.exit("rode --fase ingerir antes")
    d = pd.read_csv(SAIDA)

    com_data = d[d.tem_data]
    janela = d[d.na_janela]
    gf = janela[janela.greenfield == True]  # noqa: E712 — coluna pode ter None

    etapas = [
        ("campi_datacentermap", len(d)),
        ("com_data", len(com_data)),
        (f"janela_{ANO_MIN}_{ANO_MAX}", len(janela)),
        ("com_footprint_osm", int(janela.campus_osm.notna().sum())),
        ("greenfield", len(gf)),
    ]
    C.salvar_csv(pd.DataFrame([{"etapa": e, "restam": n} for e, n in etapas]), SAIDA_FUNIL)

    print("\n--- funil americano, via datacentermap ---")
    for e, n in etapas:
        print(f"  {e:<28}{n:>5}")

    if len(janela):
        print("\n  por ano de obra:")
        for a, n in sorted(janela.ano_obra.value_counts().items()):
            print(f"    {int(a)}: {n}")
    if len(gf):
        print(f"\n  MW total dos greenfield: {gf.mw_total.sum():.0f} "
              f"({gf.mw_total.notna().sum()} com dado)")

    print(f"\n  Comparativo — o estudo brasileiro tem 20 campi pareados.")
    print(f"  Aplicando a taxa de pareamento brasileira (~50%): {len(gf)} greenfield")
    print(f"  renderiam ~{len(gf) // 2} pares. O pareamento real ainda precisa rodar.")
    print(f"\n  -> {SAIDA_FUNIL.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("ingerir", "funil"), required=True)
    args = ap.parse_args()
    {"ingerir": fase_ingerir, "funil": fase_funil}[args.fase]()


if __name__ == "__main__":
    main()
