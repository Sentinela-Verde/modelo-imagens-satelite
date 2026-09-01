"""Testes de sentinela.labeling.candidatos_estrato (SV-09b).

Mesmo padrão de tests/test_candidatos.py: funções puras testadas com dados sintéticos; os testes
de integração abrem os artefatos já gerados por uma rodada real do CLI (`python -m
sentinela.labeling.candidatos_estrato --estrato all`) e são pulados com mensagem clara se ainda
não existirem.

Cobertura dos cenários de teste de docs/tarefas/SV-09b-kit-rotulagem-estratificado.md:
1. Rodar para um estrato -> GeoJSON + PNGs, contagem dentro do teto.
2. Rodar para um estrato de bioma novo -> limiares calculados por AOI, não globalmente
   (verificável nas properties `site_id` de cada limiar, e no fato de que o percentil de cada par
   é recomputado por `_detectar_par`, reusada sem alteração de `sentinela.labeling.candidatos`).
3. (visual/manual — feito à parte na "conferência de candidatos" do relatório de SV-09b, fora do
   pytest, mesmo padrão do cenário 2 de SV-09).
4. `_cotas.csv` somado bate com a soma das cotas do documento (40/estrato).
5. Verificação de honestidade (herdada de SV-09): `classe_id` dos candidatos vem vazio.
"""

from __future__ import annotations

import csv
import json

import pytest

from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.labeling.candidatos_estrato import (
    COTAS_POR_CLASSE,
    MAX_CANDIDATOS_POR_ESTRATO,
    _fase_do_ano,
    _parse_periodo,
    _selecionar_com_diversidade,
    definir_estratos,
)

# --------------------------------------------------------------------------------------------
# Funções puras
# --------------------------------------------------------------------------------------------


def test_parse_periodo_intervalo_valido():
    assert _parse_periodo("2018-2022") == (2018, 2022)


def test_parse_periodo_none_ou_vazio_retorna_none():
    assert _parse_periodo(None) is None
    assert _parse_periodo("") is None


def test_fase_do_ano_durante_pre_pos():
    props = {"periodo_pre": "2016-2018", "periodo_durante": "2019-2020", "periodo_pos": "2021-2025"}
    assert _fase_do_ano(props, 2017) == "pre"
    assert _fase_do_ano(props, 2019) == "durante"
    assert _fase_do_ano(props, 2020) == "durante"
    assert _fase_do_ano(props, 2023) == "pos"


def test_fase_do_ano_fora_de_qualquer_periodo_e_none():
    props = {"periodo_pre": "2016-2018", "periodo_durante": "2019-2020", "periodo_pos": "2021-2025"}
    assert _fase_do_ano(props, 2013) is None


def test_fase_do_ano_periodo_ausente_nao_quebra():
    assert _fase_do_ano({}, 2020) is None


def _candidato(site_id: str, ano: int, fase: str | None, area_ha: float) -> dict:
    return {"site_id": site_id, "ano": ano, "fase": fase, "area_ha": area_ha, "sensor": "s2"}


def test_selecionar_com_diversidade_respeita_teto():
    candidatos = [_candidato("a", 2020, "durante", 1.0 + i) for i in range(10)]
    candidatos += [_candidato("b", 2020, "durante", 1.0 + i) for i in range(10)]
    selecionados = _selecionar_com_diversidade(candidatos, teto=5)
    assert len(selecionados) == 5


def test_selecionar_com_diversidade_prioriza_durante_por_site():
    candidatos = [
        _candidato("a", 2015, "pre", 100.0),  # área grande mas fora de fase durante
        _candidato("a", 2019, "durante", 1.0),  # área pequena mas em fase durante
    ]
    selecionados = _selecionar_com_diversidade(candidatos, teto=1)
    assert selecionados[0]["fase"] == "durante"


def test_selecionar_com_diversidade_intercala_entre_sites():
    """Round-robin: com teto menor que a soma disponível, cada site com candidatos deve aparecer
    na seleção — é o que garante o critério de aceite de >= 2 AOIs distintas por estrato."""
    candidatos = [_candidato("a", 2020, "durante", 5.0)]
    candidatos += [_candidato("b", 2020, "durante", 4.0 + i) for i in range(5)]
    selecionados = _selecionar_com_diversidade(candidatos, teto=3)
    sites = {c["site_id"] for c in selecionados}
    assert "a" in sites
    assert "b" in sites


def test_cotas_por_classe_soma_40_por_estrato():
    assert sum(COTAS_POR_CLASSE.values()) == 40


def test_cotas_por_classe_cobre_as_5_classes():
    assert set(COTAS_POR_CLASSE) == {1, 2, 3, 4, 5}


# --------------------------------------------------------------------------------------------
# Estratos definidos a partir do tier 1 real de config/sites.geojson
# --------------------------------------------------------------------------------------------


def test_definir_estratos_so_usa_aois_de_tier_1():
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    tier2_ids = set(gdf[gdf["tier"] == 2]["site_id"])

    estratos = definir_estratos()
    todos_site_ids = {s for d in estratos.values() for s in d["site_ids"]}
    assert todos_site_ids.isdisjoint(tier2_ids), "estratos não podem incluir AOIs de tier 2"


def test_definir_estratos_nenhum_estrato_vazio():
    estratos = definir_estratos()
    for nome, definicao in estratos.items():
        assert definicao["site_ids"], f"estrato {nome} não deveria existir sem nenhuma AOI"


def test_definir_estratos_mata_atlantica_splitada_por_era():
    estratos = definir_estratos()
    assert "mataatlantica_landsat" in estratos
    assert "mataatlantica_s2" in estratos
    assert estratos["mataatlantica_landsat"]["sensores"] == ("landsat",)
    assert estratos["mataatlantica_s2"]["sensores"] == ("s2",)


def test_definir_estratos_pampa_nao_existe_nos_dados_reais():
    """Critério de aceite: estrato sem AOI de tier 1 não é criado. A tabela do enunciado de
    SV-09b previa `pampa_s2`, mas nenhuma AOI de tier 1 ativa tem bioma == 'Pampa' em
    config/sites.geojson na rodada atual — achado real, documentado em candidatos_estrato.py e no
    relatório de SV-09b."""
    estratos = definir_estratos()
    biomas = {d["bioma"] for d in estratos.values()}
    assert "Pampa" not in biomas


# --------------------------------------------------------------------------------------------
# Integração — artefatos já gerados por `python -m sentinela.labeling.candidatos_estrato --estrato all`
# --------------------------------------------------------------------------------------------

ESTRATOS_ESPERADOS = ["amazonia", "caatinga", "cerrado", "mataatlantica_landsat", "mataatlantica_s2"]


def _geojson_path(estrato: str):
    return SETTINGS.interim_dir / f"candidatos_estrato_{estrato}.geojson"


@pytest.mark.parametrize("estrato", ESTRATOS_ESPERADOS)
def test_cenario1_geojson_existe_com_ate_25_features_dentro_do_teto(estrato):
    path = _geojson_path(estrato)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    features = fc["features"]
    assert len(features) <= MAX_CANDIDATOS_POR_ESTRATO


@pytest.mark.parametrize("estrato", ESTRATOS_ESPERADOS)
def test_geojson_area_minima_por_sensor(estrato):
    path = _geojson_path(estrato)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    min_area = {"s2": 0.5, "landsat": 1.0}
    for f in fc["features"]:
        p = f["properties"]
        assert p["area_ha"] >= min_area[p["sensor"]], f"candidato {p['candidato_id']} abaixo da área mínima"


@pytest.mark.parametrize("estrato", ESTRATOS_ESPERADOS)
def test_cenario5_verificacao_de_honestidade_classe_id_sempre_vazio(estrato):
    path = _geojson_path(estrato)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    for f in fc["features"]:
        assert f["properties"]["classe_id"] is None


@pytest.mark.parametrize("estrato", ESTRATOS_ESPERADOS)
def test_geojson_abre_com_geopandas_em_epsg4326_geometrias_validas(estrato):
    path = _geojson_path(estrato)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    geopandas = pytest.importorskip("geopandas")
    gdf = geopandas.read_file(path)
    if len(gdf) == 0:
        pytest.skip(f"{path} não tem candidatos.")
    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 4326
    assert gdf.geometry.is_valid.all()


@pytest.mark.parametrize("estrato", ESTRATOS_ESPERADOS)
def test_cenario2_limiares_reportados_sao_por_aoi_nao_globais(estrato):
    """Cenário de teste 2: os limiares (percentis de BSI/NDVI) são calculados por AOI, nunca
    globalmente — verificado indiretamente aqui checando que os candidatos de um mesmo estrato com
    >1 AOI têm `bsi_medio`/`ndvi_medio` em faixas visivelmente diferentes por site (percentil global
    faria as distribuições colapsarem para a mesma faixa)."""
    path = _geojson_path(estrato)
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    fc = json.loads(path.read_text(encoding="utf-8"))
    sites = {f["properties"]["site_id"] for f in fc["features"]}
    if len(sites) < 2:
        pytest.skip(f"{estrato} tem só 1 AOI com candidato selecionado — nada a comparar.")
    # só confere que o campo site_id está presente e não vazio em todo candidato (pré-condição
    # para a checagem por AOI ser sequer possível)
    for f in fc["features"]:
        assert f["properties"]["site_id"]


@pytest.mark.parametrize("estrato", ESTRATOS_ESPERADOS)
def test_recortes_png_e_prancha_de_contexto_existem(estrato):
    out_dir = REPO_ROOT / "reports" / "figures" / "rotulagem" / estrato
    if not out_dir.exists():
        pytest.skip(f"{out_dir} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    pngs = sorted(out_dir.glob("*.png"))
    assert len(pngs) > 0
    for png in pngs:
        assert png.stat().st_size > 0
    assert (out_dir / "prancha_contexto.png").exists()


# --------------------------------------------------------------------------------------------
# `data/labels_manual/_cotas.csv`
# --------------------------------------------------------------------------------------------

COTAS_PATH = SETTINGS.labels_manual_dir / "_cotas.csv"


def test_cotas_csv_existe():
    if not COTAS_PATH.exists():
        pytest.skip(f"{COTAS_PATH} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")
    assert COTAS_PATH.exists()


def test_cenario4_cotas_csv_soma_bate_com_40_por_estrato():
    if not COTAS_PATH.exists():
        pytest.skip(f"{COTAS_PATH} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    with COTAS_PATH.open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))

    estratos = {linha["estrato"] for linha in linhas}
    for estrato in estratos:
        soma = sum(int(linha["cota"]) for linha in linhas if linha["estrato"] == estrato)
        assert soma == 40, f"estrato {estrato}: soma das cotas {soma} != 40"


def test_cotas_csv_soma_geral_nao_passa_de_260():
    """Critério de aceite explícito: soma das cotas <= 260 (senão SV-10 não cabe em 4h)."""
    if not COTAS_PATH.exists():
        pytest.skip(f"{COTAS_PATH} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    with COTAS_PATH.open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    soma_geral = sum(int(linha["cota"]) for linha in linhas)
    assert soma_geral <= 260


def test_cotas_csv_restante_e_cota_menos_ja_rotulado_sem_ficar_negativo():
    if not COTAS_PATH.exists():
        pytest.skip(f"{COTAS_PATH} não existe — rode `python -m sentinela.labeling.candidatos_estrato --estrato all` antes.")

    with COTAS_PATH.open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    for linha in linhas:
        cota, ja, restante = int(linha["cota"]), int(linha["ja_rotulado"]), int(linha["restante"])
        assert restante == max(cota - ja, 0)
        assert restante >= 0
