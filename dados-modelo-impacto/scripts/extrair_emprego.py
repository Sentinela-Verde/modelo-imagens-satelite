"""
Extrai serie anual de emprego formal municipal para os municipios dos sites deste repositorio
(config/sites.geojson) — apoio ao modelo de impacto do Guilherme (frente separada do
classificador principal, ver dados-modelo-impacto/README.md). NAO mexe em src/sentinela/, data/,
models/ ou outputs/ do classificador.

RESSALVA IMPORTANTE (ler antes de usar o CSV gerado): emprego formal em nivel municipal e dado de
CONTEXTO/ESTRATIFICACAO (papel D), NAO evidencia de que um data center especifico gerou aqueles
empregos. RAIS/CAGED/CEMPRE agregam por municipio (e, no maximo, por setor de atividade), sem
isolar o efeito de um unico empreendimento — um municipio inteiro tem, tipicamente, dezenas a
centenas de milhares de vinculos empregaticios; um data center de algumas dezenas de hectares nao
produz um efeito estatisticamente detectavel nesse agregado, e qualquer variacao observada tem
mais causas concorrentes plausiveis (ciclo economico local, outras empresas, sazonalidade) do que
o empreendimento sozinho. Ja registrado em docs/requisitos-dados-externos.md (secao 2) e
docs/contrato-dados-externos.yml (entrada soc_emprego_formal, papel D) na raiz deste repositorio.
O dado foi coletado porque foi pedido como contexto de mercado de trabalho local, nao porque
sustenta uma afirmacao causal de "o data center gerou N empregos".

Fonte escolhida apos pesquisa (detalhe completo, alternativas descartadas e motivo em
raw/emprego/METODOLOGIA.md): IBGE / SIDRA — CEMPRE (Cadastro Central de Empresas), variavel
"Pessoal ocupado assalariado" (numero 708), que e o proxy publico, pronto (agregado, sem exigir
processamento de microdados) e sem exigencia de cadastro/login mais proximo de "emprego formal por
municipio" hoje disponivel. A base administrativa do CEMPRE e alimentada pela propria RAIS/eSocial
— nao e uma fonte concorrente, e uma leitura agregada por estabelecimento dela.

  1. API de Localidades do IBGE — resolve nome+UF de municipio para o codigo IBGE de 7 digitos
     (identica ao script irmao extrair_populacao_ibge.py).
       GET https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF}/municipios

  2. API de Agregados (SIDRA) do IBGE — tabela 1685 "Unidades locais, empresas e outras
     organizacoes atuantes, pessoal ocupado total, pessoal ocupado assalariado... — serie
     encerrada em 2021" (todos os municipios, sem corte de populacao minima, 2006-2021).
       GET https://servicodados.ibge.gov.br/api/v3/agregados/1685/periodos/{anos}
           /variaveis/707|708|367?localidades=N6[{codigo_ibge}]

  3. API de Agregados (SIDRA) do IBGE — tabela 9509, sucessora da 1685 na metodologia atual
     (todos os municipios, 2022-2024 disponivel nesta extracao).
       GET https://servicodados.ibge.gov.br/api/v3/agregados/9509/periodos/{anos}
           /variaveis/707|708|367?localidades=N6[{codigo_ibge}]

  Variaveis extraidas de cada tabela:
    707 = Pessoal ocupado total (inclui socios/proprietarios sem carteira assinada)
    708 = Pessoal ocupado assalariado em 31/12 (== "emprego_formal_total" neste CSV — a leitura
          mais proxima de "vinculo formal ativo", equivalente ao conceito RAIS)
    367 = Numero de empresas e outras organizacoes atuantes (contexto adicional, nao usado como
          emprego)

Uso:
    .venv\\Scripts\\python.exe dados-modelo-impacto\\scripts\\extrair_emprego.py

Nao recebe argumentos. Le config/sites.geojson (raiz do repo), escreve:
  - dados-modelo-impacto/raw/emprego/*.json                    (respostas brutas da API, uma por
    chamada — o script cria esses arquivos, sobrescrevendo a cada execucao)
  - dados-modelo-impacto/processed/emprego_municipal.csv

O arquivo dados-modelo-impacto/raw/emprego/METODOLOGIA.md (pesquisa de fontes, decisao,
alternativas descartadas e o que ficou pendente) e um documento escrito a parte, nao gerado por
este script — leia-o antes de usar o CSV.

Usa so biblioteca padrao do Python para toda a logica (mesma escolha do script irmao
extrair_populacao_ibge.py) — a unica dependencia opcional e `truststore` (ja no ambiente
`.venv` deste repo), usada so para contornar um problema de validacao de certificado TLS
especifico desta maquina de desenvolvimento (ver comentario perto de `http_get_json` abaixo).
Se `truststore` nao estiver instalado, o script cai automaticamente no `urllib` padrao.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]          # .../modelo-imagens-satelite
APOIO_DIR = SCRIPT_DIR.parent              # .../dados-modelo-impacto

SITES_GEOJSON = REPO_ROOT / "config" / "sites.geojson"
RAW_DIR = APOIO_DIR / "raw" / "emprego"
PROCESSED_CSV = APOIO_DIR / "processed" / "emprego_municipal.csv"

# --------------------------------------------------------------------------------------
# Constantes da API do IBGE
# --------------------------------------------------------------------------------------

LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"

VARIAVEIS = "707|708|367"  # pessoal ocupado total | pessoal ocupado assalariado | numero de empresas

TABELAS_CEMPRE = [
    # (id_tabela, nome_curto, ano_min, ano_max)
    (1685, "CEMPRE (serie encerrada em 2021)", 2006, 2021),
    (9509, "CEMPRE (metodologia atual)", 2022, 2024),
]

AGREGADOS_URL_TMPL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/periodos/{anos}"
    f"/variaveis/{VARIAVEIS}?localidades=N6[{{codigo}}]"
)

ANO_INICIO = 2016
ANO_FIM = 2025

CSV_COLUMNS = [
    "site_id",
    "municipio",
    "uf",
    "codigo_ibge",
    "ano",
    "emprego_formal_total",
    "pessoal_ocupado_total",
    "numero_empresas",
    "fonte",
    "data_extracao",
]

REQUEST_SLEEP_SECONDS = 0.3  # cortesia com a API publica do IBGE


# --------------------------------------------------------------------------------------
# HTTP helper (so biblioteca padrao)
# --------------------------------------------------------------------------------------

try:
    # Nesta maquina de desenvolvimento (Windows), a cadeia de certificados padrao do OpenSSL
    # embutido no Python rejeita certificados TLS validos (erro "Basic Constraints of CA cert
    # not marked critical" / "unable to get local issuer certificate"), inclusive de APIs
    # publicas do governo (servicodados.ibge.gov.br) — causa provavel: software de seguranca
    # local que faz inspecao de TLS com uma CA que o validador do Python nao aceita, mas que o
    # Windows aceita (confirmado: `Invoke-WebRequest` do PowerShell acessa a mesma URL sem erro,
    # pois usa o certificate store nativo do SO). `truststore` (pacote oficial, mantido pelo
    # PyPA) resolve isso corretamente: faz o Python validar TLS usando o store de certificados
    # do sistema operacional, em vez do bundle embutido — verificacao real continua ativa, so
    # muda a fonte de confianca. Sem esse pacote instalado, cai no urllib padrao (funciona em
    # ambientes sem esse problema de CA local).
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


def http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "sentinela-verde-apoio/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw_bytes = resp.read()
        content_encoding = resp.headers.get("Content-Encoding", "")
    if content_encoding == "gzip" or raw_bytes[:2] == b"\x1f\x8b":
        raw_bytes = gzip.decompress(raw_bytes)
    return json.loads(raw_bytes.decode("utf-8")), raw_bytes


def save_raw(filename: str, raw_bytes: bytes) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / filename
    path.write_bytes(raw_bytes)
    return path


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower()


# --------------------------------------------------------------------------------------
# Passo 1: carregar sites.geojson
# --------------------------------------------------------------------------------------

def load_sites() -> list[dict]:
    with open(SITES_GEOJSON, encoding="utf-8") as f:
        data = json.load(f)
    sites = []
    for feat in data["features"]:
        p = feat["properties"]
        sites.append({
            "site_id": p["site_id"],
            "municipio": p["municipio"],
            "uf": p["uf"],
        })
    return sites


# --------------------------------------------------------------------------------------
# Passo 2: resolver codigo IBGE de 7 digitos por (municipio, uf)
# --------------------------------------------------------------------------------------

def resolve_codigos_ibge(sites: list[dict]) -> dict[tuple[str, str], dict]:
    """Retorna {(municipio, uf): {"codigo_ibge": int, "nome_ibge": str}}."""
    ufs = sorted({s["uf"] for s in sites})
    municipios_por_uf: dict[str, list[dict]] = {}

    for uf in ufs:
        url = LOCALIDADES_URL.format(uf=uf)
        print(f"[localidades] GET {url}")
        data, raw_bytes = http_get_json(url)
        save_raw(f"localidades_municipios_UF_{uf}.json", raw_bytes)
        municipios_por_uf[uf] = data
        time.sleep(REQUEST_SLEEP_SECONDS)

    resolved: dict[tuple[str, str], dict] = {}
    unresolved: list[dict] = []

    for s in sites:
        key = (s["municipio"], s["uf"])
        if key in resolved:
            continue
        candidatos = municipios_por_uf[s["uf"]]
        match = None
        for c in candidatos:
            if c["nome"] == s["municipio"]:
                match = c
                break
        if match is None:
            # fallback: comparacao normalizada (sem acento/case), so para nao falhar por
            # diferenca cosmetica de grafia — nunca inventa codigo, so relaxa o casamento de texto
            alvo_norm = normalize(s["municipio"])
            for c in candidatos:
                if normalize(c["nome"]) == alvo_norm:
                    match = c
                    break
        if match is None:
            unresolved.append(s)
            continue
        resolved[key] = {"codigo_ibge": match["id"], "nome_ibge": match["nome"]}

    if unresolved:
        print("ERRO: nao foi possivel resolver o codigo IBGE para os seguintes municipios:")
        for s in unresolved:
            print(f"  - site_id={s['site_id']} municipio={s['municipio']!r} uf={s['uf']}")
        print("Nada foi inventado — corrija o nome em config/sites.geojson ou o casamento acima.")
        sys.exit(1)

    return resolved


# --------------------------------------------------------------------------------------
# Passo 3: coletar serie por municipio unico, combinando as duas tabelas CEMPRE
# --------------------------------------------------------------------------------------

def parse_variaveis_response(data: list[dict]) -> dict[int, dict[int, int]]:
    """Recebe a resposta (lista de variaveis) da API de agregados e retorna
    {id_variavel: {ano: valor}}. Ignora anos com valor nao numerico (IBGE usa '-', '..', etc.
    para 'nao se aplica'/'nao disponivel')."""
    por_variavel: dict[int, dict[int, int]] = {}
    for var_obj in data:
        var_id = int(var_obj["id"])
        serie: dict[int, int] = {}
        try:
            serie_dict = var_obj["resultados"][0]["series"][0]["serie"]
        except (KeyError, IndexError):
            serie_dict = {}
        for ano_str, valor_str in serie_dict.items():
            if valor_str in ("-", "..", "...", None, ""):
                continue
            try:
                serie[int(ano_str)] = int(valor_str)
            except ValueError:
                continue
        por_variavel[var_id] = serie
    return por_variavel


def coletar_serie_municipio(municipio: str, uf: str, codigo: int) -> dict[int, dict]:
    """Retorna {ano: {"emprego_formal_total": int, "pessoal_ocupado_total": int,
    "numero_empresas": int, "fonte": str}} combinando as tabelas 1685 (2006-2021) e 9509
    (2022-2024), recortadas para [ANO_INICIO, ANO_FIM]."""
    serie: dict[int, dict] = {}

    for tabela_id, nome_tabela, ano_min_tabela, ano_max_tabela in TABELAS_CEMPRE:
        ano_min = max(ano_min_tabela, ANO_INICIO)
        ano_max = min(ano_max_tabela, ANO_FIM)
        if ano_min > ano_max:
            continue  # essa tabela nao cobre nada dentro da janela pedida
        anos_str = "|".join(str(a) for a in range(ano_min, ano_max + 1))
        url = AGREGADOS_URL_TMPL.format(tabela=tabela_id, anos=anos_str, codigo=codigo)
        print(f"[{nome_tabela}] {municipio}/{uf} (codigo {codigo}) GET {url}")
        try:
            data, raw_bytes = http_get_json(url)
        except urllib.error.HTTPError as e:
            print(f"  ERRO HTTP {e.code} ao buscar tabela {tabela_id} de {municipio}/{uf}: {e}")
            time.sleep(REQUEST_SLEEP_SECONDS)
            continue
        save_raw(
            f"tabela{tabela_id}_{codigo}_{municipio}_{uf}.json".replace(" ", "_"),
            raw_bytes,
        )
        por_variavel = parse_variaveis_response(data)
        anos_com_dado = sorted(
            set(por_variavel.get(707, {})) | set(por_variavel.get(708, {})) | set(por_variavel.get(367, {}))
        )
        for ano in anos_com_dado:
            serie[ano] = {
                "emprego_formal_total": por_variavel.get(708, {}).get(ano),
                "pessoal_ocupado_total": por_variavel.get(707, {}).get(ano),
                "numero_empresas": por_variavel.get(367, {}).get(ano),
                "fonte": f"IBGE - SIDRA tabela {tabela_id} ({nome_tabela}), variavel 708 'Pessoal ocupado assalariado'",
            }
        time.sleep(REQUEST_SLEEP_SECONDS)

    return serie


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------

def main() -> None:
    sites = load_sites()
    print(f"Sites carregados de {SITES_GEOJSON}: {len(sites)}")

    municipios_unicos = sorted({(s["municipio"], s["uf"]) for s in sites})
    print(f"Municipios unicos (dedup por municipio+UF): {len(municipios_unicos)}")

    codigos = resolve_codigos_ibge(sites)

    series_por_municipio: dict[tuple[str, str], dict[int, dict]] = {}
    for municipio, uf in municipios_unicos:
        codigo = codigos[(municipio, uf)]["codigo_ibge"]
        series_por_municipio[(municipio, uf)] = coletar_serie_municipio(municipio, uf, codigo)

    data_extracao = date.today().isoformat()

    linhas = []
    gaps: list[str] = []
    for s in sites:
        key = (s["municipio"], s["uf"])
        codigo = codigos[key]["codigo_ibge"]
        serie = series_por_municipio[key]
        for ano in range(ANO_INICIO, ANO_FIM + 1):
            if ano not in serie:
                gaps.append(f"{s['site_id']} ({s['municipio']}/{s['uf']}) - ano {ano} sem dado publicado")
                continue
            valores = serie[ano]
            linhas.append({
                "site_id": s["site_id"],
                "municipio": s["municipio"],
                "uf": s["uf"],
                "codigo_ibge": codigo,
                "ano": ano,
                "emprego_formal_total": valores["emprego_formal_total"],
                "pessoal_ocupado_total": valores["pessoal_ocupado_total"],
                "numero_empresas": valores["numero_empresas"],
                "fonte": valores["fonte"],
                "data_extracao": data_extracao,
            })

    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        # ordem estavel: por site_id, depois por ano
        for row in sorted(linhas, key=lambda r: (r["site_id"], r["ano"])):
            writer.writerow(row)

    anos_esperados = ANO_FIM - ANO_INICIO + 1
    print()
    print(f"CSV escrito em {PROCESSED_CSV} — {len(linhas)} linhas (site x ano).")
    print(f"Sites x anos esperados no total: {len(sites)} x {anos_esperados} = {len(sites) * anos_esperados}")
    if gaps:
        print(f"Lacunas (site/ano sem dado, deixadas ausentes, NAO estimadas): {len(gaps)}")
        for g in gaps:
            print(f"  - {g}")
        print()
        print("Motivo esperado da lacuna em 2025: nenhuma das duas tabelas CEMPRE usadas cobre")
        print("2025 ainda (defasagem de publicacao do IBGE, tipicamente ~1,5 ano) — ver")
        print("raw/emprego/METODOLOGIA.md, secao 'Cobertura obtida'.")
    else:
        print("Nenhuma lacuna: todos os sites tem dado para todos os anos pedidos.")


if __name__ == "__main__":
    main()
