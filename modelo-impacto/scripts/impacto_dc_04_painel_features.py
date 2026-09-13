"""Passo 4 — painel final de features: área por classe, por ano, para cada ponto de cada par.

Rode com:

    python modelo-impacto/scripts/impacto_dc_04_painel_features.py [--force] [--sites a,b]

É a tabela que o modelo de impacto do Guilherme consome. Uma linha por (ponto, ano), com as 5
classes do classificador em colunas — formato largo, que é o que um regressor espera; a versão
longa sai de um `melt` se precisar.

## Anos de cada par

`obra-3 .. obra+3`, mais o **ano de fim de obra** (final de `periodo_durante` em
`config/sites.geojson`) quando ele cai fora dessa faixa. Hoje isso só acontece em
`ascenty-hortolandia` (obra 2018, fim 2022, janela 2015-2021).

Tratamento e controle usam SEMPRE os mesmos anos e o MESMO sensor — é o ponto central do desenho.
`sentinela.gee.harmonizacao` reduz o resíduo espectral entre Landsat e Sentinel-2, mas SV-20
(`reports/validacao_sensores.md`) mediu que, na SAÍDA do classificador, o degrau 2018->2019 da
classe "solo exposto/obras" é indistinguível do artefato de instrumento em 48 de 48 pares. Uma
janela que atravessa a fronteira mede a troca de satélite, não a obra. Por isso a ingestão Landsat
foi estendida até 2024 no passo 2: com isso 12 dos 15 campi ficam inteiramente em Landsat, e os
outros 3 (obra em 2022/2023) inteiramente em Sentinel-2.

## Colunas de junção com a lista do Guilherme

`ids_datacenter` e `n_predios` vêm de `reconciliacao_datacenters.csv` (passo 1): os 12
`id_datacenter` da planilha dele correspondem a 8 campi, porque vários são prédios do mesmo
campus a dezenas de metros um do outro — dentro de um buffer de 5 km, o mesmo recorte de terreno.
A medição é por campus; estas colunas deixam ele dar o join pela chave dele sem que a gente finja
que Hortolândia são quatro observações independentes.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C

ENTRADA_PAREAMENTO = C.DIR_SAIDA / "pareamento_controle_rf.csv"
ENTRADA_RECONCILIACAO = C.DIR_SAIDA / "reconciliacao_datacenters.csv"
SAIDA_PAINEL = C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv"
CHECKPOINT = C.DIR_SAIDA / "_checkpoint_passo4.json"


def ano_fim_obra(props: dict[str, Any]) -> int | None:
    """Último ano de `periodo_durante` — a melhor aproximação de "obra terminou" que o repo tem.

    `ano_inicio_operacao_estimado` não serve: nos 15 sites validados ele é igual ao início da obra
    em 7 casos (a obra e a operação teriam começado no mesmo ano), o que o torna inútil como marca
    de FIM. `periodo_durante` foi montado justamente para delimitar a fase de construção.
    """
    dur = props.get("periodo_durante")
    if not dur or "-" not in str(dur):
        return None
    return int(str(dur).split("-")[1])


def anos_do_par(campus: dict[str, Any], props: dict[str, Any], sensor: str) -> tuple[list[int], int | None]:
    """Anos a medir, e o ano de fim de obra do campus.

    O ano de fim de obra é devolvido SEMPRE que `config/sites.geojson` o conhece, esteja ele
    dentro ou fora da janela — quem consome usa esse ano para classificar cada linha em
    `pre`/`durante`/`pos`, e não saber onde a obra terminou faria toda a fase de construção ser
    rotulada como `pos`. Ele é ACRESCENTADO à lista de anos só quando cai fora da janela
    `obra-3 .. obra+3` e ainda cabe no sensor dela.
    """
    anos = list(C.janela_anos(campus["ano_inicio_obra"]))
    fim = ano_fim_obra(props)
    if fim is not None and fim not in anos:
        limites = (
            (C.LANDSAT_ANO_MIN, C.LANDSAT_ANO_MAX) if sensor == "landsat" else (C.S2_ANO_MIN, C.S2_ANO_MAX)
        )
        if limites[0] <= fim <= limites[1]:
            anos.append(fim)
        else:
            # Reportado, não silencioso: medir este ano exigiria trocar de sensor no meio da
            # série, que é exatamente o que o desenho evita. O ano segue valendo para a fase.
            print(
                f"    ACHADO [{campus['site_id']}]: ano de fim de obra {fim} está fora da cobertura "
                f"de {sensor} ({limites[0]}-{limites[1]}) — não medido, para não cruzar sensor."
            )
    return sorted(set(anos)), fim


def fase(ano: int, ano_obra: int, fim: int | None) -> str:
    if ano < ano_obra:
        return "pre"
    if fim is not None and ano > fim:
        return "pos"
    if fim is None and ano > ano_obra:
        return "pos"
    return "durante"


def linha_do_ponto(
    site_id: str,
    tipo: str,
    campus: dict[str, Any],
    pareado_com: str,
    ano: int,
    sensor: str,
    fim: int | None,
    ids_dc: str,
    n_predios: int,
    extra: dict[str, Any],
) -> dict[str, Any]:
    area = C.area_por_classe(sensor, site_id, ano)
    linha: dict[str, Any] = {
        "site_id": site_id,
        "tipo": tipo,
        "pareado_com": pareado_com,
        "ids_datacenter": ids_dc,
        "n_predios_no_campus": n_predios,
        "municipio": extra.get("municipio"),
        "uf": extra.get("uf"),
        "lat": extra.get("lat"),
        "lon": extra.get("lon"),
        "buffer_km": C.BUFFER_KM,
        "ano": ano,
        "ano_inicio_obra": campus["ano_inicio_obra"],
        "ano_fim_obra": fim,
        "ano_relativo_ao_inicio_obra": ano - campus["ano_inicio_obra"],
        "fase": fase(ano, campus["ano_inicio_obra"], fim),
        "sensor": area["sensor"],
        "resolucao_m": area["resolucao_m"],
        "pixels_validos": area["pixels_validos"],
        "modelo_versao": area["modelo_versao"],
    }
    for cid in C.CLASS_IDS:
        nome = C.CLASSE_NOME[cid]
        linha[f"area_ha_{nome}"] = area[f"area_ha_{nome}"]
    for cid in C.CLASS_IDS:
        nome = C.CLASSE_NOME[cid]
        linha[f"prop_{nome}"] = area[f"prop_{nome}"]
    return linha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Painel final de features por ano (passo 4).")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sites", default=None, help="lista de site_id separada por vírgula")
    args = parser.parse_args(argv)
    filtro = {s.strip() for s in args.sites.split(",")} if args.sites else None

    if not ENTRADA_PAREAMENTO.exists():
        print(f"ERRO: {ENTRADA_PAREAMENTO} não existe — rode o passo 3 antes.", file=sys.stderr)
        return 1

    pares = pd.read_csv(ENTRADA_PAREAMENTO)
    pares_ok = pares[pares["status"] == "ok"]
    print(f"Passo 4 — {len(pares_ok)} par(es) com controle (de {len(pares)} campi)")

    recon = pd.read_csv(ENTRADA_RECONCILIACAO) if ENTRADA_RECONCILIACAO.exists() else pd.DataFrame()
    ids_por_site: dict[str, str] = {}
    n_predios: dict[str, int] = {}
    if len(recon):
        for site_id, grp in recon.groupby("site_id"):
            ids_por_site[site_id] = ";".join(sorted(grp["id_datacenter"]))
            n_predios[site_id] = len(grp)

    C.iniciar_ee()
    pacote = C.carregar_modelo()
    props_por_site = C.carregar_sites_validados()
    campi = {c["site_id"]: c for c in C.carregar_campi()}
    checkpoint = C.Checkpoint(CHECKPOINT)

    linhas: list[dict[str, Any]] = []
    falhas: list[str] = []

    for _, par in pares_ok.iterrows():
        site_id = par["site_id"]
        if filtro and site_id not in filtro:
            continue
        campus = campi[site_id]
        sensor = par["sensor"]
        anos, fim = anos_do_par(campus, props_por_site[site_id], sensor)
        print(f"  {site_id}: anos {anos} ({sensor}), fim de obra = {fim or 'n/d'}")

        pontos = [
            (site_id, "tratamento", site_id, {"municipio": campus["municipio"], "uf": campus["uf"],
                                              "lat": campus["lat"], "lon": campus["lon"]}),
            (par["site_id_controle"], "controle", site_id,
             {"municipio": par["municipio_controle"], "uf": par["uf_controle"],
              "lat": par["lat_controle"], "lon": par["lon_controle"]}),
        ]

        for ponto_id, tipo, pareado, extra in pontos:
            for ano in anos:
                chave = f"{sensor}/{ponto_id}/{ano}"
                try:
                    if not C.caminho_classificado(sensor, ponto_id, ano).exists() or args.force:
                        t0 = time.time()
                        print(f"    {chave} ...")
                        C.rodar_ponto(
                            {"site_id": ponto_id, "lat": extra["lat"], "lon": extra["lon"],
                             "buffer_km": C.BUFFER_KM},
                            ano, sensor, pacote, force=args.force,
                            # Só o controle descarta os intermediários: os do tratamento pertencem
                            # ao pipeline do classificador principal, que espera encontrá-los.
                            descartar_apos=(tipo == "controle"),
                        )
                        print(f"    {chave} OK em {time.time() - t0:.0f}s")
                    linhas.append(
                        linha_do_ponto(
                            ponto_id, tipo, campus, pareado, ano, sensor, fim,
                            ids_por_site.get(site_id, ""), n_predios.get(site_id, 0), extra,
                        )
                    )
                    checkpoint.set(chave, "ok")
                except Exception as exc:  # noqa: BLE001 — uma falha não mata o painel inteiro
                    falhas.append(f"{chave}: {exc!r}")
                    checkpoint.set(chave, f"erro: {exc!r}")
                    print(f"    {chave} FALHOU: {exc!r}")

    df = pd.DataFrame(linhas).sort_values(["pareado_com", "tipo", "ano"]).reset_index(drop=True)
    C.salvar_csv(df, SAIDA_PAINEL)

    print()
    print(f"Painel: {len(df)} linhas, {df['site_id'].nunique()} pontos, "
          f"{df['pareado_com'].nunique()} pares, anos {df['ano'].min()}-{df['ano'].max()}")
    print(f"sensores: {df.groupby('sensor')['pareado_com'].nunique().to_dict()} pares")
    if falhas:
        print(f"{len(falhas)} falha(s) — rode de novo para retomar:")
        for f in falhas:
            print(f"  {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
