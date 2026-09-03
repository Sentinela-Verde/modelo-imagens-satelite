# Schema dos artefatos de output — frente de Indicadores (etapa 05)

- **Gerado por:** `src/sentinela/export_indicadores.py` (SV-15)
- **Consome:** os rasters classificados de SV-14 (`data/processed/classificado/`)
- **Status do contrato:** **ACORDADO** (`docs/decisoes/ADR-002-contrato-indicadores.md`, resposta
  recebida em 2026-08-27) — a frente de Indicadores respondeu que ainda não tinha indicadores
  próprios estabelecidos e aceitou o schema desta frente como base, sem contraproposta. Isto não é
  "nosso contrato interno até alguém objetar": na ausência de outra definição, **este schema é a
  definição de indicador do projeto Sentinela Verde**.
- **Modelo oficial da V1:** `rf_v1.0-tuned` (ver `docs/decisoes/ADR-004-fonte-de-labels.md`,
  `reports/experiments/EXP-002-rf-labels-manuais.md`,
  `reports/experiments/EXP-003-tuning-hiperparametros.md`). **Substituiu `rf_v1.0` em 2026-09-03**
  (EXP-003: `max_depth=30` — F1 classe 3 igual ou melhor que `rf_v1.0` nos dois recortes de holdout
  espacial, e 8,1% menor em disco; `rf_v1.0.joblib` foi apagado após a troca, redundante e
  regenerável a partir de `EXP-002-rf-v1.0-treino.md`). Todo artefato leva `modelo_versao` em toda
  linha/feature, não só no nome do arquivo — se a frente de Indicadores estiver usando uma versão
  diferente da que está circulando, essa coluna é como perceber.

> **Se você é da frente de Indicadores e está lendo isto pela primeira vez:** vá direto para
> "Como plotar a série sem mentir" e "Limitações que quem consome precisa saber" antes de montar
> qualquer gráfico ou de citar qualquer número num relatório. Este output nomeia empresas reais.

---

## Convenção de classes (fixa, não muda sem ADR novo)

| `classe_id` | `classe_nome` (slug) | Nome de exibição | Observação |
|---|---|---|---|
| 0 | `nodata` | Sem dado | **Nunca aparece como linha do CSV nem como polígono do GeoJSON** — pixel fora da AOI, mascarado por nuvem, ou sem classificação válida. Existe só dentro do raster (`.tif`, `nodata=0`). |
| 1 | `vegetacao_densa` | Vegetação densa | Cobertura arbórea nativa ou cultivo denso. |
| 2 | `vegetacao_rala` | Vegetação rala / pasto / agricultura leve | Pastagem, arbusto, campo, agricultura leve. |
| 3 | `solo_exposto_obras` | Solo exposto / em obras | **Classe crítica do projeto** — sinal mais forte de início de construção. Ver limitações abaixo antes de usar esta coluna para qualquer afirmação. |
| 4 | `construida_urbana` | Área construída / urbana | Inclui o data center e infraestrutura associada; infraestrutura viária não é classe própria na V1. |
| 5 | `agua` | Água | Corpos d'água permanentes. |

Fonte única de verdade: `config/classes.yml`. Não redecida aqui — só documenta.

---

## Artefato 1 — `outputs/indicadores/area_por_classe.csv`

Uma linha por **site × ano × sensor × classe** (5 linhas por combinação site/ano/sensor, sempre —
mesmo quando `area_m2 = 0`; nunca falta linha por ausência de pixel daquela classe).

### Dicionário de colunas

| Coluna | Tipo | Unidade | Descrição |
|---|---|---|---|
| `site_id` | string | — | Identificador da AOI, `config/sites.geojson` (ex.: `ascenty-vinhedo`). **Nomeia a empresa/operador via o prefixo do id** — ver seção de risco. |
| `ano` | int | ano calendário | 2013–2025. |
| `sensor` | string | — | `sentinel2` ou `landsat`. **Obrigatório em toda linha** — é a diferença entre um gráfico honesto e um gráfico enganoso (ver seção dedicada abaixo). |
| `resolucao_m` | int | metros/pixel | `10` (Sentinel-2) ou `30` (Landsat). **Obrigatório em toda linha**, mesmo motivo de `sensor`. |
| `classe_id` | int | — | 1–5 (nunca 0 — nodata não vira linha). |
| `classe_nome` | string | — | Slug da classe (`config/classes.yml`), ex. `solo_exposto_obras`. |
| `area_m2` | float | m² | Área da classe no site/ano/sensor, calculada em **EPSG:31983** (nunca em graus): `n_pixels_da_classe × resolucao_m²`. |
| `area_ha` | float | hectares | `area_m2 / 10000`, exatamente (nunca arredondado de forma independente de `area_m2`). |
| `pct_area_valida` | float | % (0–100) | `n_pixels_da_classe / pixels_validos × 100`. **Denominador é a área válida (sem nodata), não a área total do buffer de 5 km** — senão nuvem/borda do buffer vira "classe fantasma". As 5 linhas de um mesmo site/ano/sensor somam 100 (± 0.01). |
| `pixels_validos` | int | pixels | Total de pixels válidos (não-nodata) do site/ano/sensor — **constante nas 5 linhas do grupo**, repetida por linha para permitir a checagem `pixels_validos × resolucao_m² == Σ area_m2 do grupo` sem precisar fazer join com outro arquivo. |
| `fator_correcao_sensor` | float | — | **Calculado por SV-20** (`src/sentinela/validacao_sensores.py`, `reports/validacao_sensores.md`), lido de `data/manifests/fator_correcao_sensor_sv20.json`. `1.0` na maior parte das linhas; ≠ `1.0` só nas 96 linhas `sensor=landsat`, `classe_id=4` (construída/urbana), `ano` 2013–2018 — o fator multiplicativo por site calibrado na sobreposição (ver seção dedicada abaixo). `area_m2`/`area_ha`/`pct_area_valida` **continuam crus**, nunca corrigidos in-place — aplique você mesmo `area_corrigida_ha = area_ha * fator_correcao_sensor` se for usar. Sem o JSON de SV-20 no disco, esta coluna volta a ser `1.0` em toda linha (comportamento anterior). |
| `modelo_versao` | string | — | `rf_v1.0-tuned` (modelo oficial desde 2026-09-03; ou o que for passado em `--modelo-versao`). Modelo anterior, `rf_v1.0`, substituído por EXP-003 — ver nota no topo deste documento. |
| `gerado_em` | ISO 8601 (UTC) | — | Timestamp único da execução do comando (não por linha) — dois runs diferem só nesta coluna. |
| `tipo` | string | — | `tratamento` ou `controle`. **Hoje só existe `tratamento`** — o grupo de controle pareado (SV-29) ainda não rodou. Não filtre nem assuma controle disponível até esta coluna mostrar `controle` em alguma linha. |
| `pareado_com` | string | — | `site_id` do controle pareado desta AOI de tratamento. **Vazio (`""`) em toda linha desta versão**, pela mesma razão de `tipo`. |
| `tier` | int | — | `1` ou `2`, de `config/sites.geojson`. Tier 1 = pipeline completo **com** rotulagem manual complementar (SV-09/SV-10). Tier 2 = pipeline completo **sem** rotulagem manual — ver limitações. |
| `precisao_coordenada` | string | — | `exata`, `aproximada` ou `inferida`, de `config/sites.geojson` (SV-25). **A mais importante das 4 colunas novas** — ver seção de risco. |
| `faixa_serie` | string | — | **Coluna nova de SV-20.** Marca o segmento/tratamento da linha — ver seção dedicada "Coluna `faixa_serie` (SV-20)" logo abaixo. Existe pra você não ter que reconstruir essa lógica olhando `sensor`+`ano`+`classe_id` toda vez que for plotar. |

### CRS e cálculo de área

Área calculada sobre o raster classificado, que já está nativamente em **EPSG:31983** (SIRGAS
2000 / UTM 23S, metros) — nenhuma reprojeção acontece para o cálculo de área do Artefato 1. Pixel
Sentinel-2 = 100 m² (10×10); pixel Landsat = 900 m² (30×30).

### Anos de sobreposição (2019–2021)

`config/params.yml` define `anos_sobreposicao: [2019, 2020, 2021]` — para esses 3 anos, **cada
site tem duas linhas por classe**: uma com `sensor=landsat`, outra com `sensor=sentinel2`,
distinguíveis pela coluna `sensor`. **Recomendação: use a série Sentinel-2 como oficial** (10 m,
mais recente); o Landsat desses 3 anos existe só para permitir a checagem cruzada e a validação de
SV-20 — não some as duas linhas nem tire a média sem saber o que está fazendo, ou a "área" do ano
sobreposto conta o terreno duas vezes.

### Coluna `faixa_serie` (SV-20)

SV-20 (`src/sentinela/validacao_sensores.py`, `reports/validacao_sensores.md`) mediu o viés entre
sensores **na área publicada** (não só no espectro) e decidiu, por classe, se esse viés é corrigível
ou se a série tem que ser publicada em faixas separadas sem emenda. A coluna `faixa_serie` marca o
resultado dessa decisão, linha a linha, com 4 valores possíveis:

| `faixa_serie` | Quando aparece | O que significa |
|---|---|---|
| `sentinel2_oficial_2019_2025` | `sensor=sentinel2` (sempre, 2019–2025) | A série oficial recomendada — 10 m, sem correção necessária. |
| `landsat_overlap_referencia` | `sensor=landsat`, `ano` 2019–2021 (qualquer classe) | Landsat do período de sobreposição — existe só para checagem cruzada/SV-20. **Nunca use como série**; o ano correspondente já tem o valor oficial na linha `sentinel2_oficial_2019_2025`. |
| `landsat_pre2019_nao_corrigido` | `sensor=landsat`, `ano` 2013–2018, `classe_id` ∈ {1, 2, **3**, 5} | Era exclusivamente Landsat, **sem correção aplicada** — inclui a classe crítica do projeto (3 = solo exposto/obras). SV-20 mediu que o viés de sensor nessa classe varia demais de site para site (3,5x a 23,5x) pra ser corrigido com um fator só — ver `reports/validacao_sensores.md`, seção 6. |
| `landsat_pre2019_corrigido_sv20` | `sensor=landsat`, `ano` 2013–2018, `classe_id=4` (construída/urbana) | Era Landsat, **com fator de correção aplicado** (`fator_correcao_sensor` ≠ 1.0 nessas 96 linhas) — o viés nessa classe se mostrou estável o bastante (dentro de cada site, e entre os 16 sites) para justificar um fator por site. |

**Regra prática pra não emendar a série sem querer:** ao plotar qualquer classe ao longo de
2013–2025, filtre por `faixa_serie` (não só por `sensor`) e trate `landsat_pre2019_nao_corrigido` /
`landsat_pre2019_corrigido_sv20` como um segmento visualmente distinto de
`sentinel2_oficial_2019_2025` — mesmo na classe 4 (corrigida), continue marcando a transição
(diferença de tratamento estatístico, não motivo pra ligar os pontos sem indicar a mudança).
**Nunca inclua `landsat_overlap_referencia` numa série temporal** — esses 3 anos já têm o valor
oficial (Sentinel-2) na mesma tabela; incluir os dois conta o mesmo ano duas vezes.

---

## Artefato 2 — `outputs/indicadores/classes_{site_id}_{ano}_{sensor}.geojson`

Polígonos vetorizados por classe, um arquivo por combinação site × ano × sensor (mesma cobertura
do Artefato 1). Gerado com `rasterio.features.shapes` sobre o raster de classe, **CRS de saída
EPSG:4326** (WGS84 — lon/lat, o CRS padrão do GeoJSON/RFC 7946 e o que QGIS/geojson.io esperam por
convenção).

### Propriedades de cada feature

| Propriedade | Tipo | Descrição |
|---|---|---|
| `site_id` | string | Mesmo valor do Artefato 1. |
| `ano` | int | Mesmo valor do Artefato 1. |
| `sensor` | string | `sentinel2` \| `landsat` — mesmo valor canônico do Artefato 1 (não o token de caminho `s2`/`landsat` usado internamente nos diretórios de SV-14). |
| `resolucao_m` | int | `10` ou `30`. |
| `classe_id` | int | 1–5. |
| `classe_nome` | string | Slug da classe. |
| `area_m2` | float | Área do polígono (multipolígono dissolvido da classe), **calculada em EPSG:31983 antes da reprojeção para 4326** (reprojeção para graus distorce área; nunca calcule área em EPSG:4326). |

### Filtro de área mínima e o que é descartado

Polígonos individuais **menores que 0.1 ha (1.000 m²)** são descartados **antes** do dissolve por
classe (uma mancha minúscula não vira polígono, mesmo que duas manchas minúsculas adjacentes
juntas passassem do limiar — o teste é por mancha original, não pelo resultado já fundido).

Isso remove **proporcionalmente muito mais no Landsat**: 0.1 ha equivale a ~1,1 pixel Landsat (900
m²/pixel) contra 10 pixels Sentinel-2 (100 m²/pixel) — ou seja, **praticamente qualquer pixel
isolado de Landsat é descartado do GeoJSON**, mesmo que ele conte normalmente na área do Artefato 1
(que não tem esse filtro). Isso é esperado e é por isso que a área somada dos polígonos de um
`classes_*.geojson` pode ser **menor** que a `area_m2` da classe correspondente em
`area_por_classe.csv` — o CSV é a fonte de verdade da área; o GeoJSON é para visualização, não para
recalcular indicadores de área.

A área e a contagem exatas do que foi descartado, por `site_id`/`ano`/`sensor`/`classe_id`, ficam
em `outputs/indicadores/geojson_poligonos_descartados.csv` (mesmo diretório de output, mesma
regeneração automática, não versionado no git).

---

## Artefato 3 — os rasters classificados de SV-14 (referência, não regenerados por este comando)

`data/processed/classificado/{sensor}/{site_id}/{ano}.tif` — raster de 1 banda uint8 (classes 1–5,
`nodata=0`), **EPSG:31983**, gitignored (dado processado pesado, `.gitignore` do projeto).
`{sensor}` no caminho é o **token físico** `s2`/`landsat` (diferente do valor canônico
`sentinel2`/`landsat` usado nas colunas `sensor` dos Artefatos 1 e 2 — não confundir os dois).

Manifest por raster: `data/manifests/classificado_{sensor}_{site_id}_{ano}.json` — traz
`modelo_sha256`, `git_sha`, `dataset_versao`, `lista_features` e `distribuicao_classes` (contagem
de pixels por classe calculada no momento da inferência; o Artefato 1 recalcula essa contagem
direto do `.tif` de novo, como checagem redundante, em vez de confiar cegamente neste campo).

### Como regenerar tudo do zero

```
# 1. Reclassificar os rasters (SV-14) — só necessário se o modelo mudou ou o raster não existe:
python -m sentinela.predict --modelo models/rf_v1.0-tuned.joblib --sensor all --site all

# 2. Gerar os dois artefatos de indicadores (este comando, SV-15):
python -m sentinela.export_indicadores --modelo-versao rf_v1.0-tuned
```

`export_indicadores` **não roda inferência** — ele só lê o que `predict` já classificou. Se o
`modelo_versao` pedido não tiver rasters correspondentes em `data/manifests/`, o comando falha
explicitamente listando as versões disponíveis, em vez de exportar um CSV vazio ou misturado.

Determinismo: os dois artefatos derivam inteiramente do conteúdo dos `.tif` + `config/sites.geojson`
+ `config/params.yml` (dados estáticos). Rodar o comando duas vezes produz `area_por_classe.csv`
byte-a-byte idêntico, exceto a coluna `gerado_em` (um timestamp por execução, não por linha).

### Nota sobre a área total de cada AOI — não é a área do círculo de 5 km

Somando as 5 classes de um site/ano/sensor (`Σ area_ha` do grupo), a área total medida fica em
**~10.040–10.070 ha**, não nos ~7.850 ha que a matemática de um **círculo** de raio 5 km daria
(`π × 5² ≈ 78,54 km² ≈ 7.854 ha`). Isso não é um bug de `export_indicadores`: o raster de SV-06/SV-08
cobre o **retângulo delimitador (bounding box)** do buffer de 5 km, não o círculo recortado — um
quadrado de ~10×10 km tem ~100 km² = 10.000 ha, batendo com o valor medido (a diferença residual,
~0,4–0,7%, é arredondamento de grade de pixel e discrepância de projeção). `pct_pixels_validos` de
cada raster já é ~99,98% (manifests de SV-14), consistente com "quase nenhum nodata" — o que também
confirma que não há máscara circular aplicada. Se a frente de Indicadores calcular "% da AOI
afetada" usando 7.850 ha como denominador, o número sai errado por ~28%; use a soma de `area_ha` do
próprio grupo (`site_id`/`ano`/`sensor`) do CSV como denominador, nunca uma constante fixa de área
de buffer.

---

## Como plotar a série sem mentir

A série cobre **2013–2025 com dois sensores diferentes**: Landsat 8/9 (30 m) de 2013 a 2018,
Sentinel-2 (10 m) de 2019 a 2025, trocando exatamente no mesmo período em que a maioria dos data
centers do estudo começou a ser construída (ver `config/sites.geojson`, campo `ano_inicio_obra`).
**Isso é o risco metodológico mais provável de todo este output**: um gráfico que ignore a troca
pode mostrar um "degrau" em 2019 que é do satélite, não do terreno.

Regras práticas:

1. **Sempre segmente por `faixa_serie`** (não só por `sensor` — ver seção dedicada acima), nunca
   trace uma linha única atravessando 2018→2019 sem marcar a transição. O jeito mais simples: uma
   cor/estilo de linha por valor de `faixa_serie`, e uma linha vertical ou sombreamento no eixo do
   tempo em 2019.
2. **Nos anos de sobreposição (2019, 2020, 2021), plote as duas séries lado a lado** (não
   escolha uma e esconda a outra) — a diferença entre elas naqueles 3 pontos é o melhor indício
   visual de quanto do "degrau" é sensor. Nunca ligue os pontos `landsat_overlap_referencia` como
   se fossem parte da série principal.
3. **O que este projeto mediu sobre o tamanho desse degrau, no nível espectral:** o spike de
   harmonização (SV-02b, `docs/decisoes/ADR-003-harmonizacao-multissensor.md`) mediu resíduo
   *espectral* banda a banda no período de sobreposição e **não bateu a tolerância em 3 de 6
   bandas** (NIR por R² baixo — 0.645 —, SWIR1 e SWIR2 por viés sistemático de 0.021 e 0.025,
   acima do limite de 0.02). A resposta adotada (ADR-003, "Plano B opção 1") foi incluir `sensor`
   como feature explícita do modelo (`sensor_landsat`, presente em `rf_v1.0` e mantida em
   `rf_v1.0-tuned` — EXP-003 só ajustou `max_depth`/tamanho em disco, não o conjunto de features),
   para o classificador
   aprender a compensar o resíduo em vez de confundi-lo com sinal real de mudança.
4. **O que este projeto mediu no nível da SAÍDA (SV-20, `reports/validacao_sensores.md`):** com o
   resíduo espectral respondido pela feature `sensor_landsat` (item 3), SV-20 mediu se isso bastou
   olhando pra área por classe — a métrica que este CSV de fato publica — nos 48 pares site×ano de
   sobreposição, com um controle de resolução dedicado (agregar o próprio Sentinel-2 de 10 m pra
   30 m e comparar com ele mesmo, isolando pixel-misto de sensor). **Resultado: não bastou, para a
   classe crítica do projeto.** Controlando a resolução, o Sentinel-2 ainda reporta em média
   **923 ha a mais de solo exposto/obras** que o Landsat no mesmo ano — um número quase idêntico ao
   "degrau" de 1.253 ha que a série bruta mostraria entre 2018 e 2019 — e em **48 de 48 sites
   (100%)** esse degrau é classificado como indistinguível do artefato de troca de sensor. Por isso
   a classe 3 é publicada em faixas separadas (`faixa_serie`), sem correção nem emenda. A classe 4
   (construída/urbana) teve resultado diferente — o viés se mostrou estável o bastante, dentro de
   cada site e entre os 16 sites, para justificar um fator de correção por site
   (`fator_correcao_sensor` ≠ 1.0 nas linhas `landsat_pre2019_corrigido_sv20`). Ver
   `reports/validacao_sensores.md` para a análise completa (tabela de diferença de área,
   concordância espacial, matriz de confusão, análise borda-vs-interior, decisão de tratamento por
   classe).
5. **O achado que disparou SV-20** (originalmente medido aqui mesmo, direto no CSV, antes de SV-20
   rodar): comparando as linhas de `area_por_classe.csv` nos 3 anos de sobreposição, a área da
   classe 3 que o Sentinel-2 reporta é sistematicamente maior que a do Landsat em TODOS os 48 pares
   site×ano, sem exceção — 6,6 a 18,4 pontos percentuais da área do site. SV-20 confirmou esse
   número (pareamento correto, cenário de teste 1) e foi além: separou quanto disso é resolução
   (menor) de quanto é sensor propriamente dito (maior, e na mesma direção do viés total) — ver
   item 4.
6. Índices que mais concentram o resíduo espectral não-corrigido são os ligados a SWIR (`ndbi`,
   viés de 0.034 — o maior de todos) — a fronteira solo/construído (classes 3/4) é justamente onde
   SWIR pesa mais. SV-20 encontrou um sinal consistente com isso na saída: dos pixels que o Landsat
   classifica como `construida_urbana`, 16,2% (438 mil pixels) o Sentinel-2 (mesma resolução)
   classifica como `solo_exposto_obras` — 52,6x mais que a confusão na direção oposta.

---

## Limitações que quem consome precisa saber

Números medidos, não estimativas otimistas — copiados de `reports/avaliacao_rf_v1.0-tuned.md`
(SV-13, modelo oficial desde 2026-09-03, EXP-003) e `reports/experiments/EXP-002-rf-labels-manuais.md`
(SV-16), não recalculados aqui. (O item 6, sobre ganho por bioma da rotulagem manual, vem de
EXP-002 e não é afetado pela troca de hiperparâmetros de EXP-003 — é um experimento sobre fonte de
label, não sobre o modelo.)

1. **F1 da classe 3 (solo exposto/obras) é o número mais importante deste projeto e é
   moderado, não alto.** No holdout espacial (área nunca vista em treino): **F1 = 0.5795**
   (precision 0.587, recall 0.572). No holdout de AOI inteira nunca vista em nenhum split de
   treino — a medida mais realista de "funciona num data center novo" — **F1 = 0.5454, abaixo da
   meta de referência do projeto (≥ 0.55)**, ainda que mais perto dela que `rf_v1.0` (0.5407). Por
   site individual, a F1 da classe 3 varia de **0.216** (`scala-sgigsm01`, praticamente não detecta
   solo exposto/obras) a **0.818** (`angonap-fortaleza`) — o modelo **não funciona igual em todo
   lugar**, e qualquer indicador agregado por região deve declarar essa variação, não escondê-la
   atrás de uma média nacional.

2. **A classe 3 é sistematicamente pior na era Landsat.** F1 classe 3: **0.4794** (Landsat,
   2013–2018) contra **0.5868** (Sentinel-2, 2019–2025) — recall cai para **0.421** no Landsat
   (contra 0.582 no Sentinel-2). Ou seja: a metade mais antiga da série (justamente a que cobre o
   "antes" da maioria das obras) é estruturalmente menos confiável na classe que mais importa. Isso
   soma-se ao risco de "degrau de sensor" descrito acima — não é só um problema de comparabilidade
   entre eras, é um problema de a era mais antiga ter menos sinal para a classe crítica.

3. **3 dos 16 sites (tier 2) nunca tiveram rotulagem manual complementar**:
   `ascenty-jundiai`, `ascenty-paulinia`, `hostdime-joao-pessoa` (`config/sites.geojson`, campo
   `tier == 2`). A rotulagem manual (SV-09/SV-10) existe porque nem o MapBiomas nem o WorldCover
   têm uma classe "canteiro de obras" — nesses 3 sites, a classe 3 depende inteiramente do proxy
   automático (ver item 5). Isso não significa que a classificação lá seja necessariamente pior —
   o teste de decoreba (EXP-002) mostrou que o modelo generaliza dos polígonos manuais para pixels
   automáticos vizinhos —, mas significa que **não há nenhuma verificação humana direta da classe 3
   nesses 3 sites especificamente**, e isso deveria pesar mais na leitura de qualquer indicador
   desses 3 `site_id`.

4. **`precisao_coordenada` varia por site e afeta a autoridade de qualquer afirmação.** Nem toda
   AOI tem coordenada `exata`: `ascenty-sumare` e `ascenty-paulinia` são `aproximada` (geocode de
   bairro/subestação associada, não do prédio confirmado — ambas estão na fila de conferência
   visual humana registrada em `config/sites.geojson`, campo `fila_visual`); `everest-goiania`
   também é `aproximada`. **Uma linha ancorada numa coordenada `aproximada` ou `inferida` não deve
   circular com a mesma autoridade textual de uma `exata`** — se um relatório afirma algo sobre
   `ascenty-sumare`, a frase precisa refletir essa incerteza (ex.: "na região de..." em vez de "no
   terreno de...").

5. **Ausência de validação de campo.** Nenhum ponto deste dataset foi conferido fisicamente no
   terreno — toda a "verdade" vem de MapBiomas Coleção 9 (anual, com replicação de 2023 para
   2024–2025, já que a Coleção 9 não cobre esses anos — `distancia_safra` de 1–2 nesses anos),
   ESA WorldCover v200 (só 2021, como verificação cruzada) e os 211 polígonos de rotulagem manual
   por imagem de satélite (SV-09/SV-10) — nunca por visita a campo. Nenhuma das três fontes tem uma
   classe "canteiro de obras" nativa: o MapBiomas usa "Área não Vegetada"/"Mineração"/"Afloramento
   Rochoso" como proxy (`config/classes.yml`), o que é uma fonte de ruído estrutural na classe 3
   que nenhum ajuste de modelo elimina sozinho.

6. **Cobertura por bioma é desigual.** Das linhas de teste usadas para medir as métricas acima,
   ~83% vêm de sites em Mata Atlântica (12 dos 16 sites); Caatinga, Cerrado e Amazônia têm 1–2
   sites cada. A F1 da classe 3 melhorou bastante nos biomas novos com a rotulagem manual
   (Caatinga +0.239, Cerrado +0.230 — ver EXP-002), mas a evidência de generalização real (fora dos
   próprios polígonos manuais) é sólida em Caatinga e **ambígua em Cerrado** (só 1 site,
   `everest-goiania` — o ganho agregado pode vir de uma fatia pequena e fácil, não de aprendizado
   amplo do bioma; ver EXP-002, seção "Análise por bioma"). Amazônia tem só 1 site
   (`clickip-manaus`) e a F1 da classe 3 nos pixels automáticos ali continua baixa (0.214).

7. **A série 2013–2025 mistura duas resoluções nativas** (30 m Landsat, 10 m Sentinel-2) — a área
   mínima mapeável de um evento de solo exposto é **9× maior** em pixels Landsat. SV-20
   (`reports/validacao_sensores.md`) separou esse efeito de resolução do efeito de sensor
   propriamente dito: para a classe 3, a resolução sozinha (agregar o próprio Sentinel-2 de 10 m
   para 30 m) explica só uma fração do viés total medido, e vai na direção **oposta** ao viés
   principal (agregar por maioria *reduz* área de uma classe fragmentada) — a maior parte do viés
   (73% em classe 3, 79% em classe 4) sobrevive mesmo comparando as duas classificações na mesma
   resolução. Ou seja, **não é majoritariamente um problema de resolução — é um efeito de sensor**
   que a feature `sensor_landsat` (presente em `rf_v1.0` e mantida em `rf_v1.0-tuned`) não
   neutralizou por completo na classe 3.

8. **Este output mede cobertura do solo, não atribui causa.** "Solo exposto" **não equivale a**
   "desmatamento causado pelo data center". Um pixel classificado como classe 3 num ano qualquer
   pode ter origem em obra do data center, obra de terceiros, atividade agrícola, erosão natural,
   ou erro de classificação (ver itens 1–2). **Atribuição de causalidade está fora do escopo desta
   frente** — este CSV entrega área por classe; a interpretação (isolar o efeito do data center de
   outras mudanças no entorno) é da frente de Indicadores, idealmente usando o grupo de controle
   pareado quando `tipo == "controle"` existir (SV-29, ainda não rodou nesta versão).

---

## Kill-switch — o que fazer se um erro grave for encontrado depois do dashboard já ter consumido os dados

Se, depois deste CSV/GeoJSON já estarem em uso num dashboard ou relatório publicado, alguém
encontrar um erro grave (ex.: contrato de features quebrado, mistura de versões de modelo, bug de
CRS/reprojeção, ou uma classificação claramente errada e sistemática num site):

1. **Avisar a frente de Indicadores IMEDIATAMENTE, antes de corrigir qualquer coisa** — para que a
   visualização afetada possa ser despublicada ou marcada como "sob revisão" enquanto a correção
   não sai. **Nunca corrigir em silêncio** deixando o número errado continuar circulando sem aviso.
2. Registrar o problema (o que estava errado, desde quando, quais `site_id`/`ano`/`sensor` foram
   afetados) — mesmo padrão de registro de qualquer outro experimento/decisão do projeto
   (`CLAUDE.md`: "todo experimento registrado").
3. Corrigir a causa raiz (não só regenerar o CSV) e rodar `export_indicadores` de novo com
   `--modelo-versao` explícito — os artefatos são inteiramente derivados e regeneráveis a partir
   do raster + modelo, então "reverter" é só rodar de novo com a versão anterior do modelo
   (mantenha os `.joblib`/`.sha256` de versões anteriores, não delete).
4. Avisar de novo quando a correção estiver publicada, com o que mudou.

---

## Pendência de validação humana — NÃO marcar como concluído sem isso

O critério de aceite original de SV-15 pede para confirmar, com uma pessoa real da frente de
Indicadores, que ela consegue plotar a área da classe 3 ao longo dos anos para um site **usando só
o CSV e este schema**, e que ela sabe, sem perguntar, onde a série troca de sensor.

**Isso não foi testado nesta execução** — não há acesso a uma pessoa da frente de Indicadores nesta
sessão. Este schema foi revisado internamente como se fosse a primeira leitura de alguém de fora do
ML (mesmo critério já usado em SV-28), mas isso **não substitui** o teste com uma pessoa real.
Registrado aqui como pendência explícita, mesmo padrão já usado em SV-28 — não marcar o critério de
aceite correspondente de SV-15 como concluído até esse teste acontecer de verdade.
