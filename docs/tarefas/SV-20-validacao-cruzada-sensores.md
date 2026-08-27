# SV-20 — Validação cruzada entre sensores no período de sobreposição

- **Fase:** 4 — Output e Plus · **Data-alvo:** 09/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-13 (avaliação do baseline), SV-14 (rasters classificados das duas eras)
- **Desbloqueia:** SV-17
- **Tem seção de risco:** não
- **Tipo:** validação metodológica — é o que sustenta a afirmação central do projeto

## Contexto

O projeto afirma coisas sobre **mudança ao longo de 13 anos**, usando dois sensores diferentes, com
resoluções diferentes, e trocando de um para o outro exatamente em 2019 — que é quando os data
centers começaram a crescer. Sem esta tarefa, existe uma explicação alternativa para qualquer
tendência encontrada: *"vocês trocaram de satélite, e o degrau é do satélite"*. É a primeira coisa
que um avaliador competente vai levantar, e é uma objeção justa.

SV-02b já mediu o resíduo espectral entre sensores. Esta tarefa mede o que realmente importa: o
resíduo **na saída final** — a área por classe, que é o que a frente de Indicadores publica.

Os anos de sobreposição (2019–2021), ingeridos nos dois sensores por SV-06/SV-06b, existem
exatamente para isto.

## Objetivo

Um número defensável para "quanto da variação da série vem do sensor e não do terreno", com a
correção aplicada ou a limitação declarada.

## Escopo — o que fazer

1. **`src/sentinela/validacao_sensores.py`**, CLI:
   `python -m sentinela.validacao_sensores --modelo models/rf_v0.1.joblib`

2. **Comparação pareada, por site × ano de sobreposição:**
   - Classificar o mesmo site/ano pelas duas vias (Landsat 30 m e Sentinel-2 10 m), usando o
     **mesmo modelo** — o modelo é treinado no espaço de features harmonizado, então isso é possível
     e é justamente o teste da harmonização.
   - Comparar em **dois níveis**:
     - **(a) Área por classe** — o que a frente de Indicadores consome. Diferença absoluta e
       relativa por classe, em hectares e em pontos percentuais.
     - **(b) Concordância espacial** — agregar a classificação de 10 m para a grade de 30 m por
       **classe majoritária** e calcular concordância pixel a pixel + matriz de confusão entre
       sensores. Atenção: parte da discordância aqui é **efeito de pixel misto**, não erro de
       harmonização — separe os dois na análise, olhando se a discordância se concentra nas bordas
       entre classes (efeito de resolução) ou no interior de manchas homogêneas (erro de sensor).

3. **Quantificar o degrau na série:** para cada site, plotar a área da classe 3 (e da 4) ao longo de
   2013–2025 com as duas séries sobrepostas no período de sobreposição. **O degrau de 2018→2019 é
   maior ou menor que a diferença medida entre sensores no mesmo ano?**
   - Se for **maior**, a mudança é real e a série se sustenta.
   - Se for da **mesma ordem**, a tendência não é distinguível do artefato — e isso precisa ser dito.

4. **Decidir e aplicar um tratamento**, entre:
   - **(a)** Nenhum — o viés está abaixo da tolerância de SV-02b e é declarado como incerteza residual.
   - **(b)** **Fator de correção por classe** derivado da sobreposição, aplicado à era Landsat, com
     intervalo de incerteza. Simples e honesto se a relação for estável entre os anos de
     sobreposição — **verifique a estabilidade antes de aplicar**; um fator calibrado em um ano só
     e aplicado a seis não é correção, é chute.
   - **(c)** Publicar a série em **duas faixas separadas**, sem emendá-las, deixando o corte visível
     no gráfico. É a opção mais conservadora e sempre defensável.

5. **Relatório `reports/validacao_sensores.md`** (commitado) com: tabela de diferença de área por
   classe/site/ano, concordância espacial, a análise borda vs. interior, o gráfico da série com a
   sobreposição destacada, o tratamento escolhido e por quê, e a **frase pronta** que responde à
   objeção do avaliador — em uma ou duas linhas, com o número dentro.

6. **Propagar:** se um fator de correção for aplicado, SV-15 precisa aplicá-lo no CSV e declarar isso
   em `docs/schema-indicadores.md`; se a opção for (c), o CSV ganha uma coluna que separa as faixas.
   Avise a frente de Indicadores em qualquer um dos casos.

## Fora de escopo

- Re-treinar o modelo (se a conclusão exigir isso, vira tarefa nova).
- Harmonização espectral (SV-02b já fez).
- Landsat 5/7 / Faixa B.

## Critérios de aceite

- [ ] Comparação feita para **todos** os site × ano de sobreposição disponíveis, não para um só.
- [ ] Diferença de área por classe reportada em ha e em pontos percentuais, com média e dispersão
      entre os anos de sobreposição.
- [ ] Concordância espacial na grade de 30 m reportada, com matriz de confusão entre sensores.
- [ ] Análise borda vs. interior feita — separando efeito de resolução de erro de harmonização.
- [ ] O degrau 2018→2019 da série está comparado com a diferença medida entre sensores, com veredito
      explícito sobre se a tendência é distinguível do artefato.
- [ ] Tratamento escolhido (a, b ou c) registrado com justificativa; se for (b), a estabilidade do
      fator entre os anos de sobreposição está demonstrada.
- [ ] `reports/validacao_sensores.md` contém a frase-resposta pronta para a banca, com número.
- [ ] SV-15 e a frente de Indicadores avisados se algo mudou no output.

## Cenários de teste

1. **Pareamento correto:** as duas classificações comparadas são do mesmo site e do mesmo ano
   (parece óbvio; é o erro mais fácil de cometer aqui).
2. **Agregação:** a soma das áreas por classe bate com a área válida total nas duas resoluções.
3. **Controle de resolução:** agregar o S2 de 10 m para 30 m e comparar com o **próprio S2** de 10 m
   dá a magnitude do efeito de pixel misto **isolado do sensor**. Sem esse controle, você atribui ao
   sensor o que é da resolução. **Este é o teste mais importante da tarefa.**
4. **Sanidade:** a concordância entre sensores é maior em classes de manchas grandes e homogêneas
   (água, vegetação densa) do que na classe 3, que é fragmentada. Se não for, investigue.
5. **Estabilidade do fator:** se a opção for (b), o fator calculado em 2019, 2020 e 2021
   separadamente é consistente entre si.

## Como reportar

Informe: a diferença média de área por classe entre sensores, a concordância espacial, o resultado
do controle de resolução (item 3 dos testes), o veredito sobre o degrau 2018→2019, o tratamento
escolhido, e a frase-resposta para a banca.
