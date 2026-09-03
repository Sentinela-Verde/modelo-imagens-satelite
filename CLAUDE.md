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
- **Cronograma (atualizado 2026-08-27):** este repo usa um cronograma próprio por fases, não mais
  as sprints do Notion — ver `docs/plano-execucao.md`. Prazo final fixo: **14/09/2026** (apresentação,
  sem prorrogação). Congelamento de escopo em 10/09; 11–13/09 é reserva protegida para documentação
  e ensaio de demo (critério de nota), nunca sacrificada por atraso de modelagem.
- **Janela temporal e sites (ADR-001/ADR-003):** 2013–2025, multi-sensor — Landsat 8/9 (30 m) para
  2013–2018, Sentinel-2 (10 m) para 2019–2025, harmonizados via `sentinela.gee.harmonizacao`
  (coeficientes Claverie/NASA HLS). `sensor` entra como feature explícita no modelo (SV-12) porque
  o resíduo entre sensores não bateu tolerância em 3 de 6 bandas (NIR, SWIR1, SWIR2). 3 sites:
  `ascenty-vinhedo`, `odata-hortolandia`, `scala-tambore` — ver `config/sites.geojson`.

## Outras frentes hospedadas neste repositório
- **`dados-modelo-impacto/`** (a partir de 2026-09-03): pasta separada, fora do escopo do
  classificador (`src/sentinela/`), dedicada a apoiar o modelo de impacto de outro integrante do
  time (Guilherme) — levantamento de dados externos (temperatura, população, empregos) para os
  facilities do estudo. Não segue o cronograma/prazo deste repositório. Ver
  `dados-modelo-impacto/README.md` para escopo, ressalvas já conhecidas (granularidade de
  população/emprego, reaproveito do desenho de grupo de controle de SV-29) e status.

## Regras do repositório
- Nunca commitar dado bruto pesado (raster/GeoTIFF), credenciais ou artefato de modelo grande — usar
  `.gitignore` desde o início.
- Seed fixo em qualquer split/treino, para reprodutibilidade.
- Todo experimento registrado (dataset usado, parâmetros, métricas, versão do código).
- Mudança de escopo que afete a etapa de Indicadores (formato de output) ou outras frentes do time
  precisa ser sinalizada antes de implementar, não depois.
