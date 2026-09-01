"""Kit de rotulagem manual "solo exposto / em obras" (SV-09b) — candidatos por ESTRATO.

Rode com: python -m sentinela.labeling.candidatos_estrato --estrato <nome|all>

## O que muda em relação a SV-09 (`sentinela.labeling.candidatos`)

SV-09 gerava candidatos **por site**, com teto de 60/site — escalado para 25 AOIs isso vira 1.500
polígonos (~21 h de trabalho humano, inviável em 14 dias com uma pessoa). SV-09b corrige a unidade
de amostragem: o classificador é por pixel, sobre reflectância harmonizada, e não tem `site_id`
como feature (SV-27 proíbe). O que o modelo não viu ainda não é "mais um site do mesmo bioma", é
**outro bioma** — solo e vegetação diferentes mudam a assinatura espectral de verdade.

Este módulo **reusa a heurística de SV-09 sem alterá-la** (`_detectar_par`, `_anos_disponiveis`,
`_ler_dados_ano`, `_compor_rgb`, `_plotar_geom`, todos importados de `.candidatos`) — só reorganiza
a chamada por **estrato (bioma x era de sensor)** em vez de por site, com teto de 25
candidatos/estrato em vez de 60/site, priorizando anos de fase `durante` (SV-27/`config/sites.geojson`)
e mantendo diversidade de AOI dentro do estrato (round-robin entre sites antes de aplicar o teto —
ver `_selecionar_com_diversidade`).

## Estratos: definidos a partir do tier 1 REAL de `config/sites.geojson`, não da tabela do enunciado

A tabela de SV-09b é só uma expectativa a confirmar. Rodando `definir_estratos()` sobre o tier 1 real
(13 AOIs, SV-24/SV-25):

- `mataatlantica_landsat` / `mataatlantica_s2` — Mata Atlântica tem 9 AOIs de tier 1, dá pra separar
  por era sem quebrar o critério de >= 2 AOIs distintas em cada metade.
- `caatinga` — só 2 AOIs de tier 1 (`angonap-fortaleza`, `ascenty-maracanau`). Não splitado por era:
  `ascenty-maracanau` tem a fase `durante` inteira (2014-2015) na era Landsat; separar por era
  deixaria 1 AOI por metade, quebrando o critério de diversidade E jogando fora o único exemplo real
  de canteiro daquele site. Estrato único, candidatos vêm de ambos os sensores.
- `cerrado` — só 1 AOI de tier 1 (`everest-goiania`). Criado porque a regra é "sem AOI não cria", não
  "com 1 só AOI não cria" — mas o critério de aceite "'>= 2 AOIs distintas" não pode ser satisfeito
  com os dados atuais. Reportado como achado, não escondido.
- `amazonia` — mesma situação de `cerrado`, só 1 AOI (`clickip-manaus`).
- `pampa` — **não criado**: nenhuma AOI de tier 1 tem `bioma == "Pampa"` em `config/sites.geojson`
  (a única AOI do Sul, `scala-spoapa01` em Porto Alegre, está classificada como Mata Atlântica, que é
  o bioma oficial IBGE daquela região — RS tem os dois biomas, mas Porto Alegre cai no domínio de
  Mata Atlântica). A tabela do enunciado previa Pampa; os dados reais não confirmam.

## Saída

- `data/interim/candidatos_estrato_{estrato}.geojson` (EPSG:4326, não commitado).
- `reports/figures/rotulagem/{estrato}/{site_id}_{ano}_rgb.png` e `..._falsacor.png`, um par por
  (site, ano) que efetivamente entrou nos candidatos selecionados do estrato.
- `reports/figures/rotulagem/{estrato}/prancha_contexto.png` — painel lado a lado com o candidato
  mais "classe 3 provável" (menor NDVI médio) e o confusor mais provável daquele bioma (candidato com
  `classe_worldcover` de vegetação rala/construída, se houver), com legenda específica do bioma.
- `data/labels_manual/_cotas.csv` — cota por (estrato, classe_id), descontando o que já existe em
  `data/labels_manual/*.geojson` (exceto `_template.geojson`).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import rasterio.transform
from pyproj import Transformer
from shapely.ops import transform as shapely_transform

from ..config import REPO_ROOT, SETTINGS
from .candidatos import (
    CRS_GRADE,
    CRS_SAIDA,
    _anos_disponiveis,
    _compor_rgb,
    _detectar_par,
    _ler_dados_ano,
    _plotar_geom,
)

MAX_CANDIDATOS_POR_ESTRATO = 25

# Cota por classe dentro de cada estrato (soma 40, ver docs/tarefas/SV-09b-...). Os grupos
# "negativos difíceis" (classes 2 e 4) e "âncoras" (classes 1 e 5) do enunciado são combinados —
# como `_cotas.csv` precisa de uma linha por classe_id, a cota é dividida dentro de cada grupo.
COTAS_POR_CLASSE: dict[int, int] = {
    3: 15,  # solo exposto/obras — cota cheia do enunciado
    2: 10,  # negativos difíceis, metade em vegetacao_rala
    4: 10,  # negativos difíceis, metade em construida_urbana
    1: 3,  # âncoras, maioria em vegetacao_densa
    5: 2,  # âncoras, água costuma ter menos candidatos plausíveis por AOI
}
assert sum(COTAS_POR_CLASSE.values()) == 40

_BIOMA_SLUG = {
    "Mata Atlântica": "mataatlantica",
    "Caatinga": "caatinga",
    "Cerrado": "cerrado",
    "Amazônia": "amazonia",
    "Pampa": "pampa",
}

# Texto de apoio da prancha de contexto — mesma decisão fechada documentada na seção nova de
# docs/guia-rotulagem.md ("Como a classe 3 muda de bioma para bioma"). Mantido aqui só para rotular
# a figura; a fonte de verdade do critério é o guia, não este dict.
_CONTEXTO_BIOMA = {
    "Mata Atlântica": (
        "Confusor mais comum: lavoura recém-colhida (padrão de sulcos regulares) e campo de futebol "
        "seco. Ver guia-rotulagem.md secoes 3.3/3.4."
    ),
    "Caatinga": (
        "ERRO MAIS PROVAVEL DO CONJUNTO: vegetacao decidua sem folha no periodo seco parece solo "
        "exposto mas E classe 2 (vegetacao rala), nao 3. Olhe o padrao de galhos/copas na falsa-cor "
        "(ainda ha estrutura lenhosa, mesmo sem folha) antes de marcar classe 3."
    ),
    "Cerrado": (
        "Confusor: solo exposto natural em pastagem degradada (textura uniforme, sem maquinario, sem "
        "geometria de projeto) vs. terraplenagem real (contorno ditado pelo projeto de obra, "
        "maquinario/pilha visivel)."
    ),
    "Amazônia": (
        "Confusor: estrada de terra e patio de madeira/serraria (uso consolidado, mesmo traçado ano "
        "a ano) vs. canteiro de obra (contorno muda de forma entre anos, ligado a construcao ativa)."
    ),
    "Pampa": (
        "Confusor: campo nativo seco (textura de gramínea, mesmo NDVI baixo) vs. solo raspado de "
        "verdade (textura mineral uniforme, sem nenhuma resposta de vegetação)."
    ),
}


# --------------------------------------------------------------------------------------------
# Estratos — tier 1 real de config/sites.geojson
# --------------------------------------------------------------------------------------------


def _tier1_aois() -> list[dict[str, Any]]:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[(gdf["ativo"]) & (gdf["tier"] == 1)]
    cols = ["site_id", "bioma", "regiao", "periodo_pre", "periodo_durante", "periodo_pos"]
    return gdf[cols].to_dict("records")


def definir_estratos() -> dict[str, dict[str, Any]]:
    """Agrupa as AOIs de tier 1 por bioma; separa Mata Atlântica por era de sensor (>= 4 AOIs por
    metade, dá pra respeitar o critério de >= 2 AOIs distintas). Biomas com poucas AOIs viram um
    único estrato (sem split de era) para não fragmentar a diversidade que já é escassa."""
    aois = _tier1_aois()
    por_bioma: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in aois:
        por_bioma[a["bioma"]].append(a)

    estratos: dict[str, dict[str, Any]] = {}
    for bioma, lista in por_bioma.items():
        slug = _BIOMA_SLUG.get(bioma, bioma.lower().replace(" ", "_"))
        site_ids = sorted(a["site_id"] for a in lista)
        if bioma == "Mata Atlântica" and len(site_ids) >= 4:
            estratos[f"{slug}_landsat"] = {"bioma": bioma, "sensores": ("landsat",), "site_ids": site_ids}
            estratos[f"{slug}_s2"] = {"bioma": bioma, "sensores": ("s2",), "site_ids": site_ids}
        else:
            estratos[slug] = {"bioma": bioma, "sensores": ("landsat", "s2"), "site_ids": site_ids}
    return estratos


def _parse_periodo(periodo: str | None) -> tuple[int, int] | None:
    if not periodo:
        return None
    try:
        lo, hi = periodo.split("-")
        return int(lo), int(hi)
    except (ValueError, AttributeError):
        return None


def _fase_do_ano(props: dict[str, Any], ano: int) -> str | None:
    """`durante` > `pre`/`pos` na prioridade de checagem só para desempate de anos de sobreposição
    (não deveria acontecer com os períodos reais, mas evita ambiguidade se acontecer)."""
    for fase, campo in (("durante", "periodo_durante"), ("pre", "periodo_pre"), ("pos", "periodo_pos")):
        rng = _parse_periodo(props.get(campo))
        if rng and rng[0] <= ano <= rng[1]:
            return fase
    return None


# --------------------------------------------------------------------------------------------
# Geração de candidatos por estrato (reusa `_detectar_par` de SV-09, sem alterá-la)
# --------------------------------------------------------------------------------------------


def _selecionar_com_diversidade(candidatos: list[dict[str, Any]], teto: int) -> list[dict[str, Any]]:
    """Round-robin entre AOIs (prioriza fase `durante`, depois área) até o teto — garante que o
    corte de MAX_CANDIDATOS_POR_ESTRATO não deixe o estrato dominado por uma única AOI (critério de
    aceite: cada estrato precisa de candidatos de >= 2 AOIs distintas, quando o estrato tem >= 2)."""
    por_site: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in candidatos:
        por_site[c["site_id"]].append(c)
    for lst in por_site.values():
        lst.sort(key=lambda c: (c["fase"] != "durante", -c["area_ha"]))

    ordem_sites = sorted(por_site.keys())
    selecionados: list[dict[str, Any]] = []
    i = 0
    while len(selecionados) < teto and any(por_site[s] for s in ordem_sites):
        site = ordem_sites[i % len(ordem_sites)]
        if por_site[site]:
            selecionados.append(por_site[site].pop(0))
        i += 1
    return selecionados


def gerar_candidatos_estrato(definicao: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    aois_by_id = {a["site_id"]: a for a in _tier1_aois()}
    todos: list[dict[str, Any]] = []
    limiares_relatorio: list[dict[str, Any]] = []

    for site_id in definicao["site_ids"]:
        props = aois_by_id[site_id]
        for sensor in definicao["sensores"]:
            anos = _anos_disponiveis(sensor, site_id)
            anos_set = set(anos)
            for ano_n in anos:
                if (ano_n - 1) not in anos_set:
                    continue
                candidatos, limiares = _detectar_par(site_id, sensor, ano_n)
                fase = _fase_do_ano(props, ano_n)
                for c in candidatos:
                    c["fase"] = fase
                    c["bioma"] = definicao["bioma"]
                todos.extend(candidatos)
                if limiares is not None:
                    limiares["site_id"] = site_id
                    limiares_relatorio.append(limiares)

    selecionados = _selecionar_com_diversidade(todos, MAX_CANDIDATOS_POR_ESTRATO)
    selecionados.sort(key=lambda c: (c["fase"] != "durante", -c["area_ha"]))
    for i, c in enumerate(selecionados, start=1):
        c["candidato_id"] = i
    return selecionados, limiares_relatorio


def _escrever_geojson_estrato(estrato: str, candidatos: list[dict[str, Any]]) -> Path:
    transformer = Transformer.from_crs(CRS_GRADE, CRS_SAIDA, always_xy=True)

    def _reprojetar(geom):
        return shapely_transform(lambda x, y: transformer.transform(x, y), geom)

    features = []
    for c in candidatos:
        geom_4326 = _reprojetar(c["_geom_31983"])
        props = {k: v for k, v in c.items() if k != "_geom_31983"}
        features.append({"type": "Feature", "geometry": geom_4326.__geo_interface__, "properties": props})

    fc = {
        "type": "FeatureCollection",
        "name": f"candidatos_estrato_{estrato}",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }

    out_path = SETTINGS.interim_dir / f"candidatos_estrato_{estrato}.geojson"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------------------------
# Recortes visuais por estrato (RGB + falsa-cor), reusando funções de plot de SV-09
# --------------------------------------------------------------------------------------------


def _salvar_recorte_estrato(
    dados: dict[str, Any], estrato: str, site_id: str, ano: int, candidatos_ano: list[dict[str, Any]], *, tipo: str
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bandas_rgb = ("red", "green", "blue") if tipo == "rgb" else ("swir1", "nir", "red")
    rgb = _compor_rgb(dados, bandas_rgb)

    transform = dados["transform"]
    h, w = dados["valido"].shape
    left, top = transform.c, transform.f
    right = left + w * transform.a
    bottom = top + h * transform.e
    extent = (left, right, bottom, top)

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(rgb, extent=extent, origin="upper")
    for c in candidatos_ano:
        _plotar_geom(ax, c["_geom_31983"], c["candidato_id"])

    titulo = "RGB natural" if tipo == "rgb" else "Falsa-cor SWIR (swir1/nir/red)"
    ax.set_title(f"[{estrato}] {site_id} — {ano} — {titulo}")
    ax.set_xlabel("X (EPSG:31983, m)")
    ax.set_ylabel("Y (EPSG:31983, m)")
    fig.tight_layout()

    out_dir = REPO_ROOT / "reports" / "figures" / "rotulagem" / estrato
    out_dir.mkdir(parents=True, exist_ok=True)
    sufixo = "rgb" if tipo == "rgb" else "falsacor"
    out_path = out_dir / f"{site_id}_{ano}_{sufixo}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def gerar_recortes_estrato(estrato: str, candidatos: list[dict[str, Any]]) -> list[Path]:
    """Um par de PNGs (RGB + falsa-cor) por (site, ano) que efetivamente aparece entre os
    candidatos selecionados do estrato — evita gerar todo o histórico de todas as AOIs do bioma
    quando só uma fração entrou na amostra final.

    Anos de sobreposição (2019-2021) podem ter candidatos vindos tanto do par Landsat quanto do par
    Sentinel-2 daquele mesmo ano — mesmo padrão de `gerar_recortes_site` de SV-09: usa a imagem
    Sentinel-2 (10 m) como base visual quando disponível, com TODOS os candidatos daquele (site,
    ano) desenhados por cima (a geometria já está em coordenadas reais, EPSG:31983, não em pixels,
    então funciona independente de qual sensor gerou cada candidato). Um único PNG por (site, ano)
    — nome de arquivo sem sufixo de sensor, de propósito, para não sobrescrever silenciosamente um
    pelo outro (bug encontrado e corrigido durante SV-09b: a versão anterior gerava um arquivo por
    (site, ano, sensor) mas nomeava só por (site, ano), perdendo a imagem Landsat sempre que o
    mesmo (site, ano) também tinha candidato Sentinel-2)."""
    saidas: list[Path] = []
    chaves = sorted({(c["site_id"], c["ano"]) for c in candidatos})
    for site_id, ano in chaves:
        sensores_do_ano = {c["sensor"] for c in candidatos if c["site_id"] == site_id and c["ano"] == ano}
        ordem_preferencia = ["s2", "landsat"] if "s2" in sensores_do_ano else ["landsat", "s2"]
        dados = None
        for sensor in ordem_preferencia:
            dados = _ler_dados_ano(sensor, site_id, ano)
            if dados is not None:
                break
        if dados is None:
            print(f"AVISO: sem stack de features para {site_id}/{ano} — pulando recorte.", file=sys.stderr)
            continue
        candidatos_local = [c for c in candidatos if c["site_id"] == site_id and c["ano"] == ano]
        saidas.append(_salvar_recorte_estrato(dados, estrato, site_id, ano, candidatos_local, tipo="rgb"))
        saidas.append(_salvar_recorte_estrato(dados, estrato, site_id, ano, candidatos_local, tipo="falsacor"))
    return saidas


# --------------------------------------------------------------------------------------------
# Prancha de contexto — classe 3 vs. confusor mais provável daquele bioma, lado a lado
# --------------------------------------------------------------------------------------------


def _janela_pixels(dados: dict[str, Any], geom, pad_px: int = 25) -> tuple[int, int, int, int]:
    transform = dados["transform"]
    h, w = dados["valido"].shape
    minx, miny, maxx, maxy = geom.bounds
    row0, col0 = rasterio.transform.rowcol(transform, minx, maxy)
    row1, col1 = rasterio.transform.rowcol(transform, maxx, miny)
    r0 = max(0, min(row0, row1) - pad_px)
    r1 = min(h, max(row0, row1) + pad_px)
    c0 = max(0, min(col0, col1) - pad_px)
    c1 = min(w, max(col0, col1) + pad_px)
    r1 = max(r1, r0 + 1)
    c1 = max(c1, c0 + 1)
    return r0, r1, c0, c1


# NOTA (achado de SV-09b, corrigido): a primeira versão desta função cropava a reflectância ANTES
# de compor o RGB, ou seja, chamava `_compor_rgb` (de .candidatos, reusada sem alteração) só sobre
# a janela pequena em torno do candidato. Como `_compor_rgb`/`_estica_percentil` normalizam pelo
# percentil 2-98 dos pixels *da própria chamada*, um recorte pequeno (poucas centenas de pixels,
# às vezes com boa parte inválida perto da borda da AOI) produzia um estica-contraste ruidoso e
# ilegível — a prancha de contexto ficava pior que a imagem completa que ela deveria resumir. A
# correção: compor o RGB/falsa-cor sobre a CENA INTEIRA (mesmo estica-contraste dos PNGs de
# recorte normais, que já são legíveis) e só então cortar a janela do array já composto.


def _escolher_exemplo_e_confusor(candidatos: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Escolhe o candidato mais "classe 3 provável" (menor NDVI) e o confusor mais provável.

    Exclui candidatos com `classe_worldcover == "agua"` da escolha de "provável classe 3": o
    próprio NDVI muito negativo de água (não de solo mineral) às vezes vence o mínimo global —
    achado real de SV-09b (a heurística de BSI/NDVI de SV-09 confunde água pequena/turva com solo
    exposto com mais frequência na Caatinga do que em Mata Atlântica, ver "Como reportar"). Sem
    esse filtro a prancha de contexto ensinaria o rotulador com um exemplo errado."""
    if not candidatos:
        return None
    candidatos_nao_agua = [c for c in candidatos if c.get("classe_worldcover") != "agua"]
    pool_solo = candidatos_nao_agua or candidatos
    c_solo = min(pool_solo, key=lambda c: c["ndvi_medio"])
    confusores = [
        c for c in candidatos
        if c is not c_solo and c.get("classe_worldcover") in ("vegetacao_rala", "construida_urbana")
    ]
    if confusores:
        c_confusor = confusores[0]
    else:
        restantes = [c for c in candidatos if c is not c_solo]
        c_confusor = max(restantes, key=lambda c: c["ndvi_medio"]) if restantes else c_solo
    return c_solo, c_confusor


def gerar_prancha_contexto(estrato: str, definicao: dict[str, Any], candidatos: list[dict[str, Any]]) -> Path | None:
    escolha = _escolher_exemplo_e_confusor(candidatos)
    if escolha is None:
        return None
    c_solo, c_confusor = escolha

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(11, 11))
    pares = [("provável classe 3\n(menor NDVI)", c_solo), ("confusor provável\n(worldcover 2/4 ou maior NDVI)", c_confusor)]

    for col, (rotulo, cand) in enumerate(pares):
        dados = _ler_dados_ano(cand["sensor"], cand["site_id"], cand["ano"])
        if dados is None:
            for row in range(2):
                axes[row, col].axis("off")
            continue
        r0, r1, c0, c1 = _janela_pixels(dados, cand["_geom_31983"])

        for row, (tipo, bandas) in enumerate(
            [("RGB", ("red", "green", "blue")), ("Falsa-cor SWIR", ("swir1", "nir", "red"))]
        ):
            ax = axes[row, col]
            rgb_cena_inteira = _compor_rgb(dados, bandas)  # estica-contraste sobre a cena toda
            ax.imshow(rgb_cena_inteira[r0:r1, c0:c1], origin="upper")
            ax.set_xticks([])
            ax.set_yticks([])
            legenda = (
                f"{rotulo}\n{cand['site_id']} {cand['ano']} ({cand['sensor']}) — {tipo}\n"
                f"NDVI={cand['ndvi_medio']:.2f} BSI={cand['bsi_medio']:.2f} "
                f"worldcover={cand.get('classe_worldcover')}"
            )
            ax.set_title(legenda, fontsize=8)

    contexto = _CONTEXTO_BIOMA.get(definicao["bioma"], "")
    fig.suptitle(f"[{estrato}] {definicao['bioma']} — classe 3 vs. confusor local\n{contexto}", fontsize=10, wrap=True)
    fig.tight_layout(rect=(0, 0, 1, 0.90))

    out_dir = REPO_ROOT / "reports" / "figures" / "rotulagem" / estrato
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "prancha_contexto.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------------------------
# Cotas (`data/labels_manual/_cotas.csv`)
# --------------------------------------------------------------------------------------------


def _contar_ja_rotulado(site_ids: list[str]) -> dict[int, int]:
    """Conta polígonos já rotulados (`data/labels_manual/*.geojson`, exceto o template) cujo
    `site_id` pertence ao estrato, por `classe_id`. Hoje (2026-09-01) `data/labels_manual/` só tem
    `_template.geojson` — nenhum site foi de fato rotulado ainda nesta cópia do repositório, então
    a contagem sai zerada em todas as linhas (ver "Como reportar" da tarefa)."""
    import geopandas as gpd

    contagem: dict[int, int] = dict.fromkeys(COTAS_POR_CLASSE, 0)
    labels_dir = SETTINGS.labels_manual_dir
    if not labels_dir.exists():
        return contagem
    for p in labels_dir.glob("*.geojson"):
        if p.name == "_template.geojson":
            continue
        try:
            gdf = gpd.read_file(p)
        except Exception as exc:  # noqa: BLE001 - arquivo corrompido/incompatível não pode derrubar o script
            print(f"AVISO: não consegui ler {p} para contagem de cotas ({exc}).", file=sys.stderr)
            continue
        if "site_id" not in gdf.columns or "classe_id" not in gdf.columns:
            continue
        sub = gdf[gdf["site_id"].isin(site_ids)]
        for cid, n in sub["classe_id"].value_counts(dropna=True).items():
            cid_int = int(cid)
            if cid_int in contagem:
                contagem[cid_int] += int(n)
    return contagem


def gerar_cotas_csv(estratos: dict[str, dict[str, Any]]) -> Path:
    linhas = []
    for estrato in sorted(estratos):
        definicao = estratos[estrato]
        ja_rot = _contar_ja_rotulado(definicao["site_ids"])
        for classe_id, cota in COTAS_POR_CLASSE.items():
            ja = ja_rot.get(classe_id, 0)
            linhas.append(
                {
                    "estrato": estrato,
                    "classe_id": classe_id,
                    "cota": cota,
                    "ja_rotulado": ja,
                    "restante": max(cota - ja, 0),
                }
            )

    path = SETTINGS.labels_manual_dir / "_cotas.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["estrato", "classe_id", "cota", "ja_rotulado", "restante"])
        writer.writeheader()
        writer.writerows(linhas)
    return path


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Kit de rotulagem manual (SV-09b): candidatos a solo exposto/obras por estrato "
        "(bioma x era de sensor) + recortes visuais + prancha de contexto + cotas."
    )
    parser.add_argument("--estrato", required=True, help="nome do estrato (ver definir_estratos()), ou 'all'")
    args = parser.parse_args(argv)

    estratos = definir_estratos()
    alvo = sorted(estratos) if args.estrato == "all" else [args.estrato]

    soma_cotas = 0
    for nome in alvo:
        if nome not in estratos:
            raise SystemExit(f"estrato '{nome}' não existe. Disponíveis: {sorted(estratos)}")
        definicao = estratos[nome]
        candidatos, limiares = gerar_candidatos_estrato(definicao)
        geojson_path = _escrever_geojson_estrato(nome, candidatos)
        png_paths = gerar_recortes_estrato(nome, candidatos)
        prancha_path = gerar_prancha_contexto(nome, definicao, candidatos)

        aois_no_estrato = sorted({c["site_id"] for c in candidatos})
        durante_pct = (
            100.0 * sum(1 for c in candidatos if c["fase"] == "durante") / len(candidatos) if candidatos else 0.0
        )

        print(f"\n[{nome}] bioma={definicao['bioma']} AOIs configuradas={definicao['site_ids']}")
        print(f"[{nome}] {len(candidatos)} candidatos -> {geojson_path}")
        print(f"[{nome}] AOIs com candidato selecionado: {aois_no_estrato} ({len(aois_no_estrato)} distintas)")
        print(f"[{nome}] {durante_pct:.0f}% dos candidatos em fase 'durante'")
        for lim in limiares:
            print(
                f"  {lim['site_id']}/{lim['sensor']}/{lim['ano_anterior']}->{lim['ano']}: "
                f"BSI>=p85={lim['bsi_alto_p85']}, NDVI<=p25={lim['ndvi_baixo_p25']}, "
                f"NDVI_anterior>=p55={lim['ndvi_alto_anterior_p55']} -> {lim['n_pixels_candidatos']} px, "
                f"{lim['n_poligonos_apos_filtro_area']} polígonos"
            )
        print(f"[{nome}] {len(png_paths)} PNGs de recorte + prancha_contexto={prancha_path is not None}")
        soma_cotas += 40

    cotas_path = gerar_cotas_csv(estratos)
    print(f"\n[cotas] {cotas_path} — soma geral das cotas dos estratos definidos: {40 * len(estratos)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
