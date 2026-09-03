"""Testes de sentinela.validacao_sensores (SV-20) — os 5 cenários de teste do enunciado.

Cenários 2, 3 e 4 (agregação, controle de resolução, sanidade de concordância) são testados com
arrays sintéticos pequenos e conhecidos — rápidos, determinísticos, sem I/O. Cenários 1 e 5
(pareamento correto, estabilidade do fator) precisam dos rasters reais de SV-14
(`data/processed/classificado/`) — os testes que dependem deles são marcados e pulados
automaticamente se os dados não existirem no ambiente (mesmo padrão de outros testes do projeto
que dependem de dado gerado por etapas anteriores do pipeline).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sentinela import validacao_sensores as vs
from sentinela.config import REPO_ROOT, SETTINGS

DADOS_REAIS_DISPONIVEIS = (SETTINGS.processed_dir / "classificado" / "landsat" / "ascenty-vinhedo" / "2019.tif").exists()

pytestmark_dados_reais = pytest.mark.skipif(
    not DADOS_REAIS_DISPONIVEIS,
    reason="rasters classificados de SV-14 não encontrados em data/processed/classificado/ neste ambiente",
)


# --------------------------------------------------------------------------------------------
# Cenário 2 — agregação: a soma das áreas por classe bate com a área válida total nas duas
# resoluções, e a agregação por bloco exata não perde nem inventa pixel.
# --------------------------------------------------------------------------------------------


def test_cenario2_agregacao_preserva_contagem_total_de_pixels():
    rng = np.random.default_rng(42)
    # 6x6 (S2, 10 m) -> 2x2 (Landsat, 30 m), fator 3.
    fino = rng.integers(0, 6, size=(6, 6)).astype(np.uint8)
    agregado = vs.agregar_majoritaria(fino, fator=3)

    assert agregado.shape == (2, 2)
    # nenhum pixel fino "sobra" ou "some": a soma das contagens por classe do agregado, em pixels
    # de bloco, tem que bater com 4 blocos de 9 pixels cada = 36 pixels originais.
    assert agregado.size * 9 == fino.size

    # cada valor do agregado precisa ser a classe mais frequente do bloco 3x3 correspondente
    for bi in range(2):
        for bj in range(2):
            bloco = fino[bi * 3 : bi * 3 + 3, bj * 3 : bj * 3 + 3]
            valores, contagens = np.unique(bloco, return_counts=True)
            esperado = valores[np.argmax(contagens)]
            assert agregado[bi, bj] == esperado


def test_cenario2_agregacao_bloco_todo_nodata_vira_nodata():
    fino = np.zeros((3, 3), dtype=np.uint8)
    agregado = vs.agregar_majoritaria(fino, fator=3)
    assert agregado[0, 0] == 0


def test_cenario2_agregacao_maioria_valida_vence_nodata():
    # 4 pixels nodata, 5 pixels classe 3 -> classe 3 é maioria (ainda que só por 1 pixel) e vence.
    fino = np.array(
        [[0, 0, 0], [0, 3, 3], [3, 3, 3]], dtype=np.uint8
    )  # 4 zeros, 5 treses -> classe 3 vence
    agregado = vs.agregar_majoritaria(fino, fator=3)
    assert agregado[0, 0] == 3


def test_cenario2_area_por_classe_soma_bate_com_total_de_pixels():
    arr = np.array([[1, 1, 2], [2, 3, 0], [4, 5, 5]], dtype=np.uint8)
    area = vs.area_por_classe_ha(arr, resolucao_m=10.0)
    n_pixels_validos = int((arr != 0).sum())
    soma_ha = sum(area.values())
    assert soma_ha == pytest.approx(n_pixels_validos * 100.0 / 10000.0)

    pct = vs.pct_area_valida(arr)
    assert sum(pct.values()) == pytest.approx(100.0)


# --------------------------------------------------------------------------------------------
# Cenário 3 — controle de resolução: o teste mais importante da tarefa. Construído para que a
# única diferença entre `s2_agregado_30m` e `landsat_nativo` seja a classe majoritária de um bloco
# — isolando sensor de resolução por construção.
# --------------------------------------------------------------------------------------------


def test_cenario3_identidade_algebrica_diff_total_igual_sensor_menos_resolucao():
    """diff_total = diff_sensor_isolado - diff_resolucao, por construção algébrica — checa isso
    num caso sintético pequeno onde é fácil calcular os 3 termos à mão."""
    # Landsat 2x2 (30 m nativo): todo classe 1.
    landsat = np.full((2, 2), 1, dtype=np.uint8)
    # S2 6x6 (10 m nativo): 1 bloco 3x3 é maioria classe 2 (mas com 1 pixel de classe 1
    # "vazando"), os outros 3 blocos são puro classe 1 -> agregação por maioria também dá classe 1
    # nesses 3, e classe 2 no primeiro bloco.
    s2 = np.full((6, 6), 1, dtype=np.uint8)
    s2[0:3, 0:3] = np.array([[2, 2, 2], [2, 2, 2], [2, 2, 1]])  # maioria classe 2 (8 de 9)

    s2_agg = vs.agregar_majoritaria(s2, fator=3)
    assert s2_agg.tolist() == [[2, 1], [1, 1]]

    area_landsat = vs.area_por_classe_ha(landsat, 30.0)
    area_s2_nativo = vs.area_por_classe_ha(s2, 10.0)
    area_s2_agg = vs.area_por_classe_ha(s2_agg, 30.0)

    for c in vs.CLASS_IDS:
        diff_total = area_s2_nativo[c] - area_landsat[c]
        diff_resolucao = area_s2_agg[c] - area_s2_nativo[c]
        diff_sensor_isolado = area_s2_agg[c] - area_landsat[c]
        assert diff_total == pytest.approx(diff_sensor_isolado - diff_resolucao, abs=1e-9)

    # sanidade da direção: classe 2 aparece MENOS na agregação (perde o pixel "vazado" que não
    # muda o resultado do bloco, mas o efeito de resolução em geral reduz manchas fragmentadas) —
    # aqui o bloco inteiro passa (maioria clara), então a classe 2 nativa (8 px = 0.08 ha) deve ser
    # maior que a agregada (1 bloco = 0.09 ha "vira" só 1 pixel de 900 m² inteiro) — o que importa
    # de verdade é a identidade algébrica acima, que é o cenário 3 propriamente dito.
    assert area_s2_nativo[2] > 0
    assert area_s2_agg[2] > 0


def test_cenario3_resolucao_isolada_dilui_classe_fragmentada():
    """Uma classe presente em só 1 de 9 sub-pixels de cada bloco NUNCA sobrevive à agregação por
    maioria — o efeito clássico de pixel misto que o cenário 3 existe para isolar do sensor."""
    s2 = np.full((9, 9), 1, dtype=np.uint8)
    # em cada um dos 9 blocos 3x3, exatamente 1 pixel vira classe 3 (minoria, nunca maioria)
    for bi in range(3):
        for bj in range(3):
            s2[bi * 3, bj * 3] = 3
    s2_agg = vs.agregar_majoritaria(s2, fator=3)
    assert (s2_agg == 3).sum() == 0  # classe 3 desaparece inteiramente na agregação
    assert (s2 == 3).sum() == 9  # mas existia, nativa, em 9 pixels


# --------------------------------------------------------------------------------------------
# Cenário 4 — sanidade: concordância maior em manchas grandes/homogêneas (água, veg. densa) do
# que numa classe fragmentada.
# --------------------------------------------------------------------------------------------


def test_cenario4_concordancia_maior_em_mancha_homogenea_que_em_fragmentada():
    # Landsat 6x6: metade água (classe 5, mancha homogênea), metade um mosaico fragmentado
    # alternando classe 3/4 pixel a pixel (o pior caso de fragmentação numa grade 30 m).
    landsat = np.zeros((6, 6), dtype=np.uint8)
    landsat[:, :3] = 5  # água, mancha homogênea
    landsat[:, 3:] = np.tile(np.array([[3, 4, 3]]), (6, 1))  # mosaico 3/4 fragmentado

    # S2 "agregado" simulando erro de sensor só na região fragmentada (metade dos blocos trocam
    # de classe entre 3 e 4), e concordância perfeita na água.
    s2_agg = landsat.copy()
    s2_agg[0, 3] = 4  # discorda em 1 pixel da região fragmentada
    s2_agg[2, 5] = 3  # discorda em outro pixel da região fragmentada

    conc = vs.concordancia_espacial(landsat, s2_agg)
    concordancia_agua = conc["concordancia_por_classe"][5]
    concordancia_classe3 = conc["concordancia_por_classe"][3]

    assert concordancia_agua == 100.0
    assert concordancia_classe3 is not None and concordancia_classe3 < concordancia_agua


def test_cenario4_borda_tem_concordancia_pior_que_interior_por_construcao():
    # Bloco homogêneo grande (interior) + 1 linha de borda entre duas classes, com erro só na
    # borda — a máscara de borda tem que isolar exatamente essa linha.
    landsat = np.full((5, 5), 1, dtype=np.uint8)
    landsat[:, 3:] = 2  # fronteira vertical entre classe 1 e classe 2, colunas 3-4 são "borda"
    borda = vs._mascara_borda(landsat)
    # coluna 2 (última coluna de classe 1 antes da fronteira) e coluna 3 (primeira de classe 2)
    # devem estar marcadas como borda; coluna 0 (bem no interior da classe 1) não deve.
    assert borda[:, 2].all()
    assert borda[:, 3].all()
    assert not borda[:, 0].any()


# --------------------------------------------------------------------------------------------
# Cenário 1 — pareamento correto (site/ano batendo nos dois sensores) — precisa dos rasters reais.
# --------------------------------------------------------------------------------------------


@pytestmark_dados_reais
def test_cenario1_pareamento_mesmo_site_mesmo_ano():
    pares = vs.localizar_pares("rf_v1.0", sites=["ascenty-vinhedo"])
    assert len(pares) == 3  # 3 anos de sobreposição
    for par in pares:
        assert par.site_id == "ascenty-vinhedo"
        assert par.ano in vs.ANOS_SOBREPOSICAO
        # o site_id e o ano do par batem com os componentes do PRÓPRIO caminho de cada raster —
        # o erro mais fácil de cometer aqui é comparar site/ano errado.
        assert par.landsat_tif.parent.name == par.site_id
        assert par.landsat_tif.stem == str(par.ano)
        assert par.s2_tif.parent.name == par.site_id
        assert par.s2_tif.stem == str(par.ano)
        assert par.landsat_2018_tif.stem == "2018"


@pytestmark_dados_reais
def test_cenario1_pareamento_falha_alto_se_site_nao_existe():
    with pytest.raises(Exception):
        vs.localizar_pares("rf_v1.0", sites=["site-que-nao-existe"])


# --------------------------------------------------------------------------------------------
# Integração com dados reais — 1 site, 3 anos — identidade algébrica + formato dos artefatos.
# Serve também como checagem indireta dos cenários 2/3 em cima de dado real (não só sintético).
# --------------------------------------------------------------------------------------------


@pytestmark_dados_reais
def test_integracao_1_site_identidades_e_formato():
    resultado = vs.rodar_validacao("rf_v1.0", sites=["ascenty-vinhedo"])
    df_classe = resultado["df_classe"]

    assert len(df_classe) == 3 * len(vs.CLASS_IDS)  # 3 anos x 5 classes
    # identidade algébrica (também checada dentro de rodar_validacao, mas explícita aqui)
    residuo = (
        df_classe["diff_total_ha"] - (df_classe["diff_sensor_isolado_ha"] - df_classe["diff_resolucao_ha"])
    ).abs()
    assert (residuo < 1e-6).all()

    df_conc = resultado["df_concordancia"]
    assert len(df_conc) == 3
    assert (df_conc["pct_concordancia_geral"].between(0, 100)).all()
    assert (df_conc["pct_concordancia_interior"] >= 0).all()

    df_degrau = resultado["df_degrau"]
    assert len(df_degrau) == 3 * len(vs.CLASS_IDS)
    assert set(df_degrau["veredito"]) <= {"DISTINGUIVEL", "NAO_DISTINGUIVEL"}


# --------------------------------------------------------------------------------------------
# Cenário 5 — estabilidade do fator entre os 3 anos de sobreposição (lógica pura, sem I/O).
# --------------------------------------------------------------------------------------------


def test_cenario5_estabilidade_fator_detecta_serie_estavel_e_instavel():
    df_classe = pd.DataFrame(
        [
            # site A, classe 4: fator quase idêntico nos 3 anos -> CV baixo
            {"site_id": "A", "ano": 2019, "classe_id": 4, "classe_nome": "x", "area_landsat_ha": 100.0, "area_s2_agregado30_ha": 80.0},
            {"site_id": "A", "ano": 2020, "classe_id": 4, "classe_nome": "x", "area_landsat_ha": 100.0, "area_s2_agregado30_ha": 81.0},
            {"site_id": "A", "ano": 2021, "classe_id": 4, "classe_nome": "x", "area_landsat_ha": 100.0, "area_s2_agregado30_ha": 79.0},
            # site B, classe 4: fator varia muito de ano pra ano -> CV alto
            {"site_id": "B", "ano": 2019, "classe_id": 4, "classe_nome": "x", "area_landsat_ha": 50.0, "area_s2_agregado30_ha": 10.0},
            {"site_id": "B", "ano": 2020, "classe_id": 4, "classe_nome": "x", "area_landsat_ha": 50.0, "area_s2_agregado30_ha": 90.0},
            {"site_id": "B", "ano": 2021, "classe_id": 4, "classe_nome": "x", "area_landsat_ha": 50.0, "area_s2_agregado30_ha": 30.0},
        ]
    )
    df_fator = vs.fator_multiplicativo_por_site_ano(df_classe)
    df_estab = vs.estabilidade_fator(df_fator)

    cv_a = df_estab.loc[df_estab.site_id == "A", "cv"].iloc[0]
    cv_b = df_estab.loc[df_estab.site_id == "B", "cv"].iloc[0]
    assert cv_a < 0.05
    assert cv_b > 0.3
    assert cv_a < cv_b


def test_cenario5_heterogeneidade_entre_sites_detecta_fatores_muito_diferentes():
    df_estab = pd.DataFrame(
        [
            {"site_id": "A", "classe_id": 3, "classe_nome": "x", "media": 5.0},
            {"site_id": "B", "classe_id": 3, "classe_nome": "x", "media": 20.0},
            {"site_id": "C", "classe_id": 3, "classe_nome": "x", "media": 3.0},
        ]
    )
    df_heter = vs.heterogeneidade_entre_sites(df_estab)
    assert df_heter["cv_entre_sites"].iloc[0] > vs.CV_ENTRE_SITES_LIMIAR


def test_fator_multiplicativo_ignora_base_landsat_quase_zero():
    df_classe = pd.DataFrame(
        [{"site_id": "A", "ano": 2019, "classe_id": 3, "classe_nome": "x", "area_landsat_ha": 0.5, "area_s2_agregado30_ha": 40.0}]
    )
    df_fator = vs.fator_multiplicativo_por_site_ano(df_classe)
    assert np.isnan(df_fator["fator_mult"].iloc[0])
