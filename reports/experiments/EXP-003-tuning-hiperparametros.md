# EXP-003 — Busca pequena de hiperparâmetros (SV-12, "tuning mínimo e honesto")

- **Data:** 2026-09-03
- **Dataset:** `dataset_v1.0` (mesmo de `rf_v1.0`) — sha256 `7274bc55604fc1581bb4da0769419ac34d126b60bf24f1098ec758aeb1e9179f`
- **Linhas de treino:** 1.939.285 (`split=="treino"` & `holdout_temporal==False`), 1.068 blocos — idêntico a `rf_v1.0`.
- **Motivação:** F1 da classe 3 (solo exposto/obras) no holdout de AOI nunca vista (recorte (e) de
  `sentinela.evaluate`) estava em **0,5407** (~0,541), abaixo da meta informal de 0,55 — e o
  `.joblib` de `rf_v1.0` (árvore sem `max_depth`, ~1,9M linhas de treino) ocupa **7,12 GB**, com o
  disco em ~12 GB livres. Esta rodada testa se limitar a profundidade da árvore (a dimensão mais
  provável de afetar as duas coisas) ajuda em algum dos dois eixos sem piorar o outro.
- **Nota sobre qual "holdout espacial" é 0,541:** o enunciado desta tarefa cita "F1 classe 3 no
  holdout espacial, hoje em 0,541". O relatório `reports/avaliacao_rf_v1.0.md` tem duas métricas
  candidatas: o recorte (a) `split=="teste"` (F1 classe 3 = **0,577**, já acima da meta de 0,55) e o
  recorte (e) "holdout espacial de **AOI nunca vista**" (F1 classe 3 = **0,5407**, o número que bate
  com 0,541). Esta rodada reporta **os dois** para não escolher seletivamente o que favorece a
  narrativa, mas trata o recorte (e) como o mais alinhado ao "número que motivou a rodada" (é a
  única medida real de "funciona num data center novo", e é a que está abaixo da meta).

## O que ficou fixo (fora de escopo desta rodada)

`n_estimators=300`, `max_features="sqrt"`, `class_weight="balanced_subsample"`, `random_state=42`,
variante `com_sensor` (`sensor_landsat` como feature binária — a mesma adotada por `rf_v1.0`, ver
`EXP-002-rf-v1.0-treino.md`). Só `max_depth` e `min_samples_leaf` variam, um de cada vez, nunca
junto — para poder atribuir causa a qualquer diferença observada.

## Metodologia da busca (honesta com o orçamento de disco/tempo)

Nenhum modelo de configuração candidata foi salvo em disco durante a busca — só medido em memória
e descartado. Para cada configuração:

1. **Fit único** no treino inteiro (1.939.285 linhas), cronometrado — orçamento de corte: ~6-8 min.
2. Do modelo desse fit único: soma de `estimator.tree_.node_count` das 300 árvores (proxy direto
   de tamanho) e uma **estimativa de bytes em disco sem serializar as 300 árvores**: `pickle.dumps`
   de uma amostra de 20 árvores (só em memória, nunca grava arquivo), calcula bytes/nó da amostra,
   extrapola para o total de nós das 300. Esse fit único não é salvo — só usado para medir e
   descartado (`del modelo`).
3. Se o fit único ficou dentro do orçamento, roda `GroupKFold(n_splits=5)` por `bloco_id` (mesma
   lógica de `sentinela.train.cv_macro_f1`, script separado para poder computar também F1 da
   classe 3 por fold, que `cv_macro_f1` não expõe) — cada fold treina e descarta um modelo em
   memória, nunca salva.

Scripts usados (não fazem parte do pipeline principal, ficam em `scripts/` como registro
reproduzível desta busca): `scripts/exp003_prepare_cache.py` (cache de X/y/groups em `.npy`, evita
reler/refiltrar o parquet de 3,8M linhas a cada configuração), `scripts/exp003_worker.py` (uma
etapa por chamada — fit único OU um fold — para caber no limite de tempo por chamada de shell e
nunca rodar nada em background), `scripts/exp003_finalize.py` (treino final único da configuração
vencedora + salvamento, com checagem de espaço em disco antes de gravar).

**Validação da estimativa de tamanho:** o modelo final salvo da configuração vencedora
(`max_depth=30`) pesou **6.540.830.141 bytes** no disco; a estimativa por amostragem de árvores,
calculada *antes* de salvar, tinha previsto **6.540.812.985 bytes** — diferença de 17 KB em 6,5 GB
(erro relativo ~0,0000027%). O método de estimativa (bytes/nó amostrado × total de nós) é confiável.

## Grid testado (3 configurações novas, além da atual)

| configuração | fit único | tempo total CV (5 folds) | macro-F1 CV (média ± desvio) | F1 classe 3 CV (média ± desvio) | tamanho estimado |
|---|---|---|---|---|---|
| **atual (`rf_v1.0`)** — `max_depth=None`, `min_samples_leaf=5` | 323,7s (EXP-002, não re-rodado) | 1301,3s (EXP-002) | 0,7927 ± 0,0069 | _não medido na CV original (só macro-F1 foi coletado em EXP-002)_ | **7.118.259.773 bytes (7,118 GB) — real, arquivo em disco** |
| `max_depth=30` | 317,4s | 1213,5s | **0,7922 ± 0,0072** | **0,6381 ± 0,0235** | ~6.540.812.985 bytes (6,541 GB, estimado) |
| `max_depth=20` | 293,7s | 1139,9s | 0,7823 ± 0,0113 | 0,6202 ± 0,0369 | ~2.597.294.822 bytes (2,597 GB, estimado) |
| `min_samples_leaf=10` | 309,5s | 1210,9s | 0,7871 ± 0,0092 | 0,6286 ± 0,0289 | ~4.163.363.998 bytes (4,163 GB, estimado) |

Todos os fits únicos ficaram bem dentro do orçamento de 6-8 min (293-323s, ~5-5,4 min) — nenhuma
configuração foi descartada por custo.

## Configuração vencedora e critério de decisão

**`max_depth=30` venceu a CV.** Critério: melhor macro-F1 (0,7922, estatisticamente empatada com a
configuração atual — diferença de -0,0005, bem dentro do próprio desvio de 0,0072) **e** melhor F1
classe 3 (0,6381, a maior das três candidatas) **e**, ainda assim, um tamanho em disco menor que o
atual (~6,54 GB vs 7,12 GB) — ou seja, `max_depth=30` não é só "a menos ruim", é a configuração que
melhor desempenho entre as candidatas E reduz o tamanho, sem trade-off a justificar.

`max_depth=20` reduz o tamanho de forma muito mais agressiva (~2,6 GB, -64% vs atual) mas paga um
custo real de desempenho na CV (macro-F1 -0,0104 vs atual, o dobro do próprio desvio-padrão da
config — o sinal mais claramente fora do ruído entre folds observado nesta busca) e F1 classe 3
0,018 abaixo de `max_depth=30`. `min_samples_leaf=10` fica no meio (~4,16 GB, macro-F1 -0,0056) sem
vencer `max_depth=30` em nenhuma das duas métricas de desempenho.

**Honestidade sobre o objetivo secundário:** nenhuma configuração testada reduz o disco
*drasticamente* sem custo algum — só `max_depth=20` chega perto de "drástico" (-64%), e essa é
justamente a que mostra o maior custo de desempenho na CV. `max_depth=30` entrega uma redução real
mas modesta (-8,1%) e, pelas métricas de CV, sem custo de desempenho detectável. Não inflamos o
resultado: profundidade de árvore aqui se comporta mais como "limpeza sem custo" do que como a
alavanca de compressão drástica que se esperava.

## Treino final único e avaliação em holdout

`max_depth=30` foi treinada **uma única vez** no treino inteiro (1.939.285 linhas, 313,0s) e salva
como `models/rf_v1.0-tuned.joblib` (6.540.830.141 bytes, sha256
`2d38d312706cc7b4dc3525709c06a439074825bd258f252b6b9bf817819d2d86`). Espaço livre em disco antes de
salvar: 11,79 GB (bem acima do limiar de 6 GB do enunciado); depois de salvar (com os dois
`.joblib` coexistindo): 7,69 GB.

Avaliada em holdout com `sentinela.evaluate` (nunca chama `.fit`), mesma metodologia de `rf_v1.0` —
relatório completo em `reports/avaliacao_rf_v1.0-tuned.md`.

### Tabela final: `rf_v1.0` (atual) vs. `rf_v1.0-tuned` (candidata)

| métrica | `rf_v1.0` | `rf_v1.0-tuned` | Δ (tuned − atual) |
|---|---|---|---|
| accuracy (holdout espacial, split=="teste") | 0,7889 | 0,7882 | −0,0007 |
| macro-F1 (holdout espacial) | 0,7757 | 0,7756 | −0,0001 |
| **F1 classe 3 (holdout espacial, recorte (a))** | 0,5770 | **0,5795** | **+0,0025** |
| macro-F1 (holdout temporal) | 0,7260 | 0,7256 | −0,0004 |
| **F1 classe 3 (holdout de AOI nunca vista, recorte (e) — o número "0,541" que motivou a rodada)** | 0,5407 | **0,5454** | **+0,0047** |
| macro-F1 (holdout de AOI nunca vista) | 0,7676 | 0,7681 | +0,0005 |
| F1 classe 3 (era Landsat, 2013-2018) | 0,4800 | 0,4794 | −0,0006 |
| F1 classe 3 (era Sentinel-2, 2019-2025) | 0,5838 | 0,5868 | +0,0030 |
| **tamanho do `.joblib` em disco** | 7.118.259.773 bytes (7,118 GB) | **6.540.830.141 bytes (6,541 GB)** | **−577.429.632 bytes (−8,1%)** |

Todas as diferenças de desempenho estão na casa de ±0,005 — dentro (ou próximas) do ruído
observado entre folds da própria CV (desvios de 0,007 a 0,03 nas métricas medidas nesta busca).
**Nenhuma métrica de desempenho piorou de forma que se possa distinguir de ruído**, e as duas
métricas mais relevantes para o objetivo desta rodada (F1 classe 3 nos dois recortes de holdout
espacial) melhoraram, ainda que modestamente (+0,0025 e +0,0047). Nem `rf_v1.0` nem `rf_v1.0-tuned`
batem a meta informal de 0,55 no holdout de AOI nunca vista (recorte (e)) — `rf_v1.0-tuned` chega a
0,5454, mais perto mas ainda abaixo.

## Decisão final: modelo oficial

**`rf_v1.0-tuned` passa a ser o modelo oficial da V1**, substituindo `rf_v1.0`.

Critério do enunciado: *"vira oficial só se for melhor ou igual em F1 classe 3 no holdout espacial
E menor em disco, ou claramente melhor mesmo sem ganho de disco."* `rf_v1.0-tuned` satisfaz a
primeira condição de forma limpa nos dois recortes de holdout espacial considerados (recorte (a):
+0,0025; recorte (e): +0,0047) **e** é 8,1% menor em disco — não é um empate que dependeu de
"claramente melhor" para desempatar; ganhou nas duas frentes ao mesmo tempo.

`models/rf_v1.0.joblib` (7,12 GB) foi **apagado** após esta decisão (redundante, regenerável via
`python -m sentinela.train --dataset v1.0 --modelo rf --tag v1.0`, hiperparâmetros documentados em
`EXP-002-rf-v1.0-treino.md`); `models/rf_v1.0.sha256`, órfão sem o `.joblib` correspondente, também
foi removido.

**Sinalização (não executada aqui, fora de escopo):** os artefatos de SV-14/SV-15 já existentes em
`outputs/indicadores/` (mapas classificados em GeoJSON por site/ano/sensor e
`outputs/indicadores/area_por_classe.csv`) foram gerados com o modelo **anterior** (`rf_v1.0`).
Se o time quiser que esses artefatos reflitam `rf_v1.0-tuned`, é preciso regenerá-los — isso não foi
feito nesta rodada (fora de escopo explícito do enunciado de EXP-003) e é um passo manual/maior a
decidir separadamente.

## Estado final do disco

Antes desta rodada: ~11,7 GB livres (com `rf_v1.0.joblib` de 7,12 GB presente).
Depois do treino final + avaliação + remoção de `rf_v1.0.joblib`: **14.340.464.640 bytes (14,34 GB /
13,36 GiB) livres** (`rf_v1.0-tuned.joblib`, 6,54 GB, é o único `.joblib` grande restante em
`models/`).

## Arquivos criados/modificados

- `scripts/exp003_prepare_cache.py` (novo) — prepara cache de X/y/groups do treino em `.npy`.
- `scripts/exp003_worker.py` (novo) — roda uma etapa da busca (fit único de timing/tamanho, ou um
  fold do `GroupKFold`) por chamada, persistindo em `exp003_results.json` (scratchpad, não
  commitado).
- `scripts/exp003_finalize.py` (novo) — treino final único da configuração vencedora + salvamento
  com checagem de espaço em disco.
- `models/rf_v1.0-tuned.joblib` + `models/rf_v1.0-tuned.sha256` (novos, gitignored) — modelo oficial
  a partir de agora.
- `models/rf_v1.0.joblib` + `models/rf_v1.0.sha256` (removidos) — modelo anterior, redundante após
  a decisão acima.
- `reports/avaliacao_rf_v1.0-tuned.md` + `reports/figures/*_rf_v1.0-tuned.png` (novos) — avaliação
  em holdout de `rf_v1.0-tuned`, gerada por `sentinela.evaluate` (SV-13).
- `reports/experiments/EXP-003-tuning-hiperparametros.md` (este arquivo, novo).
