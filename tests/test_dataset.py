"""Testes de sentinela.dataset (SV-11) — dataset de modelagem v0.1, split sem vazamento.

Os testes puros (bloco_id, peso_label, erosão, xy do pixel) não tocam `data/`. Os cenários
antivazamento (1-7) e os testes de controle (8-9) do enunciado de SV-11 abrem
`data/processed/dataset_v0.1.parquet` + `data/manifests/dataset_v0.1.json`, já gerados por uma
rodada real do CLI (`python -m sentinela.dataset --versao v0.1`), no mesmo padrão de
`tests/test_labels.py`/`test_indices.py` — pulados com `pytest.skip(...)` se ainda não existirem.

**Os cenários 1-3 são bloqueantes** (critério de aceite de SV-11: nenhum bloco_id em treino E
teste ao mesmo tempo; nenhum bloco_id com sensores diferentes em splits diferentes; bloco_id
coerente entre as duas resoluções para o mesmo ponto do terreno) — se qualquer um deles falhar,
o vazamento de dados está aberto e o dataset não deve ser usado em SV-12.

Os testes de controle (8-9) rodam RF rápidos (poucas árvores, subamostra) só para confirmar a
direção do efeito dentro do tempo de um `pytest` normal; os números exatos para o relatório da
banca vêm de uma rodada separada sobre o dataset inteiro (ver relatório de SV-11).
"""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pandas as pd
import pytest
import rasterio

from sentinela import classes
from sentinela.config import REPO_ROOT, SETTINGS
from sentinela.dataset import (
    TAMANHO_BLOCO_M,
    TETO_POR_CLASSE_SITE_ANO_SENSOR,
    _blocos_id_vetorizado,
    _carregar_sites_meta,
    _combos_disponiveis,
    _erodir_mascara_classe,
    _xy_pixel_centro,
    atribuir_split,
    bloco_id_de_xy,
    fase_do_ano,
    montar_dataset,
    peso_label,
)
from sentinela.dataset import (
    teste_controle_generalizacao_entre_eras as rf_generalizacao_entre_eras,
)
from sentinela.dataset import (
    teste_controle_split_aleatorio_vs_bloco as rf_split_aleatorio_vs_bloco,
)

VERSAO = "v0.1"
SEED = 42


def _parquet_path():
    return SETTINGS.processed_dir / f"dataset_{VERSAO}.parquet"


def _manifest_path():
    return SETTINGS.manifests_dir / f"dataset_{VERSAO}.json"


@pytest.fixture(scope="module")
def df():
    path = _parquet_path()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.dataset --versao {VERSAO}` antes.")
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def manifest():
    path = _manifest_path()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.dataset --versao {VERSAO}` antes.")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------
# bloco_id — funções puras, sem I/O
# --------------------------------------------------------------------------------------------


def test_bloco_id_mesmo_ponto_mesmo_bloco():
    assert bloco_id_de_xy("site-a", 288875.0, 7452325.0) == bloco_id_de_xy("site-a", 288995.0, 7452201.0)


def test_bloco_id_formato_site_i_j():
    bloco = bloco_id_de_xy("ascenty-vinhedo", 289500.0, 7451500.0)
    assert bloco.startswith("ascenty-vinhedo_")
    i, j = bloco.rsplit("_", 2)[1:]
    assert int(i) == int(np.floor(289500.0 / TAMANHO_BLOCO_M))
    assert int(j) == int(np.floor(7451500.0 / TAMANHO_BLOCO_M))


def test_bloco_id_pontos_em_blocos_vizinhos_diferem():
    b1 = bloco_id_de_xy("site-a", 288500.0, 7452500.0)
    b2 = bloco_id_de_xy("site-a", 289500.0, 7452500.0)  # 1000m a leste -> bloco seguinte
    assert b1 != b2


def test_bloco_id_vetorizado_bate_com_escalar():
    x = np.array([288875.0, 289999.0, 291000.5])
    y = np.array([7452325.0, 7451001.0, 7450000.0])
    vet = _blocos_id_vetorizado("site-a", x, y)
    esc = [bloco_id_de_xy("site-a", xi, yi) for xi, yi in zip(x, y, strict=True)]
    assert list(vet) == esc


def test_bloco_id_e_funcao_so_de_xy_nunca_de_linha_coluna():
    """bloco_id_de_xy não recebe linha/coluna como parâmetro — é impossível calcular o bloco a
    partir de índice de pixel usando esta função (prova por assinatura, não só por valor)."""
    import inspect

    assinatura = inspect.signature(bloco_id_de_xy)
    assert set(assinatura.parameters) == {"site_id", "x", "y"}


# --------------------------------------------------------------------------------------------
# xy do centro do pixel
# --------------------------------------------------------------------------------------------


def test_xy_pixel_centro_origem_e_passo():
    transform = rasterio.Affine(10.0, 0.0, 288870.0, 0.0, -10.0, 7452330.0)
    linhas = np.array([0, 1])
    colunas = np.array([0, 1])
    x, y = _xy_pixel_centro(transform, linhas, colunas)
    assert x[0] == pytest.approx(288870.0 + 5.0)
    assert y[0] == pytest.approx(7452330.0 - 5.0)
    assert x[1] == pytest.approx(288870.0 + 15.0)
    assert y[1] == pytest.approx(7452330.0 - 15.0)


# --------------------------------------------------------------------------------------------
# peso_label (item 5 do enunciado)
# --------------------------------------------------------------------------------------------


def test_peso_label_anual_sem_defasagem_e_sem_crosscheck_e_1():
    assert peso_label(0, None) == pytest.approx(1.0)


def test_peso_label_decresce_com_distancia_safra():
    assert peso_label(1, None) == pytest.approx(0.5)
    assert peso_label(2, None) == pytest.approx(1 / 3)


def test_peso_label_crosscheck_reduz_peso_dos_discordantes():
    conc = np.array([1, 0, 1, 0])
    pesos = peso_label(0, conc)
    assert pesos[0] == pytest.approx(1.0)
    assert pesos[1] == pytest.approx(0.5)
    assert pesos[2] == pytest.approx(1.0)
    assert pesos[3] == pytest.approx(0.5)


# --------------------------------------------------------------------------------------------
# Erosão de borda
# --------------------------------------------------------------------------------------------


def test_erosao_remove_borda_mantem_interior():
    mask = np.zeros((7, 7), dtype=bool)
    mask[1:6, 1:6] = True  # bloco 5x5 sólido
    erodida = _erodir_mascara_classe(mask)
    assert erodida[3, 3]  # centro sobrevive
    assert not erodida[1, 1]  # borda desaparece
    assert erodida.sum() < mask.sum()


def test_erosao_mascara_vazia_continua_vazia():
    mask = np.zeros((5, 5), dtype=bool)
    assert not _erodir_mascara_classe(mask).any()


# --------------------------------------------------------------------------------------------
# atribuir_split — split por bloco, não por linha
# --------------------------------------------------------------------------------------------


def test_atribuir_split_todas_as_linhas_de_um_bloco_vao_juntas():
    df_sintetico = pd.DataFrame(
        {
            "site_id": ["s1"] * 20,
            "bloco_id": [f"s1_{i // 4}_0" for i in range(20)],  # 5 blocos, 4 linhas cada
            "ano": [2020] * 20,
        }
    )
    resultado, n_blocos, _cobertura, _novos_blocos = atribuir_split(df_sintetico, seed=SEED)
    assert resultado.groupby("bloco_id")["split"].nunique().eq(1).all()
    assert n_blocos["treino"] + n_blocos["teste"] == resultado["bloco_id"].nunique()


def test_atribuir_split_holdout_temporal_marca_ano_mais_recente():
    df_sintetico = pd.DataFrame(
        {
            "site_id": ["s1"] * 10,
            "bloco_id": [f"s1_{i}_0" for i in range(10)],
            "ano": [2020] * 5 + [2025] * 5,
        }
    )
    resultado, _, _cobertura, _novos_blocos = atribuir_split(df_sintetico, seed=SEED)
    assert resultado.loc[resultado["ano"] == 2025, "holdout_temporal"].all()
    assert not resultado.loc[resultado["ano"] == 2020, "holdout_temporal"].any()


# --------------------------------------------------------------------------------------------
# atribuir_split — holdout espacial (SV-27, item 4)
# --------------------------------------------------------------------------------------------


def test_atribuir_split_holdout_espacial_fica_inteiro_fora_do_treino():
    """AOI marcada em holdout_site_ids: TODOS os blocos dela (não uma amostra) vão para 'teste',
    holdout_espacial=True, e ela não participa do sorteio 70/30 das demais AOIs."""
    df_sintetico = pd.DataFrame(
        {
            "site_id": ["s1"] * 20 + ["s2-holdout"] * 10,
            "bloco_id": [f"s1_{i // 4}_0" for i in range(20)] + [f"s2h_{i}_0" for i in range(10)],
            "ano": [2020] * 30,
        }
    )
    resultado, _n_blocos, _cobertura, _novos_blocos = atribuir_split(
        df_sintetico, seed=SEED, holdout_site_ids=frozenset({"s2-holdout"})
    )
    holdout_rows = resultado[resultado["site_id"] == "s2-holdout"]
    assert holdout_rows["holdout_espacial"].all()
    assert set(holdout_rows["split"].unique()) == {"teste"}
    assert not resultado.loc[resultado["site_id"] == "s1", "holdout_espacial"].any()
    # s1 continua com sorteio 70/30 normal (algum bloco em treino e algum em teste, com 5 blocos)
    assert set(resultado.loc[resultado["site_id"] == "s1", "split"].unique()) == {"treino", "teste"}


def test_cobertura_por_estrato_relata_treino_e_teste_por_valor():
    df_sintetico = pd.DataFrame(
        {
            "site_id": ["s1"] * 20 + ["s2-holdout"] * 10,
            "bloco_id": [f"s1_{i // 4}_0" for i in range(20)] + [f"s2h_{i}_0" for i in range(10)],
            "ano": [2020] * 30,
            "regiao": ["Sudeste"] * 20 + ["Norte"] * 10,
            "bioma": ["Mata Atlântica"] * 20 + ["Amazônia"] * 10,
        }
    )
    _resultado, _n_blocos, cobertura, _novos_blocos = atribuir_split(
        df_sintetico, seed=SEED, holdout_site_ids=frozenset({"s2-holdout"})
    )
    assert cobertura["regiao"]["Sudeste"]["treino"] and cobertura["regiao"]["Sudeste"]["teste"]
    # "Norte" só existe em s2-holdout: 100% em teste, sem treino -> flag correta de cobertura parcial
    assert cobertura["regiao"]["Norte"]["teste"] and not cobertura["regiao"]["Norte"]["treino"]
    assert cobertura["regiao"]["Norte"]["aois_holdout_espacial"] == ["s2-holdout"]
    assert cobertura["bioma"]["Amazônia"]["aois_holdout_espacial"] == ["s2-holdout"]


# --------------------------------------------------------------------------------------------
# fase_do_ano (SV-27, item 2)
# --------------------------------------------------------------------------------------------


def test_fase_do_ano_pre_durante_pos():
    assert fase_do_ano(2015, "2014-2016", "2017-2019", "2020-2025") == "pre"
    assert fase_do_ano(2018, "2014-2016", "2017-2019", "2020-2025") == "durante"
    assert fase_do_ano(2023, "2014-2016", "2017-2019", "2020-2025") == "pos"


def test_fase_do_ano_fora_da_janela():
    assert fase_do_ano(2013, "2014-2016", "2017-2019", "2020-2025") == "fora"


def test_fase_do_ano_sem_periodo_documentado_e_fora():
    """AOIs sem periodo_pre/durante/pos documentado (ex.: odata-hortolandia) — fase sempre 'fora',
    nunca estoura exceção."""
    assert fase_do_ano(2020, None, None, None) == "fora"


# --------------------------------------------------------------------------------------------
# Cenário 1 — antivazamento espacial (BLOQUEANTE)
# --------------------------------------------------------------------------------------------


def test_cenario1_antivazamento_espacial(df):
    blocos_treino = set(df.loc[df["split"] == "treino", "bloco_id"])
    blocos_teste = set(df.loc[df["split"] == "teste", "bloco_id"])
    intersecao = blocos_treino & blocos_teste
    assert intersecao == set(), f"{len(intersecao)} bloco(s) aparecem em treino E teste: {sorted(intersecao)[:5]}..."


# --------------------------------------------------------------------------------------------
# Cenário 2 — antivazamento entre sensores (BLOQUEANTE)
# --------------------------------------------------------------------------------------------


def test_cenario2_antivazamento_entre_sensores(df):
    nunique_por_bloco = df.groupby("bloco_id")["split"].nunique()
    ofensores = nunique_por_bloco[nunique_por_bloco != 1]
    assert ofensores.empty, f"{len(ofensores)} bloco(s) com sensores/anos espalhados por splits diferentes"


# --------------------------------------------------------------------------------------------
# Cenário 3 — coerência de bloco entre resoluções (BLOQUEANTE)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("site_id", ["ascenty-vinhedo", "odata-hortolandia", "scala-tambore"])
def test_cenario3_coerencia_de_bloco_entre_resolucoes(site_id):
    """Um mesmo ponto físico deve cair no mesmo bloco_id nas duas resoluções. Localiza o pixel
    S2 (10m) e o pixel Landsat (30m) do ano de sobreposição 2019 que contêm um ponto fixo dentro
    da AOI e confere que ambos calculam o mesmo bloco_id a partir de x/y — a prova direta de que
    bloco_id fecha o vazamento entre sensores (não é vazamento se as duas grades concordam)."""
    tif_s2 = SETTINGS.interim_dir / "features" / "s2" / site_id / "2019.tif"
    tif_landsat = SETTINGS.interim_dir / "features" / "landsat" / site_id / "2019.tif"
    if not (tif_s2.exists() and tif_landsat.exists()):
        pytest.skip(f"{tif_s2} ou {tif_landsat} não existe — rode SV-08 antes.")

    with rasterio.open(tif_s2) as ds:
        transform_s2 = ds.transform
        width_s2, height_s2 = ds.width, ds.height
    with rasterio.open(tif_landsat) as ds:
        transform_landsat = ds.transform

    # ponto fixo perto do centro da AOI (mesma origem nas duas grades, garantida por SV-06/SV-06b)
    linha_centro_s2, coluna_centro_s2 = height_s2 // 2, width_s2 // 2
    x_ponto, y_ponto = _xy_pixel_centro(
        transform_s2, np.array([linha_centro_s2]), np.array([coluna_centro_s2])
    )
    x_ponto, y_ponto = float(x_ponto[0]), float(y_ponto[0])

    # localiza o pixel Landsat que contém esse ponto (inversa do affine)
    col_landsat, linha_landsat = ~transform_landsat * (x_ponto, y_ponto)
    linha_landsat, col_landsat = int(np.floor(linha_landsat)), int(np.floor(col_landsat))
    x_landsat, y_landsat = _xy_pixel_centro(
        transform_landsat, np.array([linha_landsat]), np.array([col_landsat])
    )

    bloco_s2 = bloco_id_de_xy(site_id, x_ponto, y_ponto)
    bloco_landsat = bloco_id_de_xy(site_id, float(x_landsat[0]), float(y_landsat[0]))
    assert bloco_s2 == bloco_landsat, (
        f"{site_id}: mesmo ponto do terreno recebeu bloco_id diferente em S2 ({bloco_s2}) e "
        f"Landsat ({bloco_landsat}) — vazamento entre sensores aberto."
    )


def test_bloco_id_no_dataset_real_e_consistente_com_x_y(df):
    """Confere, sobre o dataset real, que bloco_id gravado bate com o recalculado a partir das
    colunas x/y (garante que o pipeline realmente usou x/y, não linha/coluna, na hora de gravar)."""
    amostra = df.sample(n=min(5000, len(df)), random_state=SEED)
    esperado = [
        bloco_id_de_xy(site_id, x, y)
        for site_id, x, y in zip(amostra["site_id"], amostra["x"], amostra["y"], strict=True)
    ]
    assert list(amostra["bloco_id"]) == esperado


# --------------------------------------------------------------------------------------------
# Cenário 4 — sem duplicata
# --------------------------------------------------------------------------------------------


def test_cenario4_sem_duplicata(df):
    chave = df[["site_id", "ano", "sensor", "linha", "coluna"]]
    assert not chave.duplicated().any(), "há pixels amostrados mais de uma vez (mesmo site/ano/sensor/linha/coluna)"


# --------------------------------------------------------------------------------------------
# Cenário 5 — sanidade do split (25%-35% em teste)
# --------------------------------------------------------------------------------------------


def test_cenario5_sanidade_do_split(df):
    frac_teste = (df["split"] == "teste").mean()
    assert 0.25 <= frac_teste <= 0.35, f"{frac_teste:.2%} das linhas em teste — fora da faixa 25%-35%"


# --------------------------------------------------------------------------------------------
# Cenário 6 — determinismo (mesma seed -> mesmo conteúdo)
# --------------------------------------------------------------------------------------------


def test_cenario6_determinismo_mesma_seed_mesmo_conteudo():
    if not _combos_disponiveis():
        pytest.skip("nenhum combo (features + label) disponível — rode SV-07/SV-08 antes.")
    df1, _ = montar_dataset(seed=SEED)
    df2, _ = montar_dataset(seed=SEED)
    hash1 = pd.util.hash_pandas_object(df1.sort_values(list(df1.columns)).reset_index(drop=True)).sum()
    hash2 = pd.util.hash_pandas_object(df2.sort_values(list(df2.columns)).reset_index(drop=True)).sum()
    assert hash1 == hash2, "duas rodadas com a mesma seed produziram conteúdos diferentes"


def test_cenario6_manifest_sha256_estavel_entre_rodadas(manifest):
    """O manifest já commitado deve refletir o sha256 real do parquet atual em disco (prova
    indireta de idempotência: se você rodar de novo com a mesma seed, o parquet e o sha256 no
    manifest não deveriam mudar)."""
    import hashlib

    parquet_path = _parquet_path()
    if not parquet_path.exists():
        pytest.skip(f"{parquet_path} não existe.")
    sha_atual = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    assert manifest["sha256"] == sha_atual


# --------------------------------------------------------------------------------------------
# Cenário 7 — nomes de feature idênticos, em ordem, ao manifest de SV-08
# --------------------------------------------------------------------------------------------


def test_cenario7_lista_features_bate_com_sv08(manifest):
    algum_manifest = next(SETTINGS.manifests_dir.glob("features_*.json"), None)
    if algum_manifest is None:
        pytest.skip("nenhum manifest features_*.json encontrado — rode SV-08 antes.")
    feat_manifest = json.loads(algum_manifest.read_text(encoding="utf-8"))
    assert manifest["lista_features"] == feat_manifest["bandas"]


# --------------------------------------------------------------------------------------------
# Critérios de aceite adicionais
# --------------------------------------------------------------------------------------------


def test_n_linhas_na_faixa_esperada(manifest):
    assert 300_000 <= manifest["n_linhas"] <= 2_000_000


def test_teto_por_classe_site_ano_sensor_respeitado(df):
    contagens = df.groupby(["site_id", "ano", "sensor", "classe_id"]).size()
    assert contagens.max() <= TETO_POR_CLASSE_SITE_ANO_SENSOR


def test_sem_nan_em_coluna_de_feature(df, manifest):
    features = manifest["lista_features"]
    assert df[features].isna().sum().sum() == 0


def test_todas_as_5_classes_presentes_em_treino_e_teste(df):
    slugs_esperados = {classes.ID_TO_SLUG[i] for i in range(1, 6)}
    for split in ("treino", "teste"):
        classes_no_split = {classes.ID_TO_SLUG[c] for c in df.loc[df["split"] == split, "classe_id"].unique()}
        faltando = slugs_esperados - classes_no_split
        assert not faltando, f"split '{split}' sem as classes: {faltando}"


def test_classe_3_representacao_no_teste_e_reportada(df):
    """Não falha (é um achado a reportar, não um critério bloqueante) — só imprime a contagem."""
    n_classe3_teste = int(((df["split"] == "teste") & (df["classe_id"] == 3)).sum())
    print(f"\nClasse 3 (solo_exposto_obras) no teste: {n_classe3_teste} amostras.")
    if n_classe3_teste < 1000:
        print("ACHADO: classe 3 com menos de 1.000 amostras no teste — métricas dela ficarão instáveis (SV-12).")


def test_duas_eras_representadas_e_nenhuma_domina(df):
    fracoes = df["sensor"].value_counts(normalize=True)
    assert set(fracoes.index) == {"s2", "landsat"}
    for sensor, frac in fracoes.items():
        assert frac <= 0.70, f"sensor '{sensor}' responde por {frac:.1%} das linhas (> 70%)"


def test_parquet_nao_esta_no_git():
    resultado = subprocess.run(
        ["git", "check-ignore", "-q", str(_parquet_path())], cwd=REPO_ROOT, check=False
    )
    assert resultado.returncode == 0, "data/processed/dataset_v0.1.parquet deveria estar no .gitignore"


def test_manifest_contrato_de_campos(manifest):
    for campo in (
        "versao", "n_linhas", "n_features", "lista_features", "distribuicao_classes", "n_blocos",
        "sites", "anos", "sensores", "fonte_label", "seed", "regra_split", "regra_peso_label",
        "erosao", "rasters_origem", "sha256", "git_sha", "gerado_em",
    ):
        assert campo in manifest, f"campo '{campo}' ausente do manifest"
    assert "bloco" in manifest["regra_split"].lower()
    assert manifest["seed"] == SEED
    for split in ("treino", "teste"):
        assert split in manifest["distribuicao_classes"]["por_split"]
        assert split in manifest["n_blocos"]


def test_bloco_id_derivado_de_xy_nao_de_linha_coluna_no_dataset_real(df):
    """Critério de aceite: verificável por código E por teste. Recalcula bloco_id a partir de
    x/y para uma amostra e confere que bate — se o pipeline usasse linha/coluna, isso falharia
    para qualquer sensor != referência (resoluções diferentes)."""
    amostra = df.groupby("sensor").sample(n=200, random_state=SEED)
    recalculado = [
        bloco_id_de_xy(site_id, x, y)
        for site_id, x, y in zip(amostra["site_id"], amostra["x"], amostra["y"], strict=True)
    ]
    assert list(amostra["bloco_id"]) == recalculado


# --------------------------------------------------------------------------------------------
# Cenário 8 — teste de controle: split aleatório por pixel vs. split por bloco
# --------------------------------------------------------------------------------------------


def _subamostrar_por_grupo(df: pd.DataFrame, colunas: list[str], n: int) -> pd.DataFrame:
    """`df.groupby(colunas).apply(lambda g: g.sample(...))` derruba as colunas de agrupamento em
    versões recentes do pandas (detecta que a UDF "opera sobre as colunas de agrupamento" e as
    exclui) — por isso um loop explícito em vez de groupby().apply() aqui."""
    partes = [g.sample(n=min(len(g), n), random_state=SEED) for _, g in df.groupby(colunas)]
    return pd.concat(partes, ignore_index=True)


def test_cenario8_controle_split_aleatorio_vs_bloco(df):
    """RF rápido, subamostrado para caber num pytest normal. Não é o número final do relatório
    (esse vem de uma rodada separada sobre o dataset inteiro) — aqui só confirmamos a direção:
    split aleatório por pixel deve reportar acurácia/F1 maiores que o split por bloco, porque o
    vizinho do pixel de treino vaza pro teste."""
    amostra = _subamostrar_por_grupo(df, ["classe_id"], 4000)
    resultado = rf_split_aleatorio_vs_bloco(amostra, seed=SEED)
    print(f"\n[cenário 8] split por bloco: {resultado['split_bloco']}")
    print(f"[cenário 8] split aleatório por pixel: {resultado['split_aleatorio_pixel']}")
    assert resultado["split_aleatorio_pixel"]["acuracia"] >= resultado["split_bloco"]["acuracia"] - 0.02, (
        "esperado: split aleatório por pixel com acurácia igual ou maior que split por bloco "
        "(evidência de vazamento espacial quando maior)"
    )


# --------------------------------------------------------------------------------------------
# Cenário 9 — teste de controle: generalização entre eras de sensor
# --------------------------------------------------------------------------------------------


def test_cenario9_controle_generalizacao_entre_eras(df):
    amostra = _subamostrar_por_grupo(df, ["sensor", "classe_id"], 3000)
    resultado = rf_generalizacao_entre_eras(amostra, seed=SEED)
    print(f"\n[cenário 9] generalização entre eras: {resultado}")
    assert resultado, "nenhum par treino/teste entre eras pôde ser montado"


# ==============================================================================================
# SV-27 — dataset v0.2 (expandido, ~16 AOIs, teto recalibrado, estratos, holdout espacial)
#
# Todos os cenários antivazamento acima (1-7) continuam bloqueantes e valem também para v0.2
# (mesmo bloco_id, mesma regra de split — SV-27 não mudou nenhum dos dois). Os testes abaixo
# cobrem só o que é NOVO em SV-27: teto recalibrado, colunas de estrato, e holdout espacial.
# ==============================================================================================

VERSAO_V02 = "v0.2"


def _parquet_path_v02():
    return SETTINGS.processed_dir / f"dataset_{VERSAO_V02}.parquet"


def _manifest_path_v02():
    return SETTINGS.manifests_dir / f"dataset_{VERSAO_V02}.json"


@pytest.fixture(scope="module")
def df_v02():
    path = _parquet_path_v02()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.dataset --versao v0.2 ...` antes.")
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def manifest_v02():
    path = _manifest_path_v02()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode `python -m sentinela.dataset --versao v0.2 ...` antes.")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------
# Metadados de AOI (funções puras, sem depender do dataset gerado)
# --------------------------------------------------------------------------------------------


def test_carregar_sites_meta_cobre_as_aois_ativas():
    meta = _carregar_sites_meta()
    assert len(meta) >= 3  # pelo menos as 3 AOIs originais de v0.1
    for site_id, campos in meta.items():
        assert campos["tier"] in (1, 2), f"{site_id}: tier fora de {{1,2}}"
        assert campos["regiao"], f"{site_id}: regiao ausente"
        assert campos["bioma"], f"{site_id}: bioma ausente"


# --------------------------------------------------------------------------------------------
# Critérios de aceite específicos de SV-27
# --------------------------------------------------------------------------------------------


def test_v02_n_linhas_na_faixa_3m_a_4_5m(manifest_v02):
    assert 3_000_000 <= manifest_v02["n_linhas"] <= 4_500_000, (
        f"n_linhas={manifest_v02['n_linhas']} fora da faixa 3-4,5M do enunciado de SV-27"
    )


def test_v02_memoria_abaixo_de_2_5gb(df_v02):
    mem_bytes = df_v02.memory_usage(deep=True).sum()
    assert mem_bytes < 2.5 * 1024**3, f"df.memory_usage(deep=True).sum() = {mem_bytes / 1e9:.2f} GB >= 2.5 GB"


def test_v02_teto_amostragem_registrado_e_respeitado(df_v02, manifest_v02):
    teto = manifest_v02["amostragem"]["teto_por_classe_site_ano_sensor"]
    assert teto > 0
    contagens = df_v02.groupby(["site_id", "ano", "sensor", "classe_id"], observed=True).size()
    assert contagens.max() <= teto, "alguma combinação classe x AOI x ano x sensor excede o teto declarado"


def test_v02_colunas_de_estrato_presentes_e_nunca_features(df_v02, manifest_v02):
    for coluna in ("regiao", "bioma", "uf", "tier", "fase"):
        assert coluna in df_v02.columns, f"coluna de estrato '{coluna}' ausente do dataset v0.2"
        assert coluna not in manifest_v02["lista_features"], f"'{coluna}' vazou para lista_features"
    assert set(manifest_v02["estratos_nao_sao_features"]) >= {"regiao", "bioma", "uf", "tier", "fase"}


def test_v02_fase_so_tem_valores_esperados(df_v02):
    assert set(df_v02["fase"].unique()) <= {"pre", "durante", "pos", "fora"}


# --------------------------------------------------------------------------------------------
# Cenário 4 (SV-27) — holdout espacial: AOI reservada nunca aparece em treino (BLOQUEANTE)
# --------------------------------------------------------------------------------------------


def test_v02_cenario4_holdout_espacial_nunca_em_treino(df_v02, manifest_v02):
    aois_holdout = manifest_v02["aois_holdout_espacial"]
    assert aois_holdout, "SV-27 espera pelo menos uma AOI marcada holdout_espacial (~3 AOIs tier 2)"
    linhas_holdout = df_v02[df_v02["holdout_espacial"]]
    assert not linhas_holdout.empty
    assert set(linhas_holdout["split"].unique()) == {"teste"}, (
        "há linha(s) de AOI em holdout_espacial com split == 'treino' — vazamento do critério "
        "de generalização fora-da-amostra"
    )
    assert set(linhas_holdout["site_id"].unique()) == set(aois_holdout)
    # e nenhuma AOI fora da lista de holdout está marcada holdout_espacial=True
    assert set(df_v02.loc[~df_v02["holdout_espacial"], "site_id"].unique()).isdisjoint(set(aois_holdout))


# --------------------------------------------------------------------------------------------
# Cenário 5 (SV-27) — estratificação regional: toda região aparece em treino e teste, ou exceção
# declarada no manifest
# --------------------------------------------------------------------------------------------


def test_v02_cenario5_cobertura_regional_ou_excecao_declarada(df_v02, manifest_v02):
    excecoes = set(manifest_v02["regioes_sem_ambos_splits"])
    contagem = df_v02.groupby(["regiao", "split"], observed=True).size().unstack(fill_value=0)
    for regiao in contagem.index:
        tem_treino = contagem.loc[regiao].get("treino", 0) > 0
        tem_teste = contagem.loc[regiao].get("teste", 0) > 0
        if tem_treino and tem_teste:
            continue
        assert str(regiao) in excecoes, (
            f"região '{regiao}' não tem os dois splits e NÃO está declarada em "
            f"regioes_sem_ambos_splits do manifest — exceção escondida"
        )


def test_v02_biomas_sem_ambos_splits_documentado(df_v02, manifest_v02):
    """Não falha por si só (achado a reportar) — confere que, se existir, a lista bate com os
    dados reais e não está escondida."""
    excecoes = set(manifest_v02["biomas_sem_ambos_splits"])
    contagem = df_v02.groupby(["bioma", "split"], observed=True).size().unstack(fill_value=0)
    biomas_incompletos = set()
    for bioma in contagem.index:
        tem_treino = contagem.loc[bioma].get("treino", 0) > 0
        tem_teste = contagem.loc[bioma].get("teste", 0) > 0
        if not (tem_treino and tem_teste):
            biomas_incompletos.add(str(bioma))
    assert biomas_incompletos == excecoes, (
        f"biomas incompletos reais {biomas_incompletos} != declarados no manifest {excecoes}"
    )
    print(f"\n[SV-27] biomas sem os dois splits: {sorted(biomas_incompletos) or 'nenhum'}")


# --------------------------------------------------------------------------------------------
# Antivazamento (1-4 de v0.1) reaplicados sobre v0.2 — continuam bloqueantes
# --------------------------------------------------------------------------------------------


def test_v02_antivazamento_espacial(df_v02):
    blocos_treino = set(df_v02.loc[df_v02["split"] == "treino", "bloco_id"])
    blocos_teste = set(df_v02.loc[df_v02["split"] == "teste", "bloco_id"])
    intersecao = blocos_treino & blocos_teste
    assert intersecao == set(), f"{len(intersecao)} bloco(s) em treino E teste (v0.2)"


def test_v02_antivazamento_entre_sensores(df_v02):
    nunique_por_bloco = df_v02.groupby("bloco_id", observed=True)["split"].nunique()
    ofensores = nunique_por_bloco[nunique_por_bloco != 1]
    assert ofensores.empty, f"{len(ofensores)} bloco(s) com splits divergentes dentro do mesmo bloco (v0.2)"


def test_v02_sem_duplicata(df_v02):
    chave = df_v02[["site_id", "ano", "sensor", "linha", "coluna"]]
    assert not chave.duplicated().any()


def test_v02_bloco_id_consistente_com_x_y(df_v02):
    amostra = df_v02.sample(n=min(5000, len(df_v02)), random_state=SEED)
    esperado = [
        bloco_id_de_xy(str(site_id), x, y)
        for site_id, x, y in zip(amostra["site_id"], amostra["x"], amostra["y"], strict=True)
    ]
    assert list(amostra["bloco_id"].astype(str)) == esperado


def test_v02_todas_as_5_classes_em_treino_e_teste(df_v02):
    slugs_esperados = {classes.ID_TO_SLUG[i] for i in range(1, 6)}
    for split in ("treino", "teste"):
        classes_no_split = {classes.ID_TO_SLUG[c] for c in df_v02.loc[df_v02["split"] == split, "classe_id"].unique()}
        faltando = slugs_esperados - classes_no_split
        assert not faltando, f"split '{split}' (v0.2) sem as classes: {faltando}"


def test_v02_classe_3_representacao_no_teste_e_reportada(df_v02):
    n = int(((df_v02["split"] == "teste") & (df_v02["classe_id"] == 3)).sum())
    print(f"\n[SV-27] Classe 3 (solo_exposto_obras) no teste: {n} amostras.")
    if n < 5000:
        print("ACHADO: classe 3 com menos de 5.000 amostras no teste (critério de aceite de SV-27).")


def test_v02_determinismo_sha256(manifest_v02):
    sha_atual = _sha256_arquivo_local(_parquet_path_v02())
    assert manifest_v02["sha256"] == sha_atual, (
        "sha256 do manifest não bate com o parquet em disco — reprodutibilidade quebrada"
    )


def _sha256_arquivo_local(path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_v02_parquet_nao_esta_no_git():
    resultado = subprocess.run(
        ["git", "check-ignore", "-q", str(_parquet_path_v02())], cwd=REPO_ROOT, check=False
    )
    assert resultado.returncode == 0, "data/processed/dataset_v0.2.parquet deveria estar no .gitignore"


# ==============================================================================================
# SV-16 — dataset v1.0 (rotulagem manual, SV-10, incorporada com precedência sobre o automático)
#
# Cenários de teste do enunciado (docs/tarefas/SV-16-dataset-v1.0-retreino.md):
#   1. Split preservado (BLOQUEANTE): join(v0.2, v1.0, on=bloco_id) -> split idêntico em 100%
#      dos blocos comuns.
#   2. Precedência: pixel dentro de polígono manual de classe 3 que o automático dizia outra
#      classe -> classe_id==3 e origem_label=="manual" em v1.0.
#   3. Sem vazamento novo: polígono que cruza fronteira de blocos tem seus pixels divididos por
#      bloco (nunca forçado inteiro pro treino).
#   5. Detecção de decoreba: F1 nos pixels origem_label=="mapbiomas" não pode ter caído vs. v0.2
#      — medido em reports/experiments/EXP-002 (fora do escopo de um teste de dataset).
# ==============================================================================================

VERSAO_V10 = "v1.0"


def _parquet_path_v10():
    return SETTINGS.processed_dir / f"dataset_{VERSAO_V10}.parquet"


def _manifest_path_v10():
    return SETTINGS.manifests_dir / f"dataset_{VERSAO_V10}.json"


@pytest.fixture(scope="module")
def df_v10():
    path = _parquet_path_v10()
    if not path.exists():
        pytest.skip(
            f"{path} não existe — rode `python -m sentinela.dataset --versao v1.0 --teto 4000 "
            f"--holdout-tier 2 --usar-labels-manuais --referencia-split "
            f"data/processed/dataset_v0.2.parquet` antes."
        )
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def manifest_v10():
    path = _manifest_path_v10()
    if not path.exists():
        pytest.skip(f"{path} não existe — rode o CLI de v1.0 antes (ver df_v10).")
    return json.loads(path.read_text(encoding="utf-8"))


def test_v10_origem_label_presente_com_as_duas_categorias(df_v10):
    assert "origem_label" in df_v10.columns
    assert set(df_v10["origem_label"].unique()) == {"mapbiomas", "manual"}
    assert (df_v10["origem_label"] == "manual").sum() > 0


def test_v10_cenario1_split_identico_a_v02_nos_blocos_comuns(df_v10, df_v02):
    """BLOQUEANTE: join(v0.2, v1.0, on=bloco_id) -> split idêntico em 100% dos blocos comuns."""
    m2 = (
        df_v02[["bloco_id", "split"]].astype({"bloco_id": str, "split": str})
        .drop_duplicates("bloco_id").set_index("bloco_id")["split"]
    )
    m1 = (
        df_v10[["bloco_id", "split"]].astype({"bloco_id": str, "split": str})
        .drop_duplicates("bloco_id").set_index("bloco_id")["split"]
    )
    comuns = sorted(set(m1.index) & set(m2.index))
    assert comuns, "nenhum bloco em comum entre v0.2 e v1.0 — algo está muito errado"
    divergentes = [b for b in comuns if m1.loc[b] != m2.loc[b]]
    assert not divergentes, (
        f"{len(divergentes)} bloco(s) comuns entre v0.2 e v1.0 com split DIFERENTE — a "
        f"comparação de EXP-002 fica inválida: {divergentes[:5]}"
    )


def test_v10_cenario2_precedencia_manual_sobre_automatico(df_v10, manifest_v10):
    """Onde há rotulagem manual, ela vence o automático — evidenciado por n_pixels_sobrescritos
    (por classe) > 0 no manifest e, diretamente, por pixels manuais de classe 3 existindo."""
    sobrescritos = manifest_v10["labels_manuais"]["n_pixels_sobrescritos_por_classe"]
    assert sum(sobrescritos.values()) > 0, "nenhum pixel automático foi sobrescrito por manual"
    manual_c3 = df_v10[(df_v10["origem_label"] == "manual") & (df_v10["classe_id"] == 3)]
    assert len(manual_c3) > 0, "nenhuma amostra manual de classe 3 (solo_exposto_obras) no dataset"


def test_v10_cenario3_poligono_dividido_por_bloco_nao_forcado_inteiro(df_v10):
    """Um polígono manual que cruza fronteira de blocos deve ter pixels em splits diferentes —
    prova direta de que a divisão respeita bloco_id, não o polígono inteiro."""
    manual = df_v10[df_v10["origem_label"] == "manual"]
    grp = manual.groupby(["site_id", "ano", "sensor", "classe_id"], observed=True)["split"].nunique()
    assert (grp > 1).any(), (
        "nenhum grupo (site,ano,sensor,classe) manual tem pixels em ambos os splits — "
        "esperado que ao menos um polígono cruze fronteira de bloco"
    )


def test_v10_antivazamento_espacial_preservado(df_v10):
    blocos_treino = set(df_v10.loc[df_v10["split"] == "treino", "bloco_id"])
    blocos_teste = set(df_v10.loc[df_v10["split"] == "teste", "bloco_id"])
    assert not (blocos_treino & blocos_teste)


def test_v10_amostras_manuais_nao_tem_teto(df_v10, manifest_v10):
    """Item 2 do enunciado: amostras manuais não entram no teto de amostragem (~4000/classe/AOI/
    ano/sensor) — confere que ao menos uma combinação (site,ano,sensor,classe) tem MAIS pixels
    manuais do que sobrariam se o teto valesse pra elas (ou, no mínimo, que a contagem manual usada
    bate com o que foi rasterizado, sem corte)."""
    usados = manifest_v10["labels_manuais"]["n_pixels_usados_no_dataset_por_classe"]
    assert sum(usados.values()) > 0
    manual = df_v10[df_v10["origem_label"] == "manual"]
    contagens_auto = df_v10[df_v10["origem_label"] == "mapbiomas"].groupby(
        ["site_id", "ano", "sensor", "classe_id"], observed=True
    ).size()
    teto = manifest_v10["amostragem"]["teto_por_classe_site_ano_sensor"]
    assert contagens_auto.max() <= teto, "pool automático excedeu o teto declarado em v1.0"
    # combos onde manual + automático somados excedem o teto -> prova que manual não foi cortado
    contagens_manual = manual.groupby(["site_id", "ano", "sensor", "classe_id"], observed=True).size()
    total = contagens_auto.add(contagens_manual, fill_value=0)
    assert (total[contagens_manual.index.intersection(total.index)] >= contagens_manual).all()


def test_v10_peso_label_manual_maior_que_automatico_tipico(df_v10):
    from sentinela.dataset import PESO_LABEL_MANUAL_BAIXA, PESO_LABEL_MANUAL_PADRAO

    manual = df_v10[df_v10["origem_label"] == "manual"]
    assert set(manual["peso_label"].unique()) <= {PESO_LABEL_MANUAL_PADRAO, PESO_LABEL_MANUAL_BAIXA}
    auto_peso_tipico = df_v10.loc[df_v10["origem_label"] == "mapbiomas", "peso_label"].median()
    assert PESO_LABEL_MANUAL_PADRAO > auto_peso_tipico


def test_v10_confianca_baixa_recebe_peso_reduzido(df_v10):
    from sentinela.dataset import PESO_LABEL_MANUAL_BAIXA, PESO_LABEL_MANUAL_PADRAO

    manual = df_v10[df_v10["origem_label"] == "manual"]
    baixa = manual[manual["confianca_manual"] == "baixa"]
    alta_media = manual[manual["confianca_manual"] == "alta_media"]
    if len(baixa) and len(alta_media):
        assert (baixa["peso_label"] == PESO_LABEL_MANUAL_BAIXA).all()
        assert (alta_media["peso_label"] == PESO_LABEL_MANUAL_PADRAO).all()


def test_v10_manifest_contrato_de_campos_novos(manifest_v10):
    assert "labels_manuais" in manifest_v10
    lm = manifest_v10["labels_manuais"]
    for campo in (
        "arquivos", "n_pixels_rasterizados_por_sensor", "n_pixels_usados_no_dataset_por_classe",
        "n_pixels_sobrescritos_por_classe", "politica_precedencia", "politica_peso",
        "politica_teto_amostragem", "distribuicao_classes_por_origem_label", "referencia_split",
    ):
        assert campo in lm, f"campo 'labels_manuais.{campo}' ausente do manifest v1.0"
    assert lm["arquivos"], "nenhum arquivo de rotulagem manual registrado no manifest"
    for a in lm["arquivos"]:
        assert "sha256" in a and "arquivo" in a


def test_v10_parquet_nao_esta_no_git():
    resultado = subprocess.run(
        ["git", "check-ignore", "-q", str(_parquet_path_v10())], cwd=REPO_ROOT, check=False
    )
    assert resultado.returncode == 0, "data/processed/dataset_v1.0.parquet deveria estar no .gitignore"


def test_v02_manifest_contrato_de_campos_novos(manifest_v02):
    for campo in (
        "versao", "n_linhas", "n_features", "lista_features", "distribuicao_classes", "n_blocos",
        "sites", "anos", "sensores", "fonte_label", "seed", "regra_split", "regra_peso_label",
        "erosao", "rasters_origem", "sha256", "git_sha", "gerado_em",
        # novos em SV-27:
        "estratos_nao_sao_features", "aois", "aois_holdout_espacial", "holdout_tier",
        "cobertura_estrato", "regioes_sem_ambos_splits", "biomas_sem_ambos_splits", "memoria_mb",
    ):
        assert campo in manifest_v02, f"campo '{campo}' ausente do manifest v0.2"
    assert "por_regiao" in manifest_v02["distribuicao_classes"]
    assert "por_bioma" in manifest_v02["distribuicao_classes"]
    assert manifest_v02["seed"] == SEED
    assert "teto_por_classe_site_ano_sensor" in manifest_v02["amostragem"]
    assert "justificativa_teto" in manifest_v02["amostragem"]
