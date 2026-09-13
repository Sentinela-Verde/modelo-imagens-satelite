"""Passo 28 — deriva o ano da obra dos campi americanos pelo Dynamic World.

Rode com:

    python modelo-impacto/scripts/impacto_dc_28_datar_eua_dw.py --fase geometria
    python modelo-impacto/scripts/impacto_dc_28_datar_eua_dw.py --fase datar
    python modelo-impacto/scripts/impacto_dc_28_datar_eua_dw.py --fase funil

## O problema que este passo resolve

O passo 27 mostrou que a lista americana não é o gargalo — 488 campi distintos, ~4x o
pool brasileiro — mas que a **data** é: só 15 têm `start_date` no OSM, e são datas de
construção do prédio, não do início da obra do data center. O ADR-006 §5 já listava
"ano da obra | **em aberto** — é o gargalo" e não propunha saída.

A saída: o OSM nos dá o **footprint**, e o Dynamic World é global desde jun/2015. Dá
para datar a obra pela virada da cobertura **dentro do polígono do próprio prédio**,
sem registro nenhum.

## Por que isto NÃO é circular

Derivar a data de imagem e depois medir mudança de imagem seria circular — e
circularidade já custou caro nesta frente (ver a correção do passo 26). A trava é a
mesma que sustenta o achado principal:

  - o **t0 vem de dentro da cerca** — fração construída dentro do footprint;
  - o **desfecho é medido no anel de 0,5–1 km**, que por construção nunca contém o
    prédio.

São dois conjuntos de pixels **disjuntos**. O t0 não pode fabricar o efeito porque não
compartilha um único pixel com a zona onde o efeito é medido.

## Limitações, que precisam acompanhar o número

  - **O DW começa em jun/2015.** Campus que já estava construído em 2016 não é datável
    por aqui — aparece como `pre_ja_construido` e sai da amostra. Isso enviesa a lista
    final para obras recentes, o que por acaso casa com a janela 2018–2022 do §6.
  - **Janela de meses:** jun–set (verão do hemisfério norte, baixa nuvem). A pipeline
    brasileira usa estação seca; é a mesma lógica aplicada ao hemisfério certo, não a
    mesma janela de meses.
  - **`built` do DW não é "data center"** — é área construída. O footprint é que garante
    que estamos olhando o prédio certo.
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

sys.path.insert(0, str(C.REPO_ROOT / "src"))

URL_OVERPASS = "https://overpass-api.de/api/interpreter"
CACHE_GEOM = C.DIR_SAIDA / "eua_footprints_geom.json"
SAIDA_SERIE = C.DIR_SAIDA / "eua_dw_serie.csv"
SAIDA_META = C.DIR_SAIDA / "eua_campi_footprint.csv"
SAIDA_DATAS = C.DIR_SAIDA / "eua_datas_derivadas.csv"
SAIDA_FUNIL = C.DIR_SAIDA / "eua_funil_completo.csv"

RAIO_CAMPUS_KM = 2.0
CELL_GRAU = 0.02
ANOS = list(range(2016, 2025))
MES_INI, MES_FIM = "06-01", "09-30"   # verão do hemisfério norte
DW_BUILT = 6                           # classe `built` do Dynamic World
LIMIAR_CONSTRUIDO = 0.50               # metade do footprint construída = prédio existe
MIN_ANOS_PRE = 2                       # pré-período mínimo abaixo do limiar
LOTE_FEATURES = 80                     # features por chamada de reduceRegions

CONSULTA_GEOM = """
[out:json][timeout:300];
area["ISO3166-1"="US"][admin_level=2]->.us;
(
  way["telecom"="data_center"](area.us);
  way["building"="data_center"](area.us);
);
out geom;
"""


def _dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def fase_geometria() -> None:
    """Baixa os polígonos do OSM e agrupa em campi (<2 km), igual ao passo 27."""
    if CACHE_GEOM.exists():
        print(f"  cache: {CACHE_GEOM.relative_to(C.REPO_ROOT)}")
        return

    print("  consultando Overpass com geometria...")
    req = urllib.request.Request(
        URL_OVERPASS,
        data=urllib.parse.urlencode({"data": CONSULTA_GEOM}).encode(),
        headers={"User-Agent": "SentinelaVerde-MBA/1.0 (pesquisa academica)"},
    )
    with urllib.request.urlopen(req, timeout=320) as resp:
        els = json.load(resp)["elements"]

    poligonos = [e for e in els if e.get("geometry") and len(e["geometry"]) >= 4]
    CACHE_GEOM.write_text(json.dumps(poligonos, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {CACHE_GEOM.relative_to(C.REPO_ROOT)} ({len(poligonos)} polígonos)")


def carregar_campi() -> list[dict]:
    """Agrupa os polígonos em campi e devolve um anel por campus."""
    poligonos = json.loads(CACHE_GEOM.read_text(encoding="utf-8"))

    cents = []
    for p in poligonos:
        g = p["geometry"]
        cents.append((sum(n["lat"] for n in g) / len(g), sum(n["lon"] for n in g) / len(g)))

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, c in enumerate(cents):
        grid[(int(c[0] / CELL_GRAU), int(c[1] / CELL_GRAU))].append(i)

    pai = list(range(len(cents)))

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
                if i < j and _dist_km(cents[i], cents[j]) < RAIO_CAMPUS_KM:
                    ri, rj = raiz(i), raiz(j)
                    if ri != rj:
                        pai[rj] = ri

    grupos: dict[int, list[int]] = defaultdict(list)
    for i in range(len(cents)):
        grupos[raiz(i)].append(i)

    campi = []
    for k, (_, membros) in enumerate(sorted(grupos.items()), start=1):
        aneis = [[[n["lon"], n["lat"]] for n in poligonos[i]["geometry"]] for i in membros]
        aneis = [a if a[0] == a[-1] else a + [a[0]] for a in aneis]
        tags = {}
        for i in membros:
            tags.update({k2: v for k2, v in poligonos[i].get("tags", {}).items() if v})
        campi.append({
            "campus_id": f"us-{k:04d}",
            "lat": sum(cents[i][0] for i in membros) / len(membros),
            "lon": sum(cents[i][1] for i in membros) / len(membros),
            "n_predios": len(membros),
            "nome": tags.get("name"),
            "operadora": tags.get("operator"),
            "aneis": aneis,
        })
    return campi


def fase_datar() -> None:
    """Para cada campus e ano, a fração `built` do DW DENTRO do footprint."""
    import ee
    from sentinela.gee.auth import init_ee

    init_ee()
    campi = carregar_campi()
    print(f"  {len(campi)} campi com footprint")

    feats = [
        ee.Feature(ee.Geometry.MultiPolygon([[a] for a in c["aneis"]], geodesic=False),
                   {"campus_id": c["campus_id"]})
        for c in campi
    ]

    linhas = []
    for ano in ANOS:
        dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
              .filterDate(f"{ano}-{MES_INI}", f"{ano}-{MES_FIM}")
              .select("label"))
        modal = dw.reduce(ee.Reducer.mode())
        construido = modal.eq(DW_BUILT).rename("frac_built")

        for ini in range(0, len(feats), LOTE_FEATURES):
            lote = ee.FeatureCollection(feats[ini:ini + LOTE_FEATURES])
            res = construido.reduceRegions(
                collection=lote, reducer=ee.Reducer.mean(), scale=10,
            ).getInfo()
            for f in res["features"]:
                p = f["properties"]
                linhas.append({
                    "campus_id": p["campus_id"], "ano": ano,
                    "frac_built": p.get("mean"),
                })
        print(f"    {ano}: {len(linhas)} leituras acumuladas")

    df = pd.DataFrame(linhas)
    C.salvar_csv(df, SAIDA_SERIE)
    print(f"  -> {SAIDA_SERIE.relative_to(C.REPO_ROOT)}")

    # metadados dos campi num CSV proprio, para a fase `funil` rodar offline
    # sem depender do cache de geometria (que e regeneravel e fica fora do git)
    meta = pd.DataFrame([
        {k: c[k] for k in ("campus_id", "lat", "lon", "n_predios", "nome", "operadora")}
        for c in campi
    ])
    C.salvar_csv(meta, SAIDA_META)
    print(f"  -> {SAIDA_META.relative_to(C.REPO_ROOT)}")


def fase_funil() -> None:
    """Detecta t0 e mede o funil inteiro do ADR-006 §6."""
    if not SAIDA_SERIE.exists():
        sys.exit("rode --fase datar antes")

    serie = pd.read_csv(SAIDA_SERIE)
    if not SAIDA_META.exists():
        sys.exit("falta eua_campi_footprint.csv — rode --fase datar")
    campi = {r["campus_id"]: r for _, r in pd.read_csv(SAIDA_META).iterrows()}

    linhas = []
    for cid, g in serie.groupby("campus_id"):
        g = g.sort_values("ano")
        fr = dict(zip(g["ano"], g["frac_built"]))
        vals = [fr.get(a) for a in ANOS]
        if any(v is None or pd.isna(v) for v in vals):
            status, t0 = "sem_leitura_dw", None
        elif vals[0] >= LIMIAR_CONSTRUIDO:
            status, t0 = "pre_ja_construido", None
        else:
            acima = [a for a, v in zip(ANOS, vals) if v >= LIMIAR_CONSTRUIDO]
            if not acima:
                status, t0 = "nunca_cruza_limiar", None
            elif ANOS.index(acima[0]) < MIN_ANOS_PRE:
                status, t0 = "pre_periodo_curto", None
            else:
                status, t0 = "datado", acima[0]

        c = campi.get(cid, {})
        linhas.append({
            "campus_id": cid, "lat": c.get("lat"), "lon": c.get("lon"),
            "nome": c.get("nome"), "operadora": c.get("operadora"),
            "n_predios": c.get("n_predios"),
            "ano_obra_dw": t0, "status": status,
            "frac_built_inicio": round(vals[0], 4) if vals[0] is not None and not pd.isna(vals[0]) else None,
            "frac_built_fim": round(vals[-1], 4) if vals[-1] is not None and not pd.isna(vals[-1]) else None,
        })

    df = pd.DataFrame(linhas).sort_values("campus_id")
    C.salvar_csv(df, SAIDA_DATAS)

    datados = df[df["status"] == "datado"]
    # janela utilizável: precisa de pré-período e pós-período dentro de 2016–2024
    janela = datados[(datados["ano_obra_dw"] >= 2018) & (datados["ano_obra_dw"] <= 2022)]

    etapas = [
        ("campi_com_footprint", len(df)),
        ("datados_pelo_dw", len(datados)),
        ("janela_2018_2022", len(janela)),
        ("estimativa_pareados_50pct", int(len(janela) * 0.5)),
    ]
    C.salvar_csv(pd.DataFrame([{"etapa": e, "restam": n} for e, n in etapas]), SAIDA_FUNIL)

    print("\n  funil americano completo (ADR-006 §6)")
    for e, n in etapas:
        print(f"  {e:<28}{n:>6}")
    print("\n  distribuição de status:")
    for s, n in df["status"].value_counts().items():
        print(f"    {s:<24}{n:>6}")
    if len(janela):
        print("\n  ano da obra (2018–2022):")
        for a, n in sorted(janela["ano_obra_dw"].value_counts().items()):
            print(f"    {int(a)}: {n}")

    alvo = 30
    est = int(len(janela) * 0.5)
    print(f"\n  PORTÃO §6: limiar ~{alvo} campi novos PAREADOS.")
    print(f"  Estimativa aplicando a taxa brasileira de pareamento (~50%): {est}")
    print(f"  -> {'APROVA' if est >= alvo else 'REPROVA'} o retreino pelo criterio do ADR.")
    print(f"\n  -> {SAIDA_DATAS.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("geometria", "datar", "funil"), required=True)
    args = ap.parse_args()
    {"geometria": fase_geometria, "datar": fase_datar, "funil": fase_funil}[args.fase]()


if __name__ == "__main__":
    main()
