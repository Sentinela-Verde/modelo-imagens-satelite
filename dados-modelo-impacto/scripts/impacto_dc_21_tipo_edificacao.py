"""Passo 21 — o que EXISTE no anel: residencial, comercial ou industrial?

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_21_tipo_edificacao.py

## A pergunta

Os passos 12-20 medem que o anel de 500 m converteu para "área construída". Mas o classificador
tem **uma única** classe construída — ele vê que virou construção, não vê de que tipo. "Virou
galpão logístico" e "virou conjunto residencial" são o mesmo pixel, e são coisas muito diferentes
para quem lê o resultado.

Este passo usa o OpenStreetMap para caracterizar o que há hoje no anel do tratamento e no anel do
controle, e comparar a composição.

## O que este passo NÃO responde, e por que precisa estar escrito

**O OSM mostra o que existe AGORA, não o que apareceu QUANDO.** Cada elemento tem um timestamp,
mas ele é a data em que alguém *mapeou* a feição, não a data em que ela foi construída — depende
da atividade de mapeadores na região, que é um confundidor grosseiro e correlacionado com
urbanização. Usar esse timestamp como data de construção seria erro grave, e por isso ele não é
usado aqui.

O que sai daqui é, portanto, **descritivo e transversal**: "o entorno de um data center tem esta
composição, o de um controle pareado tem esta outra". Não é antes/depois, e não é causal. A
comparação com o controle continua valendo — os dois são fotografados no mesmo momento — mas a
afirmação é sobre *composição*, não sobre *mudança de composição*.

Para a versão temporal disso seria necessária a base CNPJ da Receita Federal (que tem data de
início de atividade por estabelecimento). Ver a seção de pendências no README.

## Cobertura do OSM

Irregular no Brasil, e pior fora de grandes centros. A saída publica `n_feicoes` por ponto
justamente para que uma composição calculada sobre 3 feições não seja lida como se fosse sobre 300.
Pontos com poucas feições entram na tabela e ficam **fora** do teste agregado.

Saídas:
  - `raw/controles-rf/tipo_edificacao.csv`  — contagem e área por categoria, por ponto
  - `raw/controles-rf/tipo_edificacao_resumo.csv` — tratamento vs. controle, por categoria
  - `raw/controles-rf/figuras/fig_14_tipo_edificacao.png`
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_13_footprint_osm as P13  # noqa: E402

RAIO_M = 1000
DIR_CACHE = C.DIR_SAIDA / "osm_anel"
SAIDA = C.DIR_SAIDA / "tipo_edificacao.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "tipo_edificacao_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_14_tipo_edificacao.png"
MIN_FEICOES = 10  # abaixo disso a composição não é interpretável

CATEGORIAS = ["residencial", "comercial", "industrial_logistico", "institucional", "indeterminado"]


def categorizar(tags: dict[str, str]) -> str:
    """Uma feição do OSM -> uma das 5 categorias. Ordem importa: o mais específico vence."""
    b = (tags.get("building") or "").lower()
    lu = (tags.get("landuse") or "").lower()

    if b in {"industrial", "warehouse", "factory"} or lu == "industrial" or tags.get("man_made"):
        return "industrial_logistico"
    if b in {"commercial", "retail", "office", "supermarket", "kiosk"} or lu in {"commercial", "retail"}:
        return "comercial"
    if tags.get("shop") or tags.get("office"):
        return "comercial"
    if b in {"house", "residential", "apartments", "detached", "semidetached_house",
             "terrace", "bungalow", "dormitory"} or lu == "residential":
        return "residencial"
    if b in {"school", "hospital", "church", "university", "public", "civic", "government"}:
        return "institucional"
    if tags.get("amenity") in {"school", "hospital", "university", "place_of_worship"}:
        return "institucional"
    return "indeterminado"


def consultar_anel(lat: float, lon: float) -> dict[str, Any]:
    consulta = f"""[out:json][timeout:120];
(
  way(around:{RAIO_M},{lat},{lon})["building"];
  way(around:{RAIO_M},{lat},{lon})["landuse"~"industrial|commercial|retail|residential"];
  relation(around:{RAIO_M},{lat},{lon})["building"];
  relation(around:{RAIO_M},{lat},{lon})["landuse"~"industrial|commercial|retail|residential"];
);
out tags geom;"""
    for tentativa in range(1, P13.TENTATIVAS + 1):
        r = requests.post(P13.OVERPASS, data={"data": consulta},
                          headers={"User-Agent": P13.USER_AGENT}, timeout=240)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 504):
            espera = P13.ESPERA_APOS_429_S * tentativa
            print(f"    HTTP {r.status_code} — aguardando {espera:.0f}s "
                  f"({tentativa}/{P13.TENTATIVAS})")
            time.sleep(espera)
            continue
        raise RuntimeError(f"Overpass HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError("Overpass não respondeu 200")


def main() -> int:
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")]
    DIR_CACHE.mkdir(parents=True, exist_ok=True)

    pontos = []
    for _, r in par.iterrows():
        pontos.append((r.site_id, r.site_id, "tratamento", float(r.lat), float(r.lon)))
        pontos.append((r.site_id, r.site_id_controle, "controle",
                       float(r.lat_controle), float(r.lon_controle)))

    registros = []
    for campus, pid, tipo, lat, lon in pontos:
        cache = DIR_CACHE / f"{pid}.json"
        if cache.exists():
            dados = json.loads(cache.read_text(encoding="utf-8"))
        else:
            print(f"  consultando {pid} ({tipo})...")
            dados = consultar_anel(lat, lon)
            cache.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            time.sleep(P13.ESPERA_S)

        contagem = dict.fromkeys(CATEGORIAS, 0)
        area = dict.fromkeys(CATEGORIAS, 0.0)
        for el in dados.get("elements", []):
            tags = el.get("tags") or {}
            cat = categorizar(tags)
            contagem[cat] += 1
            geom = el.get("geometry")
            if geom and len(geom) >= 3:
                try:
                    area[cat] += P13.area_ha(geom)
                except Exception:
                    pass

        n = sum(contagem.values())
        linha = {"campus": campus, "site_id": pid, "tipo": tipo, "raio_m": RAIO_M, "n_feicoes": n,
                 "interpretavel": n >= MIN_FEICOES}
        for c in CATEGORIAS:
            linha[f"n_{c}"] = contagem[c]
            linha[f"ha_{c}"] = round(area[c], 3)
            linha[f"pct_{c}"] = round(100.0 * contagem[c] / n, 2) if n else np.nan
        registros.append(linha)
        print(f"  {pid:34s} ({tipo:11s}) {n:5d} feicoes"
              f"{'' if n >= MIN_FEICOES else '  <- poucas, fora do teste'}")

    df = pd.DataFrame(registros)
    C.salvar_csv(df, SAIDA)

    # ---------------------------------------------------------------- tratamento vs controle
    linhas = []
    for cat in CATEGORIAS:
        col = f"pct_{cat}"
        difs = []
        for campus, g in df[df.interpretavel].groupby("campus"):
            t = g[g.tipo == "tratamento"][col]
            c = g[g.tipo == "controle"][col]
            if t.empty or c.empty or t.isna().all() or c.isna().all():
                continue
            difs.append(float(t.iloc[0] - c.iloc[0]))
        if not difs:
            continue
        d = np.asarray(difs)
        n, k = len(d), int((d > 0).sum())
        p_bi = min(1.0, 2 * sum(math.comb(n, i) * 0.5**n
                                for i in range(0, min(k, n - k) + 1)))
        linhas.append({
            "categoria": cat, "n_pares": n, "n_maior_no_tratamento": k,
            "diferenca_mediana_pp": round(float(np.median(d)), 3),
            "p_bilateral": round(p_bi, 4),
            "media_tratamento_pct": round(float(df[(df.tipo == "tratamento") & df.interpretavel][col].mean()), 2),
            "media_controle_pct": round(float(df[(df.tipo == "controle") & df.interpretavel][col].mean()), 2),
        })
    resumo = pd.DataFrame(linhas).sort_values("diferenca_mediana_pp", ascending=False)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    # ---------------------------------------------------------------- figura
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))
    cores = {"residencial": "#E74C3C", "comercial": "#F39C12",
             "industrial_logistico": "#34495E", "institucional": "#8E44AD",
             "indeterminado": "#BDC3C7"}
    ok = df[df.interpretavel]
    x = np.arange(len(CATEGORIAS))
    larg = 0.36
    ax1.bar(x - larg / 2, [ok[ok.tipo == "tratamento"][f"pct_{c}"].mean() for c in CATEGORIAS],
            larg, label="entorno de data center", color="#1A5276")
    ax1.bar(x + larg / 2, [ok[ok.tipo == "controle"][f"pct_{c}"].mean() for c in CATEGORIAS],
            larg, label="controle pareado", color="#95A5A6")
    ax1.set_xticks(x)
    ax1.set_xticklabels([c.replace("_", "\n") for c in CATEGORIAS], fontsize=8)
    ax1.set_ylabel("% das feições no anel de 1 km")
    ax1.set_title(f"Composição do entorno (n={ok.campus.nunique()} pares interpretáveis)",
                  fontsize=10)
    ax1.legend(frameon=False, fontsize=9)
    ax1.grid(axis="y", alpha=0.25)

    r = resumo.set_index("categoria")
    cats = [c for c in CATEGORIAS if c in r.index]
    vals = [r.loc[c, "diferenca_mediana_pp"] for c in cats]
    ax2.barh(range(len(cats)), vals, color=[cores[c] for c in cats])
    ax2.axvline(0, color="#333", lw=1)
    ax2.set_yticks(range(len(cats)))
    ax2.set_yticklabels([c.replace("_", " ") for c in cats], fontsize=9)
    for i, c in enumerate(cats):
        ax2.text(vals[i], i, f"  p={r.loc[c, 'p_bilateral']:.2f}", va="center", fontsize=8)
    ax2.set_xlabel("diferença mediana tratamento − controle (p.p.)")
    ax2.set_title("Que tipo de construção há a mais no entorno?", fontsize=10)
    ax2.grid(axis="x", alpha=0.25)

    fig.suptitle("Passo 21 — o que existe no anel (OSM, transversal: composição, não mudança)",
                 fontsize=11, y=0.99)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print("\n--- composição do entorno: data center vs. controle ---")
    for _, r0 in resumo.iterrows():
        print(f"  {r0.categoria:22s} DC {r0.media_tratamento_pct:5.1f}%  "
              f"ctrl {r0.media_controle_pct:5.1f}%  "
              f"dif {r0.diferenca_mediana_pp:+6.2f} pp  "
              f"({r0.n_maior_no_tratamento}/{r0.n_pares}, p={r0.p_bilateral:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
