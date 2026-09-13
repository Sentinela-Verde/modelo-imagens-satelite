"""Passo 41 — o achado sobrevive ao NOSSO classificador melhor, medido nos mesmos pares?

Rode com (a ordem importa — o passo 26 do candidato precisa existir antes):

    python -m sentinela.predict --modelo models/rf_v2.0-dw.joblib --sensor all --site all \
        --saida-token classificado-rf_v2.0-dw
    SENTINELA_MODELO_IMPACTO=rf_v2.0-dw \
        python dados-modelo-impacto/scripts/impacto_dc_26_analise_expandida.py --fase analise
    python dados-modelo-impacto/scripts/impacto_dc_41_cruzar_classificador.py

## A pergunta que os passos 24 e 29 deixaram em aberto

O passo 24 refez a medição com o **Dynamic World** e o achado **não replicou** (9/14,
p=0,212). Mas o DW difere do nosso RF em três coisas ao mesmo tempo — fonte de rótulo,
arquitetura e resolução (10 m contra 30 m) — então a não-replicação não diz **qual** das três
é responsável. É um resultado importante e ambíguo.

O `rf_v2.0-dw` desfaz essa ambiguidade porque muda **uma** coisa: é o mesmo algoritmo, na mesma
grade, nos mesmos pixels, treinado com rótulo do DW em vez do MapBiomas.

| instrumento | rótulo | arquitetura | resolução |
|---|---|---|---|
| `rf_v1.0-tuned` | MapBiomas | nosso RF | a do raster |
| **`rf_v2.0-dw`** | **Dynamic World** | **nosso RF** | **a do raster** |
| Dynamic World | Dynamic World | CNN do Google | 10 m nativos |

Se o achado reaparece com o `rf_v2.0-dw`, a não-replicação do passo 24 é sobre **modelo e
geometria**, não sobre a fonte de rótulo. Se não reaparece, o achado depende do classificador
treinado com MapBiomas — e isso precisa estar dito antes da apresentação, não depois.

## O que deu (2026-09-12), anel 0,5–1 km, os MESMOS 10 pares

| instrumento | pares positivos | p | excesso mediano |
|---|---:|---:|---:|
| `rf_v1.0-tuned` (MapBiomas, nosso RF) | 10/10 | 0,0010 | +1,589 p.p. |
| `rf_v2.0-dw` (Dynamic World, nosso RF) | 8/10 | 0,0547 | **+2,204 p.p.** |
| `dynamic_world` (CNN do Google, 10 m) | 6/10 | 0,3770 | **+0,180 p.p.** |

**Trocar só o rótulo não encolhe o efeito — aumenta.** Trocar o modelo colapsa o efeito 12×. A
discordância do passo 24 é do **modelo**, não da fonte de rótulo. (Resolução já tinha sido
descartada no próprio passo 24: degradar o DW de 10 m para 30 m por moda não moveu a mediana.)

**O p do `rf_v2.0-dw` cai sem que a magnitude caia, e isso não é contradição.** O teste de sinal
conta sinais e descarta magnitude; com n=10 ele exige 9/10 para p<0,05. Os dois campi que trocam
de lado — `ascenty-osasco` (+0,390) e `ascenty-vinhedo` (+0,056) — são **exatamente os dois de
menor efeito no v1.0**. Perto de zero, trocar de lado é ruído. Por isso este passo imprime a
tabela por campus: julgar o cruzamento só pelo p-valor leria errado o próprio dado.

**O que isto NÃO diz:** qual dos dois instrumentos está certo. Uma CNN com contexto espacial
suaviza, e suavizar apaga conversão pequena real tão bem quanto apaga ruído. O que os três
concordam é a **direção** — mediana positiva nos três. A magnitude varia 12×.

## Por que 10 pares e não 20

O critério §4 (passo 29/30) só reclassificou os controles que o **Dynamic World cobre**, porque
é onde os instrumentos são comparáveis. Reclassificar um controle custa reingerir a imagem do
Earth Engine — os intermediários dele são descartados de propósito. Sobram os 10 pares cuja
janela `obra-3..obra+3` cai inteira de 2016 em diante.

**Esses 10 não são uma amostra aleatória dos 20:** são os de obra mais recente. Por isso este
passo NÃO compara "v2.0 em 10 pares" com "v1.0 em 20 pares" — isso confundiria troca de
instrumento com troca de amostra. Ele roda o teste **nos mesmos 10 pares nos três
instrumentos**, e reporta o v1.0 nos 20 apenas como referência rotulada.

Saídas:
  - `raw/controles-rf/cruzamento_classificador.csv`
  - `raw/controles-rf/figuras/fig_21_cruzamento_classificador.png`
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
import impacto_dc_comum as C  # noqa: E402

MODELO_A = "rf_v1.0-tuned"
MODELO_B = "rf_v2.0-dw"
MODELO_C = "dynamic_world"

CSV_A = C.DIR_SAIDA / "analise_expandida.csv"
CSV_B = C.DIR_SAIDA / f"analise_expandida__{MODELO_B}.csv"
# O terceiro instrumento vem do passo 24, que ja mediu o mesmo anel por campus na grade nativa
# de 10 m. Reaproveitar essa tabela e o que permite pôr os três na MESMA amostra de pares.
CSV_C = C.DIR_SAIDA / "dw_trajetoria.csv"

SAIDA = C.DIR_SAIDA / "cruzamento_classificador.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_21_cruzamento_classificador.png"

ZONA_DESTAQUE = "0.5-1km"
ASSINATURA = "virou_construida"


def diferencas(longo: pd.DataFrame, zona: str, campi: set[str] | None = None) -> dict[str, float]:
    """Excesso tratamento − controle, em p.p., por campus. Mesma conta do passo 26."""
    col = f"pct_{ASSINATURA}"
    g = longo[longo.zona == zona]
    if campi is not None:
        g = g[g.campus.isin(campi)]
    saida = {}
    for campus, par in g.groupby("campus"):
        t = par[par.tipo == "tratamento"][col]
        c = par[par.tipo == "controle"][col]
        if t.empty or c.empty or t.isna().all() or c.isna().all():
            continue
        saida[campus] = float(t.iloc[0] - c.iloc[0])
    return saida


def diferencas_dw(zona: str, campi: set[str]) -> dict[str, float]:
    """O mesmo excesso, lido da tabela por campus do passo 24 (grade nativa de 10 m).

    O passo 24 grava tratamento e controle como linhas separadas do mesmo campus, com a coluna
    `pct_virou_construida` já calculada — a mesma quantidade que `diferencas` monta a partir do
    CSV do passo 26. A conta da diferença é idêntica; só a fonte da porcentagem muda.
    """
    if not CSV_C.exists():
        return {}
    d = pd.read_csv(CSV_C)
    d = d[(d.raio_km == zona) & d.campus.isin(campi)]
    saida = {}
    for campus, par in d.groupby("campus"):
        t = par[par.tipo == "tratamento"]["pct_virou_construida"]
        c = par[par.tipo == "controle"]["pct_virou_construida"]
        if t.empty or c.empty or t.isna().all() or c.isna().all():
            continue
        saida[campus] = float(t.iloc[0] - c.iloc[0])
    return saida


def teste_de_sinal(difs: list[float]) -> tuple[int, int, float, float]:
    """(n, k positivos, p unilateral, excesso mediano). Binomial exata, H0: p=0,5."""
    d = np.asarray(difs, dtype=float)
    n, k = len(d), int((d > 0).sum())
    p = sum(math.comb(n, i) * 0.5**n for i in range(k, n + 1))
    return n, k, p, float(np.median(d))


def main() -> int:
    if not CSV_B.exists():
        print(f"ERRO: {CSV_B.name} não existe.\n"
              f"Rode antes o passo 26 com SENTINELA_MODELO_IMPACTO={MODELO_B} "
              f"(e, antes dele, `sentinela.predict --saida-token classificado-{MODELO_B}`).",
              file=sys.stderr)
        return 1

    a = pd.read_csv(CSV_A)
    b = pd.read_csv(CSV_B)

    campi_a = set(a.campus.unique())
    campi_b = set(b.campus.unique())
    comuns = campi_a & campi_b
    print(f"{MODELO_A}: {len(campi_a)} campi   ·   {MODELO_B}: {len(campi_b)} campi   ·   "
          f"medidos pelos dois: {len(comuns)}")
    so_a = sorted(campi_a - comuns)
    if so_a:
        print(f"  fora do cruzamento (controle sem raster do candidato): {so_a}")

    linhas = []
    for zona in sorted(a.zona.unique()):
        # o pareado: mesmos campi, os dois instrumentos
        for modelo in (MODELO_A, MODELO_B, MODELO_C):
            if modelo == MODELO_C:
                d = diferencas_dw(zona, comuns)
            else:
                d = diferencas(a if modelo == MODELO_A else b, zona, comuns)
            if len(d) < 3:
                continue
            n, k, p, med = teste_de_sinal(list(d.values()))
            linhas.append({
                "recorte": "mesmos_pares", "zona": zona, "modelo": modelo,
                "n_pares": n, "n_positivo": k, "frac_positivo": round(k / n, 3),
                "p_unilateral": round(p, 4), "excesso_mediano_pp": round(med, 4),
            })
        # a referência publicada, rotulada como amostra diferente
        d = diferencas(a, zona)
        if len(d) >= 3:
            n, k, p, med = teste_de_sinal(list(d.values()))
            linhas.append({
                "recorte": "amostra_publicada", "zona": zona, "modelo": MODELO_A,
                "n_pares": n, "n_positivo": k, "frac_positivo": round(k / n, 3),
                "p_unilateral": round(p, 4), "excesso_mediano_pp": round(med, 4),
            })

    res = pd.DataFrame(linhas)
    C.salvar_csv(res, SAIDA)

    # ------------------------------------------------------------------ o que o passo responde
    destaque = res[(res.zona == ZONA_DESTAQUE) & (res.recorte == "mesmos_pares")]
    print(f"\n=== anel {ZONA_DESTAQUE}, os mesmos {len(comuns)} pares, três instrumentos ===")
    for _, r in destaque.iterrows():
        print(f"  {r.modelo:16s} {int(r.n_positivo)}/{int(r.n_pares)}  "
              f"p={r.p_unilateral:.4f}  excesso mediano {r.excesso_mediano_pp:+.3f} p.p.")

    # O teste de sinal conta sinais e joga a magnitude fora. Com n=10 ele exige 9/10 para
    # p<0,05, então dois campi que já estavam perto de zero trocando de lado derrubam o p sem
    # que o tamanho do efeito tenha mudado. Ler só o p, aqui, lê errado o próprio dado — por
    # isso a tabela por campus vem junto, e é ela que sustenta qualquer conclusão.
    da = diferencas(a, ZONA_DESTAQUE, comuns)
    db = diferencas(b, ZONA_DESTAQUE, comuns)
    dc = diferencas_dw(ZONA_DESTAQUE, comuns)
    print(f"\n{'campus':28s} {MODELO_A:>13s} {MODELO_B:>13s} {MODELO_C:>15s}")
    for campus in sorted(comuns):
        v_c = f"{dc[campus]:+15.3f}" if campus in dc else f"{'—':>15s}"
        print(f"{campus:28s} {da[campus]:+13.3f} {db[campus]:+13.3f} {v_c}")

    concordam = sum(1 for k in da if k in db and da[k] > 0 and db[k] > 0)
    discordam = sorted(k for k in da if k in db and (da[k] > 0) != (db[k] > 0))
    print(f"\n  mesmo sinal nos dois RF: {concordam}/{len(da)}")
    if discordam:
        print("  trocam de sinal        : "
              + ", ".join(f"{k} (v1.0 {da[k]:+.3f} p.p.)" for k in discordam))
        menores = sorted(da, key=lambda k: abs(da[k]))[: len(discordam)]
        if set(menores) == set(discordam):
            limiar = max(abs(da[k]) for k in discordam)
            print(f"  -> e são exatamente os {len(discordam)} campi de MENOR efeito no v1.0 "
                  f"(|excesso| <= {limiar:.3f} p.p.).")
            print("     Trocar de lado perto de zero é ruído, não contradição — e é por isso "
                  "que o p cai\n     sem que a magnitude caia.")

    # ------------------------------------------------------------------ figura
    zonas = sorted(a.zona.unique())
    fig, axes = plt.subplots(1, len(zonas), figsize=(4.6 * len(zonas), 4.8), sharey=True)
    axes = np.atleast_1d(axes)
    cor = {MODELO_A: "#1A5276", MODELO_B: "#C0392B", MODELO_C: "#7F8C8D"}
    for ax, zona in zip(axes, zonas):
        s = res[(res.zona == zona) & (res.recorte == "mesmos_pares")]
        if s.empty:
            ax.set_axis_off()
            continue
        x = np.arange(len(s))
        ax.bar(x, s.excesso_mediano_pp, color=[cor[m] for m in s.modelo], width=0.55)
        for i, (_, r0) in enumerate(s.iterrows()):
            texto_p = (f"p={r0.p_unilateral:.4f}" if r0.p_unilateral < 0.001
                       else f"p={r0.p_unilateral:.3f}")
            ax.text(i, r0.excesso_mediano_pp, f"{int(r0.n_positivo)}/{int(r0.n_pares)}\n{texto_p}",
                    ha="center", va="bottom", fontsize=8)
        ax.axhline(0, color="#333", lw=1)
        ax.set_xticks(x)
        ax.set_xticklabels([m.replace("rf_", "").replace("dynamic_world", "DW 10 m")
                            for m in s.modelo], fontsize=8)
        ax.set_title(f"anel {zona}", fontsize=10)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("excesso mediano de conversão (p.p.)")
    for ax in axes:
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi * 1.18)
    fig.suptitle(f"Passo 41 — o mesmo teste, os mesmos {len(comuns)} pares, três instrumentos",
                 fontsize=11, y=0.99)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
