# ADR-005 — Expansão de sites: consolidação, dedup por AOI e tiering

- **Status:** Proposto — **aguardando aprovação humana do tier 1** (bloqueante, ver seção final)
- **Data:** 2026-08-31 (rodada 1) · **atualizado em 2026-09-01** (rodada 2 — pesquisa dirigida de ano)
- **Decisor:** usuário (owner da frente de Modelagem); levantamento e proposta produzidos em SV-24
- **Tarefa:** `docs/tarefas/SV-24-consolidacao-lista-sites.md` · **Desbloqueia:** SV-25

## Contexto

O projeto rodava com 3 AOIs (`ascenty-vinhedo`, `odata-hortolandia`, `scala-tambore`, ver ADR-001). O
time levantou no Notion duas listas de candidatos ("20 Data Centers De 2016 a 2026" e "Lista dos 30
data centers..."), que se sobrepõem e listam **prédios, não áreas de estudo** — a unidade deste
repositório é a AOI, um buffer de 5 km (ADR-001). Esta tarefa consolida as duas listas numa tabela
única, deduplicada por AOI, com elegibilidade avaliada por critério explícito e separada em tier 1
(pipeline completo + rotulagem manual) e tier 2 (pipeline sem rotulagem, generalização fora da
amostra).

**Rodada 2 (2026-09-01):** a rodada 1 (abaixo, texto original preservado) chegou a 11 AOIs elegíveis,
**10 delas em São Paulo e todas de bioma Mata Atlântica** — não atingindo o critério de aceite de ≥ 3
biomas distintos no tier 1. O motivo era estrutural: a Lista de 30, pensada para trazer diversidade
regional, não tem coluna de ano, e sem ano nenhuma entrada exclusiva dela passa em E1. O usuário pediu
explicitamente uma rodada de pesquisa dirigida (`WebSearch`/`WebFetch`) para tentar recuperar o ano de
construção/operação dos candidatos fora de SP. Essa rodada é documentada na seção **"Rodada 2 —
pesquisa dirigida de ano"** abaixo, e **substitui** a composição de tier 1/tier 2 e as conclusões sobre
diversidade de bioma da rodada 1 (as seções "Resultado da elegibilidade", "Regra de seleção do tier 1"
e "Composição proposta do tier 1" da rodada 1 ficam como registro histórico, mas a decisão vigente é a
da rodada 2).

## O que muda e o que não muda

**Não muda (fechado, não reaberto por esta tarefa):** as 5 classes de cobertura do solo, a fonte de
labels (MapBiomas + WorldCover, ADR-004), a harmonização multissensor (ADR-003), a janela temporal
2013–2025 (ADR-001), e o buffer de 5 km por AOI (ADR-001). Os `aoi_id` das 3 AOIs já ativas não foram
renomeados.

**Muda:** o número de AOIs candidatas do projeto passa de 3 para **38 linhas rastreáveis (16 elegíveis,
22 rejeitadas com motivo registrado** — nenhuma linha das listas originais, nem dos achados da rodada
2, foi descartada silenciosamente). Os 35→38 e 11→16 refletem a rodada 2: 3 AOIs novas adicionadas
(`ascenty-maracanau`, `hostdime-joao-pessoa`, `elea-poa2`, sendo a última reprovada) e 3 reclassificadas
de reprovada para elegível (`angonap-fortaleza`, `everest-goiania`, `clickip-manaus`) depois de pesquisa
dirigida encontrar ano de construção/operação com fonte pública. **O tier 1 vigente (rodada 2) tem 13
AOIs cobrindo 4 biomas distintos**, e o tier 2 tem 3 AOIs — ver seção "Rodada 2" abaixo.

## Fontes

- `data/externo/sites_notion_lista20.csv` — extração fiel da página Notion "20 Data Centers De 2016 a
  2026" (id `3cecefef-d904-80ef-8a74-f37e04084d27`), buscada via MCP em 2026-08-31.
- `data/externo/sites_notion_lista30.csv` — extração fiel da página "Lista dos 30 data centers..."
  (id `0a8cefef-d904-82ad-ade3-01ccab653ab6`), mesma data.
- Página "Dados - informações de data centers" (id `8e4cefef-d904-82ca-8419-01fcf18168bb`) — **não**
  é uma terceira lista de candidatos. Usada na rodada 1 só como referência de coordenadas/anos de alta
  confiança para prédios que já estavam numa das duas listas acima, citada em `observacao` e em
  `predios_json` (fonte `pagina_referencia_notion`). Na rodada 1, facilities que apareciam **só** nessa
  página (Ascenty Fortaleza 1, NextStream Tamboré/CIC, Elea POA2/RJO1, HostDime João Pessoa,
  Marktec/Softdados Salvador) **não** entraram em `sites_candidatos.csv` por estarem fora do escopo
  original de SV-24. **Na rodada 2, o usuário autorizou explicitamente reconsiderar 3 dessas 4
  facilities** (Ascenty Fortaleza 1, Elea POA2, HostDime João Pessoa — NextStream Tamboré foi pulada
  por indicação do próprio usuário) — ver seção "Rodada 2" abaixo.
- **Pesquisa web dirigida (rodada 2, 2026-09-01)** — `WebSearch`/`WebFetch` sobre 14 candidatos da
  Lista de 30 fora de SP mais os 3 casos acima da página de referência, buscando ano de
  construção/operação em imprensa especializada, imprensa de negócios local e releases oficiais.
  Todas as URLs exatas usadas como fonte de cada ano estão citadas em `fontes_url` e `observacao` de
  cada linha correspondente em `config/sites_candidatos.csv`, e resumidas na tabela da seção "Rodada 2"
  abaixo.

## Deduplicação (dois níveis, nesta ordem)

1. **Nível prédio** — mesma instalação com o mesmo nome nas duas listas vira um único registro de
   prédio. 7 ocorrências: Equinix SP5x, Ascenty Vinhedo 1, Ascenty Vinhedo 2, Equinix RJ3, RT-One
   Uberlândia, Scala AI City, Data Center ByteDance/Pecém.
2. **Nível AOI** — prédios do mesmo `(operador, município)` viram uma AOI (proxy provisório, sem
   coordenada real ainda — SV-25 confirma ou desfaz). Município diferente **nunca** funde
   automaticamente, mesmo vizinho (`ascenty-spo06` e `equinix-rj3` ficaram marcados
   `revisar_manualmente` por isso). 6 fusões de nível AOI: `ascenty-vinhedo` (2 prédios),
   `ascenty-hortolandia` (5-6 prédios), `ascenty-sumare` (2), `ascenty-osasco` (2),
   `equinix-santana-parnaiba` (2), e entre as rejeitadas, `equinix-rio-de-janeiro` (RJ1+RJ2).

   `predios_json` preserva **todos** os prédios de cada AOI com seus anos originais (string de
   intervalo preservada, ex. `"2018-2019"`) — nenhuma informação de ano foi perdida na fusão. Os
   campos agregados da AOI (`ano_construcao_min/max`, `ano_operacao_min/max`) usam a convenção "use o
   primeiro ano de um intervalo" só para o cálculo dos períodos, nunca sobrescrevendo `predios_json`.

## Critério de elegibilidade (E1–E4), aplicado literalmente

- **E1 — Evento datável na janela:** pelo menos um prédio com início de construção entre 2013 e 2024,
  **e** os períodos pré/durante/pós resultantes precisam ser intervalos não vazios dentro de
  2013–2025. Na prática isso significa: se o **ano de operação mais tardio usado no cálculo** for
  2025 ou depois, `periodo_pos` fica vazio (`[ano_operação+1, 2025]` com início > fim) — mesmo
  princípio do exemplo do próprio enunciado ("um evento em 2025 não tem pós"), estendido de
  construção para operação porque é a operação que ancora o início do "pós".
- **E2 — Pegada visível:** construção nova em terreno aberto (greenfield/brownfield), reprova
  colocation em prédio urbano existente.
- **E3 — Coordenada obtível:** existe fonte plausível de georreferenciamento (aplicado com bom senso:
  operador comercial conhecido com página de localização própria conta como plausível mesmo sem a URL
  específica em mãos nesta etapa — buscar a URL exata é SV-25).
- **E4 — Sem sobreposição de AOI:** não é o mesmo buffer de 5 km de uma AOI já aceita. **Interpretado
  como dedup de segurança** (pega duplicata que escapou do passo de dedup por nome/operador), não
  como proibição geral de dois operadores diferentes coexistirem numa mesma região — sem coordenada
  real ainda, seria fácil demais reprovar por engano.

**Na rodada 1: 23 de 24 reprovações foram por E1** (majoritariamente "sem ano em nenhuma fonte
consultada" — a Lista de 30 foi desenhada sem coluna de ano, então nenhuma entrada exclusiva dela
consegue passar em E1 sem uma pesquisa nova, que era fora de escopo da rodada 1). **1 reprovação foi
por E2**: Surfix Data Center (Recife) — colocation em dois andares de um edifício em Boa Viagem, o
próprio exemplo negativo citado no enunciado da tarefa.

**Na rodada 2, com a pesquisa dirigida de ano (ver seção própria abaixo): 20 de 22 reprovações são por
E1, 2 por E2** (Surfix Recife, já citada, e a nova `elea-poa2`, aquisição de prédio já existente da TIM
— não construção nova). Das reprovações por E1 na rodada 2, a maioria agora tem uma **data real
documentada** (não mais "sem dado"): o problema passou a ser, na maior parte dos casos, que a data real
cai fora da janela 2013-2024 ou gera `periodo_pos` vazio — não mais ausência de informação.

## Resultado da elegibilidade — achado central da RODADA 1 (histórico, ver Rodada 2 para o estado vigente)

**35 AOIs candidatas → 11 elegíveis, 24 reprovadas.** Isso é bem abaixo do que os alvos do enunciado
(tier 1 ~12, tier 2 13–18) presumiam, e por um motivo estrutural, não um erro de critério: **a Lista
de 30 — a fonte pensada para trazer diversidade regional (Nordeste, Norte, Centro-Oeste, Sul) — não
tem coluna de ano**, e sem ano nenhuma linha exclusiva dela passa em E1. Das 11 AOIs elegíveis, **10
são em São Paulo e 1 no Rio Grande do Sul** (fronteira de bioma incerta, ver abaixo) — ou seja,
**biomas distintos no conjunto elegível: 1 (Mata Atlântica), possivelmente 2 se a fronteira Mata
Atlântica/Pampa favorecer Porto Alegre como Pampa.** Isso **não atinge o critério de aceite de ≥ 3
biomas distintos no tier 1** definido no enunciado. Registrado aqui como achado a reportar, **não
forçado** — nenhum ano foi inventado para inflar o número.

Com 11 AOIs elegíveis, colocar todas em tier 1 (dentro do intervalo aceito de 10–14) não deixa nada
para tier 2: **tier 2 = 0 AOIs**, versus o alvo de 13–18. A alternativa (reservar 1–2 AOIs elegíveis
para tier 2) não resolveria a diversidade de bioma (todas as candidatas são do mesmo cluster
SP/Mata Atlântica) nem daria a tier 2 uma amostra minimamente útil para teste de generalização — por
isso a proposta deste ADR é **tier 1 = as 11 AOIs elegíveis, tier 2 = vazio**, com a lacuna reportada
explicitamente em vez de preenchida artificialmente.

## Regra de seleção do tier 1 aplicada — RODADA 1 (histórico, substituída pela Rodada 2)

Ordem do enunciado: (a) biomas distintos, (b) as duas eras de sensor com evento de construção,
(c) coordenada de fonte primária, (d) pegada maior. Como (a) está esgotado no conjunto elegível
(item acima), o critério decisivo foi (b): **`ascenty-hortolandia` (construção 2018) e
`ascenty-sumare` (construção 2017) são as duas únicas AOIs elegíveis com evento de construção na era
Landsat (pré-2019)** — ambas mantidas em tier 1, satisfazendo o critério de aceite "≥ 2 AOIs tier 1
com obra antes de 2019". As demais 6 novas AOIs (mais as 3 já ativas) entraram em tier 1 porque o
total (11) já está dentro do intervalo aceito (10–14) e nenhuma delas é claramente mais fraca que as
outras a ponto de justificar reservá-la para tier 2 sem propósito real.

## Composição proposta do tier 1 — RODADA 1 (11 AOIs, histórico, substituída pela Rodada 2)

| aoi_id | município/UF | bioma estimado | construção (min) | era de sensor | status |
|---|---|---|---|---|---|
| `ascenty-vinhedo` | Vinhedo/SP | Mata Atlântica | 2019 | Sentinel-2 | já ativo |
| `odata-hortolandia` | Hortolândia/SP | Mata Atlântica | — (não documentado, ADR-001) | — | já ativo |
| `scala-tambore` | Barueri/SP | Mata Atlântica | 2021 | Sentinel-2 | já ativo |
| `ascenty-hortolandia` | Hortolândia/SP | Mata Atlântica | **2018** | **Landsat** | novo |
| `ascenty-sumare` | Sumaré/SP | Mata Atlântica | **2017** | **Landsat** | novo |
| `ascenty-paulinia` | Paulínia/SP | Mata Atlântica | 2019 | Sentinel-2 | novo |
| `ascenty-jundiai` | Jundiaí/SP | Mata Atlântica | 2019 | Sentinel-2 | novo |
| `ascenty-osasco` | Osasco/SP | Mata Atlântica | 2020 | Sentinel-2 | novo |
| `equinix-santana-parnaiba` | Santana de Parnaíba/SP | Mata Atlântica | 2020 | Sentinel-2 | novo |
| `scala-sgigsm01` | São João de Meriti/RJ | Mata Atlântica | 2022 | Sentinel-2 | novo |
| `scala-spoapa01` | Porto Alegre/RS | Mata Atlântica (fronteira c/ Pampa, não confirmado) | 2023 | Sentinel-2 | novo |

Tier 2 na rodada 1: **vazio** (ver achado central acima). **Esta composição foi substituída — ver a
seção "Rodada 2" logo abaixo para a proposta vigente.**

## Rodada 2 — pesquisa dirigida de ano de construção/operação (2026-09-01)

### Motivação e pedido do usuário

O usuário revisou a rodada 1 e pediu explicitamente: *"conseguimos buscar candidatos para termos 20
com mais biomas?"* — ou seja, uma rodada de pesquisa na web (não mais só nas duas listas do Notion)
para tentar recuperar diversidade de bioma antes de fechar o tier 1. O pedido listou uma ordem de
prioridade (Cerrado, Caatinga/Nordeste, Amazônia, Pampa/Sul) e nomeou candidatos específicos da Lista
de 30, mais 4 facilities citadas só na página de referência do Notion (fora do escopo original de
SV-24) que a rodada 1 já havia sinalizado como fortes candidatos de diversidade regional.

### Metodologia

Para cada candidato, buscou-se (`WebSearch`/`WebFetch`) o ano de início de construção e/ou o ano de
operação em imprensa especializada (DataCenterDynamics, TeleTime, IT Forum, TIInside), imprensa de
negócios local, releases de prefeitura/governo, ou página do próprio operador — nesta ordem de
preferência quando havia escolha. **Nenhum ano foi inventado**: candidato sem fonte pública verificável
continua reprovado por E1, como já era a regra da rodada 1. A página de referência do Notion ("Dados -
informações de data centers", id `8e4cefef-d904-82ca-8419-01fcf18168bb`) foi buscada novamente (via
`notion-fetch`) porque já continha, fora das duas listas oficiais, coordenadas e anos de alta confiança
para 4 facilities citadas no achado 2 da rodada 1 (Ascenty Fortaleza 1, Elea POA2, HostDime João
Pessoa) — NextStream Tamboré foi explicitamente pulada por não ajudar diversidade de bioma (SP,
já bem representado).

### Candidatos pesquisados e resultado

**14 candidatos pesquisados** (11 da Lista de 30 fora de SP + 3 da página de referência):

| candidato | UF | resultado | ano encontrado | fonte |
|---|---|---|---|---|
| AngoNAP Fortaleza | CE | **ganhou ano → ELEGÍVEL** | constr. 2017, op. 2019 | [teletime.com.br](https://teletime.com.br/11/07/2017/angola-cables-comeca-construir-data-center-em-fortaleza/), [DCD](https://www.datacenterdynamics.com/br/opini%C3%B5es/angola-cables-inaugura-data-center-angonap-fortaleza/) |
| Ascenty Fortaleza 1 (Maracanaú) | CE | **ganhou ano → ELEGÍVEL** (nova AOI `ascenty-maracanau`) | constr. 2014, op. 2015 | [DCD](https://www.datacenterdynamics.com/br/opini%C3%B5es/ascenty-inaugura-data-center-de-r-120-milh%C3%B5es-no-nordeste/), página de referência Notion |
| Everest Digital (Goiânia) | GO | **ganhou ano → ELEGÍVEL** | constr. 2021, op. 2023 | [arandanet.com.br](https://www.arandanet.com.br/revista/rti/noticia/8167-Everest-Digital,-o-primeiro-data-center-de-servicos-gerenciados-Tier-III-do-Centro-Oeste.html), [empreenderemgoias.com.br](https://empreenderemgoias.com.br/2023/05/02/grupo-soluti-inicia-operacoes-da-everest-digital/) |
| HostDime João Pessoa | PB | **ganhou ano → ELEGÍVEL** (nova AOI `hostdime-joao-pessoa`, tier 2) | constr./op. 2017 | [DCD](https://www.datacenterdynamics.com/br/opini%C3%B5es/hostdime-instala-data-center-tier-iii-em-jo%C3%A3o-pessoa/), página de referência Notion (PeeringDB) |
| ClickIP Datacenters (Manaus) | AM | **ganhou ano → ELEGÍVEL** (ressalva de pegada, ver observação) | constr. 2023, op. 2024 | [telesintese.com.br](https://telesintese.com.br/grupo-clickip-inaugura-maior-data-center-da-regiao-norte/) |
| Elea BSB2 (Brasília) | DF | continua reprovado (E1) | constr. 2004 (já conhecido) | confirmado sem expansão datável nova |
| Scala Fortaleza Campus | CE | continua reprovado (E1) | constr. 2024, mas op. ~2025 → `periodo_pos` vazio | [itforum.com.br](https://itforum.com.br/noticias/scala-data-centers-obra-1-bi-fortaleza/) |
| Data Center ByteDance/Pecém | CE | continua reprovado (E1) — data real é pior que a suposição da rodada 1 | constr. jan/2026, op. prevista 3T/2027 | [bpmoney.com.br](https://bpmoney.com.br/inovacao/tecnologia/tiktok-data-center-ceara-50-bilhoes/) |
| Atlantic Data Center Recife 1 | PE | continua reprovado (E1) — fora da janela por 1 ano | constr. jan/2025 | [revistane.com.br](https://revistane.com.br/2025/01/16/um-telecom-inicia-a-construcao-do-recife1-primeiro-data-center-da-atlantic-data-centers-em-pernambuco/) |
| Hostzone Data Center (Campina Grande) | PB | continua reprovado (E1) | nenhum ano encontrado | — |
| Data Center PRODEB (Salvador) | BA | continua reprovado (E1) | nenhum ano de construção encontrado (só a fundação da empresa em 1973) | — |
| Cirion CUR1 (Curitiba) | PR | continua reprovado (E1) | facility legada (ex-Level3), rebatizada em 2022 (não é construção nova) | — |
| Elea CTA1 (Curitiba) | PR | continua reprovado (E1) | adquirida da Oi em 2021 (não é construção nova) | — |
| Tecto TPOA1 (Porto Alegre) | RS | continua reprovado (E1) | obra ainda não iniciada; retrofit de galpão, não greenfield | [tecto.com](https://tecto.com/en/news-and-insights/tecto-announces-r200-million-investment-in-a-new-data-center-in-porto-alegre-connected-to-v-tals-submarine-cable/) |
| Scala AI City (Eldorado do Sul) | RS | continua reprovado (E1), confirmado | obra prevista só para 2027 | [guaiba.online](https://www.guaiba.online/noticia/vice-presidente-da-scala-diz-que-ai-city-de-eldorado-do-sul-deve-iniciar-obras-em-2027) |
| Elea POA2 (Porto Alegre) | RS | **nova linha, reprovado por E2** (não E1) | constr. 2022*, op. 2023 | [DCD](https://www.datacenterdynamics.com/en/news/piemontes-elea-buys-tim-data-center-in-porto-alegre-brazil/) |

**Resumo:** 15 candidatos pesquisados a fundo (a lista acima) + Elea POA2 conferido por completude
(citado no pedido do usuário, mas nunca esteve na Lista de 30) = **16 buscas de web research**. **5
ganharam ano confirmado com fonte e se tornaram elegíveis** (AngoNAP Fortaleza, Ascenty Fortaleza 1/
`ascenty-maracanau`, Everest Digital/Goiânia, HostDime João Pessoa, ClickIP Manaus). **9 continuam
reprovados por E1** — mas agora com data real documentada em 6 deles (Scala Fortaleza, ByteDance/Pecém,
Atlantic Recife, Cirion, Elea CTA1, Scala AI City), não mais "sem dado". **2 seguem sem nenhum ano
encontrado em fonte pública** (Hostzone Campina Grande, PRODEB Salvador) — reprovação inalterada. **1
nova linha reprovada por E2** (Elea POA2 — aquisição de prédio de telecom já existente, não construção
nova).

Duas correções importantes ao que o pedido do usuário presumia: **`bytedance-pecem` NÃO estava
elegível na rodada 1** (o CSV já trazia `elegivel=False, criterio_reprovacao=E1`) e a pesquisa da
rodada 2 **piora** o quadro, não melhora — a obra só começou em janeiro/2026, mais tarde que a hipótese
de 2024/2025 registrada no achado 3 da rodada 1. **`scala-ai-city` também NÃO estava elegível** e segue
reprovada com folga (obra prevista só para 2027).

### Reavaliação de elegibilidade dos 5 novos casos (E1–E4)

- **`angonap-fortaleza`** (Caatinga, CE): E1 ok (construção 2017, era Landsat); E2 ok (obra nova em
  terreno aberto na Praia do Futuro, 9.000 m²/0,9 ha — mesma ordem de grandeza de AOIs já aceitas);
  E3 ok (endereço documentado em múltiplas fontes de imprensa/prefeitura); E4 ok (nenhuma AOI elegível
  próxima nesta rodada).
- **`ascenty-maracanau`** (Caatinga, CE, novo `aoi_id`): E1 ok (construção 2014, era Landsat, o evento
  mais antigo do conjunto elegível fora de SP); E2 ok (9.000 m²/0,9 ha, fonte primária do operador);
  E3 forte (coordenada de fonte primária já citada na página de referência: -3.830803,-38.611253,
  não populada em `lat`/`lon` — fica pendente para SV-25 por regra de escopo); E4 ok, mas
  `revisar_manualmente`: município distinto de `angonap-fortaleza` (Maracanaú vs. Fortaleza), sem
  fusão automática, mas ambos em CE — SV-25 deve confirmar que ficam a mais de 5 km uma da outra.
- **`everest-goiania`** (Cerrado, GO): E1 ok (construção 2021, operação 2023); E2 ok (prédio-sede novo
  com data center integrado, LEED Gold, 4.500 m²/0,45 ha); E3 ok (imprensa de negócios local + site
  institucional); E4 ok (único candidato em Goiânia/GO).
- **`hostdime-joao-pessoa`** (Mata Atlântica, PB, novo `aoi_id`): E1 ok (construção/operação 2017,
  mesma convenção de ano único já usada em outras linhas do arquivo quando só uma data é documentada);
  E2 ok (prédio purpose-built de 1.858 m²); E3 forte (coordenada de fonte primária via PeeringDB, já
  citada na página de referência); E4 ok. Não acrescenta bioma novo (Mata Atlântica já é o bioma
  dominante do conjunto) — por isso vai para **tier 2**, não tier 1 (ver regra de seleção abaixo).
- **`clickip-manaus`** (Amazônia, AM): E1 ok (construção 2023, operação 2024, `periodo_pos` =
  2025-2025, um único ano — o mínimo não-vazio possível); E2 **passa no teste literal do ADR-005**
  (construção nova em terreno aberto, não colocation), **mas com ressalva registrada para revisão
  humana**: pegada de apenas 1.200 m² (0,12 ha) de terreno / 685 m² construídos — bem abaixo da ordem
  de grandeza "≥ 1 ha" citada no enunciado original de SV-24, e a menor pegada de todo o conjunto
  elegível (a próxima menor é `scala-spoapa01`, 4.070 m²). Como é o **único** candidato de Região
  Norte/bioma Amazônia em qualquer uma das duas listas, a decisão de mantê-lo elegível apesar da
  ressalva é registrada aqui explicitamente para o usuário decidir na aprovação do tier — não foi uma
  reprovação silenciosa nem uma inclusão forçada sem aviso. E3/E4 ok.

### Regra de seleção do tier 1 aplicada — RODADA 2 (vigente)

Mesma ordem do enunciado: (a) biomas distintos, (b) as duas eras de sensor com evento de construção,
(c) coordenada de fonte primária, (d) pegada maior. Com os 5 novos elegíveis, o critério (a) deixa de
estar esgotado: **4 biomas distintos passam a ter pelo menos 1 AOI elegível** (Mata Atlântica, Caatinga,
Cerrado, Amazônia) — os 4 representantes não-Mata-Atlântica (`angonap-fortaleza`, `ascenty-maracanau`,
`everest-goiania`, `clickip-manaus`) são **obrigatórios em tier 1** por definição do critério (a).

Isso deixa 16 AOIs elegíveis para um tier 1 com alvo de ~12 (intervalo aceito 10–14). Para caber, **2
AOIs foram remanejadas de tier 1 para tier 2** — exatamente a opção (c) que a rodada 1 já havia
cogitado para o usuário no fechamento do ADR: `ascenty-paulinia` e `ascenty-jundiai`, as duas AOIs mais
redundantes do conjunto (mesmo operador, mesmo bioma, mesma era de sensor — Sentinel-2 2019 — e mesmo
eixo industrial de `ascenty-vinhedo`, que já cobre esse caso em tier 1). `hostdime-joao-pessoa` entra
direto em tier 2 (não em tier 1) pelo mesmo motivo: não acrescenta bioma novo (Mata Atlântica) nem era
de sensor nova (Landsat já coberto por 4 outras AOIs de tier 1, 2 delas agora fora de SP). O resultado
é **tier 1 com 13 AOIs** (dentro do intervalo 10–14) e **tier 2 com 3 AOIs**.

### Composição vigente do tier 1 (13 AOIs — aguardando aprovação)

| aoi_id | município/UF | bioma estimado | construção (min) | era de sensor | status |
|---|---|---|---|---|---|
| `ascenty-vinhedo` | Vinhedo/SP | Mata Atlântica | 2019 | Sentinel-2 | já ativo |
| `odata-hortolandia` | Hortolândia/SP | Mata Atlântica | — (não documentado, ADR-001) | — | já ativo |
| `scala-tambore` | Barueri/SP | Mata Atlântica | 2021 | Sentinel-2 | já ativo |
| `ascenty-hortolandia` | Hortolândia/SP | Mata Atlântica | **2018** | **Landsat** | novo (rodada 1) |
| `ascenty-sumare` | Sumaré/SP | Mata Atlântica | **2017** | **Landsat** | novo (rodada 1) |
| `ascenty-osasco` | Osasco/SP | Mata Atlântica | 2020 | Sentinel-2 | novo (rodada 1) |
| `equinix-santana-parnaiba` | Santana de Parnaíba/SP | Mata Atlântica | 2020 | Sentinel-2 | novo (rodada 1) |
| `scala-sgigsm01` | São João de Meriti/RJ | Mata Atlântica | 2022 | Sentinel-2 | novo (rodada 1) |
| `scala-spoapa01` | Porto Alegre/RS | Mata Atlântica (fronteira c/ Pampa, não confirmado) | 2023 | Sentinel-2 | novo (rodada 1) |
| `angonap-fortaleza` | Fortaleza/CE | **Caatinga** | **2017** | **Landsat** | novo (rodada 2) |
| `ascenty-maracanau` | Maracanaú/CE | **Caatinga** | **2014** | **Landsat** | novo (rodada 2) |
| `everest-goiania` | Goiânia/GO | **Cerrado** | 2021 | Sentinel-2 | novo (rodada 2) |
| `clickip-manaus` | Manaus/AM | **Amazônia** | 2023 | Sentinel-2 | novo (rodada 2, ressalva E2 de pegada) |

**Biomas distintos no tier 1: 4** (Mata Atlântica, Caatinga, Cerrado, Amazônia) — atinge com folga o
critério de aceite de ≥ 3. **AOIs de tier 1 com obra antes de 2019: 4** (`ascenty-hortolandia`,
`ascenty-sumare`, `angonap-fortaleza`, `ascenty-maracanau`), acima do mínimo de 2, e agora distribuídas
em **2 UFs diferentes (SP e CE)**, não só SP.

### Composição vigente do tier 2 (3 AOIs)

| aoi_id | município/UF | bioma estimado | construção (min) | era de sensor | motivo de estar em tier 2 |
|---|---|---|---|---|---|
| `ascenty-paulinia` | Paulínia/SP | Mata Atlântica | 2019 | Sentinel-2 | redundante com `ascenty-vinhedo` (rebalanceada da rodada 1) |
| `ascenty-jundiai` | Jundiaí/SP | Mata Atlântica | 2019 | Sentinel-2 | redundante com `ascenty-vinhedo` (rebalanceada da rodada 1) |
| `hostdime-joao-pessoa` | João Pessoa/PB | Mata Atlântica | 2017 | Landsat | novo (rodada 2); não acrescenta bioma/era não cobertos |

Tier 2 fica **abaixo do alvo original de 13–18** do enunciado de SV-24 — isso é reportado como achado,
não forçado: com apenas 16 AOIs elegíveis no total (rodada 1 + rodada 2), não há candidatos suficientes
para um tier 2 maior sem inventar datas ou baixar o rigor de E1–E4. O alvo de 13–18 presumia um universo
de candidatos bem maior do que o que a Lista de 30 + página de referência realmente sustentam com dados
verificáveis.

## Fusões marcadas `provisoria`/`revisar_manualmente`

- **`ascenty-hortolandia` × `odata-hortolandia`** — **o achado mais importante para SV-25.** As
  coordenadas de referência das duas AOIs (ambas de fonte primária/alta confiança, nenhuma delas
  ainda "oficial" via cascata de SV-25) ficam a **~1,7 km uma da outra**, bem dentro do buffer de 5 km
  de qualquer uma das duas. Se confirmado com coordenada real, isso é uma colisão de AOI (E4/V4) que
  precisa de decisão humana explícita: fundir as duas (operadores diferentes, prédios diferentes, mas
  mesmo footprint de imagem) ou manter separadas. **Não resolvido neste ADR** — sinalizado para SV-25.
- **`ascenty-osasco` × `ascenty-spo06` (rejeitada)** — nome sugere mesma série de numeração Ascenty
  ("SP3, SP4, SPO06"), mas município da Lista de 30 ("Grande São Paulo") não é específico o
  suficiente para fundir automaticamente com "Osasco".
- **`equinix-rj3`** — Lista de 20 diz município "São João de Meriti", Lista de 30 diz "Rio de
  Janeiro" para o mesmo prédio. Usado o valor mais específico (Lista de 20); a AOI está reprovada por
  E1 de qualquer forma (periodo_pos vazio), mas a divergência de município fica registrada para
  quando/se for reconsiderada.

## Achados e recomendações

1. ~~A Lista de 30 precisa de uma coluna de ano~~ — **parcialmente resolvido na rodada 2**: pesquisa
   dirigida na web (fora das duas listas do Notion) encontrou ano de construção/operação para 5 das
   entradas exclusivas da Lista de 30 (AngoNAP Fortaleza, Everest Digital, ClickIP Manaus, e por
   extensão as 2 novas linhas trazidas da página de referência). **9 entradas continuam sem passar em
   E1** mesmo após a pesquisa — 6 delas agora com data real documentada fora da janela (Scala
   Fortaleza, ByteDance/Pecém, Atlantic Recife, Cirion, Elea CTA1, Scala AI City) e só 2 ainda
   totalmente sem dado (Hostzone Campina Grande, PRODEB Salvador). Recomenda-se ainda assim adicionar
   a coluna de ano na fonte do Notion, para não depender de pesquisa manual em rodadas futuras.
2. ~~4 facilities da página de referência fora do escopo~~ — **resolvido na rodada 2**: 3 das 4
   (Ascenty Fortaleza 1 → `ascenty-maracanau`, HostDime João Pessoa, Elea POA2) foram pesquisadas e
   incorporadas a `sites_candidatos.csv` (as duas primeiras elegíveis, Elea POA2 reprovada por E2 —
   aquisição de prédio já existente, não construção nova). NextStream Tamboré foi deliberadamente
   pulada por indicação do usuário (não ajuda diversidade de bioma, já é SP).
3. ~~Data Center ByteDance/Pecém~~ — **resolvido, mas na direção oposta à esperada**: a rodada 2
   confirma que a obra só começou em janeiro de 2026 (não 2024/2025 como se esperava), com operação
   prevista só para o 3º trimestre de 2027 — mais distante da janela do repositório do que a rodada 1
   presumia. Não é mais "a reconsideração de maior valor"; a reconsideração de maior valor da rodada 2
   acabou sendo `angonap-fortaleza` e `ascenty-maracanau`.
4. **`scala-campinas-svcpcp01`** (SP) segue sem ano de construção/operação em nenhuma fonte consultada
   (nem na rodada 1 nem numa nova checagem rápida na rodada 2) — não pesquisado a fundo nesta rodada
   por já ser SP/Mata Atlântica (prioridade baixa dado que o objetivo da rodada 2 era diversidade
   regional). Continua como candidata forte para uma rodada futura de coleta de ano.
5. **Novo achado da rodada 2 — ressalva de pegada em `clickip-manaus`:** é o único candidato de
   Amazônia/Região Norte em qualquer uma das listas, mas tem a menor pegada física do conjunto elegível
   (0,12 ha, terreno de 1.200 m²) — abaixo da ordem de grandeza "≥ 1 ha" do enunciado original de
   SV-24. Passa no teste literal de E2 (construção nova, não colocation), mas o usuário deve avaliar
   explicitamente se aceita essa AOI apesar da pegada pequena ao aprovar o tier 1 (ver seção de
   aprovação abaixo).
6. **Novo achado da rodada 2 — padrão "E4 revisar_manualmente" se repete em CE:** `angonap-fortaleza`
   (Fortaleza) e `ascenty-maracanau` (Maracanaú) são municípios distintos na mesma região metropolitana
   do Ceará — sem fusão automática pela regra da tarefa, mas SV-25 deve confirmar com coordenada real
   que os dois buffers de 5 km não se sobrepõem (mesmo padrão do achado já registrado para
   `ascenty-hortolandia`×`odata-hortolandia`, embora aqui a distância aparente muito maior: litoral de
   Fortaleza vs. Maracanaú, ~15-20 km).

## Consequência para o cronograma

Nenhuma. SV-25 (validação de coordenadas em escala) processa as 16 AOIs elegíveis normalmente; o tier 2
reduzido (3 AOIs, abaixo do alvo de 13–18) não bloqueia SV-25 nem SV-26 — só reduz o tamanho do
conjunto de generalização fora da amostra que alimentará o painel de SV-30, o que deve ser registrado
como limitação do TCC (mesmo texto da rodada 1, agora com números atualizados).

## Aprovação — BLOQUEANTE, pendente

**Esta tarefa não aprova o tier 1 por conta própria — nem na rodada 1, nem na rodada 2.** A composição
de 13 AOIs de tier 1 acima (e as 3 de tier 2) precisa de confirmação explícita do usuário antes de
SV-25 começar — é a única aprovação humana desta tarefa, e ela é bloqueante por definição do
enunciado. A rodada 2 recupera diversidade de bioma real (4 biomas, contra 1 da rodada 1) mas introduz
um ponto que pede atenção explícita do usuário na aprovação:

- **(a)** aprovar o tier 1 vigente como proposto (13 AOIs, 4 biomas, tier 2 com 3 AOIs) e seguir para
  SV-25 — inclui aceitar `clickip-manaus` apesar da pegada pequena (achado 5 acima);
- **(b)** aprovar o tier 1 vigente, mas mover `clickip-manaus` para tier 2 (ou reprová-la manualmente)
  se a pegada de 0,12 ha for considerada pequena demais para o estudo — nesse caso o tier 1 fica com
  12 AOIs e 3 biomas (Amazônia sai do tier 1, e a região Norte fica de novo sem nenhuma AOI no estudo,
  já que `clickip-manaus` é o único candidato encontrado nela em qualquer rodada);
- **(c)** pedir uma 3ª rodada de pesquisa dirigida a um subconjunto ainda menor (ex.: só
  `scala-campinas-svcpcp01`, que já tem coordenada e pegada fortes e só falta o ano) antes de fechar
  definitivamente o tier 1/tier 2.

Este ADR fica em status **Proposto** até essa decisão ser registrada.
