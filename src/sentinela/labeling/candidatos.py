"""Kit de rotulagem manual "solo exposto / em obras" (SV-09) — detecção de candidatos.

Rode com: python -m sentinela.labeling.candidatos --site <id|all>

Depende do stack de índices espectrais de SV-08 (`data/interim/features/{sensor}/{site_id}/{ano}.tif`
— 13 bandas: as 6 harmonizadas em reflectância + `ndvi`/`evi`/`ndwi`/`mndwi`/`ndbi`/`bsi`/`ndmi`,
`sentinela.features.indices`). Só lê NDVI/BSI de lá — nunca recalcula a fórmula aqui, para não
correr o risco de as duas tarefas divergirem sutilmente (ex.: tratamento de divisão por zero).
Se o stack de um site/ano ainda não existir, o par é pulado com aviso (rode
`python -m sentinela.features.indices --sensor all --site all --ano all` antes).

## O que este módulo NÃO é

A heurística abaixo é só um **filtro de atenção** para acelerar a rotulagem humana (SV-10) —
ela aponta onde é *provável* que exista solo exposto/obras, não decide a classe. Nunca deve
virar label automático nem entrar como feature de treino: se virasse, o modelo aprenderia a
decorar BSI/NDVI e a avaliação ficaria circular (a classe 3 já é definida em cima desses mesmos
índices). Por isso todo candidato sai com `classe_id: null` — quem decide a classe é SV-10.

## Heurística (percentis do próprio site/ano — nunca limiar absoluto)

Pixel é candidato quando, no ano N, tem **BSI alto e NDVI baixo**, e no ano N-1 (mesmo sensor)
tinha **NDVI alto** — ou seja, a transição vegetação -> solo que caracteriza início de obra.
Os limiares são percentis calculados sobre a própria distribuição de pixels válidos do site em
cada ano (nunca um valor fixo tipo "NDVI < 0.2"), porque a faixa de reflectância varia por sensor
(Landsat 30 m vs Sentinel-2 10 m, já harmonizados mas não idênticos), por época de composição e
pelo uso do solo predominante de cada site. Ver `PCT_BSI_ALTO`, `PCT_NDVI_BAIXO`,
`PCT_NDVI_ALTO_ANTERIOR` abaixo para os valores escolhidos e o raciocínio.

## Duas eras

Um site tem imagem Landsat (2013-2021) e Sentinel-2 (2019-2025), com sobreposição em 2019-2021
(ver `config/params.yml`). A transição vegetação -> obra dos data centers mais antigos só aparece
na era Landsat — por isso a detecção roda nos pares de anos consecutivos de **cada** sensor
disponível (Landsat: 2013-14, 14-15, ..., 20-21; Sentinel-2: 2019-20, ..., 24-25), e os candidatos
de todos os pares de um site são unidos num único `data/interim/candidatos_{site_id}.geojson`,
ordenados por área e limitados a `MAX_CANDIDATOS_POR_SITE`.

Área mínima por polígono: 0.5 ha na grade de 10 m (Sentinel-2), 1 ha na grade de 30 m (Landsat) —
abaixo disso é ruído de poucos pixels (nota da revisão de 2026-08-27 da tarefa SV-09).

## Saída

- `data/interim/candidatos_{site_id}.geojson` (EPSG:4326, não commitado — é interim/reproduzível).
- `reports/figures/rotulagem/{site_id}/{ano}_rgb.png` e `{ano}_falsacor.png`, um par por ano
  disponível do site (união Landsat + Sentinel-2 — anos de sobreposição usam a imagem Sentinel-2,
  10 m, como base visual), com os candidatos daquele ano numerados por cima.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import shapes as rio_shapes
from scipy import ndimage
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry import shape as shapely_shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union
from shapely.validation import make_valid

from .. import classes
from ..config import REPO_ROOT, SETTINGS
from ..features.indices import FATOR_ESCALA as FEATURES_FATOR_ESCALA
from ..features.indices import NODATA as FEATURES_NODATA
from ..features.indices import bandas_features

CRS_GRADE = "EPSG:31983"  # CRS de todos os .tif de imagem/features/label (SV-06/SV-06b/SV-07/SV-08)
CRS_SAIDA = "EPSG:4326"  # GeoJSON de saída — mesmo CRS do template de SV-10

PASTA_SENSOR = {"s2": "s2", "landsat": "landsat"}

# --------------------------------------------------------------------------------------------
# Limiares da heurística — percentis da distribuição do próprio site/ano, documentados aqui
# porque é um critério de aceite da tarefa explicar a escolha.
#
# PCT_BSI_ALTO = 85: BSI no top 15% mais "solo mineral" do ano N. Mais alto que 90 deixava sites
#   pequenos (poucos milhares de pixels válidos) sem nenhum candidato; mais baixo que 80 trazia
#   sombra/água nas bordas (BSI também sobe em água turva) misturada aos candidatos.
# PCT_NDVI_BAIXO = 25: NDVI no bottom 25% do ano N — inclui solo exposto E construído/água, de
#   propósito: a combinação com BSI alto e NDVI_anterior alto já filtra os dois.
# PCT_NDVI_ALTO_ANTERIOR = 55: NDVI acima da mediana no ano N-1 — "estava razoavelmente vegetado".
#   Não usamos um percentil mais alto (ex.: 75) porque descartaria pasto/vegetação rala (classe 2)
#   que também é ponto de partida legítimo de um canteiro de obras, não só vegetação densa.
#
# Testado nos 3 sites em 2026-08-27: produz entre 60 e 147 polígonos brutos por site antes do
# corte de MAX_CANDIDATOS_POR_SITE (nunca zero, nunca milhares) — ver "Como reportar" da tarefa.
# --------------------------------------------------------------------------------------------
PCT_BSI_ALTO = 85.0
PCT_NDVI_BAIXO = 25.0
PCT_NDVI_ALTO_ANTERIOR = 55.0

SENSOR_MIN_AREA_HA = {"s2": 0.5, "landsat": 1.0}
MAX_CANDIDATOS_POR_SITE = 60


# --------------------------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------------------------


def _sites_ativos() -> list[str]:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[gdf["ativo"] == True]
    return sorted(gdf["site_id"].tolist())


def _validar_site(site_id: str) -> str:
    sites = _sites_ativos()
    if site_id not in sites:
        raise SystemExit(f"site_id '{site_id}' não encontrado (ou inativo) em config/sites.geojson. Disponíveis: {sites}")
    return site_id


# --------------------------------------------------------------------------------------------
# Leitura do stack de features (SV-08) — reflectância das 6 bandas harmonizadas + NDVI/BSI
# --------------------------------------------------------------------------------------------


def _anos_disponiveis(sensor: str, site_id: str) -> list[int]:
    """Anos com `.tif` bruto (SV-06/SV-06b) já ingerido — a heurística ainda pode avisar e pular
    um ano específico depois se o stack de features (SV-08) correspondente não existir."""
    pasta = SETTINGS.raw_dir / PASTA_SENSOR[sensor] / site_id
    if not pasta.exists():
        return []
    anos = []
    for p in pasta.glob("*.tif"):
        try:
            anos.append(int(p.stem))
        except ValueError:
            continue
    return sorted(anos)


def _ler_dados_ano(sensor: str, site_id: str, ano: int) -> dict[str, Any] | None:
    """Lê `data/interim/features/{sensor}/{site_id}/{ano}.tif` (stack de 13 bandas de SV-08).

    Devolve reflectância das 6 bandas harmonizadas (para os recortes RGB/falsa-cor) + NDVI/BSI já
    prontos (para a heurística) + máscara de válidos. `None` se o stack ainda não existir (SV-08
    não rodou para esse site/ano) — quem chama decide se avisa e pula.
    """
    path = SETTINGS.interim_dir / "features" / PASTA_SENSOR[sensor] / site_id / f"{ano}.tif"
    if not path.exists():
        return None

    with rasterio.open(path) as ds:
        arr = ds.read()
        transform = ds.transform
        crs = ds.crs
        resolucao_m = abs(transform.a)
        descricoes = list(ds.descriptions)

    bandas = descricoes if all(descricoes) else bandas_features()
    idx = {b: i for i, b in enumerate(bandas)}

    valido = arr[idx["blue"]] != FEATURES_NODATA  # máscara conjunta (SV-08: mesma nas 13 bandas)

    # SV-26 mudou a gravação do stack de SV-08 para int16 x FATOR_ESCALA, mas só para as 13 AOIs
    # novas processadas por ela — os 3 sites originais (ascenty-vinhedo, odata-hortolandia,
    # scala-tambore) continuam float32 (SV-26 não os retrabalhou, mesma decisão de dataset.py).
    # Descalar sempre por 10000 quebraria os 3 originais (valor já correto dividido de novo, achado
    # real durante a correção desta função em SV-09b, 2026-09-01: percentis saíam ~0.0 pros 3
    # originais). Decide pelo dtype do próprio array, mesmo critério de
    # `sentinela.dataset.processar_combo`.
    arr_float = arr.astype(np.float32)
    if np.issubdtype(arr.dtype, np.integer):
        arr_float = arr_float / np.float32(FEATURES_FATOR_ESCALA)
    arr_float[:, ~valido] = 0.0

    refl = {b: arr_float[idx[b]] for b in ("blue", "green", "red", "nir", "swir1", "swir2")}

    return {
        "refl": refl,
        "ndvi": arr_float[idx["ndvi"]],
        "bsi": arr_float[idx["bsi"]],
        "valido": valido,
        "transform": transform,
        "crs": crs,
        "resolucao_m": resolucao_m,
    }


def _ler_label_ano(sensor: str, site_id: str, ano: int) -> np.ndarray | None:
    """Raster de label (SV-07) do mesmo site/sensor/ano, se existir — usado só para reportar
    `classe_worldcover` (o que o label fraco já dizia ali), nunca para decidir a classe."""
    path = SETTINGS.raw_dir / "labels" / PASTA_SENSOR[sensor] / site_id / f"{ano}.tif"
    if not path.exists():
        return None
    with rasterio.open(path) as ds:
        return ds.read(1)


def _classe_predominante(label_arr: np.ndarray | None, regiao: np.ndarray) -> str | None:
    if label_arr is None:
        return None
    valores = label_arr[regiao]
    valores = valores[valores != 0]
    if valores.size == 0:
        return None
    vals, contagens = np.unique(valores, return_counts=True)
    classe_id = int(vals[np.argmax(contagens)])
    return classes.ID_TO_SLUG.get(classe_id)


# --------------------------------------------------------------------------------------------
# Polígonos
# --------------------------------------------------------------------------------------------


def _normalizar_poligono(geom) -> Polygon | MultiPolygon | None:
    """Corrige geometria inválida (comum em blobs 8-conectados de `rasterio.features.shapes`:
    dois componentes que só se tocam por um vértice geram um anel "laço de sapato"/self-tangent,
    tecnicamente inválido pelas regras OGC mesmo vindo de um único `shapes()`, sem precisar de
    `unary_union`). `make_valid` pode devolver `GeometryCollection` (mistura polígono com ponto/
    linha degenerados no vértice de contato) — filtra só a parte poligonal. Devolve `None` se não
    sobrar nenhuma parte com área (geometria degenerada)."""
    if not geom.is_valid:
        geom = make_valid(geom)

    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom if geom.area > 0 else None
    if isinstance(geom, GeometryCollection):
        partes = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon)) and g.area > 0]
        if not partes:
            return None
        return partes[0] if len(partes) == 1 else unary_union(partes)
    return None


def _poligonizar(
    mask: np.ndarray,
    transform: rasterio.Affine,
    ndvi_n: np.ndarray,
    bsi_n: np.ndarray,
    label_arr: np.ndarray | None,
    *,
    site_id: str,
    sensor: str,
    ano: int,
    ano_anterior: int,
    min_area_ha: float,
) -> list[dict[str, Any]]:
    """Agrupa pixels candidatos (8-conectados) em polígonos, filtra por área mínima.

    Usa `scipy.ndimage.label` para identificar componentes conectados e `rasterio.features.shapes`
    (também com `connectivity=8`, para não fragmentar um componente já identificado como único)
    para traçar a geometria de cada um. Geometria fica em `CRS_GRADE` (EPSG:31983, metros) —
    reprojeção para `CRS_SAIDA` acontece só na escrita do GeoJSON final.
    """
    if not mask.any():
        return []

    estrutura = np.ones((3, 3), dtype=int)
    rotulado, n_regioes = ndimage.label(mask, structure=estrutura)

    candidatos: list[dict[str, Any]] = []
    for rid in range(1, n_regioes + 1):
        regiao = rotulado == rid
        geoms = [
            shapely_shape(geom)
            for geom, valor in rio_shapes(rotulado.astype(np.int32), mask=regiao, transform=transform, connectivity=8)
            if valor == rid
        ]
        if not geoms:
            continue
        geom = geoms[0] if len(geoms) == 1 else unary_union(geoms)
        geom = _normalizar_poligono(geom)
        if geom is None:
            continue
        area_ha = geom.area / 10000.0
        if area_ha < min_area_ha:
            continue

        candidatos.append(
            {
                "_geom_31983": geom,
                "site_id": site_id,
                "sensor": sensor,
                "ano": ano,
                "ano_anterior": ano_anterior,
                "area_ha": round(area_ha, 4),
                "ndvi_medio": round(float(np.mean(ndvi_n[regiao])), 4),
                "bsi_medio": round(float(np.mean(bsi_n[regiao])), 4),
                "classe_worldcover": _classe_predominante(label_arr, regiao),
                "classe_id": None,  # verificação de honestidade: NUNCA um label pronto disfarçado
            }
        )
    return candidatos


def _detectar_par(site_id: str, sensor: str, ano_n: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    ano_ant = ano_n - 1
    dados_n = _ler_dados_ano(sensor, site_id, ano_n)
    dados_ant = _ler_dados_ano(sensor, site_id, ano_ant)
    if dados_n is None or dados_ant is None:
        faltando = f"{sensor}/{site_id}/{ano_n if dados_n is None else ano_ant}"
        print(
            f"AVISO: stack de features ausente para {faltando} — pulando o par {ano_ant}->{ano_n} "
            f"(rode `python -m sentinela.features.indices --sensor all --site all --ano all` antes).",
            file=sys.stderr,
        )
        return [], None

    ndvi_n, bsi_n = dados_n["ndvi"], dados_n["bsi"]
    ndvi_ant = dados_ant["ndvi"]
    valido = dados_n["valido"] & dados_ant["valido"]
    if not valido.any():
        return [], None

    bsi_alto = float(np.percentile(bsi_n[valido], PCT_BSI_ALTO))
    ndvi_baixo = float(np.percentile(ndvi_n[valido], PCT_NDVI_BAIXO))
    ndvi_alto_ant = float(np.percentile(ndvi_ant[valido], PCT_NDVI_ALTO_ANTERIOR))

    mask = valido & (bsi_n >= bsi_alto) & (ndvi_n <= ndvi_baixo) & (ndvi_ant >= ndvi_alto_ant)

    label_arr = _ler_label_ano(sensor, site_id, ano_n)
    candidatos = _poligonizar(
        mask,
        dados_n["transform"],
        ndvi_n,
        bsi_n,
        label_arr,
        site_id=site_id,
        sensor=sensor,
        ano=ano_n,
        ano_anterior=ano_ant,
        min_area_ha=SENSOR_MIN_AREA_HA[sensor],
    )
    limiares = {
        "sensor": sensor,
        "ano": ano_n,
        "ano_anterior": ano_ant,
        "bsi_alto_p85": round(bsi_alto, 4),
        "ndvi_baixo_p25": round(ndvi_baixo, 4),
        "ndvi_alto_anterior_p55": round(ndvi_alto_ant, 4),
        "n_pixels_candidatos": int(mask.sum()),
        "n_poligonos_apos_filtro_area": len(candidatos),
    }
    return candidatos, limiares


# --------------------------------------------------------------------------------------------
# Orquestração por site
# --------------------------------------------------------------------------------------------


def gerar_candidatos_site(site_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Roda a heurística em todos os pares de anos consecutivos disponíveis (as duas eras),
    une, ordena por área e limita a `MAX_CANDIDATOS_POR_SITE`. Retorna (candidatos, limiares)."""
    todos: list[dict[str, Any]] = []
    limiares_relatorio: list[dict[str, Any]] = []

    for sensor in ("landsat", "s2"):
        anos = _anos_disponiveis(sensor, site_id)
        anos_set = set(anos)
        for ano_n in anos:
            if (ano_n - 1) not in anos_set:
                continue
            candidatos, limiares = _detectar_par(site_id, sensor, ano_n)
            todos.extend(candidatos)
            if limiares is not None:
                limiares_relatorio.append(limiares)

    todos.sort(key=lambda c: c["area_ha"], reverse=True)
    todos = todos[:MAX_CANDIDATOS_POR_SITE]
    for i, c in enumerate(todos, start=1):
        c["candidato_id"] = i

    return todos, limiares_relatorio


def _escrever_geojson(site_id: str, candidatos: list[dict[str, Any]]) -> Path:
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
        "name": f"candidatos_{site_id}",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }

    out_path = SETTINGS.interim_dir / f"candidatos_{site_id}.geojson"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------------------------
# Recortes visuais (RGB + falsa-cor SWIR) com candidatos numerados
# --------------------------------------------------------------------------------------------


def _estica_percentil(canal: np.ndarray, valido: np.ndarray) -> np.ndarray:
    amostra = canal[valido]
    if amostra.size == 0:
        return np.ones_like(canal)
    lo, hi = np.percentile(amostra, [2, 98])
    hi = max(hi, lo + 1e-6)
    esticado = np.clip((canal - lo) / (hi - lo), 0, 1)
    esticado[~valido] = 1.0
    return esticado


def _compor_rgb(dados: dict[str, Any], bandas_rgb: tuple[str, str, str]) -> np.ndarray:
    refl, valido = dados["refl"], dados["valido"]
    canais = [_estica_percentil(refl[b], valido) for b in bandas_rgb]
    return np.stack(canais, axis=-1)


def _plotar_geom(ax, geom, candidato_id: int) -> None:
    from shapely.geometry import MultiPolygon, Polygon

    poligonos = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    for poly in poligonos:
        if not isinstance(poly, Polygon):
            continue
        xs, ys = poly.exterior.xy
        ax.plot(xs, ys, color="yellow", linewidth=1.3)
    cx, cy = geom.centroid.x, geom.centroid.y
    ax.text(
        cx, cy, str(candidato_id), color="black", fontsize=8, weight="bold", ha="center", va="center",
        bbox={"boxstyle": "circle,pad=0.15", "facecolor": "yellow", "edgecolor": "none", "alpha": 0.85},
    )


def _salvar_recorte(
    dados: dict[str, Any], site_id: str, ano: int, candidatos_ano: list[dict[str, Any]], *, tipo: str
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
    ax.set_title(f"{site_id} — {ano} — {titulo}")
    ax.set_xlabel("X (EPSG:31983, m)")
    ax.set_ylabel("Y (EPSG:31983, m)")
    fig.tight_layout()

    out_dir = REPO_ROOT / "reports" / "figures" / "rotulagem" / site_id
    out_dir.mkdir(parents=True, exist_ok=True)
    sufixo = "rgb" if tipo == "rgb" else "falsacor"
    out_path = out_dir / f"{ano}_{sufixo}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def gerar_recortes_site(site_id: str, candidatos: list[dict[str, Any]]) -> list[Path]:
    """Um par de PNGs (RGB + falsa-cor) por ano disponível do site (união Landsat + Sentinel-2).

    Anos de sobreposição (2019-2021, presentes nos dois sensores) usam a imagem Sentinel-2 (10 m)
    como base visual — mesma extensão física da imagem Landsat (mesma origem de grade, ver
    `sentinela.gee.landsat`), só com mais detalhe. Candidatos detectados no par Landsat desse
    mesmo ano continuam desenhados por cima normalmente, porque a geometria já está em coordenadas
    reais (EPSG:31983), não em pixels.
    """
    anos_s2 = set(_anos_disponiveis("s2", site_id))
    anos_landsat = set(_anos_disponiveis("landsat", site_id))
    anos_todos = sorted(anos_s2 | anos_landsat)

    saidas: list[Path] = []
    for ano in anos_todos:
        sensor_base = "s2" if ano in anos_s2 else "landsat"
        dados = _ler_dados_ano(sensor_base, site_id, ano)
        if dados is None:
            print(
                f"AVISO: sem stack de features para {sensor_base}/{site_id}/{ano} — pulando recorte "
                f"desse ano (rode SV-08 antes).",
                file=sys.stderr,
            )
            continue
        candidatos_ano = [c for c in candidatos if c["ano"] == ano]
        saidas.append(_salvar_recorte(dados, site_id, ano, candidatos_ano, tipo="rgb"))
        saidas.append(_salvar_recorte(dados, site_id, ano, candidatos_ano, tipo="falsacor"))
    return saidas


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Kit de rotulagem manual (SV-09): candidatos a solo exposto/obras + recortes visuais."
    )
    parser.add_argument("--site", required=True, help="site_id de config/sites.geojson, ou 'all'")
    args = parser.parse_args(argv)

    sites = _sites_ativos() if args.site == "all" else [_validar_site(args.site)]

    for site_id in sites:
        candidatos, limiares = gerar_candidatos_site(site_id)
        geojson_path = _escrever_geojson(site_id, candidatos)
        png_paths = gerar_recortes_site(site_id, candidatos)

        print(f"\n[{site_id}] {len(candidatos)} candidatos -> {geojson_path}")
        for lim in limiares:
            print(
                f"  {lim['sensor']}/{lim['ano_anterior']}->{lim['ano']}: "
                f"BSI>=p{PCT_BSI_ALTO:.0f}={lim['bsi_alto_p85']}, "
                f"NDVI<=p{PCT_NDVI_BAIXO:.0f}={lim['ndvi_baixo_p25']}, "
                f"NDVI_anterior>=p{PCT_NDVI_ALTO_ANTERIOR:.0f}={lim['ndvi_alto_anterior_p55']} "
                f"-> {lim['n_pixels_candidatos']} px candidatos, {lim['n_poligonos_apos_filtro_area']} polígonos >= área mínima"
            )
        print(f"[{site_id}] {len(png_paths)} PNGs em reports/figures/rotulagem/{site_id}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
