"""Script ad-hoc (SV-15) — gera o Artefato 2 (GeoJSON) site a site, para poder rodar em lotes
síncronos curtos (evita o comando `export_indicadores` inteiro estourar o timeout de uma chamada
de shell e ser jogado para background).

NÃO toca no Artefato 1 (`outputs/indicadores/area_por_classe.csv`) — já regenerado, completo, pelo
`export_indicadores` (o CSV é escrito de uma vez só, antes do loop de GeoJSON, e por isso terminou
intacto mesmo quando o processo anterior foi morto no meio do loop de GeoJSON).

Uso:
    python scripts/sv15_gerar_geojson_por_site.py <site_id> [<site_id> ...]
    python scripts/sv15_gerar_geojson_por_site.py --merge   # combina os descartes parciais no CSV final

Cada chamada por site grava um log de descarte PARCIAL em
`data/manifests/_sv15_descarte_partial_{site_id}.json` (scratch, não é artefato do projeto).
`--merge` combina todos os parciais em `outputs/indicadores/geojson_poligonos_descartados.csv`
(o Artefato de descarte real) e apaga os parciais.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.export_indicadores import (
    OUTPUTS_DIR,
    DESCARTE_LOG_PATH,
    carregar_resolucoes,
    gerar_geojson_por_item,
    localizar_rasters,
)

MODELO_VERSAO = "rf_v1.0-tuned"
PARTIAL_DIR = SETTINGS.manifests_dir


def _partial_path(site_id: str) -> Path:
    return PARTIAL_DIR / f"_sv15_descarte_partial_{site_id}.json"


def gerar_site(site_id: str) -> None:
    resolucoes = carregar_resolucoes()
    itens = localizar_rasters(MODELO_VERSAO, site_filtro=site_id)
    print(f"[{site_id}] {len(itens)} itens (esperado 16).")
    todas_linhas_descarte = []
    for i, item in enumerate(itens, start=1):
        resolucao_m = resolucoes[item.sensor_token]
        out_path, linhas_descarte = gerar_geojson_por_item(item, resolucao_m, OUTPUTS_DIR)
        todas_linhas_descarte.extend(linhas_descarte)
        print(f"  [{i}/{len(itens)}] {out_path.name}")
    _partial_path(site_id).write_text(
        json.dumps(todas_linhas_descarte, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{site_id}] OK — {len(itens)} geojson gerados, {len(todas_linhas_descarte)} linha(s) de descarte.")


def merge() -> None:
    from sentinela import classes as classes_mod

    sites = [
        "angonap-fortaleza", "ascenty-hortolandia", "ascenty-jundiai", "ascenty-maracanau",
        "ascenty-osasco", "ascenty-paulinia", "ascenty-sumare", "ascenty-vinhedo",
        "clickip-manaus", "equinix-santana-parnaiba", "everest-goiania", "hostdime-joao-pessoa",
        "odata-hortolandia", "scala-sgigsm01", "scala-spoapa01", "scala-tambore",
    ]
    todas = []
    faltando = []
    for site_id in sites:
        p = _partial_path(site_id)
        if not p.exists():
            faltando.append(site_id)
            continue
        todas.extend(json.loads(p.read_text(encoding="utf-8")))
    if faltando:
        print(f"AVISO: parciais faltando para {faltando} — rode esses sites antes do merge.")
        sys.exit(1)

    if todas:
        df = pd.DataFrame(todas)
        df = df.sort_values(["site_id", "ano", "sensor", "classe_id"]).reset_index(drop=True)
    else:
        df = pd.DataFrame(
            columns=[
                "site_id", "ano", "sensor", "classe_id", "classe_nome",
                "n_poligonos_descartados", "area_descartada_m2", "area_descartada_ha",
            ]
        )
    df.to_csv(DESCARTE_LOG_PATH, index=False)
    print(f"MERGE OK — {DESCARTE_LOG_PATH} escrito com {len(df)} linhas.")

    for site_id in sites:
        p = _partial_path(site_id)
        if p.exists():
            p.unlink()
    print("Parciais removidos.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("uso: sv15_gerar_geojson_por_site.py <site_id> [...] | --merge")
        sys.exit(2)
    if args == ["--merge"]:
        merge()
    else:
        for s in args:
            gerar_site(s)
