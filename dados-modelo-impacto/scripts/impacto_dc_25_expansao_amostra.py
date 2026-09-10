"""Passo 25 — expande a amostra de 15 para ~25 campi, com procedência marcada.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_25_expansao_amostra.py --fase lista
    python dados-modelo-impacto/scripts/impacto_dc_25_expansao_amostra.py --fase controles
    python dados-modelo-impacto/scripts/impacto_dc_25_expansao_amostra.py --fase classificar

## Por que N importa aqui

Vários resultados desta frente não fecham por tamanho de amostra, não por ausência de efeito:

  - temperatura no anel: estimativa +0,51 °C, precisaria de **n=31** e temos 12
  - janela longa (t>=4): inconclusivo com n=9, os dois anéis apontando para lados opostos
  - greenfield vs brownfield: 6 e 7 casos por estrato

Nada disso melhora com método melhor. Melhora com mais casos.

## De onde vêm os campi novos, e quantos existem de verdade

Da lista `datacentermap` (242 registros). Depois de agrupar prédios do mesmo campus (< 2 km) e
exigir ano documentado, sobram **53 campi**. Mas a janela `obra-3 .. obra+3` precisa caber numa
série de satélite, e é aí que o número desaba:

    2011-2015   antes de o Landsat 8 ter janela pré-obra completa
    2016-2022   a faixa utilizável
    2023-2029   ainda não têm "depois" para observar

**O boom brasileiro está acontecendo agora** — metade dos campi datados é de 2023+. Não é limitação
de esforço; é limitação de calendário. Com janela relaxada de 5 anos chegamos a ~10 campi novos.

## A ressalva que vira coluna, não nota de rodapé

Os 16 sites originais passaram por validação de coordenada em **cinco camadas** (V1-V5, SV-25). Os
novos vêm do `datacentermap` sem essa cascata. Misturar os dois sem marcar seria esconder uma
diferença real de qualidade.

Por isso toda linha carrega `procedencia` (`validado_5_camadas` | `datacentermap`), e a análise
deve ser rodada **com e sem** os novos. Se o achado mudar ao incluir sites menos validados, isso é
resultado — e o lugar de descobrir é aqui, não na banca.

Saídas:
  - `raw/controles-rf/campi_expansao.csv`      — os campi novos, com procedência e motivo
  - `raw/controles-rf/expansao_pareamento.csv` — o controle de cada um
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

URL_DCMAP = (
    "https://raw.githubusercontent.com/Sentinela-Verde/data-pipeline-model/main/"
    "data/raw/outputs_extraction/datacentermap_datacenters.csv"
)
RAIO_CAMPUS_KM = 2.0     # prédios a menos disso são o mesmo campus
DIST_MIN_DOS_NOSSOS_KM = 3.0  # abaixo disso já é um dos 16 originais
DEFASAGEM_OBRA = 1       # ano_operacional - 1 ~= inicio da obra
FOLGA_MIN = 2            # anos antes e depois exigidos (janela relaxada de 5)

SAIDA_LISTA = C.DIR_SAIDA / "campi_expansao.csv"
SAIDA_PAR = C.DIR_SAIDA / "expansao_pareamento.csv"


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "-" for c in t.lower()).strip("-")[:40]


def _hav(a: float, b: float, c: float, d: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    a, b, c, d = map(radians, [a, b, c, d])
    return 2 * 6371 * asin(sqrt(sin((c - a) / 2) ** 2 + cos(a) * cos(c) * sin((d - b) / 2) ** 2))


def _cabe_em_um_sensor(obra: int, folga: int) -> str | None:
    for sensor, (lo, hi) in (("landsat", (2013, 2024)), ("s2", (2019, 2025))):
        if obra - folga >= lo and obra + folga <= hi:
            return sensor
    return None


def fase_lista() -> pd.DataFrame:
    bruto = requests.get(URL_DCMAP, timeout=120).content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(bruto), delimiter=";"))
    nossos = [(p["lat"], p["lon"]) for p in C.carregar_sites_validados().values()]

    pontos = []
    for r in rows:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (TypeError, ValueError):
            continue
        ano = (r.get("ano_operacional") or "").strip()
        pontos.append({"nome": r["nome_datacenter"], "op": int(ano) if ano.isdigit() else None,
                       "lat": lat, "lon": lon, "municipio": r.get("cidade", ""),
                       "uf": r.get("estado", "")})

    campi: list[dict] = []
    for p in pontos:
        for c in campi:
            if _hav(p["lat"], p["lon"], c["lat"], c["lon"]) < RAIO_CAMPUS_KM:
                c["membros"].append(p["nome"])
                if p["op"]:
                    c["anos"].append(p["op"])
                break
        else:
            campi.append({**p, "membros": [p["nome"]], "anos": [p["op"]] if p["op"] else []})

    linhas = []
    for c in campi:
        if not c["anos"]:
            continue
        op = min(c["anos"])
        obra = op - DEFASAGEM_OBRA
        sensor = _cabe_em_um_sensor(obra, FOLGA_MIN)
        dist_nosso = min((_hav(c["lat"], c["lon"], la, lo) for la, lo in nossos), default=999)
        motivo = None
        if sensor is None:
            motivo = ("obra antes de 2016 (sem janela pré no Landsat 8)" if obra < 2016
                      else "obra recente demais — ainda não há período pós-obra")
        elif dist_nosso <= DIST_MIN_DOS_NOSSOS_KM:
            motivo = "já é um dos 16 sites validados"
        linhas.append({
            "site_id": f"exp-{_slug(c['nome'])}",
            "nome": c["nome"], "municipio": c["municipio"], "uf": c["uf"],
            "lat": c["lat"], "lon": c["lon"],
            "n_predios_no_campus": len(c["membros"]),
            "ano_operacional": op, "ano_inicio_obra": obra,
            "sensor_da_janela": sensor,
            "dist_ao_site_validado_mais_proximo_km": round(dist_nosso, 2),
            "procedencia": "datacentermap",
            "elegivel": motivo is None,
            "motivo_exclusao": motivo,
        })

    df = pd.DataFrame(linhas).sort_values(["elegivel", "ano_inicio_obra"], ascending=[False, True])
    C.salvar_csv(df, SAIDA_LISTA)

    el = df[df.elegivel]
    print(f"\n{len(campi)} campi distintos · {len(df)} com ano · {len(el)} ELEGIVEIS e novos")
    print(f"\nnota: `ano_inicio_obra` aqui e `ano_operacional - {DEFASAGEM_OBRA}`, uma APROXIMACAO.")
    print("Os 16 originais tem o ano pesquisado em imprensa (SV-24); estes nao. Coluna")
    print("`procedencia` carrega essa diferenca, e a analise deve rodar com e sem eles.\n")
    if not el.empty:
        print(el[["site_id", "municipio", "uf", "ano_inicio_obra", "sensor_da_janela"]]
              .to_string(index=False))
    print("\nexcluidos, por motivo:")
    print(df[~df.elegivel].motivo_exclusao.value_counts().to_string())
    return df


CHECKPOINT_EXP = C.DIR_SAIDA / "checkpoint_expansao.json"


def fase_controles() -> None:
    """Gera o controle pareado de cada campus novo, reusando `processar_campus` do passo 3.

    Não reimplementa o desenho: chama a mesma função, com os mesmos filtros geométricos, o mesmo
    pré-ranqueamento por MapBiomas e a mesma decisão final pelo classificador. A única coisa que
    muda é de onde vêm os campi — daqui, e não de `config/sites.geojson`.

    Os buffers ocupados incluem os 16 sites validados, os controles da rodada anterior E os campi
    novos entre si: um controle não pode cair perto de nenhum data center conhecido, e "conhecido"
    passou a incluir os 10 da expansão.
    """
    import impacto_dc_03_gerar_controles as P3
    import gerar_controles_pareados as G

    df = pd.read_csv(SAIDA_LISTA)
    novos = df[df.elegivel].copy()
    if novos.empty:
        print("nenhum campus elegível — nada a parear")
        return

    C.iniciar_ee()
    pacote = C.carregar_modelo()
    cfg_labels = G.SETTINGS.params()["labels"]
    cache = G.CacheGeo(G.CACHE_GEO_PATH)

    sites_tratamento = G.carregar_sites_tratamento()
    pontos_contaminacao = G.carregar_pontos_contaminacao(sites_tratamento, cache)
    # os campi novos também contaminam: são data centers reais, ainda que não validados
    pontos_contaminacao += [{"lat": r.lat, "lon": r.lon} for _, r in novos.iterrows()]
    print(f"{len(pontos_contaminacao)} pontos de contaminação (inclui os {len(novos)} novos)")

    buffers_ocupados = [(s["lat"], s["lon"], s["buffer_km"]) for s in sites_tratamento]
    par_atual = C.DIR_SAIDA / "pareamento_controle_rf.csv"
    if par_atual.exists():
        for _, r in pd.read_csv(par_atual).iterrows():
            if pd.notna(r.get("lat_controle")):
                buffers_ocupados.append((float(r.lat_controle), float(r.lon_controle), C.BUFFER_KM))
    buffers_ocupados += [(r.lat, r.lon, C.BUFFER_KM) for _, r in novos.iterrows()]

    checkpoint = C.Checkpoint(CHECKPOINT_EXP)
    for i, (_, r) in enumerate(novos.iterrows(), 1):
        if checkpoint.get(r.site_id):
            print(f"[{i}/{len(novos)}] {r.site_id} — já processado, pulando")
            continue
        campus = {
            "site_id": r.site_id, "lat": float(r.lat), "lon": float(r.lon),
            "buffer_km": C.BUFFER_KM, "ano_inicio_obra": int(r.ano_inicio_obra),
            "municipio": r.municipio, "uf": r.uf, "bioma": None, "tier": None,
        }
        print(f"[{i}/{len(novos)}] {r.site_id} ({r.municipio}/{r.uf}, obra ~{r.ano_inicio_obra})")
        try:
            # O pareamento compara a distribuição de classes do candidato contra a do TRATAMENTO
            # no ano de referência (`avaliar_finalistas_com_rf`), então o tratamento precisa estar
            # classificado antes. Para os 16 sites oficiais isso já existe — eles passam pelo
            # pipeline do classificador principal. Para um campus de expansão, não: ninguém o
            # classificou ainda, e sem esta linha o passo 3 morre com FileNotFoundError.
            ano_ref = C.ano_referencia_pareamento(campus["ano_inicio_obra"])
            sensor = C.sensor_da_janela(C.janela_anos(campus["ano_inicio_obra"]))
            if not Path(C.caminho_classificado(sensor, campus["site_id"], ano_ref)).exists():
                print(f"  classificando o tratamento em {ano_ref} (pré-requisito do pareamento)")
                C.rodar_ponto(campus, ano_ref, sensor, pacote, descartar_apos=True)

            res = P3.processar_campus(campus, pontos_contaminacao, buffers_ocupados,
                                      cache, cfg_labels, pacote)
        except Exception as exc:  # noqa: BLE001 — falha de rede num site não mata o lote
            res = {"status": "erro", "motivo": repr(exc)}
            print(f"  FALHOU: {exc!r}")
        checkpoint.set(r.site_id, res)
        if res["status"] == "ok":
            v = res["vencedor"]
            buffers_ocupados.append((v["lat"], v["lon"], C.BUFFER_KM))
            print(f"  -> controle {v['site_id_controle']} a {v['dist_ao_tratamento_km']} km, "
                  f"L1_rf={v['l1_rf']:.4f} ({C.qualidade_l1(v['l1_rf'])})")
        cache.salvar()

    linhas = []
    for _, r in novos.iterrows():
        res = checkpoint.get(r.site_id) or {}
        v = res.get("vencedor") or {}
        linhas.append({
            "site_id": r.site_id, "municipio": r.municipio, "uf": r.uf,
            "lat": r.lat, "lon": r.lon, "ano_inicio_obra": r.ano_inicio_obra,
            "sensor": res.get("sensor"), "status": res.get("status", "nao_processado"),
            "motivo": res.get("motivo"),
            "site_id_controle": v.get("site_id_controle"),
            "lat_controle": v.get("lat"), "lon_controle": v.get("lon"),
            "dist_tratamento_controle_km": v.get("dist_ao_tratamento_km"),
            "l1_rf": v.get("l1_rf"),
            "qualidade": C.qualidade_l1(v["l1_rf"]) if v.get("l1_rf") is not None else None,
            "procedencia": "datacentermap",
        })
    par = pd.DataFrame(linhas)
    C.salvar_csv(par, SAIDA_PAR)
    ok = par[par.status == "ok"]
    print(f"\n{len(ok)}/{len(par)} campi novos com controle")
    if not ok.empty:
        print(ok.qualidade.value_counts().to_string())


def fase_classificar() -> None:
    """Classifica a janela completa de cada campus novo e de seu controle."""
    par = pd.read_csv(SAIDA_PAR)
    ok = par[(par.status == "ok") & par.site_id_controle.notna()]
    if ok.empty:
        print("nenhum par pronto — rode --fase controles antes")
        return
    C.iniciar_ee()
    pacote = C.carregar_modelo()
    total = 0
    for _, r in ok.iterrows():
        anos = C.janela_anos(int(r.ano_inicio_obra))
        for tipo, pid, lat, lon in (("tratamento", r.site_id, r.lat, r.lon),
                                    ("controle", r.site_id_controle, r.lat_controle, r.lon_controle)):
            ponto = {"site_id": pid, "lat": float(lat), "lon": float(lon),
                     "buffer_km": C.BUFFER_KM}
            for ano in anos:
                if Path(C.caminho_classificado(r.sensor, pid, ano)).exists():
                    continue
                C.rodar_ponto(ponto, ano, r.sensor, pacote, descartar_apos=True)
                total += 1
        print(f"  {r.site_id} + controle ok ({anos[0]}-{anos[-1]})")
    print(f"\n{total} ponto-ano novos classificados")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True, choices=["lista", "controles", "classificar"])
    args = ap.parse_args()
    {"lista": fase_lista, "controles": fase_controles, "classificar": fase_classificar}[args.fase]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
