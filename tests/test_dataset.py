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
    _combos_disponiveis,
    _erodir_mascara_classe,
    _xy_pixel_centro,
    atribuir_split,
    bloco_id_de_xy,
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
    resultado, n_blocos = atribuir_split(df_sintetico, seed=SEED)
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
    resultado, _ = atribuir_split(df_sintetico, seed=SEED)
    assert resultado.loc[resultado["ano"] == 2025, "holdout_temporal"].all()
    assert not resultado.loc[resultado["ano"] == 2020, "holdout_temporal"].any()


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
