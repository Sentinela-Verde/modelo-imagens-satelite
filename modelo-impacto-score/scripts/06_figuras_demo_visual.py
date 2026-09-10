"""Gera as figuras visuais da demo do classificador — imagem de satélite ao lado do que o modelo vê.

    python modelo-impacto-score/scripts/06_figuras_demo_visual.py

Nenhuma dessas figuras existe ainda: as do repositório são de conferência técnica (mapas soltos)
ou de resultado estatístico (barras e dispersões). Estas são para **mostrar o modelo funcionando** —
a imagem crua, a mesma cena em falsa-cor, e a classificação lado a lado, no mesmo recorte.

Lê os rasters já em disco (`data/raw/`, `data/interim/features/`, `data/processed/classificado/`)
e não chama o Earth Engine nem reclassifica nada.

Saídas em `modelo-impacto-score/reports/figuras/demo/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import yaml
from matplotlib.colors import ListedColormap

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "dados-modelo-impacto" / "scripts"))
DESTINO = RAIZ / "modelo-impacto-score" / "reports" / "figuras" / "demo"

FATOR = 10000.0
NODATA = -9999


def paleta() -> tuple[ListedColormap, dict[int, str], dict[int, str]]:
    cfg = yaml.safe_load((RAIZ / "config" / "classes.yml").read_text(encoding="utf-8"))
    classes = cfg["classes"] if "classes" in cfg else cfg
    cores, nomes = {}, {}
    for cid, meta in classes.items():
        if not isinstance(meta, dict):
            continue
        cores[int(cid)] = meta.get("cor_hex", "#888888")
        nomes[int(cid)] = meta.get("nome_exibicao", meta.get("slug", str(cid)))
    lista = [cores.get(i, "#000000") for i in range(max(cores) + 1)]
    return ListedColormap(lista), cores, nomes


def _ler(path: Path) -> np.ndarray | None:
    if not path.exists():
        return None
    with rasterio.open(path) as src:
        return src.read()


def composicao(arr: np.ndarray, bandas: tuple[int, int, int], pct: float = 2.0) -> np.ndarray:
    """Recorte RGB com esticamento por percentil — o mesmo que qualquer SIG faz para exibir."""
    saida = np.zeros((*arr.shape[1:], 3), dtype=float)
    for i, b in enumerate(bandas):
        c = arr[b].astype(float)
        c[c <= NODATA + 1] = np.nan
        c = c / FATOR
        lo, hi = np.nanpercentile(c, [pct, 100 - pct])
        saida[..., i] = np.clip((c - lo) / (hi - lo + 1e-9), 0, 1)
    return np.nan_to_num(saida)


def caminho_raw(sensor: str, site: str, ano: int) -> Path:
    sub = "landsat" if sensor == "landsat" else "s2"
    return RAIZ / "data" / "raw" / sub / site / f"{ano}.tif"


def caminho_class(sensor: str, site: str, ano: int) -> Path:
    return RAIZ / "data" / "processed" / "classificado" / sensor / site / f"{ano}.tif"


def fig_lado_a_lado(site: str, sensor: str, ano: int, cmap, nomes, cores) -> Path | None:
    raw = _ler(caminho_raw(sensor, site, ano))
    cls = _ler(caminho_class(sensor, site, ano))
    if raw is None or cls is None:
        print(f"  ! {site}/{ano}: faltam rasters, pulando")
        return None
    cls = cls[0]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.4))
    axes[0].imshow(composicao(raw, (2, 1, 0)))
    axes[0].set_title("1. Cor verdadeira\ncomo o olho veria do espaço", fontsize=10)
    axes[1].imshow(composicao(raw, (3, 2, 1)))
    axes[1].set_title("2. Falsa-cor (infravermelho)\nvegetação vira vermelho vivo", fontsize=10)
    axes[2].imshow(np.ma.masked_where(cls == 0, cls), cmap=cmap, vmin=0, vmax=len(cmap.colors) - 1,
                   interpolation="nearest")
    axes[2].set_title("3. O que o modelo vê\ncada pixel em uma das 5 classes", fontsize=10)
    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])

    handles = [mpatches.Patch(color=cores[c], label=nomes[c]) for c in sorted(nomes) if c > 0]
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False, fontsize=9,
               bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(f"{site} · {ano} · {sensor.upper()} — buffer de 5 km", fontsize=13, y=1.06)
    fig.tight_layout(rect=(0, 0.06, 1, 0.97))
    saida = DESTINO / f"demo_lado_a_lado_{site}_{ano}.png"
    fig.savefig(saida, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {saida.name}")
    return saida


def fig_serie(site: str, sensor: str, anos: list[int], cmap, nomes, cores) -> Path | None:
    disp = [a for a in anos if caminho_class(sensor, site, a).exists()]
    if len(disp) < 3:
        print(f"  ! {site}: série curta demais")
        return None
    fig, axes = plt.subplots(1, len(disp), figsize=(3.1 * len(disp), 3.9))
    for ax, ano in zip(np.atleast_1d(axes), disp):
        cls = _ler(caminho_class(sensor, site, ano))[0]
        ax.imshow(np.ma.masked_where(cls == 0, cls), cmap=cmap, vmin=0,
                  vmax=len(cmap.colors) - 1, interpolation="nearest")
        ax.set_title(str(ano), fontsize=11)
        ax.set_xticks([]); ax.set_yticks([])
    handles = [mpatches.Patch(color=cores[c], label=nomes[c]) for c in sorted(nomes) if c > 0]
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False, fontsize=9)
    fig.suptitle(f"{site} — a mesma área, ano a ano, classificada pelo modelo", fontsize=12)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    saida = DESTINO / f"demo_serie_{site}.png"
    fig.savefig(saida, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {saida.name}")
    return saida


def fig_confianca(site: str, sensor: str, ano: int, cmap, nomes, cores) -> Path | None:
    cls = _ler(caminho_class(sensor, site, ano))
    conf = _ler(RAIZ / "data" / "processed" / "classificado" / sensor / site / f"{ano}_confianca.tif")
    if cls is None or conf is None:
        print(f"  ! {site}/{ano}: sem raster de confiança")
        return None
    cls, conf = cls[0], conf[0].astype(float)
    conf[cls == 0] = np.nan

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    axes[0].imshow(np.ma.masked_where(cls == 0, cls), cmap=cmap, vmin=0,
                   vmax=len(cmap.colors) - 1, interpolation="nearest")
    axes[0].set_title("classificação", fontsize=10)
    im = axes[1].imshow(conf, cmap="RdYlGn", vmin=np.nanpercentile(conf, 2),
                        vmax=np.nanpercentile(conf, 98), interpolation="nearest")
    axes[1].set_title("confiança do modelo\nvermelho = o modelo está em dúvida", fontsize=10)
    fig.colorbar(im, ax=axes[1], fraction=0.046)
    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(f"{site} · {ano} — onde o modelo tem certeza, e onde não tem", fontsize=12)
    fig.tight_layout()
    saida = DESTINO / f"demo_confianca_{site}_{ano}.png"
    fig.savefig(saida, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {saida.name}")
    return saida


def fig_aneis(site: str, sensor: str, ano: int, cmap, nomes, cores) -> Path | None:
    """A classificação com os anéis de medição desenhados — onde o impacto é medido."""
    import impacto_dc_comum as C
    import impacto_dc_11_sensibilidade_buffer as P11

    p = caminho_class(sensor, site, ano)
    if not p.exists():
        return None
    sites = C.carregar_sites_validados()
    if site not in sites:
        return None
    lat, lon = sites[site]["lat"], sites[site]["lon"]
    cls = _ler(p)[0]
    raios = P11.mascaras_por_raio(p, lat, lon)

    fig, ax = plt.subplots(figsize=(7.5, 7))
    ax.imshow(np.ma.masked_where(cls == 0, cls), cmap=cmap, vmin=0,
              vmax=len(cmap.colors) - 1, interpolation="nearest")
    for raio, cor in ((0.5, "#FFFFFF"), (1.0, "#FFD54F"), (2.0, "#4FC3F7")):
        ax.contour(raios[raio].astype(float), levels=[0.5], colors=[cor], linewidths=2.0)
    ax.set_xticks([]); ax.set_yticks([])
    handles = [mpatches.Patch(color=cores[c], label=nomes[c]) for c in sorted(nomes) if c > 0]
    handles += [plt.Line2D([], [], color=c, lw=2, label=f"anel {r} km")
                for r, c in ((0.5, "#FFFFFF"), (1.0, "#FFD54F"), (2.0, "#4FC3F7"))]
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.85)
    ax.set_title(f"{site} · {ano}\nonde o impacto é medido — o efeito vive no anel de 500 m\n"
                 "e desaparece depois de 2 km", fontsize=11)
    fig.tight_layout()
    saida = DESTINO / f"demo_aneis_{site}_{ano}.png"
    fig.savefig(saida, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {saida.name}")
    return saida


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    cmap, cores, nomes = paleta()
    print(f"paleta: {len(nomes) - 1} classes")

    # Vinhedo: série Landsat mais longa que temos (2013-2021), obra em 2019
    fig_lado_a_lado("ascenty-vinhedo", "landsat", 2013, cmap, nomes, cores)
    fig_lado_a_lado("ascenty-vinhedo", "landsat", 2021, cmap, nomes, cores)
    fig_serie("ascenty-vinhedo", "landsat", [2013, 2015, 2017, 2019, 2021], cmap, nomes, cores)
    fig_confianca("ascenty-vinhedo", "landsat", 2021, cmap, nomes, cores)
    fig_aneis("ascenty-vinhedo", "landsat", 2021, cmap, nomes, cores)

    # Manaus: o caso mais dramático — 0% do footprint era construído antes, 75% virou
    # Manaus: unico campus com 0% do footprint construido antes da obra -- 75% virou.
    # Usa a serie Landsat (2013-2021), que e a que tem raster bruto em disco.
    fig_lado_a_lado("clickip-manaus", "landsat", 2013, cmap, nomes, cores)
    fig_lado_a_lado("clickip-manaus", "landsat", 2021, cmap, nomes, cores)
    fig_serie("clickip-manaus", "landsat", [2013, 2015, 2017, 2019, 2021],
              cmap, nomes, cores)
    fig_aneis("clickip-manaus", "landsat", 2021, cmap, nomes, cores)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
