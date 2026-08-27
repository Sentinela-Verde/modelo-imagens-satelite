import numpy as np
import pytest

from sentinela import classes


def test_worldcover_remap_matches_table():
    # Vetor calculado direto da tabela em config/classes.yml (10->1, 20->2, 30->2, 40->2, 50->4,
    # 60->3, 70->0, 80->5, 90->0, 95->0, 100->0) — o vetor sugerido em docs/tarefas/SV-05-... está
    # deliberadamente errado ("não copie sem verificar"); este foi conferido linha a linha.
    entrada = np.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100])
    esperado = np.array([1, 2, 2, 2, 4, 3, 0, 5, 0, 0, 0])
    resultado = classes.remap(entrada, "worldcover")
    np.testing.assert_array_equal(resultado, esperado)


def test_codigo_desconhecido_vira_zero():
    resultado = classes.remap(np.array([42]), "worldcover")
    np.testing.assert_array_equal(resultado, np.array([0]))


def test_remap_preserva_shape_e_dtype():
    entrada = np.full((100, 100), 10, dtype=np.uint8)
    resultado = classes.remap(entrada, "worldcover")
    assert resultado.shape == (100, 100)
    assert resultado.dtype == entrada.dtype
    assert (resultado == 1).all()


def test_nova_fonte_de_remap_so_precisa_de_dado_novo():
    # Simula "editar o YAML" sem tocar em classes.py: injeta uma fonte fictícia direto no dict
    # já carregado e confirma que remap() funciona sem nenhuma mudança de código.
    classes.REMAPS["ficticia"] = {7: 5, 8: 1}
    try:
        resultado = classes.remap(np.array([7, 8, 9]), "ficticia")
        np.testing.assert_array_equal(resultado, np.array([5, 1, 0]))
    finally:
        del classes.REMAPS["ficticia"]


def test_fonte_inexistente_leva_erro_claro():
    with pytest.raises(KeyError):
        classes.remap(np.array([1]), "fonte-que-nao-existe")


def test_seis_classes_com_slugs_unicos():
    assert len(classes.CLASSES) == 6
    slugs = [meta["slug"] for meta in classes.CLASSES.values()]
    assert len(slugs) == len(set(slugs))


def test_mapbiomas_remap_cobre_toda_legenda_colecao_9():
    # Todos os 37 códigos da legenda oficial da Coleção 9 (SV-05b), conferidos código a código
    # contra brasil.mapbiomas.org/wp-content/uploads/sites/4/2024/08/Legenda-Colecao-9-LEGEND-CODE.pdf
    # — nenhum deve ficar de fora da tabela de remap (cenário de teste 1 de SV-05b).
    codigos_legenda_colecao_9 = {
        1, 3, 4, 5, 6, 49,  # Floresta
        10, 11, 12, 32, 29, 50,  # Vegetação Herbácea e Arbustiva
        14, 15, 18, 19, 39, 20, 40, 62, 41, 36, 46, 47, 35, 48, 9, 21,  # Agropecuária
        22, 23, 24, 30, 25,  # Área não Vegetada
        26, 33, 31,  # Corpo D'água
        27,  # Não observado
    }
    assert codigos_legenda_colecao_9 == set(classes.REMAPS["mapbiomas"].keys())


def test_mapbiomas_remap_so_produz_ids_validos():
    entrada = np.array(sorted(classes.REMAPS["mapbiomas"].keys()))
    resultado = classes.remap(entrada, "mapbiomas")
    assert set(resultado.tolist()) <= set(classes.CLASSES.keys())


def test_colormap_tem_uma_cor_por_id_sem_repeticao():
    cmap = classes.colormap()
    assert set(cmap.keys()) == set(classes.CLASSES.keys())
    cores = list(cmap.values())
    assert len(cores) == len(set(cores))
    for rgb in cores:
        assert len(rgb) == 3
        assert all(0 <= c <= 255 for c in rgb)
