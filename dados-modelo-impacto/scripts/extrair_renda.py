"""
Extrai renda media/per capita municipal (IBGE) para os 19 sites (18 municipios unicos) deste
apoio.

Fonte (confirmada por pesquisa na API de Agregados do IBGE antes de escrever este script — ver
raw/renda/METODOLOGIA.md para o detalhe completo, incluindo as ~30 tabelas SIDRA descartadas no
caminho):

  SIDRA tabela 10295 — "Moradores em domicilios particulares permanentes ocupados, exclusive os
  cuja condicao no domicilio era pensionista, empregado(a) domestico(a) ou parente do(a)
  empregado(a) domestico(a), valor do rendimento domiciliar mensal per capita, medio e mediano,
  por sexo, cor ou raca e grupos de idade" — resultado do Censo Demografico 2022, unico ano
  disponivel (Censo nao e anual).
    GET https://servicodados.ibge.gov.br/api/v3/agregados/10295/periodos/2022/variaveis/13431|13534
        ?localidades=N6[{codigo_ibge}]&classificacao=2[6794]|86[95251]|58[95253]
  onde 6794/95251/95253 sao as categorias "Total" de Sexo/Cor ou raca/Grupo de idade (fixadas em
  Total para nao pegar uma celula desagregada), variavel 13431 = valor medio, 13534 = valor
  mediano.

RESSALVA IMPORTANTE (ler antes de usar o CSV gerado): renda em nivel municipal e dado de
CONTEXTO/ESTRATIFICACAO, nao evidencia de impacto causado por um data center especifico — mesma
logica ja registrada para populacao e emprego em dados-modelo-impacto/raw/{populacao,emprego}/
METODOLOGIA.md e em docs/requisitos-dados-externos.md (raiz do repo), secao 2.

Uso:
    python extrair_renda.py

Nao recebe argumentos. Le config/sites.geojson (+ 3 sites novos em _sites_ibge_common.py),
escreve:
  - dados-modelo-impacto/raw/renda/*.json (localidades + respostas da tabela 10295)
  - dados-modelo-impacto/processed/renda_municipal.csv
"""

from __future__ import annotations

import csv
from datetime import date

from _sites_ibge_common import (
    APOIO_DIR,
    http_get_json,
    load_sites_19,
    municipios_unicos,
    resolve_codigos_ibge,
    save_raw,
)
import time

RAW_DIR = APOIO_DIR / "raw" / "renda"
PROCESSED_CSV = APOIO_DIR / "processed" / "renda_municipal.csv"

AGREGADO_RENDA = 10295
ANO_CENSO2022 = 2022
VAR_MEDIA = 13431
VAR_MEDIANA = 13534
# Sexo=Total(6794), Cor ou raca=Total(95251), Grupo de idade=Total(95253)
CLASSIFICACAO_TOTAL = "2[6794]|86[95251]|58[95253]"
RENDA_URL = (
    f"https://servicodados.ibge.gov.br/api/v3/agregados/{AGREGADO_RENDA}"
    f"/periodos/{ANO_CENSO2022}/variaveis/{VAR_MEDIA}|{VAR_MEDIANA}"
    "?localidades=N6[{codigo}]&classificacao=" + CLASSIFICACAO_TOTAL
)

REQUEST_SLEEP_SECONDS = 0.3

CSV_COLUMNS = [
    "site_id",
    "municipio",
    "uf",
    "codigo_ibge",
    "ano",
    "renda_media_per_capita_reais",
    "renda_mediana_per_capita_reais",
    "fonte",
    "data_extracao",
    "origem_lista",
]


def coletar_renda_municipio(municipio: str, uf: str, codigo: int) -> tuple[float | None, float | None]:
    url = RENDA_URL.format(codigo=codigo)
    print(f"[renda] {municipio}/{uf} (codigo {codigo}) GET {url}")
    try:
        data, raw_bytes = http_get_json(url)
    except Exception as e:
        print(f"  ERRO ao buscar renda de {municipio}/{uf}: {e}")
        return None, None
    save_raw(RAW_DIR, f"renda_censo2022_{codigo}_{municipio}_{uf}.json".replace(" ", "_"), raw_bytes)

    media = mediana = None
    for bloco in data:
        var_id = int(bloco["id"])
        try:
            valor_str = bloco["resultados"][0]["series"][0]["serie"][str(ANO_CENSO2022)]
        except (KeyError, IndexError, TypeError):
            continue
        if valor_str in ("-", "..", "...", None):
            continue
        valor = float(valor_str)
        if var_id == VAR_MEDIA:
            media = valor
        elif var_id == VAR_MEDIANA:
            mediana = valor
    time.sleep(REQUEST_SLEEP_SECONDS)
    return media, mediana


def main() -> None:
    sites = load_sites_19()
    print(f"Sites carregados: {len(sites)} (16 validados + 3 datacentermap_novo)")

    municipios = municipios_unicos(sites)
    print(f"Municipios unicos: {len(municipios)}")

    codigos = resolve_codigos_ibge(sites, RAW_DIR)

    resultados: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    for municipio, uf in municipios:
        codigo = codigos[(municipio, uf)]["codigo_ibge"]
        resultados[(municipio, uf)] = coletar_renda_municipio(municipio, uf, codigo)

    data_extracao = date.today().isoformat()
    fonte = ("IBGE - Censo Demografico 2022, SIDRA tabela 10295 (Moradores em domicilios "
             "particulares permanentes ocupados... valor do rendimento domiciliar mensal per "
             "capita, medio e mediano)")

    linhas = []
    gaps = []
    for s in sites:
        key = (s["municipio"], s["uf"])
        codigo = codigos[key]["codigo_ibge"]
        media, mediana = resultados[key]
        if media is None and mediana is None:
            gaps.append(f"{s['site_id']} ({s['municipio']}/{s['uf']}) - Censo 2022 sem valor publicado")
            continue
        linhas.append({
            "site_id": s["site_id"],
            "municipio": s["municipio"],
            "uf": s["uf"],
            "codigo_ibge": codigo,
            "ano": ANO_CENSO2022,
            "renda_media_per_capita_reais": media,
            "renda_mediana_per_capita_reais": mediana,
            "fonte": fonte,
            "data_extracao": data_extracao,
            "origem_lista": s["origem_lista"],
        })

    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sorted(linhas, key=lambda r: r["site_id"]):
            writer.writerow(row)

    print()
    print(f"CSV escrito em {PROCESSED_CSV} — {len(linhas)} linhas (site x ano-censo).")
    print(f"Sites esperados: {len(sites)} (1 ano cada, Censo 2022 — dado nao e anual).")
    if gaps:
        print(f"Lacunas: {len(gaps)}")
        for g in gaps:
            print(f"  - {g}")
    else:
        print("Nenhuma lacuna: todos os 19 sites tem renda per capita do Censo 2022.")


if __name__ == "__main__":
    main()
