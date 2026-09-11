"""Passo 20 — o efeito PERSISTE ou o controle alcança? Janela estendida até t+6.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_20_janela_estendida.py --fase classificar
    python dados-modelo-impacto/scripts/impacto_dc_20_janela_estendida.py --fase analise

## A pergunta que este passo fecha

O passo 18 (estudo de evento) mostrou o timing certo — pré-período plano, salto em t+1 — mas o
efeito **voltava a zero em t+3**, que é o último ano da janela de 7 anos. Isso deixou duas leituras
abertas, e elas levam a conclusões diferentes:

  **(A) Efeito real, medida anual ruidosa.** O estoque ano a ano com N=14 é barulhento demais;
       a estatística de trajetória (que exige persistência) é a medida boa e ela dá p=0,0037.
  **(B) Antecipação, não criação.** O data center adianta um adensamento que aconteceria de
       qualquer jeito, e por isso o controle alcança. Seria um achado diferente — e mais
       interessante — do que "o data center causa adensamento".

O passo 19 (placebo) já favoreceu (A): o método não produz falso positivo, então o ruído do passo
18 é propriedade daquela medida, não do desenho. Mas não fecha, porque **t+3 era o fim da janela**:
não dava para saber se a queda era ruído ou o começo de uma convergência real.

Este passo estende a janela para **obra-3 .. obra+6** onde o dado permite, e olha o que acontece
depois. Se a diferença voltar a subir, é (A). Se ficar em zero ou negativa de forma consistente,
é (B) — e a mensagem central do trabalho muda.

## Cobertura

Só 10 dos 15 campi podem estender: os de obra recente (2021-2023) não têm t+4 no arquivo.
  t+4  10 campi · t+5  5 campi · t+6  5 campi
A queda de N com o horizonte é reportada em toda saída — uma curva que afina de 10 para 5 casos
não pode ser lida como se tivesse N constante.

Saídas:
  - `raw/controles-rf/janela_estendida.csv`      — série estendida por ponto/zona/ano
  - `raw/controles-rf/janela_estendida_agregado.csv` — mediana e IQR por t_relativo, com N
  - `raw/controles-rf/janela_estendida_veredito.csv` — o teste (A) vs (B)
  - `raw/controles-rf/figuras/fig_13_janela_estendida.png`
"""

from __future__ import annotations

import argparse
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

CLASSE_CONSTRUIDA = 4
ANOS_DEPOIS_MAX = 6
LIMITES = {"landsat": (2013, 2024), "s2": (2019, 2025)}
ZONAS = [("0-0.5km", 0.0, 0.5), ("0.5-1km", 0.5, 1.0)]

SAIDA = C.DIR_SAIDA / "janela_estendida.csv"
SAIDA_AGG = C.DIR_SAIDA / "janela_estendida_agregado.csv"
SAIDA_VEREDITO = C.DIR_SAIDA / "janela_estendida_veredito.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_13_janela_estendida.png"


def janela_estendida(obra: int, sensor: str) -> list[int]:
    lo, hi = LIMITES[sensor]
    return [a for a in range(obra - C.ANOS_ANTES, obra + ANOS_DEPOIS_MAX + 1) if lo <= a <= hi]


def _pontos() -> pd.DataFrame:
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")]
    linhas = []
    for _, r in par.iterrows():
        linhas.append({"campus": r.site_id, "site_id": r.site_id, "tipo": "tratamento",
                       "lat": float(r.lat), "lon": float(r.lon), "sensor": r.sensor,
                       "ano_inicio_obra": int(r.ano_inicio_obra)})
        linhas.append({"campus": r.site_id, "site_id": r.site_id_controle, "tipo": "controle",
                       "lat": float(r.lat_controle), "lon": float(r.lon_controle),
                       "sensor": r.sensor, "ano_inicio_obra": int(r.ano_inicio_obra)})
    return pd.DataFrame(linhas)


def fase_classificar() -> None:
    pontos = _pontos()
    C.iniciar_ee()
    pacote = C.carregar_modelo()
    total = 0
    for _, p in pontos.iterrows():
        anos = janela_estendida(p.ano_inicio_obra, p.sensor)
        faltando = [a for a in anos
                    if not Path(C.caminho_classificado(p.sensor, p.site_id, a)).exists()]
        if not faltando:
            continue
        print(f"  {p.site_id} ({p.tipo}): faltam {faltando}")
        ponto = {"site_id": p.site_id, "lat": p.lat, "lon": p.lon, "buffer_km": C.BUFFER_KM}
        for ano in faltando:
            C.rodar_ponto(ponto, ano, p.sensor, pacote,
                          descartar_apos=p.tipo == "controle")
            total += 1
    print(f"\n{total} ponto-ano novos classificados")


def fase_analise() -> None:
    pontos = _pontos()
    fps = pd.read_csv(C.DIR_SAIDA / "footprints_osm.csv").set_index("site_id")

    registros = []
    for _, p in pontos.iterrows():
        anos = [a for a in janela_estendida(p.ano_inicio_obra, p.sensor)
                if Path(C.caminho_classificado(p.sensor, p.site_id, a)).exists()]
        if len(anos) < 5:
            continue
        primeiro = Path(C.caminho_classificado(p.sensor, p.site_id, anos[0]))
        raios = P11.mascaras_por_raio(primeiro, p.lat, p.lon)

        m_fp = None
        if p.tipo == "tratamento" and p.campus in fps.index:
            try:
                geom = P14.poligono_do_cache(p.campus, fps.loc[p.campus].get("osm_id"))
                if geom:
                    m_fp = P14.mascara_footprint(primeiro, geom)
            except Exception:
                m_fp = None

        for nome, r_int, r_ext in ZONAS:
            base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
            mascara = base & ~m_fp if m_fp is not None else base
            for ano in anos:
                with rasterio.open(C.caminho_classificado(p.sensor, p.site_id, ano)) as src:
                    arr = src.read(1)
                valido = (arr > 0) & mascara
                n = int(valido.sum())
                if n == 0:
                    continue
                registros.append({
                    "campus": p.campus, "site_id": p.site_id, "tipo": p.tipo, "zona": nome,
                    "sensor": p.sensor, "ano": ano, "t_relativo": ano - p.ano_inicio_obra,
                    "footprint_excluido": m_fp is not None, "pixels_validos": n,
                    "pct_construida": round(100.0 * int(((arr == CLASSE_CONSTRUIDA) & valido).sum()) / n, 4),
                })
        print(f"  {p.site_id} ({p.tipo}) t={anos[0] - p.ano_inicio_obra:+d}..{anos[-1] - p.ano_inicio_obra:+d}")

    longo = pd.DataFrame(registros)
    C.salvar_csv(longo, SAIDA)

    # ---------------------------------------------------------------- diferença por t
    linhas = []
    for (campus, zona), g in longo.groupby(["campus", "zona"]):
        t = g[g.tipo == "tratamento"].set_index("t_relativo")["pct_construida"]
        c = g[g.tipo == "controle"].set_index("t_relativo")["pct_construida"]
        comuns = sorted(set(t.index) & set(c.index))
        if -3 not in comuns:
            continue
        base = float(t[-3] - c[-3])
        for k in comuns:
            linhas.append({"campus": campus, "zona": zona, "t_relativo": k,
                           "dif_norm_pp": round(float(t[k] - c[k]) - base, 4)})
    dif = pd.DataFrame(linhas)

    agg = (dif.groupby(["zona", "t_relativo"])["dif_norm_pp"]
           .agg(n="count", mediana="median", q25=lambda s: s.quantile(0.25),
                q75=lambda s: s.quantile(0.75))
           .reset_index().round(4))
    C.salvar_csv(agg, SAIDA_AGG)

    # ---------------------------------------------------------------- veredito (A) vs (B)
    # (A) efeito real, medida ruidosa  -> a diferença no HORIZONTE LONGO (t>=4) segue positiva
    # (B) antecipação                  -> a diferença no horizonte longo volta a ~0 ou negativa
    vered = []
    for zona in [z[0] for z in ZONAS]:
        d = dif[dif.zona == zona]
        longo_h = d[d.t_relativo >= 4]["dif_norm_pp"].to_numpy(float)
        curto_h = d[(d.t_relativo >= 1) & (d.t_relativo <= 3)]["dif_norm_pp"].to_numpy(float)
        if len(longo_h) == 0:
            continue
        # teste de sinal no horizonte longo, por campus (média do campus em t>=4)
        por_campus = (d[d.t_relativo >= 4].groupby("campus")["dif_norm_pp"].mean()
                      .to_numpy(float))
        n, k = len(por_campus), int((por_campus > 0).sum())
        p_uni = sum(math.comb(n, i) * 0.5**n for i in range(k, n + 1))
        vered.append({
            "zona": zona,
            "n_campi_com_horizonte_longo": n,
            "n_positivo_em_t_maior_igual_4": k,
            "p_unilateral": round(p_uni, 4),
            "mediana_curto_prazo_t1_a_t3_pp": round(float(np.median(curto_h)), 4) if len(curto_h) else None,
            "mediana_longo_prazo_t4_mais_pp": round(float(np.median(por_campus)), 4),
            # Um veredito só sai com significância. Declarar (B) porque a mediana ficou
            # negativa com p=0,75 seria trocar ausência de evidência por evidência de
            # ausência — o erro exato que este projeto acusa em outros lugares (ver o selo
            # `nulo_sem_poder` do eixo de temperatura). Com n~9 o teste de sinal só separa
            # as hipóteses em casos extremos, e o resultado honesto costuma ser nenhum dos dois.
            "leitura": (
                "(A) o efeito PERSISTE no horizonte longo"
                if p_uni < 0.10 and np.median(por_campus) > 0
                else "(B) o controle ALCANCA — antecipacao, nao criacao"
                if (1 - p_uni) < 0.10 and np.median(por_campus) < 0
                else f"INCONCLUSIVO — com n={n} nenhuma das duas leituras atinge significancia "
                     f"(p={p_uni:.2f}); a mediana aponta "
                     f"{'para (B)' if np.median(por_campus) < 0 else 'para (A)'}, sem sustentacao"
            ),
        })
    veredito = pd.DataFrame(vered)
    C.salvar_csv(veredito, SAIDA_VEREDITO)

    # ---------------------------------------------------------------- figura
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, (nome, _, _) in zip(axes, ZONAS):
        a = agg[(agg.zona == nome) & (agg.n >= 4)].sort_values("t_relativo")
        if a.empty:
            continue
        ax.axvspan(a.t_relativo.min() - 0.3, -0.5, color="#F4F6F7", zorder=0)
        ax.axvspan(3.5, a.t_relativo.max() + 0.3, color="#FDF2E9", zorder=0)
        ax.fill_between(a.t_relativo, a.q25, a.q75, color="#5DADE2", alpha=0.25, zorder=2)
        ax.plot(a.t_relativo, a.mediana, color="#1A5276", lw=2.2, marker="o", ms=5, zorder=3)
        for _, r in a.iterrows():
            ax.annotate(f"n={int(r.n)}", (r.t_relativo, r.mediana), fontsize=7, color="#555",
                        xytext=(0, -13), textcoords="offset points", ha="center")
        ax.axhline(0, color="#333", lw=1, zorder=1)
        ax.axvline(-0.5, color="#C0392B", ls="--", lw=1.4, zorder=1)
        ax.set_title(f"anel {nome}" + ("  (footprint excluído)" if nome == "0-0.5km" else ""),
                     fontsize=10)
        ax.set_xlabel("anos desde o início da obra")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("diferença tratamento − controle (p.p., normalizada em t=−3)")
    axes[1].text(3.6, axes[1].get_ylim()[1] * 0.9, "horizonte novo\n(passo 20)",
                 fontsize=8, color="#B9770E", va="top")
    fig.suptitle("Passo 20 — janela estendida: o efeito persiste ou o controle alcança?",
                 fontsize=11, y=0.99)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print("\n--- veredito ---")
    for _, r in veredito.iterrows():
        print(f"  {r.zona}: curto prazo (t1-t3) {r.mediana_curto_prazo_t1_a_t3_pp:+.3f} pp · "
              f"longo prazo (t>=4) {r.mediana_longo_prazo_t4_mais_pp:+.3f} pp · "
              f"{r.n_positivo_em_t_maior_igual_4}/{r.n_campi_com_horizonte_longo} positivos, "
              f"p={r.p_unilateral:.4f}")
        print(f"    {r.leitura}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True, choices=["classificar", "analise"])
    args = ap.parse_args()
    fase_classificar() if args.fase == "classificar" else fase_analise()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
