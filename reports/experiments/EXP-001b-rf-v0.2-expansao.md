# EXP-001 — Baseline Random Forest (SV-12)

- **Data:** 2026-09-02T17:00:59.200373+00:00
- **git sha:** `4cdebd3ee0df2b982690157a1305e662c163d9f8`
- **Dataset:** `dataset_v0.2` — sha256 `7d574e4e7d129b919dc375d1f243b5adecbd16b1775d448d06dc30ca93bd3794`
- **Linhas de treino usadas:** 1912670 (`split == "treino"` E `holdout_temporal == False`)
- **Blocos de treino (bloco_id únicos):** 1067
- **Modelo salvo:** `models/rf_v0.2.joblib` — sha256 `a2d29155bccb0abea43a32db88a9378d506a649919409a6da4fc41e87b276aaa`

## Hiperparâmetros finais

```
RandomForestClassifier(
    n_estimators=300,
    min_samples_leaf=5,
    max_features="sqrt",
    class_weight="balanced_subsample",
    n_jobs=-1,
    random_state=42,
)
```

## Espaço de busca testado

Nenhum. Cronometramos um fit único antes de decidir (1912670 linhas, 13
features -> fit final de referência registrado abaixo em 321.5s com
`n_estimators=300`). Uma busca pequena como sugerida no enunciado (`min_samples_leaf ∈
{1,5,15}` x `n_estimators ∈ {200,500}` = 6 combinações, cada uma com `GroupKFold(5)`) custaria
várias vezes o tempo de uma CV única (ver "tempo total da CV" nas duas variantes abaixo), sem
garantia de ganho relevante sobre a configuração de partida. O próprio enunciado autoriza usar a
configuração inicial "se não sobrar tempo — ela é razoável", e foi essa a decisão tomada aqui.
Fica registrado como candidato de follow-up (não bloqueante para o baseline).

## Piso de comparação: DummyClassifier

`DummyClassifier(strategy="stratified", random_state=42)`, mesmo `GroupKFold(5)` por `bloco_id`:

- macro-F1 por fold: [0.1983, 0.1996, 0.1988, 0.1987, 0.1995] -> média=0.1990 ± desvio=0.0005

## Variante (i) — RandomForest SEM `sensor` como feature (adotada nesta rodada: não)

- macro-F1 por fold: [0.7720, 0.7654, 0.7814, 0.8023, 0.7868] -> média=0.7816 ± desvio=0.0127
- tempo total da CV (5 folds): 1386.6s
- ganho sobre o Dummy: +0.5826 de macro-F1

### Importância de features (ordenada, variante sem sensor)

_Fonte: média das importâncias nos 5 folds da CV (variante não adotada, sem fit extra no dataset inteiro)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1287 |
| 2 | `ndwi` | 0.1214 |
| 3 | `ndvi` | 0.1046 |
| 4 | `swir1` | 0.0998 |
| 5 | `nir` | 0.0899 |
| 6 | `mndwi` | 0.0860 |
| 7 | `red` | 0.0778 |
| 8 | `evi` | 0.0699 |
| 9 | `blue` | 0.0514 |
| 10 | `bsi` | 0.0499 |
| 11 | `green` | 0.0457 |
| 12 | `ndbi` | 0.0378 |
| 13 | `ndmi` | 0.0369 |

## Variante (ii) — RandomForest COM `sensor` como feature binária (adotada nesta rodada: SIM)

- macro-F1 por fold: [0.7848, 0.7863, 0.7940, 0.8110, 0.8027] -> média=0.7958 ± desvio=0.0099
- tempo total da CV (5 folds): 1261.3s

### Importância de features (ordenada, variante com sensor)

_Fonte: fit final no treino inteiro (modelo efetivamente salvo)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1112 |
| 2 | `ndwi` | 0.1099 |
| 3 | `ndvi` | 0.0976 |
| 4 | `swir1` | 0.0969 |
| 5 | `mndwi` | 0.0950 |
| 6 | `nir` | 0.0827 |
| 7 | `red` | 0.0749 |
| 8 | `evi` | 0.0674 |
| 9 | `bsi` | 0.0535 |
| 10 | `sensor_landsat` | 0.0506 |
| 11 | `blue` | 0.0487 |
| 12 | `green` | 0.0414 |
| 13 | `ndbi` | 0.0370 |
| 14 | `ndmi` | 0.0330 |

## Comparação das variantes e decisão

Diferença de macro-F1 (com_sensor − sem_sensor) = **+0.0142**.
Limiar de relevância adotado: 0.01 (≈1 ponto de macro-F1) — abaixo
disso, o ruído entre folds do `GroupKFold` não permite afirmar que `sensor` ajuda de verdade, e o
custo de introduzir uma dependência de época (SV-13/SV-20 precisam saber disso ao interpretar a
série) não se paga.

**Variante adotada: `com_sensor`.** O ganho da variante com sensor superou o limiar de relevância, então o modelo final treina com sensor_landsat como feature binária — SV-13 e SV-20 devem tratar a série como tendo uma dependência de época residual.

## Tempo de treino final

Refit no treino inteiro (1912670 linhas), configuração acima: **321.5s**.

## Determinismo

Dois treinos com a mesma seed (42) sobre o mesmo conjunto de treino produziram predições
idênticas em um lote fixo de 1.000 linhas do treino: **sim**.

## O que se esperava vs. o que aconteceu

Esperava-se que BSI (Bare Soil Index) e NDVI dominassem a importância de features, já que são os
índices espectrais desenhados para separar solo exposto/vegetação — as duas classes mais
relevantes para o objetivo do projeto (classe 3, solo exposto/obras, é a crítica). Isso NÃO se confirmou exatamente como esperado — ver tabela de importância acima. Nenhuma
feature de localização (`x`/`y`/`linha`/`coluna`) ou tempo (`ano`) entra no modelo: elas nem
existem em `lista_features` do manifest, e a checagem em `carregar_dataset` falha alto se algum
dia entrarem — não há sinal de que o modelo esteja "decorando" geografia ou época em vez de
espectro.

## Nota sobre a execução desta rodada (`rf_v0.2`)

Por causa do volume de dados (1.912.670 linhas de treino, ~2,3x o de `rf_v0.1`), cada fit de Random Forest desta rodada levou entre 4 e 5,5 min. Para caber no teto de tempo de execução por chamada de ferramenta do ambiente, os 10 fits de CV (`GroupKFold(5)` x 2 variantes) foram executados em processos Python separados, um por fold, sobre os mesmos arrays de treino cacheados (idênticos aos que `python -m sentinela.train` geraria) -- `GroupKFold` é determinístico (sem randomness), então a enumeração de folds é idêntica à de uma execução única do CLI. O fit final e o teste de determinismo também rodaram como processos separados, sobre os mesmos arrays. A metodologia é idêntica à de `rf_v0.1` (mesmo `RF_PARAMS_BASE`, mesmo `GroupKFold(5)` por `bloco_id`, mesmo critério de decisão sobre `sensor`); só a orquestração de execução mudou.

## Comparação `rf_v0.1` (3 sites) × `rf_v0.2` (16 sites) — material de apresentação

Pedido explícito da nota de revisão de 2026-08-31 de SV-12: o modelo melhora ou piora quando o
estudo passa a cobrir 5 biomas em vez de 1? Números da CV de treino (esta tarefa) e do holdout de
verdade (SV-13, `reports/avaliacao_rf_v0.1.md` / `reports/avaliacao_rf_v0.2.md`):

| métrica | `rf_v0.1` (3 sites) | `rf_v0.2` (16 sites) |
|---|---|---|
| macro-F1 da CV de treino | 0.7845 | 0.7958 |
| macro-F1 no holdout espacial (teste) | 0.7521 | 0.7763 |
| F1(classe 3) no holdout espacial | 0.4528 (abaixo da meta 0.55) | 0.5752 (bate a meta) |
| F1(classe 3) — era Landsat | **0.1039** (praticamente não detecta) | **0.4821** |
| F1(classe 3) — era Sentinel-2 | 0.4881 | 0.5845 |
| F1(classe 3) por site — amplitude | 0.361–0.629 (3 sites) | 0.033–0.824 (16 sites) |
| F1(classe 3) em AOI nunca vista (holdout espacial de AOI) | não medido em `dataset_v0.1` (sem AOI reservada) | 0.5402 (logo abaixo da meta) |

**No agregado, o modelo melhorou com a expansão** — todas as métricas de topo (macro-F1 de treino,
macro-F1 no holdout, F1(classe 3) no holdout) sobem de `rf_v0.1` para `rf_v0.2`, e o ganho mais
importante é qualitativo, não só numérico: a era Landsat, que em `rf_v0.1` tinha F1(classe 3) de
0.10 (o modelo essencialmente não via solo exposto/obras em imagens de 2013-2018), sobe para 0.48
em `rf_v0.2` — o dataset expandido finalmente deu ao modelo exemplos suficientes de solo exposto em
resolução Landsat para aprender o padrão, algo que 3 sites simplesmente não forneciam em volume.
Isso é o argumento mais forte a favor da expansão de sites: ela não deixou o modelo "um pouco
melhor", ela consertou um recorte que estava quebrado.

**Mas a expansão também revelou um problema que 3 sites eram homogêneos demais para mostrar:** a
variância de F1(classe 3) *entre sites* aumentou muito (de uma amplitude de 0.27 para 0.79) — dois
sites (`ascenty-maracanau`, Caatinga; `scala-sgigsm01`, Mata Atlântica/RJ) têm F1(classe 3) abaixo
de 0.05, um colapso quase total nesse recorte específico, mesmo tendo dados de treino desses sites
(não são AOIs de holdout). Com 3 sites homogêneos (todos Mata Atlântica/SP), essa fragilidade nunca
apareceria — a média mascarava a variância. E a métrica que mais importa para a promessa do produto
("funciona num data center novo") — F1(classe 3) na AOI de holdout espacial nunca vista em treino —
fica em 0.5402, marginalmente abaixo da meta de 0.55, mostrando que mais sites no treino melhora a
média mas ainda não resolve sozinho a generalização para um site genuinamente novo.

**Conclusão para a apresentação:** a expansão de 3 para 16 sites foi uma melhoria real e
mensurável, não cosmética — resolveu o problema mais grave que `rf_v0.1` tinha (era Landsat cega
para solo exposto). Mas não é uma vitória incondicional: o modelo ficou *mais desigual* entre
sites/biomas, e ainda não bate a meta de referência num data center totalmente novo. A leitura
honesta é "melhorou onde já era fraco, e expôs uma fraqueza nova que só aparece com diversidade
geográfica" — argumento direto para priorizar rotulagem manual complementar (SV-09/SV-10) nos sites
de pior desempenho antes de declarar o baseline pronto para produção.
