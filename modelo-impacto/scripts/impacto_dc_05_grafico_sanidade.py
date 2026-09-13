"""Passo 5 — gráfico de sanidade: a série de cada par, com o satélite marcado.

Rode com:

    python modelo-impacto/scripts/impacto_dc_05_grafico_sanidade.py [--pares a,b,c] [--todos]

O que este gráfico existe para responder: **a janela de 3 anos antes/depois escolhida para cada
par está artificialmente inflada pela troca de satélite?**

Cada figura tem dois painéis:

- **Painel de cima — a série do par.** Tratamento (linha cheia) e controle (tracejada), área da
  classe crítica "solo exposto/obras" ao longo dos anos. O sensor usado aparece no título e na cor
  de fundo do painel; como o desenho garante um sensor só por par, a série inteira é do mesmo
  instrumento e qualquer degrau que apareça é do terreno.
- **Painel de baixo — a prova de que isso importa.** Para o mesmo site de tratamento, a leitura
  "ingênua" (Landsat até 2018, Sentinel-2 de 2019 em diante — o que uma série emendada sem
  cuidado mostraria) contra a leitura mono-sensor. Onde as duas divergem, a diferença é artefato
  de instrumento, não obra. É a mesma comparação de
  `reports/figures/exemplo_misturar_vs_so_landsat_ascenty-vinhedo.png` e da seção 5 de
  `notebooks/00_demo_preview.ipynb`, reproduzida aqui par a par.

O painel de baixo só é desenhável quando o site tem os dois sensores no mesmo ano — o que existe
em 2019-2021 (`anos_sobreposicao` de `config/params.yml`) e, depois do passo 2, em 2022-2024
também. Quando não há sobreposição, o painel é substituído por uma nota explicando por quê.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C

PAINEL = C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv"
AREA_OFICIAL = C.REPO_ROOT / "outputs" / "indicadores" / "area_por_classe.csv"

CLASSE_FOCO = "solo_exposto_obras"
COR_TRATAMENTO = "#C0392B"
COR_CONTROLE = "#1B5E20"
COR_MISTURADA = "#C0392B"
COR_MONO = "#1B5E20"
FUNDO_SENSOR = {"landsat": "#FFF8E7", "s2": "#EAF4FF"}
NOME_SENSOR = {"landsat": "Landsat 8/9 (30 m)", "s2": "Sentinel-2 (10 m)"}


def serie_mono_vs_misturada(site_id: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """(misturada, mono) para a classe crítica, a partir do output oficial de Indicadores.

    Usa `outputs/indicadores/area_por_classe.csv` em vez do painel deste estudo porque lá estão
    as DUAS leituras de cada ano de sobreposição, que é justamente o que este painel compara.
    """
    if not AREA_OFICIAL.exists():
        return None
    df = pd.read_csv(AREA_OFICIAL)
    d = df[(df.site_id == site_id) & (df.classe_nome == CLASSE_FOCO)]
    if d.empty:
        return None
    misturada = pd.concat(
        [d[(d.sensor == "landsat") & (d.ano < 2019)], d[d.sensor == "sentinel2"]]
    ).sort_values("ano")
    mono = d[d.sensor == "landsat"].sort_values("ano")
    if mono.empty or misturada.empty:
        return None
    anos_ambos = set(d[d.sensor == "landsat"].ano) & set(d[d.sensor == "sentinel2"].ano)
    if not anos_ambos:
        return None
    return misturada, mono


def desenhar_par(painel: pd.DataFrame, site_id: str, destino: Path) -> bool:
    par = painel[painel["pareado_com"] == site_id]
    if par.empty:
        print(f"  {site_id}: sem linhas no painel — pulando")
        return False

    trat = par[par["tipo"] == "tratamento"].sort_values("ano")
    ctrl = par[par["tipo"] == "controle"].sort_values("ano")
    sensor = trat["sensor"].iloc[0]
    ano_obra = int(trat["ano_inicio_obra"].iloc[0])
    fim = trat["ano_fim_obra"].iloc[0]
    coluna = f"area_ha_{CLASSE_FOCO}"

    comparacao = serie_mono_vs_misturada(site_id)
    n_paineis = 2 if comparacao else 1
    fig, axes = plt.subplots(n_paineis, 1, figsize=(9.5, 5.0 * n_paineis), squeeze=False)
    ax = axes[0][0]

    ax.set_facecolor(FUNDO_SENSOR.get(sensor, "#FFFFFF"))
    ax.plot(trat["ano"], trat[coluna], "o-", color=COR_TRATAMENTO, linewidth=2.5, markersize=7,
            label=f"tratamento — {site_id}")
    ax.plot(ctrl["ano"], ctrl[coluna], "s--", color=COR_CONTROLE, linewidth=2.5, markersize=6,
            label=f"controle — {ctrl['site_id'].iloc[0]}")

    ax.axvline(ano_obra, color="gray", linestyle="--", linewidth=1.2, alpha=0.8)
    ax.annotate(f"início da obra\n({ano_obra})", xy=(ano_obra, ax.get_ylim()[1]),
                xytext=(4, -8), textcoords="offset points", fontsize=8.5, color="dimgray",
                va="top", bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                                    edgecolor="lightgray", alpha=0.9))
    if pd.notna(fim) and int(fim) != ano_obra:
        ax.axvline(int(fim), color="gray", linestyle=":", linewidth=1.2, alpha=0.8)
        ax.annotate(f"fim da obra\n({int(fim)})", xy=(int(fim), ax.get_ylim()[0]),
                    xytext=(4, 12), textcoords="offset points", fontsize=8.5, color="dimgray",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor="lightgray", alpha=0.9))

    ax.set_xlabel("Ano")
    ax.set_ylabel("Área de solo exposto / obras (ha)")
    ax.set_title(f"{site_id} — série do par, sensor único: {NOME_SENSOR.get(sensor, sensor)}",
                 fontsize=11.5)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    ax.set_xticks(sorted(par["ano"].unique()))

    if comparacao:
        misturada, mono = comparacao
        ax2 = axes[1][0]
        ax2.plot(misturada["ano"], misturada["area_ha"], "o-", color=COR_MISTURADA, linewidth=2.5,
                 markersize=7, label="série emendada (Landsat até 2018 + Sentinel-2 de 2019)")
        ax2.plot(mono["ano"], mono["area_ha"], "o-", color=COR_MONO, linewidth=2.5, markersize=7,
                 label="só Landsat (o que este estudo usa)")
        ax2.axvline(2019, color="gray", linestyle="--", linewidth=1.2, alpha=0.7)
        ax2.axvspan(min(par["ano"]), max(par["ano"]), color="#FFD54F", alpha=0.18,
                    label="janela usada neste estudo")
        ax2.set_xlabel("Ano")
        ax2.set_ylabel("Área de solo exposto / obras (ha)")
        ax2.set_title(
            f"{site_id} — por que a janela é mono-sensor: a mesma obra, lida de dois jeitos",
            fontsize=11.5,
        )
        ax2.legend(fontsize=9)
        ax2.grid(alpha=0.25)

    fig.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=140)
    plt.close(fig)
    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gráfico de sanidade por par (passo 5).")
    parser.add_argument("--pares", default=None, help="lista de site_id separada por vírgula")
    parser.add_argument("--todos", action="store_true", help="gera para todos os pares do painel")
    args = parser.parse_args(argv)

    if not PAINEL.exists():
        print(f"ERRO: {PAINEL} não existe — rode o passo 4 antes.", file=sys.stderr)
        return 1
    painel = pd.read_csv(PAINEL)

    disponiveis = sorted(painel["pareado_com"].unique())
    if args.pares:
        alvos = [s.strip() for s in args.pares.split(",")]
    elif args.todos:
        alvos = disponiveis
    else:
        # Padrão: os 3 pares em que a escolha de sensor mais importa — obra em 2019/2020, ou seja,
        # em cima da fronteira Landsat/Sentinel-2 que SV-20 mediu.
        preferidos = ["ascenty-vinhedo", "ascenty-jundiai", "ascenty-osasco", "ascenty-paulinia"]
        alvos = [s for s in preferidos if s in disponiveis][:3] or disponiveis[:3]

    print(f"Passo 5 — gerando figura(s) para: {', '.join(alvos)}")
    n = sum(desenhar_par(painel, s, C.DIR_FIGURAS / f"serie_{s}.png") for s in alvos)
    print(f"{n} figura(s) geradas em {C.DIR_FIGURAS.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
