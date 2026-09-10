"""Passo 8 — temperatura de superfície (LST) para os 30 pontos do painel, tratamento E controle.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_08_lst_pontos.py [--force] [--pares a,b]

Por que não dá para reusar `processed/temperatura_lst.csv` como está:

1. **Ele só cobre tratamento.** Um grupo de controle existe para dar contrafactual; LST só do lado
   tratado volta a ser contexto, não evidência de efeito.
2. **Ele começa em 2016.** Cinco campi têm janela começando antes (`ascenty-maracanau` em 2013,
   `ascenty-hortolandia` em 2015, `angonap-fortaleza`/`ascenty-sumare`/`hostdime-joao-pessoa` em
   2014). O MOD11A2 cobre desde 2000 — o corte em 2016 veio do briefing anterior ("10 anos de
   histórico"), não da fonte. Aqui a série vai de 2013, o piso da janela deste estudo.

A extração em si NÃO é reimplementada: importa `extrair_valores_ano` de
`extrair_temperatura_lst.py`, a mesma função, mesma coleção (`MODIS/061/MOD11A2`, banda
`LST_Day_1km`, composto de 8 dias, 1 km) e mesmo redutor. **Tratamento e controle passam pelo
mesmo caminho de código na mesma execução** — a mesma disciplina que a regra de sensor único
aplica à cobertura do solo: se as duas pontas de uma comparação vierem de fontes ou versões
diferentes, a diferença entre elas deixa de ser interpretável.

Saída: `raw/controles-rf/lst_pontos.csv` — 1 linha por (ponto, ano), com média, desvio, mediana e
o número de cenas MOD11A2 válidas que entraram na média.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ee
import extrair_temperatura_lst as LST
import impacto_dc_04_painel_features as P4
import impacto_dc_comum as C

SAIDA = C.DIR_SAIDA / "lst_pontos.csv"
CHECKPOINT = C.DIR_SAIDA / "_checkpoint_passo8.json"

# Faixa de sanidade herdada de `extrair_temperatura_lst.py`: LST de superfície no Brasil deveria
# ficar entre ~10 e 50 C. Fora disso é sinal de erro de escala/unidade — reportado, não bloqueante
# (solo exposto e urbano denso passam de 45 C legitimamente em dia quente).
FAIXA_SANIDADE_C = LST.FAIXA_SANIDADE_C


def pontos_do_painel(pares: pd.DataFrame, filtro: set[str] | None) -> list[dict[str, Any]]:
    """Os 30 pontos (15 tratamentos + 15 controles) com os anos da janela de cada par.

    Os anos vêm de `impacto_dc_04.anos_do_par`, a MESMA função que define o painel de cobertura
    do solo — assim LST e área por classe existem exatamente para os mesmos (ponto, ano), e o
    join do passo 10 não abre buraco.
    """
    props = C.carregar_sites_validados()
    campi = {c["site_id"]: c for c in C.carregar_campi()}
    pontos = []
    for _, r in pares[pares["status"] == "ok"].iterrows():
        site_id = r["site_id"]
        if filtro and site_id not in filtro:
            continue
        anos, _fim = P4.anos_do_par(campi[site_id], props[site_id], r["sensor"])
        pontos.append({
            "site_id": site_id, "tipo": "tratamento", "pareado_com": site_id,
            "lat": campi[site_id]["lat"], "lon": campi[site_id]["lon"], "anos": anos,
            "municipio": campi[site_id]["municipio"], "uf": campi[site_id]["uf"],
        })
        pontos.append({
            "site_id": r["site_id_controle"], "tipo": "controle", "pareado_com": site_id,
            "lat": float(r["lat_controle"]), "lon": float(r["lon_controle"]), "anos": anos,
            "municipio": r["municipio_controle"], "uf": r["uf_controle"],
        })
    return pontos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LST por ponto do painel (passo 8).")
    parser.add_argument("--force", action="store_true", help="ignora o checkpoint e refaz tudo")
    parser.add_argument("--pares", default=None, help="lista de site_id (do tratamento) separada por vírgula")
    args = parser.parse_args(argv)
    filtro = {s.strip() for s in args.pares.split(",")} if args.pares else None

    caminho_pares = C.DIR_SAIDA / "pareamento_controle_rf.csv"
    if not caminho_pares.exists():
        print(f"ERRO: {caminho_pares} não existe — rode o passo 3 antes.", file=sys.stderr)
        return 1
    pares = pd.read_csv(caminho_pares)
    pontos = pontos_do_painel(pares, filtro)
    total = sum(len(p["anos"]) for p in pontos)
    print(f"Passo 8 — LST de {len(pontos)} pontos ({total} pares ponto×ano), coleção {LST.COLLECTION_ID}")

    C.iniciar_ee()
    checkpoint = C.Checkpoint(CHECKPOINT)
    if args.force:
        checkpoint.dados = {}

    linhas: list[dict[str, Any]] = []
    fora_da_faixa: list[str] = []
    sem_cena: list[str] = []
    feitos = 0

    for ponto in pontos:
        geom = ee.Geometry.Point(ponto["lon"], ponto["lat"]).buffer(C.BUFFER_KM * 1000)
        for ano in ponto["anos"]:
            chave = f"{ponto['site_id']}/{ano}"
            registro = checkpoint.get(chave)
            if registro is None:
                t0 = time.time()
                try:
                    valores = LST.extrair_valores_ano(geom, ano)
                except Exception as exc:  # noqa: BLE001 — falha de rede não mata o lote
                    print(f"  {chave} FALHOU: {exc!r}")
                    checkpoint.set(chave, {"erro": repr(exc)})
                    continue
                registro = {
                    "n_cenas": len(valores),
                    "media": round(statistics.fmean(valores), 4) if valores else None,
                    "mediana": round(statistics.median(valores), 4) if valores else None,
                    "desvio": round(statistics.stdev(valores), 4) if len(valores) > 1 else None,
                }
                checkpoint.set(chave, registro)
                feitos += 1
                print(f"  {chave}: {registro['n_cenas']} cenas, "
                      f"media={registro['media']} C ({time.time() - t0:.0f}s)")

            if registro.get("erro"):
                continue
            if not registro["n_cenas"]:
                sem_cena.append(chave)
            elif not (FAIXA_SANIDADE_C[0] <= registro["media"] <= FAIXA_SANIDADE_C[1]):
                fora_da_faixa.append(f"{chave}={registro['media']}C")

            linhas.append({
                "site_id": ponto["site_id"], "tipo": ponto["tipo"], "pareado_com": ponto["pareado_com"],
                "municipio": ponto["municipio"], "uf": ponto["uf"], "ano": ano,
                "lst_media_celsius": registro["media"], "lst_mediana_celsius": registro["mediana"],
                "lst_desvio_celsius": registro["desvio"], "lst_n_cenas": registro["n_cenas"],
                "fonte": LST.FONTE, "colecao_gee": LST.COLLECTION_ID,
                "data_extracao": datetime.now(UTC).date().isoformat(),
            })

    df = pd.DataFrame(linhas).sort_values(["pareado_com", "tipo", "ano"]).reset_index(drop=True)
    C.salvar_csv(df, SAIDA)

    print()
    print(f"{feitos} consulta(s) novas ao Earth Engine; {len(df)} linhas no total.")
    cob = df.groupby("tipo")["lst_media_celsius"].agg(["count", "mean"])
    print(cob.round(2).to_string())
    if sem_cena:
        print(f"ACHADO: {len(sem_cena)} ponto-ano sem nenhuma cena MOD11A2 válida: {sem_cena[:6]}")
    if fora_da_faixa:
        print(f"ACHADO: {len(fora_da_faixa)} ponto-ano fora da faixa de sanidade "
              f"{FAIXA_SANIDADE_C[0]}-{FAIXA_SANIDADE_C[1]} C: {fora_da_faixa[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
