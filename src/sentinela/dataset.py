"""Dataset de modelagem v0.1 (SV-11) — une as duas eras de sensor, com split sem vazamento.

Rode com: python -m sentinela.dataset --versao v0.1

**O núcleo técnico desta tarefa é a chave de split.** `CLAUDE.md` é explícito: nunca split
aleatório por pixel. Com duas eras de sensor (Landsat 30 m 2013-2018/2019-2021, Sentinel-2 10 m
2019-2025) há três vetores de vazamento a fechar de uma vez só:

1. **Espacial** — pixels vizinhos em treino e teste.
2. **Temporal** — o mesmo lugar em anos consecutivos é quase idêntico.
3. **Entre sensores** — o mesmo lugar, no mesmo ano de sobreposição, aparece duas vezes (uma por
   sensor). Se uma cópia cai no treino e a outra no teste, é vazamento quase perfeito.

A solução: `bloco_id` é uma grade regular de 1 km x 1 km calculada a partir das coordenadas
projetadas (x, y) em EPSG:31983 — nunca de linha/coluna, que significam distâncias físicas
diferentes a 10 m e a 30 m. Como as duas eras compartilham a mesma origem de grade por site (SV-06/
SV-06b/SV-07 nunca recalculam a AOI, só reprojetam para ela), um mesmo ponto do terreno cai no
mesmo `bloco_id` nas duas resoluções. Blocos inteiros — de todos os anos e sensores — são sorteados
para treino ou teste (70/30, `random_state=42`, estratificado por site). É isso que fecha os três
vetores de vazamento simultaneamente (ver `atribuir_split`).

Amostragem estratificada por classe, com teto de 8.000 pixels por classe x site x ano x sensor —
teto por sensor, não proporcional à contagem de pixels, porque um pixel Landsat de 30 m cobre 9x a
área de um pixel S2 de 10 m; amostragem proporcional faria a era moderna dominar o dataset ~9:1.

Fonte de labels: MapBiomas Coleção 9 (anual, ADR-004 opção b) + WorldCover como verificação
cruzada só em 2021. `distancia_safra`/`peso_label` vêm dessa fonte (ver `_peso_label`).

Saída: `data/processed/dataset_{versao}.parquet` (gitignored) + `data/manifests/dataset_{versao}.json`
(commitado).

**SV-27 (v0.2)** estende este módulo para ~16 AOIs (não reescreve nada do parágrafo acima — bloco_id
e a regra 70/30 continuam idênticas): teto de amostragem parametrizável (`--teto`, recalibrado de
8.000 porque é linear no nº de AOIs), colunas de estrato `regiao`/`bioma`/`uf`/`tier`/`fase` (nunca
features do modelo, ver `_COLUNAS_NAO_FEATURE`), reserva de generalização fora-da-amostra
(`--holdout-tier`: AOIs inteiras de um tier saem do treino, ver `atribuir_split`), e tipos de dado
otimizados (`_otimizar_dtypes`) para caber em memória. Rode com:
`python -m sentinela.dataset --versao v0.2 --teto <N> --holdout-tier 2`.

**SV-16 (v1.0)** incorpora `data/labels_manual/*.geojson` (211 polígonos, SV-10) sobre a base de
v0.2. Dois mecanismos novos, ambos opt-in via flag (v0.1/v0.2 continuam byte-idênticos, flags
desligadas por padrão):

- `--usar-labels-manuais`: para cada combo (sensor, site, ano) com polígono manual correspondente
  (mesmo `site_id`/`ano`), rasteriza os polígonos **na grade daquele combo** (10 m ou 30 m,
  `rasterio.features.rasterize(all_touched=False)`) e aplica **precedência do manual sobre o
  label automático** (MapBiomas) pixel a pixel, antes de qualquer amostragem — ver
  `_rasterizar_labels_manuais`/`processar_combo`. A nova coluna `origem_label`
  (`"mapbiomas"`/`"manual"`) registra a fonte por linha; `peso_label` de amostras manuais é maior
  (`PESO_LABEL_MANUAL_PADRAO`), reduzido se `confianca == "baixa"`
  (`PESO_LABEL_MANUAL_BAIXA`) — ver constantes abaixo. Amostras manuais **nunca** são cortadas pelo
  teto de amostragem (só o pool automático da mesma classe/combo é que respeita `--teto`).
- `--referencia-split <parquet>`: reutiliza **byte a byte** o mapeamento `bloco_id -> split` de um
  dataset já gerado (tipicamente `dataset_v0.2.parquet`) em vez de recalcular `train_test_split` do
  zero. Isso é bloqueante para SV-16: qualquer bloco novo (que só existe porque um polígono manual
  caiu numa área nunca amostrada automaticamente) recebe um sorteio 70/30 **à parte**, que nunca
  perturba a ordem/composição da lista de blocos já sorteada em v0.2 — ver `atribuir_split`. Sem
  esta flag, `atribuir_split` se comporta exatamente como antes (sorteio do zero), preservando
  v0.1/v0.2 inalterados.

Rode com: `python -m sentinela.dataset --versao v1.0 --teto 4000 --holdout-tier 2
--usar-labels-manuais --referencia-split data/processed/dataset_v0.2.parquet` (mesmos `--teto`/
`--holdout-tier`/seed de v0.2 — mudar qualquer um deles junto com a rotulagem manual inviabilizaria
isolar de onde vem a diferença, ver `docs/tarefas/SV-16-dataset-v1.0-retreino.md`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import binary_erosion
from sklearn.model_selection import train_test_split

from . import classes
from .config import CONFIG_DIR, REPO_ROOT, SETTINGS

# --------------------------------------------------------------------------------------------
# Constantes / contrato
# --------------------------------------------------------------------------------------------

TETO_POR_CLASSE_SITE_ANO_SENSOR = 8000  # default histórico (v0.1, 3 sites) — v0.2 passa --teto explícito
TAMANHO_BLOCO_M = 1000.0  # grade 1 km x 1 km, ver docstring do módulo
TEST_SIZE = 0.30
PESO_LABEL_DISCORDANCIA_CROSSCHECK = 0.5  # fator aplicado no ano de verificação cruzada (2021)
                                            # quando MapBiomas e WorldCover discordam

SENSORES = ("s2", "landsat")

# Colunas de estrato (SV-27): chaves de análise/estratificação, NUNCA features do modelo — ver
# _COLUNAS_NAO_FEATURE mais abaixo e o manifest (campo `amostragem.estratos_nao_sao_features`).
COLUNAS_ESTRATO = ("regiao", "bioma", "uf", "tier", "fase")

# --------------------------------------------------------------------------------------------
# SV-16 (v1.0) — rotulagem manual: precedência sobre o label automático + peso diferenciado.
# --------------------------------------------------------------------------------------------

ORIGEM_LABEL_AUTOMATICA = "mapbiomas"  # fonte real do VALOR do pixel automático (ADR-004 opção b)
                                        # — WorldCover só entra como peso no crosscheck de 2021,
                                        # nunca substitui o valor gravado no raster de label.
ORIGEM_LABEL_MANUAL = "manual"

PESO_LABEL_MANUAL_PADRAO = 3.0  # confianca in {"alta", "media"} — mais caro de produzir (humano),
                                  # mais confiável na classe crítica que o WorldCover/MapBiomas
                                  # nunca capturam bem (canteiro de obras) — ver CLAUDE.md.
PESO_LABEL_MANUAL_BAIXA = 1.0  # confianca == "baixa": reduzido ao mesmo patamar do peso "cheio"
                                 # de uma amostra automática comum (1/(1+0)=1.0) — ainda conta,
                                 # mas não domina o gradiente como uma amostra manual confiável.

LABELS_MANUAIS_GLOB = "*.geojson"
LABELS_MANUAIS_EXCLUIR = {"_template.geojson"}
CONFIANCA_CODIGO = {"baixa": 1, "media": 2, "alta": 3}
CODIGO_CONFIANCA = {v: k for k, v in CONFIANCA_CODIGO.items()}


class DatasetError(RuntimeError):
    """Erro de construção do dataset com mensagem acionável."""


# --------------------------------------------------------------------------------------------
# Descoberta de combos (site, sensor, ano) disponíveis — nunca hardcoda anos/sites.
# --------------------------------------------------------------------------------------------


def _combos_disponiveis() -> list[tuple[str, str, int]]:
    """(sensor_token, site_id, ano) com stack de features (SV-08) E raster de label (SV-07)."""
    combos: list[tuple[str, str, int]] = []
    for sensor_token in SENSORES:
        base = SETTINGS.interim_dir / "features" / sensor_token
        if not base.exists():
            continue
        for site_dir in sorted(base.iterdir()):
            if not site_dir.is_dir():
                continue
            site_id = site_dir.name
            for tif in sorted(site_dir.glob("*.tif")):
                ano = int(tif.stem)
                label_tif = SETTINGS.raw_dir / "labels" / sensor_token / site_id / f"{ano}.tif"
                if label_tif.exists():
                    combos.append((sensor_token, site_id, ano))
                else:
                    print(
                        f"AVISO: features {sensor_token}/{site_id}/{ano} sem label correspondente "
                        f"({label_tif}) — combo ignorado.",
                        file=sys.stderr,
                    )
    return sorted(combos)


def _manifest_features_path(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.manifests_dir / f"features_{sensor_token}_{site_id}_{ano}.json"


def _manifest_labels_path(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.manifests_dir / f"labels_{sensor_token}_{site_id}_{ano}.json"


def _carregar_json(path: Path) -> dict:
    if not path.exists():
        raise DatasetError(f"manifest ausente: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _anos_sobreposicao() -> set[int]:
    params = SETTINGS.params()
    return set(params["faixa_a"]["anos_sobreposicao"])


# --------------------------------------------------------------------------------------------
# Metadados de AOI (SV-27, item 2) — regiao/bioma/uf/tier/periodos de fase, de config/sites.geojson.
# Nunca hardcoda essa lista: lê do geojson, fonte única de verdade das AOIs ativas.
# --------------------------------------------------------------------------------------------


def _carregar_sites_meta() -> dict[str, dict[str, Any]]:
    path = CONFIG_DIR / "sites.geojson"
    if not path.exists():
        raise DatasetError(f"{path} não existe — config das AOIs ausente.")
    data = json.loads(path.read_text(encoding="utf-8"))
    meta: dict[str, dict[str, Any]] = {}
    for feat in data["features"]:
        p = feat["properties"]
        site_id = p["site_id"]
        meta[site_id] = {
            "regiao": p.get("regiao"),
            "bioma": p.get("bioma"),
            "uf": p.get("uf"),
            "tier": int(p["tier"]) if p.get("tier") is not None else None,
            "periodo_pre": p.get("periodo_pre"),
            "periodo_durante": p.get("periodo_durante"),
            "periodo_pos": p.get("periodo_pos"),
        }
    return meta


def _parse_periodo(periodo: str | None) -> tuple[int, int] | None:
    """'YYYY-YYYY' -> (ano_ini, ano_fim); None (AOI sem período documentado) -> None."""
    if not periodo:
        return None
    ini, fim = periodo.split("-")
    return int(ini), int(fim)


def fase_do_ano(ano: int, periodo_pre: str | None, periodo_durante: str | None, periodo_pos: str | None) -> str:
    """Fase do empreendimento no `ano` dado, contra periodo_pre/durante/pos da AOI (item 2 do
    enunciado — é o que torna SV-30 possível). 'fora' cobre tanto anos fora de qualquer janela
    documentada quanto AOIs sem período algum documentado (ex.: odata-hortolandia)."""
    for fase, periodo in (("pre", periodo_pre), ("durante", periodo_durante), ("pos", periodo_pos)):
        intervalo = _parse_periodo(periodo)
        if intervalo is not None and intervalo[0] <= ano <= intervalo[1]:
            return fase
    return "fora"


# --------------------------------------------------------------------------------------------
# bloco_id — o coração da tarefa. SEMPRE a partir de x/y projetados, nunca linha/coluna.
# --------------------------------------------------------------------------------------------


def bloco_id_de_xy(site_id: str, x: float, y: float) -> str:
    """Grade regular de 1km x 1km sobre coordenadas projetadas (EPSG:31983).

    Usa a mesma origem absoluta do CRS para todos os sites/sensores/resoluções — é isso que faz
    um mesmo ponto do terreno cair no mesmo bloco nas duas eras (10 m e 30 m), fechando o
    vazamento de dados entre sensores (ver docstring do módulo)."""
    i = int(np.floor(x / TAMANHO_BLOCO_M))
    j = int(np.floor(y / TAMANHO_BLOCO_M))
    return f"{site_id}_{i}_{j}"


def _blocos_id_vetorizado(site_id: str, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    i = np.floor(x / TAMANHO_BLOCO_M).astype(np.int64)
    j = np.floor(y / TAMANHO_BLOCO_M).astype(np.int64)
    return np.array([f"{site_id}_{ii}_{jj}" for ii, jj in zip(i, j, strict=True)], dtype=object)


def _xy_pixel_centro(transform: rasterio.Affine, linhas: np.ndarray, colunas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Coordenada (x, y) do centro de cada pixel (linha, coluna), a partir do affine transform.

    Assume raster sem rotação (b == d == 0), verdade para todos os manifests deste projeto
    (SV-06/SV-06b/SV-07/SV-08 sempre gravam grade alinhada aos eixos)."""
    a, b, c, d, e, f = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
    if b != 0 or d != 0:
        raise DatasetError(
            f"transform com rotação (b={b}, d={d}) não suportado — bloco_id assume grade alinhada aos eixos."
        )
    x = c + a * (colunas.astype(np.float64) + 0.5)
    y = f + e * (linhas.astype(np.float64) + 0.5)
    return x, y


# --------------------------------------------------------------------------------------------
# Ponderação do label (item 5 do enunciado) — MapBiomas anual (ADR-004b) + crosscheck 2021.
# --------------------------------------------------------------------------------------------


def peso_label(distancia_safra: int, concordancia: np.ndarray | None) -> np.ndarray | float:
    """peso_label = 1 / (1 + distancia_safra) x (1.0 se concorda no crosscheck, senão 0.5).

    Fonte é anual (MapBiomas, ADR-004 opção b): `distancia_safra=0` na maioria dos anos (o
    problema de defasagem de safra fixa foi eliminado). As duas exceções documentadas:
    - 2024/2025 replicam a banda `classification_2023` (Coleção 9 não cobre esses anos) ->
      `distancia_safra` = 1 ou 2, peso reduzido proporcionalmente (1/(1+d)).
    - 2021 tem verificação cruzada com ESA WorldCover: pixels onde as duas fontes concordam
      mantêm peso cheio; pixels discordantes (inclusive praticamente toda a classe 3 crítica,
      concordância de 15-30% medida em ADR-004) entram com peso reduzido em vez de descartados.
    """
    base = 1.0 / (1.0 + distancia_safra)
    if concordancia is None:
        return base
    return np.where(concordancia == 1, base, base * PESO_LABEL_DISCORDANCIA_CROSSCHECK)


# --------------------------------------------------------------------------------------------
# Erosão de borda + amostragem estratificada por classe (item 2 do enunciado)
# --------------------------------------------------------------------------------------------


def _erodir_mascara_classe(mask: np.ndarray) -> np.ndarray:
    """Erosão de 1 pixel (scipy.ndimage.binary_erosion, estrutura default = cruz 4-conexa).

    1 pixel erodido = 10 m no S2, 30 m no Landsat — a mesma operação corta uma faixa 3x mais
    larga em metros na era antiga (documentado no manifest, seção `erosao`)."""
    return binary_erosion(mask)


def _ler_stack_features(path: Path) -> tuple[np.ndarray, rasterio.Affine, float]:
    with rasterio.open(path) as ds:
        arr = ds.read()
        transform = ds.transform
        nodata = ds.nodata if ds.nodata is not None else -9999.0
    return arr, transform, float(nodata)


def _ler_label(path: Path) -> tuple[np.ndarray, int]:
    with rasterio.open(path) as ds:
        arr = ds.read(1)
        nodata = ds.nodata if ds.nodata is not None else 0
    return arr, int(nodata)


def _ler_concordancia(path_relativo: str) -> np.ndarray:
    path = REPO_ROOT / path_relativo
    with rasterio.open(path) as ds:
        return ds.read(1)


# --------------------------------------------------------------------------------------------
# SV-16 (v1.0) — carregamento e rasterização dos polígonos manuais (SV-10)
# --------------------------------------------------------------------------------------------


def _arquivos_labels_manuais() -> list[Path]:
    d = SETTINGS.labels_manual_dir
    if not d.exists():
        raise DatasetError(f"{d} não existe — SV-10 (rotulagem manual) não rodou?")
    arquivos = sorted(
        p for p in d.glob(LABELS_MANUAIS_GLOB) if p.name not in LABELS_MANUAIS_EXCLUIR
    )
    if not arquivos:
        raise DatasetError(
            f"nenhum geojson de rotulagem manual em {d} (excluindo _template.geojson) — "
            "SV-10 não produziu labels, ou --usar-labels-manuais foi passado sem necessidade."
        )
    return arquivos


def labels_manuais_arquivos_meta() -> list[dict[str, Any]]:
    """Nome + sha256 de cada geojson de rotulagem manual usado — vai pro manifest (item 2 do
    enunciado de SV-16: 'arquivos de rotulagem usados + sha256')."""
    return [
        {"arquivo": f"data/labels_manual/{p.name}", "sha256": _sha256_arquivo(p)}
        for p in _arquivos_labels_manuais()
    ]


def _carregar_labels_manuais() -> gpd.GeoDataFrame:
    """Concatena todos os `data/labels_manual/{site_id}.geojson` (exceto o template), reprojeta
    de EPSG:4326 (CRS84, como os rotuladores desenharam no QGIS) para EPSG:31983 — o CRS comum
    que todo o pipeline usa para grade/transform/bloco_id (ver docstring do módulo)."""
    partes: list[gpd.GeoDataFrame] = []
    for path in _arquivos_labels_manuais():
        gdf = gpd.read_file(path)
        if gdf.empty:
            continue
        partes.append(gdf)
    if not partes:
        raise DatasetError("todos os geojson de rotulagem manual estão vazios (0 features).")
    gdf_total = pd.concat(partes, ignore_index=True)
    gdf_total = gpd.GeoDataFrame(gdf_total, geometry="geometry", crs=partes[0].crs)

    obrigatorias = {"site_id", "ano", "classe_id", "confianca"}
    faltando = obrigatorias - set(gdf_total.columns)
    if faltando:
        raise DatasetError(f"labels_manual: coluna(s) obrigatória(s) ausente(s) {faltando}")
    if gdf_total["classe_id"].isna().any() or gdf_total["ano"].isna().any():
        raise DatasetError("labels_manual: classe_id/ano com null — schema de SV-10 violado.")

    gdf_total["classe_id"] = gdf_total["classe_id"].astype(int)
    gdf_total["ano"] = gdf_total["ano"].astype(int)
    gdf_total["confianca"] = gdf_total["confianca"].fillna("media").astype(str)
    return gdf_total.to_crs("EPSG:31983")


def _agrupar_labels_manuais_por_site_ano(
    gdf: gpd.GeoDataFrame,
) -> dict[tuple[str, int], gpd.GeoDataFrame]:
    grupos: dict[tuple[str, int], gpd.GeoDataFrame] = {}
    for (site_id, ano), sub in gdf.groupby(["site_id", "ano"]):
        grupos[(str(site_id), int(ano))] = sub
    return grupos


def _rasterizar_labels_manuais(
    gdf_site_ano: gpd.GeoDataFrame, shape: tuple[int, int], transform: rasterio.Affine
) -> tuple[np.ndarray, np.ndarray]:
    """Rasteriza os polígonos manuais de um (site_id, ano) numa grade específica (10 m ou 30 m,
    conforme o combo que chama esta função). `all_touched=False` — mesma regra de rasterização
    usada no resto do pipeline (SV-06b/SV-07), para não inflar a área do polígono manual em
    relação ao label automático que ele está substituindo.

    Retorna (raster_classe, raster_confianca_baixa): raster_classe tem 0 onde não há polígono
    manual e o `classe_id` (1-5) onde há; raster_confianca_baixa é bool, True só nos pixels cujo
    polígono de origem tem `confianca == "baixa"` (usado para reduzir peso_label)."""
    from rasterio.features import rasterize

    shapes_classe = [
        (geom, int(cid))
        for geom, cid in zip(gdf_site_ano.geometry, gdf_site_ano["classe_id"], strict=True)
        if geom is not None and not geom.is_empty
    ]
    if not shapes_classe:
        vazio = np.zeros(shape, dtype=np.uint8)
        return vazio, vazio.astype(bool)

    raster_classe = rasterize(
        shapes_classe, out_shape=shape, transform=transform, fill=0, all_touched=False, dtype=np.uint8
    )

    shapes_baixa = [
        (geom, 1)
        for geom, conf in zip(gdf_site_ano.geometry, gdf_site_ano["confianca"], strict=True)
        if conf == "baixa" and geom is not None and not geom.is_empty
    ]
    if shapes_baixa:
        raster_baixa = rasterize(
            shapes_baixa, out_shape=shape, transform=transform, fill=0, all_touched=False, dtype=np.uint8
        ).astype(bool)
    else:
        raster_baixa = np.zeros(shape, dtype=bool)

    return raster_classe, raster_baixa


def processar_combo(
    sensor_token: str,
    site_id: str,
    ano: int,
    rng: np.random.Generator,
    erosao_acumulada: dict[str, dict[str, int]],
    anos_sobreposicao: set[int],
    teto: int = TETO_POR_CLASSE_SITE_ANO_SENSOR,
    sites_meta: dict[str, dict[str, Any]] | None = None,
    labels_manuais_por_site_ano: dict[tuple[str, int], gpd.GeoDataFrame] | None = None,
    manual_stats: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Lê features + label de um combo (sensor, site, ano), erode, amostra e monta as linhas.

    `labels_manuais_por_site_ano` (SV-16, opt-in): se houver polígonos manuais para este
    (site_id, ano), rasteriza-os NESTA grade (10 m ou 30 m — a mesma da era do combo) e aplica
    precedência sobre o label automático (MapBiomas) pixel a pixel, ANTES de erosão/amostragem —
    ver docstring do módulo. `manual_stats` acumula contagens para o manifest (mutado in-place,
    chave `sensor_token`)."""
    feat_manifest = _carregar_json(_manifest_features_path(sensor_token, site_id, ano))
    label_manifest = _carregar_json(_manifest_labels_path(sensor_token, site_id, ano))

    feat_path = SETTINGS.interim_dir / "features" / sensor_token / site_id / f"{ano}.tif"
    label_path = SETTINGS.raw_dir / "labels" / sensor_token / site_id / f"{ano}.tif"

    feat_arr, transform, nodata_feat = _ler_stack_features(feat_path)
    label_arr, nodata_label = _ler_label(label_path)

    if label_arr.shape != feat_arr.shape[1:]:
        raise DatasetError(
            f"{sensor_token}/{site_id}/{ano}: shape do label {label_arr.shape} != shape das "
            f"features {feat_arr.shape[1:]} — grades não batem (SV-07 deveria garantir isso)."
        )

    lista_features: list[str] = feat_manifest["bandas"]
    resolucao_m = feat_manifest["resolucao_m"]
    distancia_safra = int(label_manifest["distancia_safra"])
    crosscheck = label_manifest.get("crosscheck")

    concordancia_arr: np.ndarray | None = None
    if crosscheck is not None:
        concordancia_arr = _ler_concordancia(crosscheck["concordancia_tif"])
        if concordancia_arr.shape != label_arr.shape:
            raise DatasetError(
                f"{sensor_token}/{site_id}/{ano}: shape do raster de concordância "
                f"{concordancia_arr.shape} != shape do label {label_arr.shape}."
            )

    site_meta = (sites_meta or {}).get(site_id)
    if site_meta is None:
        raise DatasetError(
            f"site_id '{site_id}' tem features/labels processados mas não está em "
            f"config/sites.geojson (ou não foi passado sites_meta) — config desatualizado."
        )
    fase = fase_do_ano(ano, site_meta["periodo_pre"], site_meta["periodo_durante"], site_meta["periodo_pos"])

    # --- SV-16: precedência do label manual sobre o automático, ANTES de valido_base/erosão ---
    mask_manual = np.zeros(label_arr.shape, dtype=bool)
    raster_confianca_baixa = np.zeros(label_arr.shape, dtype=bool)
    if labels_manuais_por_site_ano:
        gdf_poly = labels_manuais_por_site_ano.get((site_id, ano))
        if gdf_poly is not None and len(gdf_poly):
            raster_classe_manual, raster_confianca_baixa = _rasterizar_labels_manuais(
                gdf_poly, label_arr.shape, transform
            )
            mask_manual = raster_classe_manual != 0
            if mask_manual.any():
                if manual_stats is not None:
                    stats_manual = manual_stats.setdefault(
                        sensor_token, {"rasterizado": 0, "sobrescrito_por_classe": {}}
                    )
                    stats_manual["rasterizado"] += int(mask_manual.sum())
                    label_automatico_valido = label_arr != nodata_label
                    sobrescrito_mask = mask_manual & label_automatico_valido & (label_arr != raster_classe_manual)
                    if sobrescrito_mask.any():
                        cids, contagens = np.unique(raster_classe_manual[sobrescrito_mask], return_counts=True)
                        for cid, cnt in zip(cids, contagens, strict=True):
                            slug = classes.ID_TO_SLUG[int(cid)]
                            stats_manual["sobrescrito_por_classe"][slug] = (
                                stats_manual["sobrescrito_por_classe"].get(slug, 0) + int(cnt)
                            )
                # precedência: manual substitui o automático onde houver polígono.
                label_arr = np.where(mask_manual, raster_classe_manual, label_arr)

    feat_valido = ~np.any(feat_arr == nodata_feat, axis=0)
    label_valido = label_arr != nodata_label
    valido_base = feat_valido & label_valido

    # SV-26 (controle de disco): SV-08 grava o stack em int16 x fator_escala em vez de float32
    # (nodata NÃO escalado — ver docstring de sentinela.features.indices). Descala aqui, DEPOIS de
    # calcular feat_valido a partir do sentinel inteiro bruto, para as colunas de feature do
    # dataset continuarem em reflectância/índice "de verdade" — o contrato de SV-11 não muda,
    # só a forma como o dado chega do disco.
    fator_escala_feat = feat_manifest.get("fator_escala")
    if fator_escala_feat and np.issubdtype(feat_arr.dtype, np.integer):
        feat_arr = feat_arr.astype(np.float32) / np.float32(fator_escala_feat)

    sobreposicao = ano in anos_sobreposicao

    partes: list[pd.DataFrame] = []
    stats = erosao_acumulada.setdefault(sensor_token, {"antes": 0, "depois": 0})

    for class_id in sorted(classes.CLASSES):
        if class_id == 0:
            continue
        mask_classe = (label_arr == class_id) & valido_base
        n_antes = int(mask_classe.sum())
        if n_antes == 0:
            continue
        mask_erodida = _erodir_mascara_classe(mask_classe)
        n_depois = int(mask_erodida.sum())
        stats["antes"] += n_antes
        stats["depois"] += n_depois

        linhas_disp, colunas_disp = np.nonzero(mask_erodida)
        n_disponivel = linhas_disp.size
        if n_disponivel == 0:
            continue

        # SV-16 item 2: amostras manuais NUNCA entram no teto — só o pool automático é cortado.
        manual_disp = mask_manual[linhas_disp, colunas_disp]
        idx_manual = np.nonzero(manual_disp)[0]
        idx_automatico_todos = np.nonzero(~manual_disp)[0]

        n_auto_disponivel = idx_automatico_todos.size
        n_amostra_auto = min(teto, n_auto_disponivel)
        if n_amostra_auto < n_auto_disponivel:
            escolhidos_auto = rng.choice(n_auto_disponivel, size=n_amostra_auto, replace=False)
            idx_automatico_sel = idx_automatico_todos[escolhidos_auto]
        else:
            idx_automatico_sel = idx_automatico_todos

        escolhidos = (
            np.concatenate([idx_manual, idx_automatico_sel]) if idx_manual.size else idx_automatico_sel
        )
        if escolhidos.size == 0:
            continue
        n_amostra = escolhidos.size

        if manual_stats is not None and idx_manual.size:
            stats_manual = manual_stats.setdefault(
                sensor_token, {"rasterizado": 0, "sobrescrito_por_classe": {}}
            )
            slug = classes.ID_TO_SLUG[class_id]
            usados = stats_manual.setdefault("usado_por_classe", {})
            usados[slug] = usados.get(slug, 0) + int(idx_manual.size)

        linhas_sel = linhas_disp[escolhidos]
        colunas_sel = colunas_disp[escolhidos]

        x, y = _xy_pixel_centro(transform, linhas_sel, colunas_sel)
        bloco_ids = _blocos_id_vetorizado(site_id, x, y)

        feats_sel = feat_arr[:, linhas_sel, colunas_sel].T  # (n_amostra, n_features)
        conc_sel = concordancia_arr[linhas_sel, colunas_sel] if concordancia_arr is not None else None
        peso_automatico = np.broadcast_to(peso_label(distancia_safra, conc_sel), (n_amostra,)).astype(np.float64)

        origem_sel = np.where(
            mask_manual[linhas_sel, colunas_sel], ORIGEM_LABEL_MANUAL, ORIGEM_LABEL_AUTOMATICA
        )
        is_manual_sel = origem_sel == ORIGEM_LABEL_MANUAL
        confianca_baixa_sel = raster_confianca_baixa[linhas_sel, colunas_sel]
        peso_manual = np.where(confianca_baixa_sel, PESO_LABEL_MANUAL_BAIXA, PESO_LABEL_MANUAL_PADRAO)
        peso = np.where(is_manual_sel, peso_manual, peso_automatico)
        confianca_manual_sel = np.where(
            is_manual_sel, np.where(confianca_baixa_sel, "baixa", "alta_media"), ""
        )

        df_parte = pd.DataFrame(feats_sel, columns=lista_features)
        df_parte["classe_id"] = np.uint8(class_id)
        df_parte["site_id"] = site_id
        df_parte["ano"] = ano
        df_parte["sensor"] = sensor_token
        df_parte["resolucao_m"] = resolucao_m
        df_parte["bloco_id"] = bloco_ids
        df_parte["linha"] = linhas_sel
        df_parte["coluna"] = colunas_sel
        df_parte["x"] = x
        df_parte["y"] = y
        df_parte["sobreposicao"] = sobreposicao
        df_parte["distancia_safra"] = distancia_safra
        df_parte["peso_label"] = peso
        # SV-16: fonte do label por linha + confiança (só preenchida p/ origem_label=="manual").
        df_parte["origem_label"] = origem_sel
        df_parte["confianca_manual"] = confianca_manual_sel
        # Estrato (SV-27, item 2) — chave de análise, nunca feature (ver _COLUNAS_NAO_FEATURE).
        df_parte["regiao"] = site_meta["regiao"]
        df_parte["bioma"] = site_meta["bioma"]
        df_parte["uf"] = site_meta["uf"]
        df_parte["tier"] = site_meta["tier"]
        df_parte["fase"] = fase
        partes.append(df_parte)

    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


# --------------------------------------------------------------------------------------------
# Split por bloco — 70/30, estratificado por site, todos os anos/sensores de um bloco juntos.
# --------------------------------------------------------------------------------------------


def _cobertura_por_estrato(df: pd.DataFrame, coluna: str) -> dict[str, dict[str, Any]]:
    """Para cada valor do estrato (regiao/bioma), registra se aparece em treino E em teste —
    material do cenário 5 (SV-27) e do critério de aceite 'toda região/bioma presente aparece em
    treino e em teste, ou a exceção está listada no manifest'."""
    if coluna not in df.columns:
        return {}
    resultado: dict[str, dict[str, Any]] = {}
    for valor in sorted(df[coluna].dropna().unique(), key=str):
        subset = df[df[coluna] == valor]
        splits_presentes = set(subset["split"].unique())
        resultado[str(valor)] = {
            "treino": "treino" in splits_presentes,
            "teste": "teste" in splits_presentes,
            "n_aois": int(subset["site_id"].nunique()),
            "aois": sorted(subset["site_id"].unique().tolist()),
            "aois_holdout_espacial": sorted(
                subset.loc[subset["holdout_espacial"], "site_id"].unique().tolist()
            ),
        }
    return resultado


def atribuir_split(
    df: pd.DataFrame,
    seed: int,
    holdout_site_ids: frozenset[str] = frozenset(),
    mapa_referencia: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, int], dict[str, dict[str, dict[str, Any]]], dict[str, list[str]]]:
    """Sorteia bloco_id inteiros para treino/teste (nunca pixels) — fecha os 3 vetores de
    vazamento descritos na docstring do módulo. Estratificado por site: cada site tem seu
    próprio sorteio 70/30 sobre a lista (ordenada, determinística) de blocos únicos daquele site.

    SV-27 acrescenta `holdout_site_ids`: AOIs inteiras (tipicamente tier 2) reservadas fora do
    treino por completo — não participam do sorteio 70/30, todos os seus blocos vão para 'teste'
    com `holdout_espacial=True`. É ortogonal ao split normal (não muda a regra de bloco_id nem o
    sorteio das demais AOIs) — ver docstring do módulo SV-27 e item 4 do enunciado.

    SV-16 acrescenta `mapa_referencia` (opcional): um `dict[bloco_id, split]` de uma rodada
    anterior (tipicamente `dataset_v0.2`) a REUTILIZAR byte a byte em vez de resortear. Isto é
    bloqueante para SV-16 — rotulagem manual pode introduzir pixels em blocos que a amostragem
    automática nunca tocou, e resortear `train_test_split` sobre a lista de blocos MUDADA
    mudaria a permutação (e portanto o split) de blocos que já existiam em v0.2, invalidando a
    comparação v0.2-vs-v1.0. A solução: blocos já presentes em `mapa_referencia` mantêm o split
    de lá, sem exceção; só blocos genuinamente NOVOS (ausentes da referência) passam por um
    sorteio 70/30 à parte, que nunca é lido nem influencia o sorteio dos blocos antigos. Quando
    `mapa_referencia=None` (default, comportamento de v0.1/v0.2), TODO bloco é "novo" e o
    resultado é idêntico ao algoritmo original (mesma chamada de `train_test_split`)."""
    bloco_para_split: dict[str, str] = dict(mapa_referencia) if mapa_referencia else {}
    novos_blocos_por_site: dict[str, list[str]] = {}

    for site_id in sorted(df["site_id"].unique()):
        blocos_site = sorted(df.loc[df["site_id"] == site_id, "bloco_id"].unique())
        blocos_novos = [b for b in blocos_site if b not in bloco_para_split]
        if not blocos_novos:
            continue
        if site_id in holdout_site_ids:
            # Reserva de generalização fora-da-amostra (SV-27 item 4): AOI inteira fora do treino.
            blocos_treino, blocos_teste = [], blocos_novos
        elif len(blocos_novos) < 2:
            # site com um único bloco novo: não dá pra split — vai pra treino, registrado no manifest.
            blocos_treino, blocos_teste = blocos_novos, []
        else:
            blocos_treino, blocos_teste = train_test_split(
                blocos_novos, test_size=TEST_SIZE, random_state=seed
            )
        for b in blocos_treino:
            bloco_para_split[b] = "treino"
        for b in blocos_teste:
            bloco_para_split[b] = "teste"
        novos_blocos_por_site[site_id] = blocos_novos

    df = df.copy()
    df["split"] = df["bloco_id"].map(bloco_para_split)
    df["holdout_espacial"] = df["site_id"].isin(holdout_site_ids)

    ano_mais_recente = int(df["ano"].max())
    df["holdout_temporal"] = df["ano"] == ano_mais_recente

    blocos_presentes = df["bloco_id"].unique()
    n_treino = int(sum(1 for b in blocos_presentes if bloco_para_split[b] == "treino"))
    n_teste = int(len(blocos_presentes) - n_treino)

    cobertura = {
        "regiao": _cobertura_por_estrato(df, "regiao"),
        "bioma": _cobertura_por_estrato(df, "bioma"),
    }

    return df, {"treino": n_treino, "teste": n_teste}, cobertura, novos_blocos_por_site


# --------------------------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------------------------


def _carregar_mapa_split_referencia(parquet_path: Path) -> dict[str, str]:
    """Lê `bloco_id -> split` de um dataset já gerado (ver `atribuir_split`, param
    `mapa_referencia`) — SV-16 reutiliza isto de `dataset_v0.2.parquet` para garantir o mesmo
    split byte a byte nos blocos que já existiam antes da rotulagem manual."""
    if not parquet_path.exists():
        raise DatasetError(f"--referencia-split: {parquet_path} não existe.")
    df_ref = pd.read_parquet(parquet_path, columns=["bloco_id", "split"])
    mapa = dict(zip(df_ref["bloco_id"].astype(str), df_ref["split"].astype(str), strict=True))
    # sanidade: um bloco não pode ter dois splits diferentes na referência (violaria o próprio
    # invariante que estamos tentando preservar).
    conf = df_ref.drop_duplicates()
    if conf["bloco_id"].duplicated().any():
        raise DatasetError(
            f"--referencia-split: {parquet_path} tem bloco_id com split ambíguo (mais de um "
            "valor) — a referência já estava corrompida, não dá pra reutilizar."
        )
    return mapa


def montar_dataset(
    seed: int,
    teto: int = TETO_POR_CLASSE_SITE_ANO_SENSOR,
    holdout_tier: int | None = None,
    usar_labels_manuais: bool = False,
    referencia_split_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Monta o dataset de modelagem.

    `teto`: pixels por classe x AOI x ano x sensor (v0.1 usava 8.000 fixo; SV-27/v0.2 recalibra
    e passa o valor explicitamente — ver módulo `TETO_POR_CLASSE_SITE_ANO_SENSOR` para o default
    histórico).
    `holdout_tier`: se dado, toda AOI com esse `tier` em config/sites.geojson fica inteiramente
    fora do treino (reserva de generalização fora-da-amostra, SV-27 item 4). None (default,
    comportamento de v0.1) = nenhuma AOI reservada.
    `usar_labels_manuais` (SV-16): incorpora `data/labels_manual/*.geojson` com precedência sobre
    o label automático — ver docstring do módulo e `processar_combo`.
    `referencia_split_path` (SV-16): path de um `dataset_{versao}.parquet` cujo mapeamento
    bloco_id->split deve ser reutilizado byte a byte (ver `atribuir_split`). None (default) =
    sorteia do zero, comportamento de v0.1/v0.2.
    """
    combos = _combos_disponiveis()
    if not combos:
        raise DatasetError(
            "nenhum combo (sensor, site, ano) com features (SV-08) e label (SV-07) encontrado — "
            "rode os módulos anteriores antes de sentinela.dataset."
        )

    sites_meta = _carregar_sites_meta()
    holdout_site_ids = frozenset(
        site_id
        for site_id, meta in sites_meta.items()
        if holdout_tier is not None and meta["tier"] == holdout_tier
    )

    lista_features_referencia: list[str] | None = None
    rasters_origem: list[dict[str, Any]] = []
    for sensor_token, site_id, ano in combos:
        feat_manifest_path = _manifest_features_path(sensor_token, site_id, ano)
        label_manifest_path = _manifest_labels_path(sensor_token, site_id, ano)
        feat_manifest = _carregar_json(feat_manifest_path)
        label_manifest = _carregar_json(label_manifest_path)

        if lista_features_referencia is None:
            lista_features_referencia = feat_manifest["bandas"]
        elif feat_manifest["bandas"] != lista_features_referencia:
            raise DatasetError(
                f"{feat_manifest_path}: lista de bandas {feat_manifest['bandas']} difere da "
                f"referência {lista_features_referencia} — contrato de SV-08 quebrado."
            )

        rasters_origem.append(
            {
                "sensor": sensor_token,
                "site_id": site_id,
                "ano": ano,
                "sha256_manifest_features": hashlib.sha256(feat_manifest_path.read_bytes()).hexdigest(),
                "sha256_manifest_labels": hashlib.sha256(label_manifest_path.read_bytes()).hexdigest(),
                "sha256_tif_features": feat_manifest["sha256"],
                "sha256_tif_labels": label_manifest["sha256"],
            }
        )

    labels_manuais_por_site_ano: dict[tuple[str, int], gpd.GeoDataFrame] | None = None
    labels_manuais_meta: list[dict[str, Any]] = []
    if usar_labels_manuais:
        gdf_manual = _carregar_labels_manuais()
        labels_manuais_por_site_ano = _agrupar_labels_manuais_por_site_ano(gdf_manual)
        labels_manuais_meta = labels_manuais_arquivos_meta()

    rng = np.random.default_rng(seed)
    anos_sobreposicao = _anos_sobreposicao()
    erosao_acumulada: dict[str, dict[str, int]] = {}
    manual_stats: dict[str, dict[str, Any]] = {}

    partes: list[pd.DataFrame] = []
    for sensor_token, site_id, ano in combos:
        parte = processar_combo(
            sensor_token, site_id, ano, rng, erosao_acumulada, anos_sobreposicao,
            teto=teto, sites_meta=sites_meta,
            labels_manuais_por_site_ano=labels_manuais_por_site_ano,
            manual_stats=manual_stats,
        )
        if not parte.empty:
            partes.append(parte)

    if not partes:
        raise DatasetError("nenhuma linha amostrada em nenhum combo — verifique os rasters de entrada.")

    df = pd.concat(partes, ignore_index=True)

    mapa_referencia: dict[str, str] | None = None
    if referencia_split_path is not None:
        mapa_referencia = _carregar_mapa_split_referencia(referencia_split_path)

    df, n_blocos, cobertura, novos_blocos_por_site = atribuir_split(
        df, seed, holdout_site_ids=holdout_site_ids, mapa_referencia=mapa_referencia
    )
    df = _otimizar_dtypes(df, lista_features_referencia or [])

    assert lista_features_referencia is not None
    stats: dict[str, Any] = {
        "lista_features": lista_features_referencia,
        "rasters_origem": rasters_origem,
        "erosao": erosao_acumulada,
        "n_blocos": n_blocos,
        "combos": combos,
        "teto": teto,
        "sites_meta": sites_meta,
        "holdout_site_ids": sorted(holdout_site_ids),
        "holdout_tier": holdout_tier,
        "cobertura_estrato": cobertura,
        "usar_labels_manuais": usar_labels_manuais,
        "labels_manuais_arquivos": labels_manuais_meta,
        "manual_stats": manual_stats,
        "referencia_split_path": (
            str(referencia_split_path.relative_to(REPO_ROOT))
            if referencia_split_path is not None and referencia_split_path.is_relative_to(REPO_ROOT)
            else (str(referencia_split_path) if referencia_split_path is not None else None)
        ),
        "novos_blocos_por_site": (
            {k: sorted(v) for k, v in novos_blocos_por_site.items()}
            if referencia_split_path is not None else None
        ),
    }
    return df, stats


# --------------------------------------------------------------------------------------------
# Testes de controle (item 8 e 9 do enunciado) — o material mais importante pro relatório final.
# --------------------------------------------------------------------------------------------


def _treinar_rf_rapido(X_treino, y_treino, seed: int, n_estimators: int = 100):
    from sklearn.ensemble import RandomForestClassifier

    modelo = RandomForestClassifier(
        n_estimators=n_estimators, max_depth=20, random_state=seed, n_jobs=-1, class_weight="balanced"
    )
    modelo.fit(X_treino, y_treino)
    return modelo


def _metricas(y_true, y_pred) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, f1_score

    return {
        "acuracia": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
    }


def teste_controle_split_aleatorio_vs_bloco(df: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Item 8: RF rápido com split aleatório por pixel vs. o split por bloco desta tarefa.

    Se o split aleatório reportar acurácia/F1 bem maiores, confirma que o vazamento espacial é
    real (o modelo está "decorando" o vizinho) e que o split por bloco resolve o problema."""
    features = _colunas_feature(df)
    X = df[features].to_numpy()
    y = df["classe_id"].to_numpy()

    # split por bloco (o desta tarefa)
    X_treino_b, y_treino_b = X[df["split"] == "treino"], y[df["split"] == "treino"]
    X_teste_b, y_teste_b = X[df["split"] == "teste"], y[df["split"] == "teste"]
    modelo_bloco = _treinar_rf_rapido(X_treino_b, y_treino_b, seed)
    metricas_bloco = _metricas(y_teste_b, modelo_bloco.predict(X_teste_b))

    # split aleatório por pixel, mesma proporção de teste, ignorando bloco_id
    X_treino_r, X_teste_r, y_treino_r, y_teste_r = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=seed, stratify=y
    )
    modelo_random = _treinar_rf_rapido(X_treino_r, y_treino_r, seed)
    metricas_random = _metricas(y_teste_r, modelo_random.predict(X_teste_r))

    return {"split_bloco": metricas_bloco, "split_aleatorio_pixel": metricas_random}


def teste_controle_generalizacao_entre_eras(df: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Item 9: treina só numa era (sensor) e testa só na outra, e vice-versa.

    Mede se a harmonização espectral (SV-02b) resolveu o problema de sensor na prática, não só
    nas bandas isoladas. Usa só linhas do split de treino/teste desta tarefa (sem vazamento
    espacial), mas particiona adicionalmente por sensor."""
    features = _colunas_feature(df)

    resultado: dict[str, Any] = {}
    for treino_sensor, teste_sensor in (("landsat", "s2"), ("s2", "landsat")):
        df_treino = df[(df["sensor"] == treino_sensor) & (df["split"] == "treino")]
        df_teste = df[(df["sensor"] == teste_sensor) & (df["split"] == "teste")]
        if df_treino.empty or df_teste.empty:
            continue
        X_treino, y_treino = df_treino[features].to_numpy(), df_treino["classe_id"].to_numpy()
        X_teste, y_teste = df_teste[features].to_numpy(), df_teste["classe_id"].to_numpy()
        modelo = _treinar_rf_rapido(X_treino, y_treino, seed)
        resultado[f"treino_{treino_sensor}_teste_{teste_sensor}"] = _metricas(y_teste, modelo.predict(X_teste))

    return resultado


_COLUNAS_NAO_FEATURE = {
    "classe_id", "site_id", "ano", "sensor", "resolucao_m", "bloco_id", "linha", "coluna",
    "x", "y", "split", "holdout_temporal", "sobreposicao", "distancia_safra", "peso_label",
    # Estratos de análise (SV-27, item 2) — NUNCA features do modelo, ver docstring do módulo.
    "regiao", "bioma", "uf", "tier", "fase", "holdout_espacial",
    # SV-16: fonte do label — chave de análise (evaluate.py mede desempenho por origem), nunca feature.
    "origem_label", "confianca_manual",
}


def _colunas_feature(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in _COLUNAS_NAO_FEATURE]


# --------------------------------------------------------------------------------------------
# Otimização de tipos (SV-27, item 5) — o que evita os 6-10 GB de RAM projetados para 25 AOIs.
# --------------------------------------------------------------------------------------------

_COLUNAS_CATEGORY = (
    "site_id", "bloco_id", "sensor", "regiao", "bioma", "uf", "fase", "split",
    "origem_label", "confianca_manual",
)
_COLUNAS_INT_ESTREITO: dict[str, type] = {
    "ano": np.int16,
    "linha": np.int32,
    "coluna": np.int32,
    "tier": np.int8,
    "distancia_safra": np.int8,
    "resolucao_m": np.int16,
    "classe_id": np.uint8,
}
_COLUNAS_BOOL = ("sobreposicao", "holdout_temporal", "holdout_espacial")


def _otimizar_dtypes(df: pd.DataFrame, lista_features: list[str]) -> pd.DataFrame:
    """`site_id`/`bloco_id`/`sensor`/`regiao`/`bioma`/`uf`/`fase` -> category; features -> float32;
    `ano`/`linha`/`coluna` (e demais inteiros pequenos) -> inteiros estreitos. `x`/`y` ficam em
    float64 (usados para recalcular bloco_id — não arriscar precisão perto de fronteira de bloco).
    """
    df = df.copy()
    for col in lista_features:
        if col in df.columns:
            df[col] = df[col].astype(np.float32)
    for col in _COLUNAS_CATEGORY:
        if col in df.columns:
            df[col] = df[col].astype("category")
    for col, dtype in _COLUNAS_INT_ESTREITO.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)
    for col in _COLUNAS_BOOL:
        if col in df.columns:
            df[col] = df[col].astype(bool)
    return df


# --------------------------------------------------------------------------------------------
# Escrita: parquet + manifest
# --------------------------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - git ausente, repo raso: manifest não pode falhar por isso
        return "desconhecido"


def _sha256_arquivo(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _distribuicao_classes(df: pd.DataFrame) -> dict[str, int]:
    contagem = df["classe_id"].value_counts().sort_index()
    return {classes.ID_TO_SLUG[int(cid)]: int(n) for cid, n in contagem.items()}


def construir_manifest(df: pd.DataFrame, stats: dict[str, Any], *, versao: str, seed: int, parquet_path: Path) -> dict[str, Any]:
    distribuicao_total = _distribuicao_classes(df)
    distribuicao_por_split = {
        split: _distribuicao_classes(df[df["split"] == split]) for split in ("treino", "teste")
    }
    distribuicao_por_sensor = {
        sensor: _distribuicao_classes(df[df["sensor"] == sensor]) for sensor in SENSORES
    }
    distribuicao_por_sensor_e_split = {
        f"{sensor}_{split}": _distribuicao_classes(df[(df["sensor"] == sensor) & (df["split"] == split)])
        for sensor in SENSORES
        for split in ("treino", "teste")
    }
    distribuicao_por_regiao = (
        {str(v): _distribuicao_classes(df[df["regiao"] == v]) for v in sorted(df["regiao"].dropna().unique(), key=str)}
        if "regiao" in df.columns else {}
    )
    distribuicao_por_bioma = (
        {str(v): _distribuicao_classes(df[df["bioma"] == v]) for v in sorted(df["bioma"].dropna().unique(), key=str)}
        if "bioma" in df.columns else {}
    )

    erosao_manifest = {
        sensor: {
            "pixels_antes_erosao": s["antes"],
            "pixels_depois_erosao": s["depois"],
            "pixels_descartados": s["antes"] - s["depois"],
            "pct_descartado": round(100.0 * (s["antes"] - s["depois"]) / s["antes"], 4) if s["antes"] else 0.0,
        }
        for sensor, s in stats["erosao"].items()
    }

    manifest = {
        "versao": versao,
        "n_linhas": len(df),
        "n_features": len(stats["lista_features"]),
        "lista_features": stats["lista_features"],
        "distribuicao_classes": {
            "total": distribuicao_total,
            "por_split": distribuicao_por_split,
            "por_sensor": distribuicao_por_sensor,
            "por_sensor_e_split": distribuicao_por_sensor_e_split,
            "por_regiao": distribuicao_por_regiao,
            "por_bioma": distribuicao_por_bioma,
        },
        "n_blocos": stats["n_blocos"],
        "sites": sorted(df["site_id"].unique().tolist()),
        "anos": sorted(int(a) for a in df["ano"].unique().tolist()),
        "sensores": sorted(df["sensor"].unique().tolist()),
        "fonte_label": "mapbiomas_coleção9_anual (ADR-004 opção b) + worldcover_crosscheck_2021",
        "seed": seed,
        "regra_split": (
            "bloco_id = grade regular de 1km x 1km sobre coordenadas projetadas (x, y) em "
            "EPSG:31983 (nunca linha/coluna — índices de pixel significam distâncias diferentes "
            "a 10m e a 30m). Blocos inteiros (não pixels) são sorteados 70%/30% para "
            "treino/teste, com random_state=42, estratificado por AOI (site_id): cada AOI tem "
            "seu próprio sorteio 70/30 sobre a lista de blocos únicos dela, e todos os anos e "
            "sensores de um mesmo bloco vão para o mesmo split. Isso fecha os 3 vetores de "
            "vazamento de dados do projeto ao mesmo tempo: espacial (pixels vizinhos), "
            "temporal (mesmo lugar em anos consecutivos) e entre sensores (mesmo lugar, mesmo "
            "ano, duas cópias em resoluções diferentes nos anos de sobreposição 2019-2021). "
            "Regra idêntica à v0.1 (SV-11) — não foi alterada para SV-27, só aplicada a mais "
            "AOIs; a estratificação por AOI garante que nenhuma região/bioma vá inteiramente "
            "para um único split (ver `cobertura_estrato`, `regioes_sem_ambos_splits`, "
            "`biomas_sem_ambos_splits`). SV-27 acrescenta `holdout_espacial`, ORTOGONAL a "
            "`split`: AOIs inteiras de `holdout_tier` não participam do sorteio 70/30 — todos os "
            "seus blocos vão para 'teste' com holdout_espacial=True, para medir generalização a "
            "uma AOI nunca vista em treino (ver `aois_holdout_espacial`). holdout_temporal marca "
            "o ano mais recente do dataset (2025) como flag informativo adicional para validação "
            "temporal em SV-12 — não substitui nem sobrepõe o split por bloco, que continua "
            "sendo a única fonte de verdade da coluna `split`."
        ),
        "regra_peso_label": (
            "peso_label = 1/(1+distancia_safra) x (1.0 se concorda com WorldCover no ano de "
            "verificação cruzada 2021, senão 0.5). Fonte é anual (MapBiomas, ADR-004 opção b): "
            "distancia_safra=0 e peso_label=1.0 na grande maioria dos casos (2013-2023, exceto "
            "2021 discordante). As duas exceções documentadas: (a) 2024/2025 replicam a banda "
            "classification_2023 (Coleção 9 não cobre esses anos) -> distancia_safra=1 ou 2, "
            "peso reduzido; (b) 2021 tem verificação cruzada com WorldCover -> pixels "
            "discordantes (~29-33% dos válidos, ver ADR-004) entram com peso 0.5 em vez de "
            "serem descartados."
        ),
        "erosao": erosao_manifest,
        "amostragem": {
            "teto_por_classe_site_ano_sensor": stats.get("teto", TETO_POR_CLASSE_SITE_ANO_SENSOR),
            "erosao_borda_px": 1,
            "observacao": (
                "teto por sensor (não proporcional à contagem de pixels) — um pixel Landsat de "
                "30m cobre 9x a área de um pixel S2 de 10m; teto proporcional faria a era "
                "moderna dominar o dataset ~9:1."
            ),
            "justificativa_teto": (
                f"v0.1 usava teto=8000 fixo (3 sites), linear no nº de AOIs. Aplicado às AOIs "
                f"desta rodada ({len(stats.get('sites_meta', {}))} ativas), 8000 projetava um "
                f"dataset na casa de dezenas de milhões de linhas e um fit de RF de dezenas de "
                f"minutos — inviável para o ciclo treinar/medir/ajustar do calendário do projeto "
                f"(ver docs/tarefas/SV-27-dataset-v0.2-expandido.md). Recalibrado para "
                f"teto={stats.get('teto', TETO_POR_CLASSE_SITE_ANO_SENSOR)}: mais pixels do mesmo "
                f"lugar não são mais informação (pixels vizinhos são quase idênticos, por isso o "
                f"split é por bloco) — o ganho da expansão é diversidade de AOI/bioma/contexto, "
                f"não volume por AOI."
            ),
        },
        "estratos_nao_sao_features": sorted(COLUNAS_ESTRATO),
        "aois": [
            {
                "site_id": site_id,
                "tier": meta["tier"],
                "regiao": meta["regiao"],
                "bioma": meta["bioma"],
                "uf": meta["uf"],
                "holdout_espacial": site_id in set(stats.get("holdout_site_ids", [])),
            }
            for site_id, meta in sorted(stats.get("sites_meta", {}).items())
            if site_id in set(df["site_id"].unique().tolist())
        ],
        "aois_holdout_espacial": stats.get("holdout_site_ids", []),
        "holdout_tier": stats.get("holdout_tier"),
        "cobertura_estrato": stats.get("cobertura_estrato", {}),
        "regioes_sem_ambos_splits": sorted(
            v for v, cov in stats.get("cobertura_estrato", {}).get("regiao", {}).items()
            if not (cov["treino"] and cov["teste"])
        ),
        "biomas_sem_ambos_splits": sorted(
            v for v, cov in stats.get("cobertura_estrato", {}).get("bioma", {}).items()
            if not (cov["treino"] and cov["teste"])
        ),
        "memoria_mb": round(float(df.memory_usage(deep=True).sum()) / 1e6, 3),
        "rasters_origem": stats["rasters_origem"],
        "sha256": _sha256_arquivo(parquet_path),
        "git_sha": _git_sha(),
        "gerado_em": datetime.now(UTC).isoformat(),
    }

    if stats.get("usar_labels_manuais"):
        manual_stats = stats.get("manual_stats", {})
        n_pixels_manuais_por_sensor = {
            sensor: s.get("rasterizado", 0) for sensor, s in manual_stats.items()
        }
        n_pixels_sobrescritos_por_classe: dict[str, int] = {}
        for s in manual_stats.values():
            for slug, n in s.get("sobrescrito_por_classe", {}).items():
                n_pixels_sobrescritos_por_classe[slug] = n_pixels_sobrescritos_por_classe.get(slug, 0) + n
        n_pixels_usados_por_classe: dict[str, int] = {}
        for s in manual_stats.values():
            for slug, n in s.get("usado_por_classe", {}).items():
                n_pixels_usados_por_classe[slug] = n_pixels_usados_por_classe.get(slug, 0) + n

        distribuicao_por_origem_label = (
            {
                str(v): _distribuicao_classes(df[df["origem_label"] == v])
                for v in sorted(df["origem_label"].dropna().unique(), key=str)
            }
            if "origem_label" in df.columns else {}
        )

        manifest["labels_manuais"] = {
            "arquivos": stats.get("labels_manuais_arquivos", []),
            "n_pixels_rasterizados_por_sensor": n_pixels_manuais_por_sensor,
            "observacao_rasterizacao": (
                "'rasterizados' = pixels cobertos pelo polígono manual na grade do combo (10m ou "
                "30m), ANTES de erosão de borda e do corte de disponibilidade — número bruto de "
                "rasterio.features.rasterize(all_touched=False). Um polígono de ~0.5ha rasteriza "
                "em ~50px a 10m e ~5-6px a 30m (área do pixel 9x maior); por isso a era Landsat "
                "recebe ordens de grandeza menos pixels manuais que a era Sentinel-2, mesmo com o "
                "mesmo número de polígonos, e isso limita o quanto a rotulagem manual consegue "
                "ajudar a classe crítica na era Landsat."
            ),
            "n_pixels_usados_no_dataset_por_classe": n_pixels_usados_por_classe,
            "n_pixels_sobrescritos_por_classe": n_pixels_sobrescritos_por_classe,
            "observacao_sobrescritos": (
                "'sobrescritos' conta só os pixels onde o label AUTOMÁTICO (MapBiomas) já existia, "
                "era válido e DIFERIA da classe manual — ou seja, o polígono manual de fato mudou "
                "o rótulo de algo que já tinha um valor, não um pixel que só passou a ter label "
                "porque estava fora da máscara automática válida. Contagem por classe = a classe "
                "NOVA (manual) que o pixel recebeu."
            ),
            "politica_precedencia": (
                "onde há polígono manual (rasterizado na grade do combo), ele SUBSTITUI o label "
                "automático (MapBiomas) pixel a pixel, antes de erosão/amostragem — a fonte real do "
                "valor gravado no raster de label continua sendo MapBiomas mesmo em anos com "
                "verificação cruzada do WorldCover (2021): WorldCover só afeta peso_label via "
                "crosscheck, nunca o valor da classe. Onde não há polígono manual, o automático "
                "permanece intocado. Coluna `origem_label` registra a fonte por linha: "
                f"'{ORIGEM_LABEL_AUTOMATICA}' ou '{ORIGEM_LABEL_MANUAL}'."
            ),
            "politica_peso": (
                f"peso_label de amostra manual = {PESO_LABEL_MANUAL_PADRAO} se confianca in "
                f"{{'alta','media'}}, {PESO_LABEL_MANUAL_BAIXA} se confianca=='baixa' (documentado "
                f"em `confianca_manual`). Escolha: {PESO_LABEL_MANUAL_PADRAO}x o peso automático "
                f"típico (1.0) reconhece que a amostra manual é mais cara de produzir (julgamento "
                f"humano) e mais confiável na classe crítica (solo exposto/obras) que MapBiomas/"
                f"WorldCover nunca capturam bem (CLAUDE.md); confianca=='baixa' reduz o peso ao "
                f"mesmo patamar do peso automático 'cheio' ({PESO_LABEL_MANUAL_BAIXA}) — ainda "
                f"conta, mas não domina o gradiente como uma amostra manual confiável."
            ),
            "politica_teto_amostragem": (
                "amostras manuais NUNCA são cortadas pelo teto de amostragem "
                f"({stats.get('teto', TETO_POR_CLASSE_SITE_ANO_SENSOR)} px/classe/AOI/ano/sensor) — "
                "só o pool automático da mesma classe/combo respeita o teto (ver processar_combo)."
            ),
            "distribuicao_classes_por_origem_label": distribuicao_por_origem_label,
            "referencia_split": {
                "path": stats.get("referencia_split_path"),
                "novos_blocos_por_site": stats.get("novos_blocos_por_site"),
                "observacao": (
                    "blocos listados em 'novos_blocos_por_site' NÃO existiam no dataset de "
                    "referência (dataset_v0.2) — só foram criados porque um pixel (manual ou "
                    "automático) caiu numa área que a amostragem de v0.2 nunca havia tocado. Esses "
                    "blocos passaram por um sorteio 70/30 à parte, seedado, que NUNCA altera o "
                    "split dos blocos que já existiam em v0.2 (ver atribuir_split, param "
                    "mapa_referencia) — é o que garante o critério de aceite bloqueante de SV-16: "
                    "'split idêntico em 100% dos blocos comuns entre v0.2 e v1.0'."
                ),
            },
        }

    return manifest


def salvar_dataset(df: pd.DataFrame, versao: str) -> Path:
    parquet_path = SETTINGS.processed_dir / f"dataset_{versao}.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    return parquet_path


def salvar_manifest(manifest: dict[str, Any], versao: str) -> Path:
    manifest_path = SETTINGS.manifests_dir / f"dataset_{versao}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dataset de modelagem (SV-11/SV-27) — split sem vazamento.")
    parser.add_argument("--versao", required=True, help="ex.: v0.1, v0.2")
    parser.add_argument("--seed", type=int, default=None, help="default: RANDOM_SEED do .env / config (42)")
    parser.add_argument(
        "--teto", type=int, default=TETO_POR_CLASSE_SITE_ANO_SENSOR,
        help=f"pixels por classe x AOI x ano x sensor (default histórico v0.1: {TETO_POR_CLASSE_SITE_ANO_SENSOR}; "
             f"SV-27/v0.2 recalibra, ver docs/tarefas/SV-27-dataset-v0.2-expandido.md).",
    )
    parser.add_argument(
        "--holdout-tier", type=int, default=None,
        help="tier (1|2) cujas AOIs ficam inteiramente fora do treino (reserva de generalização "
             "fora-da-amostra, SV-27 item 4). Default: nenhuma reserva.",
    )
    parser.add_argument(
        "--usar-labels-manuais", action="store_true",
        help="incorpora data/labels_manual/*.geojson (SV-10/SV-16), com precedência sobre o "
             "label automático. Default: desligado (comportamento de v0.1/v0.2, inalterado).",
    )
    parser.add_argument(
        "--referencia-split", default=None,
        help="path (relativo ao repo ou absoluto) de um dataset_{versao}.parquet cujo mapeamento "
             "bloco_id->split deve ser reutilizado byte a byte, em vez de resortear (SV-16, "
             "bloqueante para comparar contra uma rodada anterior — ver atribuir_split). "
             "Ex.: data/processed/dataset_v0.2.parquet. Default: None (sorteia do zero).",
    )
    args = parser.parse_args(argv)

    seed = args.seed if args.seed is not None else SETTINGS.seed
    referencia_split_path = None
    if args.referencia_split:
        p = Path(args.referencia_split)
        referencia_split_path = p if p.is_absolute() else REPO_ROOT / p

    print(
        f"Montando dataset {args.versao} (seed={seed}, teto={args.teto}, holdout_tier={args.holdout_tier}, "
        f"usar_labels_manuais={args.usar_labels_manuais}, referencia_split={referencia_split_path})..."
    )
    df, stats = montar_dataset(
        seed, teto=args.teto, holdout_tier=args.holdout_tier,
        usar_labels_manuais=args.usar_labels_manuais, referencia_split_path=referencia_split_path,
    )
    print(f"OK — {len(df)} linhas amostradas, {len(stats['combos'])} combos (sensor, site, ano).")

    parquet_path = salvar_dataset(df, args.versao)
    print(f"Parquet salvo: {parquet_path}")

    manifest = construir_manifest(df, stats, versao=args.versao, seed=seed, parquet_path=parquet_path)
    manifest_path = salvar_manifest(manifest, args.versao)
    print(f"Manifest salvo: {manifest_path}")

    print()
    print(f"n_linhas={manifest['n_linhas']} | n_blocos_treino={manifest['n_blocos']['treino']} | "
          f"n_blocos_teste={manifest['n_blocos']['teste']} | memoria_mb={manifest['memoria_mb']}")
    print("Distribuição de classes (total):", manifest["distribuicao_classes"]["total"])
    for sensor, dist in manifest["distribuicao_classes"]["por_sensor"].items():
        print(f"  {sensor}: {dist}")
    print("Erosão de borda (pixels descartados por era):", manifest["erosao"])
    if manifest["aois_holdout_espacial"]:
        print("AOIs em holdout espacial:", manifest["aois_holdout_espacial"])
    if manifest["regioes_sem_ambos_splits"]:
        print("ATENÇÃO — regiões sem os dois splits:", manifest["regioes_sem_ambos_splits"])
    if manifest["biomas_sem_ambos_splits"]:
        print("ATENÇÃO — biomas sem os dois splits:", manifest["biomas_sem_ambos_splits"])
    if "labels_manuais" in manifest:
        lm = manifest["labels_manuais"]
        print()
        print(f"Labels manuais — rasterizados por sensor: {lm['n_pixels_rasterizados_por_sensor']}")
        print(f"Labels manuais — usados no dataset por classe: {lm['n_pixels_usados_no_dataset_por_classe']}")
        print(f"Labels manuais — sobrescreveram automático, por classe: {lm['n_pixels_sobrescritos_por_classe']}")
        if lm["referencia_split"]["novos_blocos_por_site"]:
            n_novos = sum(len(v) for v in lm["referencia_split"]["novos_blocos_por_site"].values())
            print(f"ATENÇÃO — {n_novos} bloco(s) novo(s) (fora da referência), sorteados à parte: "
                  f"{lm['referencia_split']['novos_blocos_por_site']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
