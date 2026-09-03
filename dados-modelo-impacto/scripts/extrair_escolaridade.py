"""
Extrai nivel de instrucao (escolaridade) municipal (IBGE, Censo) para os 19 sites (18 municipios
unicos) deste apoio.

Fonte (confirmada por pesquisa na API de Agregados do IBGE antes de escrever este script — ver
raw/escolaridade/METODOLOGIA.md): nivel de instrucao da populacao E DADO DE CENSO, nao anual — as
duas unicas leituras dentro da janela 2016-2025 sao o Censo 2010 (fora da janela, mas usado como
ponto de comparacao historico, igual ao que ja acontece com populacao) e o Censo 2022. Duas
tabelas SIDRA, uma por Censo (nomes de categoria de nivel de instrucao IGUAIS nas duas, o que
permite comparar 2010->2022 com uma ressalva de corte etario — ver abaixo):

  Censo 2022 — tabela 10061 "Pessoas de 18 anos ou mais de idade, por nivel de instrucao,
  segundo os grupos de idade, o sexo e a cor ou raca"
    GET https://servicodados.ibge.gov.br/api/v3/agregados/10061/periodos/2022/variaveis/2667
        ?localidades=N6[{codigo}]&classificacao=1568[all]|58[95253]|2[6794]|86[95251]

  Censo 2010 — tabela 3540 "Pessoas de 10 anos ou mais de idade, por nivel de instrucao, segundo
  a situacao do domicilio, o sexo, a cor ou raca e os grupos de idade"
    GET https://servicodados.ibge.gov.br/api/v3/agregados/3540/periodos/2010/variaveis/140
        ?localidades=N6[{codigo}]&classificacao=1568[all]|1[0]|2[0]|86[0]|58[0]

Ambas tem, alem da categoria "Total", 4 niveis de instrucao com o MESMO NOME nas duas tabelas
("Sem instrucao e fundamental incompleto", "Fundamental completo e medio incompleto", "Medio
completo e superior incompleto", "Superior completo") — usados aqui para permitir comparacao
2010 x 2022. A tabela 2010 tem uma 5a categoria "Nao determinado" (ignorada aqui, residual).

RESSALVA DE CORTE ETARIO — leia antes de comparar 2010 com 2022: a tabela do Censo 2022 mede
"pessoas de 18 anos ou mais", enquanto a tabela do Censo 2010 mede "pessoas de 10 anos ou mais".
NAO sao a mesma populacao-base — o Censo 2022 mudou o recorte etario padrao de divulgacao de
escolaridade (motivo provavel: alinhar com "pessoas em idade de ter concluido a educacao basica
plenamente", 18+, em vez do padrao antigo 10+). Isso significa que o `populacao_total` (categoria
"Total") de cada ano NAO e diretamente comparavel — a diferenca nao e so evolucao real de
escolaridade, e tambem mudanca de universo de contagem. Comparar as PROPORCOES (percentual por
nivel de instrucao dentro do total de cada ano/tabela) e mais defensavel do que comparar contagens
absolutas entre os dois anos — por isso o CSV inclui tanto a contagem quanto o percentual do total
geral (variavel companheira "...percentual do total geral" de cada tabela).

RESSALVA IMPORTANTE (ler antes de usar o CSV gerado): mesma logica de granularidade ja registrada
para populacao/emprego/PIB/renda/desemprego em dados-modelo-impacto/raw/*/METODOLOGIA.md e em
docs/requisitos-dados-externos.md (raiz do repo), secao 2 — e dado de CONTEXTO, nao evidencia de
impacto causado por um data center especifico.

Uso:
    python extrair_escolaridade.py

Nao recebe argumentos. Le config/sites.geojson (+ 3 sites novos em _sites_ibge_common.py),
escreve:
  - dados-modelo-impacto/raw/escolaridade/*.json (localidades + respostas das tabelas 10061/3540)
  - dados-modelo-impacto/processed/escolaridade_municipal.csv
"""

from __future__ import annotations

import csv
import time
from datetime import date

from _sites_ibge_common import (
    APOIO_DIR,
    http_get_json,
    load_sites_19,
    municipios_unicos,
    resolve_codigos_ibge,
    save_raw,
)

RAW_DIR = APOIO_DIR / "raw" / "escolaridade"
PROCESSED_CSV = APOIO_DIR / "processed" / "escolaridade_municipal.csv"

# Categorias de nivel de instrucao com nome identico nas duas tabelas (usadas para comparar
# 2010 x 2022 apesar do corte etario diferente — ver ressalva no docstring do modulo).
NIVEIS_COMPARAVEIS = [
    "Total",
    "Sem instrução e fundamental incompleto",
    "Fundamental completo e médio incompleto",
    "Médio completo e superior incompleto",
    "Superior completo",
]

FONTES = {
    2022: {
        "agregado": 10061,
        "var_contagem": 2667,
        "var_percentual": 1002667,
        "classificacao": "1568[all]|58[95253]|2[6794]|86[95251]",
        "faixa_etaria_base": "18 anos ou mais",
        "fonte": ("IBGE - Censo Demografico 2022, SIDRA tabela 10061 (Pessoas de 18 anos ou mais "
                  "de idade, por nivel de instrucao)"),
    },
    2010: {
        "agregado": 3540,
        "var_contagem": 140,
        "var_percentual": 1000140,
        "classificacao": "1568[all]|1[0]|2[0]|86[0]|58[0]",
        "faixa_etaria_base": "10 anos ou mais",
        "fonte": ("IBGE - Censo Demografico 2010, SIDRA tabela 3540 (Pessoas de 10 anos ou mais "
                  "de idade, por nivel de instrucao)"),
    },
}

REQUEST_SLEEP_SECONDS = 0.3

CSV_COLUMNS = [
    "site_id",
    "municipio",
    "uf",
    "codigo_ibge",
    "ano",
    "faixa_etaria_base",
    "nivel_instrucao",
    "populacao",
    "percentual_do_total",
    "fonte",
    "data_extracao",
    "origem_lista",
]


def coletar_escolaridade_municipio(municipio: str, uf: str, codigo: int, ano: int) -> list[dict]:
    cfg = FONTES[ano]
    url = (f"https://servicodados.ibge.gov.br/api/v3/agregados/{cfg['agregado']}"
           f"/periodos/{ano}/variaveis/{cfg['var_contagem']}|{cfg['var_percentual']}"
           f"?localidades=N6[{codigo}]&classificacao={cfg['classificacao']}")
    print(f"[escolaridade {ano}] {municipio}/{uf} (codigo {codigo}) GET {url}")
    try:
        data, raw_bytes = http_get_json(url)
    except Exception as e:
        print(f"  ERRO ao buscar escolaridade {ano} de {municipio}/{uf}: {e}")
        return []
    save_raw(RAW_DIR, f"escolaridade_censo{ano}_{codigo}_{municipio}_{uf}.json".replace(" ", "_"), raw_bytes)

    # junta contagem e percentual por nivel de instrucao
    contagem_por_nivel: dict[str, float] = {}
    percentual_por_nivel: dict[str, float] = {}
    for bloco in data:
        var_id = int(bloco["id"])
        for resultado in bloco["resultados"]:
            nivel = None
            for classif in resultado["classificacoes"]:
                if classif["id"] == "1568":
                    nivel = list(classif["categoria"].values())[0]
            if nivel not in NIVEIS_COMPARAVEIS:
                continue
            try:
                valor_str = resultado["series"][0]["serie"][str(ano)]
            except (KeyError, IndexError, TypeError):
                continue
            if valor_str in ("-", "..", "...", None):
                continue
            valor = float(valor_str)
            if var_id == cfg["var_contagem"]:
                contagem_por_nivel[nivel] = valor
            elif var_id == cfg["var_percentual"]:
                percentual_por_nivel[nivel] = valor

    time.sleep(REQUEST_SLEEP_SECONDS)

    linhas = []
    for nivel in NIVEIS_COMPARAVEIS:
        if nivel not in contagem_por_nivel:
            continue
        linhas.append({
            "nivel_instrucao": nivel,
            "populacao": contagem_por_nivel[nivel],
            "percentual_do_total": percentual_por_nivel.get(nivel),
        })
    return linhas


def main() -> None:
    sites = load_sites_19()
    print(f"Sites carregados: {len(sites)} (16 validados + 3 datacentermap_novo)")

    municipios = municipios_unicos(sites)
    print(f"Municipios unicos: {len(municipios)}")

    codigos = resolve_codigos_ibge(sites, RAW_DIR)

    resultados: dict[tuple[str, str, int], list[dict]] = {}
    for municipio, uf in municipios:
        codigo = codigos[(municipio, uf)]["codigo_ibge"]
        for ano in (2022, 2010):
            resultados[(municipio, uf, ano)] = coletar_escolaridade_municipio(municipio, uf, codigo, ano)

    data_extracao = date.today().isoformat()

    linhas = []
    gaps = []
    for s in sites:
        key = (s["municipio"], s["uf"])
        codigo = codigos[key]["codigo_ibge"]
        for ano in (2022, 2010):
            linhas_municipio = resultados[(s["municipio"], s["uf"], ano)]
            if not linhas_municipio:
                gaps.append(f"{s['site_id']} ({s['municipio']}/{s['uf']}) - Censo {ano} sem dado publicado")
                continue
            for linha in linhas_municipio:
                linhas.append({
                    "site_id": s["site_id"],
                    "municipio": s["municipio"],
                    "uf": s["uf"],
                    "codigo_ibge": codigo,
                    "ano": ano,
                    "faixa_etaria_base": FONTES[ano]["faixa_etaria_base"],
                    "nivel_instrucao": linha["nivel_instrucao"],
                    "populacao": linha["populacao"],
                    "percentual_do_total": linha["percentual_do_total"],
                    "fonte": FONTES[ano]["fonte"],
                    "data_extracao": data_extracao,
                    "origem_lista": s["origem_lista"],
                })

    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sorted(linhas, key=lambda r: (r["site_id"], r["ano"], r["nivel_instrucao"])):
            writer.writerow(row)

    print()
    print(f"CSV escrito em {PROCESSED_CSV} — {len(linhas)} linhas "
          f"(site x ano-censo x nivel_instrucao, ate 5 niveis x 2 anos x {len(sites)} sites = "
          f"{5 * 2 * len(sites)} no maximo).")
    if gaps:
        print(f"Lacunas (site/ano-censo sem NENHUM nivel de instrucao publicado): {len(gaps)}")
        for g in gaps:
            print(f"  - {g}")
    else:
        print("Nenhuma lacuna: todos os 19 sites tem dado de escolaridade nos 2 Censos (2010 e 2022).")


if __name__ == "__main__":
    main()
