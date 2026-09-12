"""Passo 34 — pareamento de controles para os campi americanos, via Dynamic World.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_34_parear_eua.py --fase parear

## Por que não reusar o passo 3

O pareamento brasileiro (`gerar_controles_pareados.py`, 1.133 linhas) tem três peças que
não atravessam a fronteira:

| etapa | Brasil | portável? |
|---|---|---|
| grade de candidatos (7 raios x 24 azimutes, anel 15-40 km) | geométrico | sim |
| filtros de contaminação e sobreposição de buffer | geométrico | sim |
| filtro de município / microrregião | **IBGE** | não |
| pré-ranqueamento de cobertura | **MapBiomas** | não |
| escolha final | `rf_v1.0-tuned` (treinado no Brasil) | não |

As três últimas viram **Dynamic World**, que é global e é o instrumento que o portão §4
do ADR-006 concluiu ser o certo para esta frente ("usar o Dynamic World direto").

Isso torna o pareamento americano **diferente** do brasileiro, e a diferença precisa
acompanhar qualquer comparação entre os dois conjuntos. O L1 fica publicado na saída para
que a comparabilidade possa ser conferida em vez de suposta.

## Onde os EUA ficam MELHOR que o Brasil

O filtro de contaminação — "nenhum controle perto de um data center conhecido" — depende
de saber onde estão os data centers. No Brasil a lista é de 242 registros. Nos EUA temos
**488 campi do OSM** mais **~1.100 links do datacentermap**, então a chance de um
"controle" ser na verdade um data center não catalogado é bem menor.

## O que o passo NÃO faz

Não classifica nada com o nosso RF e não mede impacto. Só escolhe, para cada campus, o
terreno de comparação — e publica por que escolheu.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

sys.path.insert(0, str(C.REPO_ROOT / "src"))

CAMPI_DCM = C.DIR_SAIDA / "eua_campi_datacentermap.csv"
CAMPI_OSM = C.DIR_SAIDA / "eua_campi.csv"
LINKS_SCRAPER = (
    C.REPO_ROOT.parent / "data-pipeline-model" / "extract" / "scraping_datacentermap"
    / "output" / "datacenters_links_usa.csv"
)
SAIDA = C.DIR_SAIDA / "eua_pareamento.csv"
SAIDA_CAND = C.DIR_SAIDA / "eua_candidatos_avaliados.csv"

# Mesma grade do desenho brasileiro (SV-29), para os dois conjuntos serem comparáveis
# naquilo que PODE ser igual.
RAIOS_KM = [15, 19, 23, 27, 31, 35, 40]
N_AZIMUTES = 24
BUFFER_KM = 5.0
DIST_MIN_DC_KM = 8.0    # nenhum controle a menos disto de um data center conhecido
LOTE_EE = 60
CLASSES = [1, 2, 3, 4, 5]


def _destino(lat: float, lon: float, azimute_deg: float, dist_km: float) -> tuple[float, float]:
    r = 6371.0
    d = dist_km / r
    br = math.radians(azimute_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(br))
    l2 = l1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def _dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _datacenters_conhecidos() -> list[tuple[float, float]]:
    """Toda coordenada de data center que conhecemos, para o filtro de contaminação."""
    pontos: list[tuple[float, float]] = []
    if CAMPI_OSM.exists():
        d = pd.read_csv(CAMPI_OSM)
        pontos += [(r.lat, r.lon) for r in d.itertuples()]
    if LINKS_SCRAPER.exists():
        d = pd.read_csv(LINKS_SCRAPER)
        d = d[d.latitude.notna() & d.longitude.notna()]
        pontos += [(float(r.latitude), float(r.longitude)) for r in d.itertuples()]
    return pontos


def _tratamentos() -> pd.DataFrame:
    if not CAMPI_DCM.exists():
        sys.exit(f"falta {CAMPI_DCM} — rode o passo 33 primeiro.")
    d = pd.read_csv(CAMPI_DCM)
    d = d[d.ano_obra.notna() & d.na_janela]
    return d.reset_index(drop=True)


def _perfil_dw(feats, ano: int) -> dict[str, list[float]]:
    """Fração de cada uma das 5 classes no buffer, por Dynamic World, no ano dado."""
    import ee
    params = SETTINGS_PARAMS
    col = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
           .filterDate(f"{ano}-{params['mes_inicio']:02d}-01",
                       f"{ano}-{params['mes_fim']:02d}-30")
           .select("label"))
    modal = col.mode()
    # remap DW -> nossas 5 classes (config/classes.yml, seção remaps.dynamic_world)
    remap = modal.remap([0, 1, 2, 3, 4, 5, 6, 7, 8], [5, 1, 2, 5, 2, 2, 4, 3, 5]).rename("classe")

    perfis: dict[str, list[float]] = {}
    for ini in range(0, len(feats), LOTE_EE):
        fc = ee.FeatureCollection(feats[ini:ini + LOTE_EE])
        bandas = [remap.eq(c).rename(f"c{c}") for c in CLASSES]
        img = bandas[0]
        for b in bandas[1:]:
            img = img.addBands(b)
        res = img.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10).getInfo()
        for f in res["features"]:
            p = f["properties"]
            vals = [p.get(f"c{c}") or 0.0 for c in CLASSES]
            s = sum(vals) or 1.0
            perfis[p["id"]] = [v / s for v in vals]
    return perfis


def _l1(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


def fase_parear() -> None:
    import ee
    from sentinela.config import SETTINGS
    from sentinela.gee.auth import init_ee

    global SETTINGS_PARAMS
    SETTINGS_PARAMS = SETTINGS.params()
    init_ee()

    trat = _tratamentos()
    dcs = _datacenters_conhecidos()
    print(f"  {len(trat)} campi de tratamento (com data, na janela)")
    print(f"  {len(dcs)} coordenadas de data center para o filtro de contaminação")

    def buffer(lat: float, lon: float, ident: str):
        return ee.Feature(
            ee.Geometry.Point([lon, lat]).buffer(BUFFER_KM * 1000), {"id": ident}
        )

    linhas_cand, linhas_par = [], []
    for r in trat.itertuples():
        ano_ref = int(r.ano_obra) - 1  # cobertura no ano ANTERIOR à obra

        # --- grade de candidatos, com filtro geométrico de contaminação -------------
        candidatos = []
        for raio in RAIOS_KM:
            for k in range(N_AZIMUTES):
                la, lo = _destino(r.lat, r.lon, k * (360 / N_AZIMUTES), raio)
                if any(_dist_km((la, lo), p) < DIST_MIN_DC_KM for p in dcs):
                    continue
                candidatos.append((la, lo, raio))
        if not candidatos:
            linhas_par.append({"campus_id": r.campus_id, "status": "sem_candidato",
                               "motivo": "todos contaminados por data center a <8 km"})
            print(f"  {r.campus_id}: 0 candidatos (todos contaminados)")
            continue

        # --- perfil de cobertura do tratamento e dos candidatos ---------------------
        feats = [buffer(r.lat, r.lon, "T")]
        feats += [buffer(la, lo, f"C{i}") for i, (la, lo, _) in enumerate(candidatos)]
        try:
            perfis = _perfil_dw(feats, ano_ref)
        except Exception as e:  # noqa: BLE001
            linhas_par.append({"campus_id": r.campus_id, "status": "erro", "motivo": str(e)[:120]})
            print(f"  {r.campus_id}: ERRO {type(e).__name__}")
            continue

        alvo = perfis.get("T")
        if not alvo:
            linhas_par.append({"campus_id": r.campus_id, "status": "erro",
                               "motivo": "sem perfil do tratamento"})
            continue

        avaliados = []
        for i, (la, lo, raio) in enumerate(candidatos):
            p = perfis.get(f"C{i}")
            if not p:
                continue
            d = _l1(alvo, p)
            avaliados.append((d, la, lo, raio))
            linhas_cand.append({
                "campus_id": r.campus_id, "lat": la, "lon": lo,
                "dist_km": raio, "l1_dw": round(d, 4), "ano_referencia": ano_ref,
            })

        if not avaliados:
            linhas_par.append({"campus_id": r.campus_id, "status": "sem_candidato",
                               "motivo": "nenhum candidato com leitura de DW"})
            continue

        avaliados.sort()
        d, la, lo, raio = avaliados[0]
        # Mesma escala de qualidade do estudo brasileiro, para os selos serem legíveis
        # lado a lado: L1 <= 0,10 bom; <= 0,20 aceitável; acima disso ruim.
        qualidade = "bom" if d <= 0.10 else ("aceitavel" if d <= 0.20 else "ruim")
        linhas_par.append({
            "campus_id": r.campus_id, "lat": r.lat, "lon": r.lon,
            "ano_obra": int(r.ano_obra), "greenfield": r.greenfield,
            "site_id_controle": f"ctrl-{r.campus_id}",
            "lat_controle": la, "lon_controle": lo,
            "dist_tratamento_controle_km": raio,
            "l1_dw": round(d, 4), "qualidade": qualidade,
            "n_candidatos_validos": len(avaliados),
            "status": "ok", "motivo": None,
        })
        print(f"  {r.campus_id}: {len(avaliados)} candidatos, melhor L1={d:.3f} ({qualidade})")

    par = pd.DataFrame(linhas_par)
    C.salvar_csv(par, SAIDA)
    if linhas_cand:
        C.salvar_csv(pd.DataFrame(linhas_cand), SAIDA_CAND)

    ok = par[par.status == "ok"] if "status" in par else par
    print(f"\n--- pareamento americano ---")
    print(f"  tratamentos          : {len(trat)}")
    print(f"  pareados             : {len(ok)}  ({100 * len(ok) / max(len(trat), 1):.0f}%)")
    if len(ok):
        print(f"  greenfield pareados  : {int((ok.greenfield == True).sum())}")  # noqa: E712
        print(f"  qualidade            : {ok.qualidade.value_counts().to_dict()}")
        print(f"  L1 mediano           : {ok.l1_dw.median():.3f}")
    print(f"\n  (Brasil, para comparar: 10 de 10 elegíveis -> 5 pareados, 50%)")
    print(f"\n  -> {SAIDA.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("parear",), required=True)
    ap.parse_args()
    fase_parear()


if __name__ == "__main__":
    main()
