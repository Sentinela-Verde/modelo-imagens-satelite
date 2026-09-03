"""SV-16 — análise cross-cutting de `rf_v1.0` por `origem_label` e por `bioma`.

Não é um módulo de pipeline (não vira `sentinela.*`): é a análise específica que o enunciado de
SV-16 pede e que `sentinela.evaluate` (SV-13) não cobre — desempenho separado por origem do label
(detecção de "decoreba" dos polígonos manuais) e por bioma (isolar se a rotulagem manual ajudou os
biomas novos ou só o Sudeste). Reaproveita `sentinela.evaluate` para carregar modelo/dataset e
montar X/predições — nunca chama `.fit`.

Rode com: python -m scripts.sv16_analise_origem_bioma (ou `python scripts/sv16_analise_origem_bioma.py`)
Saída: reports/sv16_analise_origem_bioma.json + tabelas markdown impressas no stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinela import evaluate as ev  # noqa: E402
from sentinela.config import REPO_ROOT  # noqa: E402


def _tabela_md(linhas: list[dict], colunas: list[str]) -> str:
    cab = "| " + " | ".join(colunas) + " |"
    sep = "|" + "|".join(["---"] * len(colunas)) + "|"
    corpo = []
    for row in linhas:
        vals = []
        for c in colunas:
            v = row[c]
            vals.append(f"{v:.4f}" if isinstance(v, float) else str(v))
        corpo.append("| " + " | ".join(vals) + " |")
    return "\n".join([cab, sep] + corpo)


def main() -> int:
    modelo_path = REPO_ROOT / "models" / "rf_v1.0.joblib"
    print(f"Carregando modelo {modelo_path}...")
    pacote = ev.carregar_modelo(modelo_path)
    lista_features = pacote["lista_features"]

    print("Carregando dataset v1.0...")
    df, manifest = ev.carregar_dataset("v1.0")

    df_teste = df[df["split"] == "teste"].copy()
    X_teste = ev.montar_X(df_teste, lista_features)
    df_teste["pred"] = pacote["modelo"].predict(X_teste)
    print(f"Predições calculadas em {len(df_teste)} linhas de holdout espacial (nenhum .fit chamado).")

    resultado: dict = {"n_teste": int(len(df_teste))}

    # --- por origem_label (detecção de decoreba) ---
    linhas_origem = []
    for origem in sorted(df_teste["origem_label"].dropna().unique(), key=str):
        sub = df_teste[df_teste["origem_label"] == origem]
        m = ev.calcular_metricas(sub["classe_id"].to_numpy(), sub["pred"].to_numpy())
        pr_c3, rc_c3 = ev._precision_recall_classe3(m)
        linhas_origem.append({
            "origem_label": str(origem), "n": m["n"], "accuracy": m["accuracy"],
            "macro_f1": m["macro_f1"], "f1_classe3": ev._f1_classe3(m),
            "precision_classe3": pr_c3, "recall_classe3": rc_c3,
        })
    resultado["por_origem_label"] = linhas_origem

    # --- por bioma (pooled, direto do dataset_v1.0 — mais preciso que média ponderada por site) ---
    linhas_bioma = []
    for bioma in sorted(df_teste["bioma"].dropna().unique(), key=str):
        sub = df_teste[df_teste["bioma"] == bioma]
        m = ev.calcular_metricas(sub["classe_id"].to_numpy(), sub["pred"].to_numpy())
        pr_c3, rc_c3 = ev._precision_recall_classe3(m)
        n_manual = int((sub["origem_label"] == "manual").sum())
        linhas_bioma.append({
            "bioma": str(bioma), "n": m["n"], "n_manual_no_teste": n_manual,
            "accuracy": m["accuracy"], "macro_f1": m["macro_f1"],
            "f1_classe3": ev._f1_classe3(m), "precision_classe3": pr_c3, "recall_classe3": rc_c3,
        })
    resultado["por_bioma"] = linhas_bioma

    # --- por bioma x origem_label (célula fina: confirma que o ganho por bioma não é só decoreba) ---
    linhas_bioma_origem = []
    for bioma in sorted(df_teste["bioma"].dropna().unique(), key=str):
        for origem in sorted(df_teste["origem_label"].dropna().unique(), key=str):
            sub = df_teste[(df_teste["bioma"] == bioma) & (df_teste["origem_label"] == origem)]
            if sub.empty:
                continue
            m = ev.calcular_metricas(sub["classe_id"].to_numpy(), sub["pred"].to_numpy())
            linhas_bioma_origem.append({
                "bioma": str(bioma), "origem_label": str(origem), "n": m["n"],
                "macro_f1": m["macro_f1"], "f1_classe3": ev._f1_classe3(m),
            })
    resultado["por_bioma_e_origem_label"] = linhas_bioma_origem

    out_path = REPO_ROOT / "reports" / "sv16_analise_origem_bioma.json"
    out_path.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSalvo: {out_path}\n")

    print("## Por origem_label (holdout espacial)\n")
    print(_tabela_md(linhas_origem, ["origem_label", "n", "accuracy", "macro_f1", "f1_classe3", "precision_classe3", "recall_classe3"]))
    print("\n## Por bioma (holdout espacial)\n")
    print(_tabela_md(linhas_bioma, ["bioma", "n", "n_manual_no_teste", "accuracy", "macro_f1", "f1_classe3", "precision_classe3", "recall_classe3"]))
    print("\n## Por bioma x origem_label (holdout espacial)\n")
    print(_tabela_md(linhas_bioma_origem, ["bioma", "origem_label", "n", "macro_f1", "f1_classe3"]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
