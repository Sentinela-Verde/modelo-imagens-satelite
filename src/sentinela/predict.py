"""Inferência em lote: features .tif -> raster classificado (SV-14).

Rode com:

    python -m sentinela.predict --modelo models/rf_v1.0.joblib --sensor <s2|landsat|all> \
        --site <id|all> --ano <ano|all> [--force]

Este módulo é o primeiro ponto em que o modelo treinado (`sentinela.train`, SV-12) vê o raster
inteiro em vez de uma tabela amostrada — item 5 da Definition of Done da V1 ("classificação
reproduzível"). Lê `data/interim/features/{sensor}/{site}/{ano}.tif` (13 bandas — 6 harmonizadas +
7 índices, SV-08) e produz `data/processed/classificado/{sensor}/{site}/{ano}.tif` (1 banda uint8,
classes 1-5, nodata=0).

**O risco desta etapa é ordem de coluna.** O pacote do modelo (`joblib.load(...)["lista_features"]`)
é a ÚNICA fonte de verdade de quantas features entram e em que ordem — nunca a ordem física das
bandas no `.tif` (que pode, em teoria, divergir do que o modelo espera). Cada nome de
`lista_features` é casado por NOME contra `ds.descriptions` (com fallback pro manifest de SV-08) e
reordenado; se sobrar algum nome sem banda correspondente, erro explícito nomeando o que falta —
nunca uma predição silenciosa com o que der.

`lista_features` do `rf_v1.0` tem 14 entradas: as 13 bandas físicas do stack de SV-08 mais
`sensor_landsat` (feature DERIVADA, ver `sentinela.train.montar_xy` — 1.0 se a era é Landsat, 0.0
se Sentinel-2, nunca lida do raster). É por isso que o mesmo modelo roda nas duas eras sem nenhum
`if sensor ==` no caminho de predição: a única coisa que muda por era é essa constante escalar
reconstruída a partir do argumento `--sensor`, não um ramo de código.

**Processamento em janelas** (`rasterio.windows`): o stack de entrada (13 bandas int16, escala
`FATOR_ESCALA=10000` do manifest de SV-08) nunca é lido inteiro de uma vez — cada janela é lida,
descalada, tem as colunas reordenadas e classificada isoladamente. O array de SAÍDA (1 banda
uint8) é pequeno o bastante (no maior site desta rodada, ~1000x1000 px = ~1 MB) para ser acumulado
em memória enquanto cada janela é gravada no `.tif` de destino — não é o que a restrição de
memória do enunciado está protegendo (que é o stack float/int de 13 bandas), e mantê-lo em memória
evita reabrir o arquivo de saída para PNG/hash/estatística depois.

**sha256 do manifest é sobre os PIXELS classificados, não sobre os bytes do arquivo `.tif`.**
Decisão deliberada: o `.tif` carrega uma tag `gerado_em` (timestamp de execução, item 7 do
enunciado) — dois runs do mesmo site/ano produzem arquivos byte-diferentes só por causa dessa tag,
mesmo com classificação idêntica. Hashear os bytes do arquivo inteiro faria o critério de aceite
"rodar duas vezes -> mesmo sha256" falhar sempre, por um motivo que nada tem a ver com
reprodutibilidade da classificação. `sha256` no manifest e na tag do GeoTIFF é
`hashlib.sha256(classe_uint8.tobytes()).hexdigest()` — determinístico função só do modelo + input,
que é o que a validação do enunciado realmente quer garantir.

Ordem de execução do lote (`--site all`, item 10 do enunciado): tier 1 inteiro (todos os anos, os
dois sensores) antes de tier 2 — mesma convenção de `sentinela.gee.executar_lote` (SV-26). Cada
item (sensor, site, ano) é idempotente (confere sha256 do modelo já usado e pula se já bate, a
menos que `--force`) e um manifest de execução agregado
(`data/manifests/execucao_lote_predict.json`) registra status/duração por item — mesmo padrão de
retomada de SV-26, sem reimplementar um segundo mecanismo de lote. Falha em um item não aborta o
lote inteiro: é registrada e o lote segue para o próximo.

Manifest de saída por item: `data/manifests/classificado_{sensor}_{site}_{ano}.json` — o enunciado
original (SV-14) escreve o nome sem `{sensor}`, mas os anos 2019/2020/2021 têm raster classificado
NAS DUAS eras (`anos_sobreposicao` de `config/params.yml`) — sem o sensor no nome, o manifest de
uma era sobrescreveria o da outra silenciosamente. Mesma convenção já usada por
`features_{sensor}_{site}_{ano}.json`/`labels_{sensor}_{site}_{ano}.json` (SV-07/SV-08).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import rasterio
from rasterio.windows import Window

from . import classes
from .config import REPO_ROOT, SETTINGS
from .train import SENSOR_FEATURE_COL

# --------------------------------------------------------------------------------------------
# Contrato / constantes
# --------------------------------------------------------------------------------------------

WINDOW_SIZE = 512  # px — não é um raster inteiro, mas também não itera pixel a pixel
CLASS_IDS = [1, 2, 3, 4, 5]

LIMIAR_DISCO_LIVRE_GB = 5.0  # abaixo disso, para e reporta (item "contexto sobre disco")
CHECAGEM_DISCO_PERIODICA = 20  # a cada N itens processados

SENSOR_TOKENS = ("landsat", "s2")


class PredictError(RuntimeError):
    """Erro de inferência com mensagem acionável (contrato de features quebrado, etc.)."""


class DiscoBaixoError(RuntimeError):
    """Espaço em disco abaixo do limiar — sinal para o lote parar e reportar, não estourar o disco."""


# --------------------------------------------------------------------------------------------
# Disco (mesmo padrão de sentinela.gee.executar_lote, SV-26)
# --------------------------------------------------------------------------------------------


def espaco_livre_gb() -> float:
    import shutil

    return shutil.disk_usage(REPO_ROOT).free / (1024**3)


def _checar_disco(contexto: str = "") -> float:
    livre_gb = espaco_livre_gb()
    if livre_gb < LIMIAR_DISCO_LIVRE_GB:
        raise DiscoBaixoError(
            f"espaço livre em disco ({livre_gb:.2f} GB) abaixo do limiar mínimo de "
            f"{LIMIAR_DISCO_LIVRE_GB} GB{' (' + contexto + ')' if contexto else ''}."
        )
    return livre_gb


# --------------------------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - git ausente não pode derrubar a inferência
        return "desconhecido"


def _sha256_arquivo(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------------------------


def carregar_modelo(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        raise PredictError(f"modelo ausente: {caminho} (rode `python -m sentinela.train` antes)")
    pacote = joblib.load(caminho)
    for chave in ("modelo", "lista_features"):
        if chave not in pacote:
            raise PredictError(f"pacote do modelo {caminho} não tem a chave obrigatória '{chave}'")
    return pacote


def _modelo_sha256(caminho_joblib: Path) -> str:
    sha_path = caminho_joblib.with_suffix(".sha256")
    if sha_path.exists():
        return sha_path.read_text(encoding="utf-8").split()[0]
    return _sha256_arquivo(caminho_joblib)


# --------------------------------------------------------------------------------------------
# Sites / tiers (mesmo padrão de sentinela.gee.executar_lote._sites_ativos/_grupos_por_tier)
# --------------------------------------------------------------------------------------------


def _sites_ativos() -> list[dict[str, Any]]:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[gdf["ativo"] == True]  # noqa: E712
    out = [
        {
            "site_id": r["site_id"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "tier": int(r["tier"]),
            "bioma": r.get("bioma"),
        }
        for _, r in gdf.iterrows()
    ]
    return sorted(out, key=lambda s: s["site_id"])


def _grupos_por_tier(sites: list[dict], site_arg: str | None) -> list[list[dict]]:
    """Tier 1 inteiro antes de tier 2 (item 10 do enunciado) — `--site` restringe a 1 AOI."""
    if site_arg:
        alvo = [s for s in sites if s["site_id"] == site_arg]
        if not alvo:
            disponiveis = sorted(s["site_id"] for s in sites)
            raise SystemExit(f"site_id '{site_arg}' não encontrado entre as AOIs ativas. Disponíveis: {disponiveis}")
        return [alvo]
    return [[s for s in sites if s["tier"] == 1], [s for s in sites if s["tier"] == 2]]


# --------------------------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------------------------


def _caminho_features(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.interim_dir / "features" / sensor_token / site_id / f"{ano}.tif"


def _caminho_manifest_features(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.manifests_dir / f"features_{sensor_token}_{site_id}_{ano}.json"


def _caminho_saida(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.processed_dir / "classificado" / sensor_token / site_id / f"{ano}.tif"


def _caminho_saida_confianca(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.processed_dir / "classificado" / sensor_token / site_id / f"{ano}_confianca.tif"


def _caminho_manifest_saida(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.manifests_dir / f"classificado_{sensor_token}_{site_id}_{ano}.json"


def _anos_disponiveis(sensor_token: str, site_id: str) -> list[int]:
    d = SETTINGS.interim_dir / "features" / sensor_token / site_id
    if not d.exists():
        return []
    return sorted(int(p.stem) for p in d.glob("*.tif"))


# --------------------------------------------------------------------------------------------
# Contrato de features — casamento por NOME, nunca por posição (o núcleo de SV-14)
# --------------------------------------------------------------------------------------------


def _validar_contrato_bandas(bandas_raster: list[str], lista_features: list[str]) -> None:
    disponiveis = set(bandas_raster)
    faltando = [f for f in lista_features if f != SENSOR_FEATURE_COL and f not in disponiveis]
    if faltando:
        raise PredictError(
            f"banda(s) exigida(s) pelo modelo ausente(s) no raster de features: {faltando} "
            f"(bandas disponíveis no raster: {bandas_raster}). Nunca prossigo com o que der — "
            "contrato de SV-14."
        )


def _iter_windows(width: int, height: int, tam: int = WINDOW_SIZE):
    for row_off in range(0, height, tam):
        h = min(tam, height - row_off)
        for col_off in range(0, width, tam):
            w = min(tam, width - col_off)
            yield Window(col_off, row_off, w, h)


def _classificar_janela(
    stack_bruto: np.ndarray,
    idx_por_nome: dict[str, int],
    lista_features: list[str],
    fator_escala: float | None,
    nodata_raw: float,
    valor_sensor: float,
    modelo: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Uma janela (n_bandas_raster, h, w) int/float -> (classe uint8, confianca uint8), ambas (h, w).

    `valor_sensor`: 1.0 (era Landsat) ou 0.0 (era Sentinel-2) — reconstrói `sensor_landsat` como
    constante escalar da janela inteira, nunca lida de banda nenhuma (ver docstring do módulo).

    `fator_escala`: só é aplicado (divide) se o manifest de SV-08 tiver a chave `fator_escala` E o
    array lido do raster for de tipo inteiro — mesma condição de `sentinela.dataset._ler_stack_features`.
    Alguns stacks de features foram gravados ANTES da otimização de disco de SV-26 (float32 já em
    reflectância/índice, sem `fator_escala` no manifest) — dividir esses por 10000 silenciosamente
    produziria valores ~1e-5 e o modelo prediria lixo sem erro nenhum (foi exatamente o que
    aconteceu na primeira rodada desta tarefa — ver relatório final). Nunca assume int16+10000."""
    _, h, w = stack_bruto.shape
    invalido = np.any(stack_bruto == nodata_raw, axis=0)
    aplicar_escala = fator_escala is not None and np.issubdtype(stack_bruto.dtype, np.integer)

    colunas = []
    for nome in lista_features:
        if nome == SENSOR_FEATURE_COL:
            colunas.append(np.full((h, w), valor_sensor, dtype=np.float32))
        else:
            banda = stack_bruto[idx_por_nome[nome]].astype(np.float32)
            if aplicar_escala:
                banda = banda / np.float32(fator_escala)
            colunas.append(banda)
    X_full = np.stack(colunas, axis=-1)  # (h, w, n_features)

    classe_out = np.zeros((h, w), dtype=np.uint8)
    confianca_out = np.zeros((h, w), dtype=np.uint8)

    validos = ~invalido
    n_validos = int(validos.sum())
    if n_validos == 0:
        return classe_out, confianca_out

    X_validos = X_full[validos]
    pred = modelo.predict(X_validos)
    proba = modelo.predict_proba(X_validos)
    conf = np.clip(np.round(proba.max(axis=1) * 100.0), 0, 100).astype(np.uint8)

    classe_out[validos] = pred.astype(np.uint8)
    confianca_out[validos] = conf
    return classe_out, confianca_out


# --------------------------------------------------------------------------------------------
# Item (sensor, site, ano) — a unidade idempotente do lote
# --------------------------------------------------------------------------------------------


def _ja_classificado(manifest_path: Path, tif_path: Path, modelo_sha256: str) -> bool:
    if not (manifest_path.exists() and tif_path.exists()):
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return manifest.get("modelo_sha256") == modelo_sha256


def classificar_site_ano(
    sensor_token: str,
    site_id: str,
    ano: int,
    pacote: dict[str, Any],
    modelo_path: Path,
    *,
    force: bool = False,
    gerar_png: bool = False,
) -> dict[str, Any]:
    """Classifica um raster de features inteiro (SV-14) — a função idempotente que o lote chama.

    Retorna um dict de resumo (usado pelo relatório final e pelos testes de validação). Nunca
    ramifica por `sensor_token` no caminho de predição — só usa o token para (a) escolher o
    caminho de entrada/saída e (b) reconstruir a constante `sensor_landsat`."""
    feat_path = _caminho_features(sensor_token, site_id, ano)
    feat_manifest_path = _caminho_manifest_features(sensor_token, site_id, ano)
    out_tif = _caminho_saida(sensor_token, site_id, ano)
    out_confianca = _caminho_saida_confianca(sensor_token, site_id, ano)
    out_manifest_path = _caminho_manifest_saida(sensor_token, site_id, ano)

    if not feat_path.exists():
        raise PredictError(f"{feat_path} não existe — rode SV-08 (sentinela.features.indices) antes.")
    if not feat_manifest_path.exists():
        raise PredictError(f"{feat_manifest_path} não existe.")

    modelo_sha256 = _modelo_sha256(modelo_path)

    if not force and _ja_classificado(out_manifest_path, out_tif, modelo_sha256):
        manifest_existente = json.loads(out_manifest_path.read_text(encoding="utf-8"))
        manifest_existente["_pulado"] = True
        return manifest_existente

    feat_manifest = json.loads(feat_manifest_path.read_text(encoding="utf-8"))
    lista_features: list[str] = pacote["lista_features"]
    fator_escala_raw = feat_manifest.get("fator_escala")
    fator_escala = float(fator_escala_raw) if fator_escala_raw is not None else None
    valor_sensor = 1.0 if sensor_token == "landsat" else 0.0

    with rasterio.open(feat_path) as src:
        descricoes = list(src.descriptions)
        bandas_raster = descricoes if all(descricoes) else list(feat_manifest["bandas"])
        _validar_contrato_bandas(bandas_raster, lista_features)
        idx_por_nome = {nome: i for i, nome in enumerate(bandas_raster)}

        nodata_raw = src.nodata if src.nodata is not None else feat_manifest.get("nodata", -9999)
        width, height = src.width, src.height
        crs, transform = src.crs, src.transform

        classe_full = np.zeros((height, width), dtype=np.uint8)
        confianca_full = np.zeros((height, width), dtype=np.uint8)

        colormap = classes.colormap()
        gerado_em = datetime.now(UTC).isoformat()
        git_sha = _git_sha()
        tags_comuns = {
            "modelo_versao": Path(modelo_path).stem,
            "modelo_sha256": modelo_sha256,
            "dataset_versao": str(pacote.get("versao_dataset", "desconhecido")),
            "git_sha": git_sha,
            "gerado_em": gerado_em,
            "classes": json.dumps(classes.ID_TO_SLUG, ensure_ascii=False),
            "site_id": site_id,
            "ano": str(ano),
            "sensor": sensor_token,
        }

        out_tif.parent.mkdir(parents=True, exist_ok=True)
        # GDAL exige blockxsize/blockysize múltiplos de 16 quando tiled=True. AOIs na era Landsat
        # (30 m) ficam com ~330x330 px — bem abaixo de um tile de 256 múltiplo de 16 "seguro" nos
        # dois eixos. Só ativa tiling (com bloco fixo de 256, múltiplo de 16) quando o raster é
        # grande o bastante nos dois eixos; senão grava em faixas (strip), que não têm essa
        # restrição — nunca afeta os valores gravados, só o layout físico do arquivo.
        TILE = 256
        usar_tile = width >= TILE and height >= TILE
        profile_classe: dict[str, Any] = {
            "driver": "GTiff",
            "dtype": "uint8",
            "nodata": 0,
            "width": width,
            "height": height,
            "count": 1,
            "crs": crs,
            "transform": transform,
            "compress": "LZW",
        }
        if usar_tile:
            profile_classe.update(tiled=True, blockxsize=TILE, blockysize=TILE)
        profile_confianca = dict(profile_classe)

        with rasterio.open(out_tif, "w", **profile_classe) as dst_classe, \
                rasterio.open(out_confianca, "w", **profile_confianca) as dst_conf:
            for window in _iter_windows(width, height):
                stack = src.read(window=window)
                classe_j, conf_j = _classificar_janela(
                    stack, idx_por_nome, lista_features, fator_escala, nodata_raw, valor_sensor, pacote["modelo"]
                )
                row0, col0 = int(window.row_off), int(window.col_off)
                h, w = classe_j.shape
                classe_full[row0:row0 + h, col0:col0 + w] = classe_j
                confianca_full[row0:row0 + h, col0:col0 + w] = conf_j
                dst_classe.write(classe_j[np.newaxis, :, :], window=window)
                dst_conf.write(conf_j[np.newaxis, :, :], window=window)

            dst_classe.write_colormap(1, colormap)
            dst_classe.update_tags(**tags_comuns)
            dst_conf.update_tags(**tags_comuns, camada="confianca_predict_proba_max_pct")

    n_total = int(classe_full.size)
    validos_mask = classe_full != 0
    n_validos = int(validos_mask.sum())
    n_nodata = n_total - n_validos
    distribuicao = {
        classes.ID_TO_SLUG[cid]: int(np.sum(classe_full == cid)) for cid in CLASS_IDS
    }
    confianca_validos = confianca_full[validos_mask]
    stats_confianca = (
        {
            "media": round(float(confianca_validos.mean()), 2),
            "minima": int(confianca_validos.min()),
            "maxima": int(confianca_validos.max()),
        }
        if n_validos
        else None
    )

    sha256_pixels = _sha256_bytes(classe_full.tobytes())
    sha256_confianca_pixels = _sha256_bytes(confianca_full.tobytes())

    manifest = {
        "site_id": site_id,
        "ano": ano,
        "sensor": sensor_token,
        "modelo_versao": Path(modelo_path).stem,
        "modelo_path": str(Path(modelo_path).resolve().relative_to(REPO_ROOT)) if Path(modelo_path).resolve().is_relative_to(REPO_ROOT) else str(modelo_path),
        "modelo_sha256": modelo_sha256,
        "dataset_versao": str(pacote.get("versao_dataset", "desconhecido")),
        "lista_features": lista_features,
        "git_sha": git_sha,
        "gerado_em": gerado_em,
        "classes": classes.ID_TO_SLUG,
        "crs": str(crs),
        "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
        "shape": {"width": width, "height": height},
        "n_pixels_total": n_total,
        "n_pixels_validos": n_validos,
        "n_pixels_nodata": n_nodata,
        "pct_pixels_validos": round(100.0 * n_validos / n_total, 4) if n_total else 0.0,
        "distribuicao_classes": distribuicao,
        "confianca": stats_confianca,
        "sha256": sha256_pixels,
        "sha256_nota": "hash dos bytes do array uint8 de classes preditas, NAO do arquivo .tif inteiro (ver docstring do módulo) — é o que garante o critério de determinismo.",
        "sha256_confianca": sha256_confianca_pixels,
        "tif": str(out_tif.relative_to(REPO_ROOT)),
        "tif_confianca": str(out_confianca.relative_to(REPO_ROOT)),
    }
    out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")

    if gerar_png:
        gerar_png_conferencia(sensor_token, site_id, ano, classe_full)

    manifest["_pulado"] = False
    manifest["_classe_full"] = classe_full  # usado por quem chama para checagens em memória (não persistido)
    return manifest


# --------------------------------------------------------------------------------------------
# PNG de conferência (item 9 do enunciado)
# --------------------------------------------------------------------------------------------


def gerar_png_conferencia(sensor_token: str, site_id: str, ano: int, classe_arr: np.ndarray) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    colormap = classes.colormap()
    cores = [tuple(c / 255.0 for c in colormap[cid]) for cid in sorted(colormap)]
    cmap = ListedColormap(cores)
    bounds = [cid - 0.5 for cid in sorted(colormap)] + [max(colormap) + 0.5]
    norm = BoundaryNorm(bounds, cmap.N)

    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.imshow(classe_arr, cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_title(f"{site_id} — {sensor_token} — {ano}", fontsize=10)
    ax.axis("off")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=tuple(c / 255.0 for c in colormap[cid]))
        for cid in sorted(colormap)
    ]
    labels = [classes.CLASSES[cid]["nome_exibicao"] for cid in sorted(colormap)]
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, fontsize=7, frameon=False)

    out_dir = REPO_ROOT / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"mapa_{sensor_token}_{site_id}_{ano}.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def gerar_png_comparacao(site_id: str, pares: list[tuple[str, int, np.ndarray]], caminho: Path) -> Path:
    """`pares`: lista de (sensor_token, ano, classe_arr) em ordem cronológica — painel horizontal."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    colormap = classes.colormap()
    cores = [tuple(c / 255.0 for c in colormap[cid]) for cid in sorted(colormap)]
    cmap = ListedColormap(cores)
    bounds = [cid - 0.5 for cid in sorted(colormap)] + [max(colormap) + 0.5]
    norm = BoundaryNorm(bounds, cmap.N)

    n = len(pares)
    fig, axes = plt.subplots(1, n, figsize=(3.2 * n, 3.6))
    axes = np.atleast_1d(axes)
    for ax, (sensor_token, ano, arr) in zip(axes, pares, strict=True):
        ax.imshow(arr, cmap=cmap, norm=norm, interpolation="nearest")
        ax.set_title(f"{ano}\n({sensor_token})", fontsize=9)
        ax.axis("off")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=tuple(c / 255.0 for c in colormap[cid]))
        for cid in sorted(colormap)
    ]
    labels = [classes.CLASSES[cid]["nome_exibicao"] for cid in sorted(colormap)]
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.05))
    fig.suptitle(f"{site_id} — evolução da cobertura do solo", fontsize=12)

    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(caminho, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return caminho


# --------------------------------------------------------------------------------------------
# Sanidade de domínio (bloqueante) — Ascenty Vinhedo 2025 não pode sair como vegetação densa
# --------------------------------------------------------------------------------------------


def pixel_da_coordenada(crs_raster: Any, transform: rasterio.Affine, lon: float, lat: float) -> tuple[int, int]:
    """(linha, coluna) do pixel do raster que contém (lon, lat) em EPSG:4326."""
    from rasterio.warp import transform as warp_transform

    xs, ys = warp_transform("EPSG:4326", crs_raster, [lon], [lat])
    linha, coluna = rasterio.transform.rowcol(transform, xs[0], ys[0])
    return int(linha), int(coluna)


def checar_sanidade_data_center(
    classe_arr: np.ndarray, crs_raster: Any, transform: rasterio.Affine, lon: float, lat: float, raio_px: int = 3
) -> dict[str, Any]:
    """Vizinhança `raio_px` em torno da coordenada do site — resposta mais robusta que 1 pixel só
    (a coordenada pode cair perto de uma borda de prédio)."""
    linha, coluna = pixel_da_coordenada(crs_raster, transform, lon, lat)
    h, w = classe_arr.shape
    l0, l1 = max(0, linha - raio_px), min(h, linha + raio_px + 1)
    c0, c1 = max(0, coluna - raio_px), min(w, coluna + raio_px + 1)
    janela = classe_arr[l0:l1, c0:c1]
    valores, contagens = np.unique(janela, return_counts=True)
    classe_central = int(classe_arr[linha, coluna]) if 0 <= linha < h and 0 <= coluna < w else -1
    return {
        "linha": linha,
        "coluna": coluna,
        "classe_pixel_central": classe_central,
        "classe_slug_central": classes.ID_TO_SLUG.get(classe_central, "fora_do_raster"),
        "distribuicao_vizinhanca": {int(v): int(c) for v, c in zip(valores, contagens, strict=True)},
        "passou": classe_central in (3, 4),
    }


# --------------------------------------------------------------------------------------------
# Continuidade entre eras — 2018 (Landsat) vs 2019 (Sentinel-2) do mesmo site
# --------------------------------------------------------------------------------------------


def checar_continuidade_eras(
    classe_landsat: np.ndarray, crs_landsat: Any, transform_landsat: rasterio.Affine,
    classe_s2: np.ndarray, crs_s2: Any, transform_s2: rasterio.Affine,
) -> dict[str, Any]:
    """Reprojeta o mapa Sentinel-2 (10 m) para a grade Landsat (30 m, nearest) e mede a
    concordância pixel a pixel — aproximação (áreas que mudaram de verdade entre os dois anos
    contam como "discordância", então a concordância esperada não é 100%; ver docstring do
    enunciado, item "Continuidade entre eras")."""
    from rasterio.warp import Resampling, reproject

    s2_reprojetado = np.zeros_like(classe_landsat, dtype=np.uint8)
    reproject(
        source=classe_s2,
        destination=s2_reprojetado,
        src_transform=transform_s2,
        src_crs=crs_s2,
        dst_transform=transform_landsat,
        dst_crs=crs_landsat,
        resampling=Resampling.nearest,
        src_nodata=0,
        dst_nodata=0,
    )

    validos = (classe_landsat != 0) & (s2_reprojetado != 0)
    n_validos = int(validos.sum())
    if n_validos == 0:
        return {"n_pixels_comparados": 0, "pct_concordancia": None}

    concordam = classe_landsat[validos] == s2_reprojetado[validos]
    pct_concordancia = 100.0 * float(concordam.sum()) / n_validos

    return {
        "n_pixels_comparados": n_validos,
        "pct_concordancia": round(pct_concordancia, 2),
        "distribuicao_landsat": {
            classes.ID_TO_SLUG[cid]: int(np.sum(classe_landsat[validos] == cid)) for cid in CLASS_IDS
        },
        "distribuicao_s2_reprojetado": {
            classes.ID_TO_SLUG[cid]: int(np.sum(s2_reprojetado[validos] == cid)) for cid in CLASS_IDS
        },
    }


# --------------------------------------------------------------------------------------------
# Manifest de execução do lote (mesmo padrão de execucao_lote_{etapa}.json de SV-26)
# --------------------------------------------------------------------------------------------


def _manifest_lote_path() -> Path:
    return SETTINGS.manifests_dir / "execucao_lote_predict.json"


def _carregar_manifest_lote() -> dict[str, Any]:
    path = _manifest_lote_path()
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.setdefault("itens", {})
            return manifest
        except (json.JSONDecodeError, OSError):
            pass
    return {"iniciado_em": datetime.now(UTC).isoformat(), "itens": {}}


def _salvar_manifest_lote(manifest: dict[str, Any]) -> None:
    manifest["atualizado_em"] = datetime.now(UTC).isoformat()
    path = _manifest_lote_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inferência em lote — raster classificado (SV-14).")
    parser.add_argument("--modelo", required=True, help="caminho do .joblib, ex.: models/rf_v1.0.joblib")
    parser.add_argument("--sensor", required=True, choices=["s2", "landsat", "all"])
    parser.add_argument("--site", default="all", help="site_id de config/sites.geojson, ou 'all'")
    parser.add_argument("--ano", default="all", help="ano, ou 'all'")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    modelo_path_arg = Path(args.modelo)
    modelo_path = modelo_path_arg if modelo_path_arg.is_absolute() else REPO_ROOT / modelo_path_arg
    pacote = carregar_modelo(modelo_path)
    print(f"Modelo: {modelo_path} | lista_features ({len(pacote['lista_features'])}): {pacote['lista_features']}")

    sensores = list(SENSOR_TOKENS) if args.sensor == "all" else [args.sensor]

    site_arg = None if args.site == "all" else args.site
    sites = _sites_ativos()
    grupos = _grupos_por_tier(sites, site_arg)

    _checar_disco("início do lote")
    manifest_lote = _carregar_manifest_lote()

    n_ok = n_pulado = n_falha = 0
    n_visto = 0
    t0 = time.time()

    for grupo in grupos:
        for site in grupo:
            site_id = site["site_id"]
            for sensor_token in sensores:
                if args.ano == "all":
                    anos = _anos_disponiveis(sensor_token, site_id)
                else:
                    anos = [int(args.ano)]
                for ano in anos:
                    chave = f"{sensor_token}|{site_id}|{ano}"
                    n_visto += 1
                    if n_visto % CHECAGEM_DISCO_PERIODICA == 0:
                        try:
                            _checar_disco(f"checagem periódica em {chave}")
                        except DiscoBaixoError as e:
                            print(f"ABORTADO: {e}", file=sys.stderr)
                            _salvar_manifest_lote(manifest_lote)
                            print(f"[predict] PARADO por disco baixo — {n_ok} ok, {n_pulado} pulado, {n_falha} falha até aqui.")
                            return 1

                    inicio = time.time()
                    try:
                        resultado = classificar_site_ano(sensor_token, site_id, ano, pacote, modelo_path, force=args.force, gerar_png=False)
                        status = "pulado" if resultado.get("_pulado") else "ok"
                        erro = None
                    except Exception as e:  # noqa: BLE001 - 1 item ruim não pode abortar o lote inteiro
                        status = "falha"
                        erro = f"{type(e).__name__}: {e}"
                        print(f"ERRO [{chave}]: {erro}", file=sys.stderr)
                    duracao = time.time() - inicio

                    if status == "ok":
                        n_ok += 1
                    elif status == "pulado":
                        n_pulado += 1
                    else:
                        n_falha += 1

                    manifest_lote["itens"][chave] = {
                        "status": status,
                        "duracao_s": round(duracao, 2),
                        "erro": erro,
                        "atualizado_em": datetime.now(UTC).isoformat(),
                    }
                    if n_visto % 10 == 0 or status == "falha":
                        _salvar_manifest_lote(manifest_lote)
                    decorrido = (time.time() - t0) / 60
                    print(f"[predict] {n_visto} vistos (ok={n_ok} pulado={n_pulado} falha={n_falha}) — {decorrido:.1f} min — último: {chave} -> {status}")

    _salvar_manifest_lote(manifest_lote)
    livre_gb_fim = espaco_livre_gb()
    print(f"\n[predict] CONCLUÍDO — ok={n_ok} pulado={n_pulado} falha={n_falha} | disco livre ao final: {livre_gb_fim:.2f} GB")
    return 1 if n_falha else 0


if __name__ == "__main__":
    sys.exit(main())
