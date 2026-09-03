"""
Extrai serie anual de populacao municipal (IBGE) para os municipios dos sites deste
repositorio (config/sites.geojson).

Fontes (confirmadas por chamada de teste antes de escrever este script — ver
raw/populacao/METODOLOGIA.md para o detalhe completo):

  1. API de Localidades do IBGE — resolve nome+UF de municipio para o codigo IBGE de 7 digitos.
       GET https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF}/municipios

  2. API de Agregados (SIDRA) do IBGE — tabela 6579 "Populacao residente estimada"
     (estimativas intercensitarias anuais, variavel 9324).
       GET https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos
       GET https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/{anos}/variaveis/9324
           ?localidades=N6[{codigo_ibge}]

  3. API de Agregados (SIDRA) do IBGE — tabela 9514 "Populacao residente, por sexo, idade e
     forma de declaracao da idade", resultado do Censo Demografico 2022 (variavel 93, com as
     classificacoes "Sexo", "Idade" e "Forma de declaracao da idade" fixadas em "Total").
       GET https://servicodados.ibge.gov.br/api/v3/agregados/9514/periodos/2022/variaveis/93
           ?localidades=N6[{codigo_ibge}]
           &classificacao=2[6794]|287[100362]|286[113635]

RESSALVA IMPORTANTE (ler antes de usar o CSV gerado): populacao em nivel municipal e dado de
CONTEXTO/ESTRATIFICACAO, nao evidencia de impacto causado por um data center especifico — ver
dados-modelo-impacto/README.md e docs/requisitos-dados-externos.md (secao 2) na raiz deste
repositorio. Um municipio inteiro tem, tipicamente, dezenas a centenas de milhares de habitantes;
um data center de algumas dezenas de hectares nao produz efeito populacional detectavel nesse
agregado. O dado foi coletado porque foi pedido, nao porque sustenta uma afirmacao causal.

Uso:
    python extrair_populacao_ibge.py

Nao recebe argumentos. Le config/sites.geojson (raiz do repo), escreve:
  - dados-modelo-impacto/raw/populacao/*.json          (respostas brutas da API, uma por chamada)
  - dados-modelo-impacto/processed/populacao_municipal.csv

Nao usa nenhuma dependencia externa (so biblioteca padrao do Python) para nao exigir setup de
ambiente extra.
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
RAW_DIR = APOIO_DIR / "raw" / "populacao"
PROCESSED_CSV = APOIO_DIR / "processed" / "populacao_municipal.csv"

# --------------------------------------------------------------------------------------
# Constantes da API do IBGE
# --------------------------------------------------------------------------------------

LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"

AGREGADO_ESTIMATIVA = 6579           # "Populacao residente estimada"
VARIAVEL_ESTIMATIVA = 9324
PERIODOS_ESTIMATIVA_URL = f"https://servicodados.ibge.gov.br/api/v3/agregados/{AGREGADO_ESTIMATIVA}/periodos"
SERIE_ESTIMATIVA_URL = (
    f"https://servicodados.ibge.gov.br/api/v3/agregados/{AGREGADO_ESTIMATIVA}"
    "/periodos/{anos}/variaveis/{VARIAVEL_ESTIMATIVA}?localidades=N6[{codigo}]"
).replace("{VARIAVEL_ESTIMATIVA}", str(VARIAVEL_ESTIMATIVA))

AGREGADO_CENSO2022 = 9514            # "Populacao residente, por sexo, idade e forma de declaracao da idade"
VARIAVEL_CENSO2022 = 93
ANO_CENSO2022 = 2022
CLASSIFICACAO_CENSO2022 = "2[6794]|287[100362]|286[113635]"  # Sexo=Total, Idade=Total, Forma=Total
CENSO2022_URL = (
    f"https://servicodados.ibge.gov.br/api/v3/agregados/{AGREGADO_CENSO2022}"
    f"/periodos/{ANO_CENSO2022}/variaveis/{VARIAVEL_CENSO2022}"
    "?localidades=N6[{codigo}]&classificacao=" + CLASSIFICACAO_CENSO2022
)

ANO_INICIO = 2016
ANO_FIM = 2025

CSV_COLUMNS = [
    "site_id",
    "municipio",
    "uf",
    "codigo_ibge",
    "ano",
    "populacao",
    "tipo_estimativa",
    "fonte",
    "data_extracao",
]

REQUEST_SLEEP_SECONDS = 0.3  # cortesia com a API publica do IBGE


# --------------------------------------------------------------------------------------
# HTTP helper (so biblioteca padrao + truststore)
# --------------------------------------------------------------------------------------
#
# NOTA DE AMBIENTE (nao e sobre a API do IBGE): nesta maquina, o contexto SSL padrao do Python
# (OpenSSL 3.x embutido) rejeita a cadeia de certificados de QUALQUER host HTTPS com
# "CERTIFICATE_VERIFY_FAILED: Basic Constraints of CA cert not marked critical" — reproduzido
# tambem contra servicodados.ibge.gov.br isoladamente. E uma CA intermediaria local (antivirus ou
# proxy corporativo com inspecao TLS) que nao segue estritamente a RFC 5280 e que o OpenSSL 3.x
# do Python passou a rejeitar; nao e um bundle de CA desatualizado (o mesmo erro ocorre mesmo
# alimentando o proprio bundle de certificados do Windows via ssl.enum_certificates), e nao
# acontece no PowerShell/.NET (Schannel valida essa mesma cadeia sem problema) nem indica
# problema com o endpoint do IBGE em si.
#
# Correcao usada: pacote "truststore" (https://pypi.org/project/truststore/), que troca o
# verificador de certificados do Python pela API nativa de validacao do sistema operacional
# (Schannel no Windows — a mesma lógica que o PowerShell ja usa com sucesso aqui) em vez de
# desabilitar a verificacao. Continua validando a cadeia de verdade, so que com o verificador do
# SO em vez do bundle OpenSSL embutido. Requer `pip install truststore` (unica dependencia externa
# deste script; se ja estiver instalado, ou rodando numa maquina sem esse problema local, e um
# no-op inofensivo).
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    print("AVISO: pacote 'truststore' nao encontrado (pip install truststore). Se a maquina atual "
          "tiver o mesmo problema de validacao de certificado SSL documentado acima, as chamadas "
          "HTTPS abaixo vao falhar. Prosseguindo com o SSL padrao do Python.")


def http_get_json(url: str) -> object:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "sentinela-verde-apoio/1.0", "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw_bytes = resp.read()
        content_encoding = resp.headers.get("Content-Encoding", "")
    # A API do IBGE comprime a resposta com gzip mesmo com "Accept-Encoding: identity"; urllib
    # nao descomprime sozinho. Detecta pelo header OU pela assinatura magica (1f 8b), e descomprime.
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
# Passo 3: descobrir periodos disponiveis na tabela de estimativas (6579)
# --------------------------------------------------------------------------------------

def get_periodos_estimativa() -> list[int]:
    print(f"[periodos] GET {PERIODOS_ESTIMATIVA_URL}")
    data, raw_bytes = http_get_json(PERIODOS_ESTIMATIVA_URL)
    save_raw("periodos_disponiveis_tabela_6579.json", raw_bytes)
    anos = sorted(int(p["id"]) for p in data)
    anos_no_intervalo = [a for a in anos if ANO_INICIO <= a <= ANO_FIM]
    return anos_no_intervalo


# --------------------------------------------------------------------------------------
# Passo 4: coletar series por municipio unico
# --------------------------------------------------------------------------------------

def extrair_serie(data: object) -> dict[str, str]:
    """A API de agregados do IBGE retorna uma LISTA (um item por variavel pedida) no nivel
    raiz — mesmo pedindo 1 variavel so. Aceita tanto a lista quanto o dict de dentro dela, para
    nao quebrar se algum dia vier so o dict."""
    if isinstance(data, list):
        if not data:
            return {}
        data = data[0]
    try:
        return data["resultados"][0]["series"][0]["serie"]
    except (KeyError, IndexError, TypeError):
        return {}


def coletar_serie_municipio(municipio: str, uf: str, codigo: int, anos_estimativa: list[int]) -> dict[int, tuple[int, str, str]]:
    """Retorna {ano: (populacao, tipo_estimativa, fonte)} para um municipio."""
    serie: dict[int, tuple[int, str, str]] = {}

    # --- estimativas intercensitarias (tabela 6579) ---
    if anos_estimativa:
        anos_str = "|".join(str(a) for a in anos_estimativa)
        url = SERIE_ESTIMATIVA_URL.format(anos=anos_str, codigo=codigo)
        print(f"[estimativa] {municipio}/{uf} (codigo {codigo}) GET {url}")
        try:
            data, raw_bytes = http_get_json(url)
        except urllib.error.HTTPError as e:
            print(f"  ERRO HTTP {e.code} ao buscar estimativas de {municipio}/{uf}: {e}")
            data, raw_bytes = None, b""
        if data:
            save_raw(f"estimativas_{codigo}_{municipio}_{uf}.json".replace(" ", "_"), raw_bytes)
            serie_dict = extrair_serie(data)
            for ano_str, valor_str in serie_dict.items():
                if valor_str in ("-", "..", "...", None):
                    continue  # IBGE usa esses codigos para "nao se aplica"/"nao disponivel"
                serie[int(ano_str)] = (
                    int(valor_str),
                    "estimativa_intercensitaria",
                    "IBGE - SIDRA tabela 6579 (Populacao residente estimada)",
                )
        time.sleep(REQUEST_SLEEP_SECONDS)

    # --- censo 2022 (tabela 9514), se 2022 estiver dentro da janela pedida ---
    if ANO_INICIO <= ANO_CENSO2022 <= ANO_FIM:
        url = CENSO2022_URL.format(codigo=codigo)
        print(f"[censo2022] {municipio}/{uf} (codigo {codigo}) GET {url}")
        try:
            data, raw_bytes = http_get_json(url)
        except urllib.error.HTTPError as e:
            print(f"  ERRO HTTP {e.code} ao buscar censo 2022 de {municipio}/{uf}: {e}")
            data, raw_bytes = None, b""
        if data:
            save_raw(f"censo2022_{codigo}_{municipio}_{uf}.json".replace(" ", "_"), raw_bytes)
            serie_dict = extrair_serie(data)
            for ano_str, valor_str in serie_dict.items():
                if valor_str in ("-", "..", "...", None):
                    continue
                serie[int(ano_str)] = (
                    int(valor_str),
                    "censo",
                    "IBGE - Censo Demografico 2022, SIDRA tabela 9514 (Populacao residente)",
                )
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

    anos_estimativa = get_periodos_estimativa()
    print(f"Anos disponiveis na tabela 6579 dentro de [{ANO_INICIO}, {ANO_FIM}]: {anos_estimativa}")

    anos_esperados = set(range(ANO_INICIO, ANO_FIM + 1))
    anos_cobertos_por_fonte = set(anos_estimativa) | ({ANO_CENSO2022} if ANO_INICIO <= ANO_CENSO2022 <= ANO_FIM else set())
    anos_sem_nenhuma_fonte = sorted(anos_esperados - anos_cobertos_por_fonte)
    if anos_sem_nenhuma_fonte:
        print(f"AVISO: nenhuma fonte publica populacao municipal para os anos {anos_sem_nenhuma_fonte} "
              f"dentro da janela pedida — essas linhas ficarao ausentes no CSV, nao estimadas.")

    series_por_municipio: dict[tuple[str, str], dict[int, tuple[int, str, str]]] = {}
    for municipio, uf in municipios_unicos:
        codigo = codigos[(municipio, uf)]["codigo_ibge"]
        series_por_municipio[(municipio, uf)] = coletar_serie_municipio(municipio, uf, codigo, anos_estimativa)

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
            populacao, tipo, fonte = serie[ano]
            linhas.append({
                "site_id": s["site_id"],
                "municipio": s["municipio"],
                "uf": s["uf"],
                "codigo_ibge": codigo,
                "ano": ano,
                "populacao": populacao,
                "tipo_estimativa": tipo,
                "fonte": fonte,
                "data_extracao": data_extracao,
            })

    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        # ordem estavel: por site_id, depois por ano
        for row in sorted(linhas, key=lambda r: (r["site_id"], r["ano"])):
            writer.writerow(row)

    print()
    print(f"CSV escrito em {PROCESSED_CSV} — {len(linhas)} linhas (site x ano).")
    print(f"Sites x anos esperados no total: {len(sites)} x {len(anos_esperados)} = {len(sites) * len(anos_esperados)}")
    if gaps:
        print(f"Lacunas (site/ano sem dado, deixadas ausentes, NAO estimadas): {len(gaps)}")
        for g in gaps:
            print(f"  - {g}")
    else:
        print("Nenhuma lacuna: todos os sites tem dado para todos os anos pedidos.")


if __name__ == "__main__":
    main()
