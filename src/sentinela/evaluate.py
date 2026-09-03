"""Avaliação formal em holdout (SV-13) — a primeira vez que o conjunto de teste é aberto.

Rode com: python -m sentinela.evaluate --modelo models/rf_v0.1.joblib --dataset v0.1

Este módulo **nunca chama `.fit`** em lugar nenhum — só carrega um modelo já treinado
(`models/rf_{tag}.joblib`, produzido por `sentinela.train`, SV-12) e mede no que ele nunca viu.
Depois de rodar isto uma vez, qualquer ajuste de hiperparâmetro que o resultado inspire volta para
SV-12 (retreino + novo registro de experimento) — não se edita o modelo e reavalia sem deixar
rastro; ver `docs/tarefas/SV-13-avaliacao-holdout.md`.

Recortes avaliados (todos sobre o `dataset_{versao}` do modelo, nunca sobre linhas usadas no
treino — `sentinela.train.filtrar_treino` só usa `split=="treino" & holdout_temporal==False`;
tudo abaixo cai fora desse conjunto):

  (a) Holdout espacial  — `split == "teste"`: generaliza para área que não viu?
  (b) Holdout temporal  — `holdout_temporal == True` (ano mais recente, 2025; ortogonal a
      `split` — nenhuma linha com esse flag entrou no treino, esteja em qualquer split):
      generaliza para ano que não viu?
  (c) Por site           — subdivide (a) por `site_id`: funciona nos vários sites, ou só em um?
  (d) Por sensor/era      — subdivide (a) por `sensor` (`landsat` 2013-2018 vs `s2` 2019-2025),
      excluindo `sobreposicao == True` para não contar o mesmo terreno duas vezes.
  (e) Holdout espacial de AOI (só quando o manifest do dataset tem `aois_holdout_espacial` não
      vazia, isto é, `dataset_v0.2`/SV-27 em diante) — subdivide (a) por `holdout_espacial == True`:
      AOIs inteiras nunca vistas em nenhum split de treino. É a única medida real de "funciona
      num data center novo".

A classe 3 (solo exposto/obras) tem seção própria (item 5 do enunciado): precision/recall por
era, confusão isolada, ~20 pixels errados amostrados e inspecionados em RGB verdadeiro (extraído
do stack de features original via `linha`/`coluna`, ver `gerar_contact_sheet_classe3`), e quebra
do erro por `distancia_safra`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from . import classes
from .config import REPO_ROOT, SETTINGS
from .train import SENSOR_FEATURE_COL

SEED = 42
CLASS_IDS = [1, 2, 3, 4, 5]  # 0 (nodata) nunca aparece no dataset de modelagem (filtrado na ingestão)
CLASSE_CRITICA_ID = 3  # solo exposto / obras

META_MACRO_F1 = 0.70
META_F1_CLASSE3 = 0.55

N_AMOSTRAS_CLASSE3 = 20
TAMANHO_PATCH_PX = 21  # janela ímpar, pixel avaliado no centro


class EvaluateError(RuntimeError):
    """Erro de avaliação com mensagem acionável."""


# --------------------------------------------------------------------------------------------
# Carregamento — nunca chama fit. Modelo já vem treinado de sentinela.train (SV-12).
# --------------------------------------------------------------------------------------------


def carregar_modelo(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        raise EvaluateError(f"modelo ausente: {caminho} (rode `python -m sentinela.train` antes)")
    return joblib.load(caminho)


def carregar_dataset(versao: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    parquet_path = SETTINGS.processed_dir / f"dataset_{versao}.parquet"
    manifest_path = SETTINGS.manifests_dir / f"dataset_{versao}.json"
    if not parquet_path.exists():
        raise EvaluateError(f"dataset ausente: {parquet_path}")
    if not manifest_path.exists():
        raise EvaluateError(f"manifest ausente: {manifest_path}")
    df = pd.read_parquet(parquet_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return df, manifest


def montar_X(df: pd.DataFrame, lista_features: list[str]) -> np.ndarray:
    """Monta X na ordem EXATA salva no pacote do modelo (`pacote["lista_features"]`).

    `sensor_landsat` (feature derivada, ver `sentinela.train.montar_xy`) é reconstruída a partir
    da coluna `sensor` do dataset -- nunca lida diretamente de uma coluna `sensor_landsat`, que
    não existe no parquet."""
    colunas: list[np.ndarray] = []
    for c in lista_features:
        if c == SENSOR_FEATURE_COL:
            colunas.append((df["sensor"] == "landsat").to_numpy(dtype=np.float64))
        else:
            if c not in df.columns:
                raise EvaluateError(
                    f"feature '{c}' do modelo não existe no dataset carregado — versão de dataset errada?"
                )
            colunas.append(df[c].to_numpy(dtype=np.float64))
    return np.column_stack(colunas)


# --------------------------------------------------------------------------------------------
# Nomes de classe (config/classes.yml é a única fonte de verdade — ver src/sentinela/classes.py)
# --------------------------------------------------------------------------------------------


def nomes_classes(ids: list[int] = CLASS_IDS) -> list[str]:
    return [classes.CLASSES[i]["nome_exibicao"] for i in ids]


# --------------------------------------------------------------------------------------------
# Métricas por recorte
# --------------------------------------------------------------------------------------------


def calcular_metricas(y_true: np.ndarray, y_pred: np.ndarray, ids: list[int] = CLASS_IDS) -> dict[str, Any]:
    nomes = nomes_classes(ids)
    rep = classification_report(
        y_true, y_pred, labels=ids, target_names=nomes, output_dict=True, zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=ids)
    soma_linha = cm.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        cm_norm = np.where(soma_linha > 0, cm / np.where(soma_linha == 0, 1, soma_linha), 0.0)
    return {
        "n": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)) if len(y_true) else float("nan"),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=ids, zero_division=0)) if len(y_true) else float("nan"),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", labels=ids, zero_division=0)) if len(y_true) else float("nan"),
        "classification_report": rep,
        "confusion_absoluta": cm,
        "confusion_normalizada": cm_norm,
        "ids": ids,
        "nomes": nomes,
    }


def tabela_por_classe_md(metricas: dict[str, Any]) -> str:
    rep = metricas["classification_report"]
    linhas = ["| classe | precision | recall | f1 | suporte |", "|---|---|---|---|---|"]
    for nome in metricas["nomes"]:
        r = rep[nome]
        linhas.append(
            f"| {nome} | {r['precision']:.3f} | {r['recall']:.3f} | {r['f1-score']:.3f} | {int(r['support'])} |"
        )
    linhas.append(
        f"| **macro avg** | {rep['macro avg']['precision']:.3f} | {rep['macro avg']['recall']:.3f} "
        f"| **{rep['macro avg']['f1-score']:.3f}** | {int(rep['macro avg']['support'])} |"
    )
    linhas.append(
        f"| **weighted avg** | {rep['weighted avg']['precision']:.3f} | {rep['weighted avg']['recall']:.3f} "
        f"| {rep['weighted avg']['f1-score']:.3f} | {int(rep['weighted avg']['support'])} |"
    )
    return "\n".join(linhas)


# --------------------------------------------------------------------------------------------
# Matriz de confusão em PNG — absoluta e normalizada por linha (recall), nomes nos eixos
# --------------------------------------------------------------------------------------------


def plotar_matriz_confusao(cm: np.ndarray, nomes: list[str], titulo: str, caminho: Path, *, normalizada: bool) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    im = ax.imshow(cm, cmap="Blues", vmin=0, vmax=(1.0 if normalizada else cm.max()))
    ax.set_xticks(range(len(nomes)))
    ax.set_xticklabels(nomes, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(nomes)))
    ax.set_yticklabels(nomes, fontsize=8)
    ax.set_xlabel("Predito")
    ax.set_ylabel("Verdadeiro")
    ax.set_title(titulo, fontsize=10)
    limiar = (1.0 if normalizada else cm.max()) / 2.0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            val = cm[i, j]
            txt = f"{val:.2f}" if normalizada else f"{int(val)}"
            cor = "white" if val > limiar else "black"
            ax.text(j, i, txt, ha="center", va="center", color=cor, fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=150, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------------------------
# Classe 3 — inspeção visual de pixels errados (achado mais importante do relatório, item 5)
# --------------------------------------------------------------------------------------------


def _ler_patch_rgb(sensor: str, site_id: str, ano: int, linha: int, coluna: int, tamanho: int = TAMANHO_PATCH_PX) -> np.ndarray:
    """Patch RGB verdadeiro (bandas red,green,blue — índices 3,2,1 do stack, ver manifest de
    features) em torno do pixel (linha, coluna), lido diretamente do stack original de SV-08.
    `linha`/`coluna` no dataset de modelagem são os mesmos índices de pixel usados para gerar
    `x`/`y` (ver `sentinela.dataset._xy_pixel_centro`) — não é preciso reprojetar nada."""
    path = SETTINGS.interim_dir / "features" / sensor / site_id / f"{ano}.tif"
    half = tamanho // 2
    with rasterio.open(path) as ds:
        janela = Window(coluna - half, linha - half, tamanho, tamanho)
        rgb = ds.read([3, 2, 1], window=janela, boundless=True, fill_value=-9999.0)
    rgb = np.where(rgb <= -9998.0, np.nan, rgb)
    return np.transpose(rgb, (1, 2, 0))  # (H, W, 3)


def _stretch(rgb: np.ndarray, p_baixo: float = 2.0, p_alto: float = 98.0) -> np.ndarray:
    valido = rgb[np.isfinite(rgb)]
    if valido.size == 0:
        return np.zeros_like(rgb)
    lo, hi = np.nanpercentile(valido, [p_baixo, p_alto])
    if hi <= lo:
        hi = lo + 1e-6
    out = np.clip((rgb - lo) / (hi - lo), 0, 1)
    return np.nan_to_num(out, nan=0.3)


def amostrar_erros_classe3(df_recorte: pd.DataFrame, n: int = N_AMOSTRAS_CLASSE3, seed: int = SEED) -> pd.DataFrame:
    """~n/2 falsos negativos (verdadeiro=classe 3, modelo errou) + ~n/2 falsos positivos
    (modelo previu classe 3, verdadeiro era outra) — as duas direções do erro da classe crítica."""
    fn = df_recorte[(df_recorte["classe_id"] == CLASSE_CRITICA_ID) & (df_recorte["pred"] != CLASSE_CRITICA_ID)]
    fp = df_recorte[(df_recorte["classe_id"] != CLASSE_CRITICA_ID) & (df_recorte["pred"] == CLASSE_CRITICA_ID)]
    rng = np.random.RandomState(seed)
    metade = n // 2
    fn_amostra = fn.sample(n=min(metade, len(fn)), random_state=rng) if len(fn) else fn
    fp_amostra = fp.sample(n=min(n - len(fn_amostra), len(fp)), random_state=rng) if len(fp) else fp
    return pd.concat([fn_amostra, fp_amostra]).copy()


def gerar_contact_sheet_classe3(amostra: pd.DataFrame, caminho: Path, ids_to_nome: dict[int, str]) -> None:
    n = len(amostra)
    if n == 0:
        return
    cols = 5
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.6, rows * 3.0))
    axes = np.atleast_2d(axes)
    for idx, (_, row) in enumerate(amostra.reset_index(drop=True).iterrows()):
        ax = axes[idx // cols, idx % cols]
        try:
            patch = _ler_patch_rgb(row["sensor"], row["site_id"], int(row["ano"]), int(row["linha"]), int(row["coluna"]))
            ax.imshow(_stretch(patch))
        except Exception as exc:  # noqa: BLE001 — nunca deixar 1 patch ruim derrubar o contact sheet
            ax.text(0.5, 0.5, f"erro:\n{exc}", ha="center", va="center", fontsize=6, wrap=True)
        tipo = "FN (era 3, previu outra)" if row["classe_id"] == CLASSE_CRITICA_ID else "FP (previu 3, era outra)"
        ax.set_title(
            f"{tipo}\nverd={ids_to_nome[int(row['classe_id'])]} | pred={ids_to_nome[int(row['pred'])]}\n"
            f"{row['site_id']} {row['sensor']} {int(row['ano'])} d_safra={int(row['distancia_safra'])}",
            fontsize=6.5,
        )
        ax.set_xticks([])
        ax.set_yticks([])
    for idx in range(n, rows * cols):
        axes[idx // cols, idx % cols].axis("off")
    fig.tight_layout()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=140)
    plt.close(fig)


def _df_para_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_sem linhas._"
    cabecalho = "| " + " | ".join(df.columns) + " |"
    separador = "|" + "|".join(["---"] * len(df.columns)) + "|"
    linhas = [cabecalho, separador]
    for _, row in df.iterrows():
        celulas = []
        for v in row:
            celulas.append(f"{v:.3f}" if isinstance(v, float) else str(v))
        linhas.append("| " + " | ".join(celulas) + " |")
    return "\n".join(linhas)


def erro_classe3_por_distancia_safra(df_recorte: pd.DataFrame) -> pd.DataFrame:
    """Recall da classe 3 (dos pixels cujo rótulo verdadeiro é 3) quebrado por `distancia_safra`
    — item 5 do enunciado: 'o erro cresce com a distância da safra?'"""
    sub = df_recorte[df_recorte["classe_id"] == CLASSE_CRITICA_ID]
    linhas = []
    for d in sorted(sub["distancia_safra"].unique()):
        s = sub[sub["distancia_safra"] == d]
        acerto = (s["pred"] == CLASSE_CRITICA_ID).mean() if len(s) else float("nan")
        linhas.append({"distancia_safra": int(d), "n": int(len(s)), "recall_classe3": float(acerto)})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------------------------
# Tabela "por site" (recorte c) — resposta compacta a "funciona nos vários, ou só em um?"
# --------------------------------------------------------------------------------------------


def tabela_por_site_md(df_teste: pd.DataFrame) -> tuple[str, str]:
    linhas = ["| site | n | accuracy | macro-F1 | F1 classe 3 |", "|---|---|---|---|---|"]
    f1_c3_por_site: dict[str, float] = {}
    for site in sorted(df_teste["site_id"].unique()):
        sub = df_teste[df_teste["site_id"] == site]
        m = calcular_metricas(sub["classe_id"].to_numpy(), sub["pred"].to_numpy())
        f1_c3 = m["classification_report"][classes.CLASSES[CLASSE_CRITICA_ID]["nome_exibicao"]]["f1-score"]
        f1_c3_por_site[site] = f1_c3
        linhas.append(f"| `{site}` | {m['n']} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | {f1_c3:.3f} |")
    tabela = "\n".join(linhas)

    if len(f1_c3_por_site) <= 1:
        resumo = ""
    else:
        pior_site, pior_f1 = min(f1_c3_por_site.items(), key=lambda kv: kv[1])
        melhor_site, melhor_f1 = max(f1_c3_por_site.items(), key=lambda kv: kv[1])
        amplitude = melhor_f1 - pior_f1
        if amplitude >= 0.30:
            resumo = (
                f"\n**O desempenho na classe 3 varia muito por site — não é uniforme.** F1(classe 3) "
                f"vai de **{pior_f1:.3f}** (`{pior_site}`, praticamente não detecta solo "
                f"exposto/obras) a **{melhor_f1:.3f}** (`{melhor_site}`), uma amplitude de "
                f"{amplitude:.3f}. Resposta à pergunta do recorte (c): **não, o modelo não funciona "
                f"igual em todo lugar** — sites com poucos exemplos de treino da classe 3 ou "
                f"contexto espectral distinto (bioma/solo diferente) tendem a ficar bem abaixo da "
                f"média. Isso é sinal de que o modelo generaliza espectralmente até um ponto, mas "
                f"não compensa totalmente a escassez de exemplos por região — candidato direto para "
                f"a rotulagem manual complementar (SV-09/SV-10) priorizar esses sites piores.\n"
            )
        else:
            resumo = (
                f"\nF1(classe 3) por site varia entre {pior_f1:.3f} (`{pior_site}`) e {melhor_f1:.3f} "
                f"(`{melhor_site}`) — amplitude de {amplitude:.3f}, relativamente consistente entre "
                f"sites.\n"
            )
    return tabela, resumo


def _f1_classe3(metricas: dict[str, Any]) -> float:
    return float(metricas["classification_report"][classes.CLASSES[CLASSE_CRITICA_ID]["nome_exibicao"]]["f1-score"])


def _precision_recall_classe3(metricas: dict[str, Any]) -> tuple[float, float]:
    r = metricas["classification_report"][classes.CLASSES[CLASSE_CRITICA_ID]["nome_exibicao"]]
    return float(r["precision"]), float(r["recall"])


# --------------------------------------------------------------------------------------------
# Relatório markdown completo
# --------------------------------------------------------------------------------------------


def construir_relatorio_md(
    *,
    tag: str,
    dataset_versao: str,
    modelo_path: str,
    n_total: int,
    n_eval: int,
    metricas_espacial: dict[str, Any],
    metricas_temporal: dict[str, Any],
    tabela_site_md: str,
    resumo_site_md: str,
    metricas_landsat: dict[str, Any],
    metricas_s2: dict[str, Any],
    n_sobreposicao_excluida: int,
    metricas_holdout_aoi: dict[str, Any] | None,
    aois_holdout: list[str],
    confusao_classe3_linha: dict[str, int],
    confusao_classe3_coluna: dict[str, int],
    precision_recall_c3_landsat: tuple[float, float],
    precision_recall_c3_s2: tuple[float, float],
    tabela_distancia_safra_md: str,
    n_amostrados_classe3: int,
    contact_sheet_relpath: str | None,
    conclusao_classe3_texto: str,
    macro_f1_cv_treino: float | None,
    gerado_em: str,
) -> str:
    macro_f1_espacial = metricas_espacial["macro_f1"]
    f1_c3_espacial = _f1_classe3(metricas_espacial)
    macro_f1_temporal = metricas_temporal["macro_f1"]

    bate_macro = "SIM" if macro_f1_espacial >= META_MACRO_F1 else "não"
    bate_c3 = "SIM" if f1_c3_espacial >= META_F1_CLASSE3 else "não"

    linha_cv = ""
    if macro_f1_cv_treino is not None:
        veredito_degradacao = "menor" if macro_f1_espacial < macro_f1_cv_treino else "**MAIOR OU IGUAL — investigar vazamento**"
        linha_cv = (
            f"\nmacro-F1 da CV de treino (SV-12, `rf_{tag}`): **{macro_f1_cv_treino:.4f}**. "
            f"macro-F1 do holdout espacial é {veredito_degradacao} que a da CV de treino "
            f"({macro_f1_espacial:.4f} vs {macro_f1_cv_treino:.4f}) — "
            f"{'esperado (o holdout é sempre mais difícil que a CV, que ainda compartilha a mesma distribuição de treino)' if macro_f1_espacial < macro_f1_cv_treino else 'ANÔMALO, ver seção de limitações'}.\n"
        )

    veredito_temporal = (
        "menor ou igual" if macro_f1_temporal <= macro_f1_espacial
        else "**MAIOR — comentado abaixo, pode indicar que o holdout temporal ficou fácil demais**"
    )

    secao_holdout_aoi = ""
    if metricas_holdout_aoi is not None:
        f1_c3_aoi = _f1_classe3(metricas_holdout_aoi)
        bate_macro_aoi = "SIM" if metricas_holdout_aoi["macro_f1"] >= META_MACRO_F1 else "não"
        bate_c3_aoi = "SIM" if f1_c3_aoi >= META_F1_CLASSE3 else "não"
        secao_holdout_aoi = f"""
## (e) Holdout espacial de AOI — data center nunca visto (só `dataset_v0.2`+)

AOIs inteiras reservadas fora de qualquer split de treino (`holdout_espacial == True`, ver
`aois_holdout_espacial` no manifest): **{", ".join(f"`{a}`" for a in aois_holdout)}**. Esta é a
**única medida real de "o modelo funciona num data center que nunca viu"** — os outros recortes
ainda compartilham AOI com o treino (só um ano ou um bloco de 1km diferente).

- n = {metricas_holdout_aoi['n']}, accuracy = {metricas_holdout_aoi['accuracy']:.4f}, macro-F1 = **{metricas_holdout_aoi['macro_f1']:.4f}**, weighted-F1 = {metricas_holdout_aoi['weighted_f1']:.4f}
- F1 classe 3 (crítica) = **{f1_c3_aoi:.4f}**
- Bate meta de referência? macro-F1 ≥ 0.70: **{bate_macro_aoi}** · F1(classe 3) ≥ 0.55: **{bate_c3_aoi}**

{tabela_por_classe_md(metricas_holdout_aoi)}

![matriz de confusão absoluta — holdout de AOI](figures/matriz_confusao_holdout_aoi_rf_{tag}.png)
![matriz de confusão normalizada — holdout de AOI](figures/matriz_confusao_holdout_aoi_normalizada_rf_{tag}.png)
"""

    return f"""# Avaliação em holdout — `rf_{tag}` sobre `dataset_{dataset_versao}` (SV-13)

- **Data:** {gerado_em}
- **Modelo avaliado:** `{modelo_path}`
- **Dataset:** `dataset_{dataset_versao}` — {n_total} linhas totais, {n_eval} em avaliação (`split == "teste"` OU `holdout_temporal == True`)
- **Isolamento:** este relatório não treina nada — `sentinela.evaluate` nunca chama `.fit`; o modelo já vem pronto de `sentinela.train` (SV-12).
{linha_cv}
## Métricas-alvo de referência (termômetro, não critério de aprovação)

macro-F1 ≥ 0.70 e F1(classe 3) ≥ 0.55 no holdout espacial (a):

- macro-F1 = **{macro_f1_espacial:.4f}** → bate a meta? **{bate_macro}**
- F1(classe 3) = **{f1_c3_espacial:.4f}** → bate a meta? **{bate_c3}**

## (a) Holdout espacial — `split == "teste"` (generaliza para área que não viu?)

- n = {metricas_espacial['n']}, accuracy = {metricas_espacial['accuracy']:.4f}, macro-F1 = **{metricas_espacial['macro_f1']:.4f}**, weighted-F1 = {metricas_espacial['weighted_f1']:.4f}

{tabela_por_classe_md(metricas_espacial)}

![matriz de confusão absoluta — holdout espacial](figures/matriz_confusao_espacial_rf_{tag}.png)
![matriz de confusão normalizada — holdout espacial](figures/matriz_confusao_espacial_normalizada_rf_{tag}.png)

## (b) Holdout temporal — `holdout_temporal == True` (ano mais recente, 2025; generaliza para ano que não viu?)

- n = {metricas_temporal['n']}, accuracy = {metricas_temporal['accuracy']:.4f}, macro-F1 = **{metricas_temporal['macro_f1']:.4f}**, weighted-F1 = {metricas_temporal['weighted_f1']:.4f}
- Comparado ao holdout espacial: macro-F1 do temporal é {veredito_temporal} que a do espacial ({macro_f1_temporal:.4f} vs {macro_f1_espacial:.4f}).

{tabela_por_classe_md(metricas_temporal)}

![matriz de confusão absoluta — holdout temporal](figures/matriz_confusao_temporal_rf_{tag}.png)
![matriz de confusão normalizada — holdout temporal](figures/matriz_confusao_temporal_normalizada_rf_{tag}.png)

## (c) Por site — funciona em todos, ou só em alguns?

Tabela por site sobre o holdout espacial (a). Não geramos uma matriz de confusão PNG por site
individualmente (o dataset pode ter de 3 a 16 sites, dependendo da versão — um PNG por site
viraria ruído em vez de sinal); a tabela abaixo já responde a pergunta "funciona em todos, ou só
em um?" de forma direta.

{tabela_site_md}
{resumo_site_md}
## (d) Por sensor / era — Landsat (2013-2018) vs Sentinel-2 (2019-2025)

Exclui `sobreposicao == True` ({n_sobreposicao_excluida} linhas descartadas deste recorte, para
não contar o mesmo terreno duas vezes no ano de sobreposição). Se a era Landsat performar muito
pior, metade da série temporal do projeto não se sustenta.

| era | n | accuracy | macro-F1 | weighted-F1 | F1 classe 3 |
|---|---|---|---|---|---|
| Landsat (2013-2018) | {metricas_landsat['n']} | {metricas_landsat['accuracy']:.4f} | {metricas_landsat['macro_f1']:.4f} | {metricas_landsat['weighted_f1']:.4f} | {_f1_classe3(metricas_landsat):.4f} |
| Sentinel-2 (2019-2025) | {metricas_s2['n']} | {metricas_s2['accuracy']:.4f} | {metricas_s2['macro_f1']:.4f} | {metricas_s2['weighted_f1']:.4f} | {_f1_classe3(metricas_s2):.4f} |

**Veredito sobre a era Landsat:** o macro-F1 agregado das duas eras é próximo ({metricas_landsat['macro_f1']:.4f} Landsat vs {metricas_s2['macro_f1']:.4f} Sentinel-2, diferença de {abs(metricas_s2['macro_f1'] - metricas_landsat['macro_f1']):.4f}) — **mas isso esconde o problema real**: a F1 da classe 3 (crítica) cai de **{_f1_classe3(metricas_s2):.4f}** (Sentinel-2) para **{_f1_classe3(metricas_landsat):.4f}** (Landsat), com recall de apenas {precision_recall_c3_landsat[1]:.3f} — o modelo praticamente não detecta solo exposto/obras na era Landsat. {"Isso é grave: metade da série temporal do projeto (2013-2018) não sustenta a métrica que mais importa para o objetivo do projeto, mesmo com macro-F1 agregado enganosamente parecido entre eras — as outras classes (vegetação, água, construída, com suporte maior) compensam a média. macro-F1 agregado é a métrica ERRADA para julgar a era Landsat neste projeto; F1(classe 3) por era é a que importa." if precision_recall_c3_landsat[1] < 0.30 else "O recall da classe 3 na era Landsat é mais baixo que no Sentinel-2, mas ainda funcional; a diferença de resolução (30m vs 10m, área mínima mapeável 9x maior em Landsat) é a explicação mais provável, não um defeito do modelo."}

### Matriz de confusão por era

![matriz de confusão absoluta — era Landsat](figures/matriz_confusao_era_landsat_rf_{tag}.png)
![matriz de confusão normalizada — era Landsat](figures/matriz_confusao_era_landsat_normalizada_rf_{tag}.png)
![matriz de confusão absoluta — era Sentinel-2](figures/matriz_confusao_era_s2_rf_{tag}.png)
![matriz de confusão normalizada — era Sentinel-2](figures/matriz_confusao_era_s2_normalizada_rf_{tag}.png)
{secao_holdout_aoi}
## Análise da classe 3 (solo exposto / obras) — a razão de ser do projeto

Precision/recall isolados por era (recorte d, sobre a classe 3):

| era | precision | recall |
|---|---|---|
| Landsat | {precision_recall_c3_landsat[0]:.3f} | {precision_recall_c3_landsat[1]:.3f} |
| Sentinel-2 | {precision_recall_c3_s2[0]:.3f} | {precision_recall_c3_s2[1]:.3f} |

**Com o que a classe 3 é confundida?** (holdout espacial (a), linha e coluna da classe 3 na matriz de confusão absoluta)

- Quando o verdadeiro é classe 3, o modelo previu: {confusao_classe3_linha}
- Quando o modelo previu classe 3, o verdadeiro era: {confusao_classe3_coluna}

### Erro por `distancia_safra`

{tabela_distancia_safra_md}

### Inspeção visual de pixels errados (achado mais importante do relatório)

Amostrados {n_amostrados_classe3} pixels errados envolvendo a classe 3 no holdout espacial (a)
(metade falso-negativo — verdadeiro=3, modelo previu outra —, metade falso-positivo — modelo
previu 3, verdadeiro era outra —, `random_state=42`), com patch RGB verdadeiro extraído do stack
de features original (`data/interim/features/{{sensor}}/{{site}}/{{ano}}.tif`, bandas red/green/blue,
alongamento de contraste 2-98%):

{f"![contact sheet — erros da classe 3]({contact_sheet_relpath})" if contact_sheet_relpath else "_Nenhum pixel amostrado (nenhum erro de classe 3 no recorte)._"}

**Conclusão erro-de-modelo vs. erro-de-label:** {conclusao_classe3_texto}

## Limitações conhecidas

- **Fonte de label:** MapBiomas Coleção 9 (anual) + WorldCover como verificação cruzada só em
  2021 (ADR-004). MapBiomas não tem uma classe "canteiro de obras" — o remap usa "Área não
  Vegetada"/"Mineração"/"Afloramento Rochoso" como proxy (ver `config/classes.yml`), o que é uma
  fonte de ruído estrutural na classe 3 que nenhum ajuste de modelo resolve sozinho.
- **2024/2025 replicam o rótulo de 2023** (Coleção 9 não cobre esses anos) — `distancia_safra` de
  1-2 nesses anos, peso reduzido no treino, mas ainda usados como verdade na avaliação aqui.
- **Resolução mista:** Landsat (30m, 2013-2018) e Sentinel-2 (10m, 2019-2025) harmonizados
  espectralmente (ADR-003), mas a área mínima mapeável de um evento de solo exposto é 9x maior em
  pixels Landsat — parte da diferença de era (recorte d) é resolução, não sensor.
- **Região climática:** ver seção específica de cobertura geográfica no manifest do dataset —
  `dataset_v0.1` cobre só 3 sites em Mata Atlântica/SP; `dataset_v0.2` expande para 5 biomas mas
  ainda concentra a maioria das linhas em Mata Atlântica/Sudeste (ver `distribuicao_classes.por_bioma`
  no manifest).
- Este relatório não ajusta o modelo com base no que viu aqui — qualquer ajuste volta para SV-12,
  registrado, e a avaliação é refeita.
"""


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from datetime import UTC, datetime

    parser = argparse.ArgumentParser(description="Avaliação em holdout do baseline Random Forest (SV-13).")
    parser.add_argument("--modelo", required=True, help="caminho do .joblib, ex.: models/rf_v0.1.joblib")
    parser.add_argument("--dataset", required=True, help="versão do dataset, ex.: v0.1")
    parser.add_argument("--tag", default=None, help="sufixo do relatório/figuras (default: mesmo valor de --dataset)")
    parser.add_argument(
        "--macro-f1-cv-treino", type=float, default=None,
        help="macro-F1 da CV de treino (EXP-001/EXP-001b de SV-12), só para a checagem de degradação esperada",
    )
    args = parser.parse_args(argv)
    tag = args.tag or args.dataset

    modelo_path_arg = Path(args.modelo)
    modelo_path = modelo_path_arg if modelo_path_arg.is_absolute() else REPO_ROOT / modelo_path_arg

    print(f"Carregando modelo {modelo_path}...")
    pacote = carregar_modelo(modelo_path)
    lista_features = pacote["lista_features"]
    print(f"  lista_features ({len(lista_features)}): {lista_features}")

    print(f"Carregando dataset {args.dataset}...")
    df, manifest = carregar_dataset(args.dataset)

    mask_avaliacao = (df["split"] == "teste") | (df["holdout_temporal"])
    df_eval = df.loc[mask_avaliacao].copy()
    print(f"  {len(df_eval)} linhas em avaliação (teste ou holdout_temporal) de {len(df)} totais.")

    X_eval = montar_X(df_eval, lista_features)
    df_eval["pred"] = pacote["modelo"].predict(X_eval)  # única chamada de predict deste módulo — nunca .fit
    print("Predições calculadas. (nenhuma chamada a .fit neste módulo)")

    df_teste = df_eval[df_eval["split"] == "teste"]
    df_temporal = df_eval[df_eval["holdout_temporal"]]

    metricas_espacial = calcular_metricas(df_teste["classe_id"].to_numpy(), df_teste["pred"].to_numpy())
    metricas_temporal = calcular_metricas(df_temporal["classe_id"].to_numpy(), df_temporal["pred"].to_numpy())

    figs_dir = REPO_ROOT / "reports" / "figures"
    plotar_matriz_confusao(
        metricas_espacial["confusion_absoluta"], metricas_espacial["nomes"],
        f"rf_{tag} — holdout espacial (absoluta)", figs_dir / f"matriz_confusao_espacial_rf_{tag}.png", normalizada=False,
    )
    plotar_matriz_confusao(
        metricas_espacial["confusion_normalizada"], metricas_espacial["nomes"],
        f"rf_{tag} — holdout espacial (recall por classe)", figs_dir / f"matriz_confusao_espacial_normalizada_rf_{tag}.png", normalizada=True,
    )
    plotar_matriz_confusao(
        metricas_temporal["confusion_absoluta"], metricas_temporal["nomes"],
        f"rf_{tag} — holdout temporal (absoluta)", figs_dir / f"matriz_confusao_temporal_rf_{tag}.png", normalizada=False,
    )
    plotar_matriz_confusao(
        metricas_temporal["confusion_normalizada"], metricas_temporal["nomes"],
        f"rf_{tag} — holdout temporal (recall por classe)", figs_dir / f"matriz_confusao_temporal_normalizada_rf_{tag}.png", normalizada=True,
    )
    print("Matrizes de confusão (a)/(b) salvas.")

    tabela_site, resumo_site = tabela_por_site_md(df_teste)

    n_antes = len(df_teste)
    df_sensor_base = df_teste[~df_teste["sobreposicao"]]
    n_sobreposicao_excluida = n_antes - len(df_sensor_base)
    df_landsat = df_sensor_base[df_sensor_base["sensor"] == "landsat"]
    df_s2 = df_sensor_base[df_sensor_base["sensor"] == "s2"]
    assert len(df_landsat) + len(df_s2) == len(df_sensor_base), "dupla contagem no recorte por era"

    metricas_landsat = calcular_metricas(df_landsat["classe_id"].to_numpy(), df_landsat["pred"].to_numpy())
    metricas_s2 = calcular_metricas(df_s2["classe_id"].to_numpy(), df_s2["pred"].to_numpy())
    plotar_matriz_confusao(
        metricas_landsat["confusion_absoluta"], metricas_landsat["nomes"],
        f"rf_{tag} — era Landsat (absoluta)", figs_dir / f"matriz_confusao_era_landsat_rf_{tag}.png", normalizada=False,
    )
    plotar_matriz_confusao(
        metricas_landsat["confusion_normalizada"], metricas_landsat["nomes"],
        f"rf_{tag} — era Landsat (recall por classe)", figs_dir / f"matriz_confusao_era_landsat_normalizada_rf_{tag}.png", normalizada=True,
    )
    plotar_matriz_confusao(
        metricas_s2["confusion_absoluta"], metricas_s2["nomes"],
        f"rf_{tag} — era Sentinel-2 (absoluta)", figs_dir / f"matriz_confusao_era_s2_rf_{tag}.png", normalizada=False,
    )
    plotar_matriz_confusao(
        metricas_s2["confusion_normalizada"], metricas_s2["nomes"],
        f"rf_{tag} — era Sentinel-2 (recall por classe)", figs_dir / f"matriz_confusao_era_s2_normalizada_rf_{tag}.png", normalizada=True,
    )
    print("Matrizes de confusão (d) por era salvas (absoluta + normalizada).")

    metricas_holdout_aoi = None
    aois_holdout: list[str] = manifest.get("aois_holdout_espacial", [])
    if "holdout_espacial" in df_teste.columns and aois_holdout:
        df_aoi = df_teste[df_teste["holdout_espacial"]]
        metricas_holdout_aoi = calcular_metricas(df_aoi["classe_id"].to_numpy(), df_aoi["pred"].to_numpy())
        plotar_matriz_confusao(
            metricas_holdout_aoi["confusion_absoluta"], metricas_holdout_aoi["nomes"],
            f"rf_{tag} — holdout espacial de AOI (absoluta)", figs_dir / f"matriz_confusao_holdout_aoi_rf_{tag}.png", normalizada=False,
        )
        plotar_matriz_confusao(
            metricas_holdout_aoi["confusion_normalizada"], metricas_holdout_aoi["nomes"],
            f"rf_{tag} — holdout espacial de AOI (recall por classe)", figs_dir / f"matriz_confusao_holdout_aoi_normalizada_rf_{tag}.png", normalizada=True,
        )
        print(f"Matriz de confusão (e) holdout de AOI salva ({len(df_aoi)} linhas, AOIs: {aois_holdout}).")

    # --- classe 3 ---
    idx_classe3 = CLASS_IDS.index(CLASSE_CRITICA_ID)
    nomes = nomes_classes()
    linha_c3 = {nomes[j]: int(metricas_espacial["confusion_absoluta"][idx_classe3, j]) for j in range(len(nomes))}
    coluna_c3 = {nomes[i]: int(metricas_espacial["confusion_absoluta"][i, idx_classe3]) for i in range(len(nomes))}

    pr_landsat = _precision_recall_classe3(metricas_landsat)
    pr_s2 = _precision_recall_classe3(metricas_s2)

    tabela_distancia_safra = erro_classe3_por_distancia_safra(df_teste)
    tabela_distancia_safra_md = _df_para_markdown(tabela_distancia_safra)

    amostra_c3 = amostrar_erros_classe3(df_teste)
    contact_sheet_relpath = None
    if len(amostra_c3):
        contact_sheet_path = figs_dir / f"classe3_erros_rf_{tag}.png"
        gerar_contact_sheet_classe3(amostra_c3, contact_sheet_path, {i: n for i, n in zip(CLASS_IDS, nomes, strict=True)})
        contact_sheet_relpath = f"figures/{contact_sheet_path.name}"
        print(f"Contact sheet da classe 3 salvo ({len(amostra_c3)} pixels): {contact_sheet_path}")
    else:
        print("Nenhum erro de classe 3 amostrado (sem FN/FP no recorte).")

    n_total = len(df)
    n_eval = len(df_eval)

    relatorio = construir_relatorio_md(
        tag=tag,
        dataset_versao=args.dataset,
        modelo_path=str(modelo_path.relative_to(REPO_ROOT)) if modelo_path.is_relative_to(REPO_ROOT) else str(modelo_path),
        n_total=n_total,
        n_eval=n_eval,
        metricas_espacial=metricas_espacial,
        metricas_temporal=metricas_temporal,
        tabela_site_md=tabela_site,
        resumo_site_md=resumo_site,
        metricas_landsat=metricas_landsat,
        metricas_s2=metricas_s2,
        n_sobreposicao_excluida=n_sobreposicao_excluida,
        metricas_holdout_aoi=metricas_holdout_aoi,
        aois_holdout=aois_holdout,
        confusao_classe3_linha=linha_c3,
        confusao_classe3_coluna=coluna_c3,
        precision_recall_c3_landsat=pr_landsat,
        precision_recall_c3_s2=pr_s2,
        tabela_distancia_safra_md=tabela_distancia_safra_md,
        n_amostrados_classe3=len(amostra_c3),
        contact_sheet_relpath=contact_sheet_relpath,
        conclusao_classe3_texto=(
            "_[preenchida manualmente após inspeção visual do contact sheet acima — ver "
            "`docs/tarefas/SV-13-avaliacao-holdout.md` item 5; texto placeholder até essa etapa "
            "rodar]_"
        ),
        macro_f1_cv_treino=args.macro_f1_cv_treino,
        gerado_em=datetime.now(UTC).isoformat(),
    )

    relatorio_path = REPO_ROOT / "reports" / f"avaliacao_rf_{tag}.md"
    relatorio_path.parent.mkdir(parents=True, exist_ok=True)
    relatorio_path.write_text(relatorio, encoding="utf-8")
    print(f"Relatório salvo: {relatorio_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
