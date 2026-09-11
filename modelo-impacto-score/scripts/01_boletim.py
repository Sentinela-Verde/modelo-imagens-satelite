"""Camada 1 — MEDIÇÃO. O boletim de impacto por campus e por eixo.

Rode com:

    python modelo-impacto-score/scripts/01_boletim.py

## O que este script decide, e por que

**Não existe um score único.** Um número agregado do tipo "impacto 73/100" exigiria pesos
arbitrários e misturaria eixos com qualidade de evidência incompatível — hoje, conversão para
construída (p=0,0002) somada a temperatura (nulo sem poder de detecção). O agregado esconderia
exatamente a parte forte do trabalho e seria a peça mais fácil de derrubar numa banca.

O que se publica é um **boletim por eixo**: cada eixo carrega seu efeito medido, seu N, seu p e um
**selo de evidência** que diz o que pode ser afirmado a partir dele.

  forte           — o efeito foi medido e o teste de sinal sustenta a afirmação
  sugestivo       — direção consistente, sem significância com este N
  nulo_informativo— não há efeito detectável, e o desenho teria poder para vê-lo
  nulo_sem_poder  — não se detectou nada, MAS o desenho não veria nem se existisse.
                    NÃO é evidência de ausência de efeito, e reportá-lo como tal seria erro.

O score 0-100 por eixo é **posto percentual dentro dos casos medidos** — uma posição relativa
entre os 14 campi, não uma medida absoluta de dano. Está escrito assim na saída de propósito.

Saídas:
  - `outputs/boletim_por_eixo.csv`   — campus x eixo (formato longo)
  - `outputs/boletim_por_campus.csv` — uma linha por campus (formato largo)
  - `outputs/selos_de_evidencia.csv` — o que cada eixo permite afirmar
  - `reports/figuras/fig_01_boletim.png` — a figura única do achado
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum as K  # noqa: E402


def main() -> int:
    m = K.tabela_mestra()
    selos = K.selos_de_evidencia()
    K.salvar(selos, "selos_de_evidencia.csv")

    # ------------------------------------------------------------------ boletim longo
    selo_por_eixo = selos.set_index("eixo")["selo"].to_dict()
    linhas = []
    for eixo, meta in K.EIXOS.items():
        col = f"y_{eixo}"
        vals = m[col]
        scores = K.escore_percentil(vals, meta["direcao_ruim"])
        for _, r in m.iterrows():
            v = r[col]
            linhas.append(
                {
                    "site_id": r.site_id,
                    "municipio": r.municipio,
                    "uf": r.uf,
                    "eixo": eixo,
                    "rotulo": meta["rotulo"],
                    "efeito_liquido": None if pd.isna(v) else round(float(v), 3),
                    "unidade": meta["unidade"],
                    "score_0_100": None if pd.isna(v) else float(scores.loc[r.name]),
                    "selo_do_eixo": selo_por_eixo.get(eixo, "—"),
                    "tipo_sitio": r.x_tipo_sitio,
                    "qualidade_par": r.qualidade_par,
                    "ano_inicio_obra": int(r.ano_inicio_obra),
                    "sensor": r.sensor,
                }
            )
    boletim = pd.DataFrame(linhas)
    K.salvar(boletim, "boletim_por_eixo.csv")

    # ------------------------------------------------------------------ boletim largo
    largo = m[
        ["site_id", "municipio", "uf", "regiao", "bioma", "ano_inicio_obra", "sensor",
         "x_tipo_sitio", "x_pct_ja_construida", "x_area_footprint_ha", "qualidade_par",
         "dist_tratamento_controle_km"]
    ].copy()
    for eixo, meta in K.EIXOS.items():
        largo[f"efeito_{eixo}"] = m[f"y_{eixo}"].round(3)
        largo[f"score_{eixo}"] = K.escore_percentil(m[f"y_{eixo}"], meta["direcao_ruim"])
    # score de destaque = só o eixo com selo forte; nunca uma média dos quatro
    largo["score_destaque_construcao_0_500m"] = largo["score_construcao_0_500m"]
    largo["leitura"] = [
        "sem par medido"
        if pd.isna(v)
        else f"converteu {v:+.2f} p.p. a mais que o controle no anel de 500 m"
        for v in m["y_construcao_0_500m"]
    ]
    largo = largo.sort_values("efeito_construcao_0_500m", ascending=False)
    K.salvar(largo, "boletim_por_campus.csv")

    # ------------------------------------------------------------------ figura
    d = m.dropna(subset=["y_construcao_0_500m", "x_pct_ja_construida"]).sort_values(
        "x_pct_ja_construida"
    )
    fig, ax = plt.subplots(figsize=(11, 6.5))
    cores = {"greenfield": "#27AE60", "brownfield": "#E67E22"}
    for _, r in d.iterrows():
        ax.plot([0, r.y_construcao_0_500m], [r.site_id, r.site_id], color="#CCC", lw=1.5, zorder=1)
    ax.scatter(
        d.y_construcao_0_500m, d.site_id,
        c=[cores[t] for t in d.x_tipo_sitio], s=95, zorder=3, edgecolors="white", linewidths=1.2,
    )
    ax.axvline(0, color="#333", lw=1.2, zorder=2)
    med = float(d.y_construcao_0_500m.median())
    ax.axvline(med, color="#888", ls="--", lw=1, zorder=2)
    ax.set_ylim(-1.2, len(d) - 0.3)
    ax.text(med, -1.0, f"  mediana {med:+.2f} p.p.", fontsize=8, color="#666", va="center")

    for t, c in cores.items():
        sub = d[d.x_tipo_sitio == t]
        ax.scatter([], [], c=c, s=95, label=f"{t} (n={len(sub)}, {int((sub.y_construcao_0_500m > 0).sum())} positivos)")
    ax.legend(loc="upper left", fontsize=9, frameon=True, framealpha=0.92, edgecolor="#DDD")

    rot = [f"{r.site_id}  ({r.x_pct_ja_construida:.0f}% já construído)" for _, r in d.iterrows()]
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(rot, fontsize=9)
    ax.set_xlabel("excesso de conversão para área construída vs. controle pareado (p.p.)")
    ax.set_title(
        "Impacto territorial no anel de 0–500 m, por campus\n"
        f"{int((d.y_construcao_0_500m > 0).sum())}/{len(d)} acima do controle · "
        "ordenado pelo terreno já construído antes da obra (topo = mais saturado)",
        fontsize=11,
    )
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    K.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    saida = K.DIR_FIGURAS / "fig_01_boletim.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"  -> {saida.relative_to(K.RAIZ)}")

    # ------------------------------------------------------------------ leitura
    print("\n--- selos ---")
    for _, r in selos.iterrows():
        print(f"  {r.eixo:22s} {r.selo:16s} n={r.n_pares:2d} p={r.p:.4f} mediana={r.excesso_mediano:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
