"""Passo 36 — caracterização territorial de data centers nas Américas (N=612).

Rode com:

    python modelo-impacto/scripts/impacto_dc_36_descritivo.py --fase medir
    python modelo-impacto/scripts/impacto_dc_36_descritivo.py --fase relatar

## O que este estudo é, e o que ele deliberadamente NÃO é

**Não é causal.** Não afirma que o data center causou nada. Afirmação causal exige
período pré-obra e controle pareado, e isso depende de saber a data da obra — que existe
para 26 campi, não para 612. Esse é o estudo do resto desta pasta.

**É descritivo, e é onde os 612 servem.** Descreve *onde* data centers se instalam, *o
que* há ao redor deles e *quanto* de território ocupam. Nenhuma dessas perguntas precisa
de data, então todas as 612 observações entram — 23x a amostra do estudo causal.

Os dois se complementam: o descritivo dá escala, o causal dá profundidade. Trocar um pelo
outro seria erro nos dois sentidos.

## A ressalva que acompanha toda comparação Brasil x EUA aqui

As duas metades vêm de fontes diferentes, e não por escolha: o OpenStreetMap tem 45
elementos no Brasil contra 1.649 nos EUA; o datacentermap não é raspável para os EUA sem
Selenium e dezenas de horas. Cada país entrou pela melhor fonte **dele** (passo 31).

Então **diferença medida entre BR e EUA pode ser diferença de cobertura de cadastro, não
de território**. Onde o número for comparado entre países, isso tem de estar dito. Onde
for descrição dentro de um país, não se aplica.

## As medidas, e por que estas

| medida | fonte | por que não precisa de data |
|---|---|---|
| composição de cobertura no entorno (5 classes) | Dynamic World, 10 m | é um retrato de hoje |
| **anomalia térmica** (campus vs anel 5-10 km) | Landsat `ST_B10`, 30 m | compara no espaço, não no tempo |
| área do footprint | OpenStreetMap | geometria |
| capacidade (MW) | datacentermap | cadastro |

A **anomalia térmica** é a peça que responde a pergunta da ilha de calor sem antes/depois:
em vez de "esquentou depois da obra?", pergunta "o entorno do data center é mais quente
que a região ao redor dele, hoje?". É pergunta diferente e mais fraca causalmente — mas é
respondível com N=612 em vez de N=12, e o contraste espacial é medido, não suposto.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

sys.path.insert(0, str(C.REPO_ROOT / "src"))

LISTA = C.DIR_SAIDA / "lista_mestra_campi.csv"
DATAS_DW = C.DIR_SAIDA / "eua_datas_derivadas.csv"
SAIDA = C.DIR_SAIDA / "descritivo_campi.csv"

ANO = 2024              # último ano cheio com DW e Landsat
RAIO_CAMPUS_KM = 1.0    # entorno imediato
RAIO_REF_INT = 5.0      # anel de referência regional
RAIO_REF_EXT = 10.0
LOTE = 50
CLASSES = [1, 2, 3, 4, 5]
NOMES_CLASSE = {1: "veg_densa", 2: "veg_rala", 3: "solo_exposto", 4: "construida", 5: "agua"}


def _dw_remapeado(ano: int):
    import ee
    p = C.SETTINGS.params() if hasattr(C, "SETTINGS") else None
    mes_i, mes_f = (p["mes_inicio"], p["mes_fim"]) if p else (6, 9)
    col = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
           .filterDate(f"{ano}-{mes_i:02d}-01", f"{ano}-{mes_f:02d}-30")
           .select("label"))
    return col.mode().remap([0, 1, 2, 3, 4, 5, 6, 7, 8],
                            [5, 1, 2, 5, 2, 2, 4, 3, 5]).rename("classe")


def _lst(ano: int):
    """Temperatura de superfície em °C, Landsat 8/9 Collection 2 nível 2."""
    import ee

    def _prep(img):
        qa = img.select("QA_PIXEL")
        limpo = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
        # fator de escala do produto ST_B10, e Kelvin -> Celsius
        st = img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15)
        return st.updateMask(limpo).rename("lst")

    col = None
    for cid in ("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"):
        c = ee.ImageCollection(cid).filterDate(f"{ano}-01-01", f"{ano}-12-31").map(_prep)
        col = c if col is None else col.merge(c)
    return col.median()


def fase_medir() -> None:
    import ee
    from sentinela.gee.auth import init_ee

    init_ee()
    if not LISTA.exists():
        sys.exit(f"falta {LISTA} — rode o passo 31.")
    campi = pd.read_csv(LISTA)
    print(f"  {len(campi)} campi ({campi.pais.value_counts().to_dict()})")

    dw = _dw_remapeado(ANO)
    lst = _lst(ANO)
    bandas = dw.eq(CLASSES[0]).rename(f"c{CLASSES[0]}")
    for c in CLASSES[1:]:
        bandas = bandas.addBands(dw.eq(c).rename(f"c{c}"))
    img_cob = bandas

    linhas: dict[str, dict] = {}
    for ini in range(0, len(campi), LOTE):
        bloco = campi.iloc[ini:ini + LOTE]

        def fc(raio_int: float, raio_ext: float):
            fs = []
            for r in bloco.itertuples():
                pt = ee.Geometry.Point([r.lon, r.lat])
                geom = (pt.buffer(raio_ext * 1000) if raio_int == 0
                        else pt.buffer(raio_ext * 1000).difference(pt.buffer(raio_int * 1000)))
                fs.append(ee.Feature(geom, {"id": r.campus_id}))
            return ee.FeatureCollection(fs)

        # cobertura e LST no entorno imediato
        res = img_cob.addBands(lst).reduceRegions(
            collection=fc(0, RAIO_CAMPUS_KM), reducer=ee.Reducer.mean(), scale=10).getInfo()
        for f in res["features"]:
            p = f["properties"]
            vals = [p.get(f"c{c}") or 0.0 for c in CLASSES]
            s = sum(vals) or 1.0
            linhas[p["id"]] = {f"pct_{NOMES_CLASSE[c]}": 100.0 * v / s
                               for c, v in zip(CLASSES, vals)}
            linhas[p["id"]]["lst_campus"] = p.get("lst")

        # LST no anel de referência regional
        res = lst.reduceRegions(
            collection=fc(RAIO_REF_INT, RAIO_REF_EXT),
            reducer=ee.Reducer.mean(), scale=30).getInfo()
        for f in res["features"]:
            p = f["properties"]
            linhas.setdefault(p["id"], {})["lst_referencia"] = p.get("mean")

        print(f"    {min(ini + LOTE, len(campi))}/{len(campi)}")

    med = pd.DataFrame([{"campus_id": k, **v} for k, v in linhas.items()])
    d = campi.merge(med, on="campus_id", how="left")
    d["anomalia_termica_c"] = d.lst_campus - d.lst_referencia

    if DATAS_DW.exists():
        dwd = pd.read_csv(DATAS_DW)[["campus_id", "frac_built_inicio"]]
        d = d.merge(dwd, on="campus_id", how="left")
        d["greenfield"] = d.frac_built_inicio.map(
            lambda v: None if pd.isna(v) else bool(v < 0.5))

    C.salvar_csv(d, SAIDA)
    print(f"  -> {SAIDA.relative_to(C.REPO_ROOT)}")


def fase_relatar() -> None:
    if not SAIDA.exists():
        sys.exit("rode --fase medir antes")
    d = pd.read_csv(SAIDA)
    ok = d[d.lst_campus.notna()]

    print(f"\n=== caracterização territorial, N={len(ok)} de {len(d)} campi ===")
    print("(AVISO: BR e EUA vêm de fontes diferentes — ver docstring)\n")

    print("--- cobertura do solo no raio de 1 km (% mediano) ---")
    cols = [f"pct_{n}" for n in NOMES_CLASSE.values()]
    print(ok.groupby("pais")[cols].median().round(1).to_string())

    print("\n--- anomalia térmica: campus (1 km) menos região (anel 5-10 km) ---")
    a = ok[ok.anomalia_termica_c.notna()]
    for pais, g in a.groupby("pais"):
        pos = 100.0 * (g.anomalia_termica_c > 0).mean()
        print(f"  {pais}: n={len(g):>4}  mediana {g.anomalia_termica_c.median():+.2f} °C  "
              f"| {pos:.0f}% mais quentes que a região")
    print(f"  TOTAL: n={len(a)}  mediana {a.anomalia_termica_c.median():+.2f} °C")

    if "greenfield" in ok.columns:
        g = ok[ok.greenfield.notna()]
        if len(g):
            print("\n--- em que terreno se instalam (EUA, onde há footprint) ---")
            print(f"  greenfield (<50% construído antes): "
                  f"{int((g.greenfield == True).sum())} de {len(g)} "  # noqa: E712
                  f"({100 * (g.greenfield == True).mean():.0f}%)")  # noqa: E712
            print("\n  anomalia térmica por tipo de terreno:")
            for gf, sub in g.groupby("greenfield"):
                nome = "greenfield" if gf else "brownfield"
                s = sub[sub.anomalia_termica_c.notna()]
                if len(s):
                    print(f"    {nome:<12} n={len(s):>4}  {s.anomalia_termica_c.median():+.2f} °C")

    print(f"\n  -> {SAIDA.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("medir", "relatar"), required=True)
    args = ap.parse_args()
    {"medir": fase_medir, "relatar": fase_relatar}[args.fase]()


if __name__ == "__main__":
    main()
