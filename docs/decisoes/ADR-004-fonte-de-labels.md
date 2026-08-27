# ADR-004 — Fonte de labels para a série anual (WorldCover vs. MapBiomas)

- **Status:** **Aceito** — opção (b) confirmada pelo usuário em 2026-08-27
- **Proposto em:** 2026-08-27 · **Confirmado em:** 2026-08-27
- **Decisor:** usuário (owner da frente de Modelagem) — confirmado
- **Responsável pela medição:** spike SV-05b (`ml-engineer`)
- `CLAUDE.md` atualizado para refletir esta decisão. SV-07 pode implementar a opção (b).

## Contexto

`CLAUDE.md` registra ESA WorldCover v200 (safra fixa ~2020/2021) como fonte de labels. Essa decisão
presumia uma janela curta e próxima de 2021. A janela do projeto virou 2013–2025 (ADR-001/SV-02),
o que faz uma safra fixa aplicada a 13 anos gerar defasagem de até 8 anos nas pontas — um erro
sistemático correlacionado exatamente com o fenômeno que o projeto quer detectar (ver aviso no topo
de SV-05b). Este ADR registra a evidência medida e a recomendação; **não implementa nada** (isso é
SV-07) e **não redecide as 5 classes** (fechado, ver `docs/classes.md`).

## 1. Disponibilidade no Earth Engine

Verificado em 2026-08-27 com `sentinela.gee.auth.init_ee()`:

- **Asset:** `projects/mapbiomas-public/assets/brazil/lulc/collection9/mapbiomas_collection90_integration_v1`
  (`ee.data.getAsset` retorna `type: IMAGE`, acessível com o projeto GCP já registrado).
- **Versão:** Coleção 9 (asset id confirma `collection9` / `collection90_integration_v1`).
- **Cobertura temporal:** 39 bandas, uma por ano, de `classification_1985` a `classification_2023`.
  **Último ano coberto: 2023.** Não há 2024 nem 2025 — a janela do projeto (2013–2025) fica com um
  buraco de **2 anos na ponta mais recente**, bem menor que os até 8 anos do cenário WorldCover, mas
  real e precisa ser tratado em SV-07 (fallback: replicar 2023 para 2024/2025, com
  `distancia_safra` marcando isso, o mesmo mecanismo já previsto para o cenário de safra fixa).
- **Projeção nativa:** `EPSG:4326`, transform com passo `0.0002694945...°` (~30 m no equador) —
  condiz com a resolução nativa publicada (30 m).
- **Cobertura dos 3 sites:** confirmada — os três buffers de 5 km (`ascenty-vinhedo`,
  `odata-hortolandia`, `scala-tambore`) retornaram ~94 mil pixels válidos cada ao amostrar
  `classification_2021` e `classification_2013`, sem áreas mascaradas/sem dado dentro da AOI.

## 2. Remap MapBiomas → 5 classes

Conferido **código a código** contra a legenda oficial da Coleção 9 (fonte primária, baixada e lida
neste spike, não citada de memória):
<https://brasil.mapbiomas.org/wp-content/uploads/sites/4/2024/08/Legenda-Colecao-9-LEGEND-CODE.pdf>

A tabela completa (37 códigos, nenhum sem destino) está em `config/classes.yml`, seção
`remaps.mapbiomas`, e é testada em `tests/test_classes.py`
(`test_mapbiomas_remap_cobre_toda_legenda_colecao_9`). Resumo:

| Código(s) MapBiomas | Nome oficial | → Nossa classe | Observação |
|---|---|---|---|
| 1, 3, 4, 5, 6, 49 | Floresta e subtipos (Formação Florestal, Savânica, Mangue, Alagável, Restinga Arbórea) | 1 `vegetacao_densa` | |
| 9 | Silvicultura (Forest Plantation) | 1 `vegetacao_densa` | Dossel arbóreo denso — mesmo critério do WorldCover `Tree cover`→1 |
| 10, 12, 50 | Vegetação Herbácea/Arbustiva, Formação Campestre, Restinga Herbácea | 2 `vegetacao_rala` | |
| 11 | Campo Alagado e Área Pantanosa (Wetland) | 0 `nodata` | Ambíguo água/veg. rala — mesmo critério do WorldCover 90 (Herbaceous wetland) |
| 14, 15, 18, 19, 21, 36 e as culturas específicas (39, 20, 40, 62, 41, 46, 47, 35, 48) | Agropecuária, Pastagem, Agricultura (temporária e perene), Mosaico de Usos | 2 `vegetacao_rala` | Inclui Dendê (35, dossel denso) — mantido em 2 por consistência com a decisão já tomada em SV-05 de tratar toda "Agricultura" (WorldCover Cropland) como veg. leve; **decisão de julgamento, sinalizada para o time** |
| 22, 23, 25 | Área não Vegetada, Praia/Duna/Areal, Outras Áreas não Vegetadas | 3 `solo_exposto_obras` | |
| 29 | Afloramento Rochoso (Rocky Outcrop) | 3 `solo_exposto_obras` | Solo/rocha não vegetada natural; **decisão de julgamento** |
| 32 | Apicum (Hypersaline Tidal Flat) | 3 `solo_exposto_obras` | Não ocorre nos 3 sites (sem costa) |
| 30 | Mineração (Mining) | 3 `solo_exposto_obras` | Análogo mais próximo de "solo exposto/obras" na legenda MapBiomas — **decisão de julgamento**, ver seção 6 |
| 24 | Área Urbanizada (Urban Area) | 4 `construida_urbana` | |
| 26, 33, 31 | Corpo D'água, Rio/Lago/Oceano, Aquicultura | 5 `agua` | |
| 27 | Não observado (Not Observed) | 0 `nodata` | |

**Achado central da legenda, confirmado (não hipótese):** nenhum código da Coleção 9 isola
"canteiro de obras" como classe própria. O código mais próximo é `30 Mineração`, que é um fenômeno
distinto (extração, não construção civil/industrial). Isso confirma a hipótese do enunciado de
SV-05b — a rotulagem manual de SV-09/SV-10 continua necessária em **qualquer** cenário (a, b ou c).

## 3. Concordância WorldCover × MapBiomas (2021)

**Alinhamento de grade:** WorldCover (10 m) foi remapeado e depois reprojetado
(`ee.Image.reproject`, nearest neighbor — sem `.resample()`, que trocaria o default) para a
projeção nativa do MapBiomas (30 m), garantindo mesmo CRS/transform/shape antes de comparar
(cenário de teste 2 de SV-05b).

| Site | Pixels válidos (wc≠0 e mb≠0) | Concordância global |
|---|---:|---:|
| ascenty-vinhedo | 93.910 | **67,06%** |
| odata-hortolandia | 93.809 | **70,09%** |
| scala-tambore | 94.228 | **77,27%** |
| **Agregado (3 sites)** | **281.947** | **71,48%** |
| controle (Serra do Japi, mata contínua) | 94.042 | 83,86% |

Faixa plausível (60–90%, cenário de teste 3): **atendida** nos 3 sites — não é comparação da fonte
consigo mesma (>98%), nem remap quebrado (<40%).

**Concordância por classe, agregada nos 3 sites** (duas leituras: % de acordo tomando cada fonte
como referência — nenhuma das duas é "gabarito", por isso as duas leituras):

| Classe | Concordância (base = WorldCover) | Concordância (base = MapBiomas) |
|---|---:|---:|
| 1 `vegetacao_densa` | 37,7% | 98,7% |
| 2 `vegetacao_rala` | 77,4% | 59,4% |
| 3 `solo_exposto_obras` | **15,3%** | **30,1%** |
| 4 `construida_urbana` | 96,3% | 74,6% |
| 5 `agua` | 75,8% | 68,0% |

**Atenção às classes 3 e 4, como pedido:** classe 3 tem a pior concordância das cinco em qualquer
leitura (15–30%) — esperado, já que nenhuma das duas fontes tem uma classe "canteiro de obras" de
verdade (WorldCover: solo natural exposto; MapBiomas: sem classe equivalente, cai em "não
vegetada"/mineração). Classe 4 tem concordância alta pela ótica do WorldCover (96,3%) mas bem mais
baixa pela ótica do MapBiomas (74,6%) — sinal de que o MapBiomas rotula como "vegetação densa" ou
"vegetação rala" uma quantidade grande de pixels que o WorldCover rotula como "construída" (efeito
de resolução: em 30 m, um pixel misto quintal-com-árvores-e-telhado tende a puxar para vegetação
pela regra de maioria; em 10 m o WorldCover resolve o telhado à parte). Isso é evidência direta do
argumento de resolução do enunciado.

## 4. Inspeção visual dos 15 pixels de discordância

Amostrados 15 pixels discordantes (5 por site, cobrindo os pares de maior volume de discordância —
`(1,2)`, `(1,4)`, `(4,2)`, `(2,4)` — e pelo menos um envolvendo a classe crítica 3 por site), com
seed fixo (42, conforme regra do `CLAUDE.md`). Para cada um, gerado um chip RGB (Sentinel-2,
composto jun–set/2021, 300×300 m em torno do pixel) e inspecionado visualmente.
Chips em `reports/figures/sv05b_discordancia/` (nome do arquivo = `site_wcX-slug_mbY-slug.png`).

| Chip | WorldCover diz | MapBiomas diz | O que a imagem mostra | Veredito |
|---|---|---|---|---|
| ascenty-vinhedo (1,2) | veg. densa | veg. rala | Copa escura de árvore isolada cercada de telhados/solo — pixel de borda | Ambíguo (efeito de borda/resolução) |
| ascenty-vinhedo (1,4) | veg. densa | construída | Mistura de telhados, solo exposto e copas — sem dominância clara | Ambíguo (efeito de resolução) |
| ascenty-vinhedo (2,4) | veg. rala | construída | Estradas de terra e vegetação esparsa, sem edificação evidente | Nenhuma clara — leve viés a WorldCover |
| ascenty-vinhedo (3,2) | solo exposto | veg. rala | Grande mancha laranja/terra nua uniforme, sem vegetação visível | **WorldCover correto** |
| ascenty-vinhedo (4,2) | construída | veg. rala | Vegetação com trilha/objeto claro pequeno, sem edificação evidente | **MapBiomas correto** |
| odata-hortolandia (1,2) | veg. densa | veg. rala | Copas escuras entre telhados — pixel de borda | Ambíguo (efeito de resolução) |
| odata-hortolandia (1,4) | veg. densa | construída | Área acastanhada/agrícola, sem copa densa nem edificação claras | Nenhuma das duas — provável solo/agricultura mal capturado por ambas |
| odata-hortolandia (2,4) | veg. rala | construída | Telhados claros nítidos + via pavimentada visíveis | **MapBiomas correto** |
| odata-hortolandia (3,2) | solo exposto | veg. rala | Grande mancha de solo nu alaranjado, sem vegetação | **WorldCover correto** |
| odata-hortolandia (4,2) | construída | veg. rala | Telhados cerâmicos alternados com árvores — padrão residencial arborizado | **WorldCover correto** |
| scala-tambore (1,2) | veg. densa | veg. rala | Copa densa e escura dominante, poucas manchas claras | **WorldCover correto** |
| scala-tambore (1,4) | veg. densa | construída | Cobertura arbórea densa dominante | **WorldCover correto** |
| scala-tambore (2,4) | veg. rala | construída | Objeto claro pequeno em meio a mistura, ambíguo | Ambíguo (efeito de resolução) |
| scala-tambore (3,4) | solo exposto | construída | **Telhado retangular nítido**, claramente uma edificação | **MapBiomas correto** |
| scala-tambore (4,2) | construída | veg. rala | Vegetação densa dominante com trilha clara central | **MapBiomas correto** |

**Contagem do veredito:** WorldCover claramente certo em 5/15 (solo exposto real, copa densa real);
MapBiomas claramente certo em 4/15 (telhado confundido com solo exposto pelo WorldCover — uma
confusão espectral conhecida do produto, não só efeito de escala; e área verde arborizada confundida
com "construída"); 6/15 ambíguos, dominados por efeito de mistura de pixel na borda entre classes
(resolução 10 m vs 30 m, exatamente o argumento do enunciado). **Nenhuma das duas fontes é
uniformemente superior** — os dois produtos erram de formas diferentes e complementares.

## 5. Percentual de mudança MapBiomas 2013 → 2021, por site

| Site | Pixels válidos | % de pixels que mudaram de classe |
|---|---:|---:|
| ascenty-vinhedo | 94.570 | **5,18%** |
| odata-hortolandia | 94.453 | **6,00%** |
| scala-tambore | 94.854 | **4,23%** |
| controle (Serra do Japi, mata contínua, sem data center) | 94.675 | 2,98% |

Cenário de teste 4 atendido: os 3 sites com data center construído no período têm mudança maior que
o controle de mata contínua (4,23–6,00% vs 2,98%). Esse é o custo quantificado de aplicar uma safra
fixa de 2021 aos outros 12 anos da série: **entre 4 e 6 em cada 100 pixels do entorno de cada site
mudaram de classe real entre 2013 e 2021** — e o WorldCover, fixo em 2021, atribuiria a esses pixels
o mesmo label nos 13 anos, inclusive nos anos em que a classe real já era outra.

## 6. A pergunta difícil: "o que o nosso modelo acrescenta, se o MapBiomas já existe?"

A concordância medida (67–77%, média 71,5%) e a inspeção visual mostram que WorldCover e MapBiomas
não são a mesma informação em resoluções diferentes — eles erram de formas diferentes e
complementares (1/3 dos 15 casos favoreceu claramente o WorldCover, principalmente solo exposto real
e copa densa real onde 30 m mistura demais; ~1/4 favoreceu claramente o MapBiomas, incluindo um caso
concreto de telhado claro confundido com solo exposto pelo algoritmo do WorldCover — uma fraqueza
específica do produto, não apenas de escala; o resto foi efeito genuíno de pixel misto na borda entre
classes). E, confirmado código a código na legenda oficial da Coleção 9, **nenhuma das duas fontes
modela "canteiro de obras" como classe própria** — o mais perto que o MapBiomas chega é "Mineração",
um fenômeno diferente. Isso significa que, mesmo adotando MapBiomas como base, a contribuição deste
projeto não desaparece: ela migra para exatamente os pontos onde os dois produtos nacionais são
estruturalmente fracos — resolução de 10 m no entorno imediato de um único ativo (onde 30 m borra a
transição vegetação→canteiro→construído, que é o sinal-alvo do projeto), atualidade (a Coleção 9 vai
até 2023; hoje, 27/08/2026, isso já são quase 3 anos de defasagem, e um sistema de monitoramento
precisa da imagem do mês passado, não da próxima safra anual do MapBiomas), e a classe crítica em si,
que continua dependendo da rotulagem manual de SV-09/SV-10 em qualquer cenário.

Na prática, isso muda o que precisa estar escrito no TCC e no model card: o projeto não compete com o
MapBiomas como classificador de cobertura do solo do Brasil — ele é um **detector de alta resolução
e quase tempo real do estado transitório "canteiro de obras" no entorno específico de data centers**,
que usa o MapBiomas (mais rotulagem manual) como o melhor label anual disponível para treinar essa
tarefa mais estreita e mais difícil que nenhum dos dois produtos nacionais resolve sozinho. Se isso
ficar implícito, a pergunta da banca vira um ponto fraco real; escrito assim, explicitamente, vira um
argumento a favor do projeto.

## Recomendação: **(b)** — MapBiomas como fonte principal, WorldCover como verificação cruzada

- **MapBiomas** como label anual principal para 2013–2023 (cobre toda a Faixa A menos os últimos 2
  anos), resolvendo o erro sistemático de defasagem medido na seção 5 (4,2–6,0% de mudança real por
  site entre 2013 e 2021 sozinho).
- **2024 e 2025:** sem cobertura MapBiomas (coleção vai até 2023) — replicar o label de 2023, com
  `distancia_safra` marcando a defasagem (no máximo 2 anos, não os até 8 anos do cenário WorldCover
  puro). Registrar isso explicitamente em SV-07.
- **WorldCover como verificação cruzada apenas em 2021** (único ano de sobreposição real —
  WorldCover v200 é uma safra única, não uma série; não pode ponderar nenhum outro ano da série).
  Nesse ano, pixels onde as duas fontes concordam (71,5% agregado nos 3 sites) entram com peso maior
  no dataset de SV-11; pixels discordantes — inclusive praticamente toda a classe 3 (concordância de
  15–30%, a pior das cinco) — entram com peso menor ou ficam reservados para a rotulagem manual de
  SV-09/SV-10, que continua obrigatória para a classe crítica em qualquer cenário.
- **Por que não (a):** descartar o WorldCover jogaria fora um sinal de qualidade real e barato — a
  inspeção visual mostrou que o WorldCover acerta em casos que o MapBiomas erra (copa densa e solo
  exposto genuínos, onde 30 m generaliza demais), e a infraestrutura de remap já existe desde SV-05.
  Não há custo de manter os dois; há custo real (perda de sinal) em descartar um deles.
- **Por que não (c):** a defasagem de safra fixa (seção 5) é grande demais para ser tolerável numa
  série de 13 anos — 4 a 6 em cada 100 pixels do entorno de cada site mudam de classe real só entre
  2013 e 2021, e isso é sistemático, não ruído aleatório.

## Limitações e trabalho futuro

- Item 3 desta seção (11 `Wetland` → nodata) e a decisão de tratar Mineração/Afloramento Rochoso
  como classe 3, e toda a Agricultura (inclusive Dendê, dossel denso) como classe 2, são **decisões
  de julgamento** que seguem o mesmo critério já adotado para o WorldCover em SV-05 — sinalizadas
  aqui para revisão do time, não implementadas como se fossem óbvias.
- 2024–2025 sem cobertura MapBiomas — mitigado com replicação de 2023, mas é uma lacuna real.
- Este spike não testa Faixa B (2000–2011): a Coleção 9 cobre 1985–2023, então tecnicamente cobriria,
  mas isso segue fora de escopo aqui (SV-02b ainda não validou a harmonização TM→OLI necessária).

## Confirmação — recebida

Recomendação (opção b) apresentada ao usuário (owner da frente de Modelagem) em 2026-08-27, com toda
a evidência medida nesta página. **Confirmada no mesmo dia**, sem objeção nem ajuste ao proposto.
`CLAUDE.md` foi atualizado para registrar a nova fonte de labels como decisão fechada. SV-07 pode
implementar a opção (b) como especificada nas seções 2–5 acima. A confirmação com o restante do
time (além do usuário) fica registrada como pendência de comunicação, não de implementação — não
bloqueia SV-07.
