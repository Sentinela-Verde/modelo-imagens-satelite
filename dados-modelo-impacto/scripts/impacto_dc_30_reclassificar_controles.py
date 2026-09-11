"""Passo 30 — reclassifica os controles com um modelo candidato, para o portão §4.

Rode com:

    SENTINELA_MODELO_IMPACTO=rf_v2.0-dw \
      python dados-modelo-impacto/scripts/impacto_dc_30_reclassificar_controles.py --fase rodar

## Por que este passo existe

O critério §4 do ADR-006 — o único que decide se um classificador retreinado substitui o
atual — é a **instabilidade temporal nos controles**. Medi-la para um modelo novo exige os
rasters classificados por esse modelo, e eles não existem: os controles são classificados
uma vez e seus intermediários são **descartados de propósito** (`descartar_apos=True` em
`rodar_ponto`), porque guardar imagem bruta de 15 controles x 7 anos x 2 sensores encheria
o disco sem servir a nada depois.

A consequência é que reclassificar um controle custa reingerir a imagem do Earth Engine.
Este passo faz isso, e escreve num diretório próprio do modelo
(`classificado-<versao>`), nunca por cima do de produção: enquanto o retreino não passar
no §4, `rf_v1.0-tuned` continua sendo o modelo de produção e seus rasters precisam
continuar válidos.

## Quais controles

Só os que o Dynamic World cobre — a série dele começa em jun/2015, e o §4 compara os dois
instrumentos **sobre os mesmos pixels e os mesmos anos**. Medir o modelo novo num conjunto
maior que o do DW e comparar os agregados seria comparar dois conjuntos, não dois modelos
(é o defeito que o passo 29 corrigiu na primeira rodada).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

DIR_DW = C.DIR_SAIDA / "dynamic_world"


def controles_do_criterio() -> list[dict]:
    """Controles com raster do DW em disco — o conjunto em que o §4 é comparável."""
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")]

    alvos = []
    for _, r in par.iterrows():
        ctrl = r.site_id_controle
        anos_dw = sorted(int(p.stem) for p in (DIR_DW / ctrl).glob("*.tif")) \
            if (DIR_DW / ctrl).is_dir() else []
        if len(anos_dw) < 2:
            continue
        alvos.append({
            "site_id": ctrl,
            "lat": float(r.lat_controle),
            "lon": float(r.lon_controle),
            "buffer_km": C.BUFFER_KM,
            "sensor": r.sensor,
            "anos": anos_dw,
        })
    return alvos


def fase_rodar() -> None:
    if os.environ.get("SENTINELA_MODELO_IMPACTO") is None:
        print(
            "AVISO: SENTINELA_MODELO_IMPACTO não definido — isto vai reclassificar com o modelo\n"
            "de PRODUÇÃO e escrever por cima dos rasters que a cadeia de impacto usa.\n"
            "Defina a variável (ex.: rf_v2.0-dw) antes de rodar.",
            file=sys.stderr,
        )
        sys.exit(2)

    alvos = controles_do_criterio()
    print(f"modelo: {C.MODELO_VERSAO}")
    print(f"saída : {C.DIR_CLASSIFICADO_CONTROLES.relative_to(C.REPO_ROOT)}")
    print(f"{len(alvos)} controles, {sum(len(a['anos']) for a in alvos)} ponto-ano\n")

    if not C.MODELO_PATH.exists():
        sys.exit(f"modelo não encontrado: {C.MODELO_PATH}")

    C.iniciar_ee()  # a reingestão vai ao Earth Engine; sem isto todo ponto falha igual

    pacote = C.carregar_modelo() if hasattr(C, "carregar_modelo") else None
    if pacote is None:
        import joblib
        pacote = joblib.load(C.MODELO_PATH)

    feitos = falhas = 0
    for alvo in alvos:
        ponto = {k: alvo[k] for k in ("site_id", "lat", "lon", "buffer_km")}
        for ano in alvo["anos"]:
            try:
                C.rodar_ponto(ponto, ano, alvo["sensor"], pacote, descartar_apos=True)
                feitos += 1
                print(f"  OK {alvo['site_id']}/{ano}")
            except Exception as e:  # noqa: BLE001 — um ponto que falha não pode parar o lote
                falhas += 1
                print(f"  FALHOU {alvo['site_id']}/{ano}: {type(e).__name__}: {e}",
                      file=sys.stderr)

    print(f"\n{feitos} ponto-ano classificados, {falhas} falhas")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("rodar",), required=True)
    ap.parse_args()
    fase_rodar()


if __name__ == "__main__":
    main()
