"""SV-25 — gera reports/figures/coordenadas/{aoi_id}.png para a fila de conferência visual (nível D).

Cada imagem tem 2 painéis lado a lado, compostos com o Sentinel-2 mais recente disponível
(mediana da coleção COPERNICUS/S2_SR_HARMONIZED, jan-dez do ano mais recente com cobertura,
bandas RGB naturais B4/B3/B2 — mesma receita de src/sentinela/gee/check.py):

  - esquerda: recorte ~2x2 km centrado no ponto candidato, com marcador no ponto — para checar
    visualmente se a coordenada cai sobre uma instalação real (prédio(s), pátio, subestação),
    não sobre vegetação/água/vizinho.
  - direita: recorte mais amplo (bounding box do buffer geodésico de 5 km em volta do ponto),
    com o buffer de 5 km desenhado (círculo tracejado) — contexto espacial / checagem de colisão
    com outra AOI (V4).

Rodar: `.venv\\Scripts\\python.exe scripts\\gerar_imagens_fila_visual.py`
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ee
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
import truststore
from matplotlib.patches import Circle
from PIL import Image

truststore.inject_into_ssl()

from sentinela.gee.auth import init_ee

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "reports" / "figures" / "coordenadas"

# AOIs da fila visual (nível D) — ver docs/fila-conferencia-coordenadas.md para o motivo de cada uma.
FILA = {
    "ascenty-sumare": (-22.8069862, -47.2200481),
    "ascenty-paulinia": (-22.7974087, -47.1345476),
    "everest-goiania": (-16.6915189, -49.2371899),
}

ANOS_TENTATIVA = [2025, 2024, 2023]  # do mais recente para trás, primeiro ano com imagens suficientes


def _composto_mais_recente(pt: ee.Geometry, region: ee.Geometry) -> tuple[ee.Image, int]:
    for ano in ANOS_TENTATIVA:
        colecao = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region)
            .filterDate(f"{ano}-01-01", f"{ano}-12-31")
        )
        n = colecao.size().getInfo()
        if n >= 3:
            return colecao.median().select(["B4", "B3", "B2"]), ano
    # fallback: usa o que tiver, mesmo com poucas imagens
    colecao = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region).filterDate(
        f"{ANOS_TENTATIVA[-1]}-01-01", "2025-12-31"
    )
    return colecao.median().select(["B4", "B3", "B2"]), ANOS_TENTATIVA[-1]


def _baixar_thumb(composto: ee.Image, region: ee.Geometry, dim: int = 512) -> Image.Image:
    url = composto.getThumbURL({"region": region, "dimensions": dim, "min": 0, "max": 3000, "format": "png"})
    resp = requests.get(url, timeout=90)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def gerar(aoi_id: str, lat: float, lon: float) -> Path:
    pt = ee.Geometry.Point([lon, lat])
    region_zoom = pt.buffer(1000).bounds()  # ~2x2 km
    region_wide = pt.buffer(5000).bounds()  # bounding box do buffer de 5 km (ADR-001)

    composto_zoom, ano_zoom = _composto_mais_recente(pt, region_zoom)
    composto_wide, ano_wide = _composto_mais_recente(pt, region_wide)

    img_zoom = _baixar_thumb(composto_zoom, region_zoom, dim=512)
    img_wide = _baixar_thumb(composto_wide, region_wide, dim=512)

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))

    ax = axes[0]
    ax.imshow(img_zoom)
    cx, cy = img_zoom.width / 2, img_zoom.height / 2
    ax.plot(cx, cy, marker="+", markersize=28, markeredgewidth=2.5, color="red")
    ax.plot(cx, cy, marker="o", markersize=14, markerfacecolor="none", markeredgewidth=2, color="red")
    ax.set_title(f"Zoom ~2x2 km (S2 {ano_zoom})\nlat={lat:.6f}, lon={lon:.6f}")
    ax.axis("off")

    ax = axes[1]
    ax.imshow(img_wide)
    cx, cy = img_wide.width / 2, img_wide.height / 2
    ax.plot(cx, cy, marker="+", markersize=20, markeredgewidth=2, color="red")
    raio_px = min(img_wide.width, img_wide.height) / 2
    circ = Circle((cx, cy), raio_px, fill=False, edgecolor="yellow", linestyle="--", linewidth=2)
    ax.add_patch(circ)
    ax.set_title(f"Contexto — buffer 5 km (S2 {ano_wide})")
    ax.axis("off")

    fig.suptitle(f"{aoi_id} — fila de conferência visual (nível D, SV-25)", fontsize=12)
    fig.tight_layout()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{aoi_id}.png"
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def main() -> None:
    init_ee()
    for aoi_id, (lat, lon) in FILA.items():
        path = gerar(aoi_id, lat, lon)
        print(f"{aoi_id}: {path}")


if __name__ == "__main__":
    main()
