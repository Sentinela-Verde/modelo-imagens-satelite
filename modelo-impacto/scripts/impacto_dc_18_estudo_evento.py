"""Passo 18 — estudo de evento: a conversão ANTES, DURANTE e DEPOIS da obra.

Rode com:

    python modelo-impacto/scripts/impacto_dc_18_estudo_evento.py

## Por que este passo existe

Os passos 12-15 medem um número por par: quanto o tratamento converteu a mais que o controle **na
janela inteira**. Isso responde "houve excesso?", mas não responde **quando** — e "quando" é o que
separa um efeito causal de uma coincidência.

O estudo de evento alinha todos os campi no **tempo relativo ao início da obra** (t = -3 .. +3), em
vez do tempo de calendário, e mostra a trajetória da diferença tratamento-controle ano a ano. Uma
obra de 2015 e uma de 2022 não são comparáveis no eixo do calendário; são no eixo do evento.

O que se espera ver, se o efeito for real:

  t < 0   diferença plana e próxima de zero  (as duas pontas caminhavam juntas)
  t >= 0  diferença sobe                     (o tratamento descola)

Se a diferença **já estivesse subindo antes de t=0**, o excesso medido nos passos anteriores não
seria do data center — seria de o data center ter sido construído justamente onde a região já
adensava. É a mesma hipótese que o pré-teste de tendências paralelas checa numericamente; aqui ela
fica **visual**, que é a forma canônica de apresentar diferença-em-diferenças.

## O que se mede

Diferente dos passos 12-15, que contam TRAJETÓRIA de pixel (uma estatística da janela inteira),
aqui se mede o **estoque** de área construída em cada ano — a única coisa que tem valor por ano.
Cada série é normalizada pelo próprio valor em t=-3, para que campi de tecidos urbanos muito
diferentes (Vinhedo com 14% construído, São João de Meriti com 96%) possam ser empilhados.

Zonas: as mesmas dos passos 14/15, com uma diferença importante — o **anel 0-500 m aqui EXCLUI o
footprint do data center**, para que a curva não seja o próprio prédio aparecendo. Essa é a
correção do viés de circularidade: no passo 14 a zona "0-0.5km" era um disco e continha o prédio.

Saídas:
  - `raw/controles-rf/estudo_evento.csv`        — série por par, zona e tempo relativo
  - `raw/controles-rf/estudo_evento_agregado.csv` — mediana e IQR por tempo relativo
  - `raw/controles-rf/figuras/fig_11_estudo_evento.png`
"""

from __future__ import annotations

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
ZONAS = [("0-0.5km", 0.0, 0.5), ("0.5-1km", 0.5, 1.0), ("1-2km", 1.0, 2.0)]


def _poligono(site_id: str, osm_id) -> list[dict] | None:
    try:
        return P14.poligono_do_cache(site_id, osm_id)
    except Exception:
        return None


def main() -> int:
    fps = pd.read_csv(C.DIR_SAIDA / "footprints_osm.csv").set_index("site_id")
    painel = pd.read_csv(C.DIR_PROCESSED / "consolidado_impacto_painel.csv")
    pontos = painel[["site_id", "tipo", "pareado_com", "lat", "lon", "sensor",
                     "ano_inicio_obra"]].drop_duplicates("site_id")

    registros = []
    for _, pt in pontos.iterrows():
        sid, par = pt.site_id, pt.pareado_com
        sensor = pt.sensor
        anos = sorted(painel[painel.site_id == sid].ano.unique())
        obra = int(pt.ano_inicio_obra)

        # máscaras de raio: dependem só da grade, constantes entre anos
        primeiro = C.caminho_classificado(sensor, sid, anos[0])
        if not Path(primeiro).exists():
            print(f"  ! {sid}: sem raster classificado, fora")
            continue
        raios = P11.mascaras_por_raio(Path(primeiro), float(pt.lat), float(pt.lon))

        # footprint a excluir — só o tratamento tem; no controle não há o que excluir
        m_fp = None
        if pt.tipo == "tratamento" and par in fps.index:
            geom = _poligono(par, fps.loc[par].get("osm_id"))
            if geom:
                try:
                    m_fp = P14.mascara_footprint(Path(primeiro), geom)
                except Exception:
                    m_fp = None

        for nome, r_int, r_ext in ZONAS:
            base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
            mascara = base & ~m_fp if m_fp is not None else base
            for ano in anos:
                tif = Path(C.caminho_classificado(sensor, sid, ano))
                if not tif.exists():
                    continue
                with rasterio.open(tif) as src:
                    arr = src.read(1)
                valido = (arr > 0) & mascara
                n = int(valido.sum())
                if n == 0:
                    continue
                registros.append(
                    {
                        "pareado_com": par, "site_id": sid, "tipo": pt.tipo,
                        "zona": nome, "sensor": sensor, "ano": int(ano),
                        "t_relativo": int(ano) - obra,
                        "footprint_excluido": m_fp is not None,
                        "pixels_validos": n,
                        "pct_construida": round(100.0 * int(((arr == CLASSE_CONSTRUIDA) & valido).sum()) / n, 4),
                    }
                )
        print(f"  {sid} ({pt.tipo}) ok"
              f"{' [footprint excluido]' if m_fp is not None else ''}")

    longo = pd.DataFrame(registros)
    C.salvar_csv(longo, C.DIR_SAIDA / "estudo_evento.csv")

    # ---------------------------------------------------------------- diferença por t_relativo
    linhas = []
    for (par, zona), g in longo.groupby(["pareado_com", "zona"]):
        t = g[g.tipo == "tratamento"].set_index("t_relativo")["pct_construida"]
        c = g[g.tipo == "controle"].set_index("t_relativo")["pct_construida"]
        comuns = sorted(set(t.index) & set(c.index))
        if -3 not in comuns:
            continue
        dif = {k: float(t[k] - c[k]) for k in comuns}
        base = dif[-3]  # normaliza em t=-3: a curva mede DESVIO da diferença inicial
        for k in comuns:
            linhas.append({"pareado_com": par, "zona": zona, "t_relativo": k,
                           "dif_pp": round(dif[k], 4),
                           "dif_norm_pp": round(dif[k] - base, 4)})
    dif_df = pd.DataFrame(linhas)

    agg = (
        dif_df.groupby(["zona", "t_relativo"])["dif_norm_pp"]
        .agg(n="count", mediana="median",
             q25=lambda s: s.quantile(0.25), q75=lambda s: s.quantile(0.75))
        .reset_index()
        .round(4)
    )
    C.salvar_csv(agg, C.DIR_SAIDA / "estudo_evento_agregado.csv")

    # ---------------------------------------------------------------- figura
    # Só pontos com massa suficiente para uma mediana significar algo — t=+4 tem n=1 em alguns
    # campi (janela de 8 anos) e viraria um pico espúrio de um caso só.
    N_MINIMO = 5
    agg = agg[agg.n >= N_MINIMO].copy()

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for ax, (nome, _, _) in zip(axes, ZONAS):
        a = agg[agg.zona == nome].sort_values("t_relativo")
        if a.empty:
            continue
        ax.axvspan(a.t_relativo.min() - 0.3, -0.5, color="#F4F6F7", zorder=0)
        ax.fill_between(a.t_relativo, a.q25, a.q75, color="#5DADE2", alpha=0.25, zorder=2)
        ax.plot(a.t_relativo, a.mediana, color="#1A5276", lw=2.2, marker="o", ms=5, zorder=3)
        ax.axhline(0, color="#333", lw=1, zorder=1)
        ax.axvline(-0.5, color="#C0392B", ls="--", lw=1.4, zorder=1)
        ax.set_title(f"anel {nome}" + ("\n(footprint excluído)" if nome == "0-0.5km" else ""),
                     fontsize=10)
        ax.set_xlabel("anos desde o início da obra")
        ax.grid(alpha=0.25)
    axes[0].text(-0.42, axes[0].get_ylim()[1] * 0.94, " início da obra",
                 color="#C0392B", fontsize=8, va="top")
    axes[0].set_ylabel("diferença tratamento − controle\nem área construída (p.p., normalizada em t=−3)")
    n_pares = int(agg[agg.zona == "0-0.5km"].n.max()) if not agg.empty else 0
    fig.suptitle(
        f"Passo 18 — estudo de evento: quando a conversão acontece  ·  {n_pares} pares  ·  "
        "linha = mediana, faixa = intervalo interquartil",
        fontsize=11, y=0.99,
    )
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    saida = C.DIR_FIGURAS / "fig_11_estudo_evento.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"  -> {saida.relative_to(C.REPO_ROOT)}")

    print("\n--- leitura (anel 0-500 m, footprint excluido) ---")
    a = agg[agg.zona == "0-0.5km"].sort_values("t_relativo")
    for _, r in a.iterrows():
        marca = "  <- inicio da obra" if r.t_relativo == 0 else ""
        print(f"  t={int(r.t_relativo):+d}  mediana {r.mediana:+.3f} pp  "
              f"[{r.q25:+.2f}, {r.q75:+.2f}]  n={int(r.n)}{marca}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
