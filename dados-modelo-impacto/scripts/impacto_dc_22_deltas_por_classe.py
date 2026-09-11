"""Passo 22 — delta por anel para as CINCO classes, fechando o quadro ambiental.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_22_deltas_por_classe.py

## Por que este passo existe

Os passos 12-20 olham uma coisa: conversão para área construída. É o eixo forte, mas deixa três
perguntas ambientais em aberto que qualquer leitor faz — **a água mudou? a vegetação densa
diminuiu? sobrou solo exposto?** Nenhuma delas tinha número no anel, só no buffer de 5 km, onde
tudo se dilui.

Este passo mede, para as cinco classes de uma vez, o delta **tratamento − controle** no anel, com a
convenção de janela dos passos 12/18 (média dos 2 primeiros anos contra a dos 2 últimos) e com o
footprint do data center excluído do anel interno.

## Diferença importante em relação ao passo 12

O passo 12 conta **trajetória de pixel** (não-construída nos 2 primeiros anos, construída nos 2
últimos, e permanece) — uma estatística exigente, robusta a falso positivo isolado, mas que só faz
sentido para uma transição direcional específica.

Aqui a medida é o **estoque** de cada classe: quanto da área do anel era daquela classe no começo e
quanto é no fim. É mais simples e mais ruidosa — a mesma medida que tornou o passo 18 barulhento —
e por isso a leitura de qualquer resultado aqui é mais fraca do que a do eixo de conversão.
Está declarado assim na saída: a coluna `robustez` marca `estoque` para todas as linhas.

Expectativa honesta antes de rodar: **água provavelmente dá nulo.** O que um data center consome
é água encanada, que não aparece em imagem; e um espelho d'água de resfriamento teria alguns
milhares de m², abaixo do que um pixel de 30 m distingue com confiabilidade num anel de 78 ha.
Reportar esse nulo fecha o eixo — não reportá-lo deixa a pergunta pairando.

Saídas:
  - `raw/controles-rf/deltas_por_classe.csv`  — delta por par, classe e anel
  - `raw/controles-rf/deltas_por_classe_resumo.csv` — teste de sinal por classe e anel
  - `raw/controles-rf/figuras/fig_15_deltas_por_classe.png`
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
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_14_footprint_vs_anel as P14  # noqa: E402

N_PONTA = 2
ZONAS = [("0-0.5km", 0.0, 0.5), ("0.5-1km", 0.5, 1.0)]
SAIDA = C.DIR_SAIDA / "deltas_por_classe.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "deltas_por_classe_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_15_deltas_por_classe.png"


def main() -> int:
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")]
    fps = pd.read_csv(C.DIR_SAIDA / "footprints_osm.csv").set_index("site_id")

    registros = []
    for _, r in par.iterrows():
        anos = C.janela_anos(int(r.ano_inicio_obra))
        for tipo, pid, lat, lon in (
            ("tratamento", r.site_id, float(r.lat), float(r.lon)),
            ("controle", r.site_id_controle, float(r.lat_controle), float(r.lon_controle)),
        ):
            disp = [a for a in anos
                    if Path(C.caminho_classificado(r.sensor, pid, a)).exists()]
            if len(disp) < 2 * N_PONTA:
                print(f"  ! {pid}: só {len(disp)} anos, fora")
                continue
            primeiro = Path(C.caminho_classificado(r.sensor, pid, disp[0]))
            raios = P11.mascaras_por_raio(primeiro, lat, lon)

            m_fp = None
            if tipo == "tratamento" and r.site_id in fps.index:
                try:
                    geom = P14.poligono_do_cache(r.site_id, fps.loc[r.site_id].get("osm_id"))
                    if geom:
                        m_fp = P14.mascara_footprint(primeiro, geom)
                except Exception:
                    m_fp = None

            for nome, r_int, r_ext in ZONAS:
                base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
                mascara = base & ~m_fp if m_fp is not None else base
                pct = {cid: [] for cid in C.CLASS_IDS}
                for ano in disp:
                    with rasterio.open(C.caminho_classificado(r.sensor, pid, ano)) as src:
                        arr = src.read(1)
                    valido = (arr > 0) & mascara
                    n = int(valido.sum())
                    if n == 0:
                        continue
                    for cid in C.CLASS_IDS:
                        pct[cid].append(100.0 * int(((arr == cid) & valido).sum()) / n)
                for cid in C.CLASS_IDS:
                    v = pct[cid]
                    if len(v) < 2 * N_PONTA:
                        continue
                    registros.append({
                        "campus": r.site_id, "site_id": pid, "tipo": tipo, "zona": nome,
                        "sensor": r.sensor, "classe_id": cid, "classe": C.CLASSE_NOME[cid],
                        "pct_inicio": round(float(np.mean(v[:N_PONTA])), 4),
                        "pct_fim": round(float(np.mean(v[-N_PONTA:])), 4),
                        "delta_pp": round(float(np.mean(v[-N_PONTA:]) - np.mean(v[:N_PONTA])), 4),
                    })
        print(f"  {r.site_id} ok")

    df = pd.DataFrame(registros)
    C.salvar_csv(df, SAIDA)

    # ---------------------------------------------------------------- teste de sinal
    linhas = []
    for (zona, cid), g in df.groupby(["zona", "classe_id"]):
        difs = []
        for campus, p in g.groupby("campus"):
            t = p[p.tipo == "tratamento"]["delta_pp"]
            c = p[p.tipo == "controle"]["delta_pp"]
            if t.empty or c.empty:
                continue
            difs.append(float(t.iloc[0] - c.iloc[0]))
        if not difs:
            continue
        d = np.asarray(difs)
        n, k = len(d), int((d > 0).sum())
        menor = min(k, n - k)
        p_bi = min(1.0, 2 * sum(math.comb(n, i) * 0.5**n for i in range(0, menor + 1)))
        linhas.append({
            "zona": zona, "classe_id": cid, "classe": C.CLASSE_NOME[cid],
            "n_pares": n, "n_positivo": k,
            "delta_liquido_mediano_pp": round(float(np.median(d)), 4),
            "p_bilateral": round(p_bi, 4),
            "robustez": "estoque",  # ver docstring: mais fraca que a trajetoria do passo 12
            "leitura": ("diferenca detectavel" if p_bi < 0.05
                        else "sem diferenca detectavel"),
        })
    resumo = pd.DataFrame(linhas)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    # ---------------------------------------------------------------- figura
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
    cores = {1: "#196F3D", 2: "#7DCEA0", 3: "#F5A623", 4: "#7B7D7D", 5: "#2E86C1"}
    for ax, (nome, _, _) in zip(axes, ZONAS):
        a = resumo[resumo.zona == nome].sort_values("classe_id")
        if a.empty:
            continue
        y = np.arange(len(a))
        ax.barh(y, a.delta_liquido_mediano_pp, color=[cores[c] for c in a.classe_id])
        ax.axvline(0, color="#333", lw=1)
        ax.set_yticks(y)
        ax.set_yticklabels(a.classe, fontsize=9)
        for i, (_, r0) in enumerate(a.iterrows()):
            marca = " *" if r0.p_bilateral < 0.05 else ""
            ax.text(r0.delta_liquido_mediano_pp, i,
                    f"  {r0.n_positivo}/{r0.n_pares}  p={r0.p_bilateral:.2f}{marca}",
                    va="center", fontsize=8)
        ax.set_title(f"anel {nome}" + ("  (footprint excluído)" if nome == "0-0.5km" else ""),
                     fontsize=10)
        ax.set_xlabel("delta líquido tratamento − controle (p.p.)")
        ax.grid(axis="x", alpha=0.25)
    fig.suptitle("Passo 22 — delta por classe no anel (medida de ESTOQUE: mais fraca que a "
                 "trajetória do passo 12)", fontsize=10.5, y=0.99)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print("\n--- delta liquido por classe ---")
    for zona in [z[0] for z in ZONAS]:
        print(f"  anel {zona}")
        for _, r0 in resumo[resumo.zona == zona].sort_values("classe_id").iterrows():
            print(f"    {r0.classe:22s} {r0.delta_liquido_mediano_pp:+7.3f} pp  "
                  f"{r0.n_positivo}/{r0.n_pares}  p={r0.p_bilateral:.3f}  {r0.leitura}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
