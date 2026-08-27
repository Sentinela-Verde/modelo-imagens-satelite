# ADR-002 — Contrato de output com a frente de Indicadores (etapa 05)

- **Status:** **Aceito** — schema default abaixo vale, sem contraproposta do time
- **Proposto em:** 2026-08-27
- **Resposta em:** 2026-08-27 — a frente de Indicadores respondeu que **ainda não tem indicadores
  estabelecidos** e que a frente de Modelagem pode definir a base ("podemos pegar de base o que o
  PM achar melhor")
- **Decisor:** usuário (owner da frente de Modelagem) ↔ responsável pela etapa 05 – Indicadores

## Mensagem a enviar

> Proposta de contrato de output da frente de Modelagem para a etapa de Indicadores — objete até
> **29/08**, senão seguimos com isto:
>
> **1. `outputs/indicadores/area_por_classe.csv`** — uma linha por site/ano/sensor/classe:
>
> | coluna | tipo | exemplo |
> |---|---|---|
> | `site_id` | string | `ascenty-vinhedo` |
> | `ano` | int | `2023` |
> | `sensor` | string | `sentinel2` \| `landsat` |
> | `resolucao_m` | int | `10` |
> | `classe_id` | int (1–5) | `3` |
> | `classe_nome` | string | `solo_exposto_obras` |
> | `area_m2` | float | `412300.0` |
> | `area_ha` | float | `41.23` |
> | `pct_area_valida` | float (0–100) | `5.21` |
> | `pixels_validos` | int | `987654` |
> | `fator_correcao_sensor` | float | `1.0` |
> | `modelo_versao` | string | `rf_v1.0` |
> | `gerado_em` | ISO 8601 | `2026-09-04T14:00:00-03:00` |
>
> **Importante:** a série vai de **2013 a 2025** usando **dois satélites** — Landsat (30 m) até
> 2018, Sentinel-2 (10 m) de 2019 em diante. Por isso existem as colunas `sensor`/`resolucao_m` —
> um gráfico que ignore essa troca pode mostrar um "degrau" em 2019 que é do instrumento, não do
> terreno (isso está sendo medido à parte, tarefa SV-20).
>
> **2. `outputs/indicadores/classes_{site_id}_{ano}.geojson`** — polígonos vetorizados por classe,
> EPSG:4326.
>
> **3. `data/processed/classificado/{site_id}/{ano}.tif`** — raster uint8 (1–5, nodata=0),
> EPSG:31983, 10 m, para quem quiser reprocessar.
>
> Convenção de classes fixa: `1` vegetação_densa · `2` vegetação_rala · `3` solo_exposto_obras ·
> `4` construída_urbana · `5` água · `0` nodata.
>
> Quatro perguntas:
> 1. CSV serve, ou vocês precisam de banco/API?
> 2. Precisam do GeoJSON de polígonos, ou a tabela de área já basta?
> 3. Precisam de granularidade menor que site/ano (ex.: trimestre, ou por anel de distância do data center)?
> 4. **O dashboard consegue marcar visualmente a troca de sensor em 2019?** Se não conseguir, é
>    melhor saber agora do que na apresentação final.

## Resposta recebida

A frente de Indicadores (etapa 05) respondeu que **não tem indicadores estabelecidos ainda** e que
pode partir do que a frente de Modelagem definir. Nenhuma mudança de coluna/formato foi pedida — o
schema proposto (seção acima) vale como está.

**Isso muda o peso da decisão:** não é mais "nosso contrato interno até alguém objetar" — na
ausência de outra definição, este schema **é** a definição de indicador do projeto. Duas
consequências práticas para quem for implementar SV-15:

- `area_por_classe.csv` deixa de ser só "insumo pro dashboard" e passa a ser, de fato, a fonte dos
  KPIs do Sentinela Verde (% perda/ganho de vegetação, variação de área construída etc. — ver
  Briefing do projeto, seção 8.3). Vale a pena revisar se as colunas já cobrem esses KPIs
  diretamente ou se falta alguma agregação.
- A pergunta sobre marcar a troca de sensor em 2019 no dashboard **continua sem resposta** — sem
  indicadores prévios, é ainda mais importante que a própria frente de Modelagem trate isso na
  visualização que entregar (SV-15/SV-17), já que não há garantia de que o dashboard final vá
  fazer essa distinção sozinho.

## Efeito em SV-15

Sem bloqueio: SV-15 implementa o schema default acima, sem alteração pendente.
