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
- **Fonte de labels:** ESA WorldCover (v200) como labels fracos/iniciais + rotulagem manual
  complementar para a classe "solo exposto/em obras" (o WorldCover é de safra fixa ~2020/2021 e não
  captura esse estado transitório).
- **V1 (mínimo necessário):** modelo supervisionado baseline (Random Forest/scikit-learn), dataset
  de modelagem versionado, avaliação com métricas documentadas (accuracy, F1 por classe, matriz de
  confusão), classificação reproduzível, output consumível pela etapa de Indicadores (05).
- **Plus (só depois do V1 fechado):** segmentação semântica, Deep Learning avançado, Siamese CNN
  para change detection, comparação de abordagens.
- **Split:** nunca aleatório por pixel — usar split espacial e/ou temporal explícito para evitar
  vazamento de dados entre treino/teste.
- **Cronograma:** Sprint 3 (25/08–31/08) = classes + dataset de modelagem · Sprint 4 (01/09–07/09) =
  baseline + avaliação + handoff pra Indicadores · Sprint 5 (08/09–14/09) = Plus, se houver folga.

## Regras do repositório
- Nunca commitar dado bruto pesado (raster/GeoTIFF), credenciais ou artefato de modelo grande — usar
  `.gitignore` desde o início.
- Seed fixo em qualquer split/treino, para reprodutibilidade.
- Todo experimento registrado (dataset usado, parâmetros, métricas, versão do código).
- Mudança de escopo que afete a etapa de Indicadores (formato de output) ou outras frentes do time
  precisa ser sinalizada antes de implementar, não depois.
