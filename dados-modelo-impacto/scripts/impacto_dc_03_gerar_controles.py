"""Passo 3 — gerar candidatos a controle e escolher, para cada campus, o mais parecido segundo o
CLASSIFICADOR (Random Forest `rf_v1.0-tuned`), não segundo o MapBiomas.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_03_gerar_controles.py [--force] [--sites a,b]

Este passo NÃO reimplementa a geração de candidatos: importa `gerar_controles_pareados.py`, que
já traz o desenho de SV-29 validado na rodada anterior (grade de 7 raios x 24 azimutes no anel
15-40 km, sorteio determinístico por site, filtros geométricos de contaminação e sobreposição de
buffer, e filtro de mesmo município / mesma microrregião do IBGE). A única coisa nova aqui é o
CRITÉRIO DE ESCOLHA final entre os candidatos válidos.

## Por que duas etapas de pareamento (MapBiomas e depois RF)

A rodada anterior escolhia o controle pela distância L1 da distribuição de classes do **MapBiomas
Coleção 9**, que é uma consulta server-side no Earth Engine: custa uma chamada e nenhum download.
O pedido desta rodada é escolher pela saída do **nosso classificador**, que é outra história de
custo: cada ponto exige baixar o composto de 6 bandas, calcular os 7 índices e rodar o modelo —
~23 s por ponto-ano. Com ~20 candidatos válidos por campus x 15 campi, seriam ~300 pontos, quase
2 h de chamadas de rede encadeadas.

O desenho aqui é em funil, e a divisão é deliberada:

1. **Pré-ranqueamento por MapBiomas** (grátis) ordena os até 20 candidatos válidos daquele campus;
2. **os `FINALISTAS_RF` melhores** passam pelo classificador de verdade;
3. **a escolha final é do RF** — o L1 do MapBiomas nunca decide o vencedor, só decide quem entra
   na final.

O que isso troca: se o melhor candidato pelo RF estivesse fora do top-5 do MapBiomas, ele não seria
avaliado. As duas medidas são correlacionadas (medem a mesma cobertura do solo no mesmo buffer, no
mesmo ano), mas não são a mesma coisa — então este é um custo real, assumido e registrado. O CSV
`candidatos_avaliados_rf.csv` publica os dois L1 lado a lado de todos os finalistas, para dar para
conferir o quanto os dois critérios concordam.

## Saídas

- `raw/controles-rf/pareamento_controle_rf.csv` — 1 linha por campus: o par tratamento/controle
  (é a tabela pedida no passo 5 do briefing).
- `raw/controles-rf/candidatos_avaliados_rf.csv` — todos os finalistas, com L1 MapBiomas e L1 RF.
- `raw/controles-rf/sites_controle_rf.geojson` — os controles no mesmo schema de
  `config/sites.geojson`, para os passos seguintes reusarem os módulos de `src/sentinela/`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gerar_controles_pareados as G
import impacto_dc_comum as C

# Quantos dos candidatos pré-ranqueados pelo MapBiomas passam pelo classificador. 5 é o ponto onde
# o custo (5 x 15 = 75 pontos-ano, ~30 min) ainda cabe numa execução síncrona e a final tem
# alternativa real — com 1 não haveria escolha pelo RF nenhuma, e com 20 seriam ~2 h.
FINALISTAS_RF = 5

OUT_PAREAMENTO = C.DIR_SAIDA / "pareamento_controle_rf.csv"
OUT_CANDIDATOS = C.DIR_SAIDA / "candidatos_avaliados_rf.csv"
OUT_GEOJSON = C.DIR_SAIDA / "sites_controle_rf.geojson"
CHECKPOINT = C.DIR_SAIDA / "_checkpoint_passo3.json"


def coletar_candidatos_validos(
    campus: dict[str, Any],
    pontos_contaminacao: list[dict],
    buffers_ocupados: list[tuple[float, float, float]],
    cache: G.CacheGeo,
) -> tuple[list[dict], dict[str, int]]:
    """Grade + sorteio determinístico + filtros geométricos + filtro de município.

    Reimplementa só o LAÇO de `gerar_controles_pareados.buscar_controle`, chamando as mesmas
    funções dele — precisamos parar antes da escolha por MapBiomas, que lá é o passo final.
    """
    site_id = campus["site_id"]
    grade = G.grade_candidatos(campus["lat"], campus["lon"])
    rng = G.rng_do_site(site_id)
    ordem = rng.permutation(len(grade))

    validos: list[dict] = []
    contadores = {"tentativas_geocode": 0, "rejeitados_geometria": 0, "rejeitados_municipio": 0}

    for idx in ordem:
        if len(validos) >= G.MIN_CANDIDATOS_MUNICIPIO_VALIDO:
            break
        if contadores["tentativas_geocode"] >= G.MAX_TENTATIVAS_MUNICIPIO:
            break
        lat, lon, raio = grade[int(idx)]

        ok, _motivo = G.passa_filtros_baratos(lat, lon, pontos_contaminacao, buffers_ocupados)
        if not ok:
            contadores["rejeitados_geometria"] += 1
            continue

        contadores["tentativas_geocode"] += 1
        ok_mun, metodo, municipio, uf = G.checar_municipio(
            lat, lon, campus["municipio"], campus["uf"], cache
        )
        if not ok_mun:
            contadores["rejeitados_municipio"] += 1
            continue

        validos.append(
            {
                "lat": lat,
                "lon": lon,
                "raio_nominal_km": raio,
                "dist_ao_tratamento_km": round(
                    C.distancia_km(lat, lon, campus["lat"], campus["lon"]), 3
                ),
                "metodo_municipio": metodo,
                "municipio": municipio,
                "uf": uf,
            }
        )
    return validos, contadores


def prerank_mapbiomas(
    campus: dict[str, Any], validos: list[dict], ano_ref: int, cfg_labels: dict
) -> list[dict]:
    """Ordena os candidatos válidos por L1 do MapBiomas contra o tratamento, no ano de
    referência (grampeado à janela da Coleção 9, mesmo mecanismo de `sentinela.gee.labels`)."""
    ano_efetivo, dist_safra = G.ano_mapbiomas_efetivo(
        ano_ref, int(cfg_labels["ano_mapbiomas_min"]), int(cfg_labels["ano_mapbiomas_max"])
    )
    colecao = cfg_labels["colecao_mapbiomas"]

    dist_trat = G.distribuicao_mapbiomas(
        campus["lat"], campus["lon"], C.BUFFER_KM, ano_efetivo, colecao
    )
    if dist_trat is None:
        raise RuntimeError(
            f"MapBiomas não retornou distribuição para o tratamento {campus['site_id']} "
            f"em {ano_efetivo} — sem base de comparação para pré-ranquear."
        )

    for cand in validos:
        d = G.distribuicao_mapbiomas(cand["lat"], cand["lon"], C.BUFFER_KM, ano_efetivo, colecao)
        cand["l1_mapbiomas"] = None if d is None else round(G.l1_distancia(dist_trat, d), 6)
        cand["ano_mapbiomas"] = ano_efetivo
        cand["distancia_safra_mapbiomas"] = dist_safra

    com_l1 = [c for c in validos if c["l1_mapbiomas"] is not None]
    return sorted(com_l1, key=lambda c: c["l1_mapbiomas"])


def avaliar_finalistas_com_rf(
    campus: dict[str, Any], finalistas: list[dict], ano_ref: int, sensor: str, pacote: dict
) -> list[dict]:
    """Roda o classificador em cada finalista no ano de referência e calcula o L1 contra o
    tratamento — a medida que decide o vencedor."""
    area_trat = C.area_por_classe(sensor, campus["site_id"], ano_ref)

    for i, cand in enumerate(finalistas, 1):
        ctrl_id = f"ctrl-{campus['site_id']}-p{i:02d}"
        ponto = {
            "site_id": ctrl_id,
            "lat": cand["lat"],
            "lon": cand["lon"],
            "buffer_km": C.BUFFER_KM,
        }
        print(f"    finalista {i}/{len(finalistas)} {ctrl_id} (L1_mapbiomas={cand['l1_mapbiomas']:.4f}) ...")
        C.rodar_ponto(ponto, ano_ref, sensor, pacote, descartar_apos=True)
        area_ctrl = C.area_por_classe(sensor, ctrl_id, ano_ref)
        cand["site_id_controle"] = ctrl_id
        cand["l1_rf"] = round(C.distancia_l1(area_trat, area_ctrl), 6)
        cand["pixels_validos_controle"] = area_ctrl["pixels_validos"]
        for cid in C.CLASS_IDS:
            nome = C.CLASSE_NOME[cid]
            cand[f"prop_{nome}"] = area_ctrl[f"prop_{nome}"]
        print(f"      L1_rf={cand['l1_rf']:.4f} ({C.qualidade_l1(cand['l1_rf'])})")
    return sorted(finalistas, key=lambda c: c["l1_rf"])


def processar_campus(
    campus: dict[str, Any],
    pontos_contaminacao: list[dict],
    buffers_ocupados: list[tuple[float, float, float]],
    cache: G.CacheGeo,
    cfg_labels: dict,
    pacote: dict,
) -> dict[str, Any]:
    ano_ref = C.ano_referencia_pareamento(campus["ano_inicio_obra"])
    sensor = C.sensor_da_janela(C.janela_anos(campus["ano_inicio_obra"]))
    print(f"  ano de referência (1 ano antes da obra) = {ano_ref}, sensor = {sensor}")

    validos, contadores = coletar_candidatos_validos(campus, pontos_contaminacao, buffers_ocupados, cache)
    print(
        f"  candidatos válidos: {len(validos)} "
        f"(geocodes={contadores['tentativas_geocode']}, "
        f"rejeitados geometria={contadores['rejeitados_geometria']}, "
        f"município={contadores['rejeitados_municipio']})"
    )
    if not validos:
        return {
            "status": "sem_candidato",
            "motivo": (
                "nenhum ponto da grade 15-40 km passou nos filtros geométricos + município "
                f"dentro do teto de {G.MAX_TENTATIVAS_MUNICIPIO} tentativas de reverse-geocode"
            ),
            "contadores": contadores,
        }

    ranqueados = prerank_mapbiomas(campus, validos, ano_ref, cfg_labels)
    if not ranqueados:
        return {
            "status": "sem_candidato",
            "motivo": "MapBiomas não retornou distribuição para nenhum candidato válido",
            "contadores": contadores,
        }

    finalistas = ranqueados[:FINALISTAS_RF]
    print(f"  {len(finalistas)} finalista(s) para o classificador (de {len(ranqueados)} ranqueados)")
    avaliados = avaliar_finalistas_com_rf(campus, finalistas, ano_ref, sensor, pacote)
    vencedor = avaliados[0]

    return {
        "status": "ok",
        "ano_referencia": ano_ref,
        "sensor": sensor,
        "n_candidatos_validos": len(validos),
        "n_ranqueados_mapbiomas": len(ranqueados),
        "contadores": contadores,
        "finalistas": avaliados,
        "vencedor": vencedor,
    }


def montar_saidas(campi: list[dict], checkpoint: C.Checkpoint) -> None:
    linhas_par, linhas_cand, feats = [], [], []
    for campus in campi:
        r = checkpoint.get(campus["site_id"])
        if not r:
            continue
        if r["status"] != "ok":
            linhas_par.append(
                {
                    "site_id": campus["site_id"],
                    "municipio": campus["municipio"],
                    "uf": campus["uf"],
                    "lat": campus["lat"],
                    "lon": campus["lon"],
                    "ano_inicio_obra": campus["ano_inicio_obra"],
                    "status": r["status"],
                    "motivo": r.get("motivo"),
                }
            )
            continue

        v = r["vencedor"]
        linhas_par.append(
            {
                "site_id": campus["site_id"],
                "municipio": campus["municipio"],
                "uf": campus["uf"],
                "lat": campus["lat"],
                "lon": campus["lon"],
                "ano_inicio_obra": campus["ano_inicio_obra"],
                "ano_referencia_pareamento": r["ano_referencia"],
                "sensor": r["sensor"],
                "site_id_controle": v["site_id_controle"],
                "lat_controle": round(v["lat"], 6),
                "lon_controle": round(v["lon"], 6),
                "dist_tratamento_controle_km": v["dist_ao_tratamento_km"],
                "municipio_controle": v["municipio"],
                "uf_controle": v["uf"],
                "metodo_municipio": v["metodo_municipio"],
                "l1_rf": v["l1_rf"],
                "l1_mapbiomas": v["l1_mapbiomas"],
                "qualidade": C.qualidade_l1(v["l1_rf"]),
                "n_candidatos_validos": r["n_candidatos_validos"],
                "n_finalistas_rf": len(r["finalistas"]),
                "status": "ok",
                "motivo": None,
            }
        )
        for pos, cand in enumerate(r["finalistas"], 1):
            linhas_cand.append(
                {
                    "site_id": campus["site_id"],
                    "site_id_controle": cand["site_id_controle"],
                    "posicao_final_rf": pos,
                    "lat": round(cand["lat"], 6),
                    "lon": round(cand["lon"], 6),
                    "dist_ao_tratamento_km": cand["dist_ao_tratamento_km"],
                    "l1_mapbiomas": cand["l1_mapbiomas"],
                    "l1_rf": cand["l1_rf"],
                    "qualidade_rf": C.qualidade_l1(cand["l1_rf"]),
                    "municipio": cand["municipio"],
                    "uf": cand["uf"],
                    "metodo_municipio": cand["metodo_municipio"],
                    "escolhido": pos == 1,
                }
            )
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(v["lon"], 6), round(v["lat"], 6)]},
                "properties": {
                    "site_id": v["site_id_controle"],
                    "lat": round(v["lat"], 6),
                    "lon": round(v["lon"], 6),
                    "buffer_km": C.BUFFER_KM,
                    "tipo": "controle",
                    "pareado_com": campus["site_id"],
                    "ano_inicio_obra_do_tratamento": campus["ano_inicio_obra"],
                    "municipio": v["municipio"],
                    "uf": v["uf"],
                    "l1_rf": v["l1_rf"],
                    "qualidade": C.qualidade_l1(v["l1_rf"]),
                },
            }
        )

    C.salvar_csv(pd.DataFrame(linhas_par), OUT_PAREAMENTO)
    C.salvar_csv(pd.DataFrame(linhas_cand), OUT_CANDIDATOS)
    OUT_GEOJSON.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  -> {OUT_GEOJSON.relative_to(C.REPO_ROOT)} ({len(feats)} controles)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera controles pareados pelo classificador RF (passo 3).")
    parser.add_argument("--force", action="store_true", help="ignora o checkpoint e refaz todos")
    parser.add_argument("--sites", default=None, help="lista de site_id separada por vírgula")
    args = parser.parse_args(argv)
    filtro = {s.strip() for s in args.sites.split(",")} if args.sites else None

    C.DIR_SAIDA.mkdir(parents=True, exist_ok=True)
    C.iniciar_ee()
    pacote = C.carregar_modelo()
    cfg_labels = G.SETTINGS.params()["labels"]

    cache = G.CacheGeo(G.CACHE_GEO_PATH)
    sites_tratamento = G.carregar_sites_tratamento()
    pontos_contaminacao = G.carregar_pontos_contaminacao(sites_tratamento, cache)
    print(f"{len(pontos_contaminacao)} pontos de contaminação carregados")

    campi = C.carregar_campi()
    checkpoint = C.Checkpoint(CHECKPOINT)
    if args.force:
        checkpoint.dados = {}

    # Os 16 buffers de tratamento sempre contam como ocupados. Os controles da rodada ANTERIOR
    # (`raw/controles/`) deliberadamente NÃO entram: aquela rodada é um pareamento paralelo pelo
    # MapBiomas, que esta substitui para esta frente — bloquear as posições dela impediria esta
    # rodada de escolher o melhor ponto pelo RF sem nenhum ganho de isolamento.
    buffers_ocupados: list[tuple[float, float, float]] = [
        (s["lat"], s["lon"], s["buffer_km"]) for s in sites_tratamento
    ]
    for site_id, r in checkpoint.dados.items():
        if r.get("status") == "ok":
            v = r["vencedor"]
            buffers_ocupados.append((v["lat"], v["lon"], C.BUFFER_KM))

    for i, campus in enumerate(campi, 1):
        site_id = campus["site_id"]
        if checkpoint.get(site_id) and not args.force:
            print(f"[{i}/{len(campi)}] {site_id} — já processado (checkpoint), pulando")
            continue
        if filtro and site_id not in filtro:
            print(f"[{i}/{len(campi)}] {site_id} — fora do lote desta chamada (--sites)")
            continue

        print(f"[{i}/{len(campi)}] {site_id} ({campus['municipio']}/{campus['uf']})")
        try:
            r = processar_campus(campus, pontos_contaminacao, buffers_ocupados, cache, cfg_labels, pacote)
        except Exception as exc:  # noqa: BLE001 — falha de rede num site não mata o lote
            r = {"status": "erro", "motivo": repr(exc)}
            print(f"  FALHOU: {exc!r}")
        checkpoint.set(site_id, r)
        if r["status"] == "ok":
            v = r["vencedor"]
            buffers_ocupados.append((v["lat"], v["lon"], C.BUFFER_KM))
            print(
                f"  -> controle {v['site_id_controle']} a {v['dist_ao_tratamento_km']} km, "
                f"L1_rf={v['l1_rf']:.4f} ({C.qualidade_l1(v['l1_rf'])})"
            )
        cache.salvar()

    print()
    montar_saidas(campi, checkpoint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
