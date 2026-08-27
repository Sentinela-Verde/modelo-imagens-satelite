# SV-16 — Dataset v1.0 com rotulagem manual + re-treino + comparação

- **Fase:** 4 — Output e Plus · **Data-alvo:** 09/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-10 (rotulagem humana), SV-13 (avaliação do baseline)
- **Desbloqueia:** SV-18
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: a tabela comparativa ganha o recorte por era de sensor, e a rasterização
> dos polígonos manuais passa a ocorrer nas **duas grades**. Consequência da série multi-sensor de SV-02.

## Contexto

O `CLAUDE.md` prevê rotulagem manual complementar da classe "solo exposto/em obras" justamente
porque o WorldCover não a captura. SV-10 produziu esses polígonos. Esta tarefa os incorpora e
mede **se valeu a pena** — comparando contra o baseline `rf_v0.1` no **mesmo holdout**.

Se SV-10 não terminou, **esta tarefa não roda e a V1 fecha sem ela**. Isso é aceitável e já está
previsto no plano. Não invente labels para destravar.

## Objetivo

`dataset v1.0`, modelo `rf_v1.0`, e uma comparação lado a lado que responda: a rotulagem manual
melhorou a classe crítica, e em quanto?

## Escopo — o que fazer

1. **Estender `src/sentinela/dataset.py`** para `--versao v1.0`, incorporando
   `data/labels_manual/*.geojson`:
   - Rasterizar os polígonos manuais **em cada uma das duas grades** (10 m e 30 m),
     `rasterio.features.rasterize` com `all_touched=False`. Um polígono de 0,5 ha vira ~50 pixels a
     10 m e ~5 a 30 m — reporte quantos pixels cada era recebeu, porque a era Landsat vai receber
     ordens de grandeza menos, e isso limita o quanto a rotulagem consegue ajudar lá.
   - **Precedência:** onde houver label manual, ele **substitui** o WorldCover. Onde não houver,
     o WorldCover permanece. Registrar quantos pixels foram sobrescritos, por classe.
   - Nova coluna `origem_label` (`worldcover` | `manual`) — obrigatória, é o que permite a SV-13
     medir desempenho separado por origem.
   - `peso_label`: amostras manuais recebem peso maior (ex.: 3.0), e amostras com
     `confianca == "baixa"` recebem peso reduzido. Documente a escolha.
   - **Manter exatamente o mesmo split** (`bloco_id`, 70/30, seed 42, mesmo holdout temporal) de
     `v0.1`. Se o split mudar, a comparação com o baseline não vale nada. Isto é bloqueante.
   - Amostras manuais são poucas e valiosas: **não** as sub-amostre pelo teto de 8.000/classe.

2. **Manifest** `data/manifests/dataset_v1.0.json` (commitado), com tudo que o v0.1 tem, mais:
   `n_pixels_manuais`, `n_pixels_sobrescritos` por classe, arquivos de rotulagem usados + sha256,
   e a política de precedência e de peso em texto.

3. **Re-treino:** `python -m sentinela.train --dataset v1.0 --modelo rf --tag v1.0`, com os
   **mesmos hiperparâmetros** de `rf_v0.1`. Mudar dados e hiperparâmetros ao mesmo tempo torna
   impossível saber a que atribuir a diferença. Se quiser re-tunar, faça em um terceiro experimento.

4. **Avaliação comparativa:** rodar SV-13 sobre `rf_v1.0` e produzir
   `reports/avaliacao_rf_v1.0.md` **e** `reports/experiments/EXP-002-rf-labels-manuais.md`
   contendo uma tabela direta:

   | Métrica | rf_v0.1 | rf_v1.0 | Δ |
   |---|---|---|---|
   | accuracy (holdout espacial) | | | |
   | macro-F1 (holdout espacial) | | | |
   | **F1 classe 3** | | | |
   | precision classe 3 | | | |
   | recall classe 3 | | | |
   | macro-F1 (holdout temporal) | | | |
   | macro-F1 (era Landsat) | | | |
   | macro-F1 (era Sentinel-2) | | | |
   | **F1 classe 3 (era Landsat)** | | | |

   Mais: métricas do `rf_v1.0` **separadas por `origem_label`** no teste — se ele acerta muito nos
   pixels manuais e nada nos WorldCover, ele decorou os polígonos, não aprendeu a classe.

5. **Decisão registrada:** qual modelo é o oficial da V1. Se `rf_v1.0` não for melhor na classe 3,
   **mantenha `rf_v0.1` como oficial** e documente o porquê — resultado negativo bem medido é
   entrega válida e rende boa discussão na banca.

6. Se `rf_v1.0` virar o oficial, **re-rodar SV-14 e SV-15** com ele e avisar a frente de Indicadores
   (o `modelo_versao` no CSV muda).

## Fora de escopo

- Mudar hiperparâmetros (vira EXP-003 separado).
- Mudar o split (bloqueante — invalidaria a comparação).
- Deep Learning.

## Critérios de aceite

- [ ] `data/processed/dataset_v1.0.parquet` + manifest commitado.
- [ ] O split é **bit a bit o mesmo** de v0.1 para os pixels comuns (teste automatizado: nenhum
      `bloco_id` mudou de `split`).
- [ ] `origem_label` presente e com as duas categorias.
- [ ] Nenhum `bloco_id` em treino e teste ao mesmo tempo (a verificação de SV-11 continua valendo).
- [ ] `models/rf_v1.0.joblib` treinado com os mesmos hiperparâmetros de v0.1.
- [ ] `EXP-002` commitado com a tabela comparativa preenchida, incluindo Δ.
- [ ] Métricas por `origem_label` reportadas.
- [ ] A decisão sobre o modelo oficial está escrita, com justificativa — inclusive se a decisão
      for "ficamos com o v0.1".

## Cenários de teste

1. **Split preservado:** `join(v0.1, v1.0, on=bloco_id)` → `split` idêntico em 100% dos blocos.
2. **Precedência:** um pixel dentro de polígono manual de classe 3 que o WorldCover dizia ser 2 →
   `classe_id == 3` e `origem_label == "manual"` no v1.0.
3. **Sem vazamento novo:** polígonos manuais que caem em blocos de teste vão para o teste, não
   para o treino. Se um polígono cruza a fronteira de dois blocos, seus pixels se dividem conforme
   o bloco — **nunca** force o polígono inteiro para o treino.
4. **Comparação justa:** as duas avaliações usam exatamente as mesmas linhas de teste.
5. **Detecção de decoreba:** F1 nos pixels de origem `worldcover` no teste não desabou em relação
   ao v0.1.

## Como reportar

Informe: a tabela comparativa completa, quantos pixels manuais entraram e quantos sobrescreveram
WorldCover, as métricas por `origem_label`, e qual modelo você declarou oficial e por quê.
