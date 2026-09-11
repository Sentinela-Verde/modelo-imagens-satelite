"""Script ad-hoc — sequência multi-ano de `ascenty-hortolandia` (obra bem documentada:
ano_inicio_obra=2018, periodo_pre=2015-2017, periodo_durante=2018-2022, periodo_pos=2023-2025,
ver config/sites.geojson). NÃO reclassifica nada — só lê os rasters classificados já prontos em
`data/processed/classificado/{sensor}/ascenty-hortolandia/{ano}.tif` e gera PNGs, reaproveitando
`gerar_png_conferencia`/`gerar_png_comparacao` de `sentinela.predict` (mesma função usada em
SV-14, não reimplementada aqui).

Gera:
  - reports/figures/evolucao_ascenty-hortolandia_{ano}.png para cada ano da sequência (5 anos:
    2016, 2018, 2020, 2022, 2024 — antes / obra começando / em andamento / terminando / depois).
    Cada um é o PNG de conferência padrão (`mapa_{sensor}_{site}_{ano}.png`) gerado por
    `gerar_png_conferencia` e copiado para o nome com o padrão `evolucao_*` (conteúdo idêntico,
    só renomeado — não reescreve a lógica de desenho).
  - reports/figures/evolucao_ascenty-hortolandia_painel.png: os 5 anos lado a lado numa figura só,
    via `gerar_png_comparacao` (legenda de classe uma vez só, ano em destaque por painel).
"""

from __future__ import annotations

import shutil

import rasterio

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.predict import gerar_png_comparacao, gerar_png_conferencia

SITE_ID = "ascenty-hortolandia"
SEQUENCIA = [
    ("landsat", 2016),  # antes da obra (periodo_pre 2015-2017)
    ("landsat", 2018),  # obra começando (ano_inicio_obra)
    ("s2", 2020),        # obra em andamento (periodo_durante 2018-2022)
    ("s2", 2022),        # obra terminando (fim de periodo_durante)
    ("s2", 2024),        # depois (periodo_pos 2023-2025)
]

FIGURES_DIR = REPO_ROOT / "reports" / "figures"


def _ler_classe(sensor_token: str, ano: int):
    path = SETTINGS.processed_dir / "classificado" / sensor_token / SITE_ID / f"{ano}.tif"
    if not path.exists():
        raise FileNotFoundError(f"{path} não existe — esperado para a sequência de evolução.")
    with rasterio.open(path) as ds:
        return ds.read(1)


def main() -> None:
    pares = []
    gerados = []
    for sensor_token, ano in SEQUENCIA:
        arr = _ler_classe(sensor_token, ano)
        pares.append((sensor_token, ano, arr))

        # Reaproveita a função existente (SV-14) — gera mapa_{sensor}_{site}_{ano}.png.
        mapa_path = gerar_png_conferencia(sensor_token, SITE_ID, ano, arr)

        # Copia para o nome do padrão "evolucao_*" pedido (mesmo conteúdo, sem redesenhar).
        destino = FIGURES_DIR / f"evolucao_{SITE_ID}_{ano}.png"
        shutil.copyfile(mapa_path, destino)
        gerados.append(str(destino))
        print(f"[{sensor_token}/{ano}] {mapa_path.name} -> {destino.name}")

    painel_path = FIGURES_DIR / f"evolucao_{SITE_ID}_painel.png"
    gerar_png_comparacao(SITE_ID, pares, painel_path)
    gerados.append(str(painel_path))
    print(f"[painel] {len(pares)} anos -> {painel_path}")

    print(f"\nTotal PNGs gerados/renomeados: {len(gerados)}")
    for g in gerados:
        print(f"  {g}")


if __name__ == "__main__":
    main()
