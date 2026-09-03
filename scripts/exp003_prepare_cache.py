"""EXP-003 — prepara cache de X/y/groups do treino de `dataset_v1.0` para a busca de hiperparâmetros.

Roda uma única vez. Reaproveita `sentinela.train.carregar_dataset`/`filtrar_treino`/`montar_xy`
(mesmo filtro `split=="treino" & holdout_temporal==False`, mesma ordem de features, mesma variante
`com_sensor` adotada pelo `rf_v1.0` oficial — ver EXP-002-rf-v1.0-treino.md) e salva os arrays em
.npy no scratchpad, para que os passos seguintes da busca (timing de fit único + GroupKFold por
fold, cada um uma chamada Python separada para caber no limite de 10 min por chamada de shell) não
precisem reler/refiltrar o parquet (3,8M linhas) a cada vez.

Nenhum modelo é treinado aqui — só preparação de dado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(r"C:\Users\gabri\IdeaProjects\modelo-imagens-satelite")
sys.path.insert(0, str(REPO_ROOT / "src"))

from sentinela.train import carregar_dataset, filtrar_treino, montar_xy  # noqa: E402

CACHE_DIR = Path(
    r"C:\Users\gabri\AppData\Local\Temp\claude\C--Users-gabri-IdeaProjects-modelo-imagens-satelite"
    r"\b20d10eb-e2d5-45e7-b70e-dd761a5a6dd0\scratchpad\exp003"
)


def main() -> int:
    print("Carregando dataset_v1.0...")
    df, manifest = carregar_dataset("v1.0")
    df_treino = filtrar_treino(df)
    lista_features = manifest["lista_features"]
    print(f"  {len(df_treino)} linhas de treino, {df_treino['bloco_id'].nunique()} blocos.")

    X, y, groups, feature_names = montar_xy(df_treino, lista_features, incluir_sensor=True)
    print(f"  X shape={X.shape}, feature_names={feature_names}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(CACHE_DIR / "X.npy", X)
    np.save(CACHE_DIR / "y.npy", y)
    np.save(CACHE_DIR / "groups.npy", groups)
    (CACHE_DIR / "feature_names.json").write_text(json.dumps(feature_names), encoding="utf-8")
    (CACHE_DIR / "meta.json").write_text(
        json.dumps(
            {
                "n_linhas_treino": int(len(df_treino)),
                "n_blocos_treino": int(df_treino["bloco_id"].nunique()),
                "dataset_sha256": manifest.get("sha256", "desconhecido"),
            }
        ),
        encoding="utf-8",
    )
    print(f"Cache salvo em {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
