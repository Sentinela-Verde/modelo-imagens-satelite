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
    "temperatura": {
        "rotulo": "Aquecimento de superfície (LST), disco de 5 km",
        "unidade": "°C",
        "fonte": "lst_did.csv",
        "direcao_ruim": +1,
    },
}

ZONA_POR_EIXO = {
    "construcao_0_500m": ("0-0.5km", "pct_virou_construida"),
    "construcao_500m_1km": ("0.5-1km", "pct_virou_construida"),
    "vegetacao_0_500m": ("0-0.5km", "pct_vegetacao_para_construida"),
}


def _sem_footprint(anel: pd.DataFrame, zona: str, assinatura: str) -> pd.DataFrame:
    """Recalcula uma zona removendo os pixels do footprint do data center.

    **Por que isto existe.** No passo 14 a zona "0-0.5km" é um DISCO (`r_int == 0`), não um anel:
    ela contém o próprio prédio do data center. Com footprint mediano de 1,29 ha num disco de
    78,5 ha, o prédio é 1,6% da zona — e o excesso medido é ~1,6 ha. Reportar esse número como
    "impacto no entorno" mistura o empreendimento com o efeito dele, e a leitura vira circular:
    *"depois de construir um data center, detectamos um data center."*

    A correção é subtração exata, não estimativa: a linha `zona == "footprint"` traz a contagem de
    pixels válidos e de pixels que cumpriram a assinatura DENTRO do footprint, então basta
    descontar as duas do disco. Não precisa reprocessar raster nenhum.

    Só o tratamento tem footprint; no controle a zona fica inalterada, que é o comportamento certo
    (o controle não tem prédio a descontar, e é justamente a hipótese nula do disco do tratamento).
    """
    disco = anel[anel.zona == zona].set_index("site_id")
    fp = anel[anel.zona == "footprint"].set_index("site_id")

    linhas = []
    for sid, r in disco.iterrows():
        px, marcados = r.pixels_validos_mascara, r[assinatura]
        if sid in fp.index:
            f = fp.loc[sid]
            if pd.notna(f.pixels_validos_mascara) and f.pixels_validos_mascara > 0:
                px = px - f.pixels_validos_mascara
                marcados = marcados - f[assinatura]
        linhas.append(
            {
                "site_id": sid, "pareado_com": r.pareado_com, "tipo": r.tipo,
                f"pct_{assinatura}": 100.0 * marcados / px if px > 0 else np.nan,
            }
        )
    return pd.DataFrame(linhas)


def _excesso_por_zona(anel: pd.DataFrame, zona: str, coluna: str) -> pd.Series:
    """Excesso tratamento − controle de `coluna` na `zona`, indexado por campus.

    Para a zona "0-0.5km" o cálculo passa por `_sem_footprint` — ver a docstring de lá: aquela
    zona é um disco e conteria o próprio prédio.
    """
    assinatura = coluna.replace("pct_", "")
    z = _sem_footprint(anel, zona, assinatura) if zona == "0-0.5km" else anel[anel.zona == zona]
    t = z[z.tipo == "tratamento"].set_index("pareado_com")[coluna]
    c = z[z.tipo == "controle"].set_index("pareado_com")[coluna]
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
    anel = pd.read_csv(DIR_RESULTADOS / "footprint_vs_anel_resumo.csv")
    lst = pd.read_csv(DIR_RESULTADOS / "lst_did_resumo.csv")
    poder = pd.read_csv(DIR_RESULTADOS / "lst_did_poder.csv")

    # A zona 0-0.5km precisa do teste de sinal RECALCULADO sem o footprint — o resumo publicado
    # pelo passo 14 é do disco com o prédio dentro. As demais zonas são anéis de verdade e o
    # resumo serve como está.
    bruto = pd.read_csv(DIR_RESULTADOS / "footprint_vs_anel.csv")

    linhas = []
    for eixo, (zona, coluna) in ZONA_POR_EIXO.items():
        assinatura = coluna.replace("pct_", "")
        if zona == "0-0.5km":
            e = _excesso_por_zona(bruto, zona, coluna).to_numpy(float)
            n_p, k = len(e), int((e > 0).sum())
            p = sum(math.comb(n_p, i) * 0.5**n_p for i in range(k, n_p + 1))
            mediana = float(np.median(e))
        else:
            r0 = anel[(anel.zona == zona) & (anel.assinatura == assinatura)]
            if r0.empty:
                continue
            r0 = r0.iloc[0]
            n_p, k = int(r0.n_pares), int(r0.n_positivo)
            p, mediana = float(r0.p_unilateral), float(r0.excesso_mediano_pp)
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

    rl, rp = lst.iloc[0], poder.iloc[0]
    linhas.append(
        {
            "eixo": "temperatura",
            "n_pares": int(rl.n_pares),
            "n_positivo": int(rl.n_aqueceu_mais_que_controle),
            "p": round(float(rl.p_bilateral), 4),
            # O placebo do passo 19 validou a estatística de TRAJETÓRIA de pixel. A LST usa outra
            # medida (diferença-em-diferenças sobre a média do disco), então herdar aquela
            # validação aqui seria falso. O que este eixo tem no lugar é o cálculo de poder.
            "validado_por_placebo": "não se aplica — outra estatística; ver o cálculo de poder",
            "excesso_mediano": round(float(rl.excesso_mediano_c), 3),
            "selo": "nulo_sem_poder",
            "razao_do_selo": (
                f"efeito mínimo detectável {rp.efeito_minimo_detectavel_c} °C contra efeito "
                f"esperado {rp.efeito_esperado_no_disco_c} °C "
                f"({rp.razao_mde_sobre_esperado}x) — MODIS 1 km num disco de 5 km dilui o sinal; "
                "o nulo não informa sobre a existência do efeito"
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

    # --- alvos
    for eixo, (zona, coluna) in ZONA_POR_EIXO.items():
        m[f"y_{eixo}"] = m.site_id.map(_excesso_por_zona(anel, zona, coluna))
    m["y_temperatura"] = m.site_id.map(lst.set_index("pareado_com")["excesso_c"])

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
