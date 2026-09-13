# modelo-impacto — tudo da frente de impacto, numa pasta só

**Aqui não tem nada de classificação de imagem.** O modelo de imagem mora em `src/sentinela/`,
com as pastas de apoio dele (`config/`, `data/`, `models/`, `tests/`) na raiz. Esta pasta é a
outra metade do projeto: o que acontece **depois** que a imagem virou classe — pareamento de
controle, medição de conversão, e o boletim de impacto.

Fundida em **2026-09-13** a partir de `dados-modelo-impacto/` e `modelo-impacto-score/`, que eram
duas pastas com fronteira arbitrária entre si (e que, pior, hospedavam os geradores de notebook do
modelo de **imagem**).

## O que tem dentro

| | o que é |
|---|---|
| `scripts/impacto_dc_01..41_*.py` | a cadeia de impacto, na ordem — coleta, pareamento, medição, robustez |
| `scripts/impacto_dc_comum.py` | a base compartilhada de todos eles (geodésia, caminhos, sites) |
| `scripts/score_*.py` | o boletim por eixo e os selos de evidência — ver **`README-score.md`** |
| `scripts/nb_*.py` | os geradores dos notebooks de impacto (02, 03, 05, 07, 08) |
| `raw/controles-rf/` | as tabelas de resultado que o relatório cita, e as figuras |
| `processed/` | o painel consolidado de indicadores externos |
| `outputs/` | as saídas do boletim (`boletim_por_eixo.csv`, `selos_de_evidencia.csv`, …) |
| `reports/` | o relatório de impacto e as figuras dele |

Os notebooks gerados ficam em `notebooks/`, na raiz, junto com os do modelo de imagem — é onde
quem chega procura.

## Como rodar

Nunca script por script: o runner declara a ordem, o custo e a dependência de rede de cada passo.

```bash
python scripts/reproduzir_impacto.py --listar    # o plano, sem executar
python scripts/reproduzir_impacto.py             # só o que roda offline
```

## De onde veio esta pasta

Começou em 2026-09-03 para **apoiar o modelo de impacto do Guilherme** (dado um data center, como
ficam os indicadores ambientais e socioeconômicos no entorno), e cresceu até cobrir a medição
inteira. **Tem prazo próprio** e não segue o cronograma do classificador — ver `CLAUDE.md` na raiz.

## Objetivo (do briefing do time)

Dado uma latitude/longitude, projetar como ficariam ~6 indicadores no entorno (rodando o cenário
de 2026):

- **Ambientais:** cobertura vegetal, água (pode não existir em todo site), temperatura de
  superfície.
- **Socioeconômicos/demográficos:** aumento de área construída no entorno, aumento do número de
  empregos (a confirmar se é sustentável de medir — ver ressalva abaixo).

Divisão combinada com o time:
- **Guilherme:** terminar de levantar os dados do datacentermap.com para os outros facilities.
- **Gabriel (este apoio):** baixar dados de temperatura, população e número de empregos, para os
  ~20 facilities (10 anos de histórico), com possibilidade de expansão da amostra.

## Antes de baixar qualquer coisa, leia isto

Este repositório já fez um levantamento equivalente para o classificador de imagem (SV-28) e
achou coisas que afetam diretamente este apoio:

1. **População e número de empregos, em nível municipal, não sustentam afirmação de impacto** —
   servem só como contexto/estratificação. Um data center é uma fração ínfima da população/economia
   de um município inteiro; qualquer variação observada tem mais causas concorrentes plausíveis que
   o empreendimento sozinho. Ver `docs/requisitos-dados-externos.md` (seção 2, "parecer honesto de
   granularidade") e `docs/contrato-dados-externos.yml` (`soc_populacao`, `soc_emprego_formal`,
   papel `D`) na raiz deste repo. Se o objetivo é uma afirmação causal ("o data center gerou N
   empregos"), a única granularidade defensável é setor censitário — e isso tem custo alto
   (compatibilizar malha do Censo 2010↔2022). Vale decidir isso **antes** de baixar, não depois.
2. **Temperatura de superfície (LST) não precisa vir de fonte externa** — dá pra extrair da mesma
   imagem de satélite (Landsat banda termal / MODIS), via Google Earth Engine, sem download manual.
   Fora do escopo do classificador principal (quebraria a harmonização de 13 features dele), mas
   não fora do escopo deste apoio.
3. **Grupo de controle / isolamento de causalidade já está desenhado** — ver
   `docs/tarefas/SV-29-grupo-controle-pareado.md`. Ponto de atenção: a distância mínima usada lá é
   **15–40 km** do data center (não 3 km) — perto demais cai dentro do raio de influência do
   próprio empreendimento, é "tratamento disfarçado de controle", o erro mais grave possível nesse
   desenho. O pareamento lá usa cobertura do solo pré-obra como critério de similaridade, não
   população.
4. **Sobre o modelo em si (regressão linear múltipla ou outro):** com N~20 sites, um regressor
   treinado é estatisticamente frágil — ajusta ruído, não sinal, e é a peça mais fácil de derrubar
   numa banca. A decisão equivalente tomada no classificador principal (`ADR` ainda não formalizado
   aqui, mas confirmada com o usuário) foi projeção por **análogo histórico** em vez de regressor
   treinado. Vale considerar o mesmo caminho aqui, a menos que a amostra cresça bem além de 20.

## Estrutura

```
modelo-impacto/
├── raw/          # dados baixados, brutos (gitignored — pesado/específico de fonte)
├── processed/    # dados tratados, prontos para o modelo do Guilherme (gitignored por ora)
├── scripts/      # scripts de download/tratamento (committáveis)
└── README.md     # este arquivo
```

`raw/` fica de fora do git (respostas brutas de API, ~7,5MB, reproduzível rodando os scripts de
novo). `processed/` **é commitado** (~384KB, é o resultado útil — mesma lógica de
`data/manifests/` no repositório principal).

## Lista de trabalho: 19 facilities

16 sites já validados deste repositório (`config/sites.geojson`) + 3 novos, reconciliados a partir
do scraping do Guilherme
(`datacenter-extracao-modelos/data/02_silver/datacentermap_enriquecido.csv`, 21 facilities, 17 já
batiam com os nossos 16 — inclusive confirmando de forma independente o agrupamento de campus com
vários prédios que já tínhamos): **Scala AI City** (Eldorado do Sul/RS), **Pecém Data Center** (São
Gonçalo do Amarante/CE — aparecia duplicado no scraping do Guilherme, vale avisar ele), **RT-One
Uberlândia** (MG, primeira facility em Triângulo Mineiro). Essas 3 não passaram pela validação de
coordenada em 5 camadas que os 16 originais tiveram — ver coluna `origem_lista` nas planilhas.

## Arquivos finais (`processed/`)

| Arquivo | Conteúdo | Cobertura |
|---|---|---|
| `consolidado_painel_anual.csv` | 1 linha por site×ano: temperatura (LST), população, emprego formal, PIB, área por classe do classificador (vegetação/água/construída/solo exposto) | 232 linhas, 19 sites — **os 3 sites novos só têm PIB e área do classificador; temperatura/população/emprego cobrem só os 16 originais** (coletados antes da reconciliação) |
| `consolidado_desemprego.csv` | Taxa de desocupação anual | Só **5 dos 18 municípios** — o IBGE só publica essa taxa em nível municipal pras capitais de estado |
| `consolidado_renda.csv` | Renda média/mediana per capita | 19 sites, só 2022 (Censo, não é anual) |
| `consolidado_escolaridade.csv` | Nível de instrução por faixa etária, formato longo | 19 sites × 2 censos (2010, 2022) — cortes etários diferentes entre os dois, não é 1:1 comparável |
| `consolidado_facilities.csv` | Atributos estáticos por site: bioma/região/tier (nosso) + MW construído/tier projetado/nº prédios (scraping do Guilherme) | 19 sites |
| `consolidado_apoio_impacto.xlsx` | As 5 tabelas acima, uma aba cada | — |

Script que gera tudo isso: `scripts/montar_planilha_consolidada.py` (idempotente, roda de novo se
qualquer fonte for atualizada).

## Ressalva que vale repetir sempre que esses dados forem usados

**Nenhuma das variáveis socioeconômicas/demográficas acima (população, emprego, PIB, renda,
desemprego, escolaridade) tem granularidade suficiente pra sustentar uma afirmação de impacto
causado por um data center específico** — são todas em nível de município, e um empreendimento de
dezenas de hectares é uma fração ínfima da população/economia de um município inteiro. Servem como
**contexto/estratificação dos casos**, não como evidência de efeito. Detalhe completo em
`docs/requisitos-dados-externos.md` (raiz do repositório).

## Rodada 2 (2026-09-05) — painel de cobertura do solo pareado, pelo classificador

Segunda entrega desta pasta, a partir de dois CSVs que o Guilherme mandou (12 data centers e
6 candidatos a controle para cada um). O produto é o **painel final de área por classe, por ano,
para tratamento e controle de cada campus** — `processed/painel_impacto_area_por_classe.csv`.

Três coisas mudaram em relação ao que o briefing pedia, todas medidas antes de decidir:

1. **Os 12 data centers do Guilherme já eram sites validados daqui** — 8 campi, não 12 pontos
   novos (vários são prédios do mesmo campus, a 56–193 m um do outro; num buffer de 5 km, o mesmo
   recorte de terreno). Como já eram validados, o `ano_inicio_obra` de todos já estava pesquisado.
   A amostra foi ampliada para **15 campi** com os sites validados que não estavam na lista dele.
2. **A tabela de candidatos a controle dele não foi usada** — 14 dos 72 pontos caíam a menos de
   10 km de um data center do estudo (buffers sobrepostos), e 3 campi tinham candidatos em outro
   estado, um deles em outro bioma. O diagnóstico numérico, escrito para ele, está em
   `raw/controles-rf/DIAGNOSTICO-TABELA-GUILHERME.md`. Os controles foram regerados com o desenho
   de SV-29 que esta pasta já usava, mas decidindo pela saída do classificador.
3. **A ingestão Landsat foi estendida de 2021 para 2024** para que a janela `obra-3 .. obra+3` de
   cada campus caiba num sensor só e nunca cruze a fronteira 2018/2019 medida por SV-20. Isso
   acrescenta linhas a `outputs/indicadores/area_por_classe.csv` do repositório principal.

Metodologia completa: `raw/controles-rf/METODOLOGIA.md`. Scripts: `scripts/impacto_dc_*.py`,
numerados na ordem de execução.

### O consolidado para o modelo (2026-09-06)

`processed/consolidado_impacto_painel.csv` — **204 linhas × 51 colunas**, uma por (ponto, ano),
juntando cobertura do solo, LST, socioeconômico e os atributos estáticos do data center. Também em
`consolidado_impacto_modelo.xlsx` (abas `painel`, `pareamento`, `dicionario`) e com dicionário de
colunas em `consolidado_impacto_dicionario.csv`.

Para que tratamento e controle fossem comparáveis em **toda** variável, e não só na cobertura do
solo, dois blocos foram recoletados (passos 8 e 9), sempre pelo mesmo código e na mesma execução
para as duas pontas:

- **LST** dos 30 pontos, e a série estendida de 2016 para **2013** — o corte em 2016 era o "10 anos
  de histórico" do briefing anterior, não limite do MODIS. Cobertura: 204/204 nos dois lados.
- **População, emprego e PIB** dos 27 municípios do painel (13 deles são de controle e nunca
  tinham sido coletados), também de 2013. Cobertura idêntica nos dois lados: população 85/102,
  emprego 99/102, PIB 94/102 — as lacunas são de fonte (a estimativa do IBGE não cobre 2013-2015
  nem 2023; CEMPRE vai até 2024; PIB municipal até 2023).

**Duas ressalvas que precisam acompanhar este arquivo:**

1. **`mw_construido_total` só existe para 10 dos 15 campi, e a lacuna tem padrão geográfico:**
   9/9 no Sudeste e 1/1 no Sul, **0 de 5** no Nordeste, Norte e Centro-Oeste. Usar MW como medida
   de intensidade do tratamento derruba a amostra para 10 campi e elimina *todos* os biomas fora
   da Mata Atlântica — inclusive os pares de pior qualidade. O modelo pareceria melhor por um
   motivo que nada tem a ver com data center.
2. **As colunas socioeconômicas são de nível municipal** e não variam dentro do município: o
   contraste tratamento/controle nelas é entre dois municípios inteiros. Em `everest-goiania` as
   duas pontas caem no mesmo município e o contraste é literalmente zero — marcado em
   `municipio_compartilhado_com_par`.
3. **Os municípios pareados têm portes muito diferentes.** A razão de população
   controle/tratamento vai de **0,03** (`hostdime-joao-pessoa`: João Pessoa 818 mil × Conde 25 mil)
   a **15,0** (`ascenty-vinhedo`: Vinhedo 82 mil × Campinas 1,2 milhão), e **11 dos 15 pares** ficam
   fora da faixa 0,5–2,0. O pareamento foi feito por **cobertura do solo num buffer de 5 km**, que
   é o que o classificador mede — não por porte de município, que não entrou em critério nenhum.
   Consequência prática: **comparar nível** de população, emprego ou PIB entre tratamento e
   controle não significa nada; só a **variação relativa dentro de cada município** ao longo do
   tempo é interpretável.

Renda, desemprego e escolaridade ficaram **fora** do painel de propósito: existem só do lado do
tratamento e com cobertura irregular, e uma variável que existe de um lado só da comparação não é
utilizável num desenho com grupo de controle. Seguem disponíveis nas tabelas originais.

### Detecção: área agregada não vê a obra, trajetória de pixel vê (2026-09-06)

Passos 11 e 12. Este é o resultado que mais importa para o modelo do Guilherme.

**Somar área por classe no buffer não detecta a construção.** Testado em 6 raios (0,5 a 5 km) e nas
3 classes relevantes: a fração de pares em que o tratamento sobe mais que o controle fica em torno
de 0,5 na faixa inteira, e o pico de "solo exposto" cai na fase de obra **menos** vezes que o acaso
previria (4/15 contra 5,1 esperados). **Reduzir o buffer não resolve** — a hipótese de que a janela
era grande demais para o objeto foi testada e refutada.

A causa é conhecida: `solo_exposto_obras` é a pior classe do classificador (F1 **0,579**, precisão
0,587, recall 0,572 — contra 0,74 a 0,92 das outras), porque o MapBiomas não tem classe "canteiro
de obras" e os rótulos são um proxy de solo nu natural (ADR-004). Numa soma de área, cada falso
positivo pesa igual a um pixel verdadeiro.

**Trocar a estatística resolve.** Em vez de somar área, contar pixels que cumprem uma **trajetória
ordenada e persistente**: não ser construída nos 2 primeiros anos da janela, ser construída nos 2
últimos, e permanecer. Um falso positivo isolado não satisfaz uma sequência; três anos coerentes
satisfazem.

| assinatura | raio | pares com excesso | p | Bonferroni (×12) |
|---|---:|---:|---:|---:|
| `virou_construida` | 0,5 km | **13/15** | 0,0037 | 0,044 |
| `virou_construida` | 1 km | **13/15** | 0,0037 | 0,044 |
| `virou_construida_via_solo` | 1 km | **13/15** | 0,0037 | 0,044 |

Duas validações acompanham o achado, ambas no script:

1. **O excesso é localizado, não regional.** De 0,5 km para 5 km o disco cresce 100×, mas o excesso
   cresce só 11,6× (1,53 → 17,75 ha) — a densidade cai 7×. É a assinatura de mudança concentrada no
   terreno, não de uma região urbanizando por inteiro.
2. **As tendências pré-obra são paralelas.** Antes da obra, o tratamento crescia em área construída
   mais rápido que o controle em apenas **6 de 14** pares (p=0,79; diferença mediana −0,16 pp/ano).
   Ou seja: não há evidência de que os data centers tenham sido construídos onde a região já
   urbanizava mais rápido. É a hipótese identificadora do desenho, e ela se sustenta.

Com N=15 isso é sugestivo, não conclusivo — 2 dos 15 pares vão na direção contrária. Mas é a
primeira medida desta frente que sobrevive a um teste estatístico e às duas checagens que tentaram
derrubá-la.

### O excesso não é o prédio: é o entorno (passos 13 e 14)

Puxamos o **footprint real** de cada data center no OpenStreetMap (Overpass). Coberura: **14 de 15**
campi, sendo **7 com `building=data_center` explícito** — três deles a 13–14 m do ponto que o
repositório já tinha validado por outras cinco camadas, o que confirma as coordenadas de forma
independente. Área mediana do footprint: **1,29 ha**.

Dentro do footprint, só **4,8%** dos pixels (mediana) "viraram construída". Isso parece falha do
classificador, e não é: **50% (mediana) já eram construída antes da obra** — e nos casos extremos,
85 a 90% (`ascenty-jundiai`, `ascenty-osasco`, `ascenty-sumare`, `scala-tambore`). Não havia o que
ver aparecer. Bate com as tags `Retrofitted` da planilha do Guilherme e com os footprints
`landuse=industrial`: **estes data centers foram erguidos dentro de parques industriais que já
existiam**. O contra-exemplo confirma a regra: `clickip-manaus` é o único com 0% de terreno já
construído, e ali o classificador viu **75%** dos pixels virarem construída.

**A consequência inverte a leitura do passo 12:** o excesso medido não é o prédio — é conversão no
**entorno** dele, decaindo com a distância:

| zona | pares com excesso | p | excesso mediano |
|---|---:|---:|---:|
| 0–0,5 km | **12/14** | 0,006 | +2,06 pp |
| 0,5–1 km | **12/14** | 0,006 | +1,15 pp |
| 1–2 km | 8/14 | 0,395 | +0,51 pp |

Essa é a afirmação que interessa ao modelo de impacto — e a que exige mais cautela. Ela se sustenta
em N=14, com tendências pré-obra paralelas, mas não é uma estimativa de magnitude.

### Onde havia terreno para converter, o efeito é mais nítido (passo 15)

Estratificando pelo `pct_ja_construida` do footprint, na zona de 0–0,5 km:

- **greenfield** (< 50% já construído): **6 de 6** pares positivos, p=0,016, excesso mediano +2,40 pp
- **brownfield** (≥ 50%): 5 de 7, p=0,227, mediana +0,77 pp

Isso explica os **dois únicos pares negativos** do estudo inteiro: `ascenty-jundiai` (−5,37 pp) e
`ascenty-sumare` (−3,08 pp) são os mais saturados, com 86% e 88% do footprint já construído. Num
sítio saturado sobra pouco terreno convertível, e o excesso encolhe por motivo **mecânico**, não por
ausência de efeito.

O corte de 50% foi escolhido **depois** de ver os dados. O script varre 7 limiares e publica todos:
greenfield fica 100% positivo em toda a faixa de 40% a 80%. O teste contínuo equivalente (Spearman
−0,31, n=13) tem direção consistente mas magnitude fraca — **a leitura defensável é a do padrão,
não a do coeficiente**.

**Anomalias registradas, não corrigidas:** `ascenty-maracanau` ficou sem pixel válido no footprint
(0,82 ha ≈ 9 pixels Landsat, todos com nodata em algum ano); `equinix-santana-parnaiba` tem
footprint de 9,89 ha com só 1,4% classificado como construída ao fim — o polígono do OSM
provavelmente cobre o lote inteiro, não a edificação; `scala-sgigsm01` tem 71% construída no início
e 21% no fim, instabilidade de classificação num tecido urbano muito denso (São João de Meriti,
prop. construída 0,77).

**Para apresentar:** `notebooks/01_modelo_impacto.ipynb` (na raiz do repositório) percorre a
rodada inteira com as figuras — o problema, por que a tabela de candidatos não serviu, o funil de
pareamento, os 15 pares, a regra do sensor único e o painel final, terminando em limitações e
conclusão. Ele **consome** os artefatos já gerados pelos scripts, não recalcula nada — mesma
convenção do `00_demo_preview.ipynb`, que é o notebook do classificador.

**Esta rodada é paralela a `raw/controles/`, não a substitui.** Aquela pareia pelo MapBiomas e
cobre os 16 sites; esta pareia pelo classificador e cobre os 15 com ano de obra conhecido. São
critérios diferentes, e vale poder comparar os dois.

### Temperatura: nulo, mas nulo SEM PODER (passo 16, 2026-09-10)

A LST estava coletada desde o passo 8 — 204/204 ponto-ano, equilibrada em 102 tratamento e 102
controle, 2013-2025, mesmo código nas duas pontas — e **nunca tinha sido analisada**.

O resultado do desenho pareado sobre ela é nulo: **6 de 15** campi aqueceram mais que seu controle,
mediana **−0,07 °C**, p=0,61.

**Esse nulo não é evidência de ausência de aquecimento, e o script publica a prova disso.** A LST
vem do `MOD11A2`, de **1 km** de resolução, medida num disco de **5 km**. O efeito de construção
vive no anel de 0-0,5 km — menor que um único pixel MODIS. Convertendo: +2,06 p.p. num anel de
78,5 ha são ~1,6 ha, que é 0,02% do disco. Contra isso:

| | valor |
|---|---:|
| efeito esperado no disco de 5 km, pela diluição | **0,0015 °C** |
| efeito mínimo detectável do desenho (n=15, α=0,05, poder 80%) | **0,636 °C** |
| razão | **427×** |

O dado de LST em si está sadio, e o script mede isso também: ao longo dos 204 ponto-ano, LST e
proporção de área construída correlacionam a **r=0,49**, com contraste implícito de **7,2 °C** entre
0% e 100% construído. A física está lá; o que falta é escala. Responder essa pergunta de verdade
exige a **banda termal do Landsat (30 m)**, não MODIS.

Script: `scripts/impacto_dc_16_lst_did.py` · saídas `raw/controles-rf/lst_did*.csv` ·
figura `fig_10_lst_did.png`.

### Planilha de resultados para o time (passo 17)

`processed/consolidado_impacto_resultados.xlsx` — 9 abas com as tabelas dos passos 12 a 16, mais
uma aba `leia_primeiro` com os quatro avisos que precisam acompanhar o arquivo.

Existe porque `consolidado_impacto_modelo.xlsx` entrega o **painel**, e as colunas de cobertura
dele (`area_ha_*` / `prop_*`) são justamente a estatística que os passos 10-11 refutaram. Quem
receber só o painel e modelar naquelas colunas repete um beco sem saída já medido aqui.

Script: `scripts/impacto_dc_17_planilha_resultados.py`.

### Eixo econômico (CNPJ): viável em princípio, BLOQUEADO na prática (2026-09-10)

O eixo econômico — *quantas empresas abriram dentro de 1 km do data center, por ano e por setor,
contra o controle* — é a única forma de responder "teve impacto econômico?" na granularidade certa.
A fonte é a base **Dados Públicos CNPJ da Receita Federal**, que tem endereço, CEP, CNAE e **data de
início de atividade** por estabelecimento.

**O teste de granularidade passou.** Antes de qualquer download, medimos se o CEP resolve a escala
do anel de 500 m, consultando o ViaCEP para os CEPs dos 16 sites:

| nível de resolução | sites |
|---|---|
| **Logradouro** (rua específica) | **12** |
| CEP truncado no scraping do datacentermap (5 dígitos) | 3 |
| CEP inexistente (`13140-000`, Paulínia) | 1 |

Onde há CEP completo, **12 de 12 resolvem a logradouro** — uma empresa geocodificada por CEP cai
numa rua, bem dentro do anel. Não é o caso de "CEP cobre o município inteiro", que era o risco.

**O que bloqueia são duas coisas independentes, ambas de infraestrutura, nenhuma de método:**

1. **A fonte mudou de endereço e não é mais enumerável por HTTP.**
   `arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/` devolve 404 servido por uma
   instância **Nextcloud** — o portal migrou para compartilhamentos com token, sem listagem de
   diretório. `dadosabertos.rfb.gov.br/CNPJ/` não responde. A API CKAN de `dados.gov.br`, que
   traria a URL canônica, hoje exige chave (**HTTP 401**).
2. **Espaço em disco.** A máquina tem **13 GB livres de 465 GB (98% em uso)**. A tabela de
   Estabelecimentos tem ~3,5 GB compactada e ~15 GB descompactada. Dá para contornar com
   processamento em fluxo (baixa um ZIP por vez, filtra pelos 27 códigos de município do painel,
   descarta), com pico de ~1 GB — mas isso não ajuda enquanto (1) não estiver resolvido.

**Para destravar** basta uma das duas: a URL atual de um compartilhamento da RFB, ou uma chave da
API do `dados.gov.br`. O desenho da análise já está definido e o teste de viabilidade já foi feito
— o que falta é acesso ao arquivo, não decisão de método.

### Rodada 3 (2026-09-10) — robustez: o que sobrevive a teste

Seis passos novos, e o saldo é **quatro verificações passando e uma inconclusiva declarada como
tal**. A ordem aqui não é cronológica por acaso: os testes que podiam **derrubar** o achado vieram
antes dos que o **estendem**.

| passo | o que testa | resultado |
|---|---|---|
| **19 · Placebo** | o método acha efeito onde nada foi construído? | **PASSOU** |
| **18 · Estudo de evento** | quando a conversão acontece? | timing certo, não sustentado |
| **20 · Janela até t+6** | o efeito persiste ou o controle alcança? | **INCONCLUSIVO** (n=9) |
| **22 · Delta das 5 classes** | água, vegetação densa, solo mudaram? | nada por estoque |
| **21 · Tipo de edificação (OSM)** | residencial, comercial ou industrial? | **inviável**, viés de cobertura |
| **23 · LST Landsat 30 m** | o entorno esquentou? | +0,51 °C, sem significância |

**O placebo (passo 19) é a validação que mais faltava.** 15 pares controle-contra-controle — dois
lugares sem data center cada, mesma janela, mesmo ano de obra fictício, método idêntico:

| raio | placebo | real |
|---|---|---|
| 0,5 km | 8/15 · p=0,50 · +0,22 p.p. | 13/15 · **p=0,0037** · +1,93 p.p. |
| 1,0 km | 7/15 · p=0,70 · −0,26 p.p. | 13/15 · **p=0,0037** · +0,89 p.p. |
| 2,0 km | 7/15 · p=0,70 · −0,37 p.p. | 9/15 · p=0,30 · +0,62 p.p. |

Cai exatamente no acaso, com sinal trocado em dois dos três raios. O parceiro placebo **não** é o
vice do ranking original — aquele mede distância ao *tratamento*; aqui recalculamos a distância ao
*controle*, que é a outra ponta do par placebo.

**A correção de circularidade.** A zona "0-0.5km" do passo 14 era um **disco**, não um anel: continha
o próprio data center. Com footprint mediano de 1,29 ha num disco de 78,5 ha e excesso medido de
~1,6 ha, reportar aquele número como "impacto no entorno" misturava o empreendimento com o efeito
dele. Descontando os pixels do footprint (subtração exata, sem reprocessar raster):

- conversão: **+2,06 → +1,50 p.p.**, mesmos 12/14, mesmo p — **~73% do efeito está fora da cerca**
- vegetação: 10/14 p=0,090 → **11/14 p=0,0287** — passou de sugestivo a **forte**

> **⚠ Correção (2026-09-11) — os dois números acima estão errados.** A subtração aritmética só vale
> se o footprint estiver *dentro* do disco de 500 m, e não está em **4 dos 14** campi
> (`ascenty-vinhedo` 100% fora, a 615 m do ponto validado; `ascenty-sumare` 67%; `scala-sgigsm01`
> 15%; `equinix-santana-parnaiba` 3%). Recalculado por **mascaramento direto sobre o raster**:
> `ascenty-hortolandia` vai de +0,25 para **−1,31 p.p.** (troca de sinal), e o eixo de vegetação
> fica em **16 pares, p=0,105, `sugestivo`** — **não** `forte`. A leitura de que a análise mais
> estrita havia *fortalecido* um eixo era artefato do bug. O achado que se sustenta é o de
> conversão para área construída, e o número de destaque passou a ser o anel de **0,5–1 km**
> (18/20, p=0,0002), livre do prédio por construção. Ver
> `modelo-impacto/reports/relatorio-impacto.md`, seção 4.

**Por que três resultados ficaram fracos, e é um só motivo.** O passo 22 isola a causa: a classe
`construida_urbana`, que a trajetória detecta com 13/15 e p=0,0037, fica **invisível** medida como
**estoque** (8/15, p=1,00). Mesmos pares, mesmos anos, mesma classe — só muda a estatística. Os
passos 18, 20 e 22 são todos estoque, e ficam mudos pelo mesmo motivo: com N=15, estoque não tem
sensibilidade para um efeito de ~1,5 p.p. **A contrapartida honesta é que o resultado central
depende de uma estatística — e a defesa dela é o passo 19.**

**Temperatura, medida duas vezes.** O passo 16 (MODIS 1 km, disco de 5 km) deu nulo e provou que o
nulo não valia (MDE 427× o efeito esperado). O passo 23 refez com Landsat `ST_B10` a 30 m no anel —
872 pixels em vez de uma fração de um. A estimativa vai de −0,07 °C para **+0,51 °C**, com gradiente
de distância coerente com o eixo de conversão. Não atinge significância.

E o achado contraintuitivo: **a resolução melhorou 33× e o poder estatístico piorou** (MDE 0,822 °C
contra 0,636 °C). Porque `MDE = 2,80·σ/√n`, e trocar de sensor não mexe em nenhum dos dois termos a
favor — n caiu de 15 para 12 e o σ entre pares subiu. Resolução e poder são coisas diferentes.

**Por que o OSM não serviu (passo 21).** Só 7 dos 15 pares são usáveis, e as falhas são
sistemáticas: são os **controles** que não têm mapeamento (0, 0, 1, 3, 3, 3, 4, 4 feições) contra
tratamentos com 15 a 5.447. A densidade de mapeamento do OSM correlaciona com urbanização, então o
confundidor corre na **mesma direção da hipótese**. Além disso, 60,8% das feições nos anéis usáveis
não têm tag de tipo. Reforça a necessidade do CNPJ, que tem cobertura uniforme por obrigação legal.

### Reprodução

```bash
python scripts/reproduzir_impacto.py --listar            # os 31 passos, com custo e dependência
python scripts/reproduzir_impacto.py                     # 21 passos offline
python scripts/reproduzir_impacto.py --etapa completo    # + 10 passos de rede (idempotentes)
```

### Para onde isso foi

A camada de modelo em cima destes resultados **não fica nesta pasta** — está em
`modelo-impacto/` (frente separada, criada em 2026-09-10): boletim por eixo com selo de
evidência, teste de poder preditivo e projeção por classe de referência. O resultado central de lá,
que vale registrar aqui: **a magnitude do impacto não é predizível** com as features disponíveis
(R² LOOCV negativo em 13 modelos, permutação p=0,77) — o que se sustenta é o padrão, não o
coeficiente, exatamente como o passo 15 já suspeitava.

## Status

Coleta inicial concluída (2026-09-03): temperatura, população, emprego, PIB, renda, desemprego e
escolaridade levantados; lista reconciliada com o scraping do Guilherme; planilha consolidada
montada. Pendências conhecidas: (1) temperatura/população/emprego não cobrem os 3 sites novos; (2)
desemprego municipal só existe pra 5 dos 18 municípios; (3) nada foi validado com a mesma cascata
de 5 camadas (V1-V5) que os 16 sites originais tiveram.

Rodada 2 concluída (2026-09-05): pareamento pelo classificador e painel de área por classe por ano
gerados para os 15 campi com ano de obra conhecido. Pendências conhecidas: (1) `odata-hortolandia`
segue sem `ano_inicio_obra` e por isso fora do painel; (2) `ascenty-maracanau` entra com janela de
5 anos em vez de 7 (precisaria de 2011-2012, faixa_b desabilitada); (3) `clickip-manaus` e
`scala-spoapa01` entram com 6 anos (obra de 2023, o terceiro ano depois ainda não aconteceu).
