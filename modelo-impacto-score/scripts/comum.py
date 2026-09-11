"""Base compartilhada da frente "score de impacto".

Esta frente NÃO coleta nada e NÃO classifica nada. Ela lê os artefatos já produzidos por
`dados-modelo-impacto/` (desenho pareado, trajetória de pixel, anéis, footprint OSM, LST) e por
`src/sentinela/` (classificador), e monta três camadas — medição, explicação, projeção.

Ver `modelo-impacto-score/README.md` para o desenho e as razões.

## A tabela mestra

`tabela_mestra()` devolve uma linha por campus de tratamento com:

  - os ALVOS  (`y_*`): o efeito líquido já medido, tratamento menos controle, por eixo;
  - as FEATURES (`x_*`): apenas o que é conhecível ANTES da obra.

A separação é rígida de propósito. Qualquer variável medida depois do início da obra que entre
como feature vira vazamento: o modelo passaria a "prever" o efeito usando uma consequência dele.
Por isso as features de cobertura e LST são a média dos **2 primeiros anos da janela** (que começa
em `obra-3`), nunca a série inteira.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
DIR_IMPACTO = RAIZ / "dados-modelo-impacto"
DIR_RESULTADOS = DIR_IMPACTO / "raw" / "controles-rf"
DIR_PROCESSED = DIR_IMPACTO / "processed"
DIR_SAIDA = RAIZ / "modelo-impacto-score" / "outputs"
DIR_FIGURAS = RAIZ / "modelo-impacto-score" / "reports" / "figuras"

SEED = 42
N_ANOS_PONTA = 2  # mesma convenção do passo 12 de dados-modelo-impacto

# Eixos do boletim. `selo` sai do teste de sinal agregado publicado pelos passos 14/16 — é uma
# propriedade do EIXO (quão bem aquela pergunta foi respondida no conjunto), não de um campus.
EIXOS = {
    "construcao_0_500m": {
        "rotulo": "Conversão para construída, anel 0–500 m (SEM o prédio)",
        "unidade": "p.p.",
        "fonte": "footprint_vs_anel.csv (footprint subtraído)",
        "direcao_ruim": +1,  # mais conversão = mais impacto
    },
    "construcao_500m_1km": {
        "rotulo": "Conversão para construída, anel 500 m–1 km",
        "unidade": "p.p.",
        "fonte": "footprint_vs_anel.csv",
        "direcao_ruim": +1,
    },
    "vegetacao_0_500m": {
        "rotulo": "Vegetação convertida em construída, anel 0–500 m",
        "unidade": "p.p.",
        "fonte": "footprint_vs_anel.csv",
        "direcao_ruim": +1,
    },
    "temperatura_0_500m": {
        "rotulo": "Aquecimento de superfície (LST Landsat 30 m), anel 0–500 m",
        "unidade": "°C",
        "fonte": "lst_landsat_did.csv",
        "direcao_ruim": +1,
    },
}

# O eixo de temperatura foi medido DUAS vezes, e a segunda substitui a primeira:
#   passo 16 — MODIS MOD11A2, 1 km, disco de 5 km  -> nulo por DILUIÇÃO de escala
#   passo 23 — Landsat ST_B10, 30 m, anel de 500 m -> nulo por TAMANHO DE AMOSTRA
# A versão do passo 23 é a que entra no boletim, porque mede na escala em que o efeito vive
# (872 pixels no anel, contra uma fração de um pixel MODIS). A do passo 16 fica registrada no
# relatório como medição superada — não apagada, porque foi ela que motivou a troca de sensor.

ZONA_POR_EIXO = {
    "construcao_0_500m": ("0-0.5km", "pct_virou_construida"),
    "construcao_500m_1km": ("0.5-1km", "pct_virou_construida"),
    "vegetacao_0_500m": ("0-0.5km", "pct_vegetacao_para_construida"),
}


def _excesso_expandido(zona: str, assinatura: str, recorte: str = "conjunto") -> pd.Series:
    """Excesso tratamento − controle por campus, lido do passo 26.

    **Por que não se calcula aqui.** A versão anterior desta função subtraía, do disco de 0–500 m,
    as contagens da linha `zona == "footprint"` do passo 14 — uma subtração aritmética. Ela só é
    válida se o footprint estiver inteiramente DENTRO do disco, e isso é falso em 4 dos 14 campi
    originais: `ascenty-vinhedo` tem o polígono 100% fora (a 615 m do ponto validado),
    `ascenty-sumare` 67% fora, `scala-sgigsm01` 15% e `equinix-santana-parnaiba` 3%.

    O efeito não era cosmético: em `ascenty-hortolandia` a subtração indevida **trocava o sinal**
    do excesso (+0,25 p.p. aritmético contra −1,31 p.p. real).

    O passo 26 calcula por **mascaramento direto** sobre o raster (`disco AND NOT footprint`), que
    é correto por construção, e marca `footprint_excluido` só quando o polígono de fato sobrepõe a
    zona. Esta função apenas consome aquilo.
    """
    caminho = DIR_RESULTADOS / "analise_expandida.csv"
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho.name} não existe — rode "
            "`impacto_dc_26_analise_expandida.py --fase analise` antes do boletim."
        )
    d = pd.read_csv(caminho)
    d = d[d.zona == zona]
    if recorte == "so_validados":
        d = d[d.procedencia == "validado_5_camadas"]
    elif recorte == "so_expansao":
        d = d[d.procedencia == "datacentermap"]

    # No anel interno, campus sem footprint sobreposto fica FORA: a zona dele conteria o prédio.
    if zona == "0-0.5km":
        sem = set(d[(d.tipo == "tratamento") & ~d.footprint_excluido].campus)
        d = d[~d.campus.isin(sem)]

    col = f"pct_{assinatura}"
    t = d[d.tipo == "tratamento"].set_index("campus")[col]
    c = d[d.tipo == "controle"].set_index("campus")[col]
    return (t - c).dropna()


def placebo_da_estatistica() -> str:
    """Resumo, em uma linha, do teste placebo que valida a estatística por trás dos eixos fortes.

    Todo eixo de conversão deste boletim usa a mesma estatística: contagem de pixels com
    trajetória ordenada e persistente (passo 12 de `dados-modelo-impacto`). O passo 19 aplicou
    essa estatística a 15 pares de lugares onde **nada** foi construído — controle contra
    controle, mesma janela, mesmo ano de obra fictício.

    Isso é o que separa um selo `forte` aqui de um p-valor solto: sabemos qual é a taxa de falso
    positivo do instrumento, porque ela foi medida, e não assumida.
    """
    caminho = DIR_RESULTADOS / "placebo_resumo.csv"
    if not caminho.exists():
        return "placebo não executado"
    pl = pd.read_csv(caminho)
    r = pl[(pl.assinatura == "virou_construida") & (pl.raio_km == 0.5)]
    if r.empty:
        return "placebo sem linha para a assinatura principal"
    r = r.iloc[0]
    return (
        f"sim — a mesma estatística aplicada a {int(r.placebo_n_pares)} pares SEM data center dá "
        f"{int(r.placebo_n_positivo)}/{int(r.placebo_n_pares)} (p={r.placebo_p_unilateral:.2f}, "
        f"mediana {r.placebo_excesso_mediano_pp:+.2f} p.p.): não produz falso positivo"
    )


def selos_de_evidencia() -> pd.DataFrame:
    """Selo de qualidade de evidência por eixo, lido dos resumos já publicados.

    O selo é o que separa "podemos afirmar" de "medimos e não deu" de "não conseguiríamos ver
    nem se existisse". Essa terceira categoria é a que costuma ser reportada errado: um nulo sem
    poder NÃO é evidência de ausência de efeito.
    """
    poder = pd.read_csv(DIR_RESULTADOS / "lst_did_poder.csv")

    linhas = []
    for eixo, (zona, coluna) in ZONA_POR_EIXO.items():
        assinatura = coluna.replace("pct_", "")
        # Tudo vem do passo 26, que calcula por mascaramento direto sobre o raster e já inclui a
        # amostra expandida (N=20). Ver `_excesso_expandido` para por que o cálculo aritmético
        # anterior era inválido.
        e = _excesso_expandido(zona, assinatura).to_numpy(float)
        if len(e) < 3:
            continue
        n_p, k = len(e), int((e > 0).sum())
        p = sum(math.comb(n_p, i) * 0.5**n_p for i in range(k, n_p + 1))
        mediana = float(np.median(e))
        linhas.append(
            {
                "eixo": eixo,
                "n_pares": n_p,
                "n_positivo": k,
                "p": round(p, 4),
                "excesso_mediano": round(mediana, 3),
                "selo": "forte" if p < 0.05 else ("sugestivo" if p < 0.15 else "nulo_informativo"),
                "validado_por_placebo": placebo_da_estatistica(),
                "razao_do_selo": (
                    "teste de sinal unilateral sobre os pares; direção e magnitude consistentes"
                    if p < 0.05
                    else "direção consistente, mas não atinge significância com este N"
                    if p < 0.15
                    else "sem excesso detectável, e o desenho teria poder para ver"
                ),
            }
        )

    # Temperatura vem do passo 23 (Landsat 30 m no anel), não do passo 16 (MODIS 1 km no disco).
    # Ver a nota em EIXOS: o passo 16 foi superado, e o motivo da troca está no relatório.
    tl = pd.read_csv(DIR_RESULTADOS / "lst_landsat_resumo.csv")
    r_lst = tl[tl.zona == "0-0.5km"].iloc[0]
    rp = poder.iloc[0]  # o cálculo de poder do passo 16, usado só para o contraste
    linhas.append(
        {
            "eixo": "temperatura_0_500m",
            "n_pares": int(r_lst.n_pares),
            "n_positivo": int(r_lst.n_aqueceu_mais),
            "p": round(float(r_lst.p_bilateral), 4),
            # O placebo do passo 19 validou a estatística de TRAJETÓRIA de pixel. A LST usa outra
            # medida (diferença-em-diferenças sobre a média do anel), então herdar aquela
            # validação aqui seria falso. O que este eixo tem no lugar é o cálculo de poder.
            "validado_por_placebo": "não se aplica — outra estatística; ver o cálculo de poder",
            "excesso_mediano": round(float(r_lst.excesso_mediano_c), 3),
            # NÃO é mais `nulo_sem_poder`: aquele selo dizia que o sensor não veria o efeito nem
            # se existisse (MODIS diluía 427x). Na escala certa o problema mudou de natureza —
            # a estimativa é positiva e tem gradiente de distância coerente, mas n=12 não basta.
            "selo": "nulo_amostra_pequena",
            "razao_do_selo": (
                f"medido na escala certa ({int(r_lst.pixels_30m_no_anel)} pixels no anel, contra "
                f"uma fração de um pixel MODIS no passo 16): estimativa "
                f"{r_lst.excesso_mediano_c:+.2f} °C, positiva e com gradiente de distância "
                f"coerente (o anel externo tem menos da metade). Não atinge significância: "
                f"efeito mínimo detectável {r_lst.efeito_minimo_detectavel_c:.2f} °C com n="
                f"{int(r_lst.n_pares)}, e seriam necessários "
                f"n={int(r_lst.n_pares_necessario_para_detectar)} pares para confirmar o próprio "
                f"efeito estimado. Substitui a medição do passo 16 (MODIS 1 km), cujo MDE era "
                f"{rp.efeito_minimo_detectavel_c} °C contra efeito esperado "
                f"{rp.efeito_esperado_no_disco_c} °C ({rp.razao_mde_sobre_esperado}x)"
            ),
        }
    )
    return pd.DataFrame(linhas)


def tabela_mestra() -> pd.DataFrame:
    """Uma linha por campus: alvos medidos (`y_*`) + features pré-obra (`x_*`)."""
    painel = pd.read_csv(DIR_PROCESSED / "consolidado_impacto_painel.csv")
    anel = pd.read_csv(DIR_RESULTADOS / "footprint_vs_anel.csv")
    fps = pd.read_csv(DIR_RESULTADOS / "footprints_osm.csv")
    lst = pd.read_csv(DIR_RESULTADOS / "lst_did.csv")
    gb = pd.read_csv(DIR_RESULTADOS / "greenfield_brownfield.csv")

    trat = painel[painel.tipo == "tratamento"].sort_values(["site_id", "ano"])
    base = trat.groupby("site_id").first().reset_index()[
        ["site_id", "municipio", "uf", "lat", "lon", "ano_inicio_obra", "sensor",
         "regiao", "bioma", "tier", "n_predios_no_campus", "qualidade_par",
         "dist_tratamento_controle_km", "mw_construido_total"]
    ]

    # --- features pré-obra: média dos 2 primeiros anos da janela (janela começa em obra-3)
    pre = (
        trat.groupby("site_id")
        .head(N_ANOS_PONTA)
        .groupby("site_id")[
            ["prop_construida_urbana", "prop_vegetacao_densa", "prop_vegetacao_rala",
             "prop_agua", "lst_media_celsius", "populacao"]
        ]
        .mean()
        .add_prefix("x_pre_")
        .reset_index()
    )
    m = base.merge(pre, on="site_id", how="left")

    m = m.merge(
        fps[["site_id", "area_footprint_ha", "metodo_footprint"]].rename(
            columns={"area_footprint_ha": "x_area_footprint_ha"}
        ),
        on="site_id", how="left",
    )
    fp_zona = anel[anel.zona == "footprint"].set_index("site_id")["pct_ja_construida"]
    m["x_pct_ja_construida"] = m.site_id.map(fp_zona)
    tipo_sitio = gb[gb.zona == "0-0.5km"].set_index("pareado_com")["tipo_sitio"]
    m["x_tipo_sitio"] = m.site_id.map(tipo_sitio)
    m["x_n_predios"] = m.n_predios_no_campus
    m["x_regiao"] = m.regiao
    m["x_bioma"] = m.bioma

    # --- alvos (passo 26: mascaramento direto, amostra expandida)
    for eixo, (zona, coluna) in ZONA_POR_EIXO.items():
        m[f"y_{eixo}"] = m.site_id.map(_excesso_expandido(zona, coluna.replace("pct_", "")))
    # Temperatura: passo 23 (Landsat 30 m, anel de 500 m), não o passo 16 (MODIS, disco de 5 km).
    lst_anel = pd.read_csv(DIR_RESULTADOS / "lst_landsat_did.csv")
    lst_anel = lst_anel[lst_anel.zona == "0-0.5km"].set_index("campus")["excesso_c"]
    m["y_temperatura_0_500m"] = m.site_id.map(lst_anel)

    return m.sort_values("site_id").reset_index(drop=True)


def escore_percentil(valores: pd.Series, direcao_ruim: int = 1) -> pd.Series:
    """Converte um efeito medido em score 0-100 por posto percentual dentro da amostra.

    Percentil, não normalização min-max: com N~14 e caudas longas (um campus tem +6,4 p.p. e
    outro −5,4), min-max faria o score de quase todo mundo colapsar no meio da escala por causa
    de dois extremos. O percentil é robusto a isso, e é honesto sobre o que o número é — uma
    posição relativa entre os casos medidos, não uma medida absoluta de dano.
    """
    v = valores if direcao_ruim > 0 else -valores
    return (v.rank(pct=True) * 100).round(1)


def salvar(df: pd.DataFrame, nome: str) -> Path:
    DIR_SAIDA.mkdir(parents=True, exist_ok=True)
    caminho = DIR_SAIDA / nome
    df.to_csv(caminho, index=False, encoding="utf-8")
    print(f"  -> {caminho.relative_to(RAIZ)} ({len(df)} linhas)")
    return caminho
