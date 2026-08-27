# SV-13 — Avaliação em holdout + relatório de métricas

- **Fase:** 3 — Baseline · **Data-alvo:** 06/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-12
- **Desbloqueia:** SV-16, SV-20, SV-17
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: acrescentado o recorte **por sensor/era**, consequência da série
> multi-sensor de SV-02.

## Contexto

Item 4 da Definition of Done da V1 e a peça que a banca vai olhar primeiro. O `CLAUDE.md` pede o
mínimo: **matriz de confusão, F1 por classe, accuracy geral, sobre holdout de verdade** — não sobre
treino.

Aqui o conjunto de teste é aberto pela **primeira vez**. Depois de olhar para ele, qualquer ajuste de
hiperparâmetro contamina a avaliação. Se der vontade de ajustar, o ajuste volta para SV-12 e a
avaliação é refeita — e isso fica registrado.

## Objetivo

Um relatório honesto e legível do quanto o baseline funciona, por classe e **por era de sensor**,
com atenção especial à classe 3 (solo exposto/obras), que é a razão de ser do projeto.

## Escopo — o que fazer

1. **`src/sentinela/evaluate.py`**, CLI:
   `python -m sentinela.evaluate --modelo models/rf_v0.1.joblib --dataset v0.1`

2. **Avaliar em quatro recortes**, que respondem perguntas diferentes:
   - **(a) Holdout espacial:** `split == "teste"` — "generaliza para área que não viu?"
   - **(b) Holdout temporal:** `holdout_temporal == True` — "generaliza para ano que não viu?"
   - **(c) Por site** — "funciona nos 3, ou só em um?"
   - **(d) Por sensor / era (novo):** métricas separadas para `sensor == "landsat"` (2013–2018) e
     `sensor == "sentinel2"` (2019–2025). **Se o desempenho na era Landsat for muito pior, metade da
     série temporal do projeto não se sustenta** — e é melhor descobrir isso agora do que na
     apresentação. Excluir as linhas com `sobreposicao == True` deste recorte, para não contar o
     mesmo terreno duas vezes.

3. **Métricas por recorte:** accuracy, macro-F1, weighted-F1, e **precision/recall/F1 por classe**
   com suporte. Use `classification_report`, mas transcreva para tabela markdown.

4. **Matriz de confusão** por recorte, absoluta e **normalizada por linha** (recall por classe), em
   `reports/figures/matriz_confusao_{recorte}_rf_v0.1.png`, com **nomes** das classes nos eixos.

5. **Análise da classe 3 (obrigatória):**
   - Precision e recall isolados, por era.
   - **Com o que ela é confundida?** Leia a linha e a coluna dela. A hipótese a testar é confusão
     com a classe 2 (vegetação rala / lavoura colhida) e a 4 (construída).
   - Quanto da confusão é erro do **modelo** e quanto é erro do **label**? Amostre ~20 pixels errados
     e inspecione no RGB/falsa-cor. Este é o achado mais importante do relatório.
   - Se a fonte de label continuou sendo de safra fixa (ver SV-05b), quebre o erro por
     `distancia_safra`: **o erro cresce com a distância da safra?** Se crescer, você tem a prova
     quantitativa de que a fonte de label é o gargalo, não o modelo.

6. **Métricas-alvo de referência** (termômetro, não critério de aprovação):
   macro-F1 ≥ 0.70 e F1(classe 3) ≥ 0.55 no holdout espacial.
   **Se não bater, a tarefa não falhou** — o resultado é o resultado. Documente o número real e
   proponha ação (mais rotulagem manual, label anual, ponderar por `distancia_safra`, revisar remap).
   Número maquiado é pior que número baixo.

7. **`reports/avaliacao_rf_v0.1.md`** (commitado) reunindo tudo: as tabelas, links para as figuras,
   a análise da classe 3, a comparação entre eras, as limitações conhecidas (fonte de label, 3 sites,
   uma região climática, duas resoluções) e o que você recomenda a seguir.

## Fora de escopo

- Ajustar o modelo com base no que viu aqui (volta a ser SV-12, com registro explícito).
- Gerar raster/mapa (SV-14).
- Comparar as saídas de área entre sensores (SV-20 — aqui é só métrica de classificação).
- Re-treinar com labels manuais (SV-16).

## Critérios de aceite

- [ ] `reports/avaliacao_rf_v0.1.md` existe, commitado, com os **quatro** recortes.
- [ ] Accuracy, macro-F1 e F1 por classe presentes, com suporte por classe.
- [ ] Matrizes de confusão em PNG, absoluta e normalizada, com nomes de classe nos eixos.
- [ ] Seção específica da classe 3, com os ~20 pixels errados inspecionados e a conclusão sobre
      erro-de-modelo vs. erro-de-label.
- [ ] Comparação explícita entre a era Landsat e a era Sentinel-2, com veredito sobre se a era
      antiga tem qualidade suficiente para sustentar a série.
- [ ] Se o label for de safra fixa: o erro quebrado por `distancia_safra`, com a tendência declarada.
- [ ] As métricas do holdout são **piores** que as da CV de treino de SV-12. Se forem melhores ou
      iguais, desconfie de vazamento remanescente — investigue antes de fechar.
- [ ] Seção "Limitações" escrita, sem eufemismo.
- [ ] Rodar de novo produz exatamente os mesmos números.

## Cenários de teste

1. **Isolamento:** o script não chama `fit` em lugar nenhum.
2. **Determinismo:** duas execuções → métricas idênticas.
3. **Suporte:** a soma dos suportes por classe = nº de linhas do recorte.
4. **Coerência:** accuracy = traço da matriz absoluta / total.
5. **Degradação esperada:** macro-F1 (holdout temporal) ≤ macro-F1 (holdout espacial) na maioria dos
   casos. Se o temporal for muito melhor, provavelmente ficou fácil demais — comente no relatório.
6. **Sem dupla contagem:** o recorte por sensor exclui `sobreposicao == True`; a soma dos suportes
   das duas eras é igual ao total do recorte menos as linhas de sobreposição.

## Como reportar

Informe: a tabela de F1 por classe nos quatro recortes, macro-F1 e F1(classe 3), a comparação com as
métricas-alvo, a **diferença de desempenho entre as duas eras**, sua conclusão sobre erro-de-modelo
vs. erro-de-label na classe 3, e a recomendação de próximo passo.
