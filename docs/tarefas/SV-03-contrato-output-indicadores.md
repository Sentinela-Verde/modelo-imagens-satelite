# SV-03 — Alinhar contrato de output com a frente de Indicadores

- **Fase:** 0 — Destravar · **Data-alvo:** 27/08 · **Tamanho:** P (~30min de trabalho, assíncrono na resposta)
- **Responsável sugerido:** **humano** (é conversa entre frentes)
- **Bloqueado por:** — (nada)
- **Desbloqueia:** SV-15 (de forma **não bloqueante** — SV-15 segue com o default)
- **Tem seção de risco:** não
- **Tipo:** **DEPENDÊNCIA EXTERNA — isolada de propósito**

## Contexto

A saída desta frente alimenta a etapa **05 – Indicadores** do Sentinela Verde, que por sua vez
alimenta o dashboard final do grupo. O `CLAUDE.md` diz que mudança de formato de output precisa
ser sinalizada **antes** de implementar. Só que esperar resposta trava a V1 — então a estratégia
é: **propor um schema, pedir objeção (não aprovação), e seguir**.

## Objetivo

Ter, por escrito, o formato que a frente de Indicadores consegue consumir — ou a confirmação
de que a proposta abaixo serve.

## Proposta a enviar (formato "objete até <data>, senão vale isto")

Três artefatos por site/ano:

**1. `outputs/indicadores/area_por_classe.csv`** — a tabela principal, uma linha por site/ano/sensor/classe:

| coluna | tipo | exemplo |
|---|---|---|
| `site_id` | string | `ascenty-vinhedo` |
| `ano` | int | `2023` |
| `sensor` | string | `sentinel2` \| `landsat` |
| `resolucao_m` | int | `10` |
| `classe_id` | int (1–5) | `3` |
| `classe_nome` | string | `solo_exposto_obras` |
| `area_m2` | float | `412300.0` |
| `area_ha` | float | `41.23` |
| `pct_area_valida` | float (0–100) | `5.21` |
| `pixels_validos` | int | `987654` |
| `fator_correcao_sensor` | float | `1.0` |
| `modelo_versao` | string | `rf_v1.0` |
| `gerado_em` | ISO 8601 | `2026-09-04T14:00:00-03:00` |

> **Ponto que precisa ficar claro na conversa com a frente 05:** a série vai de **2013 a 2025** e usa
> **dois satélites** — Landsat (30 m) até 2018, Sentinel-2 (10 m) de 2019 em diante. Por isso as
> colunas `sensor` e `resolucao_m` existem, e por isso um gráfico que ignore essa troca pode mostrar
> um degrau em 2019 que é do instrumento, não do terreno. A magnitude desse efeito está medida em
> SV-20. **Pergunte se eles conseguem marcar a transição no gráfico do dashboard** — se não
> conseguirem, é melhor saber agora.

**2. `outputs/indicadores/classes_{site_id}_{ano}.geojson`** — polígonos vetorizados por classe,
EPSG:4326, propriedades `site_id`, `ano`, `classe_id`, `classe_nome`, `area_m2`.

**3. `data/processed/classificado/{site_id}/{ano}.tif`** — raster uint8, valores 1–5,
`nodata = 0`, CRS EPSG:31983, 10 m. Para quem quiser reprocessar por conta própria.

**Convenção de classes** (fixa, vem do `CLAUDE.md`):
`1` vegetação_densa · `2` vegetacao_rala · `3` solo_exposto_obras · `4` construida_urbana · `5` agua · `0` nodata

## Escopo — o que fazer

1. Identificar quem cuida da etapa 05 – Indicadores no time.
2. Mandar a proposta acima com um prazo curto de objeção (ex.: 48h) e quatro perguntas fechadas:
   - CSV serve, ou precisa de banco/API?
   - Precisam do GeoJSON de polígonos, ou a tabela de área basta?
   - Precisam de granularidade menor que site/ano (ex.: por trimestre, ou por anel de distância do data center)?
   - **O dashboard consegue marcar visualmente a troca de sensor em 2019?** (ver nota acima)
3. Registrar a resposta (ou o silêncio) em `docs/decisoes/ADR-002-contrato-indicadores.md`.

## Fora de escopo

- Implementar o export (isso é SV-15).
- Esperar a resposta para começar SV-15.

## Critérios de aceite

- [ ] Proposta enviada, com prazo de objeção explícito e data registrada.
- [ ] `docs/decisoes/ADR-002-contrato-indicadores.md` criado, mesmo que o conteúdo seja
      "proposto em DD/MM, sem objeção até DD/MM, vale o default".
- [ ] Se houve resposta com mudança: a mudança está escrita no ADR em formato de tabela de colunas,
      não em prosa de mensagem de chat.

## Como reportar

Informe: com quem falou, o que foi respondido, e se o schema default mudou. Se mudou, avise
explicitamente quem estiver tocando SV-15.
