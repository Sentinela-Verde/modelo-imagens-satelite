"""Testes de sentinela.gee.harmonizacao (SV-02b).

Estes testes chamam o Earth Engine de verdade (imagens sintéticas via ee.Image.constant para os
casos determinísticos, mais alguns casos com dado real — par Landsat/S2 do mesmo dia, cena
Sentinel-2 nublada, e um composto sazonal de 1 ano), então dependem de `init_ee()` ter sucesso no
ambiente de teste — mesma dependência que `tests` de outras tarefas de GEE do projeto.
`test_cenario5_...` monta um composto real e pode levar 1-2 minutos.
"""

from __future__ import annotations

import ee
import pytest

from sentinela.gee.auth import init_ee
from sentinela.gee.harmonizacao import (
    bandas_harmonizadas,
    harmonizar_landsat,
    harmonizar_s2,
    mascara_nuvem,
)


@pytest.fixture(scope="module", autouse=True)
def _ee():
    init_ee()


def _imagem_landsat_sintetica() -> ee.Image:
    # DNs de reflectância de superfície Landsat C2 L2 escolhidos para cair em reflectância
    # ~[0.04, 0.35] após a escala oficial (vegetação: NIR alto, red baixo). DN = (refl+0.2)/0.0000275.
    return ee.Image.constant([9100, 10200, 8700, 20000, 12700, 10200]).rename(
        ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]
    )


def _imagem_s2_sintetica() -> ee.Image:
    # Refletância x10000, mesma cena "vegetação" aproximada (~[0.04, 0.35] após /10000).
    return ee.Image.constant([500, 800, 400, 3500, 1500, 800]).rename(
        ["B2", "B3", "B4", "B8A", "B11", "B12"]
    )


def test_bandas_harmonizadas_ordem_canonica():
    assert bandas_harmonizadas() == ["blue", "green", "red", "nir", "swir1", "swir2"]


def test_cenario1_mesmos_nomes_de_banda_landsat_e_s2():
    nomes_landsat = harmonizar_landsat(_imagem_landsat_sintetica()).bandNames().getInfo()
    nomes_s2 = harmonizar_s2(_imagem_s2_sintetica()).bandNames().getInfo()
    assert nomes_landsat == bandas_harmonizadas()
    assert nomes_s2 == bandas_harmonizadas()


def test_cenario2_escala_cai_no_intervalo_0_1():
    ponto = ee.Geometry.Point(-47.0118926, -23.0700044)

    landsat_vals = (
        harmonizar_landsat(_imagem_landsat_sintetica())
        .reduceRegion(ee.Reducer.first(), ponto, 30)
        .getInfo()
    )
    s2_vals = (
        harmonizar_s2(_imagem_s2_sintetica())
        .reduceRegion(ee.Reducer.first(), ponto, 10)
        .getInfo()
    )

    for banda, valor in landsat_vals.items():
        assert 0.0 <= valor <= 1.0, f"Landsat {banda}={valor} fora de [0,1] — escala esquecida?"
    for banda, valor in s2_vals.items():
        assert 0.0 <= valor <= 1.0, f"S2 {banda}={valor} fora de [0,1] — escala esquecida?"


# Par real Landsat 8 / Sentinel-2 do MESMO DIA sobre ascenty-vinhedo (achado por varredura de
# datas em 2019-06..2021-09 com nuvem < 20%: 2019-06-14 tem as duas aquisições no mesmo dia —
# usado pelos cenários 3 e 5, que precisam de diferença espectral real (não sintética) para fazer
# sentido: uma imagem constante sem forma espectral não tem "erro de bandpass" de verdade a corrigir.
_DATA_PAR_MESMO_DIA = "2019-06-14"


def _aoi_teste() -> ee.Geometry:
    return ee.Geometry.Point(-47.0118926, -23.0700044).buffer(5000)


def _par_mesmo_dia_landsat_s2() -> tuple[ee.Image, ee.Image]:
    aoi = _aoi_teste()
    landsat = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(aoi)
        .filterDate(_DATA_PAR_MESMO_DIA, "2019-06-15")
        .first()
    )
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(_DATA_PAR_MESMO_DIA, "2019-06-15")
        .first()
    )
    return landsat, s2


def test_cenario5_desligar_bandpass_piora_residuo_em_dado_real():
    """Sanidade invertida, medida sobre o composto real usado no spike (Passo 3 / ADR-003).

    Uma comparação de UM pixel em UMA data (ver `test_cenario3`) é dominada por ruído de
    atmosfera/BRDF/coregistração — não é o instrumento certo para este teste (foi tentado nesta
    tarefa e o sinal ficou instável, invertendo de sinal entre datas). O composto sazonal (mediana
    de várias imagens) é o que reduz esse ruído o bastante para o efeito sistemático do bandpass
    aparecer — é também exatamente o que o ADR-003 usou para medir o resíduo real. Reaproveita
    `sentinela.gee.medir_residuo_harmonizacao` em vez de duplicar a lógica de composição.
    """
    from sentinela.gee.medir_residuo_harmonizacao import _composto_landsat, _composto_s2

    aoi = _aoi_teste()
    # Um ano só (mais rápido que os 3 anos de sobreposição do ADR-003) — o objetivo aqui é só
    # confirmar a direção do efeito, não remedir a tabela de resíduo em si.
    landsat = _composto_landsat(aoi, 2020, 2020, 6, 9)
    s2_com = _composto_s2(aoi, 2020, 2020, 6, 9, aplicar_bandpass=True)
    s2_sem = _composto_s2(aoi, 2020, 2020, 6, 9, aplicar_bandpass=False)

    bandas = ["blue", "green", "red", "nir", "swir1", "swir2"]
    proj_landsat = landsat.select("blue").projection()

    def _rmse_pooled(s2_composto) -> float:
        s2_30m = s2_composto.reduceResolution(ee.Reducer.mean(), maxPixels=1024).reproject(proj_landsat)
        diff2 = landsat.select(bandas).subtract(s2_30m.select(bandas)).pow(2)
        medias = diff2.reduceRegion(ee.Reducer.mean(), aoi, 30, maxPixels=1e8).getInfo()
        return sum(medias[b] for b in bandas) / len(bandas)

    rmse2_com = _rmse_pooled(s2_com)
    rmse2_sem = _rmse_pooled(s2_sem)
    assert rmse2_sem >= rmse2_com, (
        f"RMSE² médio (pooled, 6 bandas) sem ajuste ({rmse2_sem:.6f}) deveria ser >= com ajuste "
        f"({rmse2_com:.6f}) — o ajuste de bandpass não parece estar reduzindo o resíduo."
    )


def test_cenario3_ndvi_mesma_cena_mesmo_dia_diverge_pouco():
    """Mesma cena, mesmo dia, dois sensores -> NDVI difere pouco na maioria dos pixels."""
    landsat_raw, s2_raw = _par_mesmo_dia_landsat_s2()

    landsat = harmonizar_landsat(mascara_nuvem(landsat_raw, "landsat"))
    s2 = harmonizar_s2(mascara_nuvem(s2_raw, "sentinel2"), aplicar_bandpass=True)

    def ndvi(img: ee.Image) -> ee.Image:
        return img.normalizedDifference(["nir", "red"]).rename("ndvi")

    ndvi_landsat = ndvi(landsat)
    ndvi_s2_30m = ndvi(s2).reduceResolution(ee.Reducer.mean(), maxPixels=1024).reproject(
        landsat.projection()
    )

    diff = ndvi_landsat.subtract(ndvi_s2_30m).abs().rename("diff_ndvi")
    # Fração de pixels na AOI com |diferença de NDVI| acima da tolerância de viés do spike (0.02
    # seria rigoroso demais para índice — usamos 0.10 de folga para índice, coerente com a
    # tolerância de reflectância por banda propagada por NDVI).
    frac_dentro = (
        diff.lte(0.10)
        .reduceRegion(ee.Reducer.mean(), _aoi_teste(), 30, maxPixels=1e8)
        .get("diff_ndvi")
        .getInfo()
    )
    assert frac_dentro >= 0.5, (
        f"Só {frac_dentro:.0%} dos pixels da AOI têm |dNDVI| <= 0.10 entre Landsat e S2 no mesmo "
        "dia — esperava maioria."
    )


def test_cenario4_mascara_landsat_remove_pixel_nublado():
    ponto = ee.Geometry.Point(-47.0118926, -23.0700044)

    # bit3 (cloud) ligado no QA_PIXEL sintético; QA_RADSAT = 0 (sem saturação).
    bit_cloud = 1 << 3
    img_nublada = (
        _imagem_landsat_sintetica()
        .addBands(ee.Image.constant(bit_cloud).rename("QA_PIXEL"))
        .addBands(ee.Image.constant(0).rename("QA_RADSAT"))
    )
    mascarada = mascara_nuvem(img_nublada, "landsat")
    valores = mascarada.select("SR_B2").reduceRegion(ee.Reducer.count(), ponto, 30).getInfo()
    assert valores["SR_B2"] == 0, "Pixel com bit de nuvem ligado deveria ter sido mascarado."


def test_cenario4_mascara_landsat_mantem_pixel_limpo():
    ponto = ee.Geometry.Point(-47.0118926, -23.0700044)

    img_limpa = (
        _imagem_landsat_sintetica()
        .addBands(ee.Image.constant(0).rename("QA_PIXEL"))
        .addBands(ee.Image.constant(0).rename("QA_RADSAT"))
    )
    mascarada = mascara_nuvem(img_limpa, "landsat")
    valores = mascarada.select("SR_B2").reduceRegion(ee.Reducer.count(), ponto, 30).getInfo()
    assert valores["SR_B2"] == 1, "Pixel limpo não deveria ter sido mascarado."


def test_cenario4_mascara_s2_remove_pixels_nublados_em_cena_real():
    """Usa uma cena Sentinel-2 real e nublada sobre a AOI para exercitar o link com Cloud Score+."""
    site = ee.Geometry.Point(-47.0118926, -23.0700044).buffer(5000)

    colecao = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(site)
        .filterDate("2019-01-01", "2019-03-31")  # verão em SP — janela de maior nebulosidade
        .sort("CLOUDY_PIXEL_PERCENTAGE", False)  # imagem mais nublada primeiro
    )
    img = colecao.first()
    assert img is not None, "Sem imagens Sentinel-2 na janela usada pelo teste."

    total_valido = img.select("B2").reduceRegion(
        ee.Reducer.count(), site, 10, maxPixels=1e8
    ).get("B2").getInfo()
    mascarada = mascara_nuvem(img, "sentinel2")
    total_pos_mascara = mascarada.select("B2").reduceRegion(
        ee.Reducer.count(), site, 10, maxPixels=1e8
    ).get("B2").getInfo()

    assert total_pos_mascara < total_valido, (
        "Esperava que a máscara de Cloud Score+ removesse pixels de uma cena escolhida por ser "
        "a mais nublada disponível na janela, mas a contagem de pixels válidos não caiu."
    )


def test_sensor_invalido_levanta_erro():
    with pytest.raises(ValueError):
        mascara_nuvem(_imagem_landsat_sintetica(), "modis")
