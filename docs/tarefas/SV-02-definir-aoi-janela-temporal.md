# SV-02 — Definir AOI (sites) e janela temporal multi-sensor

- **Fase:** 0 — Destravar · **Data-alvo:** 27/08 · **Tamanho:** M (~1h30)
- **Responsável sugerido:** **humano** (é decisão de escopo) — `data-engineer` executa a parte de arquivo
- **Bloqueado por:** — (nada)
- **Desbloqueia:** SV-02b, SV-06, SV-06b, SV-07
- **Tem seção de risco:** não

> **Revisada em 2026-08-27** após decisão do usuário: *"se cobrir 2016 ou até anterior o projeto
> fica melhor? quero que seja o melhor, nem se precisarmos de outras fontes"*. A versão anterior
> desta tarefa cortava a série em 2019 por conveniência de sensor único. Isso foi revertido.

## Contexto

O `CLAUDE.md` fecha *o que* classificar (5 classes) e *de onde* vêm os labels, mas **não diz quais
data centers nem quais anos**. Sem isso, a ingestão não tem o que baixar.

A decisão do usuário é maximizar a cobertura temporal defensável, aceitando o custo de usar mais de
um sensor. Isso muda a natureza do projeto: deixa de ser "classificar imagens Sentinel-2" e passa a
ser **"construir uma série temporal harmonizada multi-sensor e classificá-la"** — que é mais difícil,
mais valioso e muito mais interessante para a banca, desde que o trade-off seja medido e documentado
em vez de varrido para debaixo do tapete.

## Objetivo

Fixar, em arquivo versionado, quais áreas e quais anos entram na V1, com qual sensor cada faixa de
anos será coberta — e registrar o porquê, incluindo o que foi descartado.

## O que o acervo permite (levantamento, leia antes de decidir)

| Sensor | Cobertura | Resolução | Situação para este projeto |
|---|---|---|---|
| Sentinel-2 L2A (`COPERNICUS/S2_SR_HARMONIZED`) | 2017-03 →, densa a partir de 2019 | 10 m | Melhor qualidade. Base da série moderna |
| Landsat 9 (`LANDSAT/LC09/C02/T1_L2`) | 2021-10 → | 30 m | Complementa L8, dobra a revisita |
| Landsat 8 (`LANDSAT/LC08/C02/T1_L2`) | 2013-03 → | 30 m | **Ponte sólida para 2013–2018.** Bem cross-calibrado com S2 |
| Landsat 7 (`LANDSAT/LE07/C02/T1_L2`) | 1999 → 2022 | 30 m | **SLC-off desde mai/2003**: ~22% de faixas vazias por cena |
| Landsat 5 (`LANDSAT/LT05/C02/T1_L2`) | 1984 → imageamento encerrado nov/2011 | 30 m | Bom até 2011, mas radiometria TM exige segunda harmonização |

**O buraco de 2012 é real e não tem solução**: o L5 parou de imagear em nov/2011 e o L8 só entrou em
operação em abr/2013. 2012 só tem Landsat 7 SLC-off. Qualquer série que atravesse 2012 tem esse ano
como elo fraco, e isso precisa estar escrito no relatório final.

## Proposta a validar (aceite ou ajuste, mas decida hoje)

**Sites (3, inalterados):** buffer de **5 km**, conforme já proposto e aceito.
1. **Ascenty Vinhedo (SP)** · 2. **Odata / Hortolândia (SP)** · 3. **Scala / Tamboré, Barueri (SP)**

**Janela temporal em duas faixas:**

- **Faixa A — núcleo obrigatório da V1: 2013–2025 (13 anos), composto anual.**
  Landsat 8/9 para 2013–2018, Sentinel-2 para 2019–2025, mais **Landsat 8 também em 2019–2021**
  (faixa de sobreposição, necessária para SV-20 medir o viés entre sensores).
  Dois sensores modernos, ambos com as 6 bandas comparáveis (azul, verde, vermelho, NIR, SWIR1,
  SWIR2), com coeficientes de cross-calibração publicados. É a série mais longa que dá para
  defender com rigor em duas sprints.

- **Faixa B — contexto de longo prazo, opcional: 2000–2011 (Landsat 5/7).**
  **Não entra na V1.** Entra se, e somente se, SV-02b mostrar que a harmonização TM→OLI fica
  dentro de tolerância aceitável, **e** SV-05b adotar uma fonte de label anual que cubra o período
  (o WorldCover não cobre — ver abaixo). Trate como Plus com prioridade alta.

**Por que 2013 e não 2016:** 2016 não é um marco de sensor nenhum — cair em 2016 exigiria Landsat 8
de qualquer forma (o S2 não serve para 2016–2018 com L2A confiável). Se já vamos pagar o custo de
harmonizar com Landsat 8, **2013 sai de graça**: é o mesmo sensor, o mesmo código, o mesmo
tratamento. Cortar em 2016 seria pagar o preço inteiro da complexidade e levar 3 anos a menos.

**Por que a Faixa B não é automática:** as construções dos três data centers são todas posteriores
a ~2013. Voltar a 2000 não adiciona sinal sobre o data center — adiciona **contexto regional**
(a região já vinha se urbanizando a que ritmo? o sítio desviou desse ritmo?). É valioso, mas é um
segundo argumento, não o principal. Custa uma harmonização a mais, o buraco de 2012 e uma fonte de
label que cubra 2000.

**Acoplamento que você precisa enxergar agora:** estender a série agrava o problema do label. O ESA
WorldCover é safra fixa ~2021; aplicá-lo a 2013 significa um label com 8 anos de defasagem. Por isso
existe **SV-05b**, que avalia o MapBiomas (anual, 30 m, cobre 1985–2023, específico para o Brasil)
como fonte de label. **Se a Faixa B for desejada, SV-05b deixa de ser opcional e vira pré-requisito.**

**CRS:** config em `EPSG:4326`; processamento e área em **`EPSG:31983`** (SIRGAS 2000 / UTM 23S).

**Resolução:** cada sensor é processado e classificado em sua **resolução nativa** (30 m Landsat,
10 m Sentinel-2). Não reamostrar Landsat para 10 m — isso inventa precisão que não existe. A
comparabilidade da série vem da harmonização **espectral** (SV-02b) e da métrica de área em m²,
que é independente de resolução, com o viés medido em SV-20.

## Escopo — o que fazer

1. Confirmar (ou ajustar) os 3 sites, a Faixa A e a posição sobre a Faixa B.
2. Criar `config/sites.geojson` (EPSG:4326), um Feature por site, propriedades:
   `site_id` (slug, ex. `ascenty-vinhedo`), `nome`, `operador`, `municipio`, `uf`, `lat`, `lon`,
   `buffer_km`, `fonte_coordenada` (URL verificável), `ano_inicio_operacao_estimado` (se conhecido —
   ajuda a interpretar a série), `ativo` (bool).
3. Criar `config/params.yml` com:
   ```yaml
   faixa_a:
     anos: [2013..2025]
     sensor_por_ano: {2013..2018: landsat, 2019..2025: sentinel2}
     anos_sobreposicao: [2019, 2020, 2021]   # ingeridos nos DOIS sensores, para SV-20
   faixa_b:
     habilitada: false
     anos: [2000..2011]
   mes_inicio: 6
   mes_fim: 9
   crs_analise: EPSG:31983
   resolucao_m: {sentinel2: 10, landsat: 30}
   seed: 42
   ```
4. Criar `docs/decisoes/ADR-001-aoi-e-janela-temporal.md` registrando: a decisão, o levantamento de
   acervo acima, as alternativas descartadas (S2-only 2019–2025; corte em 2016; Faixa B na V1) com o
   motivo de cada uma, e o buraco de 2012 declarado explicitamente.

## Fora de escopo

- Decidir *como* harmonizar os sensores (SV-02b).
- Decidir a fonte de label (SV-05b).
- Baixar qualquer imagem (SV-06, SV-06b).

## Critérios de aceite

- [ ] `config/sites.geojson` abre em `geopandas` sem erro e tem 3 features, CRS EPSG:4326.
- [ ] Todo `site_id` é slug minúsculo, sem espaço, único.
- [ ] Toda coordenada tem `fonte_coordenada` verificável — nada "de memória".
- [ ] Plotando os pontos sobre imagem de satélite, cada um cai **em cima** da instalação.
- [ ] `config/params.yml` carrega via `yaml.safe_load`; anos são inteiros; a faixa de sobreposição
      está contida na Faixa A.
- [ ] `ADR-001` existe e responde, por escrito: por que 2013, por que não 2016, por que a Faixa B
      ficou fora da V1, e o que acontece em 2012.
- [ ] A posição sobre a Faixa B está registrada como decisão (habilitada ou não), não em aberto.

## Cenários de teste

1. `geopandas.read_file("config/sites.geojson").crs` → EPSG:4326.
2. Buffer de 5 km em EPSG:31983 sobre cada ponto → polígono de ≈ 78,5 km².
3. Os 3 buffers não se sobrepõem (senão haveria vazamento espacial entre sites em SV-11); se
   sobrepuserem, reduza o buffer ou trate os sites sobrepostos como um único grupo de split.
4. `sensor_por_ano` cobre todo ano da Faixa A, sem lacuna e sem ambiguidade.
5. Para cada ano de sobreposição existe entrada nos dois sensores.

## Como reportar

Informe: os 3 sites com coordenadas e fontes, a janela final aprovada, a posição sobre a Faixa B,
e se algo mudou em relação à proposta (e por quê).
