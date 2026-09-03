# EXP-002 (treino/CV) — `rf_v1.0`, dataset com rotulagem manual (SV-16)

> Relatório de TREINO/CV gerado por `sentinela.train` (mesmo formato de EXP-001/EXP-001b, SV-12) —
> hiperparâmetros idênticos a `rf_v0.1`/`rf_v0.2` (nenhum retunado, por desenho de SV-16). A
> comparação v0.1 vs v0.2 vs v1.0 pedida pelo enunciado de SV-16 (accuracy/F1 em holdout, por
> `origem_label`, por bioma, decisão de modelo oficial) está em
> `reports/experiments/EXP-002-rf-labels-manuais.md` — o nome que o enunciado de SV-16 pede — para
> não colidir com este relatório de treino (ver docstring de `sentinela.train.caminho_relatorio`).


- **Data:** 2026-09-02T19:08:15.547730+00:00
- **git sha:** `4cdebd3ee0df2b982690157a1305e662c163d9f8`
- **Dataset:** `dataset_v1.0` — sha256 `7274bc55604fc1581bb4da0769419ac34d126b60bf24f1098ec758aeb1e9179f`
- **Linhas de treino usadas:** 1939285 (`split == "treino"` E `holdout_temporal == False`)
- **Blocos de treino (bloco_id únicos):** 1068
- **Modelo salvo:** `models/rf_v1.0.joblib` — sha256 `3d9e7e61e3660dcab3f1b810b8df5c7e95e7409b9febdb3c5a6c06f25d01d0e4`

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

Nenhum. Cronometramos um fit único antes de decidir (1939285 linhas, 13
features -> fit final de referência registrado abaixo em 323.7s com
`n_estimators=300`). Uma busca pequena como sugerida no enunciado (`min_samples_leaf ∈
{1,5,15}` x `n_estimators ∈ {200,500}` = 6 combinações, cada uma com `GroupKFold(5)`) custaria
várias vezes o tempo de uma CV única (ver "tempo total da CV" nas duas variantes abaixo), sem
garantia de ganho relevante sobre a configuração de partida. O próprio enunciado autoriza usar a
configuração inicial "se não sobrar tempo — ela é razoável", e foi essa a decisão tomada aqui.
Fica registrado como candidato de follow-up (não bloqueante para o baseline).

## Piso de comparação: DummyClassifier

`DummyClassifier(strategy="stratified", random_state=42)`, mesmo `GroupKFold(5)` por `bloco_id`:

- macro-F1 por fold: [0.1967, 0.1981, 0.1983, 0.2002, 0.1991] -> média=0.1985 ± desvio=0.0012

## Variante (i) — RandomForest SEM `sensor` como feature (adotada nesta rodada: não)

- macro-F1 por fold: [0.7783, 0.7735, 0.7785, 0.7709, 0.7895] -> média=0.7781 ± desvio=0.0064
- tempo total da CV (5 folds): 1376.9s
- ganho sobre o Dummy: +0.5796 de macro-F1

### Importância de features (ordenada, variante sem sensor)

_Fonte: média das importâncias nos 5 folds da CV (variante não adotada, sem fit extra no dataset inteiro)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1285 |
| 2 | `ndwi` | 0.1213 |
| 3 | `ndvi` | 0.1079 |
| 4 | `swir1` | 0.1010 |
| 5 | `nir` | 0.0902 |
| 6 | `mndwi` | 0.0840 |
| 7 | `red` | 0.0809 |
| 8 | `evi` | 0.0692 |
| 9 | `blue` | 0.0507 |
| 10 | `bsi` | 0.0500 |
| 11 | `green` | 0.0447 |
| 12 | `ndmi` | 0.0359 |
| 13 | `ndbi` | 0.0357 |

## Variante (ii) — RandomForest COM `sensor` como feature binária (adotada nesta rodada: SIM)

- macro-F1 por fold: [0.7945, 0.7976, 0.7857, 0.7840, 0.8020] -> média=0.7927 ± desvio=0.0069
- tempo total da CV (5 folds): 1301.3s

### Importância de features (ordenada, variante com sensor)

_Fonte: fit final no treino inteiro (modelo efetivamente salvo)._

| # | feature | importância |
|---|---|---|
| 1 | `swir2` | 0.1103 |
| 2 | `ndwi` | 0.1092 |
| 3 | `ndvi` | 0.1020 |
| 4 | `mndwi` | 0.0956 |
| 5 | `swir1` | 0.0949 |
| 6 | `nir` | 0.0835 |
| 7 | `red` | 0.0822 |
| 8 | `evi` | 0.0653 |
| 9 | `bsi` | 0.0500 |
| 10 | `sensor_landsat` | 0.0493 |
| 11 | `blue` | 0.0482 |
| 12 | `green` | 0.0405 |
| 13 | `ndmi` | 0.0359 |
| 14 | `ndbi` | 0.0331 |

## Comparação das variantes e decisão

Diferença de macro-F1 (com_sensor − sem_sensor) = **+0.0146**.
Limiar de relevância adotado: 0.01 (≈1 ponto de macro-F1) — abaixo
disso, o ruído entre folds do `GroupKFold` não permite afirmar que `sensor` ajuda de verdade, e o
custo de introduzir uma dependência de época (SV-13/SV-20 precisam saber disso ao interpretar a
série) não se paga.

**Variante adotada: `com_sensor`.** O ganho da variante com sensor superou o limiar de relevância, então o modelo final treina com sensor_landsat como feature binária — SV-13 e SV-20 devem tratar a série como tendo uma dependência de época residual.

## Tempo de treino final

Refit no treino inteiro (1939285 linhas), configuração acima: **323.7s**.

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
