# SV-15 — Output para a frente de Indicadores

- **Fase:** 4 — Output e Plus · **Data-alvo:** 08/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-14 · **Desejável (não bloqueante):** SV-03, SV-20
- **Desbloqueia:** SV-17, SV-19, SV-18
- **Tem seção de risco:** SIM (o output alimenta afirmação sobre impacto ambiental de empresa real)

> **Revisada em 2026-08-27**: o CSV ganha `sensor` e `resolucao_m`, e uma seção sobre
> comparabilidade entre eras, por causa da série multi-sensor de SV-02.

## Contexto

Item 6 da Definition of Done e o **único ponto de contato desta frente com o resto do time**. A etapa
05 – Indicadores consome isto e alimenta o dashboard final.

Se SV-03 trouxe resposta da frente de Indicadores, use o schema acordado
(`docs/decisoes/ADR-002-contrato-indicadores.md`). **Se não trouxe, implemente o default abaixo e
marque como PROVISÓRIO** — não espere.

## Objetivo

Artefatos estáveis, documentados e regeneráveis com um comando, que a frente de Indicadores use sem
precisar entender nada de machine learning — **e sem cair na armadilha de comparar 2015 com 2023 como
se tivessem a mesma precisão.**

## Escopo — o que fazer

1. **`src/sentinela/export_indicadores.py`**, CLI:
   `python -m sentinela.export_indicadores --modelo-versao rf_v0.1`

2. **Artefato 1 — `outputs/indicadores/area_por_classe.csv`**, uma linha por site × ano × classe:
   `site_id, ano, sensor, resolucao_m, classe_id, classe_nome, area_m2, area_ha, pct_area_valida,`
   `pixels_validos, fator_correcao_sensor, modelo_versao, gerado_em`
   - **`sensor` e `resolucao_m` são obrigatórios em toda linha.** Sem eles, quem consome vai plotar
     13 anos numa linha só e atribuir ao terreno um degrau que é do satélite. Esta coluna é a
     diferença entre um gráfico honesto e um gráfico enganoso.
   - `fator_correcao_sensor`: `1.0` se SV-20 concluiu que não há correção a aplicar; o fator aplicado
     se houver. Nunca aplicar correção sem registrar o valor na própria linha.
   - Área calculada em **EPSG:31983** (100 m²/pixel no S2, 900 m²/pixel no Landsat). Não calcule área
     em graus.
   - `pct_area_valida` é sobre pixels válidos, não sobre a área total do buffer — senão o nodata vira
     "classe fantasma" nos gráficos.
   - Toda combinação site × ano × classe presente, inclusive com `area_m2 = 0`. Ausência de linha
     obriga quem consome a adivinhar; zero explícito não.
   - **Anos de sobreposição:** emitir as linhas dos dois sensores, distinguíveis pela coluna `sensor`,
     e explicar no schema qual usar como série oficial (recomendação: Sentinel-2, com o Landsat
     disponível para verificação).

3. **Artefato 2 — `outputs/indicadores/classes_{site_id}_{ano}_{sensor}.geojson`:** polígonos
   vetorizados por classe (`rasterio.features.shapes` + dissolve por classe), **EPSG:4326**,
   propriedades `site_id, ano, sensor, resolucao_m, classe_id, classe_nome, area_m2`.
   Descartar polígonos < 0.1 ha e **registrar quanta área foi descartada** — note que esse corte
   remove proporcionalmente mais no Landsat, onde um polígono de 0.1 ha é apenas um pixel.

4. **Artefato 3:** os rasters de SV-14, em `data/processed/classificado/` — referenciá-los e
   documentar como regenerá-los (são gitignored).

5. **`docs/schema-indicadores.md`** (commitado) — a documentação que a outra frente vai ler:
   dicionário de colunas com tipo e unidade, convenção de classes (1–5 + 0 nodata), CRS de cada
   artefato, como regenerar, **status do contrato** (`ACORDADO com <nome> em <data>` ou `PROVISÓRIO`),
   e duas seções obrigatórias:
   - **"Como plotar a série sem mentir"** — instrução explícita de que 2013–2018 e 2019–2025 vêm de
     sensores diferentes, qual a diferença medida em SV-20, e a recomendação de marcar a transição no
     gráfico em vez de escondê-la.
   - **"Limitações que quem consome precisa saber"** (ver riscos).

6. **Determinismo:** o comando é idempotente; dois runs produzem CSV idêntico exceto `gerado_em`.

## Fora de escopo

- Calcular indicadores derivados (taxa de desmatamento, alerta, índice composto) — é a **frente 05**.
  Entregue área por classe; deixe a interpretação com quem é dono dela.
- Dashboard/visualização.
- Medir o viés entre sensores (SV-20) — aqui só se consome o resultado.
- Publicar em banco ou API (a demo é SV-19, e ela lê estes mesmos artefatos).

## Critérios de aceite

- [ ] `area_por_classe.csv` existe, com uma linha por site × ano × sensor × classe, sem lacuna.
- [ ] Para cada site × ano × sensor, a soma de `pct_area_valida` das 5 classes = 100 (± 0.01).
- [ ] `area_ha == area_m2 / 10000` em toda linha.
- [ ] `pixels_validos × (resolucao_m²)` == soma de `area_m2` do grupo — a checagem de coerência agora
      depende da resolução, e é justamente por isso que a coluna existe.
- [ ] `sensor` e `resolucao_m` preenchidos em 100% das linhas.
- [ ] GeoJSON abre no QGIS e no geojson.io, em EPSG:4326, sobre o local certo.
- [ ] `docs/schema-indicadores.md` completo, com status do contrato e a seção "Como plotar a série
      sem mentir".
- [ ] Uma pessoa da frente de Indicadores consegue plotar a área da classe 3 ao longo dos anos para
      um site **usando só o CSV e o schema**, e sabe, sem perguntar, onde a série troca de sensor.
      **Teste isso com ela de verdade.**
- [ ] Nada em `outputs/` entrou no git.

## Cenários de teste

1. **Soma:** percentuais fecham em 100 por site × ano × sensor.
2. **Unidades:** conversão m²↔ha correta; área total ≈ área do buffer de 5 km (≈ 7.850 ha) menos nodata.
3. **Coerência de resolução:** a checagem de `pixels_validos × resolução²` passa nas duas eras.
4. **Geografia:** `crs == EPSG:4326` e o centroide cai no município declarado em `config/sites.geojson`.
5. **Série temporal:** plotar `area_ha` da classe 3 por ano para um site — a curva deve ser
   interpretável. Serrilhado forte sugere instabilidade do modelo entre anos, e isso vai para as
   limitações.
6. **Sobreposição:** nos anos de sobreposição, as duas linhas de sensor existem e a diferença entre
   elas é compatível com o que SV-20 mediu.
7. **Idempotência:** dois runs → CSV idêntico exceto `gerado_em`.

## Riscos e mitigação

| Risco | Severidade | Mitigação |
|---|---|---|
| Estes números viram afirmação pública sobre impacto ambiental de **empresas reais** (Ascenty, Odata, Scala) num trabalho que pode ser apresentado ou publicado | **Alta** — erro de classificação vira acusação factualmente errada sobre empresa nomeada | `docs/schema-indicadores.md` **precisa** trazer em destaque: fonte e safra do label, F1 real da classe 3 (o número de SV-13, não uma estimativa otimista), 3 sites de uma única região, ausência de validação de campo, e a troca de sensor em 2019. Nenhum artefato sai sem `modelo_versao` |
| **Degrau de sensor lido como mudança ambiental** — o risco novo e mais provável deste conjunto de dados, porque a troca de sensor coincide com o período de construção | **Alta** | Colunas `sensor`/`resolucao_m`/`fator_correcao_sensor` em toda linha; seção "Como plotar a série sem mentir"; o número medido em SV-20 citado no schema |
| Frente de Indicadores usa versão antiga do CSV sem perceber (após SV-16 re-treinar) | Média | `modelo_versao` e `gerado_em` em **toda linha**, não só no nome do arquivo; avisar a frente 05 quando a versão mudar |
| "Solo exposto" lido como "desmatamento causado pelo data center" — correlação virando causalidade | Média | Nota explícita: o modelo mede **cobertura do solo**, não atribui causa. Atribuição de causalidade não está no escopo desta frente |

**Rollback:** os artefatos são derivados e regeneráveis a partir do raster + modelo. Reverter é rodar
o comando com o `--modelo-versao` anterior. Mantenha os joblib das versões anteriores.

**Kill-switch:** se um erro grave for descoberto depois de o dashboard consumir os dados, avisar a
frente 05 **antes** de corrigir, para que a visualização seja despublicada enquanto isso — não
corrigir em silêncio deixando o número errado circular. Deixe o procedimento escrito no schema.

## Como reportar

Informe: amostra de linhas do CSV, o status do contrato (acordado ou provisório, com quem/quando), o
que SV-20 determinou sobre correção entre sensores e como isso aparece no arquivo, o resultado do
teste com a pessoa da frente de Indicadores, e a lista de limitações escrita no schema.
