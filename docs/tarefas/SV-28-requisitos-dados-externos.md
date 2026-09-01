# SV-28 — Documento de requisitos de dados externos (handoff para a frente de Engenharia)

- **Fase:** 1b — Expansão · **Data-alvo:** 31/08–01/09 · **Tamanho:** M (~3h)
- **Responsável sugerido:** `ml-engineer` · revisado pelo **humano** antes de circular no time
- **Bloqueado por:** — (nada; é a tarefa mais paralelizável do plano, pode rodar junto com tudo)
- **Desbloqueia:** SV-17 (entra como anexo da documentação final)
- **Tem seção de risco:** não
- **Tipo:** **entregável documental** — não há pipeline, não há código de coleta

## Contexto

O time levantou dois documentos no Notion que ampliam muito o escopo de dados:

- **"Propostas de variáveis"** — ~70 variáveis em 6 dimensões (ambiental, social, econômica,
  infraestrutura, governança, temporal). O próprio documento **já separa corretamente** duas coisas
  que costumam ser confundidas: **"Entradas do Random Forest"** (bandas + NDVI/NDWI/NDBI — que é
  exatamente o que este repositório já constrói em SV-08) e **"Variáveis para avaliar impacto"**
  (pós-classificação: área por classe, deltas de índice, população, renda, MW, distâncias).
- **"Fabio — Pesquisa Indicadores x origens"** — uma arquitetura de produto bem mais ampla: STAC API,
  datalake em S3 com Bronze/Silver/Gold, AWS Glue, Spark, e 12 fontes externas (ANA, INMET, IBGE, OSM,
  SRTM/Copernicus DEM, MapBiomas Alerta, MapBiomas Fogo, áreas protegidas, etc.), mais 12 KPIs de MVP.

**Decisão já tomada pelo usuário, não reabrir:** este repositório é a frente de **Modelagem/ML**.
Ele **não** implementa datalake, STAC, Glue, Spark, nem coleta de variável não-imagem. O que ele pode
fazer — e é onde tem autoridade real, porque é quem constrói o modelo — é **dizer quais dessas
variáveis são de fato úteis, para quê, com qual granularidade, e quais não valem o esforço.**

Um documento que só reempacota as ~70 variáveis do Notion não vale nada; elas já estão lá. **O valor
deste entregável está no parecer** — no que ele recomenda cortar e no que ele recomenda elevar. Um
handoff que diz "coletem tudo" transfere o trabalho de decidir para quem tem menos informação para
decidir.

## Objetivo

`docs/requisitos-dados-externos.md` + um contrato legível por máquina, entregável à frente de
Engenharia, que responde para cada variável proposta: **serve para quê, em que granularidade, de onde
vem, e vale o esforço?**

## Escopo — o que fazer

1. **Classificar cada variável em exatamente um de quatro papéis.** Esta é a espinha do documento, e
   a distinção entre os dois primeiros é a que mais evita erro metodológico:

   | Papel | O que é | Exemplo | Onde é usado |
   |---|---|---|---|
   | **(A) Entrada do modelo** | Alimenta o classificador por pixel | reflectância, NDVI, NDBI, BSI | Já implementado — SV-08 |
   | **(B) Variável de impacto** | Calculada **depois** da classificação, sobre o resultado | área por classe, Δ NDVI pré→pós, ha de vegetação perdida | SV-15, SV-30 |
   | **(C) Confundidor / controle** | Não é impacto: é o que precisa ser descontado para o impacto ser crível | precipitação do ano, seca regional | **Ver item 3** |
   | **(D) Contexto / estratificação** | Descreve o caso, não mede efeito dele | PIB municipal, população, bioma, MW instalado | Comparar casos, agrupar, apresentar |

   **O erro que o documento precisa impedir:** tratar (D) como (B). "A população do município cresceu
   8% depois do data center" **não é um impacto medido** — é uma coincidência temporal num agregado
   municipal. Ver item 2.

2. **Dar o parecer honesto de granularidade — a seção mais valiosa do documento.**
   A AOI deste projeto é um buffer de **5 km** (~78 km²). Quase todo dado socioeconômico brasileiro é
   **municipal**. Um município do porte de Hortolândia ou Uberlândia tem centenas de milhares de
   habitantes; o efeito de um data center de 40 ha **não é detectável** num agregado desse tamanho, e
   afirmar que é seria a falha metodológica mais fácil de derrubar numa banca.

   Diga isso com todas as letras, e ofereça a saída em vez de só o problema:
   - **PIB, renda, emprego, arrecadação, escolaridade, saneamento em nível municipal → papel (D)**,
     contexto e estratificação. **Não são variáveis de impacto do data center.**
   - **Setor censitário do IBGE** é a única granularidade socioeconômica que chega perto de ser
     comparável a uma AOI de 5 km. Se a frente de Engenharia quiser socioeconômico com valor real de
     impacto, **é setor censitário ou nada** — e o custo (compatibilizar setores entre censos 2010 e
     2022) precisa estar declarado, porque é onde o esforço vai de verdade.
   - **Número de racks, ISS do empreendimento, consumo de água do operador:** normalmente não são
     públicos. Marque como **"depende de dado fornecido pelo cliente/operador"** e **não os coloque
     no caminho crítico de nenhum indicador.** Um KPI que depende de dado que ninguém tem é um KPI
     que não existe.

3. **Elevar o que a lista do Notion subestima.** Duas coisas que aparecem como itens secundários e
   que, na verdade, decidem se o resultado do projeto se sustenta:

   - **Clima como confundidor (INMET / ANA) — prioridade máxima entre os dados externos.**
     NDVI cai em ano seco **em todo lugar**, com ou sem data center. Sem série de precipitação, toda
     afirmação de "perda de vegetação" fica indefensável, porque a primeira pergunta de qualquer
     revisor é "e o clima daquele ano?". Requisito mínimo: **precipitação mensal acumulada da estação
     INMET mais próxima, 2013–2025, por AOI.** É barato, é público, e é o dado externo com maior
     razão valor/esforço do conjunto inteiro. A pesquisa do Fabio já aponta exatamente esse uso
     ("Alteração observada, porém potencialmente associada à variabilidade hidrológica") — o documento
     deve endossá-lo e promovê-lo a requisito, não a sugestão.

   - **Grupo de controle pareado — não é uma variável, é um requisito de desenho.**
     "A vegetação caiu 12% em volta do data center" só vira afirmação de impacto quando existe
     "…contra 3% em áreas comparáveis sem data center no mesmo período e no mesmo clima". Nenhum dos
     documentos do Notion menciona isso, e é a diferença entre correlação e evidência.
     **Neste repositório o controle é barato** — é o mesmo pipeline apontado para outras coordenadas
     (SV-29). Registre o requisito aqui e aponte para SV-29.

4. **Priorizar em ondas de implementação para a Engenharia**, com esforço estimado e dependências:

   | Onda | Fontes | Por quê primeiro |
   |---|---|---|
   | **1 — habilita afirmação de impacto** | INMET (precipitação), IBGE malhas municipais/setores, áreas protegidas (ICMBio/UC/TI/APP) | Sem clima não há afirmação defensável; sem áreas protegidas, "4 ha de vegetação" não vira "4 ha, sendo 1,2 em área sensível" — que é o salto de valor de menor custo do conjunto |
   | **2 — contexto territorial** | OSM/Overpass (rodovia, subestação, edificações, hidrografia), SRTM/Copernicus DEM (declividade) | Covariáveis estáticas, computáveis por AOI, sem série temporal para reconciliar |
   | **3 — hidrologia e fogo** | ANA HidroWeb (vazão/nível), MapBiomas Fogo, MapBiomas Alerta | Explicam variação que o satélite vê mas não interpreta |
   | **4 — socioeconômico** | IBGE setor censitário, RAIS/CAGED | Maior esforço, menor poder de detecção na escala da AOI. **Última, e com a limitação declarada** |
   | **Fora de escopo agora** | ISS, arrecadação, nº de racks, consumo de água do operador | Não públicos ou não vinculáveis ao empreendimento |

5. **Contrato legível por máquina:** `docs/contrato-dados-externos.yml`, uma entrada por variável:
   `id`, `nome`, `dimensao`, `papel` (A|B|C|D), `unidade`, `granularidade_espacial`
   (`pixel`|`aoi`|`setor_censitario`|`municipio`|`estacao`), `granularidade_temporal`
   (`anual`|`mensal`|`estatico`), `fonte`, `mecanismo_acesso` (API/STAC/download/Overpass),
   `licenca`, `onda`, `esforco` (`baixo`|`medio`|`alto`), `bloqueadores`, `parecer` (texto curto),
   `usado_neste_repo` (bool).

   O campo `usado_neste_repo` é o que impede o mal-entendido mais provável do handoff: deixa
   explícito, item a item, **o que esta frente já entrega** (bandas, índices, classes, áreas) e o que
   ela **não vai entregar** (todo o resto).

6. **Seção de fronteira, curta e sem rodeio:** o que a frente de ML entrega
   (raster classificado, áreas por classe/ano/AOI, deltas, o CSV de SV-15 com seu schema), o que a
   frente de Engenharia precisa entregar para que os KPIs propostos existam, e **o que fica sem dono**
   se ninguém pegar. Sobre a arquitetura proposta (STAC, S3 Bronze/Silver/Gold, Glue, Spark):
   registre-a como **recomendação recebida e endossada para o produto**, deixando claro que **não é
   pré-requisito de nada que este repositório entrega em 14/09** — o pipeline atual roda local, com
   Earth Engine, e está funcionando. Não crie dependência de infraestrutura que não existe.

## Fora de escopo

- **Implementar qualquer coleta.** Nem um `requests.get` de ANA, INMET, IBGE ou OSM.
- Montar datalake, STAC, Glue ou Spark.
- Decidir a arquitetura da frente de Engenharia. Este documento diz **o quê** e **por quê**;
  o **como** é deles.
- Prometer prazo em nome de outra frente.

## Critérios de aceite

- [ ] `docs/requisitos-dados-externos.md` existe e cobre **todas** as ~70 variáveis da página
      "Propostas de variáveis" — inclusive as recomendadas para descarte, **com o motivo**.
      Uma variável omitida em silêncio vira retrabalho para alguém.
- [ ] Toda variável tem exatamente um papel (A/B/C/D) atribuído.
- [ ] `docs/contrato-dados-externos.yml` carrega com `yaml.safe_load` e tem os campos obrigatórios
      em 100% das entradas.
- [ ] A seção de granularidade afirma explicitamente que **dado socioeconômico municipal não mede
      impacto de data center na escala da AOI de 5 km**, com a justificativa numérica.
- [ ] Clima como confundidor está na **onda 1** e o documento explica por que sem ele a afirmação de
      impacto não se sustenta.
- [ ] O requisito de grupo de controle está registrado e aponta para SV-29.
- [ ] A seção de fronteira lista, item a item, o que esta frente entrega e o que não entrega.
- [ ] **Teste de leitura:** alguém do time que não trabalha em ML consegue, lendo só este documento,
      dizer quais 3 fontes começar a integrar primeiro e por quê. Valide com uma pessoa real do time
      antes de fechar.
- [ ] Nenhuma linha do documento promete algo que este repositório vai coletar.

## Cenários de teste

1. `yaml.safe_load('docs/contrato-dados-externos.yml')` → dict, sem campo obrigatório vazio.
2. Contagem cruzada: nº de entradas no YAML ≥ nº de linhas da tabela do Notion.
3. Filtrar `papel == 'A'` → devolve **exatamente** as features já implementadas em SV-08. Se devolver
   mais, o documento está prometendo entrada de modelo que não existe.
4. Filtrar `usado_neste_repo == true` → nada fora do que `data/manifests/dataset_v0.2.json` lista.
5. Filtrar `onda == 1` → contém INMET-precipitação, IBGE-malhas e áreas protegidas.

## Como reportar

Informe: nº de variáveis classificadas por papel, quais foram recomendadas para descarte e por quê,
quais foram **promovidas** em relação à proposta original (e a justificativa), as 3 fontes da onda 1,
e o resultado do teste de leitura com a pessoa do time.
