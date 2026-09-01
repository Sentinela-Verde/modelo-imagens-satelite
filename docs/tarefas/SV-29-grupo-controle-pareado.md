# SV-29 — Grupo de controle pareado (AOIs sem data center)

- **Fase:** 3 — Análise · **Data-alvo:** 06/09 · **Tamanho:** M (~3h + ~2h de relógio de parede de ingestão)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-25 (coordenadas dos sites reais), SV-14 (inferência funcionando)
- **Desbloqueia:** SV-30
- **Tem seção de risco:** **SIM** (é o que separa "correlação apresentada como impacto" de evidência)

## Contexto

Todo o valor do projeto está numa frase do tipo: *"a vegetação no entorno do data center X caiu 12%
entre 2018 e 2023"*. O problema é que essa frase, sozinha, **não sustenta nenhuma afirmação de
impacto**. No mesmo período, no mesmo bioma, a vegetação caiu quanto **em geral**? Se caiu 11%, o data
center não explica nada. Se caiu 2%, aí sim há algo a dizer.

Nenhum dos documentos do time — nem as listas de sites, nem "Propostas de variáveis", nem a pesquisa
de arquitetura — menciona grupo de controle. É a lacuna metodológica mais séria do projeto e,
por sorte, **a mais barata de fechar neste repositório**: é o mesmo pipeline, apontado para outras
coordenadas. Nenhum código novo de ingestão, nenhum modelo novo, nenhuma rotulagem.

A expansão de 3 para ~25 AOIs é justamente o que torna isso viável: com 3 sites, um contra-factual
seria anedota; com ~25 tratamentos e ~25 controles pareados, o contraste vira medida.

## Objetivo

Um conjunto de AOIs de controle, pareadas com as AOIs de tratamento por critério explícito e
verificável, processadas pelo mesmo pipeline, para que SV-30 possa reportar **impacto líquido**
(tratamento menos controle) em vez de variação bruta.

## Escopo — o que fazer

1. **Gerar candidatos a controle**, um ou dois por AOI de tratamento. Para cada AOI real, sortear
   pontos que satisfaçam **todas** as condições:
   - **Distância:** entre **15 e 40 km** do data center. Perto demais entra no raio de influência do
     próprio empreendimento (é tratamento disfarçado de controle, o pior erro possível aqui);
     longe demais muda clima, solo e dinâmica regional e deixa de ser comparável.
   - **Mesmo município ou município vizinho** — mantém regime de licenciamento, pressão de expansão
     urbana e regime de chuva comparáveis.
   - **Cobertura inicial semelhante:** no ano de referência **pré** da AOI de tratamento, a
     distribuição de classes do controle (do raster de label MapBiomas, num buffer de 5 km) tem
     distância L1 **≤ 0,20** contra a do tratamento. É o pareamento propriamente dito: um controle de
     mata fechada não pareia com um tratamento que era pasto.
   - **Sem data center conhecido:** o ponto não está a menos de 5 km de nenhuma AOI de
     `config/sites_candidatos.csv`, **inclusive das rejeitadas**. As rejeitadas são exatamente onde
     há data center que não entrou no estudo — usar uma delas como controle contaminaria a comparação.
   - **Não intersecta o buffer de nenhuma outra AOI**, de tratamento ou de controle.

2. **Escrever em `config/sites_controle.geojson`**, no **mesmo schema** de `config/sites.geojson`
   (para que os CLIs existentes rodem sem modificação), com:
   `site_id` (`ctrl-{aoi_id}-1`), `pareado_com` (o `aoi_id` do tratamento), `distancia_km`,
   `l1_cobertura` (a distância de pareamento medida), `metodo_pareamento`, `tipo: controle`,
   e os **mesmos** `periodo_pre` / `periodo_durante` / `periodo_pos` **herdados do tratamento** —
   um controle não tem obra, mas precisa das mesmas janelas de tempo, senão a comparação não é
   sobre o mesmo período.

3. **Rodar o pipeline existente sobre os controles**: SV-06b, SV-06, SV-07, SV-08 e a inferência de
   SV-14, via o lote de SV-26 com `--sites-file config/sites_controle.geojson`.
   Custo estimado: ~16 rasters por controle × N controles. **Se o relógio apertar, um controle por
   tratamento basta** — e priorize os controles das AOIs de **tier 1**.

   **Controles não entram no treino.** Nunca. Nem em `dataset_v0.2`, nem em SV-16. Eles são
   exclusivamente superfície de medição em SV-30. Um controle que vazou para o treino deixa de ser
   contra-factual independente e a comparação inteira perde o sentido.

4. **Relatório de pareamento** `reports/pareamento_controle.csv` + resumo em markdown: por par,
   `aoi_tratamento`, `aoi_controle`, `distancia_km`, `l1_cobertura`, distribuição de classes das duas
   no ano pré, e um **flag de qualidade do pareamento** (`bom` ≤ 0,10 · `aceitavel` ≤ 0,20 ·
   `ruim` > 0,20). Pares `ruim` **são reportados, não escondidos** — e SV-30 os exclui do agregado,
   dizendo quantos foram excluídos.

5. **Figura de sanidade** por par: composto RGB lado a lado (tratamento × controle) no ano pré, em
   `reports/figures/controle/{aoi_id}.png`. Serve para o olho humano rejeitar em 10 segundos um
   pareamento que a métrica L1 aprovou por acidente — por exemplo, controle que caiu sobre um
   aeroporto ou dentro de uma represa.

## Fora de escopo

- Inferência causal formal (DiD com erros-padrão, matching por propensity score, testes de tendências
  paralelas). **Não há prazo** e o N não sustenta. O que se entrega é um **contraste pareado
  descritivo**, e o documento tem que dizer isso nessas palavras.
- Usar controles como dado de treino (proibido — item 3).
- Rotulagem manual nos controles.

## Seção de risco

| Risco | Por que importa | Mitigação |
|---|---|---|
| **Controle dentro do raio de influência do próprio data center** | Subestima o impacto e faz o projeto parecer que "não achou nada". É o erro mais difícil de perceber depois | Distância mínima de 15 km + verificação contra **todas** as AOIs, inclusive as rejeitadas |
| **Pareamento ruim apresentado como bom** | Um contraste contra um controle não comparável é pior que nenhum contraste — dá falsa confiança | `l1_cobertura` medida, publicada e com flag; pares `ruim` excluídos do agregado com a contagem declarada |
| **Afirmação causal além do que o desenho sustenta** | "O data center causou a perda de vegetação" é uma afirmação sobre uma empresa real que este desenho **não** prova | SV-30 obrigada a usar linguagem de contraste ("variação observada X contra Y no controle pareado"), nunca de causa. Escreva a limitação no output, não só no relatório |
| **Controle sorteado sobre área com outra obra grande** (rodovia, loteamento, mineração) | Vira um "controle" que também sofreu conversão de solo | Figura de sanidade por par + inspeção humana dos pares que SV-30 marcar como outliers |

## Critérios de aceite

- [ ] `config/sites_controle.geojson` existe, com ≥ 1 controle por AOI de tier 1 e schema compatível
      com `config/sites.geojson` (os CLIs existentes rodam sem alteração).
- [ ] Nenhum controle a menos de 15 km do seu tratamento; nenhum a menos de 5 km de qualquer AOI de
      `sites_candidatos.csv`, **inclusive rejeitadas** (teste automatizado bloqueante).
- [ ] Nenhum buffer de controle intersecta outro buffer, de controle ou de tratamento.
- [ ] `l1_cobertura` calculada e registrada para 100% dos pares.
- [ ] ≥ 70% dos pares são `bom` ou `aceitavel`. Abaixo disso, o critério de pareamento não está
      funcionando naquele bioma — **reporte, não afrouxe o limiar.**
- [ ] Séries ingeridas e classificadas para todos os controles de tier 1.
- [ ] **Nenhum `site_id` começando com `ctrl-` aparece em `dataset_v0.2.parquet`** (teste bloqueante).
- [ ] Figuras de sanidade geradas e inspecionadas; qualquer par obviamente ruim está marcado `ruim`.

## Cenários de teste

1. Gerar controles para uma AOI → pontos dentro da faixa de distância, fora de todos os buffers.
2. Forçar um candidato a 8 km → rejeitado pela regra de distância.
3. Colocar um candidato sobre uma AOI rejeitada da lista → rejeitado pela regra de contaminação.
4. `pandas.read_parquet(dataset_v0.2).site_id.str.startswith('ctrl-').any() == False`.
5. Rodar duas vezes com a mesma seed → mesmos controles (o sorteio é determinístico).
6. Inspeção visual de 3 pares → o controle é plausivelmente comparável ao tratamento no ano pré.

## Como reportar

Informe: nº de controles gerados e por tratamento, a tabela de pareamento com `distancia_km` e
`l1_cobertura`, a distribuição dos flags de qualidade, quais pares foram marcados `ruim` e por quê,
e o custo de relógio de parede da ingestão dos controles.
