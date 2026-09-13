"""Passo 15 — o efeito depende de o terreno já estar construído? (greenfield x brownfield)

Rode com:

    python modelo-impacto/scripts/impacto_dc_15_greenfield_brownfield.py

## De onde veio a hipótese

O passo 14 mediu que, dentro do footprint, **50% dos pixels (mediana) já eram classificados como
construída antes da obra** — em quatro campi, 85 a 90%. Estes data centers foram erguidos em
parques industriais existentes, não em campo aberto. O contra-exemplo é `clickip-manaus`: 0% de
terreno previamente construído, e 75% dos pixels do footprint convertendo.

Se o sítio já estava saturado de área construída, sobra pouco terreno convertível — e o excesso
sobre o controle deveria ser menor por um motivo **mecânico**, não por o data center ter menos
efeito. Este passo testa isso.

## Estratificador

`pct_ja_construida` do passo 14: a fração dos pixels do footprint que já eram classe 4 nos 2
primeiros anos da janela. É contínuo e cobre 13 campi — preferível ao campo `tipo_construcao` da
planilha do Guilherme, que só existe para 8 campi e é ambíguo em 2 deles (prédios de tipos
diferentes no mesmo campus).

## Honestidade sobre o corte

O limiar de 50% foi escolhido **depois** de ver os dados — é um grau de liberdade do analista, e
ignorá-lo seria enganoso. Por isso o script varre 7 limiares (20% a 80%) e publica todos, mais um
teste contínuo (Spearman) que não depende de corte nenhum. A conclusão só vale na medida em que
sobrevive à varredura.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C

ZONAS = ["0-0.5km", "0.5-1km", "1-2km"]
LIMIARES = [20, 30, 40, 50, 60, 70, 80]
LIMIAR_PADRAO = 50
ASSINATURA = "pct_virou_construida"

SAIDA = C.DIR_SAIDA / "greenfield_brownfield.csv"
SAIDA_ROBUSTEZ = C.DIR_SAIDA / "greenfield_brownfield_robustez.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_09_greenfield_brownfield.png"


def p_bin_superior(k: int, n: int, p0: float = 0.5) -> float:
    return sum(math.comb(n, i) * p0**i * (1 - p0) ** (n - i) for i in range(k, n + 1))


def excessos_por_zona(longo: pd.DataFrame, zona: str) -> pd.DataFrame:
    """Excesso do tratamento sobre o controle, por par, numa zona."""
    linhas = []
    for site_id, par in longo[longo["zona"] == zona].groupby("pareado_com"):
        t = par[par["tipo"] == "tratamento"][ASSINATURA]
        c = par[par["tipo"] == "controle"][ASSINATURA]
        if t.empty or c.empty or t.isna().all() or c.isna().all():
            continue
        linhas.append({"pareado_com": site_id, "zona": zona,
                       "excesso_pp": round(float(t.iloc[0] - c.iloc[0]), 4)})
    return pd.DataFrame(linhas)


def main() -> int:
    caminho = C.DIR_SAIDA / "footprint_vs_anel.csv"
    if not caminho.exists():
        print(f"ERRO: {caminho} não existe — rode o passo 14 antes.", file=sys.stderr)
        return 1
    longo = pd.read_csv(caminho)
    composicao = longo[(longo["zona"] == "footprint") & (longo["n_pixels_footprint"] > 0)][
        ["pareado_com", "pct_ja_construida", "area_zona_ha", "metodo_footprint"]
    ].rename(columns={"area_zona_ha": "area_footprint_ha"})
    print(f"Passo 15 — {len(composicao)} campi com composição de footprint utilizável")

    tabela = pd.concat([excessos_por_zona(longo, z) for z in ZONAS], ignore_index=True)
    tabela = tabela.merge(composicao, on="pareado_com")
    tabela["tipo_sitio"] = np.where(
        tabela["pct_ja_construida"] < LIMIAR_PADRAO, "greenfield", "brownfield"
    )
    C.salvar_csv(tabela.sort_values(["zona", "pct_ja_construida"]), SAIDA)

    linhas_rob = []
    for zona in ZONAS:
        sub = tabela[tabela["zona"] == zona]
        for limiar in LIMIARES:
            for rotulo, grupo in (("greenfield", sub[sub["pct_ja_construida"] < limiar]),
                                  ("brownfield", sub[sub["pct_ja_construida"] >= limiar])):
                if grupo.empty:
                    continue
                n = len(grupo)
                pos = int((grupo["excesso_pp"] > 0).sum())
                linhas_rob.append({
                    "zona": zona, "limiar_pct": limiar, "tipo_sitio": rotulo, "n": n,
                    "n_positivo": pos, "frac_positivo": round(pos / n, 3),
                    "p_unilateral": round(p_bin_superior(pos, n), 4),
                    "excesso_mediano_pp": round(float(grupo["excesso_pp"].median()), 4),
                })
    robustez = pd.DataFrame(linhas_rob)
    C.salvar_csv(robustez, SAIDA_ROBUSTEZ)

    print()
    print(f"=== Zona 0-0,5 km, corte padrão em {LIMIAR_PADRAO}% ===")
    z0 = tabela[tabela["zona"] == "0-0.5km"].sort_values("pct_ja_construida")
    print(f"{'campus':26} {'tipo':11} {'já constr.':>11} {'excesso pp':>12}")
    for _, r in z0.iterrows():
        print(f"{r['pareado_com']:26} {r['tipo_sitio']:11} {r['pct_ja_construida']:>10.1f}% "
              f"{r['excesso_pp']:>+12.2f}")
    for rotulo, grupo in z0.groupby("tipo_sitio"):
        pos = int((grupo["excesso_pp"] > 0).sum())
        print(f"  {rotulo:11} {pos}/{len(grupo)} positivos, mediana "
              f"{grupo['excesso_pp'].median():+.2f} pp, p={p_bin_superior(pos, len(grupo)):.3f}")

    print()
    print("=== Robustez ao corte (zona 0-0,5 km) — o corte de 50% foi escolhido vendo os dados ===")
    print(f"{'corte':>7} {'greenfield':>28} {'brownfield':>28}")
    rz = robustez[robustez["zona"] == "0-0.5km"]
    for limiar in LIMIARES:
        celulas = {}
        for rotulo in ("greenfield", "brownfield"):
            linha = rz[(rz["limiar_pct"] == limiar) & (rz["tipo_sitio"] == rotulo)]
            celulas[rotulo] = (
                "—" if linha.empty else
                f"{int(linha['n_positivo'].iloc[0])}/{int(linha['n'].iloc[0])} pos, "
                f"med {linha['excesso_mediano_pp'].iloc[0]:+.2f}, "
                f"p={linha['p_unilateral'].iloc[0]:.3f}"
            )
        print(f"{limiar:>6}% {celulas['greenfield']:>28} {celulas['brownfield']:>28}")

    rho = z0[["pct_ja_construida", "excesso_pp"]].corr(method="spearman").iloc[0, 1]
    print()
    print(f"Teste contínuo, sem corte: Spearman(% já construído, excesso) = {rho:+.3f} (n={len(z0)})")
    print("Sinal negativo = quanto MAIS construído o terreno já era, MENOR o excesso.")

    # Figura
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    ax = axes[0]
    cores = {"greenfield": "#1B5E20", "brownfield": "#C0392B"}
    for rotulo, grupo in z0.groupby("tipo_sitio"):
        ax.scatter(grupo["pct_ja_construida"], grupo["excesso_pp"], s=110,
                   color=cores[rotulo], edgecolor="white", linewidth=1.2, label=rotulo, zorder=3)
    for _, r in z0.iterrows():
        ax.annotate(r["pareado_com"], (r["pct_ja_construida"], r["excesso_pp"]), fontsize=7,
                    xytext=(6, 3), textcoords="offset points", color="#444444")
    ax.axhline(0, color="gray", linestyle="--", linewidth=1.3)
    ax.axvline(LIMIAR_PADRAO, color="#F5A623", linestyle=":", linewidth=1.6)
    ax.set_xlabel("% do footprint que já era construída antes da obra")
    ax.set_ylabel("excesso do tratamento, zona 0–0,5 km (pp)")
    ax.set_title("Terreno saturado, excesso menor\nos 2 pares negativos são os mais saturados",
                 fontsize=11.5)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)

    ax2 = axes[1]
    for rotulo in ("greenfield", "brownfield"):
        g = rz[rz["tipo_sitio"] == rotulo].sort_values("limiar_pct")
        ax2.plot(g["limiar_pct"], g["frac_positivo"], "o-", linewidth=2.2, markersize=7,
                 color=cores[rotulo], label=rotulo)
    ax2.axhline(0.5, color="gray", linestyle="--", linewidth=1.3)
    ax2.set_ylim(0, 1.05)
    ax2.set_xlabel("limiar do corte greenfield/brownfield (%)")
    ax2.set_ylabel("fração de pares com excesso positivo")
    ax2.set_title("Robustez ao corte\ngreenfield fica 100% positivo em toda a faixa útil",
                  fontsize=11.5)
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.25)

    fig.suptitle("O efeito é mais nítido onde havia terreno para converter", fontsize=13, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    SAIDA_FIGURA.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=140)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
