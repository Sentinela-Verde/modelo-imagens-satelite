# Requisitos de dados externos — handoff para a frente de Engenharia (SV-28)

- **Autor:** frente de Modelagem/ML · **Data:** 2026-08-31
- **Revisado por:** humano (pendente — ver seção "Pendente de confirmação" no final)
- **Complementa:** `docs/contrato-dados-externos.yml` (mesmo conteúdo, legível por máquina, uma
  entrada por variável)
- **Fontes originais:** páginas Notion "❓ Propostas de variáveis" (~75 linhas na tabela principal)
  e "Fabio — Pesquisa Indicadores x origens" (arquitetura + 12 fontes externas + 14 KPIs de MVP)

## O que este documento é e o que ele não é

Este documento **não reempacota** as ~75 variáveis do Notion — elas já estão lá, e uma cópia não
vale nada. O valor está no parecer: **o que cortar, o que elevar, com qual granularidade cada coisa
faz sentido, e em que ordem a Engenharia deveria integrar**. Quem tem autoridade para dizer isso é
quem constrói o modelo, porque é quem sabe o que efetivamente alimenta o classificador e o que só
descreve o caso.

Este repositório é a frente de **Modelagem/ML**. Ele **não implementa** datalake, STAC, Glue, Spark
nem coleta de nenhuma variável externa — nem um `requests.get` de ANA, INMET, IBGE ou OSM. Tudo
abaixo é análise e recomendação, para a frente de Engenharia decidir como implementar.

---

## 1. Os quatro papéis — e o erro que este documento existe para impedir

Toda variável proposta cai em exatamente um destes quatro papéis:

| Papel | O que é | Exemplo | Onde é usado |
|---|---|---|---|
| **(A) Entrada do modelo** | Alimenta o classificador por pixel | reflectância, NDVI, NDBI, BSI | Já implementado — SV-08 |
| **(B) Variável de impacto** | Calculada **depois** da classificação, sobre o resultado | área por classe, Δ NDVI pré→pós, ha de vegetação perdida | SV-15, SV-30 |
| **(C) Confundidor / controle** | Não é impacto: é o que precisa ser descontado para o impacto ser crível | precipitação do ano, seca regional, queimada | Onda 1/3 (ver seção 3) |
| **(D) Contexto / estratificação** | Descreve o caso, não mede efeito dele | PIB municipal, população, bioma, MW instalado | Comparar casos, agrupar, apresentar |

**O erro que este documento precisa impedir:** tratar (D) como (B). *"A população do município
cresceu 8% depois do data center"* **não é um impacto medido** — é uma coincidência temporal num
agregado municipal que tem dezenas de outras causas simultâneas (migração, outros empreendimentos,
ciclo econômico regional). É contexto, não evidência. A seção 2 explica por quê, com números.

### Resultado da classificação (93 entradas no contrato, cobrindo as 75 da tabela do Notion)

| Papel | Contagem | Significado |
|---|---:|---|
| A — entrada do modelo | **13** | Exatamente as 13 features que SV-08 já produz (6 bandas harmonizadas + NDVI/EVI/NDWI/MNDWI/NDBI/BSI/NDMI) — nem mais, nem menos |
| B — variável de impacto | **11** | Área por classe, mudança de cobertura, deltas pré/pós — a maioria já contratada via ADR-002/SV-15/SV-30 |
| C — confundidor/controle | **6** | Precipitação, uso/demanda de água regional, alertas de desmatamento e fogo, cobertura de nuvens |
| D — contexto/estratificação | **63** | A maioria absoluta: quase todo o dado socioeconômico, de infraestrutura e de governança proposto descreve o caso, não mede o efeito dele |

O fato de 63 das 93 entradas caírem em (D) não é um problema do documento — é o retrato honesto da
proposta original: a maior parte do que foi levantado serve para **descrever e comparar** os casos,
não para **medir impacto**. Tratar isso como se fosse impacto é exatamente o erro da seção acima.

---

## 2. O parecer honesto de granularidade — a seção mais valiosa deste documento

A AOI deste projeto é um **buffer de 5 km** ao redor de cada data center (~78 km²). Quase todo dado
socioeconômico brasileiro publicado é **municipal**.

**Por que isso importa, com números:** Hortolândia (sede do site `odata-hortolandia`) tem cerca de
230 mil habitantes; Barueri (`scala-tambore`) e Vinhedo/entorno também são municípios de dezenas a
centenas de milhares de habitantes. Um data center de referência neste projeto ocupa dezenas de
hectares — uma fração ínfima da área e da população do município inteiro. **O efeito de um
empreendimento desse porte não é estatisticamente detectável num agregado municipal**, e afirmar que
é seria a falha metodológica mais fácil de derrubar numa banca: qualquer variação de PIB, renda ou
população do município tem, com folga, mais causas concorrentes plausíveis do que o data center
sozinho.

Consequência direta para a classificação acima:

- **PIB, renda, emprego, arrecadação, escolaridade, saneamento em nível municipal → papel (D)**,
  contexto e estratificação. **Não são variáveis de impacto do data center**, por mais que o Notion
  as liste ao lado de NDVI e área construída. No contrato (`contrato-dados-externos.yml`), toda
  variável com `granularidade_espacial: municipio` tem esse aviso no campo `parecer`.
- **Setor censitário do IBGE é a única granularidade socioeconômica que chega perto de ser
  comparável a uma AOI de 5 km.** Se a Engenharia quiser socioeconômico com valor real de impacto,
  **é setor censitário ou nada** — ver `ibge_setor_censitario_socioeconomico` no contrato. O custo
  real não é o download: é **compatibilizar a malha de setores censitários entre os Censos 2010 e
  2022** (a malha muda de um censo para o outro), e isso está declarado explicitamente no campo
  `bloqueadores` dessa entrada, com `esforco: alto`, onda 4 (última prioridade).
- **Número de racks, ISS do empreendimento, arrecadação atribuível, consumo de água/energia do
  operador:** normalmente **não são públicos**. Estão marcados `onda: fora_de_escopo` e
  `mecanismo_acesso: "dado do cliente/operador"` no contrato — e nenhum indicador deste projeto
  depende deles no caminho crítico. Um KPI que depende de dado que ninguém tem é um KPI que não
  existe.

---

## 3. O que a lista do Notion subestima

Duas coisas aparecem como itens secundários (ou nem aparecem) na proposta original, e são as que
mais decidem se o resultado do projeto se sustenta numa banca.

### 3.1 Clima como confundidor (INMET/ANA) — prioridade máxima entre os dados externos

**NDVI cai em ano seco em todo lugar, com ou sem data center.** Sem uma série de precipitação, toda
afirmação de "perda de vegetação" fica indefensável, porque a primeira pergunta de qualquer revisor
é *"e o clima daquele ano?"*.

A própria pesquisa do Fabio já chega a essa conclusão, embora sem elevá-la a requisito — ela descreve
o caso de uso exato:

> *"O modelo detecta: redução de 12% da superfície de um lago. Mas simultaneamente: precipitação caiu
> 30% naquele período. Então o sistema pode indicar: 'Alteração observada, porém potencialmente
> associada à variabilidade hidrológica.'"*

Este documento **promove esse uso de sugestão a requisito**: a variável `clima_precipitacao_inmet`
no contrato (papel C, **onda 1**) especifica precipitação mensal acumulada, estação INMET mais
próxima de cada AOI, 2013–2025. É barata (dados abertos, API do INMET/BDMEP), pública, e tem a maior
razão valor/esforço do conjunto inteiro. **Não estava na tabela de 75 variáveis do Notion.**

Ela é o principal motivo de a onda 1 existir: sem ela, nenhuma afirmação de mudança ambiental deste
projeto é defensável — nem para os tratamentos, nem para o próprio contraste com o grupo de
controle (seção 3.2).

### 3.2 Grupo de controle pareado — não é uma variável, é um requisito de desenho

**Nenhum dos dois documentos do Notion menciona isso**, e é a diferença entre correlação e evidência.

*"A vegetação caiu 12% em volta do data center"* só vira afirmação de impacto quando existe
*"…contra 3% em áreas comparáveis sem data center, no mesmo período e no mesmo clima"*. Sem
contraste, 12% pode ser exatamente o que aconteceu em qualquer lugar da região naquele período —
clima, expansão urbana geral, ciclo agrícola.

**Por isso este item não tem entrada em `contrato-dados-externos.yml`**: ele não é uma variável a
ser coletada de uma fonte externa — é um **requisito de desenho do próprio pipeline de ML**, e
**neste repositório o controle é barato**: é o mesmo pipeline de ingestão/classificação apontado
para outras coordenadas, sem coleta nova, sem modelo novo, sem rotulagem nova.

**Já está especificado em `docs/tarefas/SV-29-grupo-controle-pareado.md`** (geração de AOIs de
controle pareadas por distância, cobertura inicial e ausência de outro data center conhecido) e
consumido em `docs/tarefas/SV-30-perfil-pre-durante-pos.md` (contraste tratamento × controle,
`delta_liquido`). A Engenharia não precisa fazer nada aqui — é registrado neste documento só para
que ninguém, lendo só o Notion, conclua que essa lacuna metodológica ainda está aberta.

---

## 4. Ondas de priorização para a Engenharia

Esforço estimado e dependências, do que habilita uma afirmação defensável primeiro para o que tem
menor poder de detecção na escala da AOI.

| Onda | Fontes (ids no contrato) | Por quê primeiro |
|---|---|---|
| **1 — habilita afirmação de impacto** | `clima_precipitacao_inmet` (INMET), `ibge_malhas_territoriais` (IBGE, malha municipal + setores), `amb_proximidade_area_protegida` + `amb_area_vegetacao_perdida_area_protegida` (ICMBio/MMA/CNUC — UC/TI/APP) | Sem clima não há afirmação defensável (seção 3.1). Sem áreas protegidas, "4 ha de vegetação perdida" não vira "4 ha, sendo 1,2 ha em área sensível" — o salto de valor de menor custo do conjunto inteiro. As malhas do IBGE são o pré-requisito técnico barato para agregar qualquer variável municipal ou de setor censitário a uma AOI |
| **2 — contexto territorial** | OSM/Overpass: `infra_distancia_subestacao`, `infra_distancia_linha_transmissao`, `infra_distancia_rodovias`, `infra_distancia_aeroportos`, `amb_distancia_corpos_dagua`, `amb_distancia_rios_lagos`, `soc_distancia_areas_residenciais/escolas/hospitais`; SRTM/Copernicus DEM: `topografia_declividade_dem`; `infra_potencia_energetica_disponivel` (ONS) | Covariáveis estáticas, computáveis por AOI num único lote de chamadas Overpass + um download de DEM, sem série temporal para reconciliar |
| **3 — hidrologia e fogo** | `amb_uso_agua_entorno`, `amb_demanda_hidrica`, `amb_bacia_hidrografica` (ANA HidroWeb), `mapbiomas_fogo_queimadas`, `mapbiomas_alerta_desmatamento` (MapBiomas Fogo/Alerta) | Explicam variação que o satélite vê mas não interpreta sozinho: um lago que encolheu por seca, uma queda de vegetação por queimada regional |
| **4 — socioeconômico** | `ibge_setor_censitario_socioeconomico` (setor censitário — a única forma válida), mais as variáveis municipais de contexto (`soc_*`, `eco_pib_*`, etc.) | Maior esforço (compatibilizar setores 2010↔2022), menor poder de detecção na escala da AOI (seção 2). **Última onda, com a limitação declarada em cada entrada** |
| **Fora de escopo agora** | `eco_numero_racks`, `eco_iss_empreendimento`, `eco_arrecadacao_municipal`, `eco_investimento_anunciado`, `eco_capacidade_ti_mw`, `eco_consumo_demanda_energia`, `eco_area_empreendimento`, `eco_area_construida_empreendimento`, `eco_numero_empregos_gerados`, `governanca_consumo_agua_operador`, `infra_distancia_cabos_submarinos`, `infra_conectividade_fibra` | Não públicos, não vinculáveis de forma verificável ao empreendimento específico, ou baixa relação com o objetivo ambiental do projeto (12 entradas — ver seção 5) |

**As 3 fontes para a Engenharia começar a integrar primeiro, em ordem: INMET (precipitação),
malhas territoriais do IBGE, e o polígono de áreas protegidas (ICMBio/MMA/CNUC).** Todas onda 1,
todas dados abertos, nenhuma depende de infraestrutura nova — download/API direto.

---

## 5. Variáveis recomendadas para descarte (ou "fora de escopo agora") — com o motivo

Nenhuma variável da tabela do Notion foi omitida deste documento — inclusive as recomendadas para
descarte estão no contrato, com `onda: fora_de_escopo` e o motivo no campo `bloqueadores`/`parecer`.
Resumo:

| Variável | Motivo do descarte |
|---|---|
| `eco_numero_racks` | Normalmente não é público; não colocar no caminho crítico de nenhum indicador |
| `eco_iss_empreendimento` | Protegido por sigilo fiscal; sem fonte pública |
| `eco_arrecadacao_municipal` | Agregada por município inteiro; sem como isolar a contribuição de um empreendimento específico |
| `eco_investimento_anunciado` | Não sistematicamente público; quando existe, vem de imprensa, sem padrão nem cobertura garantida |
| `eco_capacidade_ti_mw`, `eco_consumo_demanda_energia` | Não público de forma padronizada; ONS/ANEEL agregam por subestação, não por operador — levantamento manual caso a caso, não automatizável |
| `eco_area_empreendimento`, `eco_area_construida_empreendimento` | Depende de documento de licenciamento ou disclosure do cliente; sem API. A área construída **medida pela classificação** (`amb_area_construida`, papel B) já cobre a necessidade analítica real |
| `eco_numero_empregos_gerados` | RAIS é agregada por município/setor, não isola um empreendimento; número divulgado pela própria empresa não é verificável |
| `governanca_consumo_agua_operador` | Normalmente não público (item citado explicitamente na tarefa original como dependente do cliente) |
| `infra_distancia_cabos_submarinos`, `infra_conectividade_fibra` | Sem fonte pública estruturada e consistente; baixa relação com o objetivo ambiental do projeto (o produto é monitoramento de cobertura do solo, não conectividade digital) |

Nenhuma dessas variáveis é tecnicamente impossível de obter — o ponto é que **nenhuma delas deveria
estar no caminho crítico de um indicador do MVP**, porque a cobertura de dados não é garantida.

---

## 6. Promovidas em relação à proposta original — e por quê

O Notion subestimou duas categorias inteiras de coisas que este documento eleva:

1. **Clima (`clima_precipitacao_inmet`)** — não existia como linha na tabela de 75 variáveis.
   Promovida a **requisito de onda 1** (seção 3.1): sem ela, a afirmação central do projeto ("a
   vegetação caiu X% no entorno do data center") não é defensável.
2. **Grupo de controle pareado** — não existia em nenhum dos dois documentos do Notion. Registrado
   aqui como **requisito de desenho** (não variável), apontando para SV-29/SV-30, que já o
   implementam dentro deste próprio repositório (seção 3.2).
3. **Overlay de área protegida (`amb_area_vegetacao_perdida_area_protegida`)** — o Notion listava só
   "proximidade de área protegida" (uma distância estática, papel D). Este documento acrescenta a
   variável derivada de impacto real: área de vegetação perdida **dentro** de UC/TI/APP — o "salto
   de valor de menor custo" citado na pesquisa do Fabio ("4 ha de vegetação perdida" → "4 ha, sendo
   1,2 ha em área sensível"), papel B, onda 1.
4. **Malhas territoriais do IBGE (`ibge_malhas_territoriais`)** — não era uma linha própria no
   Notion (aparecia implícito em "Município"/"Estado"). Elevada a item explícito de onda 1 porque é
   o pré-requisito técnico sem o qual nenhuma variável municipal ou de setor censitário deste
   documento pode ser agregada a uma AOI.
5. **Setor censitário do IBGE (`ibge_setor_censitario_socioeconomico`)** — não estava no Notion (que
   só propunha granularidade municipal para socioeconômico). Adicionada como a **única** alternativa
   de granularidade socioeconômica com valor real de impacto (seção 2), com o custo de
   compatibilização entre censos declarado.
6. **MapBiomas Alerta e MapBiomas Fogo como confundidores** — a pesquisa do Fabio já os cita como
   fontes na arquitetura recomendada, mas sem atribuir papel analítico. Aqui entram explicitamente
   como papel **C** (onda 3): descontam desmatamento/queimada regional não relacionado ao
   empreendimento antes de qualquer leitura de "perda de vegetação" ser atribuída ao data center.
7. **Declividade (SRTM/Copernicus DEM, `topografia_declividade_dem`)** — citada na arquitetura do
   Fabio, mas sem linha própria na tabela de variáveis. Adicionada como covariável estática de onda 2.
8. **As 10 features que faltavam para o papel (A) bater com SV-08** — a lista original do Notion
   ("Entradas do Random Forest": B2, B3, B4, B8, B11, B12, NDVI, NDWI, NDBI) usa nomenclatura de
   banda do Sentinel-2 puro. A implementação real em SV-08 roda sobre **duas eras de sensor**
   (Landsat + Sentinel-2) com **nomes de banda harmonizados** (`blue, green, red, nir, swir1,
   swir2`) e **13 features**, não 9 — inclui também EVI, MNDWI, BSI e NDMI, e não inclui red-edge
   (que o Landsat não tem). O contrato reflete exatamente essas 13, nem mais nem menos — é o teste
   automatizado mais importante deste documento (seção 7).

---

## 7. Seção de fronteira — quem entrega o quê

### O que a frente de ML entrega (este repositório)

- `data/processed/classificado/{site_id}/{ano}.tif` — raster de cobertura do solo, uint8, 5 classes
- `outputs/indicadores/area_por_classe.csv` — área por classe/ano/sensor/AOI (schema ADR-002)
- `outputs/indicadores/classes_{site_id}_{ano}.geojson` — polígonos vetorizados por classe
- `outputs/perfil_aoi_ano.csv` + `outputs/assinatura_agregada.csv` — perfil pré/durante/pós e curva
  agregada por tempo relativo ao evento, com contraste contra controle pareado (SV-30)
- `reports/pareamento_controle.csv` + `config/sites_controle.geojson` — grupo de controle pareado e
  seu relatório de qualidade (SV-29)
- As 13 features de entrada do modelo (papel A) e suas fórmulas, documentadas em SV-08

Tudo isso é o que o contrato marca com `usado_neste_repo: true` — **36 das 93 entradas**. O restante
(57 entradas) é o que esta frente **não vai entregar**.

### O que a frente de Engenharia precisa entregar para os KPIs propostos existirem

As fontes das ondas 1–4 do contrato (seção 4): INMET, malhas e setores censitários do IBGE, polígono
de áreas protegidas, OSM/Overpass, SRTM/Copernicus DEM, ANA HidroWeb, MapBiomas Alerta/Fogo. Este
documento não decide *como* — API direta, STAC, download em lote — isso é escolha da Engenharia
(seção 8).

### O que fica sem dono se ninguém pegar

- **Clima (onda 1)** — sem ele, toda afirmação de impacto ambiental do projeto fica vulnerável à
  objeção "e o clima daquele ano?". Fica sem dono se a Engenharia não priorizar.
- **Setor censitário (onda 4)** — sem ele, todo dado socioeconômico do projeto permanece contexto
  (papel D), nunca impacto. Isso não impede o projeto (o núcleo ambiental não depende disso), mas
  limita qualquer afirmação socioeconômica que a apresentação final queira fazer.
- Os 12 itens marcados `fora_de_escopo` (seção 5) ficam sem dono por decisão — não porque ninguém
  pensou neles, mas porque não são publicamente obteníveis em lote.

---

## 8. Sobre a arquitetura proposta pelo Fabio (STAC, S3 Bronze/Silver/Gold, Glue, Spark)

A pesquisa do Fabio propõe uma arquitetura de produto bem mais ampla que o que este repositório
constrói: aquisição via STAC API, datalake em S3 com camadas Bronze/Silver/Gold, catalogação/
processamento via AWS Glue, processamento geoespacial distribuído via Spark, e um "Data Acquisition
Layer" com metadados de proveniência por fonte.

**Este documento registra essa recomendação como recebida e endossada para o produto** — é uma
arquitetura razoável para quando o projeto precisar processar dezenas de fontes e escalar além de
alguns sites. Mas **não é pré-requisito de nada que este repositório entrega em 14/09/2026**. O
pipeline atual roda localmente, usando Google Earth Engine para aquisição/processamento de imagem, e
está funcionando (ingestão, harmonização multi-sensor, classificação, output de indicadores — tudo
sem S3, sem Glue, sem Spark). Este documento não cria dependência de infraestrutura que não existe, e
não decide se/quando a Engenharia deveria migrar para a arquitetura do Fabio — isso é escolha e
cronograma da Engenharia, não desta frente.

---

## 9. Contrato legível por máquina

`docs/contrato-dados-externos.yml` — uma entrada por variável, 93 entradas (75 da tabela do Notion +
18 promovidas/adicionadas por este documento, listadas na seção 6). Carrega com `yaml.safe_load` e
tem os 15 campos obrigatórios preenchidos em 100% das entradas (verificado — ver comandos abaixo).

Campos: `id`, `nome`, `dimensao`, `papel` (A|B|C|D), `unidade`, `granularidade_espacial`
(`pixel|aoi|setor_censitario|municipio|estacao`), `granularidade_temporal`
(`anual|mensal|estatico`), `fonte`, `mecanismo_acesso`, `licenca`, `onda`
(`1|2|3|4|fora_de_escopo|null`), `esforco` (`baixo|medio|alto`), `bloqueadores`, `parecer`,
`usado_neste_repo` (bool), `origem` (`notion_propostas_variaveis|adicionado_sv28`).

O campo `usado_neste_repo` é o que impede o mal-entendido mais provável deste handoff: deixa
explícito, item a item, **o que esta frente já entrega** (bandas, índices, classes, áreas, deltas) e
o que ela **não vai entregar** (todo o resto — 57 das 93 entradas).

Verificação executada (2026-08-31), com `.venv\Scripts\python.exe`:

```
yaml.safe_load(...) → dict com chave 'variaveis' (93 entradas), 0 campos obrigatórios vazios
0 ids duplicados
papel: {A: 13, B: 11, C: 6, D: 63}
papel A == exatamente as 13 features de SV-08 (blue, green, red, nir, swir1, swir2,
  ndvi, evi, ndwi, mndwi, ndbi, bsi, ndmi) — confirmado por comparação de conjuntos
onda == 1 contém: clima_precipitacao_inmet (INMET), ibge_malhas_territoriais (IBGE),
  amb_proximidade_area_protegida + amb_area_vegetacao_perdida_area_protegida (áreas protegidas)
entradas no YAML (93) ≥ linhas da tabela do Notion (75)
```

---

## Pendente de confirmação

**O teste de leitura pedido pela tarefa original — "alguém do time que não trabalha em ML consegue,
lendo só este documento, dizer quais 3 fontes começar a integrar primeiro e por quê" — ainda não foi
feito com uma pessoa real do time.** Quem escreveu este documento não tem acesso a uma pessoa real
do time nesta sessão, e o próprio viés de quem escreveu não serve como substituto desse teste.

O que foi feito no lugar: revisão crítica do próprio documento, como se fosse a primeira leitura de
alguém de fora do ML — a seção 4 (ondas) foi escrita para responder sozinha "por onde eu começo",
terminando com uma frase explícita nomeando as 3 fontes da onda 1 em ordem, sem exigir que o leitor
monte essa lista a partir da tabela.

**Antes de este documento circular oficialmente no time**, peça para alguém que não é de ML ler só
este arquivo (sem abrir o YAML) e responder, sem ajuda: quais 3 fontes começar a integrar primeiro e
por quê. Se a resposta não sair direto da seção 4, a seção precisa ser reescrita — não o teste.
