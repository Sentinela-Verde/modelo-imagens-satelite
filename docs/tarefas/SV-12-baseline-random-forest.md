# SV-12 — Baseline Random Forest + registro de experimento

- **Fase:** 3 — Baseline · **Data-alvo:** 05/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-11
- **Desbloqueia:** SV-13, SV-14
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: acrescentada a decisão sobre tratar `sensor` como feature, consequência
> da série multi-sensor de SV-02.

## Contexto

O `CLAUDE.md` fixa o baseline: **Random Forest / scikit-learn**. Não é lugar para experimentar
modelo alternativo — o Deep Learning tem trilha própria (SV-21/22/23, Fase 4) e ambiente próprio,
e não pode comprometer o baseline (decisão D-01: a V1 **não tem** dependência de DL).

Entrada: `data/processed/dataset_v0.1.parquet` + `data/manifests/dataset_v0.1.json`.
O manifest diz quais colunas são features e que `bloco_id` é a coluna de grupo para CV.

## Objetivo

Um modelo treinado, salvo, e um registro de experimento que permita a outra pessoa reproduzir o
mesmo número um mês depois.

## Escopo — o que fazer

1. **`src/sentinela/train.py`**, CLI:
   `python -m sentinela.train --dataset v0.1 --modelo rf --tag v0.1`

2. **Modelo e configuração de partida:**
   ```
   RandomForestClassifier(
       n_estimators=300,
       min_samples_leaf=5,        # controla overfit em dado com autocorrelação
       max_features="sqrt",
       class_weight="balanced_subsample",   # classe 3 é rara e é a crítica
       n_jobs=-1,
       random_state=42,
   )
   ```
   Treinar **apenas** nas linhas com `split == "treino"` e `holdout_temporal == False`.
   O conjunto de teste **não é tocado nesta tarefa** — nem para "dar uma olhada".

3. **Validação cruzada:** `GroupKFold(n_splits=5)` agrupando por **`bloco_id`**
   (nunca `KFold`/`StratifiedKFold` simples — reintroduziria o vazamento que SV-11 eliminou).
   Reportar média e desvio de macro-F1 entre os folds.

4. **Tuning mínimo e honesto:** no máximo uma busca pequena (ex.: `min_samples_leaf ∈ {1,5,15}`,
   `n_estimators ∈ {200,500}`), selecionada **pela CV no treino**, nunca pelo teste.
   Se não sobrar tempo, use a configuração de partida — ela é razoável. Registre o que fez.

4b. **Decisão sobre a coluna `sensor` (específica da série multi-sensor):** treinar **duas variantes**
   e comparar pela CV:
   - **(i) sem `sensor` como feature** — o modelo é forçado a depender só do espectro harmonizado.
     É a variante preferida: generaliza para sensores futuros e não pode "trapacear" usando a época.
   - **(ii) com `sensor` como feature categórica** — permite ao modelo compensar resíduo de
     harmonização, ao custo de aprender um atalho temporal (todo Landsat é ≤ 2018).
   **Comece pela (i).** Só adote a (ii) se a diferença de macro-F1 for relevante, e nesse caso
   registre no EXP-001 que o modelo passou a ter uma dependência de época — SV-13 e SV-20 precisam
   saber disso para interpretar a série. **Nunca** inclua `ano` como feature: isso transformaria o
   classificador de cobertura num decorador de calendário.

5. **Artefatos:**
   - `models/rf_{tag}.joblib` (gitignored) — salvar um dict com: o modelo, `lista_features` na
     ordem exata, `versao_dataset`, `seed`, `sklearn_version`, `git_sha`, `classes_`.
     Nunca salvar só o estimador solto: em SV-14 a ordem das colunas é o que impede um bug silencioso.
   - `models/rf_{tag}.sha256` — hash do joblib.
   - `reports/experiments/EXP-001-rf-baseline.md` (**commitado**) contendo: data, git sha, dataset
     e seu sha256, hiperparâmetros finais, espaço de busca testado, macro-F1 por fold da CV
     (média ± desvio), tempo de treino, importância das 17 features ordenada, e uma frase sobre
     o que você esperava e o que aconteceu.

6. **Experimento de controle a registrar no mesmo EXP-001:** treinar também um
   `DummyClassifier(strategy="stratified", random_state=42)` e reportar a macro-F1 dele.
   Sem esse piso, "0.78 de F1" não significa nada para quem lê.

## Fora de escopo

- Avaliar no holdout (SV-13). **Explicitamente proibido aqui.**
- Deep Learning, XGBoost, ensembles — Plus.
- Labels manuais (SV-16).
- Gerar raster classificado (SV-14).

## Critérios de aceite

- [ ] `models/rf_v0.1.joblib` existe, carrega com `joblib.load`, e traz `lista_features` e `seed`.
- [ ] O treino usou **só** `split == "treino"` (assertion no código, não confiança).
- [ ] CV é `GroupKFold` por `bloco_id` — verificável no código e escrito no EXP-001.
- [ ] macro-F1 da CV é **substancialmente maior** que a do `DummyClassifier` (se não for, algo está
      quebrado no dataset, não no modelo — pare e investigue antes de seguir).
- [ ] Treinar duas vezes com a mesma seed produz o mesmo `sha256` do joblib (ou, se o joblib
      carregar timestamp, produz predições idênticas — teste isso).
- [ ] `reports/experiments/EXP-001-rf-baseline.md` commitado e completo.
- [ ] Nenhum `.joblib` entrou no git.

## Cenários de teste

1. **Isolamento do teste:** instrumentar o código para falhar se `split == "teste"` for lido em `fit`.
2. **Determinismo:** dois treinos → mesmas predições em um lote fixo de 1.000 linhas.
3. **Contrato de features:** `modelo["lista_features"] == manifest["lista_features"]`, na ordem.
4. **Piso:** macro-F1(RF) > macro-F1(Dummy) + 0.20.
5. **Sanidade de importância:** BSI e NDVI devem estar entre as features mais importantes.
   Se as mais importantes forem `x`/`y`/`linha`/`coluna`/`ano`, **você vazou coordenada ou tempo como
   feature** — isso é bug grave, corrija antes de seguir.
6. **Variantes de sensor:** as duas variantes do item 4b treinam e a comparação está no EXP-001.

## Como reportar

Informe: hiperparâmetros finais, macro-F1 da CV (média ± desvio) vs. Dummy, **a comparação entre as
variantes com e sem `sensor` e qual foi adotada**, top-5 features por importância, tempo de treino,
e qualquer sinal de que o modelo esteja aprendendo a geografia ou a época em vez do espectro.
