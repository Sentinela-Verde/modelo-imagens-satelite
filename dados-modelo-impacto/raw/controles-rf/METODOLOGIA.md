# Metodologia — grupo de controle pareado pelo classificador (frente do modelo de impacto)

Gerado por `dados-modelo-impacto/scripts/impacto_dc_06_metodologia.py` em 2026-09-10 21:36 UTC.
Ver `dados-modelo-impacto/README.md` para o contexto geral desta pasta e
`DIAGNOSTICO-TABELA-GUILHERME.md` (mesma pasta) para por que a tabela de pontos de controle que
veio do Guilherme não foi usada.

## O que esta rodada é, e como difere da anterior

`raw/controles/` (2026-09-03) já tinha gerado um grupo de controle para os 16 sites, escolhendo o
par pela distribuição de classes do **MapBiomas Coleção 9**. Esta rodada refaz o pareamento com o
mesmo desenho geométrico, mas decidindo pela **saída do nosso classificador Random Forest**
(`models/rf_v1.0-tuned.joblib`), que é o que o modelo de impacto vai consumir. As duas rodadas
coexistem de propósito: são critérios diferentes, e vale poder comparar.

A geração de candidatos não foi reescrita — `impacto_dc_03_gerar_controles.py` importa
`gerar_controles_pareados.py` e chama as mesmas funções de grade, sorteio, filtros geométricos e
filtro de município.

## Escopo: 15 campi

Os 16 sites validados de `config/sites.geojson` menos `odata-hortolandia`, que não tem
`ano_inicio_obra` em nenhuma fonte — sem ano de obra não há como definir "1 ano antes" nem a janela
de 3 anos antes/depois. É a mesma lacuna que já o deixou sem controle na rodada anterior.

Os 12 `id_datacenter` da planilha do Guilherme correspondem a 8 destes campi (vários são prédios do
mesmo campus, a dezenas de metros um do outro). Os outros 7 entraram porque já
estavam validados aqui e ampliam a amostra sem exigir pesquisa nova. A correspondência está em
`reconciliacao_datacenters.csv`.

| campus | município | início da obra | ano de pareamento | janela | anos | sensor |
|---|---|---:|---:|---|---:|---|
| `angonap-fortaleza` | Fortaleza/CE | 2017 | 2016 | 2014–2020 | 7 | Landsat 8/9 |
| `ascenty-hortolandia` | Hortolândia/SP | 2018 | 2017 | 2015–2021 | 7 | Landsat 8/9 |
| `ascenty-jundiai` | Jundiaí/SP | 2019 | 2018 | 2016–2022 | 7 | Landsat 8/9 |
| `ascenty-maracanau` | Maracanaú/CE | 2014 | 2013 | 2013–2017 | 5 | Landsat 8/9 |
| `ascenty-osasco` | Osasco/SP | 2020 | 2019 | 2017–2023 | 7 | Landsat 8/9 |
| `ascenty-paulinia` | Paulínia/SP | 2019 | 2018 | 2016–2022 | 7 | Landsat 8/9 |
| `ascenty-sumare` | Sumaré/SP | 2017 | 2016 | 2014–2020 | 7 | Landsat 8/9 |
| `ascenty-vinhedo` | Vinhedo/SP | 2019 | 2018 | 2016–2022 | 7 | Landsat 8/9 |
| `clickip-manaus` | Manaus/AM | 2023 | 2022 | 2020–2025 | 6 | Sentinel-2 |
| `equinix-santana-parnaiba` | Santana de Parnaíba/SP | 2020 | 2019 | 2017–2023 | 7 | Landsat 8/9 |
| `everest-goiania` | Goiânia/GO | 2021 | 2020 | 2018–2024 | 7 | Landsat 8/9 |
| `hostdime-joao-pessoa` | João Pessoa/PB | 2017 | 2016 | 2014–2020 | 7 | Landsat 8/9 |
| `scala-sgigsm01` | São João de Meriti/RJ | 2022 | 2021 | 2019–2025 | 7 | Sentinel-2 |
| `scala-spoapa01` | Porto Alegre/RS | 2023 | 2022 | 2020–2025 | 6 | Sentinel-2 |
| `scala-tambore` | Barueri/SP | 2021 | 2020 | 2018–2024 | 7 | Landsat 8/9 |

## Passo a passo

1. **Grade de candidatos** — para cada campus, 7 raios
   (16, 20, 24, 28, 32, 36, 40 km) x 24 azimutes
   (a cada 15°) = 168 pontos, com geodésia WGS84
   exata (`pyproj.Geod.fwd`).

2. **Sorteio determinístico e independente por campus** —
   `numpy.random.default_rng([42, crc32(site_id)])` embaralha a ordem de exploração. Cada
   campus tem seu próprio gerador: a ordem de um campus não depende de quais outros foram
   processados antes, então reprocessar um subconjunto (`--sites`) dá o mesmo resultado.

3. **Filtros geométricos** (sem custo de rede):
   - distância entre 15 e 40 km do tratamento — longe o
     bastante para sair do raio de influência do empreendimento, perto o bastante para manter
     regime de licenciamento, pressão de expansão urbana e regime de chuva comparáveis;
   - ≥ 5 km de todo ponto da lista de contaminação;
   - ≥ 10 km (a soma dos dois buffers de 5 km) de qualquer site de
     tratamento ou controle já colocado nesta rodada.

4. **Filtro de município** (com rede, só nos que passaram no 3) — reverse-geocode via Nominatim.
   Aceito se o município for o mesmo do tratamento, ou se estiver na mesma **microrregião do
   IBGE**. Para quando junta 20 candidatos válidos ou após
   80 tentativas.

5. **Pareamento em funil — MapBiomas ranqueia, o classificador decide.**
   - **5a. Pré-ranqueamento (MapBiomas Coleção 9).** Distância L1 entre as distribuições das 5
     classes num buffer de 5 km, no ano de pareamento (1 ano antes do início da obra, grampeado à
     janela 2013-2023 da Coleção 9). É uma consulta server-side no Earth Engine: custa uma
     chamada e nenhum download.
   - **5b. Final (classificador Random Forest).** Os **5 melhores** passam pelo
     pipeline de verdade — ingestão do composto harmonizado, cálculo dos 7 índices, inferência com
     `rf_v1.0-tuned` — e a área por classe resultante é comparada com a do tratamento, no mesmo
     ano e no mesmo sensor. **Vence o menor L1 do classificador.**

   **Por que o funil, e o que ele custa.** Cada ponto-ano no classificador leva ~23 s (download +
   índices + inferência). Avaliar todos os ~20 candidatos válidos
   de 15 campi seriam ~300 pontos e quase 2 h de chamadas encadeadas. O funil reduz para
   5 x 15 = 75. **O custo real assumido:**
   se o melhor candidato pelo classificador estivesse fora do top-5 do MapBiomas,
   ele não seria avaliado. A seção "Concordância entre os dois critérios" abaixo mede o tamanho
   desse risco com os dados desta rodada.

6. **Lista de contaminação** — os 16 sites de `config/sites.geojson` mais todas as linhas de
   `config/sites_candidatos.csv`, **inclusive as rejeitadas**: são justamente lugares onde há data
   center que não entrou no estudo, e usar um deles como controle contaminaria a comparação.

7. **Painel final** (passo 4) — para cada par, área por classe em `obra-3 .. obra+3`, mais o ano de
   fim de obra quando ele cai fora dessa faixa. Tratamento e controle sempre nos mesmos anos e no
   mesmo sensor.

## A regra do sensor único — o ponto mais importante deste desenho

SV-20 (`reports/validacao_sensores.md`) mediu, nos 16 sites x 3 anos de sobreposição: em **48 de 48
pares**, o degrau 2018→2019 da classe "solo exposto/obras" (~1.253 ha em média) é **indistinguível**
do artefato de troca de instrumento (~1.263 ha). A mudança real medida no mesmo sensor
(Landsat 2018→2019) é de −9,5 ha. Uma série emendada sem cuidado atribuiria à obra um crescimento
que é, na prática, inteiramente do satélite.

Por isso a janela de cada par **nunca cruza a fronteira 2018/2019**. Para que isso fosse possível,
a ingestão Landsat foi estendida de 2021 para **2024** (passo 2) — Landsat 8/9 cobre esses anos, o
repositório simplesmente tinha parado antes. Resultado: 12 campi
inteiramente em Landsat e 3 inteiramente em Sentinel-2
(os de obra em 2022/2023, cuja janela inteira já está na era do Sentinel-2).

Efeito colateral registrado: os anos Landsat 2022-2024 agora existem em
`data/processed/classificado/`, então a próxima execução de `sentinela.export_indicadores`
acrescenta linhas a `outputs/indicadores/area_por_classe.csv`. Isso muda o output consumido pela
etapa de Indicadores e foi sinalizado antes de implementar, como pede o `CLAUDE.md` da raiz.

O passo 5 (`impacto_dc_05_grafico_sanidade.py`) gera, por par, uma figura com a série mono-sensor
em cima e, embaixo, a comparação contra a leitura emendada — a confirmação visual de que a janela
escolhida não está inflada pela troca de satélite.

## Limiares de qualidade — e a ressalva de que eles foram calibrados noutra métrica

`l1_rf` ≤ 0,10 → `bom` · ≤ 0,20 → `aceitavel` · acima → `ruim`. São os mesmos limiares de SV-29 e
da rodada anterior. **Pares `ruim` são reportados, não escondidos nem descartados, e nenhum limiar
foi afrouxado.**

**Mas os dois números não estão na mesma escala.** Os limiares de SV-29 foram calibrados sobre o L1
do **MapBiomas**; aqui eles são aplicados ao L1 do **classificador**, que para o mesmo par tende a
ser menor:

- Mediana de `l1_rf`: **0.4890**; de `l1_mapbiomas` nos mesmos controles: **0.6108**.
- `l1_rf` é menor que `l1_mapbiomas` em **13 de 15** pares (razão mediana `l1_rf`/`l1_mapbiomas` = **0.79**).
- Pelo limiar de 0,20: **5 de 15** pares passam medindo pelo classificador, contra **2 de 15** medindo pelo MapBiomas.

Ou seja: contar quantos pares ficaram "dentro do limiar" nesta rodada e comparar com a contagem da
rodada anterior **não é uma comparação justa** — a mesma régua sobre uma métrica que corre mais
baixa aprova mais. Os limiares foram mantidos assim mesmo, de propósito, porque recalibrá-los
exigiria uma referência externa que não temos, e mudar a régua no meio do estudo é pior que usar
uma régua declaradamente aproximada. **Quando for comparar as duas rodadas, compare a coluna
`l1_mapbiomas` desta com a `l1_cobertura` daquela** — essas sim estão na mesma escala.

## Resultado desta rodada

- **15 de 15** campi com controle gerado.
- Distribuição de qualidade (pelo L1 do classificador): **aceitavel=2**, **bom=3**, **ruim=10**.
- Distância tratamento↔controle: 16.0 a 36.0 km (mediana 20.0 km).
- Método de vizinhança: `municipio_vizinho_microrregiao_ibge`=14, `mesmo_municipio`=1.

| campus | controle | dist. | L1 (RF) | L1 (MapBiomas) | qualidade | vizinhança |
|---|---|---:|---:|---:|---|---|
| `ascenty-hortolandia` | `ctrl-ascenty-hortolandia-p01` | 16.0 km | 0.0363 | 0.0567 | bom | municipio_vizinho_microrregiao_ibge |
| `ascenty-paulinia` | `ctrl-ascenty-paulinia-p02` | 20.0 km | 0.0721 | 0.2820 | bom | municipio_vizinho_microrregiao_ibge |
| `ascenty-jundiai` | `ctrl-ascenty-jundiai-p01` | 24.0 km | 0.0883 | 0.0438 | bom | municipio_vizinho_microrregiao_ibge |
| `ascenty-vinhedo` | `ctrl-ascenty-vinhedo-p02` | 28.0 km | 0.1316 | 0.2733 | aceitavel | municipio_vizinho_microrregiao_ibge |
| `angonap-fortaleza` | `ctrl-angonap-fortaleza-p01` | 16.0 km | 0.1579 | 0.3845 | aceitavel | municipio_vizinho_microrregiao_ibge |
| `ascenty-osasco` | `ctrl-ascenty-osasco-p01` | 16.0 km | 0.2659 | 0.3055 | ruim | municipio_vizinho_microrregiao_ibge |
| `ascenty-sumare` | `ctrl-ascenty-sumare-p01` | 28.0 km | 0.4111 | 0.2560 | ruim | municipio_vizinho_microrregiao_ibge |
| `scala-spoapa01` | `ctrl-scala-spoapa01-p01` | 20.0 km | 0.4890 | 0.6289 | ruim | municipio_vizinho_microrregiao_ibge |
| `equinix-santana-parnaiba` | `ctrl-equinix-santana-parnaiba-p01` | 16.0 km | 0.5415 | 0.6108 | ruim | municipio_vizinho_microrregiao_ibge |
| `hostdime-joao-pessoa` | `ctrl-hostdime-joao-pessoa-p01` | 16.0 km | 0.6552 | 0.8330 | ruim | municipio_vizinho_microrregiao_ibge |
| `ascenty-maracanau` | `ctrl-ascenty-maracanau-p03` | 36.0 km | 0.8549 | 0.9986 | ruim | municipio_vizinho_microrregiao_ibge |
| `scala-sgigsm01` | `ctrl-scala-sgigsm01-p01` | 16.0 km | 0.8624 | 0.9173 | ruim | municipio_vizinho_microrregiao_ibge |
| `everest-goiania` | `ctrl-everest-goiania-p01` | 20.0 km | 0.8661 | 1.0901 | ruim | mesmo_municipio |
| `scala-tambore` | `ctrl-scala-tambore-p01` | 20.0 km | 1.0625 | 1.2601 | ruim | municipio_vizinho_microrregiao_ibge |
| `clickip-manaus` | `ctrl-clickip-manaus-p01` | 32.0 km | 1.3692 | 1.7261 | ruim | municipio_vizinho_microrregiao_ibge |


## Concordância entre os dois critérios (prestação de contas do funil)

Correlação de Spearman entre `l1_mapbiomas` e `l1_rf` nos 71 finalistas avaliados: **0.932**. Em **12 de 15** campi o candidato que o MapBiomas colocaria em primeiro é o mesmo que o classificador escolheu.

Uma correlação alta é o que justifica o funil: o pré-filtro do MapBiomas raramente joga fora o candidato que o classificador escolheria. Onde os dois discordam, **quem decide é o classificador** — o `l1_mapbiomas` está publicado em `candidatos_avaliados_rf.csv` só para permitir esta conferência, nunca entra na escolha final.


## Painel final

- **204 linhas**: 30 pontos (15 pares x 2) x os anos de cada janela.
- Anos cobertos: 2013–2025.
- Pares por sensor: **landsat=12**, **s2=3**.
- Tratamento e controle têm sempre o mesmo número de anos: sim.
- Janela truncada (menos de 7 anos) em: `ascenty-maracanau`, `clickip-manaus`, `scala-spoapa01` — reportado, não corrigido: os anos que faltam não existem na cobertura do sensor.
- Distribuição das fases: `pre`=86, `durante`=70, `pos`=48 (a fase vem de `ano_inicio_obra` e `ano_fim_obra`, este último o fim de `periodo_durante` em `config/sites.geojson`).
- **Sem nenhum ano `pos` no painel**: `ascenty-hortolandia` (obra 2018–2022, janela até 2022), `ascenty-osasco` (obra 2020–2023, janela até 2023). A obra desses campi durou mais que os 3 anos posteriores ao início, então a janela termina antes de haver um ano pós-construção. Para uma leitura de efeito depois da obra, esses dois precisariam de uma janela ancorada no FIM da obra, não no início — decisão de desenho que não foi tomada aqui (o briefing ancora no início) e fica registrada como lacuna.


## Limitações conhecidas (documentadas, não escondidas)

- **O pré-filtro do MapBiomas pode, em princípio, descartar o melhor candidato pelo classificador**
  antes que ele seja avaliado. Medido acima; não eliminado. Eliminar exigiria rodar o classificador
  em todos os candidatos válidos (~2 h).
- **A adjacência de município usa "mesma microrregião do IBGE" como proxy de "município vizinho"**,
  não a malha poligonal oficial de fronteiras — herdado da rodada anterior, mesma ressalva.
- **A lista de contaminação usa centróide de município** para os candidatos de
  `config/sites_candidatos.csv` que nunca tiveram coordenada validada. Em municípios grandes o
  centróide pode estar longe do data center real, então a checagem de 5 km pode não pegar uma
  contaminação real fora do centro — risco residual herdado, não mitigado aqui.
- **`ascenty-maracanau` tem janela truncada** (obra 2014, precisaria de 2011-2012): a faixa_b de
  `config/params.yml` está desabilitada porque a harmonização TM→OLI nunca foi validada e o
  MapBiomas Coleção 9 começa em 2013. Ele entra com 5 anos em vez de 7.
- **`clickip-manaus` e `scala-spoapa01` têm 6 anos em vez de 7** — a obra é de 2023, e o terceiro
  ano depois (2026) ainda não existe.
- **Um controle não prova ausência de efeito.** Ele isola mudança de cobertura do solo que teria
  acontecido de qualquer jeito na mesma região; não controla nada que seja específico do terreno do
  tratamento e não da região. Vale com a mesma força a ressalva geral do
  `dados-modelo-impacto/README.md` sobre variáveis municipais não sustentarem afirmação causal.

## Arquivos desta rodada

| arquivo | conteúdo |
|---|---|
| `reconciliacao_datacenters.csv` | os 12 `id_datacenter` do Guilherme → `site_id` deste repo |
| `diagnostico_candidatos_guilherme.csv` | os 72 candidatos dele, ponto a ponto, com a marca de contaminação |
| `DIAGNOSTICO-TABELA-GUILHERME.md` | o documento explicando por que a tabela dele não foi usada |
| `pareamento_controle_rf.csv` | **a tabela de pareamento** (1 controle por campus) |
| `candidatos_avaliados_rf.csv` | todos os finalistas, com `l1_mapbiomas` e `l1_rf` lado a lado |
| `sites_controle_rf.geojson` | os controles no schema de `config/sites.geojson` |
| `figuras/serie_*.png` | os gráficos de sanidade com o sensor marcado |
| `../../processed/painel_impacto_area_por_classe.csv` | **o painel final** consumido pelo modelo de impacto |
