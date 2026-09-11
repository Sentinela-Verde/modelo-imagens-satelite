"""Passo 26 — refaz o achado com a amostra expandida, e mostra o efeito de incluir os novos.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_26_analise_expandida.py --fase footprints
    python dados-modelo-impacto/scripts/impacto_dc_26_analise_expandida.py --fase analise

## O que este passo faz, e por que não é só "rodar de novo com mais dados"

A amostra vai de 15 para 20 campi (passo 25). Mas os 5 novos **não são equivalentes** aos 15
originais em dois pontos, e ignorar isso seria esconder uma diferença real:

1. **Procedência da coordenada.** Os 16 originais passaram por validação em 5 camadas (SV-25); os
   novos vêm do `datacentermap`. O ano da obra também: imprensa (SV-24) contra `ano_operacional−1`.
2. **Footprint do OSM.** O passo 13 só rodou para os 15 originais. Sem footprint, a zona de
   0–500 m de um campus novo é um **disco que contém o próprio prédio** — exatamente o viés de
   circularidade que já foi corrigido para os originais. Misturar os dois enviesaria os novos
   **para cima**.

A fase `footprints` resolve (2) puxando o footprint dos novos no OSM. A fase `analise` resolve (1)
reportando o teste **três vezes**: só originais, só novos, e o conjunto. Se o achado mudar ao
incluir sites menos validados, isso aparece — que é o motivo de rodar assim.

O **anel de 0,5–1 km** é reportado junto de propósito: ele nunca contém o prédio, para nenhum dos
dois grupos, então é a comparação que não depende de o footprint existir.

Saídas:
  - `raw/controles-rf/expansao_footprints.csv`  — footprints OSM dos campi novos
  - `raw/controles-rf/analise_expandida.csv`    — contagens por ponto e zona, com procedência
  - `raw/controles-rf/analise_expandida_resumo.csv` — o teste de sinal nos três recortes
  - `raw/controles-rf/figuras/fig_18_analise_expandida.png`
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_12_trajetoria_pixel as P12  # noqa: E402
import impacto_dc_13_footprint_osm as P13  # noqa: E402
import impacto_dc_14_footprint_vs_anel as P14  # noqa: E402

ZONAS = [("0-0.5km", 0.0, 0.5), ("0.5-1km", 0.5, 1.0), ("1-2km", 1.0, 2.0)]
SAIDA_FP = C.DIR_SAIDA / "expansao_footprints.csv"
SAIDA = C.DIR_SAIDA / "analise_expandida.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "analise_expandida_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_18_analise_expandida.png"
# Mesmo diretório do passo 13 de propósito: `P14.poligono_do_cache` lê de um caminho fixo
# (`raw/controles-rf/osm/{site_id}.json`). Os site_id são distintos (`exp-*`), então não há
# colisão — e reusar o diretório é o que faz a máscara de footprint funcionar para os novos.
DIR_OSM_EXP = C.DIR_SAIDA / "osm"


def pares_unificados() -> pd.DataFrame:
    """Os 15 originais + os novos que conseguiram controle, com `procedencia` marcada."""
    orig = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    orig = orig[orig.site_id_controle.notna() & (orig.site_id_controle != "")].copy()
    orig = orig[["site_id", "site_id_controle", "lat", "lon", "lat_controle", "lon_controle",
                 "ano_inicio_obra", "sensor", "l1_rf"]]
    orig["procedencia"] = "validado_5_camadas"

    novos = pd.DataFrame()
    p_exp = C.DIR_SAIDA / "expansao_pareamento.csv"
    if p_exp.exists():
        e = pd.read_csv(p_exp)
        e = e[(e.status == "ok") & e.site_id_controle.notna()].copy()
        if not e.empty:
            novos = e[["site_id", "site_id_controle", "lat", "lon", "lat_controle",
                       "lon_controle", "ano_inicio_obra", "sensor", "l1_rf"]].copy()
            novos["procedencia"] = "datacentermap"
    return pd.concat([orig, novos], ignore_index=True)


def fase_footprints() -> None:
    """Puxa o footprint OSM dos campi novos — sem isso o anel deles conteria o próprio prédio."""
    pares = pares_unificados()
    novos = pares[pares.procedencia == "datacentermap"]
    if novos.empty:
        print("nenhum campus novo pareado — nada a fazer")
        return
    DIR_OSM_EXP.mkdir(parents=True, exist_ok=True)

    linhas = []
    for _, r in novos.iterrows():
        cache = DIR_OSM_EXP / f"{r.site_id}.json"
        if cache.exists():
            dados = json.loads(cache.read_text(encoding="utf-8"))
        else:
            print(f"  consultando OSM: {r.site_id}")
            dados = P13.consultar_overpass(float(r.lat), float(r.lon))
            cache.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            time.sleep(P13.ESPERA_S)

        melhor, metodo = None, "sem_footprint"
        for el in dados.get("elements", []):
            tags = el.get("tags") or {}
            geom = el.get("geometry")
            if not geom or len(geom) < 3:
                continue
            b = (tags.get("building") or "").lower()
            lu = (tags.get("landuse") or "").lower()
            if b == "data_center" or tags.get("telecom"):
                prio = 0
            elif lu == "industrial" or b in {"industrial", "warehouse"}:
                prio = 1
            elif b:
                prio = 2
            else:
                continue
            area = P13.area_ha(geom)
            if melhor is None or prio < melhor[0]:
                melhor = (prio, el, area)
        if melhor:
            metodo = {0: "osm_data_center_explicito", 1: "osm_landuse_industrial",
                      2: "osm_edificacao_mais_proxima"}[melhor[0]]
        linhas.append({
            "site_id": r.site_id, "metodo_footprint": metodo,
            # formato "tipo/id" — é o que `poligono_do_cache` faz split para reencontrar
            "osm_id": (f"{melhor[1].get('type')}/{melhor[1].get('id')}" if melhor else None),
            "area_footprint_ha": round(melhor[2], 4) if melhor else None,
            "n_feicoes_osm": len(dados.get("elements", [])),
        })
        print(f"  {r.site_id:36s} {metodo}")

    df = pd.DataFrame(linhas)
    C.salvar_csv(df, SAIDA_FP)
    print(f"\n{int(df.metodo_footprint.ne('sem_footprint').sum())}/{len(df)} com footprint")


def _mascara_footprint(site: str, ref: Path) -> np.ndarray | None:
    """Footprint do campus, do passo 13 (originais) ou do passo 26 (novos)."""
    for tabela, col in ((C.DIR_SAIDA / "footprints_osm.csv", "osm_id"),
                        (SAIDA_FP, "osm_id")):
        if not tabela.exists():
            continue
        t = pd.read_csv(tabela).set_index("site_id")
        if site not in t.index:
            continue
        try:
            geom = P14.poligono_do_cache(site, t.loc[site].get(col))
            if geom:
                return P14.mascara_footprint(ref, geom)
        except Exception:
            continue
    return None


def fase_analise() -> None:
    pares = pares_unificados()
    print(f"{len(pares)} pares: "
          f"{int((pares.procedencia == 'validado_5_camadas').sum())} validados + "
          f"{int((pares.procedencia == 'datacentermap').sum())} novos")

    registros = []
    for _, r in pares.iterrows():
        anos = C.janela_anos(int(r.ano_inicio_obra))
        ok = True
        for tipo, pid, lat, lon in (("tratamento", r.site_id, r.lat, r.lon),
                                    ("controle", r.site_id_controle, r.lat_controle, r.lon_controle)):
            faltam = [a for a in anos
                      if not Path(C.caminho_classificado(r.sensor, pid, a)).exists()]
            if faltam:
                print(f"  ! {pid}: faltam {len(faltam)} anos, par fora")
                ok = False
                break
        if not ok:
            continue

        for tipo, pid, lat, lon in (("tratamento", r.site_id, r.lat, r.lon),
                                    ("controle", r.site_id_controle, r.lat_controle, r.lon_controle)):
            ref = Path(C.caminho_classificado(r.sensor, pid, anos[0]))
            pilha = P12.empilhar(pid, r.sensor, anos)
            raios = P11.mascaras_por_raio(ref, float(lat), float(lon))
            m_fp = _mascara_footprint(r.site_id, ref) if tipo == "tratamento" else None

            for nome, r_int, r_ext in ZONAS:
                base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
                # O footprint só conta como excluído se de fato SOBREPÕE a zona. Dois campi têm
                # polígono OSM a 500-615 m do ponto validado (`ascenty-vinhedo`, 0,615 km;
                # `ascenty-sumare`, 0,498 km), ambos `landuse=industrial` — são áreas industriais
                # vizinhas, não o data center. Nesses casos a máscara não remove nada do disco, e
                # tratar isso como "prédio excluído" seria falso: o prédio continua lá dentro.
                sobrepoe = bool(m_fp is not None and (m_fp & base).any())
                mascara = base & ~m_fp if sobrepoe else base
                cont = P12.contar_assinaturas(pilha, mascara)
                n = cont["pixels_validos_mascara"]
                registros.append({
                    "campus": r.site_id, "site_id": pid, "tipo": tipo, "zona": nome,
                    "procedencia": r.procedencia, "sensor": r.sensor,
                    "footprint_excluido": sobrepoe, **cont,
                    **{f"pct_{a}": (100.0 * cont[a] / n if n else np.nan)
                       for a in P12.ASSINATURAS},
                })
        print(f"  {r.site_id} ok ({r.procedencia})")

    longo = pd.DataFrame(registros)
    C.salvar_csv(longo, SAIDA)

    # ---------------------------------------------------------------- teste nos três recortes
    linhas = []
    recortes = {
        "so_validados": lambda d: d[d.procedencia == "validado_5_camadas"],
        "so_expansao": lambda d: d[d.procedencia == "datacentermap"],
        "conjunto": lambda d: d,
    }
    # Campi sem footprint no OSM: a zona de 0-0,5 km deles é um DISCO que contém o próprio
    # prédio. Nas outras zonas isso não acontece (são anéis de verdade), então eles só saem do
    # recorte interno. Hoje é 1 campus — `everest-goiania`, o único dos 15 sem footprint no
    # passo 13. Mantê-lo no anel interno misturaria o empreendimento com o efeito dele, que é
    # exatamente a circularidade já corrigida para todos os outros.
    # Só a zona interna importa aqui: nos anéis externos o footprint naturalmente não sobrepõe
    # (ele fica no centro), então `footprint_excluido` é False para todo mundo lá — filtrar por
    # isso sem restringir a zona derrubaria a amostra inteira.
    sem_fp = set(
        longo[(longo.tipo == "tratamento") & (longo.zona == "0-0.5km")
              & ~longo.footprint_excluido].campus
    )
    if sem_fp:
        print(f"\n! fora do anel 0-0.5km por falta de footprint: {sorted(sem_fp)}")

    for nome_rec, filtro in recortes.items():
        sub = filtro(longo)
        for zona, _, _ in ZONAS:
            g = sub[sub.zona == zona]
            if zona == "0-0.5km" and sem_fp:
                g = g[~g.campus.isin(sem_fp)]
            for assin in ("virou_construida", "vegetacao_para_construida"):
                col = f"pct_{assin}"
                difs = []
                for _, par in g.groupby("campus"):
                    t = par[par.tipo == "tratamento"][col]
                    c = par[par.tipo == "controle"][col]
                    if t.empty or c.empty or t.isna().all() or c.isna().all():
                        continue
                    difs.append(float(t.iloc[0] - c.iloc[0]))
                if len(difs) < 3:
                    continue
                d = np.asarray(difs)
                n, k = len(d), int((d > 0).sum())
                p = sum(math.comb(n, i) * 0.5**n for i in range(k, n + 1))
                linhas.append({
                    "recorte": nome_rec, "zona": zona, "assinatura": assin,
                    "n_pares": n, "n_positivo": k, "frac_positivo": round(k / n, 3),
                    "p_unilateral": round(p, 4),
                    "excesso_mediano_pp": round(float(np.median(d)), 4),
                })
    resumo = pd.DataFrame(linhas)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    # ---------------------------------------------------------------- figura
    prin = resumo[resumo.assinatura == "virou_construida"]
    fig, axes = plt.subplots(1, len(ZONAS), figsize=(14, 4.8), sharey=True)
    cores = {"so_validados": "#1A5276", "so_expansao": "#E67E22", "conjunto": "#27AE60"}
    for ax, (zona, _, _) in zip(axes, ZONAS):
        s = prin[prin.zona == zona]
        if s.empty:
            continue
        x = np.arange(len(s))
        ax.bar(x, s.excesso_mediano_pp, color=[cores[r] for r in s.recorte])
        for i, (_, r0) in enumerate(s.iterrows()):
            # p com casas suficientes: 0,0002 com 3 decimais vira "p=0.000" e parece zero exato
            texto_p = (f"p={r0.p_unilateral:.4f}" if r0.p_unilateral < 0.001
                       else f"p={r0.p_unilateral:.3f}")
            ax.text(i, r0.excesso_mediano_pp,
                    f"{int(r0.n_positivo)}/{int(r0.n_pares)}\n{texto_p}",
                    ha="center", va="bottom", fontsize=8)
        ax.axhline(0, color="#333", lw=1)
        ax.set_xticks(x)
        ax.set_xticklabels([r.replace("so_validados", "só validados")
                             .replace("so_expansao", "só expansão") for r in s.recorte],
                           fontsize=8)
        ax.set_title(f"anel {zona}", fontsize=10)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("excesso mediano de conversão (p.p.)")
    # folga no topo para os rótulos de n/p não baterem no título
    for ax in axes:
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi * 1.18)
    fig.suptitle("Passo 26 — o achado com a amostra expandida, e o efeito de incluir os novos",
                 fontsize=11, y=0.99)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print("\n--- virou_construida, por recorte ---")
    for zona, _, _ in ZONAS:
        print(f"  anel {zona}")
        for _, r0 in prin[prin.zona == zona].iterrows():
            print(f"    {r0.recorte:14s} {int(r0.n_positivo):2d}/{int(r0.n_pares):2d}  "
                  f"p={r0.p_unilateral:.4f}  mediana {r0.excesso_mediano_pp:+.3f} pp")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True, choices=["footprints", "analise"])
    args = ap.parse_args()
    fase_footprints() if args.fase == "footprints" else fase_analise()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
