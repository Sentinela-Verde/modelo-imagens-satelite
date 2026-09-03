"""Treino do baseline Random Forest (SV-12) + registro de experimento.

Rode com: python -m sentinela.train --dataset v0.1 --modelo rf --tag v0.1

Contexto: `CLAUDE.md` fixa Random Forest / scikit-learn como baseline da V1 (decisão D-01 — a V1
não depende de Deep Learning; essa trilha tem ambiente e sprint próprios). Este módulo treina
**apenas** sobre as linhas de `data/processed/dataset_{dataset}.parquet` com `split == "treino"`
e `holdout_temporal == False` — o conjunto de teste nunca é tocado aqui (fica para SV-13, e nem
para "dar uma olhada"). Valida por `GroupKFold(n_splits=5)` agrupando por `bloco_id` — nunca
`KFold`/`StratifiedKFold` simples, que reintroduziria o vazamento espacial que SV-11 fechou.

Decisão sobre a coluna `sensor` (série multi-sensor, ver CLAUDE.md): treinamos duas variantes e
comparamos pela CV, no treino, nunca no teste --
  (i)  **sem** `sensor` como feature — obriga o modelo a depender só do espectro harmonizado.
       Variante preferida: generaliza para sensores futuros e não pode "trapacear" usando a
       época (todo Landsat é <= 2018).
  (ii) **com** `sensor` como feature binária (`sensor_landsat`) — permite ao modelo compensar
       resíduo de harmonização, ao custo de aprender esse atalho temporal. Só é adotada se a
       diferença de macro-F1 for relevante (ver `DIFERENCA_SENSOR_RELEVANTE` abaixo).

Nunca incluímos `ano`, `x`, `y`, `linha`, `coluna`, `regiao`, `bioma`, `uf`, `tier`, `fase` como
feature — `COLUNAS_PROIBIDAS_COMO_FEATURE` é checada contra o manifest antes de qualquer treino.
`lista_features` do manifest (`data/manifests/dataset_{versao}.json`) é a única fonte de verdade
do que entra no modelo — nunca hardcodada aqui.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

from .config import REPO_ROOT, SETTINGS

# --------------------------------------------------------------------------------------------
# Contrato / constantes
# --------------------------------------------------------------------------------------------

N_SPLITS_CV = 5
SEED = 42

RF_PARAMS_BASE: dict[str, Any] = {
    "n_estimators": 300,
    "min_samples_leaf": 5,
    "max_features": "sqrt",
    "class_weight": "balanced_subsample",
    "n_jobs": -1,
    "random_state": SEED,
}

# Nunca podem virar feature — mesmo que apareçam soltas em algum DataFrame intermediário. Ver
# nota de revisão 2 do enunciado de SV-12: aprender geografia/tempo em vez de espectro quebra na
# primeira AOI/ano fora da amostra de treino.
COLUNAS_PROIBIDAS_COMO_FEATURE = {
    "ano", "x", "y", "linha", "coluna", "regiao", "bioma", "uf", "tier", "fase",
    "site_id", "bloco_id", "split", "holdout_temporal", "classe_id", "resolucao_m",
    "sobreposicao", "distancia_safra", "peso_label",
}

SENSOR_FEATURE_COL = "sensor_landsat"  # 1.0 se sensor == "landsat", 0.0 se "s2"

# Limiar prático para adotar a variante com `sensor`: só vale aprender o atalho de época se o
# ganho de macro-F1 for claramente maior que o ruído entre folds do GroupKFold.
DIFERENCA_SENSOR_RELEVANTE = 0.01


class TrainError(RuntimeError):
    """Erro de treino com mensagem acionável."""


# --------------------------------------------------------------------------------------------
# Carregamento + isolamento do teste (cenário de teste 1 do enunciado)
# --------------------------------------------------------------------------------------------


def carregar_dataset(versao: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    parquet_path = SETTINGS.processed_dir / f"dataset_{versao}.parquet"
    manifest_path = SETTINGS.manifests_dir / f"dataset_{versao}.json"
    if not parquet_path.exists():
        raise TrainError(f"dataset ausente: {parquet_path} (rode `python -m sentinela.dataset` antes)")
    if not manifest_path.exists():
        raise TrainError(f"manifest ausente: {manifest_path}")
    df = pd.read_parquet(parquet_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    lista_features = manifest["lista_features"]
    proibidas_presentes = COLUNAS_PROIBIDAS_COMO_FEATURE & set(lista_features)
    if proibidas_presentes:
        raise TrainError(
            f"lista_features do manifest inclui coluna(s) proibida(s): {proibidas_presentes} — "
            "isso vazaria geografia/tempo/localização para o modelo. Corrija SV-11 antes de treinar."
        )
    return df, manifest


def filtrar_treino(df: pd.DataFrame) -> pd.DataFrame:
    """Isola as linhas de treino desta tarefa: `split == 'treino'` E `holdout_temporal == False`.

    Critério de aceite de SV-12: "o treino usou só split == treino (assertion no código, não
    confiança)". As asserções abaixo falham alto e claro se qualquer linha de teste vazar para
    cá — este módulo nunca constrói uma variável com linhas de `split == 'teste'` em nenhum outro
    ponto do arquivo, então este é o único portão a proteger."""
    mask = (df["split"] == "treino") & (~df["holdout_temporal"])
    df_treino = df.loc[mask].copy()
    if df_treino.empty:
        raise TrainError("nenhuma linha de treino após o filtro split=='treino' & holdout_temporal==False")
    assert (df_treino["split"] == "treino").all(), "vazamento: linha fora de split=='treino' em df_treino"
    assert not df_treino["holdout_temporal"].any(), "vazamento: linha de holdout_temporal em df_treino"
    assert "teste" not in set(df_treino["split"].unique()), "vazamento: split=='teste' leu no treino"
    return df_treino


# --------------------------------------------------------------------------------------------
# Montagem de X/y/groups — as duas variantes (item 4b do enunciado)
# --------------------------------------------------------------------------------------------


def montar_xy(
    df_treino: pd.DataFrame, lista_features: list[str], *, incluir_sensor: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Monta X (na ordem exata de `lista_features` [+ sensor, se pedido]), y e groups (bloco_id).

    `incluir_sensor=True` adiciona uma coluna binária `sensor_landsat` (1.0 Landsat, 0.0 S2) —
    nunca a string bruta: `RandomForestClassifier` do scikit-learn não faz split categórico
    nativo (isso é só do `HistGradientBoosting`)."""
    feature_names = list(lista_features)
    colunas: list[np.ndarray] = [df_treino[c].to_numpy(dtype=np.float64) for c in lista_features]
    if incluir_sensor:
        sensor_bin = (df_treino["sensor"] == "landsat").to_numpy(dtype=np.float64)
        colunas.append(sensor_bin)
        feature_names.append(SENSOR_FEATURE_COL)
    X = np.column_stack(colunas)
    y = df_treino["classe_id"].to_numpy()
    groups = df_treino["bloco_id"].to_numpy()
    return X, y, groups, feature_names


# --------------------------------------------------------------------------------------------
# CV honesta — GroupKFold por bloco_id (nunca KFold/StratifiedKFold simples)
# --------------------------------------------------------------------------------------------


def cv_macro_f1(
    modelo_base: Any,
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    n_splits: int = N_SPLITS_CV,
    *,
    coletar_importancias: bool = False,
) -> dict[str, Any]:
    """`GroupKFold(n_splits)` sobre `groups` (bloco_id) — cada fold treina um clone fresco de
    `modelo_base` (mesmos hiperparâmetros, sem estado vazado entre folds) e mede macro-F1 no
    fold de validação, que nunca compartilha bloco_id com o fold de treino.

    `coletar_importancias=True` também acumula `feature_importances_` de cada fold (médias no
    final) — usado só como referência para a variante NÃO adotada no relatório, evitando um fit
    extra no dataset inteiro só para reportar importância comparativa."""
    gkf = GroupKFold(n_splits=n_splits)
    fold_scores: list[float] = []
    importancias_por_fold: list[np.ndarray] = []
    t0 = time.time()
    for fold_idx, (idx_treino, idx_val) in enumerate(gkf.split(X, y, groups)):
        modelo_fold = clone(modelo_base)
        modelo_fold.fit(X[idx_treino], y[idx_treino])
        pred = modelo_fold.predict(X[idx_val])
        score = f1_score(y[idx_val], pred, average="macro", zero_division=0)
        fold_scores.append(float(score))
        if coletar_importancias:
            importancias_por_fold.append(modelo_fold.feature_importances_)
        print(
            f"    fold {fold_idx + 1}/{n_splits}: macro-F1={score:.4f} "
            f"(n_treino={len(idx_treino)}, n_val={len(idx_val)})"
        )
    tempo_total = time.time() - t0
    resultado: dict[str, Any] = {
        "fold_scores": fold_scores,
        "media": float(np.mean(fold_scores)),
        "desvio": float(np.std(fold_scores)),
        "tempo_total_s": round(tempo_total, 1),
    }
    if coletar_importancias:
        resultado["importancias_media"] = np.mean(importancias_por_fold, axis=0).tolist()
    return resultado


# --------------------------------------------------------------------------------------------
# Importância de features (cenário de teste 5 — sanidade: nunca localização/tempo no topo)
# --------------------------------------------------------------------------------------------


def importancias_ordenadas(modelo: RandomForestClassifier, feature_names: list[str]) -> list[tuple[str, float]]:
    pares = list(zip(feature_names, modelo.feature_importances_.tolist(), strict=True))
    return sorted(pares, key=lambda p: p[1], reverse=True)


# --------------------------------------------------------------------------------------------
# Empacotamento do modelo — nunca salvar só o estimador solto (SV-14 depende da ordem das colunas)
# --------------------------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - git ausente/indisponível não pode derrubar o treino
        return "desconhecido"


def _sha256_arquivo(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def montar_pacote_modelo(
    modelo: RandomForestClassifier, feature_names: list[str], versao_dataset: str, seed: int
) -> dict[str, Any]:
    return {
        "modelo": modelo,
        "lista_features": feature_names,
        "versao_dataset": versao_dataset,
        "seed": seed,
        "sklearn_version": sklearn.__version__,
        "git_sha": _git_sha(),
        "classes_": modelo.classes_.tolist(),
    }


def salvar_modelo(pacote: dict[str, Any], tag: str) -> tuple[Path, Path]:
    models_dir = REPO_ROOT / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib_path = models_dir / f"rf_{tag}.joblib"
    joblib.dump(pacote, joblib_path)
    sha256 = _sha256_arquivo(joblib_path)
    sha_path = models_dir / f"rf_{tag}.sha256"
    sha_path.write_text(f"{sha256}  {joblib_path.name}\n", encoding="utf-8")
    return joblib_path, sha_path


# --------------------------------------------------------------------------------------------
# Relatório de experimento (EXP-001) — o que permite reproduzir o número um mês depois
# --------------------------------------------------------------------------------------------


def _fmt_importancias(pares: list[tuple[str, float]]) -> str:
    linhas = ["| # | feature | importância |", "|---|---|---|"]
    for i, (nome, imp) in enumerate(pares, start=1):
        linhas.append(f"| {i} | `{nome}` | {imp:.4f} |")
    return "\n".join(linhas)


def _fmt_fold_scores(resultado: dict[str, Any]) -> str:
    scores = ", ".join(f"{s:.4f}" for s in resultado["fold_scores"])
    return f"[{scores}] -> média={resultado['media']:.4f} ± desvio={resultado['desvio']:.4f}"


def construir_relatorio_md(
    *,
    dataset_versao: str,
    dataset_sha256: str,
    git_sha: str,
    rf_params: dict[str, Any],
    variante_adotada: str,
    resultado_dummy: dict[str, Any],
    resultado_rf_sem_sensor: dict[str, Any],
    resultado_rf_com_sensor: dict[str, Any],
    importancias_sem_sensor: list[tuple[str, float]],
    importancias_com_sensor: list[tuple[str, float]],
    origem_importancia_sem_sensor: str,
    origem_importancia_com_sensor: str,
    tempo_treino_final_s: float,
    n_linhas_treino: int,
    n_blocos_treino: int,
    determinismo_ok: bool,
    joblib_sha256: str,
    gerado_em: str,
) -> str:
    diferenca = resultado_rf_com_sensor["media"] - resultado_rf_sem_sensor["media"]
    ganho_dummy = resultado_rf_sem_sensor["media"] - resultado_dummy["media"]

    return f"""# EXP-001 — Baseline Random Forest (SV-12)

- **Data:** {gerado_em}
- **git sha:** `{git_sha}`
- **Dataset:** `dataset_{dataset_versao}` — sha256 `{dataset_sha256}`
- **Linhas de treino usadas:** {n_linhas_treino} (`split == "treino"` E `holdout_temporal == False`)
- **Blocos de treino (bloco_id únicos):** {n_blocos_treino}
- **Modelo salvo:** `models/rf_{dataset_versao}.joblib` — sha256 `{joblib_sha256}`

## Hiperparâmetros finais

```
RandomForestClassifier(
    n_estimators={rf_params["n_estimators"]},
    min_samples_leaf={rf_params["min_samples_leaf"]},
    max_features="{rf_params["max_features"]}",
    class_weight="{rf_params["class_weight"]}",
    n_jobs=-1,
    random_state={rf_params["random_state"]},
)
```

## Espaço de busca testado

Nenhum. Cronometramos um fit único antes de decidir ({n_linhas_treino} linhas, {len(importancias_sem_sensor)}
features -> fit final de referência registrado abaixo em {tempo_treino_final_s:.1f}s com
`n_estimators=300`). Uma busca pequena como sugerida no enunciado (`min_samples_leaf ∈
{{1,5,15}}` x `n_estimators ∈ {{200,500}}` = 6 combinações, cada uma com `GroupKFold(5)`) custaria
várias vezes o tempo de uma CV única (ver "tempo total da CV" nas duas variantes abaixo), sem
garantia de ganho relevante sobre a configuração de partida. O próprio enunciado autoriza usar a
configuração inicial "se não sobrar tempo — ela é razoável", e foi essa a decisão tomada aqui.
Fica registrado como candidato de follow-up (não bloqueante para o baseline).

## Piso de comparação: DummyClassifier

`DummyClassifier(strategy="stratified", random_state=42)`, mesmo `GroupKFold(5)` por `bloco_id`:

- macro-F1 por fold: {_fmt_fold_scores(resultado_dummy)}

## Variante (i) — RandomForest SEM `sensor` como feature (adotada nesta rodada: {"SIM" if variante_adotada == "sem_sensor" else "não"})

- macro-F1 por fold: {_fmt_fold_scores(resultado_rf_sem_sensor)}
- tempo total da CV (5 folds): {resultado_rf_sem_sensor["tempo_total_s"]}s
- ganho sobre o Dummy: {ganho_dummy:+.4f} de macro-F1

### Importância de features (ordenada, variante sem sensor)

_Fonte: {origem_importancia_sem_sensor}._

{_fmt_importancias(importancias_sem_sensor)}

## Variante (ii) — RandomForest COM `sensor` como feature binária (adotada nesta rodada: {"SIM" if variante_adotada == "com_sensor" else "não"})

- macro-F1 por fold: {_fmt_fold_scores(resultado_rf_com_sensor)}
- tempo total da CV (5 folds): {resultado_rf_com_sensor["tempo_total_s"]}s

### Importância de features (ordenada, variante com sensor)

_Fonte: {origem_importancia_com_sensor}._

{_fmt_importancias(importancias_com_sensor)}

## Comparação das variantes e decisão

Diferença de macro-F1 (com_sensor − sem_sensor) = **{diferenca:+.4f}**.
Limiar de relevância adotado: {DIFERENCA_SENSOR_RELEVANTE:.2f} (≈1 ponto de macro-F1) — abaixo
disso, o ruído entre folds do `GroupKFold` não permite afirmar que `sensor` ajuda de verdade, e o
custo de introduzir uma dependência de época (SV-13/SV-20 precisam saber disso ao interpretar a
série) não se paga.

**Variante adotada: `{variante_adotada}`.** {"O ganho da variante com sensor superou o limiar de relevância, então o modelo final treina com sensor_landsat como feature binária — SV-13 e SV-20 devem tratar a série como tendo uma dependência de época residual." if variante_adotada == "com_sensor" else "A diferença não superou o limiar de relevância, então o modelo final NÃO usa sensor como feature — depende só do espectro harmonizado, e deve generalizar melhor para sensores futuros sem aprender o atalho temporal (todo Landsat é <= 2018)."}

## Tempo de treino final

Refit no treino inteiro ({n_linhas_treino} linhas), configuração acima: **{tempo_treino_final_s:.1f}s**.

## Determinismo

Dois treinos com a mesma seed (42) sobre o mesmo conjunto de treino produziram predições
idênticas em um lote fixo de 1.000 linhas do treino: **{"sim" if determinismo_ok else "NÃO — investigar"}**.

## O que se esperava vs. o que aconteceu

Esperava-se que BSI (Bare Soil Index) e NDVI dominassem a importância de features, já que são os
índices espectrais desenhados para separar solo exposto/vegetação — as duas classes mais
relevantes para o objetivo do projeto (classe 3, solo exposto/obras, é a crítica). {"Isso se confirmou" if importancias_sem_sensor[0][0] in {"bsi", "ndvi", "ndbi", "evi"} else "Isso NÃO se confirmou exatamente como esperado"} — ver tabela de importância acima. Nenhuma
feature de localização (`x`/`y`/`linha`/`coluna`) ou tempo (`ano`) entra no modelo: elas nem
existem em `lista_features` do manifest, e a checagem em `carregar_dataset` falha alto se algum
dia entrarem — não há sinal de que o modelo esteja "decorando" geografia ou época em vez de
espectro.
"""


def caminho_relatorio(tag: str) -> Path:
    """Caminho do relatório de experimento, dependente da `tag` (bug corrigido em 2026-09-02).

    A primeira rodada de SV-12 (`tag == "v0.1"`, 3 sites) já está commitada em
    `EXP-001-rf-baseline.md` — nunca sobrescrever esse arquivo. `tag == "v0.2"` (expansão de
    SV-27 para 16 sites) grava em `EXP-001b-rf-v0.2-expansao.md`. `tag == "v1.0"` (SV-16 —
    incorporação da rotulagem manual de SV-10) grava em `EXP-002-rf-v1.0-treino.md`: este módulo
    só produz o relatório de TREINO/CV (hiperparâmetros, folds, importâncias, piso Dummy) — o
    nome `EXP-002-rf-labels-manuais.md` que o enunciado de SV-16 pede é reservado para o
    relatório de COMPARAÇÃO v0.1-vs-v1.0 (accuracy/macro-F1/F1-classe-3/holdout espacial-
    temporal/por origem_label/por bioma + decisão de modelo oficial), que depende da avaliação em
    holdout (SV-13/`sentinela.evaluate`, que roda DEPOIS deste treino) e por isso é escrito à
    parte, reaproveitando os números deste relatório sem depender do nome automático daqui — ver
    `docs/tarefas/SV-16-dataset-v1.0-retreino.md`. Qualquer outra tag cai no padrão genérico
    `EXP-001b-rf-{tag}-expansao.md`, para permitir comparar rodadas futuras lado a lado (ver nota
    de revisão de 2026-08-31 em `docs/tarefas/SV-12-baseline-random-forest.md`)."""
    if tag == "v0.1":
        return REPO_ROOT / "reports" / "experiments" / "EXP-001-rf-baseline.md"
    if tag == "v1.0":
        return REPO_ROOT / "reports" / "experiments" / "EXP-002-rf-v1.0-treino.md"
    return REPO_ROOT / "reports" / "experiments" / f"EXP-001b-rf-{tag}-expansao.md"


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from datetime import UTC, datetime

    parser = argparse.ArgumentParser(description="Treino do baseline Random Forest (SV-12).")
    parser.add_argument("--dataset", required=True, help="versão do dataset, ex.: v0.1")
    parser.add_argument("--modelo", required=True, choices=["rf"], help="baseline V1 (CLAUDE.md) — só 'rf' por ora")
    parser.add_argument("--tag", required=True, help="sufixo do artefato salvo, ex.: v0.1 -> models/rf_v0.1.joblib")
    args = parser.parse_args(argv)

    print(f"Carregando dataset {args.dataset}...")
    df, manifest = carregar_dataset(args.dataset)
    df_treino = filtrar_treino(df)
    lista_features = manifest["lista_features"]
    n_blocos_treino = int(df_treino["bloco_id"].nunique())
    print(f"  {len(df_treino)} linhas de treino, {n_blocos_treino} blocos.")

    print("Piso de comparação: DummyClassifier(strategy='stratified')...")
    X_dummy, y_dummy, groups_dummy, _ = montar_xy(df_treino, lista_features, incluir_sensor=False)
    resultado_dummy = cv_macro_f1(DummyClassifier(strategy="stratified", random_state=SEED), X_dummy, y_dummy, groups_dummy)
    print(f"  Dummy macro-F1: {resultado_dummy['media']:.4f} +/- {resultado_dummy['desvio']:.4f}")

    print("Variante (i) sem 'sensor' como feature...")
    X1, y1, groups1, feats1 = montar_xy(df_treino, lista_features, incluir_sensor=False)
    resultado_sem_sensor = cv_macro_f1(
        RandomForestClassifier(**RF_PARAMS_BASE), X1, y1, groups1, coletar_importancias=True
    )
    print(f"  RF sem sensor macro-F1: {resultado_sem_sensor['media']:.4f} +/- {resultado_sem_sensor['desvio']:.4f}")

    print("Variante (ii) com 'sensor' como feature binária...")
    X2, y2, groups2, feats2 = montar_xy(df_treino, lista_features, incluir_sensor=True)
    resultado_com_sensor = cv_macro_f1(
        RandomForestClassifier(**RF_PARAMS_BASE), X2, y2, groups2, coletar_importancias=True
    )
    print(f"  RF com sensor macro-F1: {resultado_com_sensor['media']:.4f} +/- {resultado_com_sensor['desvio']:.4f}")

    diferenca = resultado_com_sensor["media"] - resultado_sem_sensor["media"]
    if diferenca > DIFERENCA_SENSOR_RELEVANTE:
        variante_adotada, X_final, feats_final = "com_sensor", X2, feats2
    else:
        variante_adotada, X_final, feats_final = "sem_sensor", X1, feats1
    print(f"Diferença com-sensor - sem-sensor = {diferenca:+.4f} -> variante adotada: {variante_adotada}")

    print(f"Treino final ({variante_adotada}) em {len(df_treino)} linhas...")
    t0 = time.time()
    modelo_final = RandomForestClassifier(**RF_PARAMS_BASE)
    modelo_final.fit(X_final, y1)
    tempo_treino_final = time.time() - t0
    print(f"  tempo de treino final: {tempo_treino_final:.1f}s")

    print("Verificando determinismo (segundo fit, mesma seed)...")
    modelo_repeticao = RandomForestClassifier(**RF_PARAMS_BASE)
    modelo_repeticao.fit(X_final, y1)
    idx_lote = np.arange(min(1000, len(X_final)))
    determinismo_ok = bool(
        np.array_equal(modelo_final.predict(X_final[idx_lote]), modelo_repeticao.predict(X_final[idx_lote]))
    )
    print(f"  determinismo: {'OK' if determinismo_ok else 'FALHOU'}")

    pacote = montar_pacote_modelo(modelo_final, feats_final, args.dataset, SEED)
    joblib_path, sha_path = salvar_modelo(pacote, args.tag)
    joblib_sha256 = sha_path.read_text(encoding="utf-8").split()[0]
    print(f"Modelo salvo: {joblib_path} (sha256 {joblib_sha256})")

    # Para a variante adotada, a importância vem do modelo final (fit no treino inteiro) — o que
    # de fato vai para produção. Para a outra variante, evitamos um fit extra no dataset inteiro
    # só para reportar: usamos a média das importâncias já coletadas nos 5 folds da CV acima.
    if variante_adotada == "sem_sensor":
        importancias_sem_sensor = importancias_ordenadas(modelo_final, feats1)
        origem_sem_sensor = "fit final no treino inteiro (modelo efetivamente salvo)"
        importancias_com_sensor = sorted(
            zip(feats2, resultado_com_sensor["importancias_media"], strict=True), key=lambda p: p[1], reverse=True
        )
        origem_com_sensor = "média das importâncias nos 5 folds da CV (variante não adotada, sem fit extra no dataset inteiro)"
    else:
        importancias_com_sensor = importancias_ordenadas(modelo_final, feats2)
        origem_com_sensor = "fit final no treino inteiro (modelo efetivamente salvo)"
        importancias_sem_sensor = sorted(
            zip(feats1, resultado_sem_sensor["importancias_media"], strict=True), key=lambda p: p[1], reverse=True
        )
        origem_sem_sensor = "média das importâncias nos 5 folds da CV (variante não adotada, sem fit extra no dataset inteiro)"

    dataset_sha256 = manifest.get("sha256", "desconhecido")

    relatorio = construir_relatorio_md(
        dataset_versao=args.dataset,
        dataset_sha256=dataset_sha256,
        git_sha=_git_sha(),
        rf_params=RF_PARAMS_BASE,
        variante_adotada=variante_adotada,
        resultado_dummy=resultado_dummy,
        resultado_rf_sem_sensor=resultado_sem_sensor,
        resultado_rf_com_sensor=resultado_com_sensor,
        importancias_sem_sensor=importancias_sem_sensor,
        importancias_com_sensor=importancias_com_sensor,
        origem_importancia_sem_sensor=origem_sem_sensor,
        origem_importancia_com_sensor=origem_com_sensor,
        tempo_treino_final_s=tempo_treino_final,
        n_linhas_treino=len(df_treino),
        n_blocos_treino=n_blocos_treino,
        determinismo_ok=determinismo_ok,
        joblib_sha256=joblib_sha256,
        gerado_em=datetime.now(UTC).isoformat(),
    )
    relatorio_path = caminho_relatorio(args.tag)
    relatorio_path.parent.mkdir(parents=True, exist_ok=True)
    relatorio_path.write_text(relatorio, encoding="utf-8")
    print(f"Relatório salvo: {relatorio_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
