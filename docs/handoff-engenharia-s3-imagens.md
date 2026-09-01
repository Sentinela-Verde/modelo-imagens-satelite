# Handoff Engenharia — replicação da aquisição de imagens de satélite para o S3

- **Autor:** frente de Modelagem/ML · **Data:** 2026-09-01
- **Complementa:** `docs/requisitos-dados-externos.md` (variáveis externas) — este documento cobre
  só a réplica da aquisição de imagens que este repositório já faz, para consolidação no S3.
- **Por que existe:** o trabalho final do grupo precisa de tudo integrado num único lugar. Hoje o
  pipeline de imagens deste repositório roda **local**, direto do Google Earth Engine para o disco
  de quem executa — não existe uma cópia centralizada em nuvem. Este documento especifica
  exatamente o que a Engenharia precisa reproduzir para que a réplica no S3 seja **o mesmo dado**,
  não um dado parecido gerado com outro parâmetro.

## 0. Mapa de arquivos — o que abrir, o que cada um faz, o que portar para o Glue

Antes dos parâmetros técnicos (seções 1-6 abaixo), aqui vai literalmente **qual arquivo abrir** e
**o que fazer com ele**. Todo o código já existe e roda — não precisa reescrever a lógica, só trocar
o destino da escrita (disco local → S3).

| Ordem | Arquivo | Função principal | O que faz | O que portar pro Glue |
|---|---|---|---|---|
| 1 | `src/sentinela/config.py` | `SETTINGS`, `REPO_ROOT` | Lê `config/params.yml` e `config/sites.geojson`, expõe caminhos de saída (`raw_dir`, `interim_dir`, `manifests_dir`) | Os dois YAMLs/GeoJSON viram o "contrato de parâmetros" do job — importar como está, só trocar `raw_dir` etc. para apontar pra um path do tipo `s3://bucket/bronze/...` |
| 2 | `src/sentinela/gee/harmonizacao.py` | `mascara_nuvem()`, `harmonizar_s2()`, `harmonizar_landsat()`, `bandas_harmonizadas()` | O núcleo científico: máscara de nuvem por sensor, conversão de escala, ajuste espectral Sentinel-2→pseudo-OLI | **Portar sem alterar uma linha.** É o módulo mais crítico — qualquer mudança aqui gera um dataset diferente do que este repositório já produziu |
| 3 | `src/sentinela/gee/sentinel2.py` | `processar_site_ano()` | Para 1 site/ano: monta a coleção Sentinel-2 filtrada, aplica máscara+harmonização (chamando o arquivo 2), compõe mediana anual, baixa como int16, grava `.tif` + manifest | Portar `calcular_grade()`, `_colecao_filtrada()`, `_compor_com_retentativa()`, `_preparar_para_download()` como estão; só trocar `_baixar_tif()`/`_finalizar_tif()` para escrever no S3 em vez de `Path` local |
| 4 | `src/sentinela/gee/landsat.py` | `ingerir_site_ano()` | Mesma função que o arquivo 3, só que para Landsat 8/9 (coleções, bandas e resolução diferentes — mesma lógica de máscara/harmonização do arquivo 2) | Mesmo tratamento do arquivo 3: só trocar `_escrever_tif()` para gravar no S3 |
| 5 | `src/sentinela/features/indices.py` | `processar_site_ano()`, `calcular_indices()` | **Roda depois dos arquivos 3/4, 100% local, sem Earth Engine.** Lê o `.tif` de 6 bandas já baixado, calcula os 7 índices espectrais, grava um `.tif` de 13 bandas | Job separado no Glue: le do S3 (Bronze), escreve no S3 (Silver). Não precisa de credencial de Earth Engine, só de leitura/escrita no S3 |
| 6 | `config/sites.geojson` | — | Lista de sites (não é código, é dado) | Compartilhar o arquivo, não redigitar coordenadas |
| 7 | `config/params.yml` | — | Janela sazonal (`mes_inicio: 6, mes_fim: 9` — composto de estação seca, junho-setembro), resolução por sensor, CRS, `seed: 42` | Mesmo — é o contrato de parâmetros, não tem lógica pra portar, só ler |

**Em uma frase:** os arquivos 3 e 4 já fazem "consulta no satélite → tratamento → grava arquivo".
A única mudança real para rodar no Glue é trocar a última função de cada um (a que escreve o
`.tif` em disco) por uma que escreve num bucket S3 — a consulta ao Earth Engine, a máscara de
nuvem, a harmonização entre sensores e o cálculo de índices são os mesmos, porque **precisam** ser
os mesmos (é a réplica, não uma reinterpretação).

## O que este documento NÃO pede

Não pede para reprocessar, reinterpretar ou melhorar nada — pede para **repetir exatamente a
mesma consulta** que este repositório já faz, com os mesmos parâmetros, e pousar o resultado no
S3 em vez de em disco local. Qualquer parâmetro diferente (janela de datas, limiar de nuvem,
banda, resolução) gera um dataset **diferente**, que não seria comparável ao que o restante deste
repositório já produziu e documentou.

**Caminho de menor esforço:** reaproveitar o código-fonte já pronto deste repositório
(`src/sentinela/gee/harmonizacao.py`, `sentinel2.py`, `landsat.py`) apontando a gravação de saída
para um bucket S3 em vez de para `data/raw/` local, em vez de reescrever a lógica do zero. A
Engenharia decide a ferramenta (rodar este código como está, portar para Glue/Spark, etc.) — este
documento só fixa os parâmetros que não podem divergir.

---

## 1. Sites (AOIs)

Fonte: `config/sites.geojson` deste repositório (compartilhar o arquivo, não redigitar). Hoje 16
sites, meta final ~20-25. Cada site tem: `site_id`, `lat`, `lon`, `buffer_km` (sempre 5 km — a
área de interesse é um quadrado/bounds ao redor do ponto, buffer de 5000 m).

## 2. Sentinel-2 (era moderna, 2019-2025)

| Parâmetro | Valor | Por quê esse tratamento |
|---|---|---|
| Coleção | `COPERNICUS/S2_SR_HARMONIZED` | Já vem com correção atmosférica de superfície (L2A) — sem isso, a reflectância mediria a atmosfera, não o solo |
| Bandas brutas usadas | `B2` (blue), `B3` (green), `B4` (red), `B8A` (nir — **não** B8), `B11` (swir1), `B12` (swir2) | `B8A` (855-875nm) é a banda estreita que corresponde ao NIR do Landsat OLI (851-879nm); `B8` (785-900nm) é mais larga e quebraria a harmonização da seção 4 |
| Máscara de nuvem | Cloud Score+ (`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`), linkada por `system:index`, mantém pixel só se `cs_cdf >= 0.60` | Nuvem e sombra têm reflectância completamente diferente do solo — sem mascarar, um pixel de nuvem entraria na mediana anual como se fosse vegetação/solo, contaminando o resultado |
| Composição | Mediana anual dentro de uma janela sazonal (`mes_inicio: 6, mes_fim: 9` em `config/params.yml` — estação seca, junho-setembro; se a coleção retornar poucas imagens na janela, o pipeline expande ±1 mês automaticamente — ver `sentinel2.py::_colecao_filtrada` / `_compor_com_retentativa`) | Mediana (não média) é resistente a nuvem residual que passou da máscara; janela de estação seca reduz nebulosidade de base, antes mesmo da máscara agir |
| Resolução nativa | 10 m | — |
| Escala de reflectância | `B* / 10000` → reflectância float [0, 1] | Sentinel-2 L2A entrega valores inteiros ×10000 por convenção do produto — sem essa divisão, os valores não são reflectância de verdade |

## 3. Landsat 8/9 (era antiga, 2013-2018)

| Parâmetro | Valor | Por quê esse tratamento |
|---|---|---|
| Coleções | `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2` | Sentinel-2 não tem cobertura densa/confiável no Brasil antes de 2019 — por isso a era 2013-2018 usa Landsat |
| Bandas brutas usadas | `SR_B2` (blue), `SR_B3` (green), `SR_B4` (red), `SR_B5` (nir), `SR_B6` (swir1), `SR_B7` (swir2) | Correspondência física com as bandas do Sentinel-2 escolhidas acima — ver tabela de harmonização, seção 4 |
| Máscara de nuvem/saturação | Bitmask de `QA_PIXEL` (dilated cloud=bit1, cirrus=bit2, cloud=bit3, cloud shadow=bit4, todos zerados) **+** `QA_RADSAT` (remove pixel com qualquer banda saturada) | Mesmo motivo do Sentinel-2 (não contaminar a mediana com nuvem/sombra); `QA_RADSAT` também remove pixel saturado (ex.: reflexo de telhado metálico), que mediria um valor fisicamente impossível |
| Escala de reflectância | `SR_B* * 0.0000275 - 0.2` (fator oficial USGS Collection 2 Level-2) → reflectância float [0, 1] | Fator oficial do produto Landsat C2 L2 — sem essa conversão, os valores brutos não são reflectância |
| Resolução nativa | 30 m | 3× mais grosseira que Sentinel-2 — é por isso que a grade da seção 6 usa 30 m como múltiplo comum entre as duas eras |

## 4. Harmonização entre sensores (obrigatória — não pousar Landsat e Sentinel-2 sem isso)

Landsat é a referência (sem ajuste espectral, só conversão de escala). Sentinel-2 recebe um ajuste
linear por banda (`pseudo_OLI = slope * MSI + offset`) para aproximar sua reflectância da
reflectância equivalente do Landsat OLI, usando os coeficientes publicados pela NASA para o
produto HLS (Claverie et al.):

| Banda | slope | offset |
|---|---|---|
| blue | 0.9778 | -0.0040 |
| green | 1.0053 | -0.0009 |
| red | 0.9765 | 0.0009 |
| nir | 0.9983 | -0.0001 |
| swir1 | 0.9987 | -0.0011 |
| swir2 | 1.0030 | -0.0012 |

Resultado: **6 bandas canônicas** finais, sempre com estes nomes e nesta ordem — `blue, green,
red, nir, swir1, swir2` — em reflectância float [0, 1], independente do sensor de origem. Nenhuma
etapa posterior deste repositório lê banda nativa (`B2`, `SR_B4`, etc.) diretamente — só esses 6
nomes. A réplica no S3 deve preservar esse contrato.

## 5. Índices espectrais derivados (7, calculados sobre as 6 bandas harmonizadas)

Calculados por `src/sentinela/features/indices.py` (`calcular_indices()`), **localmente, sem
Earth Engine**, a partir do `.tif` de 6 bandas já baixado — é um segundo job, não parte da
ingestão:

| Índice | Fórmula | Serve para |
|---|---|---|
| NDVI | `(nir - red) / (nir + red)` | Vegetação em geral |
| EVI | `2.5 * (nir - red) / (nir + 6*red - 7.5*blue + 1)` | Vegetação, satura menos que NDVI em área densa |
| NDWI | `(green - nir) / (green + nir)` | Água |
| MNDWI | `(green - swir1) / (green + swir1)` | Água, mais robusto que NDWI em área urbana |
| NDBI | `(swir1 - nir) / (swir1 + nir)` | Área construída |
| BSI | `((swir1+red)-(nir+blue)) / ((swir1+red)+(nir+blue))` | Solo exposto — o índice mais importante do projeto |
| NDMI | `(nir - swir1) / (nir + swir1)` | Umidade da vegetação, separa vegetação rala de solo exposto |

Todo denominador com `\|valor\| < 1e-6` vira `0.0` (nunca `NaN`/`inf`) e o pixel entra na máscara de
inválidos — ver `_dividir_seguro()`. Junto das 6 bandas harmonizadas, somam as **13 features** que
alimentam o classificador — nem mais, nem menos (contrato também documentado em
`docs/contrato-dados-externos.yml`, papel A).

## 6. Grade espacial determinística (crítico para alinhamento pixel a pixel)

Cada site tem uma grade própria, calculada por uma fórmula fixa a partir do centro
(lon, lat) e do buffer — origem = ponto truncado para baixo/cima na resolução do sensor, largura e
altura arredondadas para múltiplo da resolução. **Se a Engenharia recalcular essa grade com uma
fórmula diferente, os pixels da réplica no S3 não vão alinhar com os rasters que este repositório
já produziu localmente**, inviabilizando qualquer comparação futura entre as duas cópias. Por isso
a recomendação de reaproveitar `calcular_grade()` de `src/sentinela/gee/landsat.py` /
`sentinel2.py` diretamente, em vez de reimplementar.

---

## 7. Camadas sugeridas no S3

Usando a arquitetura Bronze/Silver/Gold já endossada em `docs/requisitos-dados-externos.md` (seção
8, proposta original do Fabio):

| Camada | Conteúdo | Equivalente local hoje |
|---|---|---|
| **Bronze** | GeoTIFFs brutos por sensor/site/ano, já com máscara de nuvem aplicada, antes da harmonização | `data/raw/` (gitignored, só existe na máquina de quem roda) |
| **Silver** | Stack de 13 features (6 bandas harmonizadas + 7 índices) por site/ano | `data/interim/features/` (gitignored) |
| **Gold** | Rasters classificados (5 classes), `outputs/indicadores/area_por_classe.csv`, perfil pré/durante/pós, labels manuais (GeoJSON) | `data/processed/classificado/`, `outputs/`, `data/labels_manual/` (labels manuais e manifests já são versionados no git — ver seção 8) |

## 8. Como validar que a réplica bateu com o original

Este repositório já gera manifests com hash sha256 e parâmetros completos em
`data/manifests/` para cada execução (ingestão e dataset). Comparar esses manifests com os
metadados da réplica no S3 é a forma de confirmar que os dois lados produziram o mesmo dado, em
vez de confiar só em inspeção visual das imagens.

## 9. O que este repositório entrega para viabilizar a réplica

- `config/sites.geojson` — lista completa de sites com coordenadas
- Código-fonte de ingestão/harmonização (`src/sentinela/gee/`) — reaproveitável diretamente
- `docs/decisoes/ADR-001-aoi-e-janela-temporal.md`, `ADR-003-harmonizacao-multissensor.md` — o
  raciocínio completo por trás de cada parâmetro acima, para quem quiser entender o porquê, não só
  o valor
- `data/manifests/` — como verificar que a réplica bateu

## 10. O que este repositório não vai fazer

Não vai subir nada no S3, gerenciar credenciais AWS, nem migrar o pipeline para Glue/Spark — isso
é decisão e execução da Engenharia. Este documento fixa **o que não pode divergir** (parâmetros de
consulta e grade espacial); a ferramenta de execução é escolha livre deles.

## 11. Prazo

Esta réplica **não bloqueia** a entrega deste repositório em 14/09/2026 — o pipeline local continua
rodando independente do S3. É uma integração paralela, para consolidar tudo antes da apresentação
final do trabalho.
