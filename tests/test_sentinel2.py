"""Testes de sentinela.gee.sentinel2 (SV-06).

`test_grade_*` são puramente matemáticos (pyproj, sem Earth Engine) e rápidos — cobrem a regra de
coordenação de grade com SV-06b (origem múltipla de 30 m, independente da resolução pedida).

Os demais testes abrem os arquivos já gerados por uma rodada real do CLI
(`python -m sentinela.gee.sentinel2 --site all --ano all`) em vez de rechamar o Earth Engine — mais
rápido e evita gastar quota duas vezes. Se os arquivos ainda não existirem (ex.: ambiente sem a
ingestão rodada), esses testes são pulados com um motivo claro em vez de falhar.

`test_idempotencia_pula_sem_chamar_earth_engine` chama `processar_site_ano` de verdade, mas só
exercita o caminho de "já existe" (que não faz nenhuma chamada de rede) — não precisa de
`init_ee()`.
"""

from __future__ import annotations

import json

import pytest
import rasterio

from sentinela.config import SETTINGS
from sentinela.gee.harmonizacao import bandas_harmonizadas
from sentinela.gee.sentinel2 import _site_por_id, calcular_grade, processar_site_ano

SITES = ["ascenty-vinhedo", "odata-hortolandia", "scala-tambore"]
ANOS_S2 = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

_LON, _LAT, _BUFFER_KM = -47.0118926, -23.0700044, 5.0  # ascenty-vinhedo, config/sites.geojson


def _tif_path(site_id: str, ano: int):
    return SETTINGS.raw_dir / "s2" / site_id / f"{ano}.tif"


def _manifest_path(site_id: str, ano: int):
    return SETTINGS.manifests_dir / f"s2_{site_id}_{ano}.json"


# --------------------------------------------------------------------------------------------
# Grade — puramente matemático, sem EE.
# --------------------------------------------------------------------------------------------


def test_grade_origem_e_extensao_multiplas_de_30():
    grade = calcular_grade(_LON, _LAT, _BUFFER_KM)
    assert grade["origin_x"] % 30 == 0
    assert grade["origin_y"] % 30 == 0
    assert grade["largura_m"] % 30 == 0
    assert grade["altura_m"] % 30 == 0


def test_grade_width_height_10m_e_multiplo_exato_de_30m():
    grade10 = calcular_grade(_LON, _LAT, _BUFFER_KM, resolucao_m=10)
    grade30 = calcular_grade(_LON, _LAT, _BUFFER_KM, resolucao_m=30)
    assert grade10["width"] == grade30["width"] * 3
    assert grade10["height"] == grade30["height"] * 3
    assert isinstance(grade10["width"], int) and isinstance(grade10["height"], int)


def test_grade_origem_independe_da_resolucao_pedida():
    # Garante o alinhamento entre a grade de 10 m (SV-06) e a de 30 m (SV-06b) SEM precisar
    # combinar ao vivo: a origem só depende do bbox do site (config/sites.geojson), não de
    # `resolucao_m` — condição exigida pelos critérios de aceite de SV-06/SV-06b.
    grade10 = calcular_grade(_LON, _LAT, _BUFFER_KM, resolucao_m=10)
    grade30 = calcular_grade(_LON, _LAT, _BUFFER_KM, resolucao_m=30)
    assert grade10["origin_x"] == grade30["origin_x"]
    assert grade10["origin_y"] == grade30["origin_y"]
    assert (grade10["origin_x"] - grade30["origin_x"]) % 30 == 0
    assert (grade10["origin_y"] - grade30["origin_y"]) % 30 == 0


def test_grade_e_deterministica():
    a = calcular_grade(_LON, _LAT, _BUFFER_KM)
    b = calcular_grade(_LON, _LAT, _BUFFER_KM)
    assert a == b


def test_grade_nao_depende_de_earth_engine():
    # calcular_grade não deve importar/usar `ee` — checagem estrutural simples.
    import inspect

    import sentinela.gee.sentinel2 as mod

    fonte = inspect.getsource(mod.calcular_grade)
    assert "ee." not in fonte


# --------------------------------------------------------------------------------------------
# Idempotência — não precisa de EE (caminho "já existe" é resolvido antes de qualquer chamada).
# --------------------------------------------------------------------------------------------


def test_idempotencia_pula_sem_chamar_earth_engine():
    site_id, ano = "ascenty-vinhedo", 2024
    tif_path = _tif_path(site_id, ano)
    manifest_path = _manifest_path(site_id, ano)
    if not (tif_path.exists() and manifest_path.exists()):
        pytest.skip(f"{tif_path} não existe — rode a ingestão SV-06 antes deste teste.")

    mtime_antes = tif_path.stat().st_mtime
    site = _site_por_id(site_id)
    resultado = processar_site_ano(site, ano, force=False)

    assert tif_path.stat().st_mtime == mtime_antes, "não deveria ter regravado o .tif sem --force"
    assert resultado["site_id"] == site_id
    assert resultado["ano"] == ano


# --------------------------------------------------------------------------------------------
# Arquivos gerados pela ingestão real (skip individual se o par site/ano não existir).
# --------------------------------------------------------------------------------------------

_TODOS_SITE_ANO = [(s, a) for s in SITES for a in ANOS_S2]


@pytest.mark.parametrize("site_id,ano", _TODOS_SITE_ANO)
def test_tif_tem_bandas_canonicas_int16_10m_epsg31983(site_id, ano):
    tif_path = _tif_path(site_id, ano)
    if not tif_path.exists():
        pytest.skip(f"{tif_path} não existe — rode a ingestão SV-06 antes deste teste.")

    with rasterio.open(tif_path) as ds:
        assert ds.count == len(bandas_harmonizadas()) == 6
        assert list(ds.descriptions) == bandas_harmonizadas()
        assert all(dt == "int16" for dt in ds.dtypes)
        assert str(ds.crs) == "EPSG:31983"
        assert abs(ds.transform.a) == 10
        assert abs(ds.transform.e) == 10
        assert ds.nodata == -9999
        # origem múltipla de 30 (regra de coordenação de grade com SV-06b)
        assert ds.transform.c % 30 == 0
        assert ds.transform.f % 30 == 0


@pytest.mark.parametrize("site_id,ano", _TODOS_SITE_ANO)
def test_manifest_contrato_e_sha256(site_id, ano):
    tif_path = _tif_path(site_id, ano)
    manifest_path = _manifest_path(site_id, ano)
    if not (tif_path.exists() and manifest_path.exists()):
        pytest.skip(f"{manifest_path} não existe — rode a ingestão SV-06 antes deste teste.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["bandas"] == bandas_harmonizadas()
    assert manifest["site_id"] == site_id
    assert manifest["ano"] == ano
    assert manifest["sensor"] == "sentinel2"
    assert manifest["resolucao_m"] == 10
    assert manifest["nodata"] == -9999
    assert manifest["fator_escala"] == 10000
    assert manifest["crs"] == "EPSG:31983"
    assert manifest["sha256"]

    import hashlib

    h = hashlib.sha256(tif_path.read_bytes()).hexdigest()
    assert manifest["sha256"] == h, "sha256 do manifest não bate com o arquivo .tif atual"


def test_todos_os_anos_do_mesmo_site_tem_grade_identica():
    if not any(len([a for a in ANOS_S2 if _tif_path(s, a).exists()]) >= 2 for s in SITES):
        pytest.skip("nenhum site tem >= 2 anos gerados — rode a ingestão SV-06 antes deste teste.")

    for site_id in SITES:
        anos_presentes = [a for a in ANOS_S2 if _tif_path(site_id, a).exists()]
        if len(anos_presentes) < 2:
            continue
        transforms = set()
        shapes = set()
        for ano in anos_presentes:
            with rasterio.open(_tif_path(site_id, ano)) as ds:
                transforms.add(ds.transform)
                shapes.add((ds.width, ds.height))
        assert len(transforms) == 1, f"{site_id}: transform difere entre anos {anos_presentes}"
        assert len(shapes) == 1, f"{site_id}: shape difere entre anos {anos_presentes}"


def test_pct_pixels_validos_ok_ou_justificado():
    algum_manifest = False
    for site_id in SITES:
        for ano in ANOS_S2:
            manifest_path = _manifest_path(site_id, ano)
            if not manifest_path.exists():
                continue
            algum_manifest = True
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pct = manifest["pct_pixels_validos"]
            # Critério de aceite: >=90% OU a janela já foi ampliada (desvio conhecido/justificado).
            assert pct >= 90.0 or manifest["janela"]["ampliada"], (
                f"{site_id}/{ano}: pct_pixels_validos={pct}% < 90% e a janela NÃO foi ampliada "
                "-- deveria ter tentado ampliar antes de gravar."
            )
    if not algum_manifest:
        pytest.skip("nenhum manifest encontrado — rode a ingestão SV-06 antes deste teste.")


def test_sanidade_fisica_red_baixo_nir_alto_sobre_vegetacao():
    algum_manifest = False
    for site_id in SITES:
        for ano in ANOS_S2:
            manifest_path = _manifest_path(site_id, ano)
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            sanidade = manifest.get("sanidade_fisica") or {}
            red = sanidade.get("red_mediana_vegetacao")
            nir = sanidade.get("nir_mediana_vegetacao")
            if red is None or nir is None:
                continue  # sem pixel de vegetação suficiente nesse site/ano — não é uma falha
            algum_manifest = True
            assert red < 0.1, f"{site_id}/{ano}: red mediano sobre vegetação = {red} (esperado < 0.1)"
            assert nir > 0.2, f"{site_id}/{ano}: nir mediano sobre vegetação = {nir} (esperado > 0.2)"
    if not algum_manifest:
        pytest.skip("nenhum manifest com sanidade física calculada — rode a ingestão SV-06 antes.")
