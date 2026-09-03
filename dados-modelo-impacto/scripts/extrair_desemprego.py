"""
Extrai taxa de desocupacao (desemprego) municipal (IBGE) para os 19 sites (18 municipios unicos)
deste apoio — ONDE a fonte cobre, ver ressalva de cobertura parcial abaixo.

Pesquisa feita antes de escrever este script (ver raw/desemprego/METODOLOGIA.md para o detalhe
completo): taxa de desocupacao e um produto da PNAD Continua, pesquisa AMOSTRAL cujo desenho
oficial so garante representatividade em nivel de Brasil, Grandes Regioes, UF e Regioes
Metropolitanas/municipios das capitais selecionados — NAO em nivel municipal generico (RAIS/CAGED
medem emprego FORMAL, nao desemprego; PNAD Continua trimestral e a unica fonte de taxa de
desemprego do IBGE).

Apesar disso, a API de Agregados do IBGE PUBLICA a tabela abaixo com nivel territorial N6
(Municipio) habilitado:

  SIDRA tabela 4562 — "Taxa de desocupacao, na semana de referencia, das pessoas de 14 anos ou
  mais de idade" (PNAD Continua anual, variavel 4099, unidade %)
    GET https://servicodados.ibge.gov.br/api/v3/agregados/4562/periodos/{anos}/variaveis/4099
        ?localidades=N6[{codigo_ibge}]

Testado empiricamente (nao documentado como pressuposto — CONFIRMADO por chamada real antes da
coleta completa) para os 18 municipios deste apoio: a API SO retorna valor numerico real para
municipios que sao CAPITAL DE ESTADO (a PNAD Continua tem amostra propria e representativa so
para esses casos); para os demais, o campo `serie` volta com o codigo "..." (nao disponivel/nao
divulgado pelo IBGE), em TODOS os anos, nao so alguns. Dos 18 municipios deste apoio, so 5 sao
capitais: Fortaleza(CE), Manaus(AM), Goiania(GO), Porto Alegre(RS), Joao Pessoa(PB). Os outros 13
(a maioria cidades-satelite de regioes metropolitanas — Hortolandia, Maracanau, Osasco, Sumare,
Vinhedo, Santana de Parnaiba, Sao Joao de Meriti, Barueri, Jundiai, Paulinia — mais os 3 sites
novos Eldorado do Sul, Sao Goncalo do Amarante e Uberlandia, nenhum deles capital) NAO tem taxa de
desocupacao municipal publicada pelo IBGE — CadUnico e RAIS/CAGED-derivado tambem foram
pesquisados como possiveis proxies e descartados (ver METODOLOGIA.md: nenhum publica uma TAXA de
desemprego comparavel por municipio, so contagens de vinculos formais, que ja sao cobertas pela
variavel de emprego do levantamento anterior). **Este script NAO forca um numero para os 13
municipios sem cobertura — a linha fica ausente do CSV, documentada aqui como lacuna estrutural
da fonte, nao como falha da coleta.**

Adicionalmente, mesmo para os 5 municipios com cobertura, os anos 2020, 2021 e 2022 vem "..." (a
serie tem um hiato ali — coincide com a reponderacao da PNAD Continua apos o Censo 2022 e possiveis
efeitos da pandemia na coleta amostral local; nao investigado a fundo pois foge do escopo desta
coleta, so registrado como lacuna real da fonte).

RESSALVA IMPORTANTE (ler antes de usar o CSV gerado): mesma logica de granularidade ja registrada
para populacao/emprego/PIB/renda em dados-modelo-impacto/raw/*/METODOLOGIA.md e em
docs/requisitos-dados-externos.md (raiz do repo), secao 2 — e dado de CONTEXTO, nao evidencia de
impacto causado por um data center especifico. Aqui a ressalva e ainda mais forte: nem sequer
existe granularidade municipal para a maioria dos sites.

Uso:
    python extrair_desemprego.py

Nao recebe argumentos. Le config/sites.geojson (+ 3 sites novos em _sites_ibge_common.py),
escreve:
  - dados-modelo-impacto/raw/desemprego/*.json (localidades + respostas da tabela 4562)
  - dados-modelo-impacto/processed/desemprego_municipal.csv
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

RAW_DIR = APOIO_DIR / "raw" / "desemprego"
PROCESSED_CSV = APOIO_DIR / "processed" / "desemprego_municipal.csv"

AGREGADO_DESOCUPACAO = 4562
VAR_TAXA = 4099
ANO_INICIO = 2016
ANO_FIM = 2025

ANOS_STR = "|".join(str(a) for a in range(ANO_INICIO, ANO_FIM + 1))
DESOCUPACAO_URL = (
    f"https://servicodados.ibge.gov.br/api/v3/agregados/{AGREGADO_DESOCUPACAO}"
    f"/periodos/{ANOS_STR}/variaveis/{VAR_TAXA}?localidades=N6[{{codigo}}]"
)

REQUEST_SLEEP_SECONDS = 0.3

CSV_COLUMNS = [
    "site_id",
    "municipio",
    "uf",
    "codigo_ibge",
    "ano",
    "taxa_desocupacao_pct",
    "fonte",
    "data_extracao",
    "origem_lista",
]


def coletar_desocupacao_municipio(municipio: str, uf: str, codigo: int) -> dict[int, float]:
    url = DESOCUPACAO_URL.format(codigo=codigo)
    print(f"[desocupacao] {municipio}/{uf} (codigo {codigo}) GET {url}")
    try:
        data, raw_bytes = http_get_json(url)
    except Exception as e:
        print(f"  ERRO ao buscar taxa de desocupacao de {municipio}/{uf}: {e}")
        return {}
    save_raw(RAW_DIR, f"desocupacao_{codigo}_{municipio}_{uf}.json".replace(" ", "_"), raw_bytes)

    serie_out: dict[int, float] = {}
    try:
        serie_dict = data[0]["resultados"][0]["series"][0]["serie"]
    except (KeyError, IndexError, TypeError):
        serie_dict = {}
    for ano_str, valor_str in serie_dict.items():
        if valor_str in ("-", "..", "...", None):
            continue  # IBGE: "nao disponivel" — nao forcar numero
        serie_out[int(ano_str)] = float(valor_str)
    time.sleep(REQUEST_SLEEP_SECONDS)
    return serie_out


def main() -> None:
    sites = load_sites_19()
    print(f"Sites carregados: {len(sites)} (16 validados + 3 datacentermap_novo)")

    municipios = municipios_unicos(sites)
    print(f"Municipios unicos: {len(municipios)}")

    codigos = resolve_codigos_ibge(sites, RAW_DIR)

    series_por_municipio: dict[tuple[str, str], dict[int, float]] = {}
    for municipio, uf in municipios:
        codigo = codigos[(municipio, uf)]["codigo_ibge"]
        series_por_municipio[(municipio, uf)] = coletar_desocupacao_municipio(municipio, uf, codigo)

    data_extracao = date.today().isoformat()
    fonte = ("IBGE - PNAD Continua anual, SIDRA tabela 4562 (Taxa de desocupacao, na semana de "
             "referencia, das pessoas de 14 anos ou mais de idade) — so publicada pelo IBGE em "
             "nivel N6/Municipio para municipios-capital")

    linhas = []
    municipios_sem_nenhum_dado = []
    gaps_pontuais = []
    for municipio, uf in municipios:
        serie = series_por_municipio[(municipio, uf)]
        if not serie:
            municipios_sem_nenhum_dado.append(f"{municipio}/{uf} (nao e capital de estado — sem "
                                               f"serie municipal de taxa de desocupacao no IBGE)")

    for s in sites:
        key = (s["municipio"], s["uf"])
        codigo = codigos[key]["codigo_ibge"]
        serie = series_por_municipio[key]
        for ano in range(ANO_INICIO, ANO_FIM + 1):
            if ano not in serie:
                if serie:  # municipio tem alguma cobertura, so esse ano falta (hiato 2020-2022)
                    gaps_pontuais.append(f"{s['site_id']} ({s['municipio']}/{s['uf']}) - ano {ano}")
                continue
            linhas.append({
                "site_id": s["site_id"],
                "municipio": s["municipio"],
                "uf": s["uf"],
                "codigo_ibge": codigo,
                "ano": ano,
                "taxa_desocupacao_pct": serie[ano],
                "fonte": fonte,
                "data_extracao": data_extracao,
                "origem_lista": s["origem_lista"],
            })

    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sorted(linhas, key=lambda r: (r["site_id"], r["ano"])):
            writer.writerow(row)

    print()
    print(f"CSV escrito em {PROCESSED_CSV} — {len(linhas)} linhas (site x ano, so onde a fonte cobre).")
    print(f"Municipios SEM NENHUMA cobertura (nao sao capital de estado): "
          f"{len(municipios_sem_nenhum_dado)}/{len(municipios)}")
    for m in municipios_sem_nenhum_dado:
        print(f"  - {m}")
    if gaps_pontuais:
        print(f"Lacunas pontuais nos municipios COM cobertura (hiato 2020-2022 na PNAD Continua): "
              f"{len(gaps_pontuais)}")
        for g in gaps_pontuais:
            print(f"  - {g}")


if __name__ == "__main__":
    main()
