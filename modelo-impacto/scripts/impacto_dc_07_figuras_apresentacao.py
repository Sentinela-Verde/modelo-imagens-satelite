"""Passo 7 — figuras de apresentação para `notebooks/01_modelo_impacto.ipynb`.

Rode com:

    python modelo-impacto/scripts/impacto_dc_07_figuras_apresentacao.py

As figuras do passo 5 (`serie_*.png`) respondem uma pergunta técnica: a janela deste par está
inflada pela troca de satélite? As daqui respondem as perguntas da APRESENTAÇÃO: por que os 12
data centers viraram 8, por que a tabela de controle do Guilherme não serviu, e como os 15 pares
ficaram. São geradas por script, e não desenhadas na mão dentro do notebook, para o notebook abrir
rápido e as figuras não dependerem de reexecutar célula (mesma convenção de
`notebooks/00_demo_preview.ipynb`, que exibe PNGs já prontos de `reports/figures/`).

Nenhuma delas usa tile de mapa de fundo: são plots em lat/lon com os buffers de 5 km desenhados
como polígonos geodésicos exatos (`pyproj.Geod.fwd`, o mesmo caminho usado em todo o resto desta
frente). Fica legível, roda offline e não acrescenta dependência de rede a um material de
apresentação.

Saída: `modelo-impacto/raw/controles-rf/figuras/fig_0*.png`.
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

COR_TRATAMENTO = "#C0392B"
COR_CONTROLE = "#1B5E20"
COR_CONTAMINADO = "#C0392B"
COR_OK = "#2E7D32"
COR_NEUTRA = "#5D6D7E"


def circulo_geodesico(lat: float, lon: float, raio_km: float, n: int = 180) -> tuple[list, list]:
    """Polígono do buffer de `raio_km` em lat/lon, ponto a ponto pela geodésia WGS84."""
    lats, lons = [], []
    for az in np.linspace(0, 360, n):
        la, lo = C.ponto_por_azimute(lat, lon, float(az), raio_km)
        lats.append(la)
        lons.append(lo)
    return lats, lons


def ajustar_aspecto(ax, lat_ref: float) -> None:
    """1 grau de longitude vale menos km que 1 de latitude — sem isto, um buffer circular vira
    elipse e a figura mente sobre distância."""
    ax.set_aspect(1.0 / math.cos(math.radians(lat_ref)))


def desenhar_buffer(ax, lat, lon, raio_km, cor, alpha=0.12, lw=1.2, ls="-", label=None):
    la, lo = circulo_geodesico(lat, lon, raio_km)
    ax.fill(lo, la, color=cor, alpha=alpha, zorder=1)
    ax.plot(lo, la, color=cor, linewidth=lw, linestyle=ls, alpha=0.85, zorder=2, label=label)


# --------------------------------------------------------------------------------------------
# Fig 1 — os 12 id_datacenter são 8 campi
# --------------------------------------------------------------------------------------------


def fig_campi_predios(recon: pd.DataFrame, destino: Path) -> None:
    """Dois zooms mostrando por que medir por prédio não faz sentido num buffer de 5 km."""
    alvos = [
        ("ascenty-hortolandia", "Hortolândia — 4 prédios na lista do Guilherme"),
        ("ascenty-osasco", "Osasco — 2 prédios na lista do Guilherme"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.4))

    for ax, (site_id, titulo) in zip(axes, alvos, strict=True):
        sub = recon[recon["site_id"] == site_id]
        lat0, lon0 = sub["lat_guilherme"].mean(), sub["lon_guilherme"].mean()
        desenhar_buffer(ax, lat0, lon0, C.BUFFER_KM, COR_TRATAMENTO, label="buffer de análise (5 km)")

        ax.scatter(sub["lon_guilherme"], sub["lat_guilherme"], s=90, color=COR_TRATAMENTO,
                   edgecolor="white", linewidth=1.4, zorder=5, label=f"{len(sub)} prédios")
        for _, r in sub.iterrows():
            nome = r["nome_datacenter"].split("-")[-1].strip()
            ax.annotate(nome, (r["lon_guilherme"], r["lat_guilherme"]), fontsize=8.5,
                        xytext=(6, 4), textcoords="offset points", color="#7B241C")

        # barra de escala de 1 km, para o leitor ver quão pequena é a separação entre prédios
        la_esc, lo_esc = C.ponto_por_azimute(lat0 - 0.038, lon0 - 0.040, 90.0, 1.0)
        ax.plot([lon0 - 0.040, lo_esc], [lat0 - 0.038, la_esc], color="black", linewidth=2.5)
        ax.annotate("1 km", ((lon0 - 0.040 + lo_esc) / 2, lat0 - 0.038), fontsize=8.5,
                    ha="center", xytext=(0, 5), textcoords="offset points")

        dists = [
            C.distancia_km(a.lat_guilherme, a.lon_guilherme, b.lat_guilherme, b.lon_guilherme) * 1000
            for i, a in enumerate(sub.itertuples()) for b in list(sub.itertuples())[i + 1:]
        ]
        ax.set_title(f"{titulo}\nseparação entre prédios: {min(dists):.0f}–{max(dists):.0f} m",
                     fontsize=11)
        ajustar_aspecto(ax, lat0)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.legend(fontsize=8.5, loc="upper right")
        ax.grid(alpha=0.2)

    fig.suptitle("Os prédios de um campus são o mesmo recorte de terreno no buffer de 5 km",
                 fontsize=13, y=0.98)
    fig.tight_layout()
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")


# --------------------------------------------------------------------------------------------
# Fig 2 — os candidatos contaminados
# --------------------------------------------------------------------------------------------


def fig_candidatos_contaminados(diag: pd.DataFrame, sites: dict, destino: Path) -> None:
    """Os três casos em que o gerador do Guilherme pôs candidatos em cima de um data center."""
    casos = [
        ("scala-sgigsm01", "São João de Meriti (RJ)\ncandidatos caíram em Barueri/SP"),
        ("ascenty-paulinia", "Paulínia (SP)\ncandidatos em Louveira/SP"),
        ("ascenty-osasco", "Osasco (SP)\ncandidatos em Jundiaí/SP"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 6.0))

    for ax, (site_id, titulo) in zip(axes, casos, strict=True):
        sub = diag[diag["site_id"] == site_id].drop_duplicates(
            subset=["ponto_latitude", "ponto_longitude"]
        )
        lat0 = sub["ponto_latitude"].mean()
        lon0 = sub["ponto_longitude"].mean()

        # buffers dos sites de tratamento próximos dos candidatos
        vizinhos = sorted(set(sub["site_tratamento_mais_proximo"]))
        for i, sid in enumerate(vizinhos):
            p = sites[sid]
            desenhar_buffer(ax, p["lat"], p["lon"], C.BUFFER_KM, COR_TRATAMENTO, alpha=0.18,
                            label="data center do estudo (buffer 5 km)" if i == 0 else None)
            ax.scatter([p["lon"]], [p["lat"]], marker="*", s=260, color=COR_TRATAMENTO,
                       edgecolor="white", linewidth=1.2, zorder=6)
            ax.annotate(sid, (p["lon"], p["lat"]), fontsize=8.5, xytext=(8, -12),
                        textcoords="offset points", color="#7B241C", fontweight="bold")

        for _, r in sub.iterrows():
            cor = COR_CONTAMINADO if r["contaminado"] else COR_OK
            desenhar_buffer(ax, r["ponto_latitude"], r["ponto_longitude"], C.BUFFER_KM, cor,
                            alpha=0.07, lw=1.0, ls="--")
            ax.scatter([r["ponto_longitude"]], [r["ponto_latitude"]], s=70, color=cor,
                       edgecolor="white", linewidth=1.0, zorder=5)

        n_cont = int(sub["contaminado"].sum())
        ax.set_title(f"{titulo}\n{n_cont} de {len(sub)} candidatos contaminados", fontsize=10.5)
        ajustar_aspecto(ax, lat0)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(alpha=0.2)

    marcadores = [
        plt.Line2D([], [], marker="*", color=COR_TRATAMENTO, linestyle="none", markersize=14,
                   label="data center do estudo"),
        plt.Line2D([], [], marker="o", color=COR_CONTAMINADO, linestyle="none", markersize=8,
                   label="candidato contaminado (< 10 km de um data center)"),
        plt.Line2D([], [], marker="o", color=COR_OK, linestyle="none", markersize=8,
                   label="candidato sem contaminação"),
    ]
    fig.legend(handles=marcadores, loc="lower center", ncol=3, fontsize=9.5, frameon=False)
    fig.suptitle(
        "Onde a tabela de candidatos falhou: buffers de controle sobrepostos aos de tratamento",
        fontsize=13, y=0.98,
    )
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")


# --------------------------------------------------------------------------------------------
# Fig 3 — o funil MapBiomas -> RF
# --------------------------------------------------------------------------------------------


def fig_funil(cand: pd.DataFrame, destino: Path) -> None:
    """Dispersão dos finalistas: o pré-filtro concorda com quem decide?"""
    d = cand.dropna(subset=["l1_mapbiomas", "l1_rf"])
    rho = d[["l1_mapbiomas", "l1_rf"]].corr(method="spearman").iloc[0, 1]

    fig, ax = plt.subplots(figsize=(8.2, 7.2))
    perdedores = d[~d["escolhido"]]
    vencedores = d[d["escolhido"]]

    ax.scatter(perdedores["l1_mapbiomas"], perdedores["l1_rf"], s=55, color=COR_NEUTRA, alpha=0.55,
               edgecolor="white", linewidth=0.8, label=f"finalista não escolhido (n={len(perdedores)})")
    ax.scatter(vencedores["l1_mapbiomas"], vencedores["l1_rf"], s=150, marker="D",
               color=COR_CONTROLE, edgecolor="white", linewidth=1.4, zorder=5,
               label=f"controle escolhido (n={len(vencedores)})")

    lim = max(d["l1_mapbiomas"].max(), d["l1_rf"].max()) * 1.05
    ax.plot([0, lim], [0, lim], color="gray", linestyle=":", linewidth=1.2, label="y = x")
    ax.axhline(0.20, color="#F5A623", linestyle="--", linewidth=1.2)
    ax.annotate("limiar 0,20 (SV-29)", (lim * 0.62, 0.20), fontsize=8.5, color="#B8860B",
                xytext=(0, 6), textcoords="offset points")

    ax.set_xlabel("L1 pelo MapBiomas Coleção 9  (pré-ranqueia)")
    ax.set_ylabel("L1 pelo classificador Random Forest  (decide)")
    ax.set_title(
        f"Os dois critérios concordam — Spearman = {rho:.3f}\n"
        "pontos abaixo da diagonal: o classificador vê o par como mais parecido que o MapBiomas",
        fontsize=11.5,
    )
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(alpha=0.25)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    fig.tight_layout()
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")


# --------------------------------------------------------------------------------------------
# Fig 4 — mapa dos 15 pares
# --------------------------------------------------------------------------------------------


def fig_mapa_pares(par: pd.DataFrame, destino: Path) -> None:
    ok = par[par["status"] == "ok"]
    fig, ax = plt.subplots(figsize=(9.5, 9.5))

    for _, r in ok.iterrows():
        ax.plot([r["lon"], r["lon_controle"]], [r["lat"], r["lat_controle"]],
                color=COR_NEUTRA, linewidth=1.0, alpha=0.7, zorder=1)
    ax.scatter(ok["lon"], ok["lat"], s=110, marker="*", color=COR_TRATAMENTO, edgecolor="white",
               linewidth=1.0, zorder=4, label="data center (tratamento)")
    ax.scatter(ok["lon_controle"], ok["lat_controle"], s=55, marker="s", color=COR_CONTROLE,
               edgecolor="white", linewidth=1.0, zorder=4, label="controle pareado")

    for _, r in ok.iterrows():
        ax.annotate(f"{r['site_id']}  ({r['l1_rf']:.2f})", (r["lon"], r["lat"]), fontsize=7.5,
                    xytext=(7, 4), textcoords="offset points", color="#7B241C")

    ajustar_aspecto(ax, float(ok["lat"].mean()))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(
        f"{len(ok)} pares tratamento ↔ controle\n"
        f"distância {ok['dist_tratamento_controle_km'].min():.0f}–"
        f"{ok['dist_tratamento_controle_km'].max():.0f} km (entre parênteses, o L1 do classificador)",
        fontsize=12,
    )
    ax.legend(fontsize=9.5, loc="lower left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")


# --------------------------------------------------------------------------------------------
# Fig 5 — painel: as 15 séries em pequenos múltiplos
# --------------------------------------------------------------------------------------------


def fig_painel_series(painel: pd.DataFrame, par: pd.DataFrame, destino: Path) -> None:
    """As 15 séries lado a lado, em ano RELATIVO ao início da obra — assim os pares ficam
    alinhados no eixo x mesmo com obras em anos diferentes."""
    qualidade = par.set_index("site_id")["qualidade"].to_dict()
    pares = sorted(painel["pareado_com"].unique(), key=lambda s: par.set_index("site_id")["l1_rf"].get(s, 9))
    ncols, coluna = 5, "area_ha_solo_exposto_obras"
    nrows = math.ceil(len(pares) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.3 * ncols, 2.9 * nrows), squeeze=False)

    for i, site_id in enumerate(pares):
        ax = axes[i // ncols][i % ncols]
        sub = painel[painel["pareado_com"] == site_id]
        t = sub[sub["tipo"] == "tratamento"].sort_values("ano")
        c = sub[sub["tipo"] == "controle"].sort_values("ano")
        ax.plot(t["ano_relativo_ao_inicio_obra"], t[coluna], "o-", color=COR_TRATAMENTO,
                linewidth=2.0, markersize=4.5)
        ax.plot(c["ano_relativo_ao_inicio_obra"], c[coluna], "s--", color=COR_CONTROLE,
                linewidth=2.0, markersize=4)
        ax.axvline(0, color="gray", linestyle="--", linewidth=1.0, alpha=0.7)
        q = qualidade.get(site_id, "?")
        sensor = t["sensor"].iloc[0] if len(t) else "?"
        ax.set_title(f"{site_id}\n{q} · {'Landsat' if sensor == 'landsat' else 'S2'}", fontsize=8.5)
        ax.tick_params(labelsize=7.5)
        ax.grid(alpha=0.2)

    for j in range(len(pares), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")

    marcadores = [
        plt.Line2D([], [], marker="o", color=COR_TRATAMENTO, linewidth=2, label="tratamento"),
        plt.Line2D([], [], marker="s", color=COR_CONTROLE, linewidth=2, linestyle="--",
                   label="controle"),
        plt.Line2D([], [], color="gray", linestyle="--", label="início da obra (ano 0)"),
    ]
    fig.legend(handles=marcadores, loc="lower center", ncol=3, fontsize=10, frameon=False)
    fig.suptitle(
        "Solo exposto / obras (ha) no buffer de 5 km — ano relativo ao início da obra\n"
        "ordenados do par mais parecido para o menos parecido",
        fontsize=13, y=0.985,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.96))
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")


def main() -> int:
    print("Passo 7 — figuras de apresentação")
    sites = C.carregar_sites_validados()
    recon = pd.read_csv(C.DIR_SAIDA / "reconciliacao_datacenters.csv")
    diag = pd.read_csv(C.DIR_SAIDA / "diagnostico_candidatos_guilherme.csv")
    cand = pd.read_csv(C.DIR_SAIDA / "candidatos_avaliados_rf.csv")
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    painel = pd.read_csv(C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv")
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)

    fig_campi_predios(recon, C.DIR_FIGURAS / "fig_01_campi_predios.png")
    fig_candidatos_contaminados(diag, sites, C.DIR_FIGURAS / "fig_02_candidatos_contaminados.png")
    fig_funil(cand, C.DIR_FIGURAS / "fig_03_funil_mapbiomas_rf.png")
    fig_mapa_pares(par, C.DIR_FIGURAS / "fig_04_mapa_pares.png")
    fig_painel_series(painel, par, C.DIR_FIGURAS / "fig_05_painel_series.png")
    print(f"5 figuras em {C.DIR_FIGURAS.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
