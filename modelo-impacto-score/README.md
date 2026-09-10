# modelo-impacto-score

Terceira frente hospedada neste repositório, criada em **2026-09-10**. Não é o classificador de
cobertura do solo (`src/sentinela/`) nem a coleta de dados externos (`dados-modelo-impacto/`) —
**consome os artefatos das duas** e responde a uma pergunta diferente: *qual foi o impacto
territorial de cada data center, e ele é predizível?*

Tem prazo próprio e **não segue o cronograma do classificador** (congelamento 10/09, apresentação
14/09), pela mesma lógica de `dados-modelo-impacto/`.

## A decisão de desenho que define esta pasta

**Não existe um score único de impacto aqui, e isso é deliberado.**

Um número agregado ("impacto: 73/100") exigiria pesos arbitrários e misturaria eixos com qualidade
de evidência incompatível — conversão de solo (p=0,0065) somada a temperatura, que com n=12 não
atinge significância. O agregado esconderia a parte forte do trabalho e seria a peça mais fácil de
derrubar numa banca.

O que se publica é um **boletim por eixo**, cada um com efeito medido, N, p e um **selo de
evidência** que diz o que pode ser afirmado a partir dele:

| selo | significado |
|---|---|
| `forte` | efeito medido, teste de sinal sustenta a afirmação |
| `sugestivo` | direção consistente, sem significância com este N |
| `nulo_informativo` | não há efeito detectável **e** o desenho teria poder para vê-lo |
| `nulo_amostra_pequena` | medido na escala certa, sinal na direção esperada, mas o N não basta |
| `nulo_sem_poder` | não se detectou nada, mas o desenho **não veria nem se existisse** — não é evidência de ausência |

Os três selos de nulo não são sinônimos, e a diferença entre eles é o que separa *"não existe"* de
*"não sabemos"* de *"não podíamos saber"*.

## As três camadas

| camada | script | pergunta | resposta obtida |
|---|---|---|---|
| **1 — Medição** | `01_boletim.py` | Quanto cada campus impactou, por eixo? | 4 eixos medidos, 3 com selo `forte` |
| **2 — Explicação** | `02_explicacao.py` | O que prediz o tamanho do impacto? | **nada** — todos os R² LOOCV negativos, permutação p=0,64 |
| **3 — Projeção** | `03_projecao.py` | Dado um site novo, que faixa esperar? | classe de referência calibrada (cobertura 69% vs nominal 70%) |

## Resultados

### Camada 1 — o boletim (`outputs/boletim_por_eixo.csv`)

| eixo | n | efeito mediano | p | selo |
|---|---:|---:|---:|---|
| Conversão para construída, anel 0–500 m (**sem o prédio**) | 14 | **+1,50 p.p.** | **0,0065** | `forte` |
| Conversão para construída, anel 500 m–1 km | 14 | **+1,15 p.p.** | **0,0065** | `forte` |
| Vegetação → construída, anel 0–500 m | 14 | **+0,52 p.p.** | **0,0287** | `forte` |
| Aquecimento (LST Landsat 30 m), anel 0–500 m | 12 | +0,51 °C | 0,388 | `nulo_amostra_pequena` |

**Todo eixo `forte` foi validado por placebo.** A mesma estatística, aplicada a 15 pares de lugares
**sem** data center, dá 8/15 (p=0,50) — não produz falso positivo. Cada linha de
`outputs/selos_de_evidencia.csv` carrega essa validação escrita na coluna `validado_por_placebo`.

O eixo de temperatura percorreu **dois** desses selos, e a trajetória entre eles é o resultado:

- primeiro `nulo_sem_poder` — MODIS de 1 km num disco de 5 km diluía o sinal **427×**; o desenho
  não veria o efeito nem se existisse;
- depois `nulo_amostra_pequena` — refeito com Landsat de 30 m no anel (872 pixels em vez de uma
  fração de um), a estimativa vira **+0,51 °C** com gradiente de distância coerente, mas n=12 não
  basta: precisaria de **n=31**.

O score 0–100 de cada campus é **posto percentual dentro dos casos medidos** — posição relativa
entre os 14, não medida absoluta de dano. Está rotulado assim na saída.

### Camada 2 — a magnitude não é predizível

Testados 13 modelos contra o baseline "prever a mediana", todos por LOOCV (N=13):

- melhor modelo: R² fora-da-amostra **−0,07** — pior que prever a média;
- **todos** os modelos com R² negativo;
- nenhuma feature atinge significância (a melhor, `pct_ja_construida`, dá Spearman ρ=−0,31, p=0,30);
- teste de permutação com 999 embaralhamentos: **p=0,64** — o melhor ajuste encontrado é
  indistinguível do que ruído puro produz na mesma busca.

**Isto não contradiz o achado greenfield/brownfield do passo 15 de `dados-modelo-impacto`.** São
perguntas diferentes e as duas respostas estão certas:

- *"a **direção** é consistente?"* → sim: 6/6 pares greenfield positivos, p=0,016 (teste de sinal)
- *"a **magnitude** é predizível?"* → não: R² LOOCV negativo em todos os modelos

É o que o próprio README de `dados-modelo-impacto` já antecipava: *"a leitura defensável é a do
padrão, não a do coeficiente."* Agora está medido.

### Camada 3 — projeção como classe de referência

Como a regressão de magnitude falhou, a projeção não devolve um número: devolve o que sítios
comparáveis de fato produziram. Validada por **cobertura**, não por R² (intervalo não se valida
por R²):

| estratégia | cobertura da faixa 15–85% | largura mediana | veredito |
|---|---:|---:|---|
| classe única (amostra completa) | **69%** (nominal 70%) | 5,05 p.p. | **calibrada — usar esta** |
| condicionada no tipo de sítio | 46% | 4,75 p.p. | estreita só 0,3 p.p. e perde cobertura — não usar |

Condicionar em greenfield/brownfield **piora** o intervalo: com subgrupos de n=6 e n=7 os percentis
ficam instáveis. O achado direcional continua valendo; o intervalo condicionado, não.

```
python modelo-impacto-score/scripts/03_projecao.py --pct-ja-construida 15

  direção   — 6/6 dos análogos greenfield converteram MAIS que seu controle (100%)
  magnitude — faixa 15–85%: -0.39 a +3.88 p.p., mediana +1.93 p.p.
```

## O que esta frente NÃO afirma

- **Emprego, PIB, população.** São de nível municipal. Um empreendimento de dezenas de hectares é
  fração ínfima de um município, e os pares têm portes municipais de razão 0,03 a 15,0. Servem como
  contexto; não entram em nenhum eixo do boletim.
- **Temperatura.** Medida **duas vezes** e reportada nas duas. Com Landsat de 30 m no anel — a
  escala certa — a estimativa é **+0,51 °C** com gradiente de distância coerente, mas não atinge
  significância: seriam necessários **n=31** pares e temos 12. Ver
  `dados-modelo-impacto/scripts/impacto_dc_23_lst_landsat.py` (e o passo 16, superado, que motivou
  a troca de sensor).
  Um detalhe contraintuitivo que vale registrar: a resolução melhorou **33×** e o poder
  estatístico **piorou** (MDE 0,82 °C contra 0,64 °C), porque `MDE = 2,80·σ/√n` e trocar de sensor
  não mexe em nenhum dos dois termos a favor.
- **Magnitude individual de um site novo.** Camada 2, resultado negativo, medido.
- **Inferência causal formal.** N=15, desenho pareado com pré-tendências paralelas verificadas —
  é padrão consistente, não estimativa causal de magnitude.

## Estrutura

```
modelo-impacto-score/
├── scripts/
│   ├── comum.py           # tabela mestra (alvos y_* + features pré-obra x_*) e selos
│   ├── 01_boletim.py      # camada 1 — medição
│   ├── 02_explicacao.py   # camada 2 — explicação (LOOCV + permutação)
│   └── 03_projecao.py     # camada 3 — projeção por classe de referência
├── outputs/               # CSVs (commitados — são o resultado útil)
└── reports/figuras/       # fig_01_boletim · fig_02_explicacao · fig_03_projecao
```

Rode na ordem: `01` → `02` → `03` → `04`. Nenhum reclassifica nem retreina nada; todos leem
artefatos prontos. Seed fixo (42) em tudo que sorteia.

## Reprodução

Um comando, da estaca zero ao notebook:

```bash
python scripts/reproduzir_impacto.py --listar                # o plano, sem executar
python scripts/reproduzir_impacto.py                         # 21 passos offline, minutos
python scripts/reproduzir_impacto.py --etapa completo        # + 10 passos de rede (GEE/Overpass)
```

O runner declara ordem, custo e dependência externa de cada um dos 31 passos das duas frentes. O
padrão é a etapa `analise` — só o que roda offline, que é o caso de uso de quem está **conferindo**
os números de um relatório. Os passos de rede são idempotentes: pulam o que já está em disco.

## Documentos

| arquivo | para quem |
|---|---|
| `reports/sumario-executivo.md` | banca e leitor não técnico — 1 página, sem um p-valor no corpo |
| `reports/relatorio-impacto.md` | detalhamento técnico com todos os números, testes e limitações |
| `../notebooks/02_impacto_score.ipynb` | demo executada, abre já renderizada |

## Insumos consumidos

| origem | arquivo | o que fornece |
|---|---|---|
| `dados-modelo-impacto/processed/` | `consolidado_impacto_painel.csv` | painel 204×51, 15 pares, 2013–2025 |
| `dados-modelo-impacto/raw/controles-rf/` | `footprint_vs_anel.csv` | conversão por zona (footprint, 0–0,5, 0,5–1, 1–2 km) |
| " | `greenfield_brownfield.csv` | `pct_ja_construida` e tipo de sítio |
| " | `footprints_osm.csv` | footprint real do OSM, 14/15 campi |
| " | `lst_did*.csv` | diferença-em-diferenças de LST + poder (passo 16) |
| `config/sites.geojson` | — | `ano_inicio_obra`, bioma, região, tier |

## Separação alvo/feature

Rígida, e é o que impede o erro mais fácil de cometer aqui: **nenhuma variável medida depois do
início da obra entra como feature.** As features de cobertura e LST são a média dos 2 primeiros anos
da janela (que começa em `obra-3`), nunca da série inteira. Uma feature pós-obra faria o modelo
"prever" o efeito usando uma consequência dele.
