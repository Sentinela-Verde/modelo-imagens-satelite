"""Testes de sentinela.features.indices (SV-08).

Os cenários 1-3 e o de intervalo teórico são testes puros (sem I/O) sobre
`calcular_indices`/`montar_stack`. O cenário 5 (valores conhecidos + prova de que o código não
ramifica por sensor) roda o pipeline completo (`processar_site_ano`) sobre um `.tif` bruto
sintético, isolado em `tmp_path` — não toca `data/` real.

Os cenários 4 e 6, e as checagens adicionais dos critérios de aceite (zero NaN/inf, idempotência,
sanidade física, continuidade 2018->2019), rodam sobre os stacks reais em
`data/interim/features/` (gerados a partir de `data/raw/` de SV-06/SV-06b via
`python -m sentinela.features.indices --sensor all --site all --ano all`) e viram
`pytest.skip(...)` com mensagem clara se ainda não existirem.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from sentinela.config import SETTINGS
from sentinela.features.indices import (
    _CLIP,
    EPS,
    NODATA,
    _dividir_seguro,
    bandas_features,
    calcular_indices,
    montar_stack,
    processar_site_ano,
)
from sentinela.gee.harmonizacao import bandas_harmonizadas


def _bandas_uniformes(valor: float, shape: tuple[int, int] = (3, 3)) -> dict[str, np.ndarray]:
    """dict de bandas com o mesmo valor em todos os pixels — útil pra montar cenários simples."""
    return {b: np.full(shape, valor, dtype=np.float32) for b in bandas_harmonizadas()}


# --------------------------------------------------------------------------------------------
# Cenário 1 — divisão por zero: NDVI (e os demais índices) viram nodata, nunca NaN/inf
# --------------------------------------------------------------------------------------------


def test_cenario1_divisao_por_zero_vira_nodata_nao_nan():
    bandas = _bandas_uniformes(0.0, shape=(1, 1))  # nir = red = ... = 0 em todas as bandas
    indices, invalido = calcular_indices(bandas)

    assert not np.isnan(indices["ndvi"]).any()
    assert not np.isinf(indices["ndvi"]).any()
    assert invalido[0, 0]  # nir+red=0 (denominador do NDVI) -> pixel marcado inválido

    stack, pct = montar_stack(bandas, np.zeros((1, 1), dtype=bool))
    assert np.all(stack[:, 0, 0] == NODATA), "pixel com denominador zero devia virar nodata nas 13 bandas"
    assert pct == 0.0


def test_dividir_seguro_denominador_exatamente_zero_nunca_gera_nan_ou_inf():
    num = np.array([1.0, -1.0, 0.0], dtype=np.float32)
    den = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    invalido = np.zeros(3, dtype=bool)
    resultado = _dividir_seguro(num, den, invalido)
    assert not np.isnan(resultado).any()
    assert not np.isinf(resultado).any()
    assert np.all(resultado == 0.0)
    assert np.all(invalido)


def test_dividir_seguro_denominador_perto_de_zero_tambem_vira_invalido():
    num = np.array([1.0], dtype=np.float32)
    den = np.array([EPS / 10], dtype=np.float32)  # abaixo do limiar, mas != 0.0
    invalido = np.zeros(1, dtype=bool)
    _dividir_seguro(num, den, invalido)
    assert invalido[0]


def test_dividir_seguro_denominador_valido_nao_marca_invalido():
    num = np.array([0.4], dtype=np.float32)
    den = np.array([0.5], dtype=np.float32)
    invalido = np.zeros(1, dtype=bool)
    resultado = _dividir_seguro(num, den, invalido)
    assert resultado[0] == pytest.approx(0.8)
    assert not invalido[0]


# --------------------------------------------------------------------------------------------
# Cenário 2 — intervalo teórico: NDVI/NDWI/NDBI/BSI/NDMI em [-1, 1], EVI em [-1, 2.5]
# --------------------------------------------------------------------------------------------


def test_cenario2_indices_dentro_do_intervalo_teorico():
    rng = np.random.default_rng(42)
    shape = (50, 50)
    # Faixa ampla de propósito (inclui valores fisicamente implausíveis) — o clip tem que
    # segurar mesmo em entradas ruins, não só no caso "bem comportado".
    bandas = {b: rng.uniform(-1.0, 1.5, size=shape).astype(np.float32) for b in bandas_harmonizadas()}
    indices, _ = calcular_indices(bandas)

    assert set(indices) == {"ndvi", "evi", "ndwi", "mndwi", "ndbi", "bsi", "ndmi"}
    for nome, arr in indices.items():
        lo, hi = _CLIP[nome]
        assert arr.min() >= lo - 1e-6, f"{nome}: valor abaixo do clip teórico {lo}"
        assert arr.max() <= hi + 1e-6, f"{nome}: valor acima do clip teórico {hi}"
        assert not np.isnan(arr).any(), f"{nome}: NaN encontrado"
        assert not np.isinf(arr).any(), f"{nome}: inf encontrado"


# --------------------------------------------------------------------------------------------
# Cenário 3 — máscara conjunta: nodata em uma única banda de entrada propaga para as 13 de saída
# --------------------------------------------------------------------------------------------


def test_cenario3_nodata_em_uma_banda_propaga_para_as_13():
    shape = (2, 2)
    bandas = {
        "blue": np.full(shape, 0.05, dtype=np.float32),
        "green": np.full(shape, 0.08, dtype=np.float32),
        "red": np.full(shape, 0.04, dtype=np.float32),
        "nir": np.full(shape, 0.35, dtype=np.float32),
        "swir1": np.full(shape, 0.15, dtype=np.float32),
        "swir2": np.full(shape, 0.08, dtype=np.float32),
    }
    # Simula o que `_ler_raster_origem` faria: uma única banda nodata num pixel já vira
    # `pixel_nodata_entrada=True` para o pixel inteiro (a máscara de nodata é por pixel, não por
    # banda, desde a leitura — ver docstring do módulo).
    pixel_nodata_entrada = np.zeros(shape, dtype=bool)
    pixel_nodata_entrada[0, 1] = True

    stack, _ = montar_stack(bandas, pixel_nodata_entrada)

    assert stack.shape[0] == 13
    assert np.all(stack[:, 0, 1] == NODATA), "pixel nodata na entrada devia virar nodata nas 13 bandas"
    assert np.all(stack[:, 0, 0] != NODATA)
    assert np.all(stack[:, 1, 0] != NODATA)
    assert np.all(stack[:, 1, 1] != NODATA)


def test_bandas_features_13_nomes_ordem_fixa():
    bandas = bandas_features()
    assert len(bandas) == 13
    assert bandas[:6] == bandas_harmonizadas()
    assert bandas[6:] == ["ndvi", "evi", "ndwi", "mndwi", "ndbi", "bsi", "ndmi"]


# --------------------------------------------------------------------------------------------
# Cenário 5 — valores conhecidos + prova de que o código não ramifica por sensor
# --------------------------------------------------------------------------------------------


def _escrever_raw_sintetico(tmp_path, sensor_token: str, site_id: str, ano: int, arr_refl: np.ndarray, *, resolucao_m: int):
    """Escreve um `.tif` bruto (int16 x10000, nodata -9999) + manifest mínimo, no layout que
    `processar_site_ano` espera — testa o pipeline completo sem depender de dado real."""
    fator_escala = 10000
    nodata = -9999
    arr_int16 = np.round(arr_refl * fator_escala).astype(np.int16)

    raw_dir = tmp_path / "data" / "raw" / sensor_token / site_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    tif_path = raw_dir / f"{ano}.tif"
    transform = from_origin(0, 0, resolucao_m, resolucao_m)
    profile = {
        "driver": "GTiff",
        "dtype": "int16",
        "nodata": nodata,
        "width": arr_int16.shape[2],
        "height": arr_int16.shape[1],
        "count": arr_int16.shape[0],
        "crs": "EPSG:31983",
        "transform": transform,
    }
    with rasterio.open(tif_path, "w", **profile) as ds:
        ds.write(arr_int16)
        ds.descriptions = tuple(bandas_harmonizadas())

    manifest_dir = tmp_path / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{sensor_token}_{site_id}_{ano}.json"
    manifest = {
        "bandas": bandas_harmonizadas(),
        "nodata": nodata,
        "fator_escala": fator_escala,
        "resolucao_m": resolucao_m,
    }
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f)

    return tif_path, manifest_path


def test_cenario5_pixel_sintetico_vegetacao_e_solo_resultado_independe_do_sensor(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "data_root", tmp_path / "data")

    idx = {b: i for i, b in enumerate(bandas_harmonizadas())}
    arr = np.zeros((6, 1, 2), dtype=np.float32)
    # pixel [0]: assinatura de vegetação densa (red baixo, nir alto)
    arr[idx["blue"], 0, 0] = 0.03
    arr[idx["green"], 0, 0] = 0.06
    arr[idx["red"], 0, 0] = 0.03
    arr[idx["nir"], 0, 0] = 0.45
    arr[idx["swir1"], 0, 0] = 0.12
    arr[idx["swir2"], 0, 0] = 0.06
    # pixel [1]: assinatura de solo exposto (red/swir1 altos, nir moderado)
    arr[idx["blue"], 0, 1] = 0.15
    arr[idx["green"], 0, 1] = 0.18
    arr[idx["red"], 0, 1] = 0.22
    arr[idx["nir"], 0, 1] = 0.28
    arr[idx["swir1"], 0, 1] = 0.35
    arr[idx["swir2"], 0, 1] = 0.30

    site_id, ano = "site-teste-sv08", 2020
    resultados = {}
    for sensor_token, resolucao_m in (("s2", 10), ("landsat", 30)):
        _escrever_raw_sintetico(tmp_path, sensor_token, site_id, ano, arr, resolucao_m=resolucao_m)
        manifest = processar_site_ano(sensor_token, site_id, ano)
        out_path = SETTINGS.interim_dir / "features" / sensor_token / site_id / f"{ano}.tif"
        with rasterio.open(out_path) as ds:
            stack = ds.read()
            bandas_out = list(ds.descriptions)
        resultados[sensor_token] = (stack, bandas_out, manifest)

    stack_s2, bandas_s2, manifest_s2 = resultados["s2"]
    stack_landsat, bandas_landsat, manifest_landsat = resultados["landsat"]

    assert bandas_s2 == bandas_landsat == bandas_features()

    idx_out = {b: i for i, b in enumerate(bandas_s2)}
    ndvi_veg = stack_s2[idx_out["ndvi"], 0, 0]
    bsi_veg = stack_s2[idx_out["bsi"], 0, 0]
    ndvi_solo = stack_s2[idx_out["ndvi"], 0, 1]
    bsi_solo = stack_s2[idx_out["bsi"], 0, 1]

    assert ndvi_veg > 0.5, "vegetação sintética devia dar NDVI alto"
    assert bsi_veg < 0.0, "vegetação sintética devia dar BSI baixo"
    assert ndvi_solo < ndvi_veg, "solo sintético devia dar NDVI menor que vegetação"
    assert bsi_solo > bsi_veg, "solo sintético devia dar BSI maior que vegetação"

    # A prova em si: o MESMO pixel sintético, processado como Sentinel-2 ou como Landsat, produz
    # exatamente o mesmo resultado — o código de índices não ramifica por sensor.
    np.testing.assert_allclose(stack_s2, stack_landsat, atol=1e-5)
    assert manifest_s2["bandas"] == manifest_landsat["bandas"] == bandas_features()


# --------------------------------------------------------------------------------------------
# Cenário 4 — grade (transform/CRS/shape) idêntica ao raster de origem, nas duas eras
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensor_token,site_id,ano",
    [
        ("s2", "ascenty-vinhedo", 2019),
        ("landsat", "ascenty-vinhedo", 2013),
    ],
)
def test_cenario4_grade_identica_ao_raster_de_origem(sensor_token, site_id, ano):
    raw_path = SETTINGS.raw_dir / sensor_token / site_id / f"{ano}.tif"
    out_path = SETTINGS.interim_dir / "features" / sensor_token / site_id / f"{ano}.tif"
    if not (raw_path.exists() and out_path.exists()):
        pytest.skip(
            f"{raw_path} ou {out_path} não existe — rode "
            f"`python -m sentinela.features.indices --sensor all --site all --ano all` antes."
        )

    with rasterio.open(raw_path) as ds_raw, rasterio.open(out_path) as ds_out:
        assert ds_out.transform == ds_raw.transform
        assert ds_out.crs == ds_raw.crs
        assert (ds_out.width, ds_out.height) == (ds_raw.width, ds_raw.height)
        assert ds_out.count == 13
        assert ds_out.dtypes == ("float32",) * 13
        assert ds_out.nodata == NODATA
        assert list(ds_out.descriptions) == bandas_features()


# --------------------------------------------------------------------------------------------
# Cenário 6 — contrato de bandas idêntico entre as duas eras
# --------------------------------------------------------------------------------------------


def test_cenario6_contrato_de_bandas_s2_igual_landsat():
    p_s2 = SETTINGS.manifests_dir / "features_s2_ascenty-vinhedo_2019.json"
    p_landsat = SETTINGS.manifests_dir / "features_landsat_ascenty-vinhedo_2013.json"
    if not (p_s2.exists() and p_landsat.exists()):
        pytest.skip(
            f"{p_s2} ou {p_landsat} não existe — rode "
            f"`python -m sentinela.features.indices --sensor all --site all --ano all` antes."
        )
    with p_s2.open("r", encoding="utf-8") as f:
        manifest_s2 = json.load(f)
    with p_landsat.open("r", encoding="utf-8") as f:
        manifest_landsat = json.load(f)

    assert manifest_s2["bandas"] == manifest_landsat["bandas"] == bandas_features()


# --------------------------------------------------------------------------------------------
# Critérios de aceite adicionais, sobre os stacks reais (pulados se ainda não gerados)
# --------------------------------------------------------------------------------------------


def _todos_os_stacks_gerados() -> list:
    return sorted((SETTINGS.interim_dir / "features").glob("*/*/*.tif"))


def test_zero_nan_zero_inf_em_todos_os_stacks_gerados():
    stacks = _todos_os_stacks_gerados()
    if not stacks:
        pytest.skip("nenhum stack em data/interim/features/ ainda — rode a CLI de SV-08 antes.")
    for path in stacks:
        with rasterio.open(path) as ds:
            arr = ds.read()
        assert not np.isnan(arr).any(), f"{path}: NaN encontrado"
        assert not np.isinf(arr).any(), f"{path}: inf encontrado"


def test_idempotencia_mesma_execucao_gera_mesmo_sha256():
    raw = SETTINGS.raw_dir / "s2" / "ascenty-vinhedo" / "2019.tif"
    if not raw.exists():
        pytest.skip(f"{raw} não existe.")
    m1 = processar_site_ano("s2", "ascenty-vinhedo", 2019)
    m2 = processar_site_ano("s2", "ascenty-vinhedo", 2019)
    assert m1["sha256"] == m2["sha256"]


@pytest.mark.parametrize("site_id", ["ascenty-vinhedo", "odata-hortolandia", "scala-tambore"])
def test_sanity_ndvi_mata_fechada_telhado_asfalto_e_mndwi_agua(site_id):
    """Sanidade física manual (item 'Como reportar' de SV-08): amostra pixels conhecidos (via
    percentil, já que não há coordenada exata de telhado/água catalogada) e confere que o sinal
    bate com o esperado fisicamente."""
    path = SETTINGS.interim_dir / "features" / "s2" / site_id / "2024.tif"
    if not path.exists():
        pytest.skip(f"{path} não existe — rode a CLI de SV-08 antes.")

    with rasterio.open(path) as ds:
        arr = ds.read()
        bandas = list(ds.descriptions)
    idx = {b: i for i, b in enumerate(bandas)}
    valido = arr[idx["blue"]] != NODATA
    ndvi, mndwi = arr[idx["ndvi"]], arr[idx["mndwi"]]

    ndvi_valido = ndvi[valido]
    mata = valido & (ndvi >= np.percentile(ndvi_valido, 95))
    construido = valido & (ndvi <= np.percentile(ndvi_valido, 5))

    ndvi_mata = float(ndvi[mata].mean())
    ndvi_construido = float(ndvi[construido].mean())
    print(
        f"\n[{site_id}] sanidade: NDVI mata fechada (top 5% NDVI) = {ndvi_mata:.3f} | "
        f"NDVI telhado/asfalto/solo (bottom 5% NDVI) = {ndvi_construido:.3f}"
    )
    assert ndvi_mata > 0.6
    assert ndvi_construido < 0.2

    agua = valido & (mndwi > 0)
    if agua.sum() == 0:
        pytest.skip(f"{site_id}: nenhum pixel com MNDWI>0 em 2024 — sem corpo d'água detectável nesta AOI/ano.")
    mndwi_agua = float(mndwi[agua].mean())
    print(f"[{site_id}] sanidade: MNDWI médio em pixels de água candidatos (n={int(agua.sum())}) = {mndwi_agua:.3f}")
    assert mndwi_agua > 0


@pytest.mark.parametrize("site_id", ["ascenty-vinhedo", "odata-hortolandia", "scala-tambore"])
def test_continuidade_ndvi_2018_landsat_para_2019_s2_mata_estavel(site_id):
    """Item 'Como reportar'/critério de aceite de SV-08: NDVI médio numa área de mata estável não
    pode dar um salto grosseiro entre 2018 (Landsat) e 2019 (Sentinel-2) — mesma metodologia e
    mesma tolerância de `tests/test_landsat.py::test_cenario6...` (SV-06b), mas medida sobre a
    banda `ndvi` já gravada no stack de SV-08, não recalculada aqui."""
    p_l = SETTINGS.interim_dir / "features" / "landsat" / site_id / "2018.tif"
    p_s = SETTINGS.interim_dir / "features" / "s2" / site_id / "2019.tif"
    if not (p_l.exists() and p_s.exists()):
        pytest.skip("stacks 2018 (landsat) / 2019 (s2) ainda não gerados — rode a CLI de SV-08 antes.")

    with rasterio.open(p_l) as ds:
        arr_l = ds.read()
        bandas_l = list(ds.descriptions)
    with rasterio.open(p_s) as ds:
        arr_s = ds.read()
        bandas_s = list(ds.descriptions)

    idx_l = {b: i for i, b in enumerate(bandas_l)}
    idx_s = {b: i for i, b in enumerate(bandas_s)}
    ndvi_l = arr_l[idx_l["ndvi"]]
    ndvi_s = arr_s[idx_s["ndvi"]]
    valido_l = arr_l[idx_l["blue"]] != NODATA
    valido_s = arr_s[idx_s["blue"]] != NODATA

    limiar = np.percentile(ndvi_l[valido_l], 90)
    mascara_mata = valido_l & (ndvi_l >= limiar)

    h_l, w_l = ndvi_l.shape
    h_s, w_s = ndvi_s.shape
    h_ok, w_ok = min(h_l * 3, h_s), min(w_l * 3, w_s)
    ndvi_s_agregado = ndvi_s[:h_ok, :w_ok].reshape(h_ok // 3, 3, w_ok // 3, 3).mean(axis=(1, 3))
    valido_s_agregado = valido_s[:h_ok, :w_ok].reshape(h_ok // 3, 3, w_ok // 3, 3).all(axis=(1, 3))

    h_c, w_c = ndvi_s_agregado.shape
    mascara_c = mascara_mata[:h_c, :w_c] & valido_s_agregado

    diff_ndvi = float(np.mean(np.abs(ndvi_l[:h_c, :w_c][mascara_c] - ndvi_s_agregado[mascara_c])))
    print(f"\n[{site_id}] continuidade NDVI 2018(Landsat)->2019(S2), mata estável: |dNDVI| médio = {diff_ndvi:.4f}")
    assert diff_ndvi < 0.10, f"|dNDVI| médio = {diff_ndvi:.4f} — salto grosseiro entre eras?"
