"""Gera e executa `notebooks/02_impacto_score.ipynb` — a demo desta frente.

Rode com:

    python modelo-impacto-score/scripts/04_gerar_notebook.py

O notebook **consome** os artefatos já gerados pelas camadas 1-3 e não recalcula nada pesado —
mesma convenção de `01_modelo_impacto.ipynb` e `00_demo_preview.ipynb`. A única coisa que ele roda
ao vivo é a projeção da camada 3, que é barata (uma consulta a 13 análogos) e é o ponto onde a
demo vira interativa: dá para trocar o `pct_ja_construida` e ver a faixa mudar.

O script escreve o .ipynb e o EXECUTA, deixando as saídas embutidas — assim o notebook abre já
renderizado, sem exigir que quem for olhar tenha o ambiente montado.
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "notebooks" / "02_impacto_score.ipynb"


def md(texto: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(texto.strip("\n"))


def code(texto: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(texto.strip("\n"))


CELULAS = [
    md("""
# Sentinela Verde — modelo de impacto de data centers

**Frente:** `modelo-impacto-score/` · **Data:** 2026-09-10

Este notebook responde três perguntas, nesta ordem:

1. **Quanto** cada data center impactou o território ao redor? *(camada 1 — medição)*
2. **O que explica** o tamanho desse impacto? *(camada 2 — explicação)*
3. Dado um site novo, **que faixa esperar**? *(camada 3 — projeção)*

Ele **consome** os artefatos já gerados pelos scripts da frente — não recalcula nada pesado.
O desenho de pareamento que sustenta tudo aqui está no notebook anterior,
`01_modelo_impacto.ipynb`.

> **Aviso que acompanha todo este notebook:** a resposta da pergunta 2 é **negativa**, e isso é
> um resultado, não uma etapa faltando. O que se sustenta é o padrão; a magnitude não é
> predizível com as features disponíveis.
"""),
    md("## Setup"),
    code("""
from pathlib import Path
import sys


def _find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("não encontrei a raiz do repositório (pyproject.toml) a partir do cwd")


REPO_ROOT = _find_repo_root(Path.cwd())
sys.path.insert(0, str(REPO_ROOT / "modelo-impacto-score" / "scripts"))

import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Image, display

SCORE_DIR = REPO_ROOT / "modelo-impacto-score"
OUT = SCORE_DIR / "outputs"
FIG = SCORE_DIR / "reports" / "figuras"
RES = REPO_ROOT / "dados-modelo-impacto" / "raw" / "controles-rf"
RES_FIG = RES / "figuras"

plt.rcParams["figure.dpi"] = 110
pd.set_option("display.max_columns", 40)
pd.set_option("display.width", 200)

boletim = pd.read_csv(OUT / "boletim_por_eixo.csv")
por_campus = pd.read_csv(OUT / "boletim_por_campus.csv")
selos = pd.read_csv(OUT / "selos_de_evidencia.csv")
modelos = pd.read_csv(OUT / "explicacao_modelos.csv")
features = pd.read_csv(OUT / "explicacao_features.csv")
permutacao = pd.read_csv(OUT / "explicacao_permutacao.csv")
classes_ref = pd.read_csv(OUT / "projecao_classes_referencia.csv")
validacao = pd.read_csv(OUT / "projecao_validacao.csv")

print(f"{por_campus.site_id.nunique()} campi · {len(boletim)} linhas de boletim (campus × eixo)")
"""),
    md("""
---
## 1. Camada 1 — o que foi medido

### Por que não existe um score único

Um número agregado do tipo *"impacto: 73/100"* exigiria pesos arbitrários e misturaria eixos com
qualidade de evidência incompatível — conversão de solo (p=0,0065) somada a temperatura, que com
n=12 não atinge significância. O agregado esconderia a parte forte do trabalho.

O que se publica é um boletim por eixo, cada um com seu **selo de evidência**:
"""),
    code("""
selos[["eixo", "n_pares", "n_positivo", "p", "excesso_mediano", "selo"]]
"""),
    md("""
Os selos de nulo são os que costumam ser reportados errado por aí, e por isso são **dois**:

- `nulo_sem_poder` — *não detectamos nada, e o desenho não detectaria nem se existisse.* Não é
  evidência de ausência de efeito. Foi o caso da primeira medição de temperatura (MODIS 1 km).
- `nulo_amostra_pequena` — *medimos na escala certa, o sinal aponta na direção esperada, mas o N
  não basta para confirmar.* É o caso da segunda medição (Landsat 30 m).

A diferença entre os dois é o que separa "não sabemos" de "não existe". A razão de cada selo está
por extenso na coluna `razao_do_selo`:
"""),
    code("""
for _, r in selos.iterrows():
    print(f"{r.eixo}\\n  selo: {r.selo}\\n  {r.razao_do_selo}\\n")
"""),
    md("""
### O achado central

Em **12 dos 14** campi com par válido, o anel de 500 m ao redor converteu para área construída
mais do que um terreno pareado sem data center. Excesso mediano **+1,50 p.p.**, p=0,0065.

**Esse número exclui o prédio do data center.** A primeira versão desta análise media um *disco*
de 500 m que continha o próprio empreendimento — o que tornava a leitura circular ("depois de
construir um data center, detectamos um data center"). Descontando os pixels do footprint, o
excesso cai de +2,06 para +1,50 p.p. e **os mesmos 12/14 e o mesmo p se mantêm**: ~73% do efeito
está fora da cerca.

Em hectares: o data center mediano tem **1,29 ha**; o excesso convertido fora dele, dentro de
500 m, é **~1,2 ha**. Aproximadamente um hectare a mais se converte ao redor para cada hectare de
data center.

O efeito **decai com a distância e some depois de 1 km** — é localizado no terreno, não é a
região urbanizando por inteiro:

| zona | pares com excesso | p | excesso mediano |
|---|---:|---:|---:|
| 0–0,5 km (sem o prédio) | **12/14** | 0,0065 | +1,50 p.p. |
| 0,5–1 km | **12/14** | 0,0065 | +1,15 p.p. |
| 1–2 km | 8/14 | 0,395 | +0,51 p.p. |
"""),
    code("""
display(Image(filename=str(FIG / "fig_01_boletim.png")))
"""),
    md("""
Repare na ordenação: os campi estão ordenados pelo **quanto do terreno já era construído antes da
obra**. Os dois únicos negativos do estudo — `ascenty-jundiai` (−5,37 p.p.) e `ascenty-sumare`
(−3,08 p.p.) — são os mais saturados, com 86% e 88% já construídos. Num sítio saturado sobra pouco
terreno convertível, e o excesso encolhe por motivo **mecânico**, não por ausência de efeito.
"""),
    md("### O boletim campus a campus"),
    code("""
cols = ["site_id", "municipio", "uf", "x_tipo_sitio", "x_pct_ja_construida",
        "efeito_construcao_0_500m", "score_construcao_0_500m",
        "efeito_vegetacao_0_500m", "efeito_temperatura_0_500m"]
por_campus[cols].rename(columns={
    "x_tipo_sitio": "tipo_sitio",
    "x_pct_ja_construida": "pct_ja_construido",
    "efeito_construcao_0_500m": "constr_0-500m_pp",
    "score_construcao_0_500m": "score_0_100",
    "efeito_vegetacao_0_500m": "veget_0-500m_pp",
    "efeito_temperatura_0_500m": "lst_anel_C",
})
"""),
    md("""
> O `score_0_100` é **posto percentual dentro dos 14 casos medidos** — posição relativa, não medida
> absoluta de dano. Um campus com score 100 é o que mais converteu *nesta amostra*, não "impacto
> máximo possível".

### Temperatura: medida duas vezes, e a segunda história é melhor

**Primeira medição** (MODIS `MOD11A2`, 1 km, disco de 5 km): nulo, −0,07 °C, p=0,61. Mas um nulo
que **não informava nada** — o efeito vive num anel de 500 m, menor que **um pixel** MODIS.

**Segunda medição** (Landsat `ST_B10`, 30 m, anel de 500 m): 872 pixels no anel em vez de uma
fração de um. A estimativa muda de sinal e ganha estrutura espacial coerente.
"""),
    code("""
RES = REPO_ROOT / "dados-modelo-impacto" / "raw" / "controles-rf"

poder = pd.read_csv(RES / "lst_did_poder.csv")
print("PASSO 16 — MODIS 1 km, disco de 5 km")
print(f"  efeito esperado pela diluição : {poder.efeito_esperado_no_disco_c.iloc[0]:.4f} °C")
print(f"  efeito mínimo detectável      : {poder.efeito_minimo_detectavel_c.iloc[0]:.3f} °C")
print(f"  razão                         : {poder.razao_mde_sobre_esperado.iloc[0]:.0f}x"
      "   -> o nulo não informa nada\\n")

ls = pd.read_csv(RES / "lst_landsat_resumo.csv")
print("PASSO 23 — Landsat 30 m, no anel")
for _, r in ls.iterrows():
    print(f"  {r.zona:9s} {int(r.n_aqueceu_mais)}/{int(r.n_pares)} aqueceram mais · "
          f"mediana {r.excesso_mediano_c:+.3f} °C · p={r.p_bilateral:.3f} · "
          f"{int(r.pixels_30m_no_anel)} pixels no anel")
"""),
    code("""
display(Image(filename=str(RES_FIG / "fig_16_lst_landsat.png")))
"""),
    md("""
> **O achado contraintuitivo:** a resolução melhorou **33×** e o poder estatístico **piorou** —
> efeito mínimo detectável 0,822 °C contra 0,636 °C do MODIS.
>
> Porque `MDE = 2,80 × σ / √n`, e trocar de sensor não mexe em nenhum dos dois termos a favor:
> n caiu de 15 para 12 (só os pares Landsat têm banda termal na janela) e o σ entre pares subiu.
> **Resolução e poder estatístico são coisas diferentes**, e este é o contraexemplo limpo disso.

O selo do eixo muda de natureza: sai de `nulo_sem_poder` — *o sensor não veria nem se existisse* —
para `nulo_amostra_pequena`: medimos na escala certa, o sinal aponta para **+0,5 °C** com o
gradiente esperado, e **seriam necessários n=31 pares** para confirmar. Temos 12.

*Ressalva:* LST é temperatura **radiativa de superfície**, não do ar. Para "o entorno esquentou por
causa da conversão de terreno" é a medida certa; para "está mais quente para quem mora ali" é um
limite superior.
"""),
    md("""
### O placebo — a validação que sustenta tudo

A pergunta óbvia contra qualquer achado destes é: *e se o método simplesmente produzisse sinal do
nada?* Aplicamos o método idêntico a **15 pares de lugares onde nenhum data center foi
construído** — controle contra controle, mesma janela, mesmo ano de obra fictício.
"""),
    code("""
placebo = pd.read_csv(RES / "placebo_resumo.csv")
p = placebo[placebo.assinatura == "virou_construida"]
print(f"{'raio':>7s}   {'PLACEBO (sem data center)':34s} REAL")
for _, r in p.iterrows():
    print(f"{r.raio_km:>5.1f}km   "
          f"{int(r.placebo_n_positivo):2d}/{int(r.placebo_n_pares):2d}  p={r.placebo_p_unilateral:.3f}  "
          f"mediana {r.placebo_excesso_mediano_pp:+6.3f} pp      "
          f"{r.real_frac_positivo:.0%}  p={r.real_p_unilateral:.4f}  "
          f"mediana {r.real_excesso_mediano_pp:+6.3f} pp")
print("\\nO placebo cai exatamente no acaso, com sinal trocado em dois dos três raios.")
print("Aplicado onde nada foi construído, o método não acha nada.")
"""),
    code("""
display(Image(filename=str(RES_FIG / "fig_12_placebo.png")))
"""),
    md("""
---
## 2. Camada 2 — o que explica o tamanho do impacto?

O passo 15 da frente anterior achou uma regra de **uma variável** que funciona: sítios *greenfield*
(< 50% do footprint já construído) dão **6/6** pares positivos (p=0,016), contra 5/7 em *brownfield*.

A pergunta desta camada era a única que interessa depois disso:

> **alguma coisa bate `pct_ja_construida` sozinho?**

Testamos 13 modelos contra o baseline "prever a mediana", **todos por validação cruzada
leave-one-out** com N=13. Todo número abaixo é fora-da-amostra.
"""),
    code("""
modelos
"""),
    md("""
**Todos os 13 modelos têm R² negativo** — todos preveem pior que simplesmente dizer "a média" para
todo mundo. Nenhuma feature isolada atinge significância:
"""),
    code("""
features[["feature", "n", "spearman_rho", "spearman_p"]].dropna(subset=["spearman_rho"])
"""),
    md("""
### O teste que fecha a porta

Com 13 pontos e ~8 features candidatas, o melhor R² de um sorteio de **ruído puro** é
surpreendentemente alto. Embaralhamos o alvo 999 vezes e refizemos a busca inteira, para medir
exatamente essa inflação por garimpo:
"""),
    code("""
for c, v in permutacao.iloc[0].items():
    print(f"{c:32s} {v}")
"""),
    code("""
display(Image(filename=str(FIG / "fig_02_explicacao.png")))
"""),
    md("""
### Isto contradiz o achado greenfield/brownfield? Não.

São duas perguntas diferentes, e **as duas respostas estão certas**:

| pergunta | teste | resposta |
|---|---|---|
| a **direção** é consistente? | teste de sinal | **sim** — 6/6 greenfield positivos, p=0,016 |
| a **magnitude** é predizível? | R² LOOCV | **não** — negativo em todos os modelos |

Um teste de sinal pergunta se o efeito aponta para o mesmo lado. Uma regressão pergunta se dá para
prever *o quanto*. Com 13 casos muito heterogêneos — um campus de 400 MW e um prédio de 3 MW,
Manaus e Porto Alegre — a primeira resposta se sustenta e a segunda não.

É exatamente o que o README da frente anterior já suspeitava ao escrever *"a leitura defensável é a
do padrão, não a do coeficiente"*. Agora está medido.
"""),
    md("""
---
## 3. Camada 3 — a projeção (demo)

Como a regressão de magnitude falhou, projetar um site novo **não pode devolver um número**.
Devolve o que sítios comparáveis de fato produziram — uma previsão de **classe de referência**.

Ela continua válida quando a regressão individual falha, porque não afirma nada sobre o caso
específico: afirma sobre a taxa-base do grupo.
"""),
    code("""
classes_ref
"""),
    md("""
### Como isso é validado

Intervalo não se valida por R². Valida-se por **cobertura**: deixando cada campus de fora, a faixa
projetada pelos outros 12 contém o valor observado?
"""),
    code("""
validacao[["estrategia", "cobertura_faixa_15_85", "cobertura_nominal",
           "largura_mediana_pp", "recomendada", "leitura"]]
"""),
    md("""
**Resultado contraintuitivo e importante:** condicionar em greenfield/brownfield **piora** o
intervalo — derruba a cobertura de 69% para 46% e estreita só 0,3 p.p. Com subgrupos de n=6 e n=7
os percentis ficam instáveis.

Ou seja: o achado direcional de greenfield vale, **o intervalo condicionado não**. Duas conclusões
que parecem contraditórias e não são — e que só aparecem porque validamos as duas coisas
separadamente.

### A demo — troque o número e rode de novo
"""),
    code("""
import importlib
import projecao_demo  # noqa  (helper fino em modelo-impacto-score/scripts/)
importlib.reload(projecao_demo)

# >>> TROQUE AQUI: % do terreno do footprint já construído antes da obra (0 a 100)
projecao_demo.projetar_e_mostrar(15)
"""),
    code("""
# Alguns cenários lado a lado
for pct in (0, 25, 50, 75, 90):
    projecao_demo.projetar_e_mostrar(pct)
    print()
"""),
    md("""
> **Repare que a faixa de magnitude é a MESMA nos cinco cenários — e isso não é bug, é o
> resultado.** Só a *direção* muda com a entrada (100% dos greenfield positivos contra 71% dos
> brownfield), porque é a única coisa que as features preveem. A magnitude não muda porque
> **nada na camada 2 conseguiu prevê-la**, então a faixa honesta é a da amostra inteira — a única
> com cobertura calibrada.
>
> Uma ferramenta que devolvesse faixas diferentes por cenário aqui estaria inventando precisão que
> os dados não sustentam. Este é o comportamento correto, e é o que separa esta demo de um
> dashboard bonito que mente.
"""),
    code("""
display(Image(filename=str(FIG / "fig_03_projecao.png")))
"""),
    md("""
---
## 4. Limitações — as que eu levantaria antes que perguntem

- **N=15**, e 2 dos pares vão na direção contrária (ambos explicados pela saturação do sítio).
- **`pct_ja_construida` só existe para 13 campi** — 2 sem footprint no OpenStreetMap.
- **O corte de 50% greenfield/brownfield foi escolhido depois de ver os dados.** O script varre 7
  limiares e publica todos; greenfield fica 100% positivo em toda a faixa de 40% a 80%. O teste
  contínuo equivalente (Spearman −0,31) tem direção consistente e magnitude fraca.
- **Janela pós-obra curta:** pela coluna `fase`, só 7 dos 15 campi têm ≥2 anos pré *e* ≥2 pós. Por
  isso tudo aqui usa a convenção "2 primeiros × 2 últimos anos da janela", que preserva 14–15
  pares. **É a pergunta que eu faria no lugar da banca.**
- **Sem série de precipitação.** Qualquer afirmação sobre vegetação carrega o confundidor climático
  não controlado.
- **Emprego, PIB e população não entram em eixo nenhum** — são municipais, e os pares têm portes
  municipais de razão 0,03 a 15,0. Servem como contexto, nunca como evidência.
- **Não é inferência causal formal.** É padrão consistente contra grupo de controle, com
  pré-tendências paralelas verificadas (6/14, p=0,79).
"""),
    md("""
---
## 5. A conclusão em uma frase

> Em **12 dos 14** data centers com par válido, o anel de 500 m ao redor converteu para área
> construída mais do que um terreno pareado sem data center — excesso mediano de **2,06 p.p.**,
> **p=0,0065**. O efeito decai com a distância e desaparece depois de 1 km, é localizado e não
> regional, e as tendências pré-obra eram paralelas. A **magnitude**, porém, **não é predizível**
> a partir das features disponíveis: nenhum dos 13 modelos testados supera o baseline sob validação
> cruzada. O que se sustenta é o padrão, não o coeficiente.

Relatório completo: `modelo-impacto-score/reports/relatorio-impacto.md`
"""),
]


def main() -> int:
    nb = nbf.v4.new_notebook(cells=CELULAS)
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": sys.version.split()[0]},
    }
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, DESTINO)
    print(f"escrito: {DESTINO.relative_to(RAIZ)} ({len(CELULAS)} células)")

    print("executando (as saídas ficam embutidas, o notebook abre já renderizado)...")
    client = NotebookClient(
        nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(DESTINO.parent)}}
    )
    client.execute()
    nbf.write(nb, DESTINO)
    print(f"  -> executado, {sum(1 for c in nb.cells if c.cell_type == 'code')} células de código")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
