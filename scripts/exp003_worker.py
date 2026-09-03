"""EXP-003 — worker de uma etapa da busca de hiperparâmetros (SV-12 "tuning mínimo e honesto").

Desenhado para caber no limite de ~10 min por chamada de shell: cada invocação faz **uma** coisa
só (um fit único de timing/tamanho, OU um fold do GroupKFold(5)) e persiste o resultado em
`exp003_results.json` no scratchpad — nunca salva nenhum `.joblib` de configuração candidata em
disco (só o vencedor final é salvo, por `sentinela.train.salvar_modelo`, fora deste script).

Reaproveita `RF_PARAMS_BASE` de `sentinela.train` como ponto de partida e sobrepõe só os
hiperparâmetros que este experimento varia (`max_depth`, `min_samples_leaf`) — `n_estimators`,
`max_features`, `class_weight`, `random_state` ficam fixos, fora de escopo desta rodada.

Uso:
    python exp003_worker.py timing --config max_depth_30 --max-depth 30
    python exp003_worker.py fold   --config max_depth_30 --max-depth 30 --fold 0
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

REPO_ROOT = Path(r"C:\Users\gabri\IdeaProjects\modelo-imagens-satelite")
sys.path.insert(0, str(REPO_ROOT / "src"))

from sentinela.train import RF_PARAMS_BASE  # noqa: E402

CACHE_DIR = Path(
    r"C:\Users\gabri\AppData\Local\Temp\claude\C--Users-gabri-IdeaProjects-modelo-imagens-satelite"
    r"\b20d10eb-e2d5-45e7-b70e-dd761a5a6dd0\scratchpad\exp003"
)
RESULTS_PATH = CACHE_DIR / "exp003_results.json"
N_SPLITS_CV = 5
CLASSE_CRITICA_ID = 3
SEED = 42
N_TREES_AMOSTRA_TAMANHO = 20  # nº de árvores usadas p/ estimar bytes/nó via pickle, sem salvar as 300 em disco


def carregar_cache() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.load(CACHE_DIR / "X.npy")
    y = np.load(CACHE_DIR / "y.npy")
    groups = np.load(CACHE_DIR / "groups.npy", allow_pickle=True)
    return X, y, groups


def montar_params(args: argparse.Namespace) -> dict:
    params = dict(RF_PARAMS_BASE)
    if args.max_depth is not None:
        params["max_depth"] = None if args.max_depth == "None" else int(args.max_depth)
    if args.min_samples_leaf is not None:
        params["min_samples_leaf"] = int(args.min_samples_leaf)
    return params


def carregar_resultados() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {}


def salvar_resultados(resultados: dict) -> None:
    RESULTS_PATH.write_text(json.dumps(resultados, indent=2), encoding="utf-8")


def cmd_timing(args: argparse.Namespace) -> int:
    X, y, _ = carregar_cache()
    params = montar_params(args)
    print(f"[{args.config}] fit único (timing+tamanho) — params={params}")

    modelo = RandomForestClassifier(**params)
    t0 = time.time()
    modelo.fit(X, y)
    tempo = time.time() - t0
    print(f"  tempo de fit único: {tempo:.1f}s")

    node_counts = [int(est.tree_.node_count) for est in modelo.estimators_]
    total_nodes = int(sum(node_counts))
    n_trees = len(modelo.estimators_)
    avg_nodes = total_nodes / n_trees
    print(f"  total_nodes (300 árvores)={total_nodes}, média nós/árvore={avg_nodes:.0f}")

    # Estimativa de tamanho em disco sem salvar as 300 árvores: pickle.dumps só de uma amostra
    # de árvores (in-memory, nunca toca disco) -> bytes/nó -> extrapola para o total.
    idx_amostra = list(range(min(N_TREES_AMOSTRA_TAMANHO, n_trees)))
    amostra_estimators = [modelo.estimators_[i] for i in idx_amostra]
    nodes_amostra = sum(node_counts[i] for i in idx_amostra)
    bytes_amostra = len(pickle.dumps(amostra_estimators, protocol=pickle.HIGHEST_PROTOCOL))
    bytes_por_no = bytes_amostra / nodes_amostra
    estimativa_bytes = bytes_por_no * total_nodes
    print(
        f"  amostra {len(idx_amostra)} árvores: {bytes_amostra} bytes / {nodes_amostra} nós "
        f"= {bytes_por_no:.2f} bytes/nó -> estimativa total = {estimativa_bytes / 1e9:.3f} GB"
    )

    resultados = carregar_resultados()
    resultados.setdefault(args.config, {})
    resultados[args.config]["params"] = params
    resultados[args.config]["timing"] = {
        "tempo_fit_unico_s": round(tempo, 1),
        "total_nodes_300_arvores": total_nodes,
        "media_nos_por_arvore": round(avg_nodes, 1),
        "bytes_por_no_amostrado": round(bytes_por_no, 3),
        "estimativa_tamanho_bytes": round(estimativa_bytes),
        "estimativa_tamanho_gb": round(estimativa_bytes / 1e9, 3),
        "n_arvores_amostradas_para_estimativa": len(idx_amostra),
    }
    salvar_resultados(resultados)
    del modelo
    print("Resultado de timing salvo.")
    return 0


def cmd_fold(args: argparse.Namespace) -> int:
    X, y, groups = carregar_cache()
    params = montar_params(args)
    gkf = GroupKFold(n_splits=N_SPLITS_CV)
    splits = list(gkf.split(X, y, groups))
    idx_treino, idx_val = splits[args.fold]
    print(
        f"[{args.config}] fold {args.fold + 1}/{N_SPLITS_CV} — n_treino={len(idx_treino)}, "
        f"n_val={len(idx_val)}, params={params}"
    )

    modelo = clone(RandomForestClassifier(**params))
    t0 = time.time()
    modelo.fit(X[idx_treino], y[idx_treino])
    tempo_fit = time.time() - t0
    pred = modelo.predict(X[idx_val])
    y_val = y[idx_val]

    macro_f1 = float(f1_score(y_val, pred, average="macro", zero_division=0))
    f1_classe3 = float(f1_score(y_val, pred, labels=[CLASSE_CRITICA_ID], average=None, zero_division=0)[0])
    print(f"  tempo_fit={tempo_fit:.1f}s macro_f1={macro_f1:.4f} f1_classe3={f1_classe3:.4f}")

    resultados = carregar_resultados()
    resultados.setdefault(args.config, {})
    resultados[args.config]["params"] = params
    resultados[args.config].setdefault("folds", {})
    resultados[args.config]["folds"][str(args.fold)] = {
        "tempo_fit_s": round(tempo_fit, 1),
        "n_treino": int(len(idx_treino)),
        "n_val": int(len(idx_val)),
        "macro_f1": macro_f1,
        "f1_classe3": f1_classe3,
    }
    salvar_resultados(resultados)
    del modelo
    print("Resultado de fold salvo.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker EXP-003 — uma etapa da busca de hiperparâmetros.")
    parser.add_argument("step", choices=["timing", "fold"])
    parser.add_argument("--config", required=True, help="nome da configuração (chave no results.json)")
    parser.add_argument("--max-depth", default=None, help="int ou 'None' (default do RF_PARAMS_BASE se omitido)")
    parser.add_argument("--min-samples-leaf", default=None, help="int (default do RF_PARAMS_BASE se omitido)")
    parser.add_argument("--fold", type=int, default=None, help="índice do fold (0-4), obrigatório para step=fold")
    args = parser.parse_args(argv)

    if args.step == "fold" and args.fold is None:
        parser.error("--fold é obrigatório para step=fold")

    if args.step == "timing":
        return cmd_timing(args)
    return cmd_fold(args)


if __name__ == "__main__":
    sys.exit(main())
