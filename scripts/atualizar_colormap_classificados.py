"""Script ad-hoc — reescreve só o colormap embutido nos GeoTIFFs classificados já existentes em
`data/processed/classificado/{sensor}/{site}/{ano}.tif`, depois da troca de cor da classe 3
(`config/classes.yml`, #C87137 -> #F5A623, 2026-09-05).

NÃO reclassifica nada: os valores de pixel (classes 0-5) não são tocados, só a paleta de cores
(metadado do GeoTIFF). Abre cada raster em modo 'r+' e chama `write_colormap` de novo com o
colormap atual de `sentinela.classes.colormap()` (que já lê do YAML — fonte única de verdade).

Roda de forma síncrona/bloqueante (sem subprocesso em paralelo) para não arriscar duas escritas
concorrentes no mesmo arquivo.
"""

from __future__ import annotations

from pathlib import Path

import rasterio

from sentinela import classes
from sentinela.config import REPO_ROOT, SETTINGS


def main() -> None:
    colormap = classes.colormap()
    base_dir = SETTINGS.processed_dir / "classificado"

    tifs = sorted(
        p for p in base_dir.rglob("*.tif") if not p.stem.endswith("_confianca")
    )
    print(f"{len(tifs)} GeoTIFFs classificados encontrados em {base_dir}")

    atualizados = []
    erros = []
    for tif_path in tifs:
        try:
            with rasterio.open(tif_path, "r+") as ds:
                ds.write_colormap(1, colormap)
            atualizados.append(tif_path)
        except Exception as exc:  # noqa: BLE001
            erros.append((tif_path, str(exc)))

    print(f"Colormap atualizado em {len(atualizados)} arquivos.")
    if erros:
        print(f"ERROS em {len(erros)} arquivos:")
        for p, e in erros:
            print(f"  {p}: {e}")

    # Checagem rápida: reabre um arquivo qualquer e confere que a cor da classe 3 bate com o YAML.
    if atualizados:
        amostra = atualizados[0]
        with rasterio.open(amostra) as ds:
            cm = ds.colormap(1)
            cor3 = cm[3][:3]
            esperado = colormap[3]
            status = "OK" if cor3 == esperado else "DIVERGENTE"
            print(f"Checagem ({amostra.relative_to(REPO_ROOT)}): classe 3 = {cor3} (esperado {esperado}) -> {status}")


if __name__ == "__main__":
    main()
