"""Passo 14 — o excesso é o prédio ou é desenvolvimento induzido no entorno?

Rode com:

    python modelo-impacto/scripts/impacto_dc_14_footprint_vs_anel.py

## A pergunta que o passo 12 deixou aberta

O passo 12 achou que o tratamento tem mais pixels virando "construída" que o controle: 13 de 15
pares, excesso mediano de 1,53 ha num raio de 500 m. Mas um disco de 500 m tem 78 ha. Duas
interpretações muito diferentes cabem nesse número:

- **"o data center ocupa N hectares"** — trivial, e não é impacto: é a definição do
  empreendimento;
- **"o data center puxa urbanização em volta"** — esta sim é a afirmação que interessa ao modelo
  de impacto.

Com o footprint real do passo 13 dá para separar as duas, medindo em zonas concêntricas:

| zona | o que responde |
|---|---|
| dentro do footprint | o classificador enxerga o prédio? |
| footprint → 500 m | há conversão colada ao terreno? |
| 500 m → 1 km | o efeito se estende? |
| 1 km → 2 km | ainda há excesso longe? |

No controle não há footprint (é um lugar sem data center, por definição), então as zonas são
círculos concêntricos de **mesmo raio** em volta do ponto de controle. A zona interna do controle
é a hipótese nula da zona interna do tratamento.

## Leitura esperada

- Excesso **só** dentro do footprint → o sinal do passo 12 é o próprio prédio. Verdadeiro, mas não
  é impacto no entorno.
- Excesso dentro **e** nos anéis, decaindo com a distância → há conversão além do terreno, que é o
  que sustentaria a afirmação de impacto induzido.
- Excesso só nos anéis e não no footprint → sinal de problema: o classificador não estaria vendo o
  prédio, e a interpretação do passo 12 precisaria ser revista.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_11_sensibilidade_buffer as P11
import impacto_dc_12_trajetoria_pixel as P12
import impacto_dc_comum as C

ANEIS_KM = [(0.0, 0.5), (0.5, 1.0), (1.0, 2.0)]
SAIDA = C.DIR_SAIDA / "footprint_vs_anel.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "footprint_vs_anel_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_08_footprint_vs_anel.png"


def poligono_do_cache(site_id: str, osm_id: str) -> list[dict[str, float]] | None:
    """Recupera a geometria escolhida no passo 13 a partir do cache cru do Overpass."""
    cache = C.DIR_SAIDA / "osm" / f"{site_id}.json"
    if not cache.exists():
        return None
    dados = json.loads(cache.read_text(encoding="utf-8"))
    tipo_alvo, id_alvo = osm_id.split("/")
    for elemento in dados.get("elements", []):
        if elemento.get("type") == tipo_alvo and str(elemento.get("id")) == id_alvo:
            return elemento.get("geometry")
    return None


def mascara_footprint(tif: Path, anel: list[dict[str, float]]) -> np.ndarray:
    """Máscara booleana dos pixels dentro do polígono, no CRS/grade do raster."""
    from pyproj import Transformer

    with rasterio.open(tif) as src:
        transform, altura, largura, crs = src.transform, src.height, src.width, src.crs
    para_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = para_crs.transform([p["lon"] for p in anel], [p["lat"] for p in anel])
    poligono = {"type": "Polygon", "coordinates": [list(zip(xs, ys, strict=True))]}
    # geometry_mask devolve True FORA da geometria; invertemos para "dentro"
    return ~geometry_mask([poligono], out_shape=(altura, largura), transform=transform,
                          all_touched=True)


def contar_zona(pilha: np.ndarray, mascara: np.ndarray) -> dict[str, Any]:
    """Reusa exatamente a contagem de assinaturas do passo 12, restrita a uma zona."""
    return P12.contar_assinaturas(pilha, mascara)


def composicao_footprint(pilha: np.ndarray, mascara: np.ndarray) -> dict[str, Any]:
    """Decompõe o footprint entre "já era construída antes da obra" e "virou construída".

    Sem esta separação, um `virou_construida` baixo é ambíguo e leva à conclusão errada. Ele pode
    significar (a) o classificador não enxerga o prédio — o que invalidaria a leitura do passo 12 —
    ou (b) não havia nada a ver aparecer, porque o terreno **já era** classificado como construída
    antes da obra. São diagnósticos opostos e a coluna `pct_ja_construida` distingue os dois.
    """
    borda = P12.ANOS_BORDA
    valido = np.all(pilha > 0, axis=0) & mascara
    inicio, fim = pilha[:borda], pilha[-borda:]
    n = int(valido.sum())
    if n == 0:
        return {"n_pixels_footprint": 0, "pct_ja_construida": np.nan,
                "pct_virou_construida_fp": np.nan, "pct_construida_no_fim": np.nan}
    ja = int((np.all(inicio == P12.CONSTRUIDA, axis=0) & valido).sum())
    virou = int((np.all(inicio != P12.CONSTRUIDA, axis=0)
                 & np.all(fim == P12.CONSTRUIDA, axis=0) & valido).sum())
    no_fim = int((np.all(fim == P12.CONSTRUIDA, axis=0) & valido).sum())
    return {
        "n_pixels_footprint": n,
        "pct_ja_construida": round(100.0 * ja / n, 2),
        "pct_virou_construida_fp": round(100.0 * virou / n, 2),
        "pct_construida_no_fim": round(100.0 * no_fim / n, 2),
    }


def main() -> int:
    fp_path = C.DIR_SAIDA / "footprints_osm.csv"
    if not fp_path.exists():
        print(f"ERRO: {fp_path} não existe — rode o passo 13 antes.", file=sys.stderr)
        return 1
    footprints = pd.read_csv(fp_path)
    com_fp = footprints[footprints["metodo_footprint"].str.startswith("osm_", na=False)]
    print(f"Passo 14 — {len(com_fp)} campi com footprint de {len(footprints)}")
    if com_fp.empty:
        print("Nenhum footprint disponível: nada a decompor.")
        return 1

    painel = pd.read_csv(C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv")
    registros: list[dict[str, Any]] = []

    for _, fp in com_fp.iterrows():
        site_id = fp["site_id"]
        par = painel[painel["pareado_com"] == site_id]
        if par.empty:
            continue
        anel_geom = poligono_do_cache(site_id, fp["osm_id"])
        if not anel_geom:
            print(f"  {site_id}: geometria não encontrada no cache — pulando")
            continue

        for tipo in ("tratamento", "controle"):
            ponto = par[par["tipo"] == tipo]
            if ponto.empty:
                continue
            pid = ponto["site_id"].iloc[0]
            sensor = ponto["sensor"].iloc[0]
            anos = sorted(ponto["ano"].tolist())
            if len(anos) < 2 * P12.ANOS_BORDA + 1:
                continue
            tif = C.caminho_classificado(sensor, pid, anos[0])
            pilha = P12.empilhar(pid, sensor, anos)
            raios = P11.mascaras_por_raio(tif, float(ponto["lat"].iloc[0]),
                                          float(ponto["lon"].iloc[0]))

            # Zona 0: o footprint em si — só existe no tratamento. No controle, o equivalente é o
            # disco central de mesmo raio nominal (0,5 km), que é a hipótese nula.
            if tipo == "tratamento":
                try:
                    m_fp = mascara_footprint(tif, anel_geom)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {site_id}: falha ao rasterizar footprint ({exc!r})")
                    m_fp = np.zeros(pilha.shape[1:], dtype=bool)
                registros.append({
                    "pareado_com": site_id, "site_id": pid, "tipo": tipo, "zona": "footprint",
                    "raio_int_km": 0.0, "raio_ext_km": 0.0,
                    "area_zona_ha": fp["area_footprint_ha"],
                    "metodo_footprint": fp["metodo_footprint"],
                    **contar_zona(pilha, m_fp),
                    **composicao_footprint(pilha, m_fp),
                })

            for r_int, r_ext in ANEIS_KM:
                mascara = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
                registros.append({
                    "pareado_com": site_id, "site_id": pid, "tipo": tipo,
                    "zona": f"{r_int:g}-{r_ext:g}km",
                    "raio_int_km": r_int, "raio_ext_km": r_ext,
                    "area_zona_ha": round(np.pi * (r_ext**2 - r_int**2) * 100, 2),
                    **contar_zona(pilha, mascara),
                })
        print(f"  {site_id}: ok ({fp['metodo_footprint']}, {fp['area_footprint_ha']:.2f} ha)")

    longo = pd.DataFrame(registros)
    for assinatura in P12.ASSINATURAS:
        longo[f"pct_{assinatura}"] = (
            100.0 * longo[assinatura] / longo["pixels_validos_mascara"].replace(0, np.nan)
        )
    C.salvar_csv(longo, SAIDA)

    # Resumo: excesso do tratamento sobre o controle, por zona
    linhas = []
    for zona, g in longo[longo["zona"] != "footprint"].groupby("zona"):
        for assinatura in P12.ASSINATURAS:
            col = f"pct_{assinatura}"
            difs = []
            for _, p in g.groupby("pareado_com"):
                t = p[p["tipo"] == "tratamento"][col]
                c = p[p["tipo"] == "controle"][col]
                if t.empty or c.empty or t.isna().all() or c.isna().all():
                    continue
                difs.append(float(t.iloc[0] - c.iloc[0]))
            if not difs:
                continue
            n = len(difs)
            pos = sum(1 for v in difs if v > 0)
            linhas.append({
                "zona": zona, "assinatura": assinatura, "n_pares": n, "n_positivo": pos,
                "frac_positivo": round(pos / n, 3),
                "p_unilateral": round(P12.p_bin_superior(pos, n), 4),
                "excesso_mediano_pp": round(float(np.median(difs)), 4),
            })
    resumo = pd.DataFrame(linhas)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    # O footprint em si: o classificador vê o prédio?
    fp_rows = longo[longo["zona"] == "footprint"]
    print()
    print("=== Dentro do footprint: o terreno já era construído antes da obra? ===")
    print(f"{'campus':26} {'ha':>6} {'px':>5} {'já constr.':>11} {'virou':>8} "
          f"{'constr. no fim':>15}")
    for _, r in fp_rows.iterrows():
        if not r["n_pixels_footprint"]:
            print(f"{r['pareado_com']:26} {r['area_zona_ha']:>6.2f} {0:>5} "
                  f"{'—':>11} {'—':>8} {'sem pixel válido':>15}")
            continue
        print(f"{r['pareado_com']:26} {r['area_zona_ha']:>6.2f} "
              f"{int(r['n_pixels_footprint']):>5} {r['pct_ja_construida']:>10.1f}% "
              f"{r['pct_virou_construida_fp']:>7.1f}% {r['pct_construida_no_fim']:>14.1f}%")
    validos = fp_rows[fp_rows["n_pixels_footprint"] > 0]
    if len(validos):
        ja = validos["pct_ja_construida"].median()
        virou = validos["pct_virou_construida_fp"].median()
        print(f"\nmedianas: já era construída {ja:.1f}% · virou construída {virou:.1f}%")
        if ja > 2 * max(virou, 0.1):
            print("LEITURA: o `virou construída` baixo NÃO é o classificador falhando em ver o")
            print("prédio — é não haver o que ver aparecer, porque o terreno já era construído")
            print("antes da obra. Consistente com data centers erguidos em parques industriais")
            print("existentes (e com as tags `Retrofitted` da planilha do Guilherme).")
            print("CONSEQUÊNCIA: o excesso medido no passo 12 NÃO é o prédio em si — é conversão")
            print("no entorno dele. Que é a afirmação mais forte, e a que precisa de mais cuidado.")

    print()
    print("=== Excesso do tratamento por zona (assinatura virou_construida) ===")
    foco = resumo[resumo["assinatura"] == "virou_construida"].sort_values("zona")
    print(f"{'zona':12} {'trat>ctrl':>10} {'fração':>8} {'p':>8} {'excesso pp':>12}")
    for _, r in foco.iterrows():
        marca = f"{int(r['n_positivo'])}/{int(r['n_pares'])}"
        print(f"{r['zona']:12} {marca:>10} {r['frac_positivo']:>8.2f} "
              f"{r['p_unilateral']:>8.3f} {r['excesso_mediano_pp']:>12.4f}")

    # Figura
    fig, ax = plt.subplots(figsize=(9.0, 5.6))
    cores = {"virou_construida": "#C0392B", "virou_construida_via_solo": "#F5A623",
             "vegetacao_para_construida": "#1B5E20"}
    ordem = [f"{a:g}-{b:g}km" for a, b in ANEIS_KM]
    for assinatura, g in resumo.groupby("assinatura"):
        g = g.set_index("zona").reindex(ordem).reset_index()
        ax.plot(g["zona"], g["excesso_mediano_pp"], "o-", linewidth=2.2, markersize=8,
                color=cores.get(assinatura, "#5D6D7E"), label=assinatura)
    ax.axhline(0, color="gray", linestyle="--", linewidth=1.4)
    ax.set_xlabel("Zona (distância ao data center)")
    ax.set_ylabel("excesso do tratamento (pontos percentuais dos pixels)")
    ax.set_title("O excesso decai com a distância ao empreendimento?\n"
                 "positivo = mais conversão para construída no tratamento", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    SAIDA_FIGURA.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=140)
    plt.close(fig)
    print(f"\n  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
