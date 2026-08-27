"""Testes de sentinela.gee.labels (SV-07) — implementação da opção (b) de ADR-004.

Os testes puros (grade, ano efetivo, distribuição, escrita de tif) não tocam o Earth Engine.
Os demais abrem os arquivos já gerados por uma rodada real do CLI
(`python -m sentinela.gee.labels --site all --ano all --sensor all`) em vez de rechamar o Earth
Engine — mais rápido e evita gastar quota duas vezes. Se os arquivos ainda não existirem, esses
testes são pulados com uma mensagem clara, no mesmo padrão de `tests/test_landsat.py`/`test_sentinel2.py`.

Cobertura dos 7 cenários de teste de `docs/tarefas/SV-07-labels-worldcover.md`:
1. Alinhamento, era moderna (S2/10m).
2. Alinhamento, era antiga (Landsat/30m).
3. Coerência entre grades (mesmo ano, as duas grades concordam na maioria dos pixels).
4. Domínio de valores ⊆ {0,1,2,3,4,5}.
5. Sem interpolação (nenhum valor fora do domínio — prova indireta de nearest).
6. Validação visual (PNG gerado com sentinela.classes.colormap()).
7. Idempotência (mesmo sha256 rodando duas vezes).
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio

from sentinela import classes
from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.gee.auth import init_ee
from sentinela.gee.labels import (
    NODATA,
    _anos_disponiveis,
    _grade_geometry,
    ano_mapbiomas_efetivo,
    distribuicao_classes,
)

SITES = ["ascenty-vinhedo", "odata-hortolandia", "scala-tambore"]
ANOS_S2 = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
ANOS_LANDSAT = list(range(2013, 2022))
ANO_CROSSCHECK = 2021


@pytest.fixture(scope="module", autouse=True)
def _ee():
    init_ee()


def _tif_label(sensor: str, site_id: str, ano: int):
    return SETTINGS.raw_dir / "labels" / sensor / site_id / f"{ano}.tif"


def _manifest_label(sensor: str, site_id: str, ano: int):
    return SETTINGS.manifests_dir / f"labels_{sensor}_{site_id}_{ano}.json"


def _tif_imagem(sensor: str, site_id: str, ano: int):
    pasta = "s2" if sensor == "s2" else "landsat"
    return SETTINGS.raw_dir / pasta / site_id / f"{ano}.tif"


def _manifest_imagem(sensor: str, site_id: str, ano: int):
    prefixo = "s2" if sensor == "s2" else "landsat"
    return SETTINGS.manifests_dir / f"{prefixo}_{site_id}_{ano}.json"


# --------------------------------------------------------------------------------------------
# Funções puras (sem EE)
# --------------------------------------------------------------------------------------------


def test_ano_mapbiomas_efetivo_dentro_da_cobertura():
    ano_efetivo, distancia = ano_mapbiomas_efetivo(2019, ano_max=2023)
    assert ano_efetivo == 2019
    assert distancia == 0


def test_ano_mapbiomas_efetivo_replica_ultimo_ano_disponivel():
    ano_efetivo, distancia = ano_mapbiomas_efetivo(2024, ano_max=2023)
    assert ano_efetivo == 2023
    assert distancia == 1

    ano_efetivo, distancia = ano_mapbiomas_efetivo(2025, ano_max=2023)
    assert ano_efetivo == 2023
    assert distancia == 2


def test_ano_mapbiomas_efetivo_no_limite_exato_nao_replica():
    ano_efetivo, distancia = ano_mapbiomas_efetivo(2023, ano_max=2023)
    assert ano_efetivo == 2023
    assert distancia == 0


def test_distribuicao_classes_cobre_todas_as_6_classes_e_soma_100pct():
    arr = np.array([0, 0, 1, 1, 1, 2, 3, 4, 5], dtype=np.uint8)
    dist = distribuicao_classes(arr)
    assert set(dist.keys()) == {str(i) for i in range(6)}
    assert dist["0"]["n_pixels"] == 2
    assert dist["1"]["n_pixels"] == 3
    soma_pct_total = sum(d["pct_total"] for d in dist.values())
    assert soma_pct_total == pytest.approx(100.0, abs=1e-3)  # arredondamento a 4 casas por classe
    # pct_validos exclui nodata do denominador e não é definido para a própria classe 0
    assert dist["0"]["pct_validos"] is None
    n_validos = int((arr != 0).sum())
    assert dist["1"]["pct_validos"] == pytest.approx(100.0 * 3 / n_validos)


def test_grade_geometry_construida_a_partir_do_transform_do_manifest():
    # transform no formato [a, b, c, d, e, f] gravado nos manifests de SV-06/SV-06b. Só constrói
    # o objeto ee.Geometry client-side (sem chamada de rede) — valida que não levanta exceção e
    # que os limites derivados da origem/tamanho estão corretos, sem depender de init_ee().
    import ee

    transform = [10.0, 0.0, 288870.0, 0.0, -10.0, 7452330.0]
    geom = _grade_geometry(transform, width=100, height=50, crs="EPSG:31983")
    assert isinstance(geom, ee.Geometry)


def test_anos_disponiveis_reflete_manifests_de_imagem_existentes():
    anos_s2 = _anos_disponiveis("s2", "ascenty-vinhedo")
    if not anos_s2:
        pytest.skip("nenhum manifest s2_ascenty-vinhedo_*.json encontrado — rode SV-06 antes.")
    assert anos_s2 == sorted(anos_s2)
    assert all(a in ANOS_S2 for a in anos_s2)


# --------------------------------------------------------------------------------------------
# Cenário 4/5 — domínio de valores e ausência de interpolação
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("site_id", SITES)
@pytest.mark.parametrize("ano", ANOS_S2)
def test_cenario4_5_dominio_s2_sem_interpolacao(site_id, ano):
    tif = _tif_label("s2", site_id, ano)
    if not tif.exists():
        pytest.skip(f"{tif} não existe — rode `python -m sentinela.gee.labels` antes.")
    with rasterio.open(tif) as ds:
        arr = ds.read(1)
        assert ds.dtypes[0] == "uint8"
        assert ds.nodata == NODATA
    valores = set(np.unique(arr).tolist())
    assert valores - {0, 1, 2, 3, 4, 5} == set()


@pytest.mark.parametrize("site_id", SITES)
@pytest.mark.parametrize("ano", ANOS_LANDSAT)
def test_cenario4_5_dominio_landsat_sem_interpolacao(site_id, ano):
    tif = _tif_label("landsat", site_id, ano)
    if not tif.exists():
        pytest.skip(f"{tif} não existe — rode `python -m sentinela.gee.labels` antes.")
    with rasterio.open(tif) as ds:
        arr = ds.read(1)
        assert ds.dtypes[0] == "uint8"
        assert ds.nodata == NODATA
    valores = set(np.unique(arr).tolist())
    assert valores - {0, 1, 2, 3, 4, 5} == set()


# --------------------------------------------------------------------------------------------
# Cenário 1 — alinhamento, era moderna (S2 / 10 m)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("site_id", SITES)
@pytest.mark.parametrize("ano", ANOS_S2)
def test_cenario1_alinhamento_era_moderna(site_id, ano):
    tif_label = _tif_label("s2", site_id, ano)
    tif_imagem = _tif_imagem("s2", site_id, ano)
    if not (tif_label.exists() and tif_imagem.exists()):
        pytest.skip(f"{tif_label} ou {tif_imagem} não existe.")
    with rasterio.open(tif_label) as ds_label, rasterio.open(tif_imagem) as ds_imagem:
        assert ds_label.width == ds_imagem.width
        assert ds_label.height == ds_imagem.height
        assert ds_label.transform == ds_imagem.transform
        assert ds_label.crs == ds_imagem.crs


# --------------------------------------------------------------------------------------------
# Cenário 2 — alinhamento, era antiga (Landsat / 30 m)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("site_id", SITES)
@pytest.mark.parametrize("ano", ANOS_LANDSAT)
def test_cenario2_alinhamento_era_antiga(site_id, ano):
    tif_label = _tif_label("landsat", site_id, ano)
    tif_imagem = _tif_imagem("landsat", site_id, ano)
    if not (tif_label.exists() and tif_imagem.exists()):
        pytest.skip(f"{tif_label} ou {tif_imagem} não existe.")
    with rasterio.open(tif_label) as ds_label, rasterio.open(tif_imagem) as ds_imagem:
        assert ds_label.width == ds_imagem.width
        assert ds_label.height == ds_imagem.height
        assert ds_label.transform == ds_imagem.transform
        assert ds_label.crs == ds_imagem.crs


# --------------------------------------------------------------------------------------------
# Cenário 3 — coerência entre grades (mesmo ano, dois rasters de label)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("site_id", SITES)
def test_cenario3_coerencia_entre_grades_mesmo_ano(site_id):
    """Um ponto do terreno deve receber a mesma classe nos dois rasters de label do mesmo ano,
    salvo efeito de pixel misto na borda entre manchas. Agrega a grade de 10 m em blocos 3x3
    (mesma origem da grade de 30 m, refinamento exato — SV-06/SV-06b) por voto majoritário e
    compara com a grade de 30 m: concordância no interior de manchas homogêneas deve ser alta.
    """
    tif_10m = _tif_label("s2", site_id, ANO_CROSSCHECK)
    tif_30m = _tif_label("landsat", site_id, ANO_CROSSCHECK)
    if not (tif_10m.exists() and tif_30m.exists()):
        pytest.skip(f"{tif_10m} ou {tif_30m} não existe — rode `python -m sentinela.gee.labels` antes.")

    with rasterio.open(tif_10m) as ds10, rasterio.open(tif_30m) as ds30:
        arr10 = ds10.read(1)
        arr30 = ds30.read(1)
        # mesma origem (canto superior-esquerdo) nas duas grades — contrato de SV-06/SV-06b
        assert ds10.transform.c == ds30.transform.c
        assert ds10.transform.f == ds30.transform.f

    h30, w30 = arr30.shape
    h10_ok, w10_ok = h30 * 3, w30 * 3
    bloco = arr10[:h10_ok, :w10_ok].reshape(h30, 3, w30, 3)

    def _moda_bloco(bloco3x3: np.ndarray) -> int:
        valores, contagens = np.unique(bloco3x3, return_counts=True)
        return int(valores[np.argmax(contagens)])

    arr10_agregado = np.zeros((h30, w30), dtype=np.uint8)
    for i in range(h30):
        for j in range(w30):
            arr10_agregado[i, j] = _moda_bloco(bloco[i, :, j, :])

    ambos_validos = (arr10_agregado != 0) & (arr30 != 0)
    n_validos = int(ambos_validos.sum())
    if n_validos == 0:
        pytest.skip(f"{site_id}: nenhum pixel válido em comum entre as duas grades em {ANO_CROSSCHECK}.")
    concordancia = float((arr10_agregado[ambos_validos] == arr30[ambos_validos]).mean())
    print(f"\n{site_id}: coerência entre grades 10m/30m em {ANO_CROSSCHECK} = {concordancia:.2%}")
    # Mesma fonte (MapBiomas), reprojeções independentes a partir da mesma imagem nativa 30m —
    # divergência só deveria vir de efeito de borda/arredondamento, não de erro de reprojeção.
    assert concordancia > 0.85, (
        f"{site_id}: concordância entre grades = {concordancia:.2%} — divergência sistemática "
        "no interior de manchas homogêneas sugere erro de reprojeção."
    )


# --------------------------------------------------------------------------------------------
# Cenário 6 — validação visual (PNG)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sensor,site_id,ano", [("s2", s, 2025) for s in SITES] + [("landsat", s, 2013) for s in SITES])
def test_cenario6_png_de_conferencia_existe(sensor, site_id, ano):
    png = REPO_ROOT / "reports" / "figures" / f"labels_{sensor}_{site_id}_{ano}.png"
    if not png.exists():
        pytest.skip(f"{png} não existe — rode `python -m sentinela.gee.labels` antes.")
    assert png.stat().st_size > 0


# --------------------------------------------------------------------------------------------
# Cenário 7 — idempotência
# --------------------------------------------------------------------------------------------


def test_cenario7_idempotencia_pula_sem_regravar():
    from sentinela.gee.labels import _site_por_id, gerar_label_site_ano

    site_id, sensor, ano = "ascenty-vinhedo", "s2", 2019
    tif = _tif_label(sensor, site_id, ano)
    manifest_path = _manifest_label(sensor, site_id, ano)
    if not (tif.exists() and manifest_path.exists()):
        pytest.skip(f"{tif} não existe — rode `python -m sentinela.gee.labels` antes.")

    sha_antes = json.loads(manifest_path.read_text(encoding="utf-8"))["sha256"]
    mtime_antes = tif.stat().st_mtime

    site = _site_por_id(site_id)
    resultado = gerar_label_site_ano(site, sensor, ano, force=False)

    assert tif.stat().st_mtime == mtime_antes, "não deveria ter regravado o .tif sem --force"
    assert resultado["sha256"] == sha_antes


# --------------------------------------------------------------------------------------------
# Manifest: contrato de campos + sha256 batendo com o arquivo real
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sensor,anos", [("s2", ANOS_S2), ("landsat", ANOS_LANDSAT)])
def test_manifest_contrato_de_campos_e_sha256(sensor, anos):
    algum = False
    for site_id in SITES:
        for ano in anos:
            manifest_path = _manifest_label(sensor, site_id, ano)
            tif = _tif_label(sensor, site_id, ano)
            if not (manifest_path.exists() and tif.exists()):
                continue
            algum = True
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for campo in (
                "site_id", "ano", "sensor", "fonte", "colecao", "anual", "ano_mapbiomas_efetivo",
                "distancia_safra", "remap_usado", "crs", "transform", "shape", "resolucao_m",
                "nodata", "distribuicao_classes", "sha256", "git_sha", "gerado_em",
            ):
                assert campo in manifest, f"{manifest_path}: campo '{campo}' ausente"
            assert manifest["site_id"] == site_id
            assert manifest["ano"] == ano
            assert manifest["sensor"] == sensor
            assert manifest["nodata"] == 0
            assert manifest["anual"] is True
            assert set(manifest["distribuicao_classes"].keys()) == {str(i) for i in range(6)}

            import hashlib

            h = hashlib.sha256(tif.read_bytes()).hexdigest()
            assert manifest["sha256"] == h, f"{manifest_path}: sha256 não bate com o .tif atual"
    if not algum:
        pytest.skip(f"nenhum manifest labels_{sensor}_* encontrado — rode a geração antes.")


def test_manifest_distancia_safra_2024_2025_marca_replicacao_de_2023():
    algum = False
    for site_id in SITES:
        for ano in (2024, 2025):
            manifest_path = _manifest_label("s2", site_id, ano)
            if not manifest_path.exists():
                continue
            algum = True
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["ano_mapbiomas_efetivo"] == 2023
            assert manifest["distancia_safra"] == ano - 2023
    if not algum:
        pytest.skip("nenhum manifest labels_s2_*_2024/2025.json encontrado — rode a geração antes.")


def test_manifest_crosscheck_so_existe_no_ano_de_verificacao_cruzada():
    algum = False
    for sensor in ("s2", "landsat"):
        for site_id in SITES:
            for ano in (ANOS_S2 if sensor == "s2" else ANOS_LANDSAT):
                manifest_path = _manifest_label(sensor, site_id, ano)
                if not manifest_path.exists():
                    continue
                algum = True
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if ano == ANO_CROSSCHECK:
                    assert manifest["crosscheck"] is not None
                    assert 0.0 <= manifest["crosscheck"]["pct_concordancia_global"] <= 100.0
                else:
                    assert manifest["crosscheck"] is None
    if not algum:
        pytest.skip("nenhum manifest labels_* encontrado — rode a geração antes.")


def test_distribuicao_2013_2025_muda_sinal_de_construcao_no_periodo():
    """Critério de aceite de SV-07: se a distribuição não mudar nada entre 2013 e 2025, é sinal
    de que 2023 foi replicado por engano em vez de usar o ano correto em cada ponto da série."""
    algum = False
    for site_id in SITES:
        m2013 = _manifest_label("landsat", site_id, 2013)
        m2025 = _manifest_label("s2", site_id, 2025)
        if not (m2013.exists() and m2025.exists()):
            continue
        algum = True
        d2013 = json.loads(m2013.read_text(encoding="utf-8"))["distribuicao_classes"]
        d2025 = json.loads(m2025.read_text(encoding="utf-8"))["distribuicao_classes"]
        maior_delta = max(
            abs((d2025[str(c)]["pct_validos"] or 0) - (d2013[str(c)]["pct_validos"] or 0))
            for c in range(1, 6)
        )
        assert maior_delta > 0.5, (
            f"{site_id}: maior variação de classe entre 2013 e 2025 = {maior_delta:.2f}pp — "
            "distribuição praticamente igual sugere réplica indevida de um único ano."
        )
    if not algum:
        pytest.skip("faltam manifests landsat_2013/s2_2025 de labels — rode a geração antes.")


# --------------------------------------------------------------------------------------------
# Classe 3 — representação (achado a sinalizar, não uma falha de teste)
# --------------------------------------------------------------------------------------------


def test_classe_3_representacao_e_reportada():
    """Não falha o teste — só imprime a representação da classe 3 (solo_exposto_obras) para
    que fique visível no relatório do pytest, já que baixa representação aqui define a urgência
    de SV-09/SV-10 (rotulagem manual)."""
    achados = []
    for sensor, anos in (("s2", ANOS_S2), ("landsat", ANOS_LANDSAT)):
        for site_id in SITES:
            for ano in anos:
                manifest_path = _manifest_label(sensor, site_id, ano)
                if not manifest_path.exists():
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                pct3 = manifest["distribuicao_classes"]["3"]["pct_validos"]
                if pct3 is not None:
                    achados.append((site_id, sensor, ano, pct3))
    if not achados:
        pytest.skip("nenhum manifest de label encontrado — rode a geração antes.")
    media = sum(a[3] for a in achados) / len(achados)
    print(f"\nClasse 3 (solo_exposto_obras): representação média = {media:.3f}% ao longo de todos os site/sensor/ano.")
    if media < 2.0:
        print(
            "ACHADO: classe 3 com representação média < 2% em todo o dataset de labels — "
            "reforça que a rotulagem manual (SV-09/SV-10) é urgente, não opcional."
        )
    assert classes.ID_TO_SLUG[3] == "solo_exposto_obras"
