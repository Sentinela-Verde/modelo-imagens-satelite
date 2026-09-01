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

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import binary_erosion
from sklearn.model_selection import train_test_split

from . import classes
from .config import REPO_ROOT, SETTINGS

# --------------------------------------------------------------------------------------------
# Constantes / contrato
# --------------------------------------------------------------------------------------------

TETO_POR_CLASSE_SITE_ANO_SENSOR = 8000
TAMANHO_BLOCO_M = 1000.0  # grade 1 km x 1 km, ver docstring do módulo
TEST_SIZE = 0.30
PESO_LABEL_DISCORDANCIA_CROSSCHECK = 0.5  # fator aplicado no ano de verificação cruzada (2021)
                                            # quando MapBiomas e WorldCover discordam

SENSORES = ("s2", "landsat")


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


def processar_combo(
    sensor_token: str,
    site_id: str,
    ano: int,
    rng: np.random.Generator,
    erosao_acumulada: dict[str, dict[str, int]],
    anos_sobreposicao: set[int],
) -> pd.DataFrame:
    """Lê features + label de um combo (sensor, site, ano), erode, amostra e monta as linhas."""
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

        n_amostra = min(TETO_POR_CLASSE_SITE_ANO_SENSOR, n_disponivel)
        if n_amostra < n_disponivel:
            escolhidos = rng.choice(n_disponivel, size=n_amostra, replace=False)
        else:
            escolhidos = np.arange(n_disponivel)

        linhas_sel = linhas_disp[escolhidos]
        colunas_sel = colunas_disp[escolhidos]

        x, y = _xy_pixel_centro(transform, linhas_sel, colunas_sel)
        bloco_ids = _blocos_id_vetorizado(site_id, x, y)

        feats_sel = feat_arr[:, linhas_sel, colunas_sel].T  # (n_amostra, n_features)
        conc_sel = concordancia_arr[linhas_sel, colunas_sel] if concordancia_arr is not None else None
        peso = np.broadcast_to(peso_label(distancia_safra, conc_sel), (n_amostra,)).astype(np.float64)

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
        partes.append(df_parte)

    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


# --------------------------------------------------------------------------------------------
# Split por bloco — 70/30, estratificado por site, todos os anos/sensores de um bloco juntos.
# --------------------------------------------------------------------------------------------


def atribuir_split(df: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, dict[str, int]]:
    """Sorteia bloco_id inteiros para treino/teste (nunca pixels) — fecha os 3 vetores de
    vazamento descritos na docstring do módulo. Estratificado por site: cada site tem seu
    próprio sorteio 70/30 sobre a lista (ordenada, determinística) de blocos únicos daquele site.
    """
    bloco_para_split: dict[str, str] = {}
    n_treino = 0
    n_teste = 0

    for site_id in sorted(df["site_id"].unique()):
        blocos_site = sorted(df.loc[df["site_id"] == site_id, "bloco_id"].unique())
        if len(blocos_site) < 2:
            # site com um único bloco: não dá pra split — tudo em treino, registrado no manifest.
            blocos_treino, blocos_teste = blocos_site, []
        else:
            blocos_treino, blocos_teste = train_test_split(
                blocos_site, test_size=TEST_SIZE, random_state=seed
            )
        n_treino += len(blocos_treino)
        n_teste += len(blocos_teste)
        for b in blocos_treino:
            bloco_para_split[b] = "treino"
        for b in blocos_teste:
            bloco_para_split[b] = "teste"

    df = df.copy()
    df["split"] = df["bloco_id"].map(bloco_para_split)

    ano_mais_recente = int(df["ano"].max())
    df["holdout_temporal"] = df["ano"] == ano_mais_recente

    return df, {"treino": n_treino, "teste": n_teste}


# --------------------------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------------------------


def montar_dataset(seed: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    combos = _combos_disponiveis()
    if not combos:
        raise DatasetError(
            "nenhum combo (sensor, site, ano) com features (SV-08) e label (SV-07) encontrado — "
            "rode os módulos anteriores antes de sentinela.dataset."
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

    rng = np.random.default_rng(seed)
    anos_sobreposicao = _anos_sobreposicao()
    erosao_acumulada: dict[str, dict[str, int]] = {}

    partes: list[pd.DataFrame] = []
    for sensor_token, site_id, ano in combos:
        parte = processar_combo(sensor_token, site_id, ano, rng, erosao_acumulada, anos_sobreposicao)
        if not parte.empty:
            partes.append(parte)

    if not partes:
        raise DatasetError("nenhuma linha amostrada em nenhum combo — verifique os rasters de entrada.")

    df = pd.concat(partes, ignore_index=True)
    df, n_blocos = atribuir_split(df, seed)

    assert lista_features_referencia is not None
    stats: dict[str, Any] = {
        "lista_features": lista_features_referencia,
        "rasters_origem": rasters_origem,
        "erosao": erosao_acumulada,
        "n_blocos": n_blocos,
        "combos": combos,
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
}


def _colunas_feature(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in _COLUNAS_NAO_FEATURE]


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
            "treino/teste, com random_state=42, estratificado por site: todos os anos e "
            "sensores de um mesmo bloco vão para o mesmo split. Isso fecha os 3 vetores de "
            "vazamento de dados do projeto ao mesmo tempo: espacial (pixels vizinhos), "
            "temporal (mesmo lugar em anos consecutivos) e entre sensores (mesmo lugar, mesmo "
            "ano, duas cópias em resoluções diferentes nos anos de sobreposição 2019-2021). "
            "holdout_temporal marca o ano mais recente do dataset (2025) como flag informativo "
            "adicional para validação temporal em SV-12 — não substitui nem sobrepõe o split "
            "por bloco, que continua sendo a única fonte de verdade da coluna `split`."
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
            "teto_por_classe_site_ano_sensor": TETO_POR_CLASSE_SITE_ANO_SENSOR,
            "erosao_borda_px": 1,
            "observacao": (
                "teto por sensor (não proporcional à contagem de pixels) — um pixel Landsat de "
                "30m cobre 9x a área de um pixel S2 de 10m; teto proporcional faria a era "
                "moderna dominar o dataset ~9:1."
            ),
        },
        "rasters_origem": stats["rasters_origem"],
        "sha256": _sha256_arquivo(parquet_path),
        "git_sha": _git_sha(),
        "gerado_em": datetime.now(UTC).isoformat(),
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
    parser = argparse.ArgumentParser(description="Dataset de modelagem v0.1 (SV-11) — split sem vazamento.")
    parser.add_argument("--versao", required=True, help="ex.: v0.1")
    parser.add_argument("--seed", type=int, default=None, help="default: RANDOM_SEED do .env / config (42)")
    args = parser.parse_args(argv)

    seed = args.seed if args.seed is not None else SETTINGS.seed

    print(f"Montando dataset {args.versao} (seed={seed})...")
    df, stats = montar_dataset(seed)
    print(f"OK — {len(df)} linhas amostradas, {len(stats['combos'])} combos (sensor, site, ano).")

    parquet_path = salvar_dataset(df, args.versao)
    print(f"Parquet salvo: {parquet_path}")

    manifest = construir_manifest(df, stats, versao=args.versao, seed=seed, parquet_path=parquet_path)
    manifest_path = salvar_manifest(manifest, args.versao)
    print(f"Manifest salvo: {manifest_path}")

    print()
    print(f"n_linhas={manifest['n_linhas']} | n_blocos_treino={manifest['n_blocos']['treino']} | "
          f"n_blocos_teste={manifest['n_blocos']['teste']}")
    print("Distribuição de classes (total):", manifest["distribuicao_classes"]["total"])
    for sensor, dist in manifest["distribuicao_classes"]["por_sensor"].items():
        print(f"  {sensor}: {dist}")
    print("Erosão de borda (pixels descartados por era):", manifest["erosao"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
