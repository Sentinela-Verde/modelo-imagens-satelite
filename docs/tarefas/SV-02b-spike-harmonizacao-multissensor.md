# SV-02b — Spike: harmonização Landsat ↔ Sentinel-2

- **Fase:** 1 — Dados · **Data-alvo:** 30/08 · **Tamanho:** M (~3h, **timeboxed** — ver regra de parada)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-02 (AOI e faixas), SV-04 (auth EE)
- **Desbloqueia:** SV-06, SV-06b, SV-08
- **Tem seção de risco:** não
- **Tipo:** **SPIKE** — a entrega é uma decisão medida + código de referência, não um pipeline pronto

## Contexto

SV-02 decidiu cobrir 2013–2025 com dois sensores. Landsat 8/9 (30 m) e Sentinel-2 (10 m) medem a
mesma coisa de formas ligeiramente diferentes: bandas com larguras e centros diferentes, correção
atmosférica de cadeias diferentes, escalas de reflectância diferentes. Jogar os dois no mesmo modelo
sem tratar isso produz um classificador que aprende **a diferença entre os satélites** em vez da
diferença entre 2015 e 2023 — e a série temporal fica com um degrau artificial exatamente em 2019,
que é justamente onde a maioria dos data centers começou a crescer. Seria o pior erro possível neste
projeto: um artefato de instrumentação parecendo um achado ambiental.

Esta tarefa existe para escolher **como** harmonizar e para **medir** o resíduo, antes de qualquer
ingestão em massa.

## Objetivo

Uma decisão registrada sobre o método de harmonização, com o erro residual entre sensores
**quantificado** em dados reais da AOI, e o código de referência que SV-06/SV-06b vão usar.

## Escopo — o que fazer

### Passo 1 — Avaliar o caminho pronto: NASA HLS

A NASA publica o **HLS (Harmonized Landsat Sentinel-2) v2.0**, que é exatamente este problema já
resolvido e validado: `NASA/HLS/HLSL30/v002` (Landsat, 30 m) e `NASA/HLS/HLSS30/v002` (Sentinel-2
reamostrado a 30 m), com ajuste de BRDF, band-pass e grade comum.

- **Verifique no Earth Engine** (não assuma): as coleções existem? Cobrem a AOI? Desde quando?
  O HLSL30 começa ~2013; o HLSS30 depende da disponibilidade S2 na região.
- **Se cobrir bem:** é o caminho recomendado para a série harmonizada. Custo de implementação
  muito menor e a harmonização é publicada e citável — argumento forte na banca.
- **Custo a pesar:** o HLS entrega tudo a **30 m**, incluindo o Sentinel-2. Perderíamos a resolução
  de 10 m que é justamente a vantagem da era moderna.

### Passo 2 — Avaliar o caminho manual

Harmonização própria a partir de `LANDSAT/LC0{8,9}/C02/T1_L2` e `COPERNICUS/S2_SR_HARMONIZED`:

- **Escala para reflectância:** Landsat C2 L2 → `SR_B* × 0.0000275 − 0.2`. Sentinel-2 L2A → `/10000`.
  Errar isso é o bug mais comum e mais silencioso do projeto.
- **Correspondência de bandas** (nomes harmonizados propostos, que viram contrato para SV-08):

  | Harmonizado | Landsat 8/9 OLI | Sentinel-2 | Observação |
  |---|---|---|---|
  | `blue` | SR_B2 | B2 | |
  | `green` | SR_B3 | B3 | |
  | `red` | SR_B4 | B4 | |
  | `nir` | SR_B5 | **B8A** | use B8A (855–875 nm), não B8 (785–900 nm) — B8A é a correspondência estreita correta com o NIR do OLI |
  | `swir1` | SR_B6 | B11 | |
  | `swir2` | SR_B7 | B12 | |

- **Ajuste band-pass:** aplicar coeficientes lineares publicados (Claverie et al. 2018, base do HLS;
  Roy et al. 2016 para OLI↔ETM+). Registre a fonte exata dos coeficientes usados.
- **Máscara de nuvem por sensor:** Landsat C2 → bitmask de `QA_PIXEL` (nuvem dilatada, cirrus,
  nuvem, sombra de nuvem) + `QA_RADSAT`. Sentinel-2 → Cloud Score+ `cs_cdf ≥ 0.60` (decisão D-04).

### Passo 3 — Medir o resíduo (o núcleo do spike)

Para **um** site e os anos de sobreposição (2019–2021), gerar o composto sazonal pelos dois sensores
e comparar, sobre os mesmos pixels (Landsat na grade de 30 m; Sentinel-2 agregado por média para a
mesma grade, só **para efeito desta comparação**):

- Por banda harmonizada: diferença média (viés), desvio, RMSE e R².
- Idem para NDVI, BSI e NDBI — os índices que mais importam para a classe crítica.
- Um scatter plot por banda, salvo em `reports/figures/harmonizacao/`.

**Critério de tolerância proposto:** viés absoluto médio de reflectância **< 0.02** e R² **> 0.85**
por banda, depois do ajuste. Acima disso, a série tem degrau visível e a harmonização precisa ser
revista (ou o degrau precisa ser tratado como covariável conhecida no modelo).

### Passo 4 — Registrar a decisão

`docs/decisoes/ADR-003-harmonizacao-multissensor.md` com: método escolhido (HLS ou manual) e por quê,
a tabela de resíduo medido, os coeficientes usados com fonte, a resolução final de cada era, e a
recomendação sobre a Faixa B (2000–2011, Landsat 5/7 TM/ETM+) — **incluindo, se for o caso, a
recomendação de não fazer**, com justificativa técnica. Não decidir sozinho sem registrar o trade-off.

### Passo 5 — Código de referência

`src/sentinela/gee/harmonizacao.py`, exportando:
`bandas_harmonizadas()` (lista ordenada canônica), `harmonizar_landsat(img)`, `harmonizar_s2(img)`,
`mascara_nuvem(img, sensor)` — todos devolvendo imagem em reflectância float com **os mesmos nomes
de banda**. SV-06 e SV-06b só chamam essas funções.

## Regra de parada (timebox)

São **3 horas**. Se ao fim delas o resíduo não estiver dentro da tolerância, **não continue
ajustando** — entregue o ADR com o resíduo medido e a recomendação de plano B:
1. tratar `sensor` como feature explícita no modelo (o RF aprende a compensar o degrau); ou
2. treinar **um modelo por era** e comparar as saídas em nível de área, não de pixel; ou
3. recuar a Faixa A para 2019–2025 (S2 puro) e apresentar a série longa como trabalho futuro.

Um spike que termina com "não deu, e aqui está o porquê medido" é um spike bem-sucedido.

## Fora de escopo

- Ingerir a série completa (SV-06, SV-06b).
- Treinar qualquer modelo.
- Harmonizar Landsat 5/7 (só a **recomendação** sobre viabilidade entra aqui).

## Critérios de aceite

- [ ] A disponibilidade real do HLS na AOI foi verificada no Earth Engine e o resultado está no ADR
      (com contagem de imagens por ano, não com "parece que tem").
- [ ] O resíduo entre sensores está medido em dados reais da AOI, por banda e para NDVI/BSI/NDBI,
      com viés, RMSE e R² em tabela.
- [ ] Os scatter plots estão em `reports/figures/harmonizacao/`.
- [ ] `ADR-003` registra método escolhido, coeficientes com fonte bibliográfica, tolerância atingida
      ou não, e a recomendação sobre a Faixa B.
- [ ] `src/sentinela/gee/harmonizacao.py` existe e as duas funções devolvem os **mesmos 6 nomes de
      banda** na mesma ordem, verificável por teste.
- [ ] Se a tolerância não foi atingida, o plano B escolhido está registrado e SV-06/SV-06b/SV-11
      foram avisados do impacto.

## Cenários de teste

1. `harmonizar_landsat(img).bandNames()` == `harmonizar_s2(img).bandNames()` == `bandas_harmonizadas()`.
2. Escala: um pixel de reflectância conhecida sai no intervalo [0, 1] nos dois sensores — se sair
   em milhares, a escala foi esquecida.
3. Mesma cena, mesmo dia, dois sensores → NDVI difere por menos que a tolerância na maioria dos pixels.
4. Máscara: um pixel notoriamente nublado é removido nos dois caminhos.
5. Sanidade invertida: **desligar** o ajuste band-pass e confirmar que o resíduo **piora** — se não
   piorar, o ajuste não está sendo aplicado de fato.

## Como reportar

Informe: método escolhido e por quê, a tabela de resíduo, se a tolerância foi atingida, a resolução
final de cada era, a recomendação sobre a Faixa B, e — se aplicável — qual plano B foi acionado e o
que isso muda em SV-06/SV-06b/SV-11.
