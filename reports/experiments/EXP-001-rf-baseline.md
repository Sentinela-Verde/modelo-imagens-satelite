# EXP-001 — Baseline Random Forest (SV-12)

- **Data:** 2026-09-01T06:27:16.176919+00:00
- **git sha:** `7356c20a10db2f6588eaa30fc497732a5ab8ea74`
- **Dataset:** `dataset_v0.1` — sha256 `ec4d82466619d3add494714a3fd8ca24f384acf4f0f44ee8e48ca3e03ce51e21`
- **Linhas de treino usadas:** 830018 (`split == "treino"` E `holdout_temporal == False`)
- **Blocos de treino (bloco_id únicos):** 252
- **Modelo salvo:** `models/rf_v0.1.joblib` — sha256 `8d4799ac30a68cfe7c62f738ee75f39e58ea9aa13eb31c2509e839ec74ffe3ff`

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

Nenhum. Cronometramos um fit único antes de decidir (830.018 linhas, 13 features -> ~140s por
fit com `n_estimators=300`). Uma busca pequena como sugerida no enunciado (`min_samples_leaf ∈
{1,5,15}` x `n_estimators ∈ {200,500}` = 6 combinações, cada uma com `GroupKFold(5)`) custaria
da ordem de 1h de CPU só para o tuning, sem garantia de ganho relevante sobre a configuração de
partida. O próprio enunciado autoriza usar a configuração inicial "se não sobrar tempo — ela é
razoável", e foi essa a decisão tomada aqui. Fica registrado como candidato de follow-up (não
bloqueante para o baseline).

## Piso de comparação: DummyClassifier

`DummyClassifier(strategy="stratified", random_state=42)`, mesmo `GroupKFold(5)` por `bloco_id`:

- macro-F1 por fold: [0.1983, 0.1971, 0.1982, 0.1966, 0.1974] -> média=0.1975 ± desvio=0.0007

## Variante (i) — RandomForest SEM `sensor` como feature (adotada nesta rodada: não)

- macro-F1 por fold: [0.7226, 0.7517, 0.7703, 0.7853, 0.7825] -> média=0.7625 ± desvio=0.0232
- tempo total da CV (5 folds): 550.4s
- ganho sobre o Dummy: +0.5649 de macro-F1

### Importância de features (ordenada, variante sem sensor)

_Fonte: média das importâncias nos 5 folds da CV (variante não adotada, sem fit extra no dataset inteiro)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1411 |
| 2 | `ndvi` | 0.1382 |
| 3 | `ndwi` | 0.1254 |
| 4 | `swir1` | 0.0903 |
| 5 | `mndwi` | 0.0816 |
| 6 | `nir` | 0.0808 |
| 7 | `red` | 0.0748 |
| 8 | `evi` | 0.0667 |
| 9 | `bsi` | 0.0493 |
| 10 | `blue` | 0.0437 |
| 11 | `green` | 0.0428 |
| 12 | `ndmi` | 0.0343 |
| 13 | `ndbi` | 0.0311 |

## Variante (ii) — RandomForest COM `sensor` como feature binária (adotada nesta rodada: SIM)

- macro-F1 por fold: [0.7491, 0.7688, 0.7967, 0.8070, 0.8011] -> média=0.7845 ± desvio=0.0221
- tempo total da CV (5 folds): 462.1s

### Importância de features (ordenada, variante com sensor)

_Fonte: fit final no treino inteiro (modelo efetivamente salvo)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1253 |
| 2 | `ndwi` | 0.1237 |
| 3 | `ndvi` | 0.1065 |
| 4 | `nir` | 0.0863 |
| 5 | `swir1` | 0.0778 |
| 6 | `mndwi` | 0.0748 |
| 7 | `red` | 0.0732 |
| 8 | `evi` | 0.0630 |
| 9 | `sensor_landsat` | 0.0624 |
| 10 | `bsi` | 0.0563 |
| 11 | `green` | 0.0420 |
| 12 | `blue` | 0.0405 |
| 13 | `ndbi` | 0.0373 |
| 14 | `ndmi` | 0.0311 |

## Comparação das variantes e decisão

Diferença de macro-F1 (com_sensor − sem_sensor) = **+0.0221**.
Limiar de relevância adotado: 0.01 (≈1 ponto de macro-F1) — abaixo
disso, o ruído entre folds do `GroupKFold` não permite afirmar que `sensor` ajuda de verdade, e o
custo de introduzir uma dependência de época (SV-13/SV-20 precisam saber disso ao interpretar a
série) não se paga.

**Variante adotada: `com_sensor`.** O ganho da variante com sensor superou o limiar de relevância, então o modelo final treina com sensor_landsat como feature binária — SV-13 e SV-20 devem tratar a série como tendo uma dependência de época residual.

## Tempo de treino final

Refit no treino inteiro (830018 linhas), configuração acima: **117.4s**.

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
