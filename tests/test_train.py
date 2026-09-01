"""Testes de sentinela.train (SV-12) — baseline Random Forest + registro de experimento.

Os testes puros (filtro de treino, montagem de X/y, importâncias) não tocam `data/` nem treinam
modelos grandes — usam DataFrames sintéticos pequenos ou RFs com poucas árvores, no mesmo padrão
de `tests/test_dataset.py`. Os testes que dependem de artefatos reais (`models/rf_v0.1.joblib`,
`reports/experiments/EXP-001-rf-baseline.md`) são pulados com `pytest.skip(...)` se ainda não
existirem — o número final para o relatório da banca vem de uma rodada completa do CLI
(`python -m sentinela.train --dataset v0.1 --modelo rf --tag v0.1`), não deste arquivo.

Cobre os "cenários de teste" do enunciado de SV-12:
1. Isolamento do teste — `filtrar_treino` falha alto se só sobrarem linhas de teste/holdout.
2. Determinismo — duas RFs com a mesma seed produzem as mesmas predições num lote fixo.
3. Contrato de features — o joblib real traz `lista_features`/`seed`/`classes_` e nunca inclui
   coluna proibida (localização/tempo).
4. Piso — `DummyClassifier` bem pior que RF num dataset sintético claramente separável.
5. Sanidade de importância — `COLUNAS_PROIBIDAS_COMO_FEATURE` nunca aparece em `lista_features`.
6. Variantes de sensor — `montar_xy(incluir_sensor=True)` adiciona exatamente uma coluna binária.
"""

from __future__ import annotations

import hashlib
import json

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.train import (
    COLUNAS_PROIBIDAS_COMO_FEATURE,
    SENSOR_FEATURE_COL,
    TrainError,
    carregar_dataset,
    cv_macro_f1,
    filtrar_treino,
    importancias_ordenadas,
    montar_xy,
)

SEED = 42


# --------------------------------------------------------------------------------------------
# filtrar_treino — cenário 1 (isolamento do teste), BLOQUEANTE
# --------------------------------------------------------------------------------------------


def _df_sintetico_split():
    return pd.DataFrame(
        {
            "blue": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "split": ["treino", "treino", "teste", "teste", "treino", "treino"],
            "holdout_temporal": [False, False, False, False, True, False],
        }
    )


def test_filtrar_treino_remove_teste_e_holdout():
    df = _df_sintetico_split()
    df_treino = filtrar_treino(df)
    # índices 0, 1, 5: split=='treino' e holdout_temporal==False. Índices 2,3 são teste (fora);
    # índice 4 é treino mas holdout_temporal==True (fora).
    assert len(df_treino) == 3
    assert (df_treino["split"] == "treino").all()
    assert not df_treino["holdout_temporal"].any()


def test_filtrar_treino_falha_se_so_sobra_teste():
    df = pd.DataFrame({"blue": [0.1, 0.2], "split": ["teste", "teste"], "holdout_temporal": [False, False]})
    with pytest.raises(TrainError):
        filtrar_treino(df)


def test_filtrar_treino_falha_se_so_sobra_holdout():
    df = pd.DataFrame({"blue": [0.1, 0.2], "split": ["treino", "treino"], "holdout_temporal": [True, True]})
    with pytest.raises(TrainError):
        filtrar_treino(df)


def test_filtrar_treino_nunca_deixa_teste_passar_mesmo_com_dado_maior():
    """Reforça o cenário 1 com mais linhas — nenhuma linha de split=='teste' sobrevive ao filtro,
    mesmo quando teste é a maioria do DataFrame de entrada."""
    n = 1000
    rng = np.random.default_rng(SEED)
    df = pd.DataFrame(
        {
            "blue": rng.random(n),
            "split": rng.choice(["treino", "teste"], size=n, p=[0.3, 0.7]),
            "holdout_temporal": rng.choice([True, False], size=n, p=[0.1, 0.9]),
        }
    )
    df_treino = filtrar_treino(df)
    assert not (df_treino["split"] == "teste").any()
    assert not df_treino["holdout_temporal"].any()


# --------------------------------------------------------------------------------------------
# montar_xy — ordem das features e variante com/sem sensor (cenário 6)
# --------------------------------------------------------------------------------------------


def _df_sintetico_xy():
    return pd.DataFrame(
        {
            "blue": [0.1, 0.2, 0.3, 0.4],
            "green": [0.5, 0.6, 0.7, 0.8],
            "classe_id": [1, 2, 1, 2],
            "bloco_id": ["b1", "b1", "b2", "b2"],
            "sensor": ["s2", "landsat", "s2", "landsat"],
        }
    )


def test_montar_xy_ordem_bate_com_lista_features():
    df = _df_sintetico_xy()
    X, y, groups, feature_names = montar_xy(df, ["blue", "green"], incluir_sensor=False)
    assert feature_names == ["blue", "green"]
    assert X.shape == (4, 2)
    np.testing.assert_allclose(X[:, 0], df["blue"].to_numpy())
    np.testing.assert_allclose(X[:, 1], df["green"].to_numpy())
    np.testing.assert_array_equal(y, df["classe_id"].to_numpy())
    np.testing.assert_array_equal(groups, df["bloco_id"].to_numpy())


def test_montar_xy_incluir_sensor_adiciona_uma_coluna_binaria():
    df = _df_sintetico_xy()
    X, _, _, feature_names = montar_xy(df, ["blue", "green"], incluir_sensor=True)
    assert feature_names == ["blue", "green", SENSOR_FEATURE_COL]
    assert X.shape == (4, 3)
    # sensor == "landsat" -> 1.0, "s2" -> 0.0, na mesma ordem das linhas do df
    np.testing.assert_allclose(X[:, 2], [0.0, 1.0, 0.0, 1.0])


def test_montar_xy_sem_sensor_nao_adiciona_coluna():
    df = _df_sintetico_xy()
    X, _, _, feature_names = montar_xy(df, ["blue", "green"], incluir_sensor=False)
    assert SENSOR_FEATURE_COL not in feature_names
    assert X.shape[1] == 2


# --------------------------------------------------------------------------------------------
# carregar_dataset — nunca deixa coluna proibida entrar como feature
# --------------------------------------------------------------------------------------------


def test_carregar_dataset_falha_se_manifest_lista_coluna_proibida(tmp_path, monkeypatch):
    processed_dir = tmp_path / "processed"
    manifests_dir = tmp_path / "manifests"
    processed_dir.mkdir()
    manifests_dir.mkdir()

    df = pd.DataFrame({"blue": [0.1], "ano": [2020], "split": ["treino"], "holdout_temporal": [False]})
    df.to_parquet(processed_dir / "dataset_vteste.parquet")
    manifest = {"lista_features": ["blue", "ano"], "sha256": "x"}  # "ano" nunca pode ser feature
    (manifests_dir / "dataset_vteste.json").write_text(json.dumps(manifest), encoding="utf-8")

    # `processed_dir`/`manifests_dir` são properties calculadas a partir de `data_root` (esse sim
    # um atributo simples) — precisa trocar a raiz, não a property (que não tem setter).
    monkeypatch.setattr(SETTINGS, "data_root", tmp_path)

    with pytest.raises(TrainError, match="proibida"):
        carregar_dataset("vteste")


def test_colunas_proibidas_como_feature_inclui_localizacao_e_tempo():
    assert {"ano", "x", "y", "linha", "coluna"} <= COLUNAS_PROIBIDAS_COMO_FEATURE


# --------------------------------------------------------------------------------------------
# cv_macro_f1 — GroupKFold + piso do Dummy (cenário 4), em dado sintético rápido
# --------------------------------------------------------------------------------------------


def _dataset_sintetico_separavel(n_por_classe: int = 200, seed: int = SEED):
    rng = np.random.default_rng(seed)
    classes_ = [1, 2, 3]
    linhas = []
    for classe_id in classes_:
        centro = classe_id * 5.0
        for _ in range(n_por_classe):
            linhas.append(
                {
                    "f1": rng.normal(centro, 0.5),
                    "f2": rng.normal(-centro, 0.5),
                    "classe_id": classe_id,
                    # blocos únicos o bastante para o GroupKFold(3) ter grupos em cada fold
                    "bloco_id": f"b{rng.integers(0, 40)}",
                }
            )
    return pd.DataFrame(linhas)


def test_cv_macro_f1_rf_muito_melhor_que_dummy_em_dado_separavel():
    df = _dataset_sintetico_separavel()
    X, y, groups, _ = montar_xy(df, ["f1", "f2"], incluir_sensor=False)

    resultado_dummy = cv_macro_f1(DummyClassifier(strategy="stratified", random_state=SEED), X, y, groups, n_splits=3)
    resultado_rf = cv_macro_f1(
        RandomForestClassifier(n_estimators=50, random_state=SEED, n_jobs=-1), X, y, groups, n_splits=3
    )

    assert resultado_rf["media"] > resultado_dummy["media"] + 0.20


def test_cv_macro_f1_coleta_importancias_quando_pedido():
    df = _dataset_sintetico_separavel()
    X, y, groups, feature_names = montar_xy(df, ["f1", "f2"], incluir_sensor=False)
    resultado = cv_macro_f1(
        RandomForestClassifier(n_estimators=30, random_state=SEED, n_jobs=-1),
        X, y, groups, n_splits=3, coletar_importancias=True,
    )
    assert "importancias_media" in resultado
    assert len(resultado["importancias_media"]) == len(feature_names)
    assert pytest.approx(sum(resultado["importancias_media"]), abs=1e-6) == 1.0


# --------------------------------------------------------------------------------------------
# Determinismo (cenário 2) — dado sintético pequeno, mesma seed -> mesmas predições
# --------------------------------------------------------------------------------------------


def test_determinismo_mesma_seed_mesmas_predicoes():
    df = _dataset_sintetico_separavel(n_por_classe=100)
    X, y, _, _ = montar_xy(df, ["f1", "f2"], incluir_sensor=False)

    params = {"n_estimators": 50, "random_state": SEED, "n_jobs": -1, "min_samples_leaf": 5}
    modelo_a = RandomForestClassifier(**params).fit(X, y)
    modelo_b = RandomForestClassifier(**params).fit(X, y)

    lote = X[:1000] if len(X) > 1000 else X
    np.testing.assert_array_equal(modelo_a.predict(lote), modelo_b.predict(lote))


# --------------------------------------------------------------------------------------------
# importancias_ordenadas
# --------------------------------------------------------------------------------------------


def test_importancias_ordenadas_desc():
    df = _dataset_sintetico_separavel(n_por_classe=100)
    X, y, _, feature_names = montar_xy(df, ["f1", "f2"], incluir_sensor=False)
    modelo = RandomForestClassifier(n_estimators=30, random_state=SEED, n_jobs=-1).fit(X, y)
    pares = importancias_ordenadas(modelo, feature_names)
    valores = [v for _, v in pares]
    assert valores == sorted(valores, reverse=True)
    assert {nome for nome, _ in pares} == set(feature_names)


# --------------------------------------------------------------------------------------------
# Artefatos reais (SV-12) — pulados se a rodada completa ainda não foi feita
# --------------------------------------------------------------------------------------------


def _joblib_path():
    return REPO_ROOT / "models" / "rf_v0.1.joblib"


def _relatorio_path():
    return REPO_ROOT / "reports" / "experiments" / "EXP-001-rf-baseline.md"


@pytest.fixture(scope="module")
def pacote_modelo():
    path = _joblib_path()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.train --dataset v0.1 --modelo rf --tag v0.1`.")
    return joblib.load(path)


def test_modelo_salvo_traz_contrato_completo(pacote_modelo):
    for campo in ("modelo", "lista_features", "versao_dataset", "seed", "sklearn_version", "git_sha", "classes_"):
        assert campo in pacote_modelo, f"campo '{campo}' ausente do pacote salvo"
    assert pacote_modelo["seed"] == SEED
    assert pacote_modelo["versao_dataset"] == "v0.1"
    assert isinstance(pacote_modelo["lista_features"], list)
    assert len(pacote_modelo["lista_features"]) == len(set(pacote_modelo["lista_features"])), "feature duplicada"


def test_modelo_salvo_nunca_inclui_coluna_proibida(pacote_modelo):
    proibidas = COLUNAS_PROIBIDAS_COMO_FEATURE & set(pacote_modelo["lista_features"])
    assert not proibidas, f"modelo salvo inclui coluna(s) proibida(s) como feature: {proibidas}"


def test_modelo_salvo_carrega_e_prediz(pacote_modelo):
    modelo = pacote_modelo["modelo"]
    n_features = len(pacote_modelo["lista_features"])
    X_fake = np.zeros((3, n_features))
    pred = modelo.predict(X_fake)
    assert len(pred) == 3
    assert set(pred.tolist()) <= set(pacote_modelo["classes_"])


def test_sha256_do_joblib_bate_com_arquivo_sha256():
    joblib_path = _joblib_path()
    sha_path = joblib_path.with_suffix(".sha256")
    if not (joblib_path.exists() and sha_path.exists()):
        pytest.skip("modelo/sha256 ainda não gerados.")
    sha_gravado = sha_path.read_text(encoding="utf-8").split()[0]
    h = hashlib.sha256()
    with joblib_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    assert h.hexdigest() == sha_gravado


def test_modelo_nao_esta_no_git():
    import subprocess

    joblib_path = _joblib_path()
    if not joblib_path.exists():
        pytest.skip(f"{joblib_path} não existe.")
    resultado = subprocess.run(["git", "check-ignore", "-q", str(joblib_path)], cwd=REPO_ROOT, check=False)
    assert resultado.returncode == 0, "models/rf_v0.1.joblib deveria estar no .gitignore"


def test_relatorio_exp001_existe_e_traz_secoes_obrigatorias():
    path = _relatorio_path()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode o treino completo antes.")
    conteudo = path.read_text(encoding="utf-8")
    for trecho in (
        "git sha", "Hiperparâmetros finais", "DummyClassifier", "macro-F1",
        "Importância de features", "Determinismo", "Comparação das variantes",
    ):
        assert trecho in conteudo, f"seção/trecho '{trecho}' ausente do EXP-001"
