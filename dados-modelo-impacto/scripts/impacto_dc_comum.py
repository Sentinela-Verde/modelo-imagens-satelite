"""Base compartilhada da frente "modelo de impacto" sobre a lista de data centers do Guilherme.

Contexto: `dados-modelo-impacto/README.md` (escopo desta pasta) e
`dados-modelo-impacto/raw/controles-rf/METODOLOGIA.md` (o desenho completo desta rodada).

Este módulo NÃO reimplementa nada do classificador principal — ele orquestra os módulos de
`src/sentinela/` para uma lista ARBITRÁRIA de pontos (lat, lon, ano), que é a única coisa que
aqueles módulos não fazem sozinhos: os CLIs de `sentinela.gee.landsat` / `sentinela.gee.sentinel2`
/ `sentinela.predict` recebem `--site <id>` e resolvem o id contra `config/sites.geojson`, mas as
FUNÇÕES por trás deles (`ingerir_site_ano`, `processar_site_ano`, `classificar_site_ano`) aceitam
um dict de site solto. É esse caminho que usamos aqui, para não precisar cadastrar cada ponto de
controle no `config/sites.geojson` do classificador (que é a lista oficial de tratamento do outro
escopo e não deve inchar com pontos desta frente).

Área por classe é recalculada aqui em vez de chamar `sentinela.export_indicadores` porque aquele
módulo exige, por contrato, que todo `site_id` exista em `config/sites.geojson` (para propagar
tier/precisão de coordenada) e levanta `ExportError` para qualquer outro — o que é o comportamento
certo lá e inaplicável aqui. A conta em si é a mesma: contagem de pixels por classe x resolução².
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from pyproj import Geod

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sentinela import predict as mod_predict
from sentinela.config import SETTINGS
from sentinela.features import indices as mod_indices
from sentinela.gee import landsat as mod_landsat
from sentinela.gee import sentinel2 as mod_s2
from sentinela.gee.auth import init_ee

# --------------------------------------------------------------------------------------------
# Constantes de escopo desta rodada
# --------------------------------------------------------------------------------------------

DIR_SAIDA = REPO_ROOT / "dados-modelo-impacto" / "raw" / "controles-rf"
DIR_FIGURAS = DIR_SAIDA / "figuras"
DIR_PROCESSED = REPO_ROOT / "dados-modelo-impacto" / "processed"

CSV_GUILHERME_DCS = Path.home() / "Downloads" / "datacenter_filtrado (1).csv"
CSV_GUILHERME_CANDIDATOS = Path.home() / "Downloads" / "datacenter_expandido_6_pontos (1).csv"

MODELO_PATH = REPO_ROOT / "models" / "rf_v1.0-tuned.joblib"
MODELO_VERSAO = "rf_v1.0-tuned"

SEED = 42
BUFFER_KM = 5.0
ANOS_ANTES = 3
ANOS_DEPOIS = 3

# Cobertura de sensor DEPOIS da extensão desta rodada. Landsat vai a 2024 (era 2021 no repo) —
# decisão do usuário em 2026-09-05, justamente para que a janela obra-3..obra+3 de cada campus
# caiba num único sensor e não cruze a fronteira 2018/2019 medida por SV-20
# (`reports/validacao_sensores.md`). 2013 é o piso da faixa_a (`config/params.yml`); a faixa_b
# (2000-2011) segue desabilitada porque a harmonização TM->OLI nunca foi validada.
LANDSAT_ANO_MIN, LANDSAT_ANO_MAX = 2013, 2024
S2_ANO_MIN, S2_ANO_MAX = 2019, 2025

CLASS_IDS = (1, 2, 3, 4, 5)
CLASSE_NOME = {
    1: "vegetacao_densa",
    2: "vegetacao_rala",
    3: "solo_exposto_obras",
    4: "construida_urbana",
    5: "agua",
}

# Os 15 campi desta rodada: os 16 sites validados de `config/sites.geojson` menos
# `odata-hortolandia`, que não tem `ano_inicio_obra` em nenhuma fonte (mesma lacuna que já o
# deixou sem controle na rodada de `gerar_controles_pareados.py`). Sem ano de obra não há janela
# temporal para definir "1 ano antes" nem "3 anos antes/depois".
SITE_SEM_ANO_OBRA = "odata-hortolandia"

_geod = Geod(ellps="WGS84")


# --------------------------------------------------------------------------------------------
# Geodésia
# --------------------------------------------------------------------------------------------


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância geodésica WGS84 exata (não aproximação planar)."""
    return _geod.inv(lon1, lat1, lon2, lat2)[2] / 1000.0


def ponto_por_azimute(
    lat: float, lon: float, azimute_graus: float, distancia: float
) -> tuple[float, float]:
    """Ponto a `distancia` km de (lat, lon) no azimute dado. Retorna (lat, lon)."""
    lon2, lat2, _ = _geod.fwd(lon, lat, azimute_graus, distancia * 1000.0)
    return lat2, lon2


# --------------------------------------------------------------------------------------------
# Sites e janelas temporais
# --------------------------------------------------------------------------------------------


def carregar_sites_validados() -> dict[str, dict[str, Any]]:
    """Os 16 sites de `config/sites.geojson`, por `site_id`."""
    caminho = REPO_ROOT / "config" / "sites.geojson"
    with caminho.open("r", encoding="utf-8") as f:
        geo = json.load(f)
    return {feat["properties"]["site_id"]: feat["properties"] for feat in geo["features"]}


def carregar_campi() -> list[dict[str, Any]]:
    """Os 15 campi de tratamento desta rodada, em ordem alfabética de `site_id`."""
    sites = carregar_sites_validados()
    campi = []
    for site_id, props in sorted(sites.items()):
        if site_id == SITE_SEM_ANO_OBRA:
            continue
        if not props.get("ano_inicio_obra"):
            raise ValueError(
                f"site '{site_id}' sem ano_inicio_obra e fora da lista de exceção conhecida — "
                "conferir config/sites.geojson antes de seguir."
            )
        campi.append(
            {
                "site_id": site_id,
                "lat": float(props["lat"]),
                "lon": float(props["lon"]),
                "buffer_km": BUFFER_KM,
                "ano_inicio_obra": int(props["ano_inicio_obra"]),
                "municipio": props["municipio"],
                "uf": props["uf"],
                "bioma": props.get("bioma"),
                "tier": props.get("tier"),
            }
        )
    return campi


def janela_anos(ano_obra: int) -> list[int]:
    """`obra-3 .. obra+3`, grampeada ao que existe em ALGUM sensor (2013 a 2025).

    O grampeamento é reportado, não silencioso: quem chama compara `len(...)` com 7 para saber
    se aquele campus tem a janela completa. Hoje só `ascenty-maracanau` (obra 2014) perde anos —
    precisaria de 2011/2012, que estão na faixa_b desabilitada de `config/params.yml`.
    """
    bruto = range(ano_obra - ANOS_ANTES, ano_obra + ANOS_DEPOIS + 1)
    return [a for a in bruto if LANDSAT_ANO_MIN <= a <= S2_ANO_MAX]


def sensor_da_janela(anos: list[int]) -> str:
    """Sensor ÚNICO que cobre a janela inteira — `landsat` ou `s2`.

    Esta é a regra central desta rodada e a razão de a ingestão Landsat ter sido estendida até
    2024. SV-20 (`reports/validacao_sensores.md`) mediu que, em 48 de 48 pares, o degrau
    2018->2019 da classe "solo exposto/obras" é indistinguível do artefato de troca de
    instrumento. Comparar "antes" e "depois" em sensores diferentes é, portanto, medir o
    satélite, não a obra. Preferimos Landsat quando os dois servem, para o painel ficar no mesmo
    instrumento no maior número possível de campi.
    """
    if all(LANDSAT_ANO_MIN <= a <= LANDSAT_ANO_MAX for a in anos):
        return "landsat"
    if all(S2_ANO_MIN <= a <= S2_ANO_MAX for a in anos):
        return "s2"
    raise ValueError(
        f"janela {min(anos)}..{max(anos)} não cabe em nenhum sensor sozinho "
        f"(landsat {LANDSAT_ANO_MIN}-{LANDSAT_ANO_MAX}, s2 {S2_ANO_MIN}-{S2_ANO_MAX}) — "
        "cruzar a fronteira 2018/2019 é justamente o que esta rodada evita (SV-20)."
    )


def ano_referencia_pareamento(ano_obra: int) -> int:
    """O ano em que tratamento e candidatos são comparados: 1 ano ANTES do início da obra."""
    return ano_obra - 1


# --------------------------------------------------------------------------------------------
# Sorteio determinístico por site (mesma convenção de gerar_controles_pareados.py)
# --------------------------------------------------------------------------------------------


def rng_do_site(site_id: str) -> np.random.Generator:
    """Gerador independente por site: `default_rng([SEED, hash_estável(site_id)])`.

    Independente de propósito — a ordem de exploração de um site não pode depender de quais
    outros sites foram processados antes, senão reprocessar um subconjunto muda o resultado.
    Foi um bug real da primeira rodada de controles, descrito em `raw/controles/METODOLOGIA.md`.
    """
    h = int(hashlib.sha256(site_id.encode("utf-8")).hexdigest()[:8], 16)
    return np.random.default_rng([SEED, h])


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação — para comparar nome de município entre fontes."""
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# --------------------------------------------------------------------------------------------
# Pipeline por ponto: ingestão -> features -> classificação -> área por classe
# --------------------------------------------------------------------------------------------


PREFIXO_CONTROLE = "ctrl-"
DIR_CLASSIFICADO_CONTROLES = DIR_SAIDA / "classificado"
DIR_MANIFESTS_CONTROLES = DIR_SAIDA / "manifests"


def eh_controle(site_id: str) -> bool:
    return site_id.startswith(PREFIXO_CONTROLE)


def caminho_classificado(sensor_token: str, site_id: str, ano: int) -> Path:
    """Onde mora o raster classificado de um ponto.

    Sites de TRATAMENTO ficam em `data/processed/classificado/`, o diretório do classificador
    principal — são os sites oficiais de `config/sites.geojson`.

    Pontos de CONTROLE ficam sob `dados-modelo-impacto/raw/controles-rf/classificado/`. A
    separação não é cosmética: `sentinela.export_indicadores` varre
    `data/manifests/classificado_*.json` e levanta `ExportError` para qualquer `site_id` que não
    esteja em `config/sites.geojson` (ele precisa propagar tier/precisão de coordenada, e falhar
    alto é o comportamento certo lá). Deixar os ~150 pontos de controle desta frente naquele
    diretório quebraria o output da etapa de Indicadores do repositório principal — uma frente
    contaminando a outra.
    """
    if eh_controle(site_id):
        return DIR_CLASSIFICADO_CONTROLES / sensor_token / site_id / f"{ano}.tif"
    return SETTINGS.processed_dir / "classificado" / sensor_token / site_id / f"{ano}.tif"


def isolar_artefatos_de_controle(sensor_token: str, site_id: str, ano: int) -> int:
    """Move raster classificado e manifests de um ponto de CONTROLE para a pasta desta frente.

    Chamada logo depois de classificar, para que `data/processed/classificado/` e
    `data/manifests/` nunca acumulem pontos que não são de `config/sites.geojson`.
    Retorna quantos arquivos foram movidos.
    """
    if not eh_controle(site_id):
        return 0

    movidos = 0
    origem_tif = SETTINGS.processed_dir / "classificado" / sensor_token / site_id / f"{ano}.tif"
    destino_tif = caminho_classificado(sensor_token, site_id, ano)
    for sufixo in ("", "_confianca"):
        org = origem_tif.with_name(f"{ano}{sufixo}.tif")
        if org.exists():
            dst = destino_tif.with_name(f"{ano}{sufixo}.tif")
            dst.parent.mkdir(parents=True, exist_ok=True)
            org.replace(dst)
            movidos += 1
    if origem_tif.parent.exists() and not any(origem_tif.parent.iterdir()):
        origem_tif.parent.rmdir()

    DIR_MANIFESTS_CONTROLES.mkdir(parents=True, exist_ok=True)
    padroes = [
        f"classificado_{sensor_token}_{site_id}_{ano}.json",
        f"features_{sensor_token}_{site_id}_{ano}.json",
        f"{sensor_token}_{site_id}_{ano}.json",
    ]
    for nome in padroes:
        org = SETTINGS.manifests_dir / nome
        if org.exists():
            org.replace(DIR_MANIFESTS_CONTROLES / nome)
            movidos += 1
    return movidos


def iniciar_ee() -> None:
    """Autentica no Earth Engine uma vez por processo. Os módulos de `src/sentinela/` fazem isso
    dentro dos próprios `main()` de CLI; como aqui chamamos as funções direto, a inicialização
    fica por conta de quem orquestra."""
    init_ee()


def descartar_intermediarios(sensor_token: str, site_id: str, ano: int) -> int:
    """Apaga o composto bruto e o stack de features de um ponto, mantendo o raster classificado.

    Os pontos de CONTROLE desta frente são muitos (5 finalistas x 15 campi na seleção, mais 7 anos
    do controle escolhido) e cada ponto-ano ocupa ~3,4 MB em Landsat e ~55 MB em Sentinel-2 —
    contra 132 KB do raster classificado, que é a única coisa de que a área por classe precisa.
    Guardar os intermediários de todos estouraria o disco (o pipeline tem um piso de 5 GB livres,
    `predict.LIMIAR_DISCO_LIVRE_GB`, e aborta abaixo dele).

    Não é perda de reprodutibilidade: o manifest de cada etapa continua gravado, e rodar o script
    de novo com `--force` refaz o intermediário a partir do Earth Engine. É a mesma lógica de
    `raw/` ser gitignored nesta pasta — o que se guarda é o resultado, não o insumo.

    Nunca é chamada para site de tratamento: aqueles pertencem ao pipeline do classificador
    principal, que espera os intermediários no lugar.
    """
    import shutil

    liberado = 0
    alvos = [
        SETTINGS.raw_dir / sensor_token / site_id / f"{ano}.tif",
        SETTINGS.interim_dir / "features" / sensor_token / site_id / f"{ano}.tif",
    ]
    for alvo in alvos:
        if alvo.exists():
            liberado += alvo.stat().st_size
            alvo.unlink()
        # remove o diretório do ponto quando ficou vazio (todos os anos já descartados)
        if alvo.parent.exists() and not any(alvo.parent.iterdir()):
            shutil.rmtree(alvo.parent, ignore_errors=True)
    return liberado


def rodar_ponto(
    ponto: dict[str, Any],
    ano: int,
    sensor_token: str,
    pacote_modelo: dict[str, Any],
    *,
    force: bool = False,
    descartar_apos: bool = False,
) -> None:
    """Ingestão + índices + classificação de UM ponto/ano, idempotente.

    `ponto` precisa de `site_id`, `lat`, `lon`, `buffer_km` — o mesmo contrato mínimo que
    `config/sites.geojson` entrega aos módulos de `src/sentinela/`. Cada etapa já tem seu próprio
    "pula se já existe e o sha256 confere", então rodar de novo é barato.

    `descartar_apos=True` apaga os intermediários ao final (ver `descartar_intermediarios`) — use
    para pontos de controle, nunca para sites de tratamento.
    """
    # Se o raster classificado já existe, não há o que refazer: é o único artefato que a área por
    # classe consome, e os intermediários podem ter sido descartados de propósito.
    if not force and caminho_classificado(sensor_token, ponto["site_id"], ano).exists():
        return

    if sensor_token == "landsat":
        params = SETTINGS.params()
        mod_landsat.ingerir_site_ano(ponto, ano, params["mes_inicio"], params["mes_fim"], force=force)
    elif sensor_token == "s2":
        mod_s2.processar_site_ano(ponto, ano, force=force)
    else:
        raise ValueError(f"sensor desconhecido: {sensor_token!r}")

    mod_indices.processar_site_ano(sensor_token, ponto["site_id"], ano, force=force)
    mod_predict.classificar_site_ano(
        sensor_token, ponto["site_id"], ano, pacote_modelo, MODELO_PATH, force=force
    )

    # Ponto de controle sai imediatamente dos diretórios do classificador principal — ver
    # `caminho_classificado`. Feito aqui, e não no fim do lote, para que uma interrupção no meio
    # nunca deixe `data/manifests/` num estado que quebre `sentinela.export_indicadores`.
    isolar_artefatos_de_controle(sensor_token, ponto["site_id"], ano)

    if descartar_apos:
        liberado = descartar_intermediarios(sensor_token, ponto["site_id"], ano)
        if liberado:
            print(f"      (intermediários descartados: {liberado / 1024 / 1024:.0f} MB)")


def area_por_classe(sensor_token: str, site_id: str, ano: int) -> dict[str, Any]:
    """Área (ha) e proporção por classe no buffer, lidas do raster classificado.

    Mesma conta de `sentinela.export_indicadores.gerar_area_por_classe` (contagem de pixels x
    resolução²), reimplementada aqui só porque aquele módulo exige `site_id` presente em
    `config/sites.geojson` — ver docstring do módulo.
    """
    tif = caminho_classificado(sensor_token, site_id, ano)
    if not tif.exists():
        raise FileNotFoundError(f"raster classificado ausente: {tif}")
    with rasterio.open(tif) as src:
        arr = src.read(1)
    chave = "sentinel2" if sensor_token == "s2" else "landsat"
    resolucao_m = int(SETTINGS.params()["resolucao_m"][chave])

    valores, contagens = np.unique(arr, return_counts=True)
    contagem = dict(zip(valores.tolist(), contagens.tolist(), strict=True))
    pixels = {cid: int(contagem.get(cid, 0)) for cid in CLASS_IDS}
    total = sum(pixels.values())

    saida: dict[str, Any] = {
        "site_id": site_id,
        "ano": ano,
        "sensor": sensor_token,
        "resolucao_m": resolucao_m,
        "pixels_validos": total,
        "modelo_versao": MODELO_VERSAO,
    }
    for cid in CLASS_IDS:
        area_ha = pixels[cid] * resolucao_m * resolucao_m / 10_000.0
        saida[f"area_ha_{CLASSE_NOME[cid]}"] = round(area_ha, 4)
        saida[f"prop_{CLASSE_NOME[cid]}"] = round(pixels[cid] / total, 6) if total else 0.0
    return saida


def proporcoes(linha: dict[str, Any]) -> np.ndarray:
    """Vetor de 5 proporções, na ordem das classes 1-5."""
    return np.array([linha[f"prop_{CLASSE_NOME[cid]}"] for cid in CLASS_IDS], dtype=float)


def distancia_l1(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Distância L1 entre duas distribuições de classe — soma das diferenças absolutas de
    proporção. Mesmo critério e mesmos limiares da rodada anterior
    (`raw/controles/METODOLOGIA.md`), para os dois desenhos continuarem comparáveis.
    """
    return float(np.abs(proporcoes(a) - proporcoes(b)).sum())


def qualidade_l1(l1: float) -> str:
    """`bom` <= 0.10 · `aceitavel` <= 0.20 · `ruim` acima — limiares de SV-29, não afrouxados."""
    if l1 <= 0.10:
        return "bom"
    if l1 <= 0.20:
        return "aceitavel"
    return "ruim"


# --------------------------------------------------------------------------------------------
# Checkpoint (retomada sem refazer trabalho de rede)
# --------------------------------------------------------------------------------------------


class Checkpoint:
    """Estado incremental em JSON. Mesmo padrão de `gerar_controles_pareados.py`: qualquer etapa
    cara de rede grava progresso, para uma falha no meio não custar o lote inteiro.
    """

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.dados: dict[str, Any] = {}
        if caminho.exists():
            with caminho.open("r", encoding="utf-8") as f:
                self.dados = json.load(f)

    def get(self, chave: str) -> Any:
        return self.dados.get(chave)

    def set(self, chave: str, valor: Any) -> None:
        self.dados[chave] = valor
        self.salvar()

    def salvar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.dados, f, ensure_ascii=False, indent=2)
        tmp.replace(self.caminho)


def carregar_modelo() -> dict[str, Any]:
    return mod_predict.carregar_modelo(MODELO_PATH)


def salvar_csv(df: pd.DataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False, encoding="utf-8")
    print(f"  -> {caminho.relative_to(REPO_ROOT)} ({len(df)} linhas)")
