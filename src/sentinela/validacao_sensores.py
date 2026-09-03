"""SV-20 — Validação cruzada entre sensores no período de sobreposição (2019-2021).

Rode com:

    python -m sentinela.validacao_sensores --modelo models/rf_v1.0.joblib

**Por que esta tarefa existe:** o projeto afirma coisas sobre mudança de cobertura do solo ao
longo de 2013-2025, usando Landsat 8/9 (30 m) até 2018 e Sentinel-2 (10 m) a partir de 2019 — a
troca de sensor acontece exatamente quando a maioria dos data centers do estudo começou a crescer.
Sem esta validação, "vocês trocaram de satélite, e o degrau é do satélite" é uma objeção justa e
não respondida. SV-02b (`docs/decisoes/ADR-003-harmonizacao-multissensor.md`) já mediu o resíduo
*espectral* banda a banda (não bateu tolerância em NIR/SWIR1/SWIR2) e a resposta adotada foi tratar
`sensor` como feature do modelo. SV-15 (`outputs/indicadores/area_por_classe.csv`), ao gerar o
output real, mediu que a classe 3 (solo exposto/obras) do Sentinel-2 é sistematicamente maior que a
do Landsat em TODOS os 48 pares site x ano de sobreposição (6,6 a 18,4 p.p.) — maior do que o
resíduo espectral isolado sugeriria. Este módulo mede o resíduo **na saída final** (área por
classe) e faz o controle que falta para separar duas explicações que SV-15 não conseguia separar
sozinho: efeito de RESOLUÇÃO (pixel misto, 30 m vs 10 m) vs. efeito de SENSOR (harmonização
espectral/comportamento do modelo).

**Não reclassifica nada.** Os 256 rasters de SV-14 (`data/processed/classificado/{sensor}/{site}/
{ano}.tif`) já existem para os 16 sites ativos, incluindo os 3 anos de sobreposição (2019-2021) nos
dois sensores E o ano 2018 (Landsat, não-sobreposição, usado para medir o degrau publicado). Este
módulo só lê e compara.

## O truque central: agregação exata 3x3

Os rasters Landsat (30 m) e Sentinel-2 (10 m) de um mesmo site/ano compartilham EXATAMENTE a mesma
origem, CRS (EPSG:31983) e bounding box — verificado nos 16 sites x 3 anos de sobreposição antes de
escrever este módulo. A dimensão do raster S2 é sempre 3x a do Landsat em cada eixo (ex.:
`ascenty-vinhedo/2019`: Landsat 334x335, S2 1002x1005 = 334*3 x 335*3). Isso permite reduzir o S2
de 10 m para 30 m por **agregação de blocos exata** (`reshape` + contagem por classe, sem
reamostragem/reprojeção do GDAL) — cada pixel Landsat corresponde a exatamente 9 pixels S2, sem
nenhuma ambiguidade de alinhamento de grade.

Isso dá 3 rasters comparáveis por site/ano de sobreposição:

  - `landsat_nativo`  — 30 m, sensor Landsat.
  - `s2_nativo`       — 10 m, sensor Sentinel-2 (resolução real da era 2019-2025).
  - `s2_agregado_30m` — 30 m (classe majoritária do bloco 3x3), sensor Sentinel-2.

E permite uma decomposição aditiva do viés total medido por SV-15 (todas as áreas em ha, por
classe, mesmo site/ano):

    diff_total            = area(s2_nativo) - area(landsat_nativo)        # o que SV-15 mediu
    diff_resolucao         = area(s2_agregado_30m) - area(s2_nativo)      # MESMO sensor, resolução
                                                                            # diferente -> pixel misto
    diff_sensor_isolado    = area(s2_agregado_30m) - area(landsat_nativo) # MESMA resolução (30 m),
                                                                            # sensor diferente -> só
                                                                            # sensor/harmonização

Por identidade algébrica, `diff_total == diff_sensor_isolado - diff_resolucao` sempre (checado como
teste de sanidade). `diff_resolucao` é o cenário de teste 3 do enunciado — o teste mais importante
da tarefa: sem ele, qualquer diferença observada entre `landsat_nativo` e `s2_nativo` é atribuída
inteiramente a "sensor", quando parte pode ser só "pixel de 900 m² vê uma mistura que o pixel de
100 m² separa".
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio

from . import classes
from .config import REPO_ROOT, SETTINGS

# --------------------------------------------------------------------------------------------
# Contrato / constantes
# --------------------------------------------------------------------------------------------

CLASS_IDS = [1, 2, 3, 4, 5]
CLASSES_CRITICAS = [3, 4]  # solo_exposto_obras, construida_urbana — foco do enunciado (item 3)

ANOS_SOBREPOSICAO = [2019, 2020, 2021]  # config/params.yml: faixa_a.anos_sobreposicao
ANO_PRE_SOBREPOSICAO = 2018  # última safra só-Landsat — usado para medir o "degrau publicado"

SENSOR_TOKEN_TO_CANONICO = {"s2": "sentinel2", "landsat": "landsat"}

FATOR_AGREGACAO = 3  # 30 m / 10 m — verificado, não assumido às cegas (ver _validar_fator_agregacao)

OUT_DIR = REPO_ROOT / "reports" / "figures" / "validacao_sensores"
REPORT_PATH = REPO_ROOT / "reports" / "validacao_sensores.md"


class ValidacaoError(RuntimeError):
    """Erro de validação com mensagem acionável."""


# --------------------------------------------------------------------------------------------
# Sites ativos (mesmo padrão de predict._sites_ativos)
# --------------------------------------------------------------------------------------------


def _sites_ativos() -> list[str]:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[gdf["ativo"] == True]  # noqa: E712
    return sorted(gdf["site_id"].tolist())


# --------------------------------------------------------------------------------------------
# Localização dos rasters + checagem de versão do modelo
# --------------------------------------------------------------------------------------------


def _caminho_raster(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.processed_dir / "classificado" / sensor_token / site_id / f"{ano}.tif"


def _caminho_manifest(sensor_token: str, site_id: str, ano: int) -> Path:
    return SETTINGS.manifests_dir / f"classificado_{sensor_token}_{site_id}_{ano}.json"


def _checar_modelo_versao(sensor_token: str, site_id: str, ano: int, modelo_versao: str) -> None:
    manifest_path = _caminho_manifest(sensor_token, site_id, ano)
    if not manifest_path.exists():
        raise ValidacaoError(
            f"{manifest_path} não existe — rode `python -m sentinela.predict --modelo "
            f"models/{modelo_versao}.joblib --sensor {sensor_token} --site {site_id} --ano {ano}` antes."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("modelo_versao") != modelo_versao:
        raise ValidacaoError(
            f"{manifest_path}: modelo_versao='{manifest.get('modelo_versao')}', esperado "
            f"'{modelo_versao}' — reclassifique com o modelo pedido antes de validar."
        )


@dataclass(frozen=True)
class ParSobreposicao:
    """Um site x ano de sobreposição — as duas classificações do MESMO site e do MESMO ano
    (cenário de teste 1: pareamento correto é o erro mais fácil de cometer aqui)."""

    site_id: str
    ano: int
    landsat_tif: Path
    s2_tif: Path
    landsat_2018_tif: Path  # para o cálculo do degrau publicado (item 5 do enunciado)


def localizar_pares(modelo_versao: str, sites: list[str] | None = None) -> list[ParSobreposicao]:
    sites = sites or _sites_ativos()
    pares: list[ParSobreposicao] = []
    for site_id in sites:
        for ano in ANOS_SOBREPOSICAO:
            _checar_modelo_versao("landsat", site_id, ano, modelo_versao)
            _checar_modelo_versao("s2", site_id, ano, modelo_versao)
            _checar_modelo_versao("landsat", site_id, ANO_PRE_SOBREPOSICAO, modelo_versao)
            landsat_tif = _caminho_raster("landsat", site_id, ano)
            s2_tif = _caminho_raster("s2", site_id, ano)
            landsat_2018_tif = _caminho_raster("landsat", site_id, ANO_PRE_SOBREPOSICAO)
            for p in (landsat_tif, s2_tif, landsat_2018_tif):
                if not p.exists():
                    raise ValidacaoError(f"{p} não existe (manifest aponta pra ele, mas o .tif sumiu).")
            pares.append(
                ParSobreposicao(
                    site_id=site_id, ano=ano, landsat_tif=landsat_tif, s2_tif=s2_tif,
                    landsat_2018_tif=landsat_2018_tif,
                )
            )
    if len(pares) != len(sites) * len(ANOS_SOBREPOSICAO):
        raise ValidacaoError(
            f"esperado {len(sites) * len(ANOS_SOBREPOSICAO)} pares (16 sites x 3 anos), "
            f"encontrado {len(pares)} — comparação parcial não é aceitável para esta tarefa "
            "(critério de aceite: 'para TODOS os site x ano, não para um só')."
        )
    return pares


# --------------------------------------------------------------------------------------------
# Leitura + agregação exata 3x3 (o núcleo do controle de resolução)
# --------------------------------------------------------------------------------------------


def _ler_raster(path: Path) -> tuple[np.ndarray, Any, Any]:
    with rasterio.open(path) as src:
        return src.read(1), src.crs, src.transform


def _validar_fator_agregacao(shape_landsat: tuple[int, int], shape_s2: tuple[int, int]) -> None:
    hl, wl = shape_landsat
    hs, ws = shape_s2
    if hs != hl * FATOR_AGREGACAO or ws != wl * FATOR_AGREGACAO:
        raise ValidacaoError(
            f"grade S2 {shape_s2} não é exatamente {FATOR_AGREGACAO}x a grade Landsat "
            f"{shape_landsat} — a agregação de bloco exata pressupõe essa relação (verificada "
            "manualmente para os 16 sites x 3 anos antes de escrever este módulo; se isso disparar, "
            "algo mudou na ingestão/AOI e a agregação por bloco não é mais segura sem reprojeção "
            "explícita)."
        )


def agregar_majoritaria(
    arr_fino: np.ndarray, fator: int = FATOR_AGREGACAO
) -> np.ndarray:
    """Agrega `arr_fino` (h*fator, w*fator) para (h, w) por CLASSE MAJORITÁRIA do bloco fator x
    fator — cenário de teste 2/3 do enunciado (`agregar a classificação de 10 m pra grade de 30 m
    por classe majoritária`).

    Implementado por contagem exata (reshape + soma por classe), não por reamostragem do GDAL —
    a grade S2 é EXATAMENTE `fator`x a grade Landsat na mesma origem (checado por
    `_validar_fator_agregacao` antes de chamar isto), então não há ambiguidade de alinhamento a
    resolver via interpolação.

    Empate: classe com MAIOR contagem no bloco vence; em empate exato entre duas classes válidas
    (1-5), a de menor `classe_id` vence (ordem de iteração 0..5, só sobrescreve com `>` estrito).
    Um bloco onde nodata (0) é maioria absoluta agrega para nodata (0) — nunca "inventa" uma classe
    válida a partir de um bloco majoritariamente inválido.
    """
    h, w = arr_fino.shape[0] // fator, arr_fino.shape[1] // fator
    aparado = arr_fino[: h * fator, : w * fator]
    blocos = aparado.reshape(h, fator, w, fator)

    saida = np.zeros((h, w), dtype=np.uint8)
    melhor_contagem = np.full((h, w), -1, dtype=np.int32)
    for c in range(6):  # 0 (nodata) .. 5
        contagem_c = (blocos == c).sum(axis=(1, 3))
        sobrescrever = contagem_c > melhor_contagem
        saida[sobrescrever] = c
        melhor_contagem[sobrescrever] = contagem_c[sobrescrever]
    return saida


# --------------------------------------------------------------------------------------------
# Área por classe (ha e p.p.) — mesma convenção de export_indicadores
# --------------------------------------------------------------------------------------------


def area_por_classe_ha(arr: np.ndarray, resolucao_m: float) -> dict[int, float]:
    px_m2 = resolucao_m * resolucao_m
    valores, contagens = np.unique(arr, return_counts=True)
    contagem = dict(zip(valores.tolist(), contagens.tolist(), strict=True))
    return {c: contagem.get(c, 0) * px_m2 / 10000.0 for c in CLASS_IDS}


def pct_area_valida(arr: np.ndarray) -> dict[int, float]:
    valores, contagens = np.unique(arr, return_counts=True)
    contagem = dict(zip(valores.tolist(), contagens.tolist(), strict=True))
    n_validos = sum(v for k, v in contagem.items() if k != 0)
    if n_validos == 0:
        return {c: 0.0 for c in CLASS_IDS}
    return {c: 100.0 * contagem.get(c, 0) / n_validos for c in CLASS_IDS}


# --------------------------------------------------------------------------------------------
# Concordância espacial + matriz de confusão (item 2b do enunciado)
# --------------------------------------------------------------------------------------------


def _mascara_borda(arr: np.ndarray) -> np.ndarray:
    """True onde o pixel tem ao menos 1 vizinho válido (8-conectividade) de classe DIFERENTE —
    aproxima 'está perto de uma fronteira entre classes' na grade de 30 m (o mesmo raster usado
    como referência na comparação pixel a pixel). Pixels nodata nunca contam como vizinho válido
    para efeito de definir borda."""
    h, w = arr.shape
    padded = np.pad(arr, 1, mode="constant", constant_values=0)
    centro = padded[1:-1, 1:-1]
    borda = np.zeros((h, w), dtype=bool)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            vizinho = padded[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w]
            borda |= (vizinho != 0) & (vizinho != centro)
    return borda


def concordancia_espacial(landsat_arr: np.ndarray, s2_agg_arr: np.ndarray) -> dict[str, Any]:
    """Concordância pixel a pixel na grade de 30 m entre Landsat nativo e S2 agregado por
    majoritária — item 2b do enunciado. Retorna concordância geral, por borda/interior
    (cenário 4/análise item 4), e a matriz de confusão 5x5 (linha=Landsat, coluna=S2 agregado)."""
    validos = (landsat_arr != 0) & (s2_agg_arr != 0)
    n_validos = int(validos.sum())
    if n_validos == 0:
        return {"n_pixels_comparados": 0}

    concordam = landsat_arr[validos] == s2_agg_arr[validos]
    pct_geral = 100.0 * float(concordam.sum()) / n_validos

    borda_mask = _mascara_borda(landsat_arr) & validos
    interior_mask = validos & ~_mascara_borda(landsat_arr)

    def _pct(mask: np.ndarray) -> float | None:
        n = int(mask.sum())
        if n == 0:
            return None
        return 100.0 * float((landsat_arr[mask] == s2_agg_arr[mask]).sum()) / n

    matriz = np.zeros((5, 5), dtype=np.int64)  # [landsat_classe-1, s2_classe-1]
    for i, ci in enumerate(CLASS_IDS):
        for j, cj in enumerate(CLASS_IDS):
            matriz[i, j] = int(np.sum(validos & (landsat_arr == ci) & (s2_agg_arr == cj)))

    concordancia_por_classe: dict[int, float | None] = {}
    for c in CLASS_IDS:
        mask_c = validos & (landsat_arr == c)
        n_c = int(mask_c.sum())
        concordancia_por_classe[c] = (
            100.0 * float((s2_agg_arr[mask_c] == c).sum()) / n_c if n_c else None
        )

    return {
        "n_pixels_comparados": n_validos,
        "pct_concordancia_geral": round(pct_geral, 3),
        "n_pixels_borda": int(borda_mask.sum()),
        "pct_concordancia_borda": round(_pct(borda_mask), 3) if _pct(borda_mask) is not None else None,
        "n_pixels_interior": int(interior_mask.sum()),
        "pct_concordancia_interior": (
            round(_pct(interior_mask), 3) if _pct(interior_mask) is not None else None
        ),
        "matriz_confusao": matriz,  # linhas/colunas na ordem de CLASS_IDS
        "concordancia_por_classe": concordancia_por_classe,
    }


# --------------------------------------------------------------------------------------------
# Comparação completa de 1 par (site, ano de sobreposição)
# --------------------------------------------------------------------------------------------


def comparar_par(par: ParSobreposicao) -> dict[str, Any]:
    landsat_arr, landsat_crs, _ = _ler_raster(par.landsat_tif)
    s2_arr, s2_crs, _ = _ler_raster(par.s2_tif)
    if landsat_crs != s2_crs:
        raise ValidacaoError(f"{par.site_id}/{par.ano}: CRS diverge entre sensores ({landsat_crs} vs {s2_crs}).")
    _validar_fator_agregacao(landsat_arr.shape, s2_arr.shape)

    s2_agg = agregar_majoritaria(s2_arr, FATOR_AGREGACAO)
    assert s2_agg.shape == landsat_arr.shape

    area_landsat = area_por_classe_ha(landsat_arr, 30.0)
    area_s2_nativo = area_por_classe_ha(s2_arr, 10.0)
    area_s2_agg = area_por_classe_ha(s2_agg, 30.0)

    pct_landsat = pct_area_valida(landsat_arr)
    pct_s2_nativo = pct_area_valida(s2_arr)
    pct_s2_agg = pct_area_valida(s2_agg)

    linhas_classe = []
    for c in CLASS_IDS:
        diff_total_ha = area_s2_nativo[c] - area_landsat[c]
        diff_resolucao_ha = area_s2_agg[c] - area_s2_nativo[c]
        diff_sensor_ha = area_s2_agg[c] - area_landsat[c]
        linhas_classe.append(
            {
                "site_id": par.site_id,
                "ano": par.ano,
                "classe_id": c,
                "classe_nome": classes.ID_TO_SLUG[c],
                "area_landsat_ha": round(area_landsat[c], 4),
                "area_s2_nativo_ha": round(area_s2_nativo[c], 4),
                "area_s2_agregado30_ha": round(area_s2_agg[c], 4),
                "diff_total_ha": round(diff_total_ha, 4),
                "diff_total_pp": round(pct_s2_nativo[c] - pct_landsat[c], 4),
                "diff_resolucao_ha": round(diff_resolucao_ha, 4),
                "diff_resolucao_pp": round(pct_s2_agg[c] - pct_s2_nativo[c], 4),
                "diff_sensor_isolado_ha": round(diff_sensor_ha, 4),
                "diff_sensor_isolado_pp": round(pct_s2_agg[c] - pct_landsat[c], 4),
            }
        )

    concordancia = concordancia_espacial(landsat_arr, s2_agg)

    return {
        "site_id": par.site_id,
        "ano": par.ano,
        "linhas_classe": linhas_classe,
        "concordancia": concordancia,
        "landsat_arr": landsat_arr,
        "s2_agg_arr": s2_agg,
        "pct_landsat": pct_landsat,
        "pct_s2_nativo": pct_s2_nativo,
    }


# --------------------------------------------------------------------------------------------
# Degrau na série: 2018 (Landsat) -> ano de sobreposição (S2), vs. artefato de sensor no mesmo ano
# --------------------------------------------------------------------------------------------


def quantificar_degrau(
    par: ParSobreposicao,
    linhas_classe_par: list[dict[str, Any]],
    pct_s2_nativo: dict[int, float],
) -> list[dict[str, Any]]:
    """Item 5 do enunciado — o veredito central da tarefa.

    `degrau_publicado`     = area_s2[ano] - area_landsat[2018]  (o que a série oficial mostraria,
                              já que a recomendação de `docs/schema-indicadores.md` é usar S2 como
                              série oficial a partir de 2019).
    `controle_real_landsat`= area_landsat[ano] - area_landsat[2018]  (MESMO sensor nos dois lados —
                              mudança real de terreno em 1 ano, sem confundir com troca de
                              instrumento; só existe porque 2019/2020/2021 têm Landsat também).
    `artefato_sensor`      = diff_total_ha já calculado em `comparar_par` para este (site, ano) —
                              area_s2[ano] - area_landsat[ano], MESMO ano, dois sensores.

    Identidade: degrau_publicado == controle_real_landsat + artefato_sensor (checada como teste de
    sanidade). O veredito compara |artefato_sensor| com |controle_real_landsat|: se o artefato for
    da mesma ordem de grandeza (ou maior), o degrau publicado não é distinguível de um artefato de
    troca de sensor.
    """
    landsat_2018_arr, _, _ = _ler_raster(par.landsat_2018_tif)
    area_landsat_2018 = area_por_classe_ha(landsat_2018_arr, 30.0)
    pct_landsat_2018 = pct_area_valida(landsat_2018_arr)

    por_classe = {linha["classe_id"]: linha for linha in linhas_classe_par}

    saida = []
    for c in CLASS_IDS:
        linha_par = por_classe[c]
        area_s2_ano = linha_par["area_s2_nativo_ha"]
        area_landsat_ano = linha_par["area_landsat_ha"]
        artefato_sensor_ha = linha_par["diff_total_ha"]

        degrau_publicado_ha = area_s2_ano - area_landsat_2018[c]
        controle_real_ha = area_landsat_ano - area_landsat_2018[c]

        artefato_abs = abs(artefato_sensor_ha)
        controle_abs = abs(controle_real_ha)
        if controle_abs < 1e-9 and artefato_abs < 1e-9:
            razao = 0.0
        elif controle_abs < 1e-9:
            razao = float("inf")
        else:
            razao = artefato_abs / controle_abs

        if razao == float("inf") or razao >= 0.5:
            veredito = "NAO_DISTINGUIVEL"  # artefato >= metade do sinal real -> não dá pra confiar
        else:
            veredito = "DISTINGUIVEL"

        degrau_publicado_pp = pct_s2_nativo[c] - pct_landsat_2018[c]

        saida.append(
            {
                "site_id": par.site_id,
                "ano_overlap": par.ano,
                "classe_id": c,
                "classe_nome": classes.ID_TO_SLUG[c],
                "area_landsat_2018_ha": round(area_landsat_2018[c], 4),
                "area_landsat_ano_ha": round(area_landsat_ano, 4),
                "area_s2_ano_ha": round(area_s2_ano, 4),
                "degrau_publicado_ha": round(degrau_publicado_ha, 4),
                "degrau_publicado_pp": round(degrau_publicado_pp, 4),
                "controle_real_landsat_ha": round(controle_real_ha, 4),
                "artefato_sensor_ha": round(artefato_sensor_ha, 4),
                "razao_artefato_sobre_controle": round(razao, 3) if razao != float("inf") else None,
                "veredito": veredito,
            }
        )
    return saida


# --------------------------------------------------------------------------------------------
# Estabilidade do fator — DUAS perguntas distintas (item 4b / cenário 5 do enunciado)
# --------------------------------------------------------------------------------------------

AREA_LANDSAT_MINIMA_PARA_FATOR_HA = 5.0  # abaixo disso, fator multiplicativo é ruído (quase /0)


def fator_multiplicativo_por_site_ano(df_classe: pd.DataFrame) -> pd.DataFrame:
    """`fator_mult` = area_s2_agregado30_ha / area_landsat_ha, a MESMA resolução (30 m) nos dois
    lados — isola o efeito de sensor (não resolução), é o que de fato se aplicaria como correção.
    Linhas com `area_landsat_ha` abaixo de `AREA_LANDSAT_MINIMA_PARA_FATOR_HA` viram NaN (fator
    multiplicativo de uma base quase-zero explode e não significa nada)."""
    df = df_classe.copy()
    base_valida = df["area_landsat_ha"] >= AREA_LANDSAT_MINIMA_PARA_FATOR_HA
    df["fator_mult"] = np.where(base_valida, df["area_s2_agregado30_ha"] / df["area_landsat_ha"], np.nan)
    return df[["site_id", "ano", "classe_id", "classe_nome", "area_landsat_ha", "area_s2_agregado30_ha", "fator_mult"]]


def estabilidade_fator(df_fator: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 1 — ESTABILIDADE DENTRO DO SITE: para cada (site_id, classe_id), o fator
    calculado em 2019/2020/2021 separadamente é consistente entre si (cenário de teste 5, lido
    literalmente por site)? CV = desvio-padrão / média do `fator_mult` entre os 3 anos daquele
    site."""
    g = df_fator.dropna(subset=["fator_mult"]).groupby(["site_id", "classe_id", "classe_nome"])["fator_mult"]
    resumo = g.agg(n_anos="count", media="mean", desvio="std", minimo="min", maximo="max").reset_index()
    resumo["desvio"] = resumo["desvio"].fillna(0.0)
    resumo["cv"] = np.where(resumo["media"].abs() > 1e-6, resumo["desvio"] / resumo["media"].abs(), np.nan)
    return resumo


def heterogeneidade_entre_sites(df_estab_intra: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 2 — a pergunta que o enunciado NÃO faz explicitamente, mas que decide se um fator
    é seguro de aplicar: o fator (já com média de 3 anos por site) é PARECIDO entre os 16 sites, ou
    cada site tem seu próprio número? Um fator estável ano a ano DENTRO de um site pode ainda ser
    inútil como número único nacional se variar demais DE SITE PARA SITE (Simpson: a média pooled
    pode parecer estável só porque os anos são parecidos entre si, escondendo que cada site precisa
    do seu próprio fator). CV calculado sobre a `media` por site (não sobre as observações
    individuais ano a ano, que é a pergunta 1)."""
    g = df_estab_intra.groupby(["classe_id", "classe_nome"])["media"]
    resumo = g.agg(n_sites="count", media_entre_sites="mean", desvio_entre_sites="std",
                    minimo="min", maximo="max").reset_index()
    resumo["cv_entre_sites"] = resumo["desvio_entre_sites"] / resumo["media_entre_sites"].abs()
    return resumo


# --------------------------------------------------------------------------------------------
# Execução completa + geração de artefatos
# --------------------------------------------------------------------------------------------


def rodar_validacao(modelo_versao: str, sites: list[str] | None = None) -> dict[str, Any]:
    pares = localizar_pares(modelo_versao, sites)
    print(f"[validacao_sensores] {len(pares)} pares site x ano de sobreposição localizados.")

    todas_linhas_classe: list[dict[str, Any]] = []
    todas_linhas_degrau: list[dict[str, Any]] = []
    resumo_concordancia: list[dict[str, Any]] = []
    matriz_confusao_total = np.zeros((5, 5), dtype=np.int64)

    for i, par in enumerate(pares, start=1):
        resultado = comparar_par(par)
        todas_linhas_classe.extend(resultado["linhas_classe"])

        conc = resultado["concordancia"]
        matriz_confusao_total += conc["matriz_confusao"]
        resumo_concordancia.append(
            {
                "site_id": par.site_id,
                "ano": par.ano,
                "n_pixels_comparados": conc["n_pixels_comparados"],
                "pct_concordancia_geral": conc["pct_concordancia_geral"],
                "n_pixels_borda": conc["n_pixels_borda"],
                "pct_concordancia_borda": conc["pct_concordancia_borda"],
                "n_pixels_interior": conc["n_pixels_interior"],
                "pct_concordancia_interior": conc["pct_concordancia_interior"],
                **{
                    f"concordancia_classe_{classes.ID_TO_SLUG[c]}": conc["concordancia_por_classe"][c]
                    for c in CLASS_IDS
                },
            }
        )

        degrau = quantificar_degrau(par, resultado["linhas_classe"], resultado["pct_s2_nativo"])
        todas_linhas_degrau.extend(degrau)

        if i % 12 == 0 or i == len(pares):
            print(f"[validacao_sensores] {i}/{len(pares)} pares processados — último: {par.site_id}/{par.ano}")

    df_classe = pd.DataFrame(todas_linhas_classe)
    df_degrau = pd.DataFrame(todas_linhas_degrau)
    df_concordancia = pd.DataFrame(resumo_concordancia)
    df_fator = fator_multiplicativo_por_site_ano(df_classe)
    df_estabilidade = estabilidade_fator(df_fator)
    df_heterogeneidade = heterogeneidade_entre_sites(df_estabilidade)

    # Checagem de sanidade: identidade algébrica diff_total == diff_sensor_isolado - diff_resolucao
    residuo_identidade = (
        df_classe["diff_total_ha"] - (df_classe["diff_sensor_isolado_ha"] - df_classe["diff_resolucao_ha"])
    ).abs()
    if (residuo_identidade > 1e-6).any():
        raise ValidacaoError(
            f"identidade diff_total = diff_sensor_isolado - diff_resolucao falhou em "
            f"{(residuo_identidade > 1e-6).sum()} linha(s) — bug na decomposição."
        )

    # Checagem de sanidade: identidade do degrau (item "Sanidade" — não é cenário oficial, mas é
    # a mesma lógica algébrica aplicada ao degrau)
    residuo_degrau = (
        df_degrau["degrau_publicado_ha"]
        - (df_degrau["controle_real_landsat_ha"] + df_degrau["artefato_sensor_ha"])
    ).abs()
    if (residuo_degrau > 1e-6).any():
        raise ValidacaoError("identidade degrau_publicado = controle_real + artefato_sensor falhou.")

    return {
        "df_classe": df_classe,
        "df_degrau": df_degrau,
        "df_concordancia": df_concordancia,
        "df_fator": df_fator,
        "df_estabilidade": df_estabilidade,
        "df_heterogeneidade": df_heterogeneidade,
        "matriz_confusao_total": matriz_confusao_total,
        "n_pares": len(pares),
    }


def salvar_csvs(resultado: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    resultado["df_classe"].to_csv(OUT_DIR / "diferenca_area_por_classe.csv", index=False)
    resultado["df_degrau"].to_csv(OUT_DIR / "degrau_2018_vs_overlap.csv", index=False)
    resultado["df_concordancia"].to_csv(OUT_DIR / "concordancia_espacial_por_par.csv", index=False)
    resultado["df_estabilidade"].to_csv(OUT_DIR / "estabilidade_fator_por_site_classe.csv", index=False)
    resultado["df_heterogeneidade"].to_csv(OUT_DIR / "heterogeneidade_fator_entre_sites.csv", index=False)

    matriz = resultado["matriz_confusao_total"]
    df_matriz = pd.DataFrame(
        matriz,
        index=[f"landsat_{classes.ID_TO_SLUG[c]}" for c in CLASS_IDS],
        columns=[f"s2agg30_{classes.ID_TO_SLUG[c]}" for c in CLASS_IDS],
    )
    df_matriz.to_csv(OUT_DIR / "matriz_confusao_agregada.csv")


def gerar_grafico_serie(df_area_por_classe_csv: Path, out_path: Path) -> Path | None:
    """Gráfico da série 2013-2025 (área agregada nos 16 sites, classes 3 e 4) com a sobreposição
    2019-2021 destacada e as duas séries (Landsat/S2) plotadas lado a lado nesse trecho — item 5 do
    enunciado do relatório. Usa `outputs/indicadores/area_por_classe.csv` (SV-15), que já cobre
    todos os anos 2013-2025, não só o período de sobreposição."""
    if not df_area_por_classe_csv.exists():
        print(f"[validacao_sensores] {df_area_por_classe_csv} não existe — pulando gráfico da série.")
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.read_csv(df_area_por_classe_csv)
    df = df[df["classe_id"].isin(CLASSES_CRITICAS)]
    agregado = df.groupby(["ano", "sensor", "classe_id", "classe_nome"])["area_ha"].sum().reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharex=True)
    cores_sensor = {"landsat": "#B03A2E", "sentinel2": "#1565C0"}
    marcadores_sensor = {"landsat": "o", "sentinel2": "s"}

    for ax, classe_id in zip(axes, CLASSES_CRITICAS, strict=True):
        sub = agregado[agregado["classe_id"] == classe_id]
        nome = classes.CLASSES[classe_id]["nome_exibicao"]
        for sensor, cor in cores_sensor.items():
            s = sub[sub["sensor"] == sensor].sort_values("ano")
            if s.empty:
                continue
            ax.plot(
                s["ano"], s["area_ha"], marker=marcadores_sensor[sensor], color=cor,
                label=f"{sensor}", linewidth=1.8, markersize=5,
            )
        ax.axvspan(2018.5, 2021.5, color="grey", alpha=0.15, label="sobreposição (2019-2021)")
        ax.axvline(2018.5, color="black", linestyle="--", linewidth=1, alpha=0.6)
        ax.set_title(f"{nome} — soma dos 16 sites")
        ax.set_xlabel("Ano")
        ax.set_ylabel("Área (ha)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)

    fig.suptitle(
        "Série 2013-2025 — classes críticas, com o período de sobreposição destacado\n"
        "(as duas linhas dentro da faixa cinza são o MESMO ano, dois sensores — a distância entre "
        "elas é o viés medido por SV-20)",
        fontsize=10,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------------------------
# Decisão de tratamento (item 4 do enunciado) — a partir dos dados calculados, não a priori
# --------------------------------------------------------------------------------------------


CV_INTRA_SITE_LIMIAR = 0.30  # cenário 5 do enunciado, lido por site: fator estável entre os 3 anos
FRACAO_INTRA_MINIMA = 0.70  # pelo menos 70% dos sites precisam passar no CV intra-site
CV_ENTRE_SITES_LIMIAR = 0.35  # pergunta extra (heterogeneidade): fator parecido de site pra site?


def decidir_tratamento(resultado: dict[str, Any]) -> dict[str, Any]:
    """Decide o tratamento (a/b/c) POR CLASSE crítica (3 e 4), a partir de DUAS perguntas
    distintas sobre o `fator_mult` (área S2-agregada-30m / área Landsat, mesma resolução —
    isola sensor de resolução):

      1. **Estabilidade dentro do site** (cenário de teste 5 do enunciado, lido por site): o fator
         calculado em 2019/2020/2021 separadamente é parecido entre si NAQUELE site? CV < 0.30 em
         pelo menos 70% dos 16 sites.
      2. **Heterogeneidade entre sites** (pergunta que o enunciado não faz explicitamente, mas que
         decide se um fator faz sentido aplicar de uma vez): mesmo que o fator seja estável DENTRO
         de cada site, ele é PARECIDO de um site pro outro? Um fator estável ano a ano mas que varia
         de 3,5x a 23x entre sites (medido abaixo, classe 3) não é "um" fator — é 16 fatores
         diferentes que só parecem um porque a média entre anos esconde a variação entre sites
         (viés de agregação, o mesmo raciocínio do paradoxo de Simpson).

    Regra: (b) só é escolhido se as DUAS perguntas passarem — estabilidade sozinha não basta.
    Quando (b) passa, o fator aplicado é o **por site** (média dos 3 anos daquele site), nunca um
    número nacional único — isso é o que a pergunta 2 está checando que seja seguro fazer.
    Quando (b) falha, o tratamento cai para (c) — publicar em faixas separadas, sem emendar — e
    NÃO para (a), porque o viés medido é grande demais (SV-15 já tinha medido 6,6-18,4 p.p. em
    classe 3) para ser declarado "dentro da tolerância" e ignorado.
    """
    df_estab = resultado["df_estabilidade"]
    df_heter = resultado["df_heterogeneidade"]
    df_fator = resultado["df_fator"]

    por_classe: dict[int, dict[str, Any]] = {}
    for c in CLASSES_CRITICAS:
        estab_c = df_estab[df_estab["classe_id"] == c]
        n_avaliaveis = int(estab_c["cv"].notna().sum())
        n_estaveis = int((estab_c["cv"].notna() & (estab_c["cv"] < CV_INTRA_SITE_LIMIAR)).sum())
        frac_estavel = n_estaveis / n_avaliaveis if n_avaliaveis else 0.0
        pergunta1_ok = frac_estavel >= FRACAO_INTRA_MINIMA

        heter_c = df_heter[df_heter["classe_id"] == c]
        cv_entre_sites = float(heter_c["cv_entre_sites"].iloc[0]) if len(heter_c) else None
        pergunta2_ok = cv_entre_sites is not None and cv_entre_sites < CV_ENTRE_SITES_LIMIAR

        elegivel_b = pergunta1_ok and pergunta2_ok

        # fator por site (média dos 3 anos), usado se elegivel_b == True
        fator_por_site = (
            df_fator[df_fator["classe_id"] == c]
            .groupby("site_id")["fator_mult"]
            .mean()
            .round(4)
            .to_dict()
        )

        if elegivel_b:
            tratamento = "b"
            justificativa = (
                f"fator estável dentro do site em {n_estaveis}/{n_avaliaveis} ({frac_estavel:.0%}) "
                f"dos sites (CV<{CV_INTRA_SITE_LIMIAR}) E parecido entre sites (CV entre sites = "
                f"{cv_entre_sites:.3f} < {CV_ENTRE_SITES_LIMIAR}) — aplicável um fator "
                "multiplicativo POR SITE (não um número nacional único), calibrado na média dos 3 "
                "anos de sobreposição."
            )
        else:
            motivos = []
            if not pergunta1_ok:
                motivos.append(
                    f"instável dentro do site em {n_avaliaveis - n_estaveis}/{n_avaliaveis} sites "
                    f"(só {frac_estavel:.0%} < limiar de {FRACAO_INTRA_MINIMA:.0%})"
                )
            if not pergunta2_ok:
                motivos.append(
                    f"heterogêneo entre sites (CV={cv_entre_sites:.3f} >= {CV_ENTRE_SITES_LIMIAR})"
                    if cv_entre_sites is not None
                    else "heterogeneidade entre sites não calculável"
                )
            tratamento = "c"
            justificativa = (
                "fator " + " e ".join(motivos) + " — calibrar em 3 anos e aplicar aos outros 6 anos "
                "da era Landsat seria chute, não correção. Publicar em faixas separadas (sem emendar "
                "a série) é a opção defensável."
            )

        por_classe[c] = {
            "tratamento": tratamento,
            "justificativa": justificativa,
            "n_avaliaveis": n_avaliaveis,
            "n_estaveis": n_estaveis,
            "frac_estavel": frac_estavel,
            "cv_entre_sites": cv_entre_sites,
            "fator_por_site": fator_por_site,
        }

    medias_criticas = (
        resultado["df_classe"][resultado["df_classe"]["classe_id"].isin(CLASSES_CRITICAS)]
        .groupby("classe_id")[["diff_total_ha", "diff_resolucao_ha", "diff_sensor_isolado_ha"]]
        .mean()
    )

    return {"por_classe": por_classe, "medias_criticas": medias_criticas}


# --------------------------------------------------------------------------------------------
# Artefato de correção — consumido por export_indicadores.py (SV-15), item 6 do enunciado
# --------------------------------------------------------------------------------------------

FATOR_CORRECAO_PATH = REPO_ROOT / "data" / "manifests" / "fator_correcao_sensor_sv20.json"


def escrever_artefato_correcao(decisao: dict[str, Any], modelo_versao: str, n_pares: int) -> Path:
    """Grava o resultado da decisão de tratamento num JSON que `export_indicadores.py` lê para
    popular `fator_correcao_sensor` e a nova coluna `faixa_serie` de
    `outputs/indicadores/area_por_classe.csv` — sem isso, a correção calculada aqui nunca chegaria
    no CSV que a frente de Indicadores consome (item 6 do enunciado de SV-20: "propagar")."""
    payload: dict[str, Any] = {
        "gerado_em": datetime.now(UTC).isoformat(),
        "modelo_versao": modelo_versao,
        "n_pares_sobreposicao": n_pares,
        "metodo": (
            "fator_mult = area_s2_agregado_30m_ha / area_landsat_ha (MESMA resolução, 30 m nos "
            "dois lados — isola sensor de resolução), média dos 3 anos de sobreposição (2019-2021), "
            "POR SITE. Só aplicado se estável dentro do site (CV<0.30 entre anos) E parecido entre "
            "sites (CV<0.35 entre a média dos 16 sites) — ver validacao_sensores.decidir_tratamento."
        ),
        "classes": {},
    }
    for c, info in decisao["por_classe"].items():
        payload["classes"][str(c)] = {
            "classe_nome": classes.ID_TO_SLUG[c],
            "tratamento": info["tratamento"],
            "justificativa": info["justificativa"],
            "fator_por_site": info["fator_por_site"] if info["tratamento"] == "b" else {},
        }
    FATOR_CORRECAO_PATH.parent.mkdir(parents=True, exist_ok=True)
    FATOR_CORRECAO_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return FATOR_CORRECAO_PATH


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SV-20 — validação cruzada entre sensores no período de sobreposição."
    )
    parser.add_argument("--modelo", required=True, help="caminho do .joblib, ex.: models/rf_v1.0.joblib")
    parser.add_argument("--site", default=None, help="restringe a 1 site_id (default: todos os 16 ativos)")
    args = parser.parse_args(argv)

    modelo_versao = Path(args.modelo).stem
    sites = [args.site] if args.site else None

    print(f"[validacao_sensores] modelo_versao={modelo_versao}")
    resultado = rodar_validacao(modelo_versao, sites)
    salvar_csvs(resultado)
    decisao = decidir_tratamento(resultado)
    artefato_correcao = escrever_artefato_correcao(decisao, modelo_versao, resultado["n_pares"])

    grafico = gerar_grafico_serie(
        REPO_ROOT / "outputs" / "indicadores" / "area_por_classe.csv",
        OUT_DIR / "serie_classes_criticas_com_sobreposicao.png",
    )

    for c, info in decisao["por_classe"].items():
        print(f"[validacao_sensores] classe {c} ({classes.ID_TO_SLUG[c]}): tratamento={info['tratamento']} — {info['justificativa']}")
    print(f"[validacao_sensores] artefatos em {OUT_DIR}")
    print(f"[validacao_sensores] fator de correção gravado em {artefato_correcao}")
    if grafico:
        print(f"[validacao_sensores] gráfico: {grafico}")
    print("[validacao_sensores] CONCLUÍDO — rode `python -m sentinela.export_indicadores --modelo-versao "
          f"{modelo_versao}` para propagar a correção pro CSV, e escreva reports/validacao_sensores.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
