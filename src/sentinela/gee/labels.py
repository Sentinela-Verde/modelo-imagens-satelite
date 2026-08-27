"""Geração dos rasters de label (SV-07) — implementa ADR-004 opção (b).

Rode com: python -m sentinela.gee.labels --site <site_id|all> --ano <ano|all> --sensor <s2|landsat|all>

**Fonte (ADR-004, opção b — não redecida aqui, só implementada):**
- **MapBiomas Coleção 9** (`config/params.yml`, seção `labels`) como label anual principal para
  2013-2023. A coleção não cobre 2024/2025 — esses dois anos replicam a banda `classification_2023`,
  com `distancia_safra` no manifest marcando a defasagem (0-2 anos, nunca os até 8 anos que uma
  safra fixa geraria numa série de 13 anos).
- **ESA WorldCover v200** como verificação cruzada só em 2021 (único ano de sobreposição real entre
  as duas fontes) — gera um raster `concordancia_{sensor}_{site_id}_{ano}.tif` (1 onde as duas
  fontes remapeadas concordam, 0 onde divergem ou onde uma delas não tem dado válido), que SV-11 usa
  para ponderar as amostras.

**Alinhamento de grade — a parte central desta tarefa:** cada raster de label é gerado por
site x ano x sensor, reprojetado (Earth Engine `ee.Image.reproject`, resampling nearest — nunca
`.resample()`, que trocaria o default) para o **exato** CRS/`transform`/`shape` do manifest de
imagem correspondente (`data/manifests/s2_{site}_{ano}.json` ou `landsat_{site}_{ano}.json`), nunca
recalculado aqui. Isso é o que garante que o label bata pixel a pixel com a imagem na hora de montar
o dataset de modelagem (SV-11).

O remap de códigos de origem para as 5 classes usa exclusivamente `sentinela.classes.remap()` —
este módulo nunca reescreve a tabela (`config/classes.yml`, seção `remaps`).

Saída: `data/raw/labels/{sensor}/{site_id}/{ano}.tif` (uint8, valores 0-5, nodata=0) +
`data/raw/labels/{sensor}/{site_id}/concordancia_{ano}.tif` (uint8, 0/1, só em 2021) +
`data/manifests/labels_{sensor}_{site_id}_{ano}.json` (commitado).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ee
import numpy as np
import rasterio
import requests

from .. import classes
from ..config import REPO_ROOT, SETTINGS, ConfigError
from .auth import init_ee

NODATA = 0
CRS_PADRAO = "EPSG:31983"  # todos os manifests de imagem (SV-06/SV-06b) já estão nessa projeção
_PREFIXO_MANIFEST = {"s2": "s2", "landsat": "landsat"}

_MAX_TENTATIVAS_REDE = 5
_ESPERA_INICIAL_S = 5.0


# --------------------------------------------------------------------------------------------
# Rede com backoff — mesma política das outras tarefas de ingestão (EE tem quota).
# --------------------------------------------------------------------------------------------


def _retry(fn, *, descricao: str, tentativas: int = _MAX_TENTATIVAS_REDE, espera_inicial: float = _ESPERA_INICIAL_S):
    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            return fn()
        except (ee.EEException, requests.RequestException) as e:
            ultimo_erro = e
            mensagem = str(e).lower()
            transiente = any(
                p in mensagem
                for p in ("quota", "rate limit", "429", "500", "503", "timeout", "temporarily", "too many requests")
            )
            if not transiente or tentativa == tentativas - 1:
                raise
            espera = espera_inicial * (2**tentativa)
            print(
                f"AVISO: {descricao} falhou ({e}); tentando de novo em {espera:.0f}s "
                f"({tentativa + 1}/{tentativas})...",
                file=sys.stderr,
            )
            time.sleep(espera)
    raise ultimo_erro  # pragma: no cover — inatingível (loop sempre retorna ou levanta acima)


# --------------------------------------------------------------------------------------------
# Config / sites (mesmo padrão de sentinela.gee.sentinel2 / landsat)
# --------------------------------------------------------------------------------------------


def _sites_ativos() -> list[dict]:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[gdf["ativo"] == True]
    return [
        {
            "site_id": r["site_id"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "buffer_km": float(r["buffer_km"]),
        }
        for _, r in gdf.iterrows()
    ]


def _site_por_id(site_id: str) -> dict:
    for s in _sites_ativos():
        if s["site_id"] == site_id:
            return s
    raise SystemExit(f"site_id '{site_id}' não encontrado (ou não ativo) em config/sites.geojson.")


def _config_labels() -> dict[str, Any]:
    params = SETTINGS.params()
    cfg = params.get("labels")
    if not cfg:
        raise ConfigError(
            "config/params.yml não tem a seção 'labels' (fonte de label, ADR-004). "
            "SV-07 depende dela — ver docs/decisoes/ADR-004-fonte-de-labels.md."
        )
    if cfg.get("forma_adr004") != "b":
        raise ConfigError(
            f"config/params.yml -> labels.forma_adr004 = '{cfg.get('forma_adr004')}', mas este "
            "módulo só implementa a forma (b) confirmada em ADR-004 (MapBiomas principal + "
            "WorldCover como verificação cruzada em 2021). Formas (a)/(c) não estão implementadas."
        )
    return cfg


# --------------------------------------------------------------------------------------------
# Manifests de imagem (SV-06/SV-06b) — grade a reproduzir, nunca recalculada aqui.
# --------------------------------------------------------------------------------------------


def _manifest_imagem_path(sensor: str, site_id: str, ano: int) -> Path:
    prefixo = _PREFIXO_MANIFEST[sensor]
    return SETTINGS.manifests_dir / f"{prefixo}_{site_id}_{ano}.json"


def _carregar_manifest_imagem(sensor: str, site_id: str, ano: int) -> dict | None:
    path = _manifest_imagem_path(sensor, site_id, ano)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _anos_disponiveis(sensor: str, site_id: str) -> list[int]:
    """Anos com manifest de imagem (SV-06/SV-06b) já gerado para este site/sensor."""
    prefixo = _PREFIXO_MANIFEST[sensor]
    anos: list[int] = []
    for p in SETTINGS.manifests_dir.glob(f"{prefixo}_{site_id}_*.json"):
        ano_str = p.stem.rsplit("_", 1)[-1]
        try:
            anos.append(int(ano_str))
        except ValueError:
            continue
    return sorted(anos)


# --------------------------------------------------------------------------------------------
# Ano efetivo do MapBiomas (replica 2023 em 2024/2025 — ver docstring do módulo).
# --------------------------------------------------------------------------------------------


def ano_mapbiomas_efetivo(ano: int, ano_max: int) -> tuple[int, int]:
    """Retorna (ano_efetivo_usado_na_coleção, distancia_safra). distancia_safra=0 se `ano<=ano_max`."""
    ano_efetivo = min(ano, ano_max)
    return ano_efetivo, ano - ano_efetivo


# --------------------------------------------------------------------------------------------
# Earth Engine: reprojeção + download de raster categórico (nearest, nunca bilinear).
# --------------------------------------------------------------------------------------------


def _grade_geometry(transform: list[float], width: int, height: int, crs: str) -> ee.Geometry:
    res_x, _, origin_x, _, res_y, origin_y = transform
    minx = origin_x
    maxy = origin_y
    maxx = minx + width * res_x
    miny = maxy + height * res_y  # res_y já é negativo
    return ee.Geometry.Rectangle([minx, miny, maxx, maxy], proj=crs, geodesic=False)


def _baixar_raster_categorico(
    imagem: ee.Image, transform: list[float], width: int, height: int, crs: str, aoi: ee.Geometry
) -> np.ndarray:
    """Reprojeta `imagem` (1 banda, código categórico) para a grade exata e baixa como uint8.

    `reproject` com `crs`/`crsTransform` explícitos usa o resampling default da imagem, que é
    nearest neighbor a menos que `.resample()` tenha sido chamado antes — nunca é aqui. Dado
    categórico não pode passar por bilinear (inventaria códigos de classe que não existem).
    """
    imagem_grade = imagem.reproject(crs=crs, crsTransform=transform).unmask(0).toUint8()

    def _url() -> str:
        return imagem_grade.getDownloadURL(
            {
                "crs": crs,
                "crsTransform": transform,
                "dimensions": f"{width}x{height}",
                "region": aoi,
                "format": "GEO_TIFF",
            }
        )

    url = _retry(_url, descricao="gerar URL de download de raster categórico")

    def _fetch() -> bytes:
        resp = requests.get(url, timeout=180)
        resp.raise_for_status()
        return resp.content

    conteudo = _retry(_fetch, descricao="baixar GeoTIFF de raster categórico")

    with rasterio.io.MemoryFile(conteudo) as memfile, memfile.open() as ds:
        arr = ds.read(1)
    return arr.astype(np.uint8)


def _imagem_mapbiomas(colecao: str, ano_efetivo: int) -> ee.Image:
    return ee.Image(colecao).select(f"classification_{ano_efetivo}").rename("codigo")


def _imagem_worldcover(colecao: str, aoi: ee.Geometry) -> ee.Image:
    return ee.ImageCollection(colecao).filterBounds(aoi).mosaic().select("Map").rename("codigo")


# --------------------------------------------------------------------------------------------
# Estatísticas de sanidade por classe
# --------------------------------------------------------------------------------------------


def distribuicao_classes(arr: np.ndarray) -> dict[str, dict[str, Any]]:
    total = int(arr.size)
    n_validos = int((arr != 0).sum())
    dist: dict[str, dict[str, Any]] = {}
    for class_id in sorted(classes.CLASSES):
        n = int((arr == class_id).sum())
        pct_validos = round(100.0 * n / n_validos, 4) if (class_id != 0 and n_validos) else None
        dist[str(class_id)] = {
            "slug": classes.ID_TO_SLUG[class_id],
            "n_pixels": n,
            "pct_total": round(100.0 * n / total, 4) if total else 0.0,
            "pct_validos": pct_validos,
        }
    return dist


# --------------------------------------------------------------------------------------------
# Escrita de raster
# --------------------------------------------------------------------------------------------


def _escrever_tif_uint8(path: Path, arr: np.ndarray, transform: list[float], crs: str, *, nodata: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "nodata": nodata,
        "width": arr.shape[1],
        "height": arr.shape[0],
        "count": 1,
        "crs": crs,
        "transform": rasterio.Affine(*transform),
        "compress": "deflate",
        "predictor": 2,
    }
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(arr, 1)
        ds.set_band_description(1, "classe")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - git ausente, repo raso, etc: manifest não pode falhar por isso
        return "desconhecido"


# --------------------------------------------------------------------------------------------
# PNG de conferência visual
# --------------------------------------------------------------------------------------------


def _salvar_png_label(arr_label: np.ndarray, site_id: str, sensor: str, ano: int) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cmap = classes.colormap()
    h, w = arr_label.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for class_id, cor in cmap.items():
        rgb[arr_label == class_id] = cor

    out_dir = REPO_ROOT / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"labels_{sensor}_{site_id}_{ano}.png"
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(rgb)
    ax.set_title(f"Label MapBiomas ({sensor}, {'{}m'.format(10 if sensor == 's2' else 30)}) — {site_id} — {ano}")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------------------------
# Orquestração por site/sensor/ano
# --------------------------------------------------------------------------------------------


def gerar_label_site_ano(
    site: dict, sensor: str, ano: int, *, force: bool = False, gerar_png: bool = False
) -> dict | None:
    site_id = site["site_id"]
    manifest_imagem = _carregar_manifest_imagem(sensor, site_id, ano)
    if manifest_imagem is None:
        print(
            f"AVISO: {site_id}/{sensor}/{ano}: sem manifest de imagem "
            f"({_manifest_imagem_path(sensor, site_id, ano)}) — pulando (rode SV-06/SV-06b antes).",
            file=sys.stderr,
        )
        return None

    tif_path = SETTINGS.raw_dir / "labels" / sensor / site_id / f"{ano}.tif"
    manifest_path = SETTINGS.manifests_dir / f"labels_{sensor}_{site_id}_{ano}.json"

    if not force and tif_path.exists() and manifest_path.exists():
        print(f"[{site_id}/{sensor}/{ano}] label já existe ({tif_path}) — pulando (use --force para regerar).")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    cfg = _config_labels()
    colecao_mb = cfg["colecao_mapbiomas"]
    ano_max = cfg["ano_mapbiomas_max"]
    ano_crosscheck = cfg["ano_crosscheck"]
    colecao_wc = cfg["colecao_worldcover"]

    crs = manifest_imagem["crs"]
    transform = manifest_imagem["transform"]
    width = manifest_imagem["shape"]["width"]
    height = manifest_imagem["shape"]["height"]
    resolucao_m = manifest_imagem["resolucao_m"]

    aoi = _grade_geometry(transform, width, height, crs)

    ano_efetivo, distancia_safra = ano_mapbiomas_efetivo(ano, ano_max)

    mb_img = _imagem_mapbiomas(colecao_mb, ano_efetivo)
    mb_raw = _baixar_raster_categorico(mb_img, transform, width, height, crs, aoi)
    mb_label = classes.remap(mb_raw, "mapbiomas").astype(np.uint8)

    crosscheck_info: dict[str, Any] | None = None
    concordancia_tif_path: Path | None = None

    if ano == ano_crosscheck:
        wc_img = _imagem_worldcover(colecao_wc, aoi)
        wc_raw = _baixar_raster_categorico(wc_img, transform, width, height, crs, aoi)
        wc_label = classes.remap(wc_raw, "worldcover").astype(np.uint8)

        valido = (mb_label != 0) & (wc_label != 0)
        concordancia = np.zeros_like(mb_label, dtype=np.uint8)
        concordancia[valido & (mb_label == wc_label)] = 1

        concordancia_tif_path = SETTINGS.raw_dir / "labels" / sensor / site_id / f"concordancia_{ano}.tif"
        _escrever_tif_uint8(concordancia_tif_path, concordancia, transform, crs, nodata=None)

        n_validos_ambas = int(valido.sum())
        crosscheck_info = {
            "ano": ano_crosscheck,
            "colecao_worldcover": colecao_wc,
            "n_pixels_validos_ambas_fontes": n_validos_ambas,
            "pct_concordancia_global": (
                round(100.0 * int(concordancia.sum()) / n_validos_ambas, 4) if n_validos_ambas else None
            ),
            "concordancia_tif": str(concordancia_tif_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        }

    _escrever_tif_uint8(tif_path, mb_label, transform, crs, nodata=NODATA)

    dist = distribuicao_classes(mb_label)
    sha256 = _sha256(tif_path)

    manifest = {
        "site_id": site_id,
        "ano": ano,
        "sensor": sensor,
        "fonte": "mapbiomas_principal" + ("+worldcover_crosscheck" if crosscheck_info else ""),
        "colecao": {"mapbiomas": colecao_mb, "worldcover": colecao_wc if crosscheck_info else None},
        "anual": True,
        "ano_mapbiomas_efetivo": ano_efetivo,
        "distancia_safra": distancia_safra,
        "remap_usado": ["mapbiomas"] + (["worldcover"] if crosscheck_info else []),
        "crs": crs,
        "transform": transform,
        "shape": {"width": width, "height": height},
        "resolucao_m": resolucao_m,
        "nodata": NODATA,
        "distribuicao_classes": dist,
        "crosscheck": crosscheck_info,
        "sha256": sha256,
        "git_sha": _git_sha(),
        "gerado_em": datetime.now(UTC).isoformat(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pct3 = dist["3"]["pct_validos"]
    print(
        f"[{site_id}/{sensor}/{ano}] OK — ano_efetivo={ano_efetivo} distancia_safra={distancia_safra} "
        f"-> {tif_path} (pct classe 3 = {pct3}%)"
    )
    if crosscheck_info:
        print(f"[{site_id}/{sensor}/{ano}] concordância WorldCover x MapBiomas = {crosscheck_info['pct_concordancia_global']}%")

    if gerar_png:
        png_path = _salvar_png_label(mb_label, site_id, sensor, ano)
        print(f"[{site_id}/{sensor}/{ano}] PNG de conferência: {png_path}")

    return manifest


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Geração dos rasters de label (SV-07, ADR-004 opção b).")
    parser.add_argument("--site", required=True, help="site_id de config/sites.geojson, ou 'all'")
    parser.add_argument("--ano", required=True, help="ano (ex.: 2021), ou 'all' (todos os anos com manifest de imagem)")
    parser.add_argument("--sensor", required=True, choices=["s2", "landsat", "all"], help="grade a usar")
    parser.add_argument("--force", action="store_true", help="regera mesmo se .tif/manifest já existirem")
    args = parser.parse_args(argv)

    try:
        init_ee()
    except ConfigError as e:
        print(f"ERRO DE CONFIGURAÇÃO:\n{e}", file=sys.stderr)
        return 1

    cfg = _config_labels()
    sites = _sites_ativos() if args.site == "all" else [_site_por_id(args.site)]
    sensores = ["s2", "landsat"] if args.sensor == "all" else [args.sensor]

    resultados: list[dict] = []
    houve_erro = False

    for site in sites:
        for sensor in sensores:
            anos_disponiveis = _anos_disponiveis(sensor, site["site_id"])
            if not anos_disponiveis:
                print(
                    f"AVISO: {site['site_id']}/{sensor}: nenhum manifest de imagem encontrado — "
                    f"rode sentinela.gee.{'sentinel2' if sensor == 's2' else 'landsat'} antes.",
                    file=sys.stderr,
                )
                continue

            if args.ano == "all":
                anos = anos_disponiveis
            else:
                ano_int = int(args.ano)
                if ano_int not in anos_disponiveis:
                    print(
                        f"AVISO: {site['site_id']}/{sensor}/{ano_int}: sem manifest de imagem "
                        f"correspondente (anos disponíveis: {anos_disponiveis}) — pulando.",
                        file=sys.stderr,
                    )
                    continue
                anos = [ano_int]

            # PNG de conferência: primeiro ano, último ano, e o ano de verificação cruzada (2021)
            # sempre que estiverem entre os anos processados desta rodada.
            anos_png = {anos_disponiveis[0], anos_disponiveis[-1]}
            if cfg["ano_crosscheck"] in anos_disponiveis:
                anos_png.add(cfg["ano_crosscheck"])

            for ano in anos:
                try:
                    manifest = gerar_label_site_ano(
                        site, sensor, ano, force=args.force, gerar_png=(ano in anos_png)
                    )
                    if manifest is not None:
                        resultados.append(manifest)
                except Exception as e:  # noqa: BLE001 - um site/sensor/ano falhar não derruba o lote
                    houve_erro = True
                    print(f"ERRO ao processar {site['site_id']}/{sensor}/{ano}: {e}", file=sys.stderr)

    print()
    print("site | sensor | ano | classe 1 | classe 2 | classe 3 | classe 4 | classe 5 (% válidos)")
    print("-----|--------|-----|----------|----------|----------|----------|----------")
    for m in resultados:
        d = m["distribuicao_classes"]
        print(
            f"{m['site_id']} | {m['sensor']} | {m['ano']} | "
            f"{d['1']['pct_validos']} | {d['2']['pct_validos']} | {d['3']['pct_validos']} | "
            f"{d['4']['pct_validos']} | {d['5']['pct_validos']}"
        )

    # Variação 2013 -> 2025 por site (sinal de mudança de uso; ver ADR-004 seção 5 e critério de
    # aceite de SV-07 — se não mudar nada, é sinal de que 2023 foi replicado por engano em algum
    # lugar que não deveria).
    print()
    print("Variação da distribuição de classes 2013 (landsat) -> 2025 (s2, réplica de 2023):")
    by_site: dict[str, dict[int, dict]] = {}
    for m in resultados:
        by_site.setdefault(m["site_id"], {})[m["ano"]] = m
    for site_id, por_ano in by_site.items():
        if 2013 in por_ano and 2025 in por_ano:
            d13 = por_ano[2013]["distribuicao_classes"]
            d25 = por_ano[2025]["distribuicao_classes"]
            deltas = []
            for cid in range(1, 6):
                p13 = d13[str(cid)]["pct_validos"] or 0.0
                p25 = d25[str(cid)]["pct_validos"] or 0.0
                deltas.append(f"classe {cid}: {p13:.2f}% -> {p25:.2f}% (delta {p25 - p13:+.2f}pp)")
            print(f"  {site_id}: " + " | ".join(deltas))

    return 1 if houve_erro else 0


if __name__ == "__main__":
    sys.exit(main())
