"""Camada 3 — PROJEÇÃO. Dado um site novo, em que faixa de impacto ele deve cair?

Rode com:

    python modelo-impacto-score/scripts/03_projecao.py                    # valida e publica as faixas
    python modelo-impacto-score/scripts/03_projecao.py --pct-ja-construida 15   # projeta um site novo

## Por que isto NÃO é uma previsão pontual

A camada 2 mediu, e o resultado foi negativo: com N=13, **nenhum** modelo supera o baseline de
prever a mediana. Todos os R² fora-da-amostra são negativos e o teste de permutação dá p=0,64 — o
melhor ajuste encontrado é indistinguível do que ruído puro produz na mesma busca. A **magnitude**
do impacto não é predizível a partir das features pré-obra que temos.

Isso NÃO anula o achado do passo 15. São perguntas diferentes, e as duas respostas estão certas:

  - "a DIREÇÃO é consistente?"   -> sim: 6/6 pares greenfield positivos, p=0,016 (teste de sinal)
  - "a MAGNITUDE é predizível?"  -> não: R² LOOCV negativo em todos os modelos

Então a projeção honesta não é um número, é uma **classe de referência**: em vez de prever quanto
este site vai converter, reporta-se o que sítios comparáveis de fato produziram — quantos foram
positivos, e em que faixa. Uma previsão de classe de referência continua válida quando a regressão
individual falha, porque ela não afirma nada sobre o caso; afirma sobre a taxa-base do grupo.

## Como isto é validado

Não por R² — intervalo não se valida por R². Valida-se por **cobertura**: deixando cada campus de
fora, a faixa projetada pelos outros contém o valor observado? Uma faixa de 15-85% bem calibrada
cobre ~70% dos casos retidos. Cobrir 100% significa faixa larga demais para ser útil; cobrir 30%
significa faixa que mente.

Saídas:
  - `outputs/projecao_classes_referencia.csv` — a faixa de cada classe
  - `outputs/projecao_validacao.csv`          — cobertura LOOCV, contra a classe única
  - `reports/figuras/fig_03_projecao.png`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum as K  # noqa: E402

ALVO = "y_construcao_0_500m"
CORTE_GREENFIELD = 50.0  # % do footprint já construído (passo 15 de dados-modelo-impacto)
PCT_BAIXO, PCT_ALTO = 15, 85


def classe_de(pct_ja_construida: float | None) -> str:
    if pct_ja_construida is None or (isinstance(pct_ja_construida, float) and np.isnan(pct_ja_construida)):
        return "indeterminado"
    return "greenfield" if pct_ja_construida < CORTE_GREENFIELD else "brownfield"


def faixa(valores: np.ndarray) -> dict:
    return {
        "n": int(len(valores)),
        "n_positivo": int((valores > 0).sum()),
        "frac_positivo": round(float((valores > 0).mean()), 3),
        "mediana_pp": round(float(np.median(valores)), 3),
        "p15_pp": round(float(np.percentile(valores, PCT_BAIXO)), 3),
        "p85_pp": round(float(np.percentile(valores, PCT_ALTO)), 3),
        "min_pp": round(float(valores.min()), 3),
        "max_pp": round(float(valores.max()), 3),
    }


def projetar(d: pd.DataFrame, pct: float | None, usar_classe: bool = True) -> dict:
    """Faixa esperada para um site com este `pct_ja_construida`, a partir dos análogos."""
    cls = classe_de(pct)
    if usar_classe and cls != "indeterminado":
        sub = d[d.x_tipo_sitio == cls]
        if len(sub) < 3:  # classe pequena demais para dar faixa; cai para a amostra inteira
            sub, cls = d, "amostra_completa"
    else:
        sub, cls = d, "amostra_completa"
    return {"classe_referencia": cls, **faixa(sub[ALVO].to_numpy(float))}


def validar(d: pd.DataFrame) -> pd.DataFrame:
    """Cobertura LOOCV da faixa, com e sem condicionar na classe."""
    linhas = []
    for usar_classe in (True, False):
        cobertos, larguras = [], []
        for i in range(len(d)):
            treino = d.drop(index=d.index[i])
            alvo = float(d[ALVO].iloc[i])
            p = projetar(treino, d.x_pct_ja_construida.iloc[i], usar_classe=usar_classe)
            cobertos.append(p["p15_pp"] <= alvo <= p["p85_pp"])
            larguras.append(p["p85_pp"] - p["p15_pp"])
        linhas.append(
            {
                "estrategia": "condicionada_no_tipo_de_sitio" if usar_classe else "classe_unica",
                "n": len(d),
                "cobertura_faixa_15_85": round(float(np.mean(cobertos)), 3),
                "cobertura_nominal": (PCT_ALTO - PCT_BAIXO) / 100,
                "largura_mediana_pp": round(float(np.median(larguras)), 3),
            }
        )
    t = pd.DataFrame(linhas)
    nominal = (PCT_ALTO - PCT_BAIXO) / 100
    cond, unica = t.iloc[0], t.iloc[1]
    estreitou = unica.largura_mediana_pp - cond.largura_mediana_pp
    # Uma faixa mais estreita só é melhor se continuar cobrindo. Estreitar perdendo cobertura é
    # uma faixa que mente — e com subgrupos de n=6/n=7 os percentis ficam instáveis, que é
    # exatamente o modo de falha esperado aqui.
    perdeu_cobertura = cond.cobertura_faixa_15_85 < nominal - 0.10
    t["leitura"] = [
        (
            f"condicionar estreita a faixa em só {estreitou:+.2f} p.p. e DERRUBA a cobertura para "
            f"{cond.cobertura_faixa_15_85:.0%} (nominal {nominal:.0%}) — faixa estreita demais "
            "para o que ela afirma; não use"
            if perdeu_cobertura
            else f"condicionar estreita a faixa em {estreitou:+.2f} p.p. mantendo cobertura"
        ),
        f"cobertura {unica.cobertura_faixa_15_85:.0%} contra nominal {nominal:.0%} — calibrada; "
        "é esta que deve ser usada" if abs(unica.cobertura_faixa_15_85 - nominal) <= 0.10
        else f"cobertura {unica.cobertura_faixa_15_85:.0%} contra nominal {nominal:.0%} — descalibrada",
    ]
    t["recomendada"] = [not perdeu_cobertura, perdeu_cobertura]
    return t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pct-ja-construida", type=float, default=None,
                    help="%% do terreno do footprint já construído antes da obra (0-100)")
    args = ap.parse_args()

    m = K.tabela_mestra()
    d = m.dropna(subset=[ALVO, "x_pct_ja_construida", "x_tipo_sitio"]).reset_index(drop=True)
    print(f"análogos históricos disponíveis: {len(d)} campi")

    if args.pct_ja_construida is not None:
        cls = classe_de(args.pct_ja_construida)
        # A FAIXA vem da amostra completa (é a única calibrada — ver projecao_validacao.csv);
        # a TAXA-BASE vem da classe do sítio (é onde o achado direcional de fato está).
        f_calibrada = projetar(d, args.pct_ja_construida, usar_classe=False)
        f_classe = projetar(d, args.pct_ja_construida, usar_classe=True)
        print(f"\n--- projeção para um site com {args.pct_ja_construida:.0f}% já construído "
              f"({cls}) ---")
        print(f"direção   — {f_classe['n_positivo']}/{f_classe['n']} dos análogos "
              f"{f_classe['classe_referencia']} converteram MAIS que seu controle "
              f"({f_classe['frac_positivo']:.0%})")
        print(f"magnitude — faixa 15–85%: {f_calibrada['p15_pp']:+.2f} a "
              f"{f_calibrada['p85_pp']:+.2f} p.p., mediana {f_calibrada['mediana_pp']:+.2f} p.p.")
        print(f"            (faixa da amostra completa, n={f_calibrada['n']} — é a única com "
              "cobertura calibrada; condicionar no tipo de sítio derruba a cobertura para 46%)")
        print("\nlembrete obrigatório: é a taxa-base de uma classe de referência, NÃO uma previsão "
              "deste site. A magnitude individual não é predizível com as features disponíveis "
              "(camada 2: R² LOOCV negativo em todos os modelos, permutação p=0,64).")
        return 0

    linhas = []
    for cls in ("greenfield", "brownfield"):
        sub = d[d.x_tipo_sitio == cls]
        linhas.append({"classe_referencia": cls, **faixa(sub[ALVO].to_numpy(float))})
    linhas.append({"classe_referencia": "amostra_completa", **faixa(d[ALVO].to_numpy(float))})
    classes = pd.DataFrame(linhas)
    K.salvar(classes, "projecao_classes_referencia.csv")

    val = validar(d)
    K.salvar(val, "projecao_validacao.csv")
    print("\n--- classes de referência ---")
    print(classes.to_string(index=False))
    print("\n--- validação por cobertura ---")
    print(val.to_string(index=False))

    # ---------------------------------------------------------------- figura
    fig, ax = plt.subplots(figsize=(10, 4.2))
    cores = {"greenfield": "#27AE60", "brownfield": "#E67E22", "amostra_completa": "#7F8C8D"}
    for i, r in classes.iterrows():
        ax.plot([r.p15_pp, r.p85_pp], [i, i], color=cores[r.classe_referencia], lw=9, alpha=0.35,
                solid_capstyle="butt")
        ax.plot([r.min_pp, r.max_pp], [i, i], color=cores[r.classe_referencia], lw=1.5, alpha=0.8)
        ax.scatter([r.mediana_pp], [i], color=cores[r.classe_referencia], s=140, zorder=3,
                   edgecolors="white", linewidths=1.5)
        sub = (d if r.classe_referencia == "amostra_completa"
               else d[d.x_tipo_sitio == r.classe_referencia])
        ax.scatter(sub[ALVO], [i] * len(sub), color="#333", s=22, zorder=4, alpha=0.75)
    ax.axvline(0, color="#333", lw=1.2)
    ax.set_yticks(range(len(classes)))
    ax.set_yticklabels([f"{r.classe_referencia}\n(n={r.n}, {r.n_positivo} positivos)"
                        for _, r in classes.iterrows()], fontsize=9)
    ax.set_xlabel("excesso de conversão para construída vs. controle, anel 0–500 m (p.p.)")
    cob_unica = float(val.loc[val.estrategia == "classe_unica", "cobertura_faixa_15_85"].iloc[0])
    cob_cond = float(
        val.loc[val.estrategia == "condicionada_no_tipo_de_sitio", "cobertura_faixa_15_85"].iloc[0]
    )
    ax.set_title(
        "Camada 3 — faixa esperada por classe de referência, não previsão pontual\n"
        "barra grossa = faixa 15–85% · linha fina = amplitude observada · pontos = casos\n"
        f"cobertura LOOCV: amostra completa {cob_unica:.0%} (calibrada, nominal 70%) · "
        f"condicionada no tipo de sítio {cob_cond:.0%} (não usar)",
        fontsize=9.5,
    )
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    K.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    saida = K.DIR_FIGURAS / "fig_03_projecao.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"\n  -> {saida.relative_to(K.RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
