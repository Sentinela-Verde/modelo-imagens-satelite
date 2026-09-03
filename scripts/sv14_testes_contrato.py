"""Script ad-hoc (SV-14) — testes de contrato de features: banda embaralhada e banda faltando.

Não é parte do CLI de produção; roda uma vez para gerar evidência para o relatório de SV-14.
Cria cópias temporárias do stack de features de ascenty-vinhedo/s2/2025 com (a) bandas em ordem
embaralhada e (b) uma banda removida, e chama `sentinela.predict.classificar_site_ano` sobre elas
como se fossem um site fictício `_teste_contrato`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import joblib
import numpy as np
import rasterio

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.predict import PredictError, classificar_site_ano

MODELO_PATH = REPO_ROOT / "models" / "rf_v1.0-tuned.joblib"
ORIG_TIF = SETTINGS.interim_dir / "features" / "s2" / "ascenty-vinhedo" / "2025.tif"
ORIG_MANIFEST = SETTINGS.manifests_dir / "features_s2_ascenty-vinhedo_2025.json"

SITE_EMBARALHADO = "_teste_contrato_embaralhado"
SITE_FALTANDO = "_teste_contrato_faltando"


def _limpar(site_id: str) -> None:
    for base in (SETTINGS.interim_dir / "features" / "s2", SETTINGS.manifests_dir, SETTINGS.processed_dir / "classificado" / "s2"):
        alvo = base / site_id if base.name != "manifests" else None
        if alvo and alvo.exists():
            shutil.rmtree(alvo)
    for p in SETTINGS.manifests_dir.glob(f"features_s2_{site_id}_*.json"):
        p.unlink()
    for p in SETTINGS.manifests_dir.glob(f"classificado_s2_{site_id}_*.json"):
        p.unlink()


def _preparar_embaralhado() -> None:
    manifest = json.loads(ORIG_MANIFEST.read_text(encoding="utf-8"))
    bandas_orig = manifest["bandas"]
    rng = np.random.RandomState(7)
    ordem = list(range(len(bandas_orig)))
    rng.shuffle(ordem)
    bandas_embaralhadas = [bandas_orig[i] for i in ordem]
    assert bandas_embaralhadas != bandas_orig, "shuffle não mudou a ordem — RNG ruim"

    with rasterio.open(ORIG_TIF) as src:
        arr = src.read()
        profile = src.profile

    arr_embaralhado = arr[ordem]

    out_dir = SETTINGS.interim_dir / "features" / "s2" / SITE_EMBARALHADO
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tif = out_dir / "2025.tif"
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(arr_embaralhado)
        dst.descriptions = tuple(bandas_embaralhadas)

    manifest_novo = dict(manifest)
    manifest_novo["bandas"] = bandas_embaralhadas
    manifest_novo["site_id"] = SITE_EMBARALHADO
    (SETTINGS.manifests_dir / f"features_s2_{SITE_EMBARALHADO}_2025.json").write_text(
        json.dumps(manifest_novo, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[embaralhado] bandas originais: {bandas_orig}")
    print(f"[embaralhado] bandas embaralhadas: {bandas_embaralhadas}")


def _preparar_faltando(banda_removida: str = "bsi") -> None:
    manifest = json.loads(ORIG_MANIFEST.read_text(encoding="utf-8"))
    bandas_orig = manifest["bandas"]
    idx_manter = [i for i, b in enumerate(bandas_orig) if b != banda_removida]
    bandas_restantes = [bandas_orig[i] for i in idx_manter]

    with rasterio.open(ORIG_TIF) as src:
        arr = src.read()
        profile = src.profile

    arr_reduzido = arr[idx_manter]
    profile_reduzido = dict(profile)
    profile_reduzido["count"] = len(idx_manter)

    out_dir = SETTINGS.interim_dir / "features" / "s2" / SITE_FALTANDO
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tif = out_dir / "2025.tif"
    with rasterio.open(out_tif, "w", **profile_reduzido) as dst:
        dst.write(arr_reduzido)
        dst.descriptions = tuple(bandas_restantes)

    manifest_novo = dict(manifest)
    manifest_novo["bandas"] = bandas_restantes
    manifest_novo["site_id"] = SITE_FALTANDO
    (SETTINGS.manifests_dir / f"features_s2_{SITE_FALTANDO}_2025.json").write_text(
        json.dumps(manifest_novo, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[faltando] banda removida: {banda_removida!r} — restam {bandas_restantes}")


def main() -> None:
    pacote = joblib.load(MODELO_PATH)

    print("=" * 80)
    print("TESTE 1 — banda embaralhada: resultado deve ser IDÊNTICO ao original")
    print("=" * 80)
    _limpar(SITE_EMBARALHADO)
    _preparar_embaralhado()
    resultado_original = classificar_site_ano("s2", "ascenty-vinhedo", 2025, pacote, MODELO_PATH, force=False, gerar_png=False)
    resultado_embaralhado = classificar_site_ano("s2", SITE_EMBARALHADO, 2025, pacote, MODELO_PATH, force=True, gerar_png=False)
    sha_original = resultado_original["sha256"]
    sha_embaralhado = resultado_embaralhado["sha256"]
    print(f"sha256 original (bandas em ordem):    {sha_original}")
    print(f"sha256 embaralhado (bandas fora de ordem): {sha_embaralhado}")
    print(f"IDÊNTICO: {sha_original == sha_embaralhado}")
    assert sha_original == sha_embaralhado, "FALHOU: reordenação por nome não está funcionando"

    print()
    print("=" * 80)
    print("TESTE 2 — banda faltando ('bsi' removida): deve levantar PredictError nomeando a banda")
    print("=" * 80)
    _limpar(SITE_FALTANDO)
    _preparar_faltando("bsi")
    try:
        classificar_site_ano("s2", SITE_FALTANDO, 2025, pacote, MODELO_PATH, force=True, gerar_png=False)
        print("FALHOU: deveria ter levantado PredictError, mas não levantou nada.")
    except PredictError as e:
        print(f"OK — PredictError levantado: {e}")
        assert "bsi" in str(e), "FALHOU: mensagem de erro não nomeia a banda ausente"

    print()
    print("Limpando artefatos de teste...")
    _limpar(SITE_EMBARALHADO)
    _limpar(SITE_FALTANDO)
    print("OK.")


if __name__ == "__main__":
    main()
