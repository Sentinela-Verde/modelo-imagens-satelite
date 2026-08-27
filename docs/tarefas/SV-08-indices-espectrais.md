# SV-08 — Índices espectrais / stack de features

- **Fase:** 2 — Dataset · **Data-alvo:** 02/09 · **Tamanho:** P (~1h30)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-02b (nomes canônicos de banda), SV-06, SV-06b
- **Desbloqueia:** SV-11
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: as fórmulas passam a usar os **nomes harmonizados de banda**
> (`blue, green, red, nir, swir1, swir2`) em vez de `B2..B12`, e a tarefa processa as **duas eras**
> de sensor. Consequência da série multi-sensor de SV-02.

## Contexto

Bandas cruas separam mal vegetação rala de solo exposto — que é exatamente a fronteira que este
projeto precisa acertar. Índices espectrais são features baratas e muito informativas para
cobertura do solo, e são o que faz um Random Forest simples ficar competitivo.

Entradas (**as duas**, mesmo tratamento):
- `data/raw/s2/{site_id}/{ano}.tif` — 6 bandas, 10 m (era Sentinel-2)
- `data/raw/landsat/{site_id}/{ano}.tif` — 6 bandas, 30 m (era Landsat)

Ambas em int16 com fator 10000, nodata `-9999`, e com **os mesmos nomes de banda canônicos**
definidos em SV-02b. Confira os nomes e a ordem nos manifests, **não assuma**.

**Nota sobre o que se perdeu:** o conjunto harmonizado não tem as bandas de red-edge do Sentinel-2
(o Landsat não as possui), que ajudariam a separar vegetação densa de rala. É o preço da série longa,
aceito em SV-02. Se `data/raw/s2_extendido/` existir (saída opcional de SV-06), gere um segundo stack
com red-edge marcado como **experimental**, para o "Plus" medir o que essa perda custou — mas o stack
harmonizado é o principal da V1.

## Objetivo

Um stack de features por site/ano/sensor, cada um na grade do seu raster de origem, pronto para
amostragem em SV-11.

## Escopo — o que fazer

1. **`src/sentinela/features/indices.py`** com os índices abaixo (todos sobre reflectância
   já em float32 no intervalo [0, 1], **usando os nomes canônicos** — o mesmo código roda nas duas
   eras sem ramificação por sensor, e é justamente esse o ganho da harmonização):

| Índice | Fórmula | Para que serve aqui |
|---|---|---|
| NDVI | (nir − red) / (nir + red) | vegetação vs. não-vegetação; separa classes 1/2 de 3/4 |
| EVI | 2.5·(nir − red) / (nir + 6·red − 7.5·blue + 1) | menos saturado que NDVI em vegetação densa; separa 1 de 2 |
| NDWI | (green − nir) / (green + nir) | água |
| MNDWI | (green − swir1) / (green + swir1) | água, mais robusto em área urbana que NDWI |
| NDBI | (swir1 − nir) / (swir1 + nir) | área construída |
| BSI | ((swir1 + red) − (nir + blue)) / ((swir1 + red) + (nir + blue)) | **solo exposto — o índice mais importante para a classe 3** |
| NDMI | (nir − swir1) / (nir + swir1) | umidade da vegetação; ajuda a separar 2 de 3 |

2. **Tratamento numérico obrigatório:**
   - Denominador zero ou muito próximo de zero → `nodata`, **nunca** `inf`/`NaN` silencioso.
   - Qualquer pixel que seja nodata em **qualquer** banda de entrada é nodata em **todas** as
     features de saída (máscara conjunta) — senão SV-11 monta linhas parcialmente inválidas.
   - Clipar índices ao intervalo teórico `[-1, 1]` (exceto EVI, clipar em `[-1, 2.5]`).

3. **Saída:** `data/interim/features/{sensor}/{site_id}/{ano}.tif` — **float32**, nodata `-9999`,
   contendo **as 6 bandas harmonizadas (em reflectância float) + os 7 índices = 13 bandas**, em
   ordem fixa e documentada, **idêntica nas duas eras**. Mesma grade/CRS/transform do input
   (copie do input, não recalcule) — 10 m na era S2, 30 m na era Landsat.

4. **CLI:** `python -m sentinela.features.indices --sensor <s2|landsat|all> --site <id|all> --ano <ano|all> [--force]`, idempotente.

5. **Manifest** `data/manifests/features_{sensor}_{site_id}_{ano}.json` (commitado): lista ordenada
   dos nomes das 13 bandas, fórmulas usadas, `sensor`, `resolucao_m`, `pct_pixels_validos` do stack
   final, `sha256`, `git_sha`.
   **Os nomes das bandas deste manifest viram os nomes das colunas do dataset em SV-11** —
   trate como contrato, e ele precisa ser **o mesmo nas duas eras**.

6. **`tests/test_indices.py`** com os casos abaixo.

## Fora de escopo

- Features temporais (delta ano-a-ano, tendência) — são poderosas, mas são item **Plus**. V1 é
  classificação por ano, independente.
- Features de textura/vizinhança (GLCM, janela móvel) — Plus.
- Amostragem ou join com labels (SV-11).

## Critérios de aceite

- [ ] Existe `data/interim/features/{sensor}/{site_id}/{ano}.tif` para todo site × ano × sensor.
- [ ] 13 bandas, float32, nomes gravados no manifest, ordem estável entre execuções, entre sites
      **e entre as duas eras** (teste automatizado comparando os manifests de S2 e Landsat).
- [ ] `transform`/`shape`/CRS idênticos ao raster de origem correspondente.
- [ ] **Zero** `NaN` e zero `inf` em qualquer banda de saída (teste automatizado, não inspeção visual).
- [ ] Máscara conjunta aplicada: o conjunto de pixels nodata é o mesmo nas 13 bandas.
- [ ] **Continuidade entre eras:** o NDVI médio sobre uma área de mata estável em 2018 (Landsat) e em
      2019 (Sentinel-2) difere por menos que a tolerância medida em SV-02b. Se diferir muito, o
      problema está na harmonização, não aqui — mas é aqui que aparece primeiro.
- [ ] NDVI em área de mata fechada > 0.6; NDVI em telhado/asfalto < 0.2; MNDWI em corpo d'água > 0
      (amostre alguns pixels conhecidos e confira — sanity check manual documentado no relatório).
- [ ] Rodar duas vezes gera o mesmo `sha256`.

## Cenários de teste

1. **Divisão por zero:** array sintético com B8 = B4 = 0 → NDVI vira nodata, não `NaN`.
2. **Intervalo:** todos os NDVI/NDWI/NDBI/BSI/NDMI finais ∈ [−1, 1].
3. **Máscara conjunta:** injetar nodata em uma única banda de um pixel → esse pixel é nodata nas 13.
4. **Grade:** `features.transform == origem.transform`, nas duas eras.
5. **Valores conhecidos:** um pixel sintético com assinatura típica de vegetação produz NDVI alto e
   BSI baixo; um com assinatura de solo produz o inverso — **e o mesmo pixel sintético produz o mesmo
   resultado processado como Landsat ou como Sentinel-2** (prova de que o código não ramifica por sensor).
6. **Contrato entre eras:** `manifest_features_s2["bandas"] == manifest_features_landsat["bandas"]`.

## Como reportar

Informe: os 13 nomes de banda na ordem final, `pct_pixels_validos` por site/ano/sensor, o resultado
do sanity check de NDVI/MNDWI em pixels conhecidos, e o número da continuidade 2018→2019.
