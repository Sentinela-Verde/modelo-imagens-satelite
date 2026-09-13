"""Passo 32 — data da obra por Landsat, para alcançar antes de 2016.

Rode com:

    python modelo-impacto/scripts/impacto_dc_32_datar_landsat.py --fase serie
    python modelo-impacto/scripts/impacto_dc_32_datar_landsat.py --fase validar
    python modelo-impacto/scripts/impacto_dc_32_datar_landsat.py --fase datar

## O corte que este passo existe para desfazer

O passo 28 datou campi americanos pelo Dynamic World e alcançou 75 de 488. Os outros
413 não são indatáveis — são indatáveis **pelo DW**, cuja série começa em jun/2015. Dos
482 com footprint, **329 já estavam construídos em 2016**.

Isso foi limitação da fonte que escolhemos, não do problema: o **Landsat é global e vai a
2013** (e Landsat 5/7 vão aos anos 1980). O estudo brasileiro já usa Landsat 2013–2018.

## Como se data sem classificador

O DW entrega classe; o Landsat entrega reflectância. Em vez de classificar, medimos um
índice de construído e procuramos o degrau:

    NDBI = (SWIR1 - NIR) / (SWIR1 + NIR)

NDBI sobe quando vegetação/solo viram superfície impermeável, e **fica alto** — é degrau,
não pico. Obra em curso passa por solo exposto, que também levanta o NDBI; por isso o
critério exige que o nível **se sustente** depois, e não só que suba num ano.

`t0` é o ano que maximiza (média dos anos >= t) − (média dos anos < t), exigindo pelo menos
2 anos de cada lado e um degrau acima de `DEGRAU_MIN`. É detecção de ponto de mudança
padrão, e o degrau medido fica na saída para quem quiser outro limiar.

## Por que a fase `validar` existe, e por que ela vem antes de `datar`

Um método de datação novo sem validação é chute com decimais. Temos dois conjuntos com data
conhecida:

  - **75 campi americanos** datados pelo DW (passo 28);
  - **52 campi brasileiros** com `ano_operacional` declarado no datacentermap.

A fase `validar` roda o NDBI nesses e compara com a data conhecida. Se o erro for grande,
o método não serve para os 413 e é melhor saber antes de publicar 413 datas erradas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

sys.path.insert(0, str(C.REPO_ROOT / "src"))

CACHE_GEOM = C.DIR_SAIDA / "eua_footprints_geom.json"
LISTA_MESTRA = C.DIR_SAIDA / "lista_mestra_campi.csv"
SAIDA_SERIE = C.DIR_SAIDA / "landsat_ndbi_serie.csv"
SAIDA_VALID = C.DIR_SAIDA / "landsat_datacao_validacao.csv"
SAIDA_DATAS = C.DIR_SAIDA / "landsat_datas_derivadas.csv"

ANOS = list(range(2013, 2026))
MES_INI, MES_FIM = 6, 9          # verão do hemisfério norte, baixa nuvem
MIN_LADO = 2                      # anos minimos de cada lado do degrau
DEGRAU_MIN = 0.03                 # degrau de NDBI abaixo disto nao conta como obra
LOTE = 60


def _colecao_landsat(ano: int):
    """Composto mediano de superfície, Landsat 8+9, com nuvem mascarada."""
    import ee

    def _prep(img):
        qa = img.select("QA_PIXEL")
        # bits 3 e 4 do QA_PIXEL: nuvem e sombra de nuvem
        limpo = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
        sr = img.select(["SR_B5", "SR_B6"]).multiply(0.0000275).add(-0.2)
        return sr.updateMask(limpo).rename(["nir", "swir1"])

    col = None
    for cid in ("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"):
        c = (ee.ImageCollection(cid)
             .filterDate(f"{ano}-{MES_INI:02d}-01", f"{ano}-{MES_FIM:02d}-30")
             .map(_prep))
        col = c if col is None else col.merge(c)
    mediana = col.median()
    return (mediana.select("swir1").subtract(mediana.select("nir"))
            .divide(mediana.select("swir1").add(mediana.select("nir")))
            .rename("ndbi"))


def _features_dos_campi(campus_ids: set[str] | None = None):
    """Footprints como ee.Feature, reaproveitando o agrupamento do passo 28."""
    import ee
    import impacto_dc_28_datar_eua_dw as m28

    feats, meta = [], []
    for c in m28.carregar_campi():
        if campus_ids is not None and c["campus_id"] not in campus_ids:
            continue
        feats.append(ee.Feature(
            ee.Geometry.MultiPolygon([[a] for a in c["aneis"]], geodesic=False),
            {"campus_id": c["campus_id"]},
        ))
        meta.append({k: c[k] for k in ("campus_id", "lat", "lon", "nome", "operadora")})
    return feats, pd.DataFrame(meta)


def _serie_ndbi(feats) -> pd.DataFrame:
    import ee
    from sentinela.gee.auth import init_ee

    init_ee()
    linhas = []
    for ano in ANOS:
        ndbi = _colecao_landsat(ano)
        for ini in range(0, len(feats), LOTE):
            fc = ee.FeatureCollection(feats[ini:ini + LOTE])
            res = ndbi.reduceRegions(collection=fc, reducer=ee.Reducer.mean(),
                                     scale=30).getInfo()
            for f in res["features"]:
                p = f["properties"]
                linhas.append({"campus_id": p["campus_id"], "ano": ano,
                               "ndbi": p.get("mean")})
        print(f"    {ano}: {len(linhas)} leituras")
    return pd.DataFrame(linhas)


def detectar_degrau(anos: list[int], valores: list[float]) -> tuple[int | None, float]:
    """Ano que maximiza (media depois) - (media antes). Devolve (t0, degrau)."""
    pares = [(a, v) for a, v in zip(anos, valores) if v is not None and not pd.isna(v)]
    if len(pares) < 2 * MIN_LADO:
        return None, float("nan")
    aa = [a for a, _ in pares]
    vv = np.array([v for _, v in pares], dtype=float)

    melhor_t, melhor_d = None, -np.inf
    for i in range(MIN_LADO, len(vv) - MIN_LADO + 1):
        d = vv[i:].mean() - vv[:i].mean()
        if d > melhor_d:
            melhor_t, melhor_d = aa[i], d
    if melhor_d < DEGRAU_MIN:
        return None, float(melhor_d)
    return melhor_t, float(melhor_d)


def fase_serie() -> None:
    # antes de _features_dos_campi: construir ee.Feature ja exige o cliente inicializado
    from sentinela.gee.auth import init_ee
    init_ee()

    feats, meta = _features_dos_campi()
    print(f"  {len(feats)} campi com footprint")
    df = _serie_ndbi(feats)
    C.salvar_csv(df, SAIDA_SERIE)
    C.salvar_csv(meta, C.DIR_SAIDA / "landsat_campi_meta.csv")
    print(f"  -> {SAIDA_SERIE.relative_to(C.REPO_ROOT)}")


def fase_validar() -> None:
    """Compara a datacao por NDBI com as 75 datas do DW (passo 28)."""
    if not SAIDA_SERIE.exists():
        sys.exit("rode --fase serie antes")
    serie = pd.read_csv(SAIDA_SERIE)

    dw = pd.read_csv(C.DIR_SAIDA / "eua_datas_derivadas.csv")
    dw = dw[dw.ano_obra_dw.notna()][["campus_id", "ano_obra_dw"]]

    linhas = []
    for cid, g in serie.groupby("campus_id"):
        g = g.sort_values("ano")
        t0, degrau = detectar_degrau(list(g.ano), list(g.ndbi))
        linhas.append({"campus_id": cid, "ano_landsat": t0, "degrau_ndbi": degrau})
    est = pd.DataFrame(linhas)

    comp = dw.merge(est, on="campus_id", how="inner")
    comp["erro_anos"] = comp.ano_landsat - comp.ano_obra_dw
    C.salvar_csv(comp, SAIDA_VALID)

    ok = comp[comp.ano_landsat.notna()]
    print(f"\n--- validacao contra as {len(dw)} datas do Dynamic World ---")
    print(f"  datados pelo Landsat tambem : {len(ok)}")
    if len(ok):
        e = ok.erro_anos.astype(float)
        print(f"  erro mediano   : {e.median():+.1f} anos")
        print(f"  erro |mediano| : {e.abs().median():.1f} anos")
        print(f"  dentro de +-1  : {100.0 * (e.abs() <= 1).mean():.0f}%")
        print(f"  dentro de +-2  : {100.0 * (e.abs() <= 2).mean():.0f}%")
    print(f"\n  -> {SAIDA_VALID.relative_to(C.REPO_ROOT)}")


def fase_datar() -> None:
    if not SAIDA_SERIE.exists():
        sys.exit("rode --fase serie antes")
    serie = pd.read_csv(SAIDA_SERIE)
    meta = pd.read_csv(C.DIR_SAIDA / "landsat_campi_meta.csv")

    linhas = []
    for cid, g in serie.groupby("campus_id"):
        g = g.sort_values("ano")
        t0, degrau = detectar_degrau(list(g.ano), list(g.ndbi))
        linhas.append({
            "campus_id": cid, "ano_obra_landsat": t0,
            "degrau_ndbi": round(degrau, 4) if not pd.isna(degrau) else None,
            "status": "datado" if t0 else "sem_degrau",
        })
    df = pd.DataFrame(linhas).merge(meta, on="campus_id", how="left")
    C.salvar_csv(df, SAIDA_DATAS)

    dat = df[df.status == "datado"]
    print(f"\n--- datacao por Landsat ({len(df)} campi) ---")
    print(f"  datados    : {len(dat)}")
    print(f"  sem degrau : {len(df) - len(dat)}")
    if len(dat):
        print("\n  por ano de obra:")
        for a, n in sorted(dat.ano_obra_landsat.value_counts().items()):
            print(f"    {int(a)}: {n}")
    print(f"\n  -> {SAIDA_DATAS.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("serie", "validar", "datar"), required=True)
    args = ap.parse_args()
    {"serie": fase_serie, "validar": fase_validar, "datar": fase_datar}[args.fase]()


if __name__ == "__main__":
    main()
