"""EXP-003 — treino final ÚNICO da configuração vencedora da busca (`max_depth=30`) + salvamento.

Reaproveita `sentinela.train.carregar_dataset`/`filtrar_treino`/`montar_xy`/`montar_pacote_modelo`/
`salvar_modelo` — mesmo pipeline usado para `rf_v1.0`, só troca o `RandomForestClassifier` para
incluir `max_depth=30` (vencedor da CV de EXP-003, ver `exp003_results.json`). Roda **uma única vez**
sobre o treino inteiro (`split=="treino" & holdout_temporal==False`, 1.939.285 linhas), nunca sobre
`split=="teste"`. Confere espaço em disco livre antes de salvar (regra do enunciado de EXP-003: se
< ~6 GB livres, aborta sem salvar).
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(r"C:\Users\gabri\IdeaProjects\modelo-imagens-satelite")
sys.path.insert(0, str(REPO_ROOT / "src"))

from sklearn.ensemble import RandomForestClassifier  # noqa: E402

from sentinela.train import (  # noqa: E402
    RF_PARAMS_BASE,
    SEED,
    carregar_dataset,
    filtrar_treino,
    montar_pacote_modelo,
    montar_xy,
    salvar_modelo,
)

LIMIAR_DISCO_LIVRE_BYTES = 6_000_000_000  # ~6 GB, regra do enunciado de EXP-003


def main() -> int:
    print("Carregando dataset_v1.0...")
    df, manifest = carregar_dataset("v1.0")
    df_treino = filtrar_treino(df)
    lista_features = manifest["lista_features"]
    print(f"  {len(df_treino)} linhas de treino, {df_treino['bloco_id'].nunique()} blocos.")

    X, y, groups, feature_names = montar_xy(df_treino, lista_features, incluir_sensor=True)
    print(f"  X shape={X.shape}, feature_names={feature_names}")

    params = dict(RF_PARAMS_BASE)
    params["max_depth"] = 30
    print(f"Treino final (config vencedora EXP-003, max_depth=30): {params}")

    t0 = time.time()
    modelo = RandomForestClassifier(**params)
    modelo.fit(X, y)
    tempo_treino = time.time() - t0
    print(f"  tempo de treino final: {tempo_treino:.1f}s")

    livre = shutil.disk_usage(REPO_ROOT.drive + "\\").free
    print(f"Espaço livre em disco antes de salvar: {livre / 1e9:.2f} GB")
    if livre < LIMIAR_DISCO_LIVRE_BYTES:
        print(f"ABORTANDO: espaço livre ({livre / 1e9:.2f} GB) abaixo do limiar de 6 GB. Modelo NÃO salvo.")
        return 1

    pacote = montar_pacote_modelo(modelo, feature_names, "v1.0", SEED)
    joblib_path, sha_path = salvar_modelo(pacote, "v1.0-tuned")
    sha256 = sha_path.read_text(encoding="utf-8").split()[0]
    tamanho_bytes = joblib_path.stat().st_size
    print(f"Modelo salvo: {joblib_path} ({tamanho_bytes} bytes = {tamanho_bytes / 1e9:.3f} GB), sha256={sha256}")

    livre_depois = shutil.disk_usage(REPO_ROOT.drive + "\\").free
    print(f"Espaço livre em disco depois de salvar: {livre_depois / 1e9:.2f} GB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
