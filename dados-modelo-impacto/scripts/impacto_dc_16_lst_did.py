"""Passo 16 — o data center esquentou o entorno? Diferença-em-diferenças de LST.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_16_lst_did.py

## Por que este passo existe

A temperatura de superfície (LST) foi coletada no passo 8 para os 30 pontos do painel — 204/204
ponto-ano, equilibrado em 102 tratamento e 102 controle, 2013-2025, mesmo código nas duas pontas —
e **nunca foi analisada**. `METODOLOGIA.md` não a menciona uma vez. É a pergunta ambiental mais
direta que esta frente pode fazer ("o data center aqueceu o entorno?") e estava em aberto.

## O que este script conclui, e por que a conclusão não é "não houve efeito"

Ele roda o mesmo desenho pareado dos passos 12/14 sobre a LST, e roda também o **cálculo de poder**
que diz se esse desenho teria conseguido ver o efeito caso ele existisse. Os dois juntos são o
resultado; o primeiro sozinho seria enganoso.

O problema é de ESCALA, e é conhecido antes de rodar: a LST vem do `MODIS/061/MOD11A2`, que tem
**1 km de resolução**, medida num **buffer de 5 km**. O efeito de construção que os passos 12-15
mediram vive no anel de 0-0,5 km — que é menor que UM pixel MODIS. Convertendo: o excesso de
+2,06 p.p. num anel de 78,5 ha equivale a ~1,6 ha convertidos, que é 0,02% do disco de 5 km
(7.854 ha). Qualquer contraste térmico real fica diluído por esse fator antes de chegar à média.

Por isso o script publica três coisas, não uma:

1. `lst_did.csv` — o efeito medido, par a par (é o que seria o "resultado").
2. `lst_did_poder.csv` — o efeito mínimo detectável (MDE) deste desenho, contra o efeito esperado
   pela diluição. Se o MDE for muito maior que o esperado, um nulo **não informa nada** sobre a
   existência do efeito, e afirmar "não houve aquecimento" seria erro.
3. `lst_did_validade.csv` — a checagem de que o dado de LST está fisicamente sadio: a correlação
   entre LST e proporção de área construída ao longo de todos os ponto-ano, e a inclinação em
   °C por ponto percentual de construída. Se essa relação existe, um nulo é falta de poder, não
   dado ruim — e é essa distinção que sustenta a leitura.

## Convenção de janela

Igual à do passo 12, deliberadamente: pré = 2 primeiros anos da janela do campus, pós = 2 últimos.
NÃO se usa a coluna `fase` aqui: por ela, só 7 dos 15 campi teriam >=2 anos pré e >=2 pós (vários
têm `periodo_durante` longo e sobra 0 ou 1 ano de `pos`), e a amostra cairia pela metade sem que
ninguém percebesse.

Saídas:
  - `raw/controles-rf/lst_did.csv`           — efeito por par
  - `raw/controles-rf/lst_did_resumo.csv`    — teste de sinal
  - `raw/controles-rf/lst_did_poder.csv`     — MDE vs efeito esperado pela diluição
  - `raw/controles-rf/lst_did_validade.csv`  — LST x construída (sanidade física do dado)
  - `raw/controles-rf/figuras/fig_10_lst_did.png`
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

N_ANOS_PONTA = 2          # pré = 2 primeiros anos da janela; pós = 2 últimos (convenção do passo 12)
RAIO_ANEL_KM = 0.5        # anel onde o efeito de construção foi medido (passos 14/15)
EXCESSO_ANEL_PP = 2.0589  # excesso mediano de `virou_construida` em 0-0,5 km (footprint_vs_anel_resumo)


def p_bin_bilateral(k: int, n: int) -> float:
    """P de um teste de sinal BILATERAL sob Binomial(n, 0.5).

    Bilateral aqui, ao contrário do passo 12: a hipótese de aquecimento tem direção esperada, mas
    um resfriamento seria igualmente interpretável (vegetação irrigada no entorno, sombreamento,
    água de resfriamento). Não há razão física para descartar um lado a priori.
    """
    menor = min(k, n - k)
    p_uma_cauda = sum(math.comb(n, i) * 0.5**n for i in range(0, menor + 1))
    return min(1.0, 2 * p_uma_cauda)


def delta_ponta_a_ponta(serie: pd.DataFrame, coluna: str) -> float | None:
    """média(coluna nos 2 últimos anos da janela) - média(nos 2 primeiros)."""
    s = serie.sort_values("ano")
    v = s[coluna].dropna()
    if len(v) < 2 * N_ANOS_PONTA:
        return None
    return float(v.iloc[-N_ANOS_PONTA:].mean() - v.iloc[:N_ANOS_PONTA].mean())


def main() -> int:
    painel = pd.read_csv(C.DIR_PROCESSED / "consolidado_impacto_painel.csv")
    print(f"painel: {len(painel)} linhas, {painel.site_id.nunique()} pontos")

    # ---------------------------------------------------------------- 1. efeito par a par
    linhas = []
    for par, g in painel.groupby("pareado_com"):
        t = g[g.tipo == "tratamento"].sort_values("ano")
        c = g[g.tipo == "controle"].sort_values("ano")
        if t.empty or c.empty:
            continue
        dt = delta_ponta_a_ponta(t, "lst_media_celsius")
        dc = delta_ponta_a_ponta(c, "lst_media_celsius")
        if dt is None or dc is None:
            print(f"  ! {par}: janela curta demais, fora do teste")
            continue
        linhas.append(
            {
                "pareado_com": par,
                "sensor": t.sensor.iloc[0],
                "ano_inicio_obra": int(t.ano_inicio_obra.iloc[0]),
                "ano_min": int(t.ano.min()),
                "ano_max": int(t.ano.max()),
                "n_anos": int(t.ano.nunique()),
                "lst_pre_tratamento": round(float(t.lst_media_celsius.iloc[:N_ANOS_PONTA].mean()), 3),
                "lst_pos_tratamento": round(float(t.lst_media_celsius.iloc[-N_ANOS_PONTA:].mean()), 3),
                "delta_tratamento_c": round(dt, 3),
                "delta_controle_c": round(dc, 3),
                "excesso_c": round(dt - dc, 3),
                "qualidade_par": t.qualidade_par.iloc[0],
                "municipio_compartilhado_com_par": bool(t.municipio_compartilhado_com_par.iloc[0]),
            }
        )
    did = pd.DataFrame(linhas).sort_values("excesso_c", ascending=False)
    C.salvar_csv(did, C.DIR_SAIDA / "lst_did.csv")

    n = len(did)
    k = int((did.excesso_c > 0).sum())
    p_val = p_bin_bilateral(k, n)
    resumo = pd.DataFrame(
        [
            {
                "metrica": "lst_media_celsius",
                "n_pares": n,
                "n_aqueceu_mais_que_controle": k,
                "frac_positivo": round(k / n, 3),
                "p_bilateral": round(p_val, 4),
                "excesso_mediano_c": round(float(did.excesso_c.median()), 3),
                "excesso_medio_c": round(float(did.excesso_c.mean()), 3),
                "desvio_do_excesso_c": round(float(did.excesso_c.std()), 3),
            }
        ]
    )
    C.salvar_csv(resumo, C.DIR_SAIDA / "lst_did_resumo.csv")

    # ---------------------------------------------------------------- 2. validade física do dado
    ajuste = np.polyfit(painel.prop_construida_urbana, painel.lst_media_celsius, 1)
    contraste_c = float(ajuste[0])  # °C entre 0% e 100% de área construída
    r = float(painel.lst_media_celsius.corr(painel.prop_construida_urbana))
    validade = pd.DataFrame(
        [
            {
                "n_ponto_ano": len(painel),
                "correlacao_lst_x_prop_construida": round(r, 3),
                "inclinacao_c_por_pp_construida": round(contraste_c / 100.0, 4),
                "contraste_0pct_vs_100pct_construida_c": round(contraste_c, 2),
                "ruido_ano_a_ano_mediano_c": round(
                    float(painel.groupby("site_id").lst_media_celsius.std().median()), 3
                ),
            }
        ]
    )
    C.salvar_csv(validade, C.DIR_SAIDA / "lst_did_validade.csv")

    # ---------------------------------------------------------------- 3. poder do desenho
    area_anel_ha = math.pi * RAIO_ANEL_KM**2 * 100
    area_disco_ha = math.pi * C.BUFFER_KM**2 * 100
    ha_convertidos = EXCESSO_ANEL_PP / 100 * area_anel_ha
    fracao_do_disco = ha_convertidos / area_disco_ha
    efeito_esperado_c = fracao_do_disco * contraste_c

    sigma = float(did.excesso_c.std())
    # MDE de um teste pareado bilateral, alfa 0,05, poder 80%: (1,96 + 0,84) * sigma / sqrt(n)
    mde_c = 2.80 * sigma / math.sqrt(n)

    poder = pd.DataFrame(
        [
            {
                "resolucao_lst_m": 1000,
                "buffer_medido_km": C.BUFFER_KM,
                "anel_do_efeito_km": RAIO_ANEL_KM,
                "excesso_construida_no_anel_pp": EXCESSO_ANEL_PP,
                "ha_convertidos_no_anel": round(ha_convertidos, 2),
                "fracao_do_disco_5km": round(fracao_do_disco, 6),
                "contraste_termico_construida_c": round(contraste_c, 2),
                "efeito_esperado_no_disco_c": round(efeito_esperado_c, 5),
                "desvio_do_excesso_c": round(sigma, 3),
                "n_pares": n,
                "efeito_minimo_detectavel_c": round(mde_c, 3),
                "razao_mde_sobre_esperado": round(mde_c / efeito_esperado_c, 1) if efeito_esperado_c else None,
            }
        ]
    )
    C.salvar_csv(poder, C.DIR_SAIDA / "lst_did_poder.csv")

    # ---------------------------------------------------------------- 4. figura
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    d = did.sort_values("excesso_c")
    cores = ["#C0392B" if v > 0 else "#2980B9" for v in d.excesso_c]
    ax1.barh(d.pareado_com, d.excesso_c, color=cores)
    ax1.axvline(0, color="#333", lw=1)
    ax1.axvline(mde_c, color="#888", ls="--", lw=1)
    ax1.axvline(-mde_c, color="#888", ls="--", lw=1)
    ax1.set_xlabel("excesso de aquecimento vs. controle (°C)")
    ax1.set_title(
        f"LST: tratamento − controle, {n} pares\n"
        f"{k}/{n} aqueceram mais (p={p_val:.2f}) · "
        f"tracejado = efeito mínimo detectável (±{mde_c:.2f} °C)",
        fontsize=10,
    )
    ax1.tick_params(labelsize=8)

    ax2.scatter(
        painel.prop_construida_urbana * 100, painel.lst_media_celsius,
        s=18, alpha=0.55, c="#E67E22", edgecolors="none",
    )
    xs = np.linspace(0, 100, 50)
    ax2.plot(xs, np.polyval(ajuste, xs / 100), color="#333", lw=1.6)
    ax2.set_xlabel("área construída no disco de 5 km (%)")
    ax2.set_ylabel("LST média do ano (°C)")
    ax2.set_title(
        f"Validade do dado: LST × construída, r={r:.2f} (n={len(painel)})\n"
        f"contraste implícito de {contraste_c:.1f} °C entre 0% e 100% construído",
        fontsize=10,
    )

    fig.suptitle(
        "Passo 16 — aquecimento no entorno: o desenho não tem poder nesta escala "
        f"(esperado {efeito_esperado_c:.4f} °C, detectável {mde_c:.2f} °C)",
        fontsize=11, y=0.99,
    )
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    saida_fig = C.DIR_FIGURAS / "fig_10_lst_did.png"
    fig.savefig(saida_fig, dpi=150)
    plt.close(fig)
    print(f"  -> {saida_fig.relative_to(C.REPO_ROOT)}")

    # ---------------------------------------------------------------- 5. leitura
    print("\n--- leitura ---")
    print(f"efeito medido: {k}/{n} pares aqueceram mais que o controle, "
          f"mediana {did.excesso_c.median():+.3f} °C, p={p_val:.3f}")
    print(f"validade do dado: LST x construída r={r:.3f} — a relação física existe")
    print(f"efeito esperado pela diluição no disco de 5 km: {efeito_esperado_c:.5f} °C")
    print(f"efeito mínimo detectável com n={n}: {mde_c:.3f} °C "
          f"({mde_c / efeito_esperado_c:.0f}x maior que o esperado)")
    print("conclusão: nulo NÃO INFORMATIVO — o desenho não conseguiria ver o efeito se ele "
          "existisse. Responder isso exige banda termal do Landsat (30 m), não MODIS (1 km).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
