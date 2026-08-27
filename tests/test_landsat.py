"""Testes de sentinela.gee.landsat (SV-06b).

Testes puros (grade, conversão int16, pct válidos) não tocam o Earth Engine. Os testes de
integração (`test_ingerir_*`) chamam o EE de verdade e a rede (mesma dependência de
`tests/test_harmonizacao.py`) — reaproveitam o site `ascenty-vinhedo`/ano 2018 já ingerido durante
o desenvolvimento desta tarefa, então na maioria das vezes só exercitam o caminho idempotente
(rápido, sem novo download).

Os cenários de comparação com o Sentinel-2 (contrato de bandas, alinhamento de grade,
continuidade visual 2018->2019) dependem dos manifests de SV-06 (`s2_{site}_{ano}.json`), que é
uma tarefa rodando em paralelo, sem coordenação direta com esta. Esses testes fazem
`pytest.skip(...)` com uma mensagem clara quando o manifest correspondente ainda não existe, em
vez de falhar — não é responsabilidade desta tarefa esperar pela outra.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.gee.auth import init_ee
from sentinela.gee.harmonizacao import bandas_harmonizadas
from sentinela.gee.landsat import (
    FATOR_ESCALA,
    NODATA,
    RESOLUCAO_M,
    _anos_alvo,
    _para_int16,
    _pct_pixels_validos,
    calcular_grade,
    ingerir_site_ano,
)


@pytest.fixture(scope="module", autouse=True)
def _ee():
    init_ee()


# --------------------------------------------------------------------------------------------
# Grade determinística — o contrato de coordenação com SV-06 (sem comunicação ao vivo).
# --------------------------------------------------------------------------------------------


# Valores calculados de forma independente nesta tarefa a partir de config/sites.geojson (mesma
# fórmula que SV-06 recebeu, palavra por palavra) — servem de valor de referência para pegar
# regressão na fórmula, não são "mágicos".
_GRADES_ESPERADAS_30M = {
    "ascenty-vinhedo": (-47.0118926, -23.0700044, 5, 288870, 7452330, 335, 334),
    "odata-hortolandia": (-47.1952611, -22.8995299, 5, 269820, 7470930, 334, 334),
    "scala-tambore": (-46.8130769, -23.4948321, 5, 309840, 7405560, 334, 335),
}


@pytest.mark.parametrize("site_id", list(_GRADES_ESPERADAS_30M))
def test_calcular_grade_valores_esperados_por_site(site_id):
    lon, lat, buffer_km, origin_x, origin_y, width, height = _GRADES_ESPERADAS_30M[site_id]
    grade = calcular_grade(lon, lat, buffer_km)
    assert grade["origin_x"] == origin_x
    assert grade["origin_y"] == origin_y
    assert grade["width"] == width
    assert grade["height"] == height


def test_calcular_grade_origem_e_multiplo_da_resolucao():
    for lon, lat, buffer_km, *_ in _GRADES_ESPERADAS_30M.values():
        grade = calcular_grade(lon, lat, buffer_km)
        assert grade["origin_x"] % RESOLUCAO_M == 0
        assert grade["origin_y"] % RESOLUCAO_M == 0


def test_calcular_grade_cobre_o_buffer_inteiro():
    """A grade (origem + largura/altura) deve conter o círculo de buffer inteiro, não cortar."""
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
    for lon, lat, buffer_km, *_ in _GRADES_ESPERADAS_30M.values():
        grade = calcular_grade(lon, lat, buffer_km)
        x0, y0 = transformer.transform(lon, lat)
        buffer_m = buffer_km * 1000
        minx, miny, maxx, maxy = x0 - buffer_m, y0 - buffer_m, x0 + buffer_m, y0 + buffer_m
        res = grade["resolucao_m"]
        assert grade["origin_x"] <= minx
        assert grade["origin_y"] >= maxy
        assert grade["origin_x"] + grade["width"] * res >= maxx
        assert grade["origin_y"] - grade["height"] * res <= miny


def test_calcular_grade_mesmo_site_anos_diferentes_grade_identica():
    """Não depende do ano — só de (lon, lat, buffer_km) — logo é sempre igual entre anos."""
    lon, lat, buffer_km, *_ = _GRADES_ESPERADAS_30M["ascenty-vinhedo"]
    g1 = calcular_grade(lon, lat, buffer_km)
    g2 = calcular_grade(lon, lat, buffer_km)
    assert g1 == g2


# --------------------------------------------------------------------------------------------
# Conversão de escala / nodata (funções puras, sem EE)
# --------------------------------------------------------------------------------------------


def test_para_int16_sentinela_de_nodata_vira_exatamente_nodata():
    sentinela_float = NODATA / FATOR_ESCALA  # -0.9999
    arr = np.array([[[sentinela_float, 0.15, -0.02]]], dtype=np.float32)
    arr_int16 = _para_int16(arr)
    assert arr_int16[0, 0, 0] == NODATA


def test_para_int16_valores_fisicos_plausiveis():
    arr = np.array([[[0.03, 0.55]]], dtype=np.float32)  # red baixo / nir alto de vegetação
    arr_int16 = _para_int16(arr)
    assert arr_int16[0, 0, 0] == 300
    assert arr_int16[0, 0, 1] == 5500


def test_pct_pixels_validos_conta_so_banda_0_ignora_nodata():
    banda0 = np.array([[NODATA, 100, 200], [NODATA, NODATA, 300]])
    outras_bandas = np.zeros_like(banda0)
    arr = np.stack([banda0, outras_bandas, outras_bandas, outras_bandas, outras_bandas, outras_bandas])
    pct = _pct_pixels_validos(arr)
    assert pct == pytest.approx(100.0 * 3 / 6)


def test_anos_alvo_cobre_2013_2018_mais_sobreposicao_sem_duplicar():
    anos = _anos_alvo()
    assert anos == sorted(set(anos))  # sem duplicata
    assert set(range(2013, 2019)).issubset(anos)
    params = SETTINGS.params()
    for ano in params["faixa_a"]["anos_sobreposicao"]:
        assert ano in anos
    # anos puramente Sentinel-2 (fora da sobreposição) não devem aparecer aqui
    assert 2023 not in anos


# --------------------------------------------------------------------------------------------
# Integração: ingestão real (reaproveita ascenty-vinhedo/2018, já gerado nesta tarefa)
# --------------------------------------------------------------------------------------------

_SITE_TESTE = {"site_id": "ascenty-vinhedo", "lat": -23.0700044, "lon": -47.0118926, "buffer_km": 5}
_ANO_TESTE = 2018


def _tif_teste():
    return SETTINGS.raw_dir / "landsat" / _SITE_TESTE["site_id"] / f"{_ANO_TESTE}.tif"


def _manifest_teste():
    return SETTINGS.manifests_dir / f"landsat_{_SITE_TESTE['site_id']}_{_ANO_TESTE}.json"


def test_cenario1_ingerir_gera_tif_e_manifest():
    manifest = ingerir_site_ano(_SITE_TESTE, _ANO_TESTE, 6, 9)
    assert _tif_teste().exists()
    assert _manifest_teste().exists()
    assert manifest["sensor"] == "landsat"
    assert manifest["resolucao_m"] == RESOLUCAO_M
    assert manifest["bandas"] == bandas_harmonizadas()
    assert manifest["nodata"] == NODATA
    assert manifest["fator_escala"] == FATOR_ESCALA


def test_cenario2_idempotencia_e_determinismo_mesmo_sha256():
    m1 = ingerir_site_ano(_SITE_TESTE, _ANO_TESTE, 6, 9)
    m2 = ingerir_site_ano(_SITE_TESTE, _ANO_TESTE, 6, 9)
    assert m1["sha256"] == m2["sha256"]


def test_manifest_sha256_bate_com_arquivo_real():
    with _manifest_teste().open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    import hashlib

    h = hashlib.sha256()
    with _tif_teste().open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    assert manifest["sha256"] == h.hexdigest()


def test_tif_tem_as_6_bandas_canonicas_int16_31983_30m():
    with rasterio.open(_tif_teste()) as ds:
        assert ds.count == 6
        assert ds.dtypes == ("int16",) * 6
        assert ds.nodata == NODATA
        assert ds.crs.to_string() in ("EPSG:31983", "epsg:31983")
        assert ds.transform.a == RESOLUCAO_M
        assert -ds.transform.e == RESOLUCAO_M
        assert list(ds.descriptions) == bandas_harmonizadas()


def test_cenario4_escala_reflectancia_em_faixa_fisica():
    """Sanidade física: reflectância em [-0.05, 1.2]; red baixo / nir alto sobre vegetação."""
    with rasterio.open(_tif_teste()) as ds:
        arr_int = ds.read()
        arr = arr_int.astype(np.float64) / FATOR_ESCALA
        bandas = list(ds.descriptions)
    valido = arr_int[0] != NODATA

    idx = {b: i for i, b in enumerate(bandas)}
    red = arr[idx["red"]]
    nir = arr[idx["nir"]]

    assert red[valido].min() >= -0.05, "red abaixo de -0.05 sugere escala/offset errados"
    assert arr[:, valido].max() <= 1.2, "reflectância acima de 1.2 sugere escala/offset errados"

    ndvi = np.zeros_like(red)
    ndvi[valido] = (nir[valido] - red[valido]) / (nir[valido] + red[valido] + 1e-9)
    limiar_vegetacao = np.percentile(ndvi[valido], 75)
    mascara_vegetacao = valido & (ndvi >= limiar_vegetacao)
    assert mascara_vegetacao.sum() > 0
    assert np.median(red[mascara_vegetacao]) < 0.1, "red sobre vegetação deveria ser < 0.1"
    assert np.median(nir[mascara_vegetacao]) > 0.2, "nir sobre vegetação deveria ser > 0.2"


def test_pct_pixels_validos_no_manifest_acima_do_piso_ou_justificado():
    with _manifest_teste().open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    pct = manifest["pct_pixels_validos"]
    assert 0.0 <= pct <= 100.0
    if pct < 90.0:
        # Critério de aceite permite < 90% desde que a janela tenha sido ampliada e registrada.
        assert manifest["janela_ampliada"] is True


# --------------------------------------------------------------------------------------------
# Cenários que dependem do manifest de SV-06 (Sentinel-2) — pulados se ainda não existir.
# --------------------------------------------------------------------------------------------


def _manifest_s2(site_id: str, ano: int):
    path = REPO_ROOT / "data" / "manifests" / f"s2_{site_id}_{ano}.json"
    if not path.exists():
        pytest.skip(f"{path} ainda não existe — SV-06 (Sentinel-2) roda em paralelo, sem coordenação.")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_cenario3_contrato_de_bandas_landsat_igual_s2():
    with _manifest_teste().open("r", encoding="utf-8") as f:
        manifest_landsat = json.load(f)
    manifest_s2 = _manifest_s2(_SITE_TESTE["site_id"], 2019)
    assert manifest_landsat["bandas"] == manifest_s2["bandas"]


def test_cenario5_alinhamento_entre_grades_30m_e_10m():
    with _manifest_teste().open("r", encoding="utf-8") as f:
        manifest_landsat = json.load(f)
    manifest_s2 = _manifest_s2(_SITE_TESTE["site_id"], 2019)

    transform_30m = manifest_landsat["transform"]
    transform_10m = manifest_s2["transform"]
    origem_x_30m, origem_y_30m = transform_30m[2], transform_30m[5]
    origem_x_10m, origem_y_10m = transform_10m[2], transform_10m[5]

    assert (origem_x_10m - origem_x_30m) % 30 == 0
    assert (origem_y_10m - origem_y_30m) % 30 == 0
    assert manifest_s2["resolucao_m"] == 10
    assert manifest_landsat["resolucao_m"] == 30


def test_cenario6_continuidade_visual_ndvi_2018_2019_mata_estavel():
    """Diferença de NDVI médio sobre uma área de mata estável entre 2018 (Landsat) e 2019 (S2)
    deve ser pequena — o teste mais importante da tarefa (item 6 do enunciado)."""
    tif_s2_2019 = REPO_ROOT / "data" / "raw" / "s2" / _SITE_TESTE["site_id"] / "2019.tif"
    if not tif_s2_2019.exists():
        pytest.skip(f"{tif_s2_2019} ainda não existe — SV-06 roda em paralelo, sem coordenação.")

    with rasterio.open(_tif_teste()) as ds:
        arr_l = ds.read().astype(np.float64) / FATOR_ESCALA
        bandas_l = list(ds.descriptions)
    with rasterio.open(tif_s2_2019) as ds:
        arr_s = ds.read().astype(np.float64) / FATOR_ESCALA
        bandas_s = list(ds.descriptions)

    idx_l = {b: i for i, b in enumerate(bandas_l)}
    idx_s = {b: i for i, b in enumerate(bandas_s)}
    red_l, nir_l = arr_l[idx_l["red"]], arr_l[idx_l["nir"]]
    red_s, nir_s = arr_s[idx_s["red"]], arr_s[idx_s["nir"]]

    ndvi_l = (nir_l - red_l) / (nir_l + red_l + 1e-9)
    ndvi_s = (nir_s - red_s) / (nir_s + red_s + 1e-9)

    # Mata estável ~ alto NDVI em 2018 (quartil superior) na grade Landsat; agrega S2 (10m) para
    # a grade Landsat (30m) por média simples de blocos 3x3 alinhados (mesma origem, refinamento
    # exato — ver test_cenario5).
    limiar = np.percentile(ndvi_l, 90)
    mascara_mata = ndvi_l >= limiar

    h_l, w_l = ndvi_l.shape
    h_s, w_s = ndvi_s.shape
    h_ok, w_ok = min(h_l * 3, h_s), min(w_l * 3, w_s)
    ndvi_s_agregado = (
        ndvi_s[:h_ok, :w_ok]
        .reshape(h_ok // 3, 3, w_ok // 3, 3)
        .mean(axis=(1, 3))
    )
    h_c, w_c = ndvi_s_agregado.shape
    mascara_mata_c = mascara_mata[:h_c, :w_c]

    diff_ndvi = float(np.mean(np.abs(ndvi_l[:h_c, :w_c][mascara_mata_c] - ndvi_s_agregado[mascara_mata_c])))
    print(f"\nContinuidade visual 2018->2019 (mata estável, top 10% NDVI 2018): |dNDVI| médio = {diff_ndvi:.4f}")
    # Mesma tolerância de índice usada em SV-02b/ADR-003 (test_cenario3_ndvi_mesma_cena_mesmo_dia):
    # 0.10, folga sobre a tolerância de viés por banda (0.02) para um índice derivado.
    assert diff_ndvi < 0.10, f"|dNDVI| médio = {diff_ndvi:.4f} — salto grosseiro entre eras?"
