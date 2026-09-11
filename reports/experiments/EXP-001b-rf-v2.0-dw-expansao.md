# EXP-001 — Baseline Random Forest (SV-12)

- **Data:** 2026-09-11T20:55:53.759041+00:00
- **git sha:** `800a6e805d62789945b34bbc5be1227923c70770`
- **Dataset:** `dataset_v2.0` — sha256 `72a27a7fcbd86b65ef655df9f32446d888854ee23e5dd6b21658d20ee4da8834`
- **Linhas de treino usadas:** 1213756 (`split == "treino"` E `holdout_temporal == False`)
- **Blocos de treino (bloco_id únicos):** 1092
- **Modelo salvo:** `models/rf_v2.0.joblib` — sha256 `9dd049b4dec2e47f90c20bc7c66ca7fd19e43840a218d2962570cbb854938b19`

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

Nenhum. Cronometramos um fit único antes de decidir (1213756 linhas, 13
features -> fit final de referência registrado abaixo em 179.4s com
`n_estimators=300`). Uma busca pequena como sugerida no enunciado (`min_samples_leaf ∈
{1,5,15}` x `n_estimators ∈ {200,500}` = 6 combinações, cada uma com `GroupKFold(5)`) custaria
várias vezes o tempo de uma CV única (ver "tempo total da CV" nas duas variantes abaixo), sem
garantia de ganho relevante sobre a configuração de partida. O próprio enunciado autoriza usar a
configuração inicial "se não sobrar tempo — ela é razoável", e foi essa a decisão tomada aqui.
Fica registrado como candidato de follow-up (não bloqueante para o baseline).

## Piso de comparação: DummyClassifier

`DummyClassifier(strategy="stratified", random_state=42)`, mesmo `GroupKFold(5)` por `bloco_id`:

- macro-F1 por fold: [0.1983, 0.1964, 0.1989, 0.2006, 0.1973] -> média=0.1983 ± desvio=0.0014

## Variante (i) — RandomForest SEM `sensor` como feature (adotada nesta rodada: SIM)

- macro-F1 por fold: [0.8053, 0.8386, 0.8473, 0.8428, 0.8201] -> média=0.8308 ± desvio=0.0158
- tempo total da CV (5 folds): 702.7s
- ganho sobre o Dummy: +0.6325 de macro-F1

### Importância de features (ordenada, variante sem sensor)

_Fonte: fit final no treino inteiro (modelo efetivamente salvo)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1461 |
| 2 | `ndwi` | 0.1263 |
| 3 | `swir1` | 0.1202 |
| 4 | `ndvi` | 0.1072 |
| 5 | `red` | 0.1050 |
| 6 | `nir` | 0.0885 |
| 7 | `evi` | 0.0747 |
| 8 | `mndwi` | 0.0620 |
| 9 | `green` | 0.0414 |
| 10 | `blue` | 0.0396 |
| 11 | `bsi` | 0.0373 |
| 12 | `ndbi` | 0.0266 |
| 13 | `ndmi` | 0.0254 |

## Variante (ii) — RandomForest COM `sensor` como feature binária (adotada nesta rodada: não)

- macro-F1 por fold: [0.8074, 0.8409, 0.8497, 0.8450, 0.8228] -> média=0.8332 ± desvio=0.0158
- tempo total da CV (5 folds): 653.9s

### Importância de features (ordenada, variante com sensor)

_Fonte: média das importâncias nos 5 folds da CV (variante não adotada, sem fit extra no dataset inteiro)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1339 |
| 2 | `swir1` | 0.1188 |
| 3 | `ndwi` | 0.1118 |
| 4 | `red` | 0.1026 |
| 5 | `nir` | 0.0959 |
| 6 | `ndvi` | 0.0957 |
| 7 | `evi` | 0.0826 |
| 8 | `mndwi` | 0.0655 |
| 9 | `blue` | 0.0471 |
| 10 | `green` | 0.0432 |
| 11 | `bsi` | 0.0396 |
| 12 | `ndbi` | 0.0302 |
| 13 | `ndmi` | 0.0282 |
| 14 | `sensor_landsat` | 0.0049 |

## Comparação das variantes e decisão

Diferença de macro-F1 (com_sensor − sem_sensor) = **+0.0024**.
Limiar de relevância adotado: 0.01 (≈1 ponto de macro-F1) — abaixo
disso, o ruído entre folds do `GroupKFold` não permite afirmar que `sensor` ajuda de verdade, e o
custo de introduzir uma dependência de época (SV-13/SV-20 precisam saber disso ao interpretar a
série) não se paga.

**Variante adotada: `sem_sensor`.** A diferença não superou o limiar de relevância, então o modelo final NÃO usa sensor como feature — depende só do espectro harmonizado, e deve generalizar melhor para sensores futuros sem aprender o atalho temporal (todo Landsat é <= 2018).

## Tempo de treino final

Refit no treino inteiro (1213756 linhas), configuração acima: **179.4s**.

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
