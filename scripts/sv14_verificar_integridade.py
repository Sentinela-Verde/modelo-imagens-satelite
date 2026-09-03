"""Verificação ad-hoc pós-incidente: um processo de predict antigo (rodando em background, com
--force) ficou ativo em paralelo com uma segunda rodada em foreground (mesmo comando, sem --force)
por um tempo — os dois podiam, em teoria, ter escrito no mesmo .tif ao mesmo tempo para os mesmos
site/ano/sensor, arriscando corromper o arquivo (rasterio.open(..., "w") trunca o arquivo ao abrir).

Este script relê TODOS os rasters classificados referenciados pelos manifests
`classificado_{sensor}_{site}_{ano}.json`, recalcula o sha256 dos pixels e compara com o valor
gravado no manifest — não confia em "arquivo existe" como prova de integridade."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import rasterio

from sentinela.config import REPO_ROOT, SETTINGS


def main() -> int:
    manifests = sorted(SETTINGS.manifests_dir.glob("classificado_*.json"))
    print(f"{len(manifests)} manifests encontrados.")
    ok = 0
    problemas = []
    for mp in manifests:
        m = json.loads(mp.read_text(encoding="utf-8"))
        tif_path = REPO_ROOT / m["tif"]
        if not tif_path.exists():
            problemas.append((mp.name, "tif ausente"))
            continue
        try:
            with rasterio.open(tif_path) as ds:
                arr = ds.read(1)
                shape_ok = (ds.width == m["shape"]["width"] and ds.height == m["shape"]["height"])
        except Exception as e:  # noqa: BLE001
            problemas.append((mp.name, f"erro ao abrir/ler: {type(e).__name__}: {e}"))
            continue
        if not shape_ok:
            problemas.append((mp.name, f"shape divergente: tif=({ds.width}x{ds.height}) manifest=({m['shape']['width']}x{m['shape']['height']})"))
            continue
        sha_recalculado = hashlib.sha256(arr.tobytes()).hexdigest()
        if sha_recalculado != m["sha256"]:
            problemas.append((mp.name, f"sha256 divergente: manifest={m['sha256'][:16]}... recalculado={sha_recalculado[:16]}..."))
            continue
        if m.get("modelo_versao") != "rf_v1.0-tuned":
            problemas.append((mp.name, f"modelo_versao inesperado: {m.get('modelo_versao')}"))
            continue
        ok += 1

    print(f"\nOK: {ok}/{len(manifests)}")
    if problemas:
        print(f"\nPROBLEMAS ({len(problemas)}):")
        for nome, msg in problemas:
            print(f"  {nome}: {msg}")
        return 1
    print("Nenhum problema — todos os rasters íntegros e com modelo_versao=rf_v1.0-tuned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
