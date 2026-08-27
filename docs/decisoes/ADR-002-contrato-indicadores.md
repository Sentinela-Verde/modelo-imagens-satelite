# ADR-002 — Contrato de output com a frente de Indicadores (etapa 05)

- **Status:** Proposto — aguardando objeção
- **Proposto em:** 2026-08-27
- **Prazo de objeção:** 2026-08-29 (48h) — sem resposta até lá, vale o default abaixo
- **Decisor:** usuário (owner da frente de Modelagem) ↔ responsável pela etapa 05 – Indicadores

> **AÇÃO PENDENTE (humana):** esta proposta ainda não foi enviada. Copie a seção "Mensagem a
> enviar" abaixo e mande para quem cuida da etapa 05 – Indicadores no time. Depois, atualize o
> "Status" acima e, se a resposta mudar algo, preencha "Resposta recebida" com a tabela de colunas
> final (não em prosa).

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

_(preencher depois que houver resposta — ou registrar "sem objeção até 29/08/2026, vale o default
acima" se ninguém responder)_

## Efeito em SV-15

Esta dependência é **não bloqueante**: SV-15 (implementação do export) segue com o schema default
acima independente de resposta. Se a resposta mudar alguma coluna/formato, atualize esta seção e
avise explicitamente quem estiver tocando SV-15 antes de a tarefa ser dada como concluída.
