# modelo-imagens-satelite — Sentinela Verde (MBA Engenharia de Dados, Mackenzie)

Repositório dedicado à frente de **Modelagem / Machine Learning** do projeto Sentinela Verde:
monitoramento geoespacial de impacto ambiental/territorial no entorno de data centers, via
séries temporais de imagens de satélite (Sentinel-2 / Landsat).

Trabalho em grupo (6 integrantes), repos separados por frente no GitHub (`Sentinela-Verde/*`).
Existe um repo irmão, `datacenter-extracao-modelos`, que já tem um pipeline de extração +
classificação funcionando (para um data center, Ascenty Vinhedo). **Decisão do time (2026-08-27):
este repo é construído do zero, independente do repo irmão**, até o time se reunir e decidir o
melhor caminho de integração/consolidação entre os dois. Não copie nem dependa de código do
`datacenter-extracao-modelos` sem alinhar antes.

## Fonte de verdade do planejamento
Plano completo (problema, critérios de sucesso, escopo, frentes de trabalho, backlog por sprint,
riscos) vive no Notion: página **"🧭 Plano de Modelos de ML — Product Flow"**, dentro do espaço
"Projeto MBA Engenharia de Dados". Consulte antes de mudar escopo.

## Decisões já tomadas pelo time (não renegociar sem alinhar)
- **Classes de cobertura/uso do solo (5):** Vegetação (densa) · Vegetação rala/pasto/agricultura leve
  · Solo exposto/em obras (classe crítica — sinal de início de construção) · Área construída/urbana
  · Água. Infraestrutura viária como classe separada fica fora do V1 (entra em "construída").
- **Fonte de labels (atualizado 2026-08-27, ADR-004):** **MapBiomas Coleção 9 (anual, 2013–2023,
  replicando 2023 para 2024–2025) como label principal**, com **ESA WorldCover v200 como
  verificação cruzada só em 2021** (peso maior nos pixels onde as duas fontes concordam) — troca a
  decisão original (WorldCover puro) porque a janela do projeto virou 2013–2025 e uma safra fixa
  aplicada a 13 anos gerava defasagem de até 8 anos, um erro sistemático medido em 4–6% de pixels
  por site. **Em qualquer cenário, a rotulagem manual complementar da classe "solo exposto/em
  obras" continua obrigatória** — nem WorldCover nem MapBiomas têm uma classe "canteiro de obras".
  Detalhe completo: `docs/decisoes/ADR-004-fonte-de-labels.md`.
- **V1 (mínimo necessário):** modelo supervisionado baseline (Random Forest/scikit-learn), dataset
  de modelagem versionado, avaliação com métricas documentadas (accuracy, F1 por classe, matriz de
  confusão), classificação reproduzível, output consumível pela etapa de Indicadores (05).
- **Plus (só depois do V1 fechado):** segmentação semântica, Deep Learning avançado, Siamese CNN
  para change detection, comparação de abordagens.
- **Split:** nunca aleatório por pixel — usar split espacial e/ou temporal explícito para evitar
  vazamento de dados entre treino/teste.
- **Cronograma (prazo atualizado 2026-09-11):** este repo usa um cronograma próprio por fases, não
  mais as sprints do Notion — ver `docs/plano-execucao.md`. Prazo final fixo: **17/09/2026, quinta**
  (apresentação, sem prorrogação). Congelamento de escopo em **16/09**; **14–16/09 é reserva
  protegida** para documentação e ensaio de demo (critério de nota), nunca sacrificada por atraso de
  modelagem. **Atenção:** `docs/plano-execucao.md` ainda descreve o cronograma antigo (prazo 14/09,
  congelamento 10/09, reserva 11–13/09) em todas as fases, ondas e no diagrama — vale como registro
  histórico do plano, não como as datas correntes. Em caso de divergência, esta linha vence.
- **Janela temporal e sites (ADR-001/ADR-003):** 2013–2025, multi-sensor — Landsat 8/9 (30 m) para
  2013–2018, Sentinel-2 (10 m) para 2019–2025, harmonizados via `sentinela.gee.harmonizacao`
  (coeficientes Claverie/NASA HLS). `sensor` entra como feature explícita no modelo (SV-12) porque
  o resíduo entre sensores não bateu tolerância em 3 de 6 bandas (NIR, SWIR1, SWIR2). 3 sites:
  `ascenty-vinhedo`, `odata-hortolandia`, `scala-tambore` — ver `config/sites.geojson`.

## As duas frentes, e a linha que as separa

O repositório tem **duas** pastas de código, e a divisão é por assunto, não por cronograma:

| pasta | o que é | prazo |
|---|---|---|
| **`src/sentinela/`** + `config/`, `data/`, `models/`, `tests/` | **o modelo de imagem** — ingestão de satélite, features, treino, classificação | o deste repo |
| **`modelo-impacto/`** | **tudo de impacto** — grupos de controle, os passos 01–41, o boletim por eixo | próprio |

As duas eram três pastas até 2026-09-13 (`dados-modelo-impacto/` e `modelo-impacto-score/`
separadas), e a fronteira entre elas não correspondia a nada: os geradores de notebook do
**modelo de imagem** moravam dentro de `modelo-impacto-score/`, porque era onde já havia gerador
de notebook. A pasta prometia uma coisa e entregava outra. Hoje eles moram em `scripts/`, junto
do classificador que documentam.

**`modelo-impacto/`** (aberta em 2026-09-03, fundida em 2026-09-13) reúne:

- **os dados externos** (temperatura, população, emprego) que apoiam o modelo de impacto do
  Guilherme — ver `README.md`, com as ressalvas conhecidas de granularidade;
- **os passos 01–41**, que selecionam grupo de controle e medem a conversão de cobertura;
- **o boletim por eixo** (`score_*.py`), que responde *qual foi o impacto territorial de cada
  data center, e ele é predizível?* em três camadas (medição / explicação / projeção).
  **Não produz um score único agregado, por decisão de desenho:** publica um boletim por eixo,
  cada um com selo de evidência (`forte` / `sugestivo` / `nulo_informativo` /
  `nulo_amostra_pequena` / `nulo_sem_poder`). Resultado central: o padrão se sustenta (conversão
  no anel de 0,5-1 km, 18/20 pares, p=0,0002), a **magnitude não é predizível** (R² LOOCV
  negativo em 13 modelos, permutação p=0,77). Ver `README-score.md`.

Os 9 notebooks ficam todos em `notebooks/`, dos dois lados — é onde quem chega procura.

## Regras do repositório
- Nunca commitar dado bruto pesado (raster/GeoTIFF), credenciais ou artefato de modelo grande — usar
  `.gitignore` desde o início.
- Seed fixo em qualquer split/treino, para reprodutibilidade.
- Todo experimento registrado (dataset usado, parâmetros, métricas, versão do código).
- Mudança de escopo que afete a etapa de Indicadores (formato de output) ou outras frentes do time
  precisa ser sinalizada antes de implementar, não depois.
