"""Gera um grupo de controle pareado (1 controle por site) para os 16 sites originais de
`config/sites.geojson`, como apoio ao modelo de impacto do Guilherme.

Versão adaptada e mais leve de SV-29 (`docs/tarefas/SV-29-grupo-controle-pareado.md`) — reaproveita
a MESMA lógica de geração/validação de candidatos (distância 15-40 km, mesmo município ou vizinho,
sem data center conhecido por perto, sem sobrepor buffer, similaridade de cobertura pré-obra via
MapBiomas), mas **não** roda o pipeline pesado de ingestão de imagem (SV-06/06b/07/08/14) — isso é
escopo do classificador principal (`src/sentinela/`), fora do escopo deste apoio. Aqui só a
geometria dos pontos de controle e a checagem MapBiomas (mais leve que Landsat/Sentinel-2 completo).

NÃO mexe em `src/sentinela/`, `config/sites.geojson`, `data/`, `models/`, `outputs/` do
classificador principal — só lê esses arquivos. Escreve exclusivamente em
`dados-modelo-impacto/raw/controles/`.

## Escopo: só os 16 sites originais

`config/sites.geojson` já contém só os 16 sites validados (V1-V5) — nenhum filtro adicional é
necessário. Os 3 sites novos (Scala AI City, Pecém Data Center, RT-One Uberlândia, reconciliados em
`dados-modelo-impacto/processed/consolidado_facilities.csv`, `origem_lista == "datacentermap_novo"`)
NÃO entram nesta rodada — decisão explícita, não esquecimento: estão em estágio de
planejamento/construção futura, sem `periodo_pre/durante/pos` real (ver
`dados-modelo-impacto/README.md`). Suas coordenadas SÃO usadas para enriquecer a lista de
contaminação (não pode haver controle perto delas), só não geram controle próprio.

## Metodologia (resumo — detalhe completo gerado em `raw/controles/METODOLOGIA.md` a cada rodada)

1. **Grade de candidatos**: para cada site, uma grade sistemática de pontos (7 raios entre 16 e
   40 km x 24 azimutes = 168 pontos), embaralhada de forma determinística e independente por site
   com `numpy.random.default_rng([42, hash(site_id)])` (seed 42 = mesma seed do repositório,
   `RANDOM_SEED`/`SETTINGS.seed` — combinada com um hash do `site_id`, para que a ordem de um site
   não dependa de quais outros sites são processados na mesma chamada nem de como o trabalho é
   dividido em lotes, ver `--sites` abaixo).
2. **Filtros baratos (sem rede)**, aplicados na ordem embaralhada: distância 15-40 km do
   tratamento; >=5 km de todo ponto de contaminação (os 16 sites + `config/sites_candidatos.csv`,
   inclusive rejeitadas); >=10 km (soma dos dois buffers de 5 km) de qualquer buffer de site já
   existente ou controle já colocado nesta mesma rodada.
3. **Filtro de município** (rede — Nominatim + IBGE, só nos candidatos que passaram o filtro
   barato): reverse-geocode do candidato; aceito se cai no mesmo município do tratamento OU na
   mesma microrregião do IBGE (proxy documentado de "município vizinho" — ver seção 3 do
   METODOLOGIA.md gerado). Para de tentar candidatos assim que 20 válidos forem coletados, ou após
   80 tentativas de reverse-geocode sem sucesso.
4. **Pareamento por cobertura do solo**: dentre os candidatos válidos, calcula a distância L1 entre
   a distribuição de classes MapBiomas (5 classes do repositório, `config/classes.yml`) num buffer
   de 5 km do candidato e do tratamento, no ano inicial de `periodo_pre` do tratamento (grampeado à
   janela 2013-2023 da Coleção 9). Escolhe o candidato de MENOR L1 — não um sorteio cego: a seed
   determina a ORDEM de exploração (reprodutível), a escolha final é pela melhor similaridade de
   cobertura entre os candidatos que passaram todos os filtros geométricos.
5. Site sem NENHUM candidato que passe os filtros geométricos/de município: reportado como
   "sem controle" com o motivo, não afrouxado.

Reprodutível/resumível: grava um checkpoint por site em `raw/controles/_checkpoint.json` e caches
de geocodificação em `raw/controles/_cache_geo.json` — rodar de novo pula o que já foi feito
(`--force` ignora o checkpoint). Os artefatos finais (`sites_controle.geojson`,
`pareamento_controle.csv`, `METODOLOGIA.md`, figuras) são reconstruídos a partir do checkpoint a
cada execução, mesmo que ela não termine todos os 16 sites.

Uso:
    .venv\\Scripts\\python.exe dados-modelo-impacto\\scripts\\gerar_controles_pareados.py [--force]
        [--sites site_id1,site_id2,...]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

import truststore  # noqa: E402

truststore.inject_into_ssl()  # mesma justificativa de sentinela.gee.auth (SChannel do Windows)

import ee  # noqa: E402
import numpy as np  # noqa: E402
import requests  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pyproj import Geod  # noqa: E402

from sentinela import classes  # noqa: E402
from sentinela.config import SETTINGS, ConfigError  # noqa: E402
from sentinela.gee.auth import init_ee  # noqa: E402

# --------------------------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------------------------

SITES_PATH = REPO_ROOT / "config" / "sites.geojson"
CANDIDATOS_PATH = REPO_ROOT / "config" / "sites_candidatos.csv"
FACILITIES_PATH = REPO_ROOT / "dados-modelo-impacto" / "processed" / "consolidado_facilities.csv"

OUT_DIR = REPO_ROOT / "dados-modelo-impacto" / "raw" / "controles"
FIGURAS_DIR = OUT_DIR / "figuras"
OUT_GEOJSON = OUT_DIR / "sites_controle.geojson"
OUT_CSV = OUT_DIR / "pareamento_controle.csv"
OUT_METODOLOGIA = OUT_DIR / "METODOLOGIA.md"
CHECKPOINT_PATH = OUT_DIR / "_checkpoint.json"
CACHE_GEO_PATH = OUT_DIR / "_cache_geo.json"

# --------------------------------------------------------------------------------------------
# Parâmetros do desenho (mesmos limiares de SV-29)
# --------------------------------------------------------------------------------------------

SEED = SETTINGS.seed
DIST_MIN_KM = 15.0
DIST_MAX_KM = 40.0
CONTAM_MIN_KM = 5.0
BUFFER_KM = 5.0
NO_OVERLAP_MIN_KM = BUFFER_KM + BUFFER_KM  # 10 km, soma dos dois buffers de 5 km
L1_BOM = 0.10
L1_ACEITAVEL = 0.20

RAIOS_GRADE_KM = [16, 20, 24, 28, 32, 36, 40]
AZIMUTES_GRADE_DEG = list(range(0, 360, 15))  # 24 valores

# Rodada de melhoria (2026-09-03): a primeira rodada parava de buscar candidatos assim que
# encontrava 6 válidos (mesmo município/microrregião) e escolhia o de menor L1 só entre esses —
# uma amostra pequena demais do anel 15-40km para um pareamento de cobertura confiável (12 de 14
# pares saíram `ruim`, alguns com L1 > 1.0). Aumentado para buscar até 20 candidatos válidos (teto
# de tentativas de reverse-geocode também subiu, de 25 para 80, já que a maioria dos sites tem
# 90-160 candidatos passando nos filtros baratos — sobra espaço de sobra para explorar).
MAX_TENTATIVAS_MUNICIPIO = 80
MIN_CANDIDATOS_MUNICIPIO_VALIDO = 20

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_MIN_INTERVAL_S = 1.1
USER_AGENT = (
    "sentinela-verde-mba-dados-modelo-impacto/1.0 "
    "(uso academico, MBA Engenharia de Dados Mackenzie; contato: consignadouniverso@gmail.com)"
)

IBGE_MUNICIPIOS_UF_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"

GEOD = Geod(ellps="WGS84")

# nome completo do estado (como o Nominatim devolve em address.state) -> sigla UF
ESTADO_PARA_UF = {
    "acre": "AC", "alagoas": "AL", "amapá": "AP", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceará": "CE", "ceara": "CE", "distrito federal": "DF", "espírito santo": "ES",
    "espirito santo": "ES", "goiás": "GO", "goias": "GO", "maranhão": "MA", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG", "pará": "PA",
    "para": "PA", "paraíba": "PB", "paraiba": "PB", "paraná": "PR", "parana": "PR",
    "pernambuco": "PE", "piauí": "PI", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondônia": "RO", "rondonia": "RO",
    "roraima": "RR", "santa catarina": "SC", "são paulo": "SP", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}

_ultima_chamada_nominatim = 0.0


# --------------------------------------------------------------------------------------------
# Utilidades gerais
# --------------------------------------------------------------------------------------------


def _normalizar(txt: str | None) -> str:
    if not txt:
        return ""
    sem_acento = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


def _retry(fn, *, descricao: str, tentativas: int = 5, espera_inicial: float = 3.0):
    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            return fn()
        except (ee.EEException, requests.RequestException, urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            ultimo_erro = e
            if tentativa == tentativas - 1:
                raise
            espera = espera_inicial * (2**tentativa)
            print(
                f"  AVISO: {descricao} falhou ({e}); tentando de novo em {espera:.0f}s "
                f"({tentativa + 1}/{tentativas})...",
                file=sys.stderr,
            )
            time.sleep(espera)
    raise ultimo_erro  # pragma: no cover


def _http_get_json(url: str, params: dict[str, str]) -> Any:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip

        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _throttle_nominatim() -> None:
    global _ultima_chamada_nominatim
    agora = time.monotonic()
    espera = NOMINATIM_MIN_INTERVAL_S - (agora - _ultima_chamada_nominatim)
    if espera > 0:
        time.sleep(espera)
    _ultima_chamada_nominatim = time.monotonic()


def destino(lat: float, lon: float, azimute_deg: float, distancia_km: float) -> tuple[float, float]:
    lon2, lat2, _ = GEOD.fwd(lon, lat, azimute_deg, distancia_km * 1000.0)
    return lat2, lon2


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    _, _, dist_m = GEOD.inv(lon1, lat1, lon2, lat2)
    return dist_m / 1000.0


# --------------------------------------------------------------------------------------------
# Cache de geocodificação em disco (persiste entre execuções — poupa rede em reruns)
# --------------------------------------------------------------------------------------------


class CacheGeo:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"geocode_municipio": {}, "reverse": {}, "ibge_municipios_uf": {}}

    def salvar(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def geocode_municipio(self, municipio: str, uf: str) -> tuple[float, float] | None:
        chave = f"{_normalizar(municipio)}|{uf.upper()}"
        if chave in self.data["geocode_municipio"]:
            v = self.data["geocode_municipio"][chave]
            return tuple(v) if v else None
        _throttle_nominatim()
        query = f"{municipio}, {uf}, Brazil"
        try:
            resultado = _retry(
                lambda: _http_get_json(
                    NOMINATIM_SEARCH_URL, {"q": query, "format": "json", "limit": "1", "countrycodes": "br"}
                ),
                descricao=f"geocode município '{query}'",
            )
        except Exception as e:  # noqa: BLE001 — geocode falho não pode derrubar o script
            print(f"  AVISO: geocode de '{query}' falhou definitivamente: {e}", file=sys.stderr)
            resultado = []
        if resultado:
            lat, lon = float(resultado[0]["lat"]), float(resultado[0]["lon"])
            self.data["geocode_municipio"][chave] = [lat, lon]
            self.salvar()
            return lat, lon
        self.data["geocode_municipio"][chave] = None
        self.salvar()
        return None

    def reverse(self, lat: float, lon: float) -> dict | None:
        chave = f"{round(lat, 5)},{round(lon, 5)}"
        if chave in self.data["reverse"]:
            return self.data["reverse"][chave]
        _throttle_nominatim()
        try:
            resultado = _retry(
                lambda: _http_get_json(
                    NOMINATIM_REVERSE_URL,
                    {"lat": str(lat), "lon": str(lon), "format": "json", "zoom": "10", "addressdetails": "1"},
                ),
                descricao=f"reverse-geocode ({lat:.4f},{lon:.4f})",
                tentativas=3,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  AVISO: reverse-geocode ({lat:.4f},{lon:.4f}) falhou: {e}", file=sys.stderr)
            resultado = None
        addr = (resultado or {}).get("address", {})
        municipio = addr.get("municipality") or addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county")
        estado = addr.get("state")
        uf = ESTADO_PARA_UF.get(_normalizar(estado), None)
        out = {"municipio": municipio, "uf": uf} if municipio else None
        self.data["reverse"][chave] = out
        self.salvar()
        return out

    def microrregiao(self, municipio: str, uf: str) -> str | None:
        uf = uf.upper()
        if uf not in self.data["ibge_municipios_uf"]:
            try:
                lista = _retry(
                    lambda: _http_get_json(IBGE_MUNICIPIOS_UF_URL.format(uf=uf), {}),
                    descricao=f"IBGE municípios de {uf}",
                )
            except Exception as e:  # noqa: BLE001
                print(f"  AVISO: IBGE municípios de {uf} falhou: {e}", file=sys.stderr)
                lista = []
            mapa = {}
            for m in lista:
                micro = (m.get("microrregiao") or {}).get("nome")
                if micro:
                    mapa[_normalizar(m["nome"])] = micro
            self.data["ibge_municipios_uf"][uf] = mapa
            self.salvar()
        return self.data["ibge_municipios_uf"][uf].get(_normalizar(municipio))


# --------------------------------------------------------------------------------------------
# Carregamento de dados de entrada
# --------------------------------------------------------------------------------------------


def carregar_sites_tratamento() -> list[dict]:
    data = json.loads(SITES_PATH.read_text(encoding="utf-8"))
    sites = []
    for feat in data["features"]:
        p = feat["properties"]
        sites.append(
            {
                "site_id": p["site_id"],
                "nome": p.get("nome"),
                "municipio": p.get("municipio"),
                "uf": p.get("uf"),
                "lat": float(p["lat"]),
                "lon": float(p["lon"]),
                "buffer_km": float(p.get("buffer_km", 5)),
                "periodo_pre": p.get("periodo_pre"),
                "periodo_durante": p.get("periodo_durante"),
                "periodo_pos": p.get("periodo_pos"),
                "tier": p.get("tier"),
            }
        )
    return sorted(sites, key=lambda s: s["site_id"])


def carregar_pontos_contaminacao(sites_tratamento: list[dict], cache: CacheGeo) -> list[dict]:
    """16 sites de tratamento + todas as linhas de sites_candidatos.csv (inclusive rejeitadas).

    Prioridade de coordenada por linha de sites_candidatos.csv:
      1. aoi_id bate com um site_id de config/sites.geojson -> reusa a coordenada exata.
      2. aoi_id (via alias manual) bate com um site_id de consolidado_facilities.csv que já tem
         lat/lon (os 3 sites novos reconciliados pelo Guilherme) -> reusa a coordenada exata.
      3. senão, geocodifica o centróide do município (Nominatim) -> aproximado, documentado.
    """
    import csv

    pontos: list[dict] = [
        {"id": s["site_id"], "lat": s["lat"], "lon": s["lon"], "precisao": "exata_tratamento"}
        for s in sites_tratamento
    ]
    ids_tratamento = {s["site_id"] for s in sites_tratamento}

    facilities_coords: dict[str, tuple[float, float]] = {}
    if FACILITIES_PATH.exists():
        with FACILITIES_PATH.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lat, lon = row.get("lat"), row.get("lon")
                if lat and lon:
                    facilities_coords[row["site_id"]] = (float(lat), float(lon))

    alias_candidato_para_facility = {
        "bytedance-pecem": "pecem-datacenter",
        "scala-ai-city": "scala-ai-city",
        "rt-one-uberlandia": "rtone-uberlandia",
    }

    if not CANDIDATOS_PATH.exists():
        print(f"AVISO: {CANDIDATOS_PATH} não encontrado — lista de contaminação fica só com os 16 sites.", file=sys.stderr)
        return pontos

    with CANDIDATOS_PATH.open(encoding="utf-8") as f:
        candidatos = list(csv.DictReader(f))

    n_geocode, n_exato_facility, n_ja_no_geojson = 0, 0, 0
    for row in candidatos:
        aoi_id = row["aoi_id"]
        if aoi_id in ids_tratamento:
            n_ja_no_geojson += 1
            continue  # já coberto pelos 16 sites de tratamento acima
        facility_id = alias_candidato_para_facility.get(aoi_id)
        if facility_id and facility_id in facilities_coords:
            lat, lon = facilities_coords[facility_id]
            pontos.append({"id": aoi_id, "lat": lat, "lon": lon, "precisao": "exata_facility_reconciliada"})
            n_exato_facility += 1
            continue
        municipio, uf = row.get("municipio"), row.get("uf")
        if not municipio or not uf:
            continue
        coord = cache.geocode_municipio(municipio, uf)
        if coord is None:
            print(f"  AVISO: não foi possível geocodificar '{municipio}/{uf}' (aoi_id={aoi_id}) — excluído da lista de contaminação.", file=sys.stderr)
            continue
        pontos.append({"id": aoi_id, "lat": coord[0], "lon": coord[1], "precisao": "aproximada_centroide_municipio"})
        n_geocode += 1

    print(
        f"Lista de contaminação: {len(pontos)} pontos "
        f"({len(sites_tratamento)} sites exatos + {n_ja_no_geojson} já cobertos + "
        f"{n_exato_facility} facilities reconciliadas exatas + {n_geocode} centróides de município geocodificados)."
    )
    return pontos


# --------------------------------------------------------------------------------------------
# MapBiomas — distribuição de classes e L1 (Earth Engine)
# --------------------------------------------------------------------------------------------


def ano_mapbiomas_efetivo(ano: int, ano_min: int, ano_max: int) -> tuple[int, int]:
    ano_efetivo = min(max(ano, ano_min), ano_max)
    return ano_efetivo, ano - ano_efetivo


def distribuicao_mapbiomas(lat: float, lon: float, buffer_km: float, ano_efetivo: int, colecao_mb: str) -> dict[int, float] | None:
    geom = ee.Geometry.Point([lon, lat]).buffer(buffer_km * 1000)
    img = ee.Image(colecao_mb).select(f"classification_{ano_efetivo}").rename("codigo")

    def _hist():
        return img.reduceRegion(
            reducer=ee.Reducer.frequencyHistogram(),
            geometry=geom,
            scale=30,
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo()

    hist = _retry(_hist, descricao=f"histograma MapBiomas ({lat:.4f},{lon:.4f}, ano={ano_efetivo})")
    raw_counts = hist.get("codigo", {}) if hist else {}
    if not raw_counts:
        return None
    tabela = classes.REMAPS["mapbiomas"]
    counts = {c: 0.0 for c in range(1, 6)}
    for codigo_str, cnt in raw_counts.items():
        cid = tabela.get(int(float(codigo_str)), 0)
        if cid in counts:
            counts[cid] += float(cnt)
    total = sum(counts.values())
    if total <= 0:
        return None
    return {c: v / total for c, v in counts.items()}


def l1_distancia(a: dict[int, float], b: dict[int, float]) -> float:
    return sum(abs(a.get(c, 0.0) - b.get(c, 0.0)) for c in range(1, 6))


def flag_qualidade(l1: float) -> str:
    if l1 <= L1_BOM:
        return "bom"
    if l1 <= L1_ACEITAVEL:
        return "aceitavel"
    return "ruim"


# --------------------------------------------------------------------------------------------
# Geração de candidatos e funil de filtros
# --------------------------------------------------------------------------------------------


def grade_candidatos(lat0: float, lon0: float) -> list[tuple[float, float, float]]:
    """Retorna [(lat, lon, distancia_km_nominal), ...] — grade sistemática de raios x azimutes."""
    out = []
    for raio in RAIOS_GRADE_KM:
        for az in AZIMUTES_GRADE_DEG:
            lat, lon = destino(lat0, lon0, az, raio)
            out.append((lat, lon, float(raio)))
    return out


def passa_filtros_baratos(
    lat: float, lon: float, pontos_contaminacao: list[dict], buffers_ocupados: list[tuple[float, float, float]]
) -> tuple[bool, str | None]:
    for p in pontos_contaminacao:
        if distancia_km(lat, lon, p["lat"], p["lon"]) < CONTAM_MIN_KM:
            return False, f"contaminacao:{p['id']}"
    for (olat, olon, obuf) in buffers_ocupados:
        if distancia_km(lat, lon, olat, olon) < (BUFFER_KM + obuf):
            return False, "sobreposicao_buffer"
    return True, None


def checar_municipio(
    lat: float, lon: float, municipio_trat: str, uf_trat: str, cache: CacheGeo
) -> tuple[bool, str | None, str | None, str | None]:
    """Retorna (ok, metodo, municipio_encontrado, uf_encontrada)."""
    r = cache.reverse(lat, lon)
    if r is None or not r.get("municipio"):
        return False, None, None, None
    municipio_cand, uf_cand = r["municipio"], r.get("uf")
    if _normalizar(municipio_cand) == _normalizar(municipio_trat):
        return True, "mesmo_municipio", municipio_cand, uf_cand or uf_trat
    if uf_cand:
        micro_trat = cache.microrregiao(municipio_trat, uf_trat)
        micro_cand = cache.microrregiao(municipio_cand, uf_cand)
        if micro_trat and micro_cand and micro_trat == micro_cand:
            return True, "municipio_vizinho_microrregiao_ibge", municipio_cand, uf_cand
    return False, None, municipio_cand, uf_cand


def rng_do_site(site_id: str) -> np.random.Generator:
    """RNG determinístico e INDEPENDENTE por site (seed global + hash do site_id).

    Rodada de melhoria (2026-09-03): a primeira versão usava um único gerador compartilhado,
    consumido sequencialmente em ordem alfabética de site_id — isso amarrava a ordem de
    exploração de CADA site à ordem/composição do lote inteiro processado na mesma execução.
    Reprocessar um subconjunto dos sites (para caber no orçamento de tempo de uma chamada de
    ferramenta, sem rodar em background) mudava a ordem de exploração de sites não tocados
    pela mudança de composição do lote — o oposto de reprodutível. Com um gerador independente
    por site (seed fixa 42 + hash estável do site_id), a ordem de exploração de um site é sempre
    a mesma não importa quais outros sites foram processados antes, depois, ou em qual chamada.
    """
    return np.random.default_rng([SEED, zlib.crc32(site_id.encode("utf-8"))])


def buscar_controle(
    site: dict,
    pontos_contaminacao: list[dict],
    buffers_ocupados: list[tuple[float, float, float]],
    cfg_labels: dict,
    cache: CacheGeo,
) -> dict:
    site_id = site["site_id"]

    if not site.get("periodo_pre"):
        return {
            "status": "sem_dados_temporais",
            "motivo": (
                "config/sites.geojson não define periodo_pre (nem ano_inicio_obra/"
                "ano_inicio_operacao_estimado) para este site — sem ano de referência não é "
                "possível herdar janelas temporais nem calcular similaridade de cobertura "
                "pré-obra. Reportado como lacuna de dado-fonte, não como falha de pareamento."
            ),
        }

    ano_pre_ini = int(site["periodo_pre"].split("-")[0])
    ano_mb_efetivo, distancia_safra = ano_mapbiomas_efetivo(
        ano_pre_ini, cfg_labels["ano_mapbiomas_min"], cfg_labels["ano_mapbiomas_max"]
    )
    colecao_mb = cfg_labels["colecao_mapbiomas"]

    dist_tratamento = distribuicao_mapbiomas(site["lat"], site["lon"], site["buffer_km"], ano_mb_efetivo, colecao_mb)
    if dist_tratamento is None:
        return {"status": "sem_controle", "motivo": "MapBiomas não retornou pixels válidos no buffer do próprio tratamento — não é possível medir similaridade."}

    candidatos_grade = grade_candidatos(site["lat"], site["lon"])
    ordem = rng_do_site(site_id).permutation(len(candidatos_grade))

    n_pos_barato = 0
    tentativas_municipio = 0
    candidatos_municipio_valido: list[dict] = []

    for idx in ordem:
        lat, lon, raio_nominal = candidatos_grade[int(idx)]
        d = distancia_km(site["lat"], site["lon"], lat, lon)
        if not (DIST_MIN_KM <= d <= DIST_MAX_KM):
            continue
        ok_barato, _motivo = passa_filtros_baratos(lat, lon, pontos_contaminacao, buffers_ocupados)
        if not ok_barato:
            continue
        n_pos_barato += 1

        if tentativas_municipio >= MAX_TENTATIVAS_MUNICIPIO or len(candidatos_municipio_valido) >= MIN_CANDIDATOS_MUNICIPIO_VALIDO:
            continue
        tentativas_municipio += 1
        ok_mun, metodo, municipio_cand, uf_cand = checar_municipio(lat, lon, site["municipio"], site["uf"], cache)
        if ok_mun:
            candidatos_municipio_valido.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "distancia_km": d,
                    "metodo_municipio": metodo,
                    "municipio": municipio_cand,
                    "uf": uf_cand,
                }
            )

    if not candidatos_municipio_valido:
        return {
            "status": "sem_controle",
            "motivo": (
                f"nenhum candidato na grade 15-40km passou nos filtros geométricos+contaminação "
                f"E no filtro de município/microrregião IBGE ({n_pos_barato} passaram nos filtros "
                f"baratos, {tentativas_municipio} tentativas de reverse-geocode, 0 válidos)."
            ),
            "n_pos_filtro_barato": n_pos_barato,
            "n_tentativas_municipio": tentativas_municipio,
        }

    melhor = None
    melhor_l1 = None
    melhor_dist_ctrl = None
    for cand in candidatos_municipio_valido:
        dist_ctrl = distribuicao_mapbiomas(cand["lat"], cand["lon"], BUFFER_KM, ano_mb_efetivo, colecao_mb)
        if dist_ctrl is None:
            continue
        l1 = l1_distancia(dist_tratamento, dist_ctrl)
        if melhor_l1 is None or l1 < melhor_l1:
            melhor, melhor_l1, melhor_dist_ctrl = cand, l1, dist_ctrl

    if melhor is None:
        return {
            "status": "sem_controle",
            "motivo": (
                f"{len(candidatos_municipio_valido)} candidatos passaram no filtro de município, mas "
                "nenhum teve pixels MapBiomas válidos no próprio buffer (fora de área continental?)."
            ),
        }

    return {
        "status": "ok",
        "controle": {
            "site_id_controle": f"ctrl-{site_id}",
            "pareado_com": site_id,
            "nome": f"Controle pareado — {site.get('nome') or site_id}",
            "lat": round(melhor["lat"], 6),
            "lon": round(melhor["lon"], 6),
            "buffer_km": BUFFER_KM,
            "municipio": melhor["municipio"],
            "uf": melhor["uf"],
            "metodo_municipio": melhor["metodo_municipio"],
            "distancia_km": round(melhor["distancia_km"], 3),
            "l1_cobertura": round(melhor_l1, 4),
            "flag_qualidade": flag_qualidade(melhor_l1),
            "ano_mapbiomas_referencia": ano_mb_efetivo,
            "distancia_safra_mapbiomas": distancia_safra,
            "periodo_pre": site["periodo_pre"],
            "periodo_durante": site["periodo_durante"],
            "periodo_pos": site["periodo_pos"],
            "dist_classes_tratamento": {str(k): round(v, 4) for k, v in dist_tratamento.items()},
            "dist_classes_controle": {str(k): round(v, 4) for k, v in melhor_dist_ctrl.items()},
            "n_candidatos_grade": len(candidatos_grade),
            "n_pos_filtro_barato": n_pos_barato,
            "n_candidatos_municipio_valido": len(candidatos_municipio_valido),
        },
    }


# --------------------------------------------------------------------------------------------
# Figura de sanidade (RGB Sentinel-2/Landsat, lado a lado)
# --------------------------------------------------------------------------------------------


def _composite_rgb(lat: float, lon: float, buffer_km: float, ano_ini: int, ano_fim: int) -> Image.Image | None:
    geom = ee.Geometry.Point([lon, lat]).buffer(buffer_km * 1000)
    region = geom.bounds()

    def _tentar_s2() -> Image.Image | None:
        for limiar_nuvem in (50, 100):
            ic = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(geom)
                .filterDate(f"{ano_ini}-01-01", f"{ano_fim + 1}-01-01")
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", limiar_nuvem))
            )
            n = _retry(ic.size().getInfo, descricao="contar cenas S2")
            if n > 0:
                img = ic.median().select(["B4", "B3", "B2"])
                vis = img.visualize(min=0, max=3000, gamma=1.3)
                url = _retry(
                    lambda: vis.getThumbURL({"region": region, "dimensions": 480, "format": "png"}),
                    descricao="thumbnail S2",
                )
                content = _retry(lambda: requests.get(url, timeout=120).content, descricao="download thumbnail S2")
                return Image.open(io.BytesIO(content)).convert("RGB")
        return None

    def _tentar_landsat() -> Image.Image | None:
        for limiar_nuvem in (50, 100):
            ic = (
                ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                .filterBounds(geom)
                .filterDate(f"{ano_ini}-01-01", f"{ano_fim + 1}-01-01")
                .filter(ee.Filter.lt("CLOUD_COVER", limiar_nuvem))
            )
            n = _retry(ic.size().getInfo, descricao="contar cenas Landsat")
            if n > 0:
                def _escala(im):
                    opt = im.select("SR_B.").multiply(0.0000275).add(-0.2)
                    return im.addBands(opt, overwrite=True)

                img = ic.map(_escala).median().select(["SR_B4", "SR_B3", "SR_B2"])
                vis = img.visualize(min=0.0, max=0.3, gamma=1.3)
                url = _retry(
                    lambda: vis.getThumbURL({"region": region, "dimensions": 480, "format": "png"}),
                    descricao="thumbnail Landsat",
                )
                content = _retry(lambda: requests.get(url, timeout=120).content, descricao="download thumbnail Landsat")
                return Image.open(io.BytesIO(content)).convert("RGB")
        return None

    try:
        if ano_fim >= 2017:
            img = _tentar_s2()
            if img is None:
                img = _tentar_landsat()
        else:
            img = _tentar_landsat()
        return img
    except Exception as e:  # noqa: BLE001 — figura de sanidade não pode derrubar o script
        print(f"  AVISO: composite RGB falhou ({lat:.4f},{lon:.4f}): {e}", file=sys.stderr)
        return None


def gerar_figura_sanidade(site: dict, controle: dict, out_path: Path) -> bool:
    if out_path.exists():
        return True
    ano_ini, ano_fim = (int(x) for x in site["periodo_pre"].split("-"))
    img_trat = _composite_rgb(site["lat"], site["lon"], site["buffer_km"], ano_ini, ano_fim)
    img_ctrl = _composite_rgb(controle["lat"], controle["lon"], controle["buffer_km"], ano_ini, ano_fim)
    if img_trat is None and img_ctrl is None:
        print(f"  AVISO: sem imagem disponível (nem S2 nem Landsat) para {site['site_id']} nem seu controle — figura pulada.", file=sys.stderr)
        return False
    faltando = Image.new("RGB", (480, 480), (200, 200, 200))
    img_trat = img_trat or faltando
    img_ctrl = img_ctrl or faltando

    pad_top = 34
    w = img_trat.width + img_ctrl.width + 20
    h = max(img_trat.height, img_ctrl.height) + pad_top
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(img_trat, (0, pad_top))
    canvas.paste(img_ctrl, (img_trat.width + 20, pad_top))
    draw = ImageDraw.Draw(canvas)
    draw.text((6, 8), f"TRATAMENTO: {site['site_id']} ({site['periodo_pre']})", fill=(0, 0, 0))
    draw.text(
        (img_trat.width + 26, 8),
        f"CONTROLE: dist={controle['distancia_km']:.1f}km L1={controle['l1_cobertura']:.3f} ({controle['flag_qualidade']})",
        fill=(0, 0, 0),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return True


# --------------------------------------------------------------------------------------------
# Checkpoint
# --------------------------------------------------------------------------------------------


def carregar_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {}


def salvar_checkpoint(checkpoint: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------------
# Montagem dos artefatos finais a partir do checkpoint
# --------------------------------------------------------------------------------------------


def montar_saidas(sites_tratamento: list[dict], checkpoint: dict) -> None:
    features = []
    linhas_csv = []
    for site in sites_tratamento:
        site_id = site["site_id"]
        r = checkpoint.get(site_id)
        if r is None:
            continue
        if r["status"] != "ok":
            linhas_csv.append(
                {
                    "site_tratamento": site_id,
                    "site_controle": "",
                    "distancia_km": "",
                    "l1_cobertura": "",
                    "flag_qualidade": r["status"],
                    "metodo_municipio": "",
                    "municipio_tratamento": site["municipio"],
                    "municipio_controle": "",
                    "motivo_sem_controle": r.get("motivo", ""),
                }
            )
            continue
        c = r["controle"]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "site_id": c["site_id_controle"],
                    "nome": c["nome"],
                    "pareado_com": c["pareado_com"],
                    "municipio": c["municipio"],
                    "uf": c["uf"],
                    "buffer_km": c["buffer_km"],
                    "tipo": "controle",
                    "metodo_pareamento": "grade_sistematica_seed42_L1_mapbiomas",
                    "metodo_municipio": c["metodo_municipio"],
                    "distancia_km": c["distancia_km"],
                    "l1_cobertura": c["l1_cobertura"],
                    "flag_qualidade": c["flag_qualidade"],
                    "ano_mapbiomas_referencia": c["ano_mapbiomas_referencia"],
                    "distancia_safra_mapbiomas": c["distancia_safra_mapbiomas"],
                    "periodo_pre": c["periodo_pre"],
                    "periodo_durante": c["periodo_durante"],
                    "periodo_pos": c["periodo_pos"],
                    "seed": SEED,
                    "data_geracao": datetime.now(UTC).strftime("%Y-%m-%d"),
                },
                "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
            }
        )
        linhas_csv.append(
            {
                "site_tratamento": site_id,
                "site_controle": c["site_id_controle"],
                "distancia_km": c["distancia_km"],
                "l1_cobertura": c["l1_cobertura"],
                "flag_qualidade": c["flag_qualidade"],
                "metodo_municipio": c["metodo_municipio"],
                "municipio_tratamento": site["municipio"],
                "municipio_controle": c["municipio"],
                "motivo_sem_controle": "",
                **{f"dist_trat_classe{k}": v for k, v in c["dist_classes_tratamento"].items()},
                **{f"dist_ctrl_classe{k}": v for k, v in c["dist_classes_controle"].items()},
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geojson = {"type": "FeatureCollection", "features": features}
    OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    import csv

    campos = [
        "site_tratamento", "site_controle", "distancia_km", "l1_cobertura", "flag_qualidade",
        "metodo_municipio", "municipio_tratamento", "municipio_controle", "motivo_sem_controle",
    ]
    if linhas_csv:
        extras = sorted({k for linha in linhas_csv for k in linha if k not in campos})
        campos = campos + extras
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for linha in linhas_csv:
            writer.writerow({k: linha.get(k, "") for k in campos})

    print(f"Gravado: {OUT_GEOJSON} ({len(features)} controles)")
    print(f"Gravado: {OUT_CSV} ({len(linhas_csv)} linhas)")


def escrever_metodologia(sites_tratamento: list[dict], checkpoint: dict, n_pontos_contaminacao: int, cfg_labels: dict) -> None:
    total = len(sites_tratamento)
    processados = {sid: checkpoint[sid] for sid in checkpoint if sid in {s["site_id"] for s in sites_tratamento}}
    n_ok = sum(1 for r in processados.values() if r["status"] == "ok")
    n_sem_controle = sum(1 for r in processados.values() if r["status"] == "sem_controle")
    n_sem_dados = sum(1 for r in processados.values() if r["status"] == "sem_dados_temporais")
    n_erro = sum(1 for r in processados.values() if r["status"] == "erro")
    n_pendentes = total - len(processados)

    flags = {"bom": 0, "aceitavel": 0, "ruim": 0}
    for r in processados.values():
        if r["status"] == "ok":
            flags[r["controle"]["flag_qualidade"]] += 1

    linhas_ruim = [
        f"- `{sid}` -> `{r['controle']['site_id_controle']}`: L1={r['controle']['l1_cobertura']:.4f} "
        f"(dist={r['controle']['distancia_km']:.1f}km, método_município={r['controle']['metodo_municipio']})"
        for sid, r in processados.items()
        if r["status"] == "ok" and r["controle"]["flag_qualidade"] == "ruim"
    ]
    linhas_sem_controle = [
        f"- `{sid}` [{r['status']}]: {r.get('motivo', '(sem motivo registrado)')}"
        for sid, r in processados.items()
        if r["status"] in ("sem_controle", "sem_dados_temporais", "erro")
    ]

    md = f"""# Metodologia — grupo de controle pareado (apoio ao modelo de impacto)

Gerado por `dados-modelo-impacto/scripts/gerar_controles_pareados.py` em
{datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}. Versão adaptada e mais leve de
`docs/tarefas/SV-29-grupo-controle-pareado.md` — mesma lógica de geração/validação de candidatos,
sem rodar o pipeline pesado de ingestão de imagem (isso é escopo do classificador principal, fora
daqui). Ver `dados-modelo-impacto/README.md` para o contexto geral deste apoio.

## Escopo

- **16 sites originais** de `config/sites.geojson` (todos — o arquivo já contém só os validados
  V1-V5, nenhum filtro adicional necessário).
- **Decisão explícita, não esquecimento**: os 3 sites novos reconciliados a partir do scraping do
  Guilherme (Scala AI City / Eldorado do Sul-RS, Pecém Data Center / São Gonçalo do Amarante-CE,
  RT-One Uberlândia/MG — `dados-modelo-impacto/processed/consolidado_facilities.csv`,
  `origem_lista == "datacentermap_novo"`) **não geram controle nesta rodada**: estão em estágio de
  planejamento/construção futura, sem `periodo_pre/periodo_durante/periodo_pos` reais definidos —
  não há janela temporal para herdar nem ano de referência para medir similaridade pré-obra. Suas
  coordenadas (quando conhecidas) SÃO usadas na lista de contaminação, para que nenhum controle dos
  16 sites originais caia perto delas.

## Passo a passo

1. **Grade de candidatos**: para cada site de tratamento, uma grade sistemática de
   {len(RAIOS_GRADE_KM)} raios ({', '.join(str(r) for r in RAIOS_GRADE_KM)} km) x
   {len(AZIMUTES_GRADE_DEG)} azimutes (a cada 15°) = {len(RAIOS_GRADE_KM) * len(AZIMUTES_GRADE_DEG)}
   pontos candidatos, calculados com geodésia WGS84 exata (`pyproj.Geod.fwd`), não aproximação
   planar.
2. **Sorteio determinístico e independente por site**: `numpy.random.default_rng([{SEED}, hash(site_id)])`
   (seed global {SEED}, mesma convenção do repositório — `RANDOM_SEED`/`CLAUDE.md`, combinada com um
   hash estável do `site_id` de cada site) embaralha a ORDEM de exploração da grade daquele site.
   Cada site tem seu próprio gerador independente — a ordem de exploração de um site não depende de
   quais outros sites foram processados antes/depois nem de como o trabalho foi dividido em lotes
   (reprodutível rodando de novo com a mesma seed, ou processando só um subconjunto dos sites com
   `--sites`). Isso não é um sorteio cego: dentre os candidatos que passam **todos** os filtros
   geométricos abaixo, o escolhido é o de **menor distância L1 de cobertura** contra o tratamento —
   a seed garante que a ordem de busca (e, portanto, o resultado final quando há empate ou corte por
   tentativas) seja sempre a mesma, não que a escolha final ignore similaridade de cobertura.
3. **Filtros geométricos (sem custo de rede), aplicados na ordem embaralhada**:
   - Distância entre {DIST_MIN_KM:.0f} e {DIST_MAX_KM:.0f} km do tratamento.
   - >= {CONTAM_MIN_KM:.0f} km de todo ponto da lista de contaminação (abaixo).
   - >= {NO_OVERLAP_MIN_KM:.0f} km (soma dos dois buffers de 5 km) de qualquer buffer de site já
     existente (os 16 originais) ou de controle já colocado nesta mesma rodada (sites processados
     em ordem alfabética; cada controle aceito entra na lista de buffers ocupados antes do próximo
     site ser processado).
4. **Filtro de município/vizinhança** (com rede — só nos candidatos que passaram o passo 3):
   reverse-geocode do ponto candidato via Nominatim (OpenStreetMap). Aceito se:
   - o município retornado é o mesmo do tratamento (comparação normalizada, sem acento/maiúscula); OU
   - o município retornado está na **mesma microrregião do IBGE** que o município do tratamento
     (`servicodados.ibge.gov.br/api/v1/localidades/estados/{{uf}}/municipios`, campo
     `microrregiao.nome`) — **aproximação documentada de "município vizinho"**: microrregião do
     IBGE agrupa municípios geograficamente próximos com estrutura socioeconômica correlata, não é
     literalmente "compartilha fronteira" (que exigiria a malha poligonal de município a município,
     mais pesada de consultar), mas captura o espírito do critério de SV-29 ("mantém regime de
     licenciamento, pressão de expansão urbana e regime de chuva comparáveis") sem exigir geometria
     poligonal completa.
   Para de tentar candidatos assim que {MIN_CANDIDATOS_MUNICIPIO_VALIDO} válidos forem coletados, ou
   após {MAX_TENTATIVAS_MUNICIPIO} tentativas de reverse-geocode sem sucesso suficiente (limite para
   manter o tempo de execução tratável — sites com região muito restritiva podem não conseguir
   controle por esse motivo, reportado explicitamente, não escondido).
5. **Pareamento por cobertura do solo**: para os candidatos que passam o passo 4, calcula a
   distância L1 (soma das diferenças absolutas de proporção, por classe) entre a distribuição das 5
   classes do repositório (`config/classes.yml`, remap `mapbiomas`) num buffer de 5 km do candidato
   e do tratamento, na coleção `{cfg_labels["colecao_mapbiomas"]}` (MapBiomas Coleção 9, ver
   `docs/decisoes/ADR-004-fonte-de-labels.md`),
   no ano inicial de `periodo_pre` do tratamento — grampeado à janela 2013-2023 coberta pela
   Coleção 9 (mesmo mecanismo de `distancia_safra` de `src/sentinela/gee/labels.py`). Escolhe o
   candidato de menor L1.
6. **Lista de contaminação** ({n_pontos_contaminacao} pontos): os 16 sites de `config/sites.geojson`
   (coordenada exata) + todas as {len(_carregar_candidatos_csv_bruto())} linhas de
   `config/sites_candidatos.csv`, **inclusive as rejeitadas** — são justamente onde há data center
   que não entrou no estudo, e usar uma delas como controle contaminaria a comparação. Coordenada
   por linha: reusa a coordenada exata quando o `aoi_id` já corresponde a um dos 16 sites (16 casos)
   ou a uma das 3 facilities novas reconciliadas com coordenada conhecida (2 casos: Scala AI City,
   Pecém — RT-One Uberlândia não tem coordenada em nenhuma fonte disponível); para as demais linhas
   (candidatos rejeitados sem coordenada validada em SV-25, que nunca rodou para eles), geocodifica
   o **centróide do município** via Nominatim — uma aproximação real (o centróide não é o endereço
   exato do data center), documentada aqui, não escondida. É o mesmo tipo de aproximação já usado
   em `config/sites.geojson` para casos sem endereço exato (ex.: `ascenty-sumare`, `everest-goiania`,
   método `geocode`/precisão `aproximada`).
7. **Figura de sanidade**: composto RGB mediano (Sentinel-2 se `periodo_pre` termina em 2017 ou
   depois, senão Landsat 8) sobre a janela `periodo_pre` inteira do tratamento (não só o ano
   inicial — mais robusto a nuvem para uma checagem visual rápida), tratamento e controle lado a
   lado, em `raw/controles/figuras/{{site_id}}.png`.

## Limiares de qualidade (mesmos de SV-29)

`l1_cobertura` <= {L1_BOM:.2f} -> `bom` · <= {L1_ACEITAVEL:.2f} -> `aceitavel` · acima -> `ruim`.
Pares `ruim` são reportados, não escondidos nem descartados — nenhum limiar foi afrouxado para
"melhorar" o resultado.

## Resultado desta rodada

- **{n_ok} de {total}** sites com controle gerado (`ok`).
- **{n_sem_controle}** sites sem candidato válido (filtros geométricos/município esgotados sem
  sucesso).
- **{n_sem_dados}** site(s) sem dado temporal de origem (`periodo_pre` ausente em
  `config/sites.geojson`) — não é falha de pareamento, é lacuna do dado-fonte.
- **{n_erro}** site(s) com exceção não recuperada durante o processamento (ver motivo abaixo —
  normalmente falha de rede persistente; rode o script de novo, o checkpoint permite reprocessar
  só esse site apagando a entrada dele em `_checkpoint.json`, ou use `--force` para refazer tudo).
- **{n_pendentes}** site(s) ainda não processados nesta rodada (rode o script de novo para
  continuar — checkpoint em `raw/controles/_checkpoint.json`).

Distribuição de qualidade entre os `{n_ok}` controles gerados: **bom={flags['bom']}**,
**aceitavel={flags['aceitavel']}**, **ruim={flags['ruim']}**.

### Pares `ruim` (reportados, não escondidos)
{chr(10).join(linhas_ruim) if linhas_ruim else "(nenhum)"}

### Sites sem controle / sem dado temporal (motivo)
{chr(10).join(linhas_sem_controle) if linhas_sem_controle else "(nenhum)"}

## Limitações conhecidas (documentadas, não escondidas)

- A adjacência de município usa "mesma microrregião do IBGE" como proxy de "município vizinho",
  não a malha poligonal oficial (touching de fronteiras) — mais simples de consultar em lote, mas
  uma microrregião pode ser maior que uma vizinhança estrita de fronteira em alguns casos.
- A lista de contaminação usa centróide de município (não endereço exato) para os candidatos
  rejeitados de `config/sites_candidatos.csv` que nunca tiveram coordenada validada (SV-25 nunca
  rodou para eles, por definição — foram rejeitados antes dessa etapa). Isso é conservador na
  direção errada em municípios muito grandes (o centróide pode estar longe do data center real,
  então a checagem de 5 km pode não pegar contaminação real fora do centro do município) — reportado
  explicitamente como risco residual, não mitigado nesta rodada (mitigação completa exigiria
  geocodificação de endereço-nível, fora do escopo "mais leve" pedido).
- A figura de sanidade é um composto simples (sem harmonização multi-sensor completa de
  `sentinela.gee.harmonizacao`, que é do classificador principal) — serve só para rejeição visual
  rápida, não para análise quantitativa.
- Esta rodada não roda o pipeline de ingestão de imagem completo (SV-06/06b/07/08/14) sobre os
  controles — só a geometria dos pontos e a checagem MapBiomas. Se o Guilherme precisar dos
  indicadores completos (LST, área por classe etc.) também para os controles, isso é um passo
  seguinte, fora do escopo desta tarefa.
"""
    OUT_METODOLOGIA.write_text(md, encoding="utf-8")
    print(f"Gravado: {OUT_METODOLOGIA}")


_candidatos_csv_cache: list[dict] | None = None


def _carregar_candidatos_csv_bruto() -> list[dict]:
    global _candidatos_csv_cache
    if _candidatos_csv_cache is None:
        import csv

        with CANDIDATOS_PATH.open(encoding="utf-8") as f:
            _candidatos_csv_cache = list(csv.DictReader(f))
    return _candidatos_csv_cache


# --------------------------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="ignora o checkpoint e reprocessa todos os sites")
    parser.add_argument(
        "--sites",
        type=str,
        default=None,
        help=(
            "lista de site_id separados por vírgula para processar só esse subconjunto nesta "
            "chamada (os demais, se ainda não estiverem no checkpoint, ficam pendentes para uma "
            "próxima chamada — útil para rodar em lotes pequenos e síncronos). Sites já no "
            "checkpoint continuam sendo pulados independentemente desta lista."
        ),
    )
    args = parser.parse_args(argv)
    sites_selecionados = (
        {s.strip() for s in args.sites.split(",") if s.strip()} if args.sites else None
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURAS_DIR.mkdir(parents=True, exist_ok=True)

    print("Inicializando Google Earth Engine...")
    try:
        init_ee()
    except ConfigError as e:
        print(f"ERRO DE CONFIGURAÇÃO:\n{e}", file=sys.stderr)
        return 1

    cfg_labels = SETTINGS.params()["labels"]

    cache = CacheGeo(CACHE_GEO_PATH)
    sites_tratamento = carregar_sites_tratamento()
    print(f"{len(sites_tratamento)} sites de tratamento carregados de {SITES_PATH}")

    pontos_contaminacao = carregar_pontos_contaminacao(sites_tratamento, cache)

    checkpoint = {} if args.force else carregar_checkpoint()

    buffers_ocupados: list[tuple[float, float, float]] = [
        (s["lat"], s["lon"], s["buffer_km"]) for s in sites_tratamento
    ]
    # buffers de controles já resolvidos em rodadas anteriores também contam como ocupados
    for sid, r in checkpoint.items():
        if r.get("status") == "ok":
            c = r["controle"]
            buffers_ocupados.append((c["lat"], c["lon"], c["buffer_km"]))

    for site in sites_tratamento:
        site_id = site["site_id"]
        if site_id in checkpoint:
            print(f"[{site_id}] já processado (checkpoint) — pulando (use --force para refazer).")
            continue
        if sites_selecionados is not None and site_id not in sites_selecionados:
            # Fora do lote desta chamada (--sites). Cada site usa um RNG independente
            # (rng_do_site — seed global + hash do site_id), então pular um site aqui não afeta
            # a ordem de exploração de nenhum outro: não há estado compartilhado a preservar.
            print(f"[{site_id}] fora do lote desta chamada (--sites) — pendente para próxima chamada.")
            continue

        print(f"\n=== {site_id} ({site['municipio']}/{site['uf']}) ===")
        try:
            resultado = buscar_controle(site, pontos_contaminacao, buffers_ocupados, cfg_labels, cache)
        except Exception as e:  # noqa: BLE001 — um site falhar não pode derrubar o lote inteiro
            print(f"[{site_id}] ERRO não recuperado: {e}", file=sys.stderr)
            resultado = {"status": "erro", "motivo": f"exceção não recuperada: {e}"}
        resultado["gerado_em"] = datetime.now(UTC).isoformat()
        checkpoint[site_id] = resultado
        salvar_checkpoint(checkpoint)

        if resultado["status"] == "ok":
            c = resultado["controle"]
            print(
                f"[{site_id}] OK -> {c['site_id_controle']} @ ({c['lat']},{c['lon']}) "
                f"dist={c['distancia_km']:.1f}km L1={c['l1_cobertura']:.4f} ({c['flag_qualidade']}) "
                f"município={c['municipio']}/{c['uf']} ({c['metodo_municipio']})"
            )
            buffers_ocupados.append((c["lat"], c["lon"], c["buffer_km"]))
            fig_path = FIGURAS_DIR / f"{site_id}.png"
            ok_fig = gerar_figura_sanidade(site, c, fig_path)
            print(f"[{site_id}] figura de sanidade: {'OK -> ' + str(fig_path) if ok_fig else 'FALHOU'}")
        else:
            print(f"[{site_id}] {resultado['status'].upper()}: {resultado.get('motivo')}")

    montar_saidas(sites_tratamento, checkpoint)
    escrever_metodologia(sites_tratamento, checkpoint, len(pontos_contaminacao), cfg_labels)

    total = len(sites_tratamento)
    n_processados = sum(1 for s in sites_tratamento if s["site_id"] in checkpoint)
    print(f"\n{n_processados}/{total} sites processados nesta(s) rodada(s).")
    if n_processados < total:
        print("Rode o script de novo para continuar (checkpoint preserva o progresso).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
