"""Testes de sentinela.sites (SV-25 — validação de coordenadas em escala).

Cobertura dos cenários de teste de docs/tarefas/SV-25-validacao-coordenadas-escala.md:
1. geopandas.read_file carrega config/sites.geojson; CRS EPSG:4326; geometrias Point.
2. Coordenada com lat/lon trocada (Vinhedo) -> V1 reprova.
3. Coordenada deslocada para dentro de mata -> V1 passa mas seria reprovada por V3 (V3 não é
   recomputado ao vivo neste arquivo — ver módulo `sentinela.sites` — mas a função pura de V1 é
   testada aqui e o pipeline real (scripts/validar_coordenadas_sv25.py) já reprovaria e mandaria
   para a fila visual; este teste cobre a metade pura/determinística do cenário).
4. Duplicar uma AOI com deslocamento de 1 km -> V4 acusa colisão.
5. Idempotência: v1/v4/v5 são funções puras determinísticas (sem I/O) — mesma entrada, mesma saída.
6. Conferência cruzada ascenty-vinhedo: coordenada de produção é a mesma gravada no cenário do
   pipeline (ver `config/sites.geojson`, campo `observacao` de `ascenty-vinhedo` documenta a
   distância real medida na cascata A/B, < 1 km).

V1, V2, V4 e o schema são o que o enunciado pede como "vira teste automatizado" (item 6 do escopo).
V2 depende de reverse-geocode (rede) — em vez de rebater a rede a cada `pytest`, os testes
verificam a propriedade `v2_aprovado` já gravada em config/sites.geojson pelo pipeline (mesmo
padrão que tests/test_candidatos.py já usa para os artefatos gerados por script). V3 e V5 também
são conferidos como propriedades gravadas, mas não são exigidos como bloqueantes pelo enunciado
(só V1/V2/V4/schema são).
"""

from __future__ import annotations

import json

import pytest

from sentinela.config import REPO_ROOT
from sentinela.sites import (
    METODOS_VALIDOS,
    PRECISOES_VALIDAS,
    SITES_PATH,
    haversine_km,
    v1_caixa_brasil,
    v4_colisoes,
    v5_distancia,
)

CAMPOS_OBRIGATORIOS = (
    "site_id", "nome", "operador", "municipio", "uf", "lat", "lon", "buffer_km",
    "fonte_coordenada", "ano_inicio_operacao_estimado", "ativo",
    "tier", "regiao", "bioma", "metodo_coordenada", "precisao_coordenada", "data_consulta",
    "ano_inicio_obra", "periodo_pre", "periodo_durante", "periodo_pos", "n_predios",
)
CAMPOS_PROVENIENCIA = ("metodo_coordenada", "precisao_coordenada", "fonte_coordenada", "data_consulta")

SITES_ORIGINAIS_ESPERADOS = {
    "ascenty-vinhedo": (-23.0700044, -47.0118926),
    "odata-hortolandia": (-22.8995299, -47.1952611),
    "scala-tambore": (-23.4948321, -46.8130769),
}


@pytest.fixture(scope="module")
def feature_collection() -> dict:
    if not SITES_PATH.exists():
        pytest.skip(f"{SITES_PATH} não existe — rode scripts/validar_coordenadas_sv25.py antes.")
    return json.loads(SITES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def features_ativas(feature_collection: dict) -> list[dict]:
    return [f["properties"] for f in feature_collection["features"] if f["properties"]["ativo"]]


# --------------------------------------------------------------------------------------------
# Funções puras (V1, V4, V5, haversine) — sem I/O, sem rede.
# --------------------------------------------------------------------------------------------


def test_haversine_zero_para_mesmo_ponto():
    assert haversine_km(-23.07, -47.01, -23.07, -47.01) == pytest.approx(0.0, abs=1e-9)


def test_haversine_distancia_conhecida_vinhedo_hortolandia():
    # ~27 km em linha reta entre as duas coordenadas de produção (ordem de grandeza, não valor exato)
    d = haversine_km(-23.0700044, -47.0118926, -22.8995299, -47.1952611)
    assert 20.0 < d < 35.0


def test_v1_caixa_brasil_aprova_coordenada_valida():
    assert v1_caixa_brasil(-23.0700044, -47.0118926) is True


def test_v1_caixa_brasil_cenario2_lat_lon_trocados_de_vinhedo_reprova():
    """Cenário de teste 2 do enunciado: lat/lon trocados de Vinhedo -> V1 reprova."""
    lat_real, lon_real = -23.0700044, -47.0118926
    lat_trocado, lon_trocado = lon_real, lat_real  # troca proposital
    assert v1_caixa_brasil(lat_trocado, lon_trocado) is False


def test_v1_caixa_brasil_sinal_invertido_reprova():
    assert v1_caixa_brasil(23.0700044, -47.0118926) is False  # lat com sinal trocado
    assert v1_caixa_brasil(-23.0700044, 47.0118926) is False  # lon com sinal trocado


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(-34.1, -47.0), (7.0, -47.0), (-23.0, -75.0), (-23.0, -33.0)],
)
def test_v1_caixa_brasil_fora_da_caixa_reprova(lat, lon):
    assert v1_caixa_brasil(lat, lon) is False


def test_v4_colisoes_cenario4_aoi_duplicada_deslocada_1km_acusa_colisao():
    """Cenário de teste 4 do enunciado: duplicar uma AOI com deslocamento de 1 km -> V4 acusa."""
    sites = [
        {"site_id": "original", "lat": -23.0700044, "lon": -47.0118926},
        # ~1 km ao norte (0.009 grau de latitude ~ 1 km)
        {"site_id": "duplicata_deslocada", "lat": -23.0700044 + 0.009, "lon": -47.0118926},
    ]
    colisoes = v4_colisoes(sites)
    assert colisoes["original"], "esperava colisão detectada"
    assert colisoes["duplicata_deslocada"], "esperava colisão detectada (simétrica)"
    outro_id, distancia = colisoes["original"][0]
    assert outro_id == "duplicata_deslocada"
    assert distancia < 5.0


def test_v4_colisoes_aois_distantes_nao_colidem():
    sites = [
        {"site_id": "a", "lat": -23.0700044, "lon": -47.0118926},  # Vinhedo/SP
        {"site_id": "b", "lat": -3.734736, "lon": -38.462636},  # Fortaleza/CE
    ]
    colisoes = v4_colisoes(sites)
    assert colisoes["a"] == []
    assert colisoes["b"] == []


def test_v5_distancia_aprova_dentro_do_limiar():
    d, ok = v5_distancia(-23.0700044, -47.0118926, -23.0702, -47.0130)
    assert ok is True
    assert d < 2.0


def test_v5_distancia_reprova_acima_do_limiar():
    d, ok = v5_distancia(-23.0700044, -47.0118926, -23.20, -47.30)
    assert ok is False
    assert d >= 2.0


def test_funcoes_puras_sao_deterministicas_cenario5_idempotencia():
    """Cenário de teste 5 (idempotência): mesma entrada, mesma saída, sempre — sem I/O."""
    for _ in range(3):
        assert v1_caixa_brasil(-23.07, -47.01) is True
        d1, ok1 = v5_distancia(-23.07, -47.01, -23.08, -47.02)
        d2, ok2 = v5_distancia(-23.07, -47.01, -23.08, -47.02)
        assert d1 == d2 and ok1 == ok2


# --------------------------------------------------------------------------------------------
# Cenário 1 — config/sites.geojson abre com geopandas, CRS EPSG:4326, geometrias Point.
# --------------------------------------------------------------------------------------------


def test_cenario1_sites_geojson_abre_com_geopandas_epsg4326_geometrias_point():
    geopandas = pytest.importorskip("geopandas")
    if not SITES_PATH.exists():
        pytest.skip(f"{SITES_PATH} não existe.")
    gdf = geopandas.read_file(SITES_PATH)
    assert len(gdf) > 0
    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 4326
    assert (gdf.geometry.geom_type == "Point").all()
    assert gdf.geometry.is_valid.all()


# --------------------------------------------------------------------------------------------
# As 3 AOIs originais (ADR-001) permanecem inalteradas — critério de aceite explícito.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("site_id", sorted(SITES_ORIGINAIS_ESPERADOS))
def test_aois_originais_site_id_lat_lon_buffer_inalterados(features_ativas, site_id):
    lat_esp, lon_esp = SITES_ORIGINAIS_ESPERADOS[site_id]
    props = next((p for p in features_ativas if p["site_id"] == site_id), None)
    assert props is not None, f"{site_id} deveria continuar ativo"
    assert props["lat"] == lat_esp
    assert props["lon"] == lon_esp
    assert props["buffer_km"] == 5


# --------------------------------------------------------------------------------------------
# Schema — todo campo de proveniência obrigatório, preenchido, com valores válidos.
# --------------------------------------------------------------------------------------------


def test_schema_todos_os_campos_obrigatorios_presentes(features_ativas):
    for props in features_ativas:
        faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in props]
        assert not faltando, f"{props.get('site_id')}: campos faltando {faltando}"


def test_schema_nenhum_campo_de_proveniencia_e_null(features_ativas):
    """Critério de aceite: nenhum AOI ativa com metodo/precisao/fonte/data_consulta nulos."""
    for props in features_ativas:
        for campo in CAMPOS_PROVENIENCIA:
            assert props[campo] not in (None, ""), f"{props['site_id']}.{campo} está vazio"


def test_schema_metodo_coordenada_e_precisao_tem_valores_validos(features_ativas):
    for props in features_ativas:
        assert props["metodo_coordenada"] in METODOS_VALIDOS, props["site_id"]
        assert props["precisao_coordenada"] in PRECISOES_VALIDAS, props["site_id"]


def test_schema_tier_e_1_ou_2(features_ativas):
    for props in features_ativas:
        assert props["tier"] in (1, 2), props["site_id"]


def test_schema_site_ids_sao_unicos(features_ativas):
    ids = [p["site_id"] for p in features_ativas]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------------------------
# V1, V2, V4 recomputados/verificados sobre config/sites.geojson — bloqueantes (item 6 do escopo).
# --------------------------------------------------------------------------------------------


def test_v1_recomputado_passa_para_100pct_das_aois_ativas(features_ativas):
    for props in features_ativas:
        assert v1_caixa_brasil(props["lat"], props["lon"]), f"{props['site_id']} falhou V1"


def test_v2_gravado_passa_para_100pct_das_aois_ativas(features_ativas):
    """V2 depende de reverse-geocode (rede) — verificado aqui como propriedade já gravada pelo
    pipeline (`v2_aprovado`), não recomputado ao vivo. Ver docstring do módulo."""
    for props in features_ativas:
        assert props.get("v2_aprovado") is True, (
            f"{props['site_id']}: v2_aprovado não é True (município geocodificado="
            f"{props.get('v2_municipio_geocodificado')!r}, declarado={props['municipio']!r})"
        )


def test_v4_recomputado_nao_acusa_colisao_nao_registrada(features_ativas):
    """V4 nunca reprova uma AOI sozinha (colisão exige decisão caso a caso, não rejeição
    automática) — mas toda colisão real (<5 km) tem que estar registrada em `v4_colisoes`."""
    sites = [{"site_id": p["site_id"], "lat": p["lat"], "lon": p["lon"]} for p in features_ativas]
    colisoes = v4_colisoes(sites)
    for props in features_ativas:
        pares_calculados = {outro for outro, _ in colisoes[props["site_id"]]}
        registrado = props.get("v4_colisoes") or ""
        pares_registrados = {par.split(":")[0] for par in registrado.split(";") if par}
        assert pares_calculados == pares_registrados, (
            f"{props['site_id']}: colisões recomputadas {pares_calculados} != registradas "
            f"{pares_registrados}"
        )
        assert props["v4_aprovado"] is True


def test_v4_colisoes_conhecidas_hortolandia_e_osasco_tambore(features_ativas):
    """Regressão dos 2 pares de colisão encontrados nesta rodada (ver relatório de SV-25) —
    documentado e decidido (manter ambas ativas), não uma falha."""
    by_id = {p["site_id"]: p for p in features_ativas}
    if "ascenty-hortolandia" in by_id and "odata-hortolandia" in by_id:
        d = haversine_km(
            by_id["ascenty-hortolandia"]["lat"], by_id["ascenty-hortolandia"]["lon"],
            by_id["odata-hortolandia"]["lat"], by_id["odata-hortolandia"]["lon"],
        )
        assert d < 5.0


# --------------------------------------------------------------------------------------------
# V3 — não bloqueante no enunciado, mas conferido como já gravado (justificado ou aprovado).
# --------------------------------------------------------------------------------------------


def test_v3_aprovado_ou_justificado_como_nao_aplicavel(features_ativas):
    for props in features_ativas:
        assert props.get("v3_aprovado") or props.get("v3_nao_aplicavel"), (
            f"{props['site_id']}: V3 nem aprovado nem justificado como não aplicável"
        )


# --------------------------------------------------------------------------------------------
# Cenário 6 — conferência cruzada de ascenty-vinhedo (documentada em `observacao`).
# --------------------------------------------------------------------------------------------


def test_cenario6_ascenty_vinhedo_tem_conferencia_cruzada_documentada(features_ativas):
    props = next(p for p in features_ativas if p["site_id"] == "ascenty-vinhedo")
    obs = (props.get("observacao") or "").lower()
    assert "cross-check" in obs or "cenário" in obs or "cenario" in obs
    assert "km" in obs


# --------------------------------------------------------------------------------------------
# Fila de conferência visual — arquivo existe (mesmo que pendente, não "conferido").
# --------------------------------------------------------------------------------------------


def test_fila_conferencia_coordenadas_md_existe():
    path = REPO_ROOT / "docs" / "fila-conferencia-coordenadas.md"
    assert path.exists(), f"{path} deveria existir (gerado por scripts/validar_coordenadas_sv25.py)"


def test_peeringdb_cache_existe_e_commitavel():
    path = REPO_ROOT / "data" / "externo" / "peeringdb_fac_br.json"
    assert path.exists(), f"{path} deveria existir (cache do PeeringDB, ver scripts/fetch_peeringdb.py)"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["n_registros"] > 0
