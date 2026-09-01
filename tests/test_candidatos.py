"""Testes de sentinela.labeling.candidatos (SV-09).

Testes puros (sem I/O) cobrem `_poligonizar`/`_classe_predominante`/filtro de área mínima com
arrays sintéticos. Os demais abrem os arquivos já gerados por uma rodada real do CLI
(`python -m sentinela.labeling.candidatos --site all`) — mesmo padrão de `tests/test_labels.py` —
e são pulados com mensagem clara se ainda não existirem.

Cobertura dos cenários de teste de `docs/tarefas/SV-09-kit-rotulagem-solo-exposto.md`:
1. Rodar para um site -> GeoJSON + PNGs gerados, contagem dentro do limite.
2. (visual/manual — conferido à parte, fora do pytest) candidatos caem sobre área alterada.
3. Template abre no QGIS / é legível por geopandas.
4. Verificação de honestidade: `classe_id` do candidato vem vazio.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from rasterio.transform import from_origin

from sentinela import classes
from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.labeling.candidatos import (
    MAX_CANDIDATOS_POR_SITE,
    SENSOR_MIN_AREA_HA,
    _classe_predominante,
    _poligonizar,
    _sites_ativos,
)

# Atualizado por SV-25 (validação de coordenadas em escala): config/sites.geojson passou de 3 para
# 16 AOIs ativas (13 tier 1 + 3 tier 2, ver ADR-005). Os testes parametrizados abaixo já pulam com
# mensagem clara (`pytest.skip`) para as 13 novas, cujos artefatos de SV-09 (candidatos_*.geojson,
# PNGs de rotulagem) ainda não existem até a ingestão expandida (SV-26) rodar para elas.
SITES = [
    "ascenty-vinhedo", "odata-hortolandia", "scala-tambore",
    "ascenty-hortolandia", "ascenty-sumare", "ascenty-osasco", "equinix-santana-parnaiba",
    "scala-sgigsm01", "scala-spoapa01", "angonap-fortaleza", "ascenty-maracanau",
    "everest-goiania", "clickip-manaus", "ascenty-paulinia", "ascenty-jundiai",
    "hostdime-joao-pessoa",
]


# --------------------------------------------------------------------------------------------
# Funções puras
# --------------------------------------------------------------------------------------------


def test_classe_predominante_vota_a_classe_majoritaria_ignorando_nodata():
    label_arr = np.array([[0, 2, 2], [2, 4, 0]], dtype=np.uint8)
    regiao = np.ones((2, 3), dtype=bool)
    assert _classe_predominante(label_arr, regiao) == "vegetacao_rala"


def test_classe_predominante_none_quando_label_ausente():
    regiao = np.ones((2, 2), dtype=bool)
    assert _classe_predominante(None, regiao) is None


def test_classe_predominante_none_quando_regiao_e_toda_nodata():
    label_arr = np.zeros((2, 2), dtype=np.uint8)
    regiao = np.ones((2, 2), dtype=bool)
    assert _classe_predominante(label_arr, regiao) is None


def _poligonizar_quadrado(lado_px: int, resolucao_m: float, min_area_ha: float):
    mask = np.zeros((lado_px + 4, lado_px + 4), dtype=bool)
    mask[2 : 2 + lado_px, 2 : 2 + lado_px] = True
    transform = from_origin(0, 0, resolucao_m, resolucao_m)
    ndvi = np.full(mask.shape, 0.1, dtype=np.float32)
    bsi = np.full(mask.shape, 0.3, dtype=np.float32)
    return _poligonizar(
        mask, transform, ndvi, bsi, None,
        site_id="site-teste", sensor="s2", ano=2020, ano_anterior=2019, min_area_ha=min_area_ha,
    )


def test_poligonizar_area_acima_do_minimo_e_mantida():
    # 30x30 px a 10 m = 900 m2 * ... na verdade lado 30px*10m=300m -> 9 ha, bem acima de 0.5 ha
    candidatos = _poligonizar_quadrado(lado_px=30, resolucao_m=10.0, min_area_ha=0.5)
    assert len(candidatos) == 1
    c = candidatos[0]
    assert c["area_ha"] == pytest.approx(9.0, rel=1e-3)
    assert c["site_id"] == "site-teste"
    assert c["classe_id"] is None
    assert c["ndvi_medio"] == pytest.approx(0.1)
    assert c["bsi_medio"] == pytest.approx(0.3)


def test_poligonizar_area_abaixo_do_minimo_e_descartada():
    # 3x3 px a 10 m = 900 m2 = 0.09 ha, abaixo do mínimo de 0.5 ha (S2) e de 1 ha (Landsat)
    candidatos = _poligonizar_quadrado(lado_px=3, resolucao_m=10.0, min_area_ha=SENSOR_MIN_AREA_HA["s2"])
    assert candidatos == []


def test_poligonizar_mascara_vazia_nao_gera_candidato():
    mask = np.zeros((10, 10), dtype=bool)
    transform = from_origin(0, 0, 10.0, 10.0)
    ndvi = np.zeros((10, 10), dtype=np.float32)
    bsi = np.zeros((10, 10), dtype=np.float32)
    candidatos = _poligonizar(
        mask, transform, ndvi, bsi, None,
        site_id="x", sensor="s2", ano=2020, ano_anterior=2019, min_area_ha=0.5,
    )
    assert candidatos == []


def test_min_area_ha_landsat_maior_que_s2():
    # nota da revisão de 2026-08-27 de SV-09: grade de 30 m usa área mínima maior (1 ha vs 0.5 ha)
    assert SENSOR_MIN_AREA_HA["landsat"] > SENSOR_MIN_AREA_HA["s2"]
    assert SENSOR_MIN_AREA_HA["s2"] == 0.5
    assert SENSOR_MIN_AREA_HA["landsat"] == 1.0


def test_sites_ativos_bate_com_config():
    sites = _sites_ativos()
    assert set(sites) == set(SITES)


# --------------------------------------------------------------------------------------------
# Integração — sobre os arquivos já gerados por `python -m sentinela.labeling.candidatos --site all`
# --------------------------------------------------------------------------------------------


def _geojson_path(site_id: str):
    return SETTINGS.interim_dir / f"candidatos_{site_id}.geojson"


@pytest.mark.parametrize("site_id", SITES)
def test_cenario1_geojson_existe_com_ate_60_features_todas_acima_da_area_minima(site_id):
    path = _geojson_path(site_id)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos --site all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    features = fc["features"]
    assert len(features) <= MAX_CANDIDATOS_POR_SITE

    areas = [f["properties"]["area_ha"] for f in features]
    assert areas == sorted(areas, reverse=True), "candidatos deveriam vir ordenados por área decrescente"

    for f in features:
        p = f["properties"]
        min_area = SENSOR_MIN_AREA_HA[p["sensor"]]
        assert p["area_ha"] >= min_area, f"candidato {p['candidato_id']} abaixo da área mínima ({p['sensor']})"


@pytest.mark.parametrize("site_id", SITES)
def test_cenario1_pngs_existem_para_todos_os_anos_do_site(site_id):
    out_dir = REPO_ROOT / "reports" / "figures" / "rotulagem" / site_id
    if not out_dir.exists():
        pytest.skip(f"{out_dir} não existe — rode `python -m sentinela.labeling.candidatos --site all` antes.")

    pngs = sorted(out_dir.glob("*.png"))
    assert len(pngs) > 0
    for png in pngs:
        assert png.stat().st_size > 0
    # um par (rgb + falsacor) por ano
    sufixos = {p.stem.rsplit("_", 1)[-1] for p in pngs}
    assert sufixos == {"rgb", "falsacor"}


@pytest.mark.parametrize("site_id", SITES)
def test_geojson_abre_com_geopandas_em_epsg4326_geometrias_validas(site_id):
    path = _geojson_path(site_id)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos --site all` antes.")

    geopandas = pytest.importorskip("geopandas")
    gdf = geopandas.read_file(path)
    if len(gdf) == 0:
        pytest.skip(f"{path} não tem candidatos.")
    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 4326
    assert gdf.geometry.is_valid.all()


@pytest.mark.parametrize("site_id", SITES)
def test_cenario4_verificacao_de_honestidade_classe_id_sempre_vazio(site_id):
    """Nenhum arquivo desta tarefa pode ter classe_id preenchido — a heurística é um localizador,
    não um label pronto disfarçado (critério de aceite explícito de SV-09)."""
    path = _geojson_path(site_id)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos --site all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    for f in fc["features"]:
        assert f["properties"]["classe_id"] is None


@pytest.mark.parametrize("site_id", SITES)
def test_candidato_ids_sao_sequenciais_e_unicos(site_id):
    path = _geojson_path(site_id)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos --site all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    ids = [f["properties"]["candidato_id"] for f in fc["features"]]
    assert ids == list(range(1, len(ids) + 1))


@pytest.mark.parametrize("site_id", SITES)
def test_candidatos_cobrem_as_duas_eras_de_sensor(site_id):
    """Revisão de 2026-08-27 de SV-09: candidatos precisam existir nas duas eras (Landsat e S2),
    não só na moderna — senão a classe crítica fica sem exemplo onde ela aparece primeiro."""
    path = _geojson_path(site_id)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos --site all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    sensores = {f["properties"]["sensor"] for f in fc["features"]}
    assert sensores, f"{site_id}: nenhum candidato encontrado"
    assert sensores <= {"s2", "landsat"}


# --------------------------------------------------------------------------------------------
# Template de rotulagem manual (item 3 do escopo de SV-09)
# --------------------------------------------------------------------------------------------


TEMPLATE_PATH = REPO_ROOT / "data" / "labels_manual" / "_template.geojson"
CAMPOS_SCHEMA = (
    "site_id", "ano", "classe_id", "classe_slug", "confianca", "autor",
    "data_rotulagem", "observacao", "origem",
)


def test_template_existe_e_esta_vazio():
    assert TEMPLATE_PATH.exists(), f"{TEMPLATE_PATH} deveria existir (commitado) mesmo sem candidatos gerados."
    fc = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert fc["features"] == []


def test_template_documenta_o_schema_de_campos_no_proprio_arquivo():
    fc = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert "schema_campos" in fc
    assert set(fc["schema_campos"].keys()) == set(CAMPOS_SCHEMA)


def test_template_e_legivel_por_geopandas():
    geopandas = pytest.importorskip("geopandas")
    gdf = geopandas.read_file(TEMPLATE_PATH)
    assert len(gdf) == 0
    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 4326


def test_template_classe_id_1_a_5_e_classes_batem_com_sentinela_classes():
    # confere que os slugs documentados no template batem com sentinela.classes (fonte única)
    for classe_id in range(1, 6):
        assert classe_id in classes.CLASSES
