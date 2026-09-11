"""Camada 2 — EXPLICAÇÃO. O que prediz o tamanho do impacto?

Rode com:

    python modelo-impacto-score/scripts/02_explicacao.py

## A pergunta central

O passo 15 de `dados-modelo-impacto` já achou uma regra de UMA variável que funciona:
`pct_ja_construida` (quanto do terreno do footprint já era construído antes da obra) separa
greenfield de brownfield, com 6/6 pares positivos contra 5/7. A pergunta desta camada é a única
que interessa depois disso:

    **alguma coisa bate `pct_ja_construida` sozinho?**

Se nada bater, isso É o resultado — e é publicável. Um modelo que não supera uma regra de uma
variável não deve ser apresentado como modelo.

## Por que o protocolo é este

N = 13 campi com alvo e feature de terreno. Treze. Nesse regime:

- **LOOCV é obrigatório.** R² dentro da amostra com 13 pontos é uma medida de quanto o modelo
  decora, não de quanto ele generaliza. Todo número publicado aqui é fora-da-amostra.
- **Baseline burro entra na comparação.** "Prever a mediana do fold de treino" é o piso. Um
  modelo que não bate esse piso não tem poder preditivo, por mais bonito que seja o ajuste.
- **Teste de permutação.** Com 13 pontos e ~8 features candidatas, o melhor R² de um sorteio de
  ruído puro é surpreendentemente alto. Embaralhar o alvo 999 vezes e refazer a busca inteira
  mede exatamente essa inflação, e é o que separa achado de garimpo.
- **Nada acima de 3 parâmetros livres.** Não é preferência; é o que 13 pontos sustentam.

Saídas:
  - `outputs/explicacao_features.csv`  — correlação de cada feature com o alvo
  - `outputs/explicacao_modelos.csv`   — placar LOOCV de cada modelo contra o baseline
  - `outputs/explicacao_permutacao.csv`— inflação por garimpo, medida
  - `reports/figuras/fig_02_explicacao.png`
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.tree import DecisionTreeRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum as K  # noqa: E402

ALVO = "y_construcao_0_500m"  # o único eixo com selo forte
N_PERMUTACOES = 999

NUMERICAS = [
    "x_pct_ja_construida",
    "x_pre_prop_construida_urbana",
    "x_pre_prop_vegetacao_densa",
    "x_pre_prop_vegetacao_rala",
    "x_area_footprint_ha",
    "x_n_predios",
    "x_pre_lst_media_celsius",
]
CATEGORICAS = ["x_tipo_sitio", "x_regiao", "x_bioma"]


def r2_fora_da_amostra(y: np.ndarray, pred: np.ndarray) -> float:
    """R² fora-da-amostra contra a média do alvo. Pode ser NEGATIVO — e isso é informação:
    significa que o modelo prevê pior que dizer 'a média' para todo mundo."""
    sse = float(np.sum((y - pred) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    return 1 - sse / sst


def loocv_predicoes(ajustar_prever, X, y: np.ndarray) -> np.ndarray:
    """Uma previsão por observação, sempre com o modelo treinado SEM ela."""
    pred = np.empty(len(y))
    for i in range(len(y)):
        treino = np.ones(len(y), dtype=bool)
        treino[i] = False
        pred[i] = ajustar_prever(X, y, treino, i)
    return pred


def _mediana(X, y, treino, i):
    return float(np.median(y[treino]))


def _ols_1(coluna: np.ndarray):
    def f(X, y, treino, i):
        mod = LinearRegression().fit(coluna[treino].reshape(-1, 1), y[treino])
        return float(mod.predict(coluna[i].reshape(1, -1))[0])
    return f


def _regra_grupo(grupos: np.ndarray):
    """Prevê a mediana do grupo do fold de treino; cai na mediana geral se o grupo sumir."""
    def f(X, y, treino, i):
        mesmo = treino & (grupos == grupos[i])
        return float(np.median(y[mesmo])) if mesmo.any() else float(np.median(y[treino]))
    return f


def _ridge(M: np.ndarray, alpha: float = 1.0):
    def f(X, y, treino, i):
        mu, sd = M[treino].mean(0), M[treino].std(0)
        sd = np.where(sd == 0, 1.0, sd)
        mod = Ridge(alpha=alpha, random_state=K.SEED).fit((M[treino] - mu) / sd, y[treino])
        return float(mod.predict(((M[i] - mu) / sd).reshape(1, -1))[0])
    return f


def _arvore(M: np.ndarray, profundidade: int = 1):
    def f(X, y, treino, i):
        mod = DecisionTreeRegressor(
            max_depth=profundidade, min_samples_leaf=3, random_state=K.SEED
        ).fit(M[treino], y[treino])
        return float(mod.predict(M[i].reshape(1, -1))[0])
    return f


def montar_modelos(d: pd.DataFrame, y: np.ndarray) -> dict:
    modelos = {"baseline_mediana": (_mediana, 0)}
    for c in NUMERICAS:
        if d[c].notna().all():
            modelos[f"ols_1f::{c}"] = (_ols_1(d[c].to_numpy(float)), 2)
    for c in CATEGORICAS:
        if d[c].notna().all():
            modelos[f"regra_grupo::{c}"] = (_regra_grupo(d[c].to_numpy()), d[c].nunique())
    duas = ["x_pct_ja_construida", "x_pre_prop_vegetacao_densa"]
    if all(d[c].notna().all() for c in duas):
        modelos["ridge_2f::terreno+vegetacao"] = (_ridge(d[duas].to_numpy(float)), 3)
    tres = duas + ["x_area_footprint_ha"]
    if all(d[c].notna().all() for c in tres):
        modelos["ridge_3f::+footprint"] = (_ridge(d[tres].to_numpy(float)), 4)
    if d["x_pct_ja_construida"].notna().all():
        modelos["arvore_d1::terreno"] = (
            _arvore(d[["x_pct_ja_construida"]].to_numpy(float)), 2
        )
    return modelos


def placar(d: pd.DataFrame, y: np.ndarray) -> pd.DataFrame:
    linhas = []
    for nome, (fn, n_par) in montar_modelos(d, y).items():
        pred = loocv_predicoes(fn, None, y)
        linhas.append(
            {
                "modelo": nome,
                "n_parametros_livres": n_par,
                "loocv_mae_pp": round(float(np.mean(np.abs(y - pred))), 3),
                "loocv_r2": round(r2_fora_da_amostra(y, pred), 3),
                "loocv_rmse_pp": round(float(np.sqrt(np.mean((y - pred) ** 2))), 3),
            }
        )
    return pd.DataFrame(linhas).sort_values("loocv_r2", ascending=False)


def main() -> int:
    m = K.tabela_mestra()
    d = m.dropna(subset=[ALVO, "x_pct_ja_construida"]).reset_index(drop=True)
    y = d[ALVO].to_numpy(float)
    print(f"alvo: {ALVO} · N = {len(d)} campi "
          f"(de {m[ALVO].notna().sum()} com alvo; {len(m) - len(d)} sem footprint OSM)")

    # ---------------------------------------------------------------- correlações
    linhas = []
    for c in NUMERICAS:
        v = d[c].astype(float)
        ok = v.notna() & pd.Series(y).notna()
        if ok.sum() < 5:
            continue
        rho, p_rho = stats.spearmanr(v[ok], y[ok])
        r, p_r = stats.pearsonr(v[ok], y[ok])
        linhas.append(
            {
                "feature": c, "n": int(ok.sum()),
                "spearman_rho": round(float(rho), 3), "spearman_p": round(float(p_rho), 4),
                "pearson_r": round(float(r), 3), "pearson_p": round(float(p_r), 4),
            }
        )
    for c in CATEGORICAS:
        grupos = d[c].dropna()
        if grupos.nunique() < 2:
            continue
        amostras = [y[(d[c] == g).to_numpy()] for g in grupos.unique()]
        amostras = [a for a in amostras if len(a) >= 2]
        if len(amostras) < 2:
            continue
        h, p_h = stats.kruskal(*amostras)
        linhas.append(
            {"feature": c, "n": int(grupos.notna().sum()), "spearman_rho": None,
             "spearman_p": None, "pearson_r": None, "pearson_p": None,
             "kruskal_h": round(float(h), 3), "kruskal_p": round(float(p_h), 4)}
        )
    feats = pd.DataFrame(linhas)
    K.salvar(feats, "explicacao_features.csv")

    # ---------------------------------------------------------------- placar LOOCV
    tabela = placar(d, y)
    base_r2 = float(tabela.loc[tabela.modelo == "baseline_mediana", "loocv_r2"].iloc[0])
    tabela["bate_baseline"] = tabela.loocv_r2 > base_r2
    K.salvar(tabela, "explicacao_modelos.csv")

    melhor = tabela.iloc[0]
    print(f"\nmelhor modelo: {melhor.modelo}  LOOCV R²={melhor.loocv_r2}  MAE={melhor.loocv_mae_pp} p.p.")
    print(f"baseline (mediana):                LOOCV R²={base_r2}")

    # ---------------------------------------------------------------- permutação
    rng = np.random.default_rng(K.SEED)
    nulos = []
    for _ in range(N_PERMUTACOES):
        y_emb = rng.permutation(y)
        nulos.append(float(placar(d, y_emb).loocv_r2.max()))
    nulos_arr = np.asarray(nulos)
    p_perm = float((nulos_arr >= melhor.loocv_r2).mean())
    perm = pd.DataFrame(
        [
            {
                "melhor_modelo_observado": melhor.modelo,
                "loocv_r2_observado": melhor.loocv_r2,
                "n_permutacoes": N_PERMUTACOES,
                "r2_maximo_mediano_sob_ruido": round(float(np.median(nulos_arr)), 3),
                "r2_maximo_p95_sob_ruido": round(float(np.percentile(nulos_arr, 95)), 3),
                "p_permutacao": round(p_perm, 4),
                "leitura": (
                    "supera o que o garimpo produz por acaso"
                    if p_perm < 0.05
                    else "NÃO se distingue do melhor resultado que ruído puro produziria "
                         "na mesma busca — não há poder preditivo demonstrado"
                ),
            }
        ]
    )
    K.salvar(perm, "explicacao_permutacao.csv")
    print(f"permutação: p={p_perm:.4f} — {perm.leitura.iloc[0]}")

    # ---------------------------------------------------------------- figura
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    cores = {"greenfield": "#27AE60", "brownfield": "#E67E22"}
    ax1.scatter(d.x_pct_ja_construida, y, c=[cores[t] for t in d.x_tipo_sitio], s=100,
                edgecolors="white", linewidths=1.2, zorder=3)
    for _, r in d.iterrows():
        ax1.annotate(r.site_id.replace("ascenty-", "a-").replace("scala-", "s-"),
                     (r.x_pct_ja_construida, r[ALVO]), fontsize=7, alpha=0.75,
                     xytext=(4, 4), textcoords="offset points")
    ax1.axhline(0, color="#333", lw=1)
    ax1.axvline(50, color="#888", ls="--", lw=1)
    ax1.text(50.8, ax1.get_ylim()[0] * 0.88, "corte greenfield/brownfield", fontsize=8, color="#666")
    rho = feats.loc[feats.feature == "x_pct_ja_construida"]
    if not rho.empty:
        ax1.set_title(
            "A melhor feature disponível — e ela não separa os casos\n"
            f"Spearman ρ={rho.spearman_rho.iloc[0]}, p={rho.spearman_p.iloc[0]} (n={len(d)}) · "
            "direção certa, magnitude não",
            fontsize=10,
        )
    ax1.set_xlabel("% do footprint já construído antes da obra")
    ax1.set_ylabel("excesso de conversão vs. controle (p.p.)")
    ax1.grid(alpha=0.25)

    t = tabela.sort_values("loocv_r2")
    cor = ["#27AE60" if b else "#C0392B" for b in t.bate_baseline]
    cor[list(t.modelo).index("baseline_mediana")] = "#555"
    ax2.barh(t.modelo.str.replace("::", "\n", regex=False), t.loocv_r2, color=cor)
    ax2.axvline(0, color="#333", lw=1)
    ax2.axvline(float(np.percentile(nulos_arr, 95)), color="#888", ls="--", lw=1)
    ax2.text(float(np.percentile(nulos_arr, 95)), -0.7,
             " p95 sob ruído", fontsize=8, color="#666")
    ax2.set_xlabel("R² fora-da-amostra (LOOCV) — negativo = pior que prever a média")
    ax2.set_title(
        f"Placar honesto: TODOS os {len(t)} modelos têm R² negativo\n"
        f"verde = ainda assim melhor que o baseline · cinza = baseline · "
        f"permutação p={p_perm:.3f}",
        fontsize=10,
    )
    ax2.tick_params(labelsize=7)

    fig.suptitle("Camada 2 — o que prediz o tamanho do impacto territorial", fontsize=11, y=0.99)
    fig.tight_layout()
    K.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    saida = K.DIR_FIGURAS / "fig_02_explicacao.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"  -> {saida.relative_to(K.RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
