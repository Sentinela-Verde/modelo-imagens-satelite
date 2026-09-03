"""
Modulo compartilhado pelos 4 coletores de variaveis socioeconomicas (PIB, renda, desemprego,
escolaridade) em dados-modelo-impacto/scripts/. Nao e um script standalone — e importado por
extrair_pib.py, extrair_renda.py, extrair_desemprego.py e extrair_escolaridade.py.

Responsabilidades:
  1. Montar a lista de 19 sites (16 de config/sites.geojson + 3 novos do levantamento do
     Guilherme via datacentermap.com, reconciliados em 2026-09-03 — ver
     dados-modelo-impacto/raw/*/METODOLOGIA.md de cada variavel para o detalhe da reconciliacao).
  2. Resolver codigo IBGE de 7 digitos para cada municipio unico (mesmo endpoint e mesma logica
     de casamento de nome ja confirmados em extrair_populacao_ibge.py:
       GET https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF}/municipios
     ), com correcao manual para os 3 municipios novos onde o nome as vezes precisa de ajuste
     fino (nenhum caso encontrado ate agora, mas o mecanismo de fallback continua o mesmo).
  3. HTTP helper com o mesmo tratamento de gzip e do problema de certificado TLS local (pacote
     truststore) documentado em extrair_populacao_ibge.py.

RESSALVA DE PROVENIENCIA DOS 3 SITES NOVOS (ler antes de usar): as coordenadas de
`scala-ai-city`, `pecem-datacenter` e `rtone-uberlandia` vêm do levantamento do Guilherme
(datacentermap.com, arquivo `datacentermap_enriquecido.csv` do repo irmao
datacenter-extracao-modelos) e NAO passaram pela validacao em 5 camadas (v1-v5) que os 16 sites
de config/sites.geojson tiveram. Isso nao afeta a extracao AQUI (as variaveis coletadas sao por
MUNICIPIO, nao por coordenada exata — o que importa e o nome do municipio/UF estar correto, o que
foi conferido manualmente para os 3 casos), mas e sinalizado na coluna `origem_lista` de todo CSV
processado por este modulo: `sites_validados` (os 16 originais) vs. `datacentermap_novo` (os 3
novos).
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]          # .../modelo-imagens-satelite
APOIO_DIR = SCRIPT_DIR.parent              # .../dados-modelo-impacto

SITES_GEOJSON = REPO_ROOT / "config" / "sites.geojson"

# --------------------------------------------------------------------------------------
# Os 3 sites novos (reconciliacao 2026-09-03 com datacentermap_enriquecido.csv do Guilherme,
# repo irmao datacenter-extracao-modelos/data/02_silver/ — so LEITURA foi feita la, nada foi
# escrito nesse repo irmao). UF resolvida manualmente pelo time (nao usar a coluna "estado" do
# CSV do Guilherme — e mercado/regiao, nao UF, conforme aviso dele no dicionario de colunas).
# --------------------------------------------------------------------------------------

NOVOS_SITES = [
    {
        "site_id": "scala-ai-city",
        "municipio": "Eldorado do Sul",
        "uf": "RS",
        "lat": -30.07425077314578,
        "lon": -51.49400150419427,
    },
    {
        "site_id": "pecem-datacenter",
        "municipio": "São Gonçalo do Amarante",
        "uf": "CE",
        "lat": -3.653321,
        "lon": -38.8251428,
    },
    {
        "site_id": "rtone-uberlandia",
        "municipio": "Uberlândia",
        "uf": "MG",
        # lat/lon do CSV do Guilherme (datacentermap_enriquecido.csv, id_datacenter='dc_c79290add5')
        "lat": -18.94893942693562,
        "lon": -48.33580789389012,
    },
]


def load_sites_19() -> list[dict]:
    """16 sites de config/sites.geojson (origem_lista='sites_validados') + 3 novos
    (origem_lista='datacentermap_novo'). Retorna lista de dicts com site_id, municipio, uf,
    origem_lista."""
    with open(SITES_GEOJSON, encoding="utf-8") as f:
        data = json.load(f)
    sites = []
    for feat in data["features"]:
        p = feat["properties"]
        sites.append({
            "site_id": p["site_id"],
            "municipio": p["municipio"],
            "uf": p["uf"],
            "origem_lista": "sites_validados",
        })
    for s in NOVOS_SITES:
        sites.append({
            "site_id": s["site_id"],
            "municipio": s["municipio"],
            "uf": s["uf"],
            "origem_lista": "datacentermap_novo",
        })
    assert len({s["site_id"] for s in sites}) == len(sites) == 19, \
        f"esperado 19 site_id unicos, encontrado {len(sites)}"
    return sites


# --------------------------------------------------------------------------------------
# HTTP helper (mesmo padrao de extrair_populacao_ibge.py — ver NOTA DE AMBIENTE la)
# --------------------------------------------------------------------------------------

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    print("AVISO: pacote 'truststore' nao encontrado (pip install truststore). Se esta maquina "
          "tiver o problema de validacao de certificado SSL documentado em "
          "raw/populacao/METODOLOGIA.md, as chamadas HTTPS abaixo vao falhar.")


def http_get_json(url: str) -> tuple[object, bytes]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "sentinela-verde-apoio/1.0", "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw_bytes = resp.read()
        content_encoding = resp.headers.get("Content-Encoding", "")
    if content_encoding == "gzip" or raw_bytes[:2] == b"\x1f\x8b":
        raw_bytes = gzip.decompress(raw_bytes)
    return json.loads(raw_bytes.decode("utf-8")), raw_bytes


def save_raw(raw_dir: Path, filename: str, raw_bytes: bytes) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / filename
    path.write_bytes(raw_bytes)
    return path


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower()


REQUEST_SLEEP_SECONDS = 0.3

LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"


def resolve_codigos_ibge(sites: list[dict], raw_dir: Path) -> dict[tuple[str, str], dict]:
    """Retorna {(municipio, uf): {"codigo_ibge": int, "nome_ibge": str}}. Mesma logica de
    extrair_populacao_ibge.py: casamento exato de nome primeiro, normalizado (sem acento/case)
    como fallback, nunca inventa codigo."""
    ufs = sorted({s["uf"] for s in sites})
    municipios_por_uf: dict[str, list[dict]] = {}

    for uf in ufs:
        url = LOCALIDADES_URL.format(uf=uf)
        print(f"[localidades] GET {url}")
        data, raw_bytes = http_get_json(url)
        save_raw(raw_dir, f"localidades_municipios_UF_{uf}.json", raw_bytes)
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
        print("Nada foi inventado — corrija o nome em config/sites.geojson ou NOVOS_SITES.")
        sys.exit(1)

    return resolved


def municipios_unicos(sites: list[dict]) -> list[tuple[str, str]]:
    return sorted({(s["municipio"], s["uf"]) for s in sites})
