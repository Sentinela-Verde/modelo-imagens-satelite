# SV-06b — Ingestão Landsat (era 2013–2018 + faixa de sobreposição)

- **Fase:** 1 — Dados · **Data-alvo:** 01/09 · **Tamanho:** M (~3h)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-02 (AOI e faixas), SV-02b (contrato de harmonização), SV-04 (auth EE)
- **Desbloqueia:** SV-08, SV-20
- **Tem seção de risco:** não

## Contexto

SV-02 estendeu a série para 2013–2025. O Sentinel-2 não cobre bem antes de 2019, então a metade
anterior da série vem do **Landsat 8/9**. Esta tarefa é o par de SV-06 e precisa produzir arquivos
com **exatamente o mesmo esquema de bandas**, definido em SV-02b — senão o dataset de SV-11 não tem
como unir as duas eras.

Além de 2013–2018, esta tarefa ingere também os **anos de sobreposição** (2019–2021, ver
`config/params.yml`), onde Landsat e Sentinel-2 coexistem. Esses anos não entram na série final
duplicados: existem para que **SV-20 possa medir o viés entre os dois sensores em dados reais**.
Sem eles, a série multi-sensor é uma promessa não verificada.

## Objetivo

`data/raw/landsat/{site_id}/{ano}.tif` para 2013–2018 e para os anos de sobreposição, no mesmo
esquema de bandas da era Sentinel-2, com manifest auditável.

## Escopo — o que fazer

1. **`src/sentinela/gee/landsat.py`:**
   - Coleções: `LANDSAT/LC08/C02/T1_L2` (2013→) e `LANDSAT/LC09/C02/T1_L2` (2021→), unidas.
     **Não inclua Landsat 5 nem 7 nesta tarefa** — são a Faixa B, fora da V1 (ver SV-02), e o L7 tem
     falhas de SLC que exigem tratamento próprio.
   - **Escala para reflectância:** `SR_B* × 0.0000275 − 0.2`. Este é o erro silencioso mais comum
     do projeto: sem isso, os valores saem em dezenas de milhares e todo índice espectral fica errado
     sem lançar exceção.
   - **Máscara de nuvem:** bitmask de `QA_PIXEL` (nuvem, nuvem dilatada, cirrus, sombra de nuvem)
     mais `QA_RADSAT` para pixels saturados. Documente exatamente quais bits foram usados.
   - **Harmonização:** aplicar `sentinela.gee.harmonizacao.harmonizar_landsat` — devolve as 6 bandas
     canônicas com o ajuste band-pass de SV-02b. Não reimplemente.
   - Filtro: AOI + janela `mes_inicio`–`mes_fim`.
   - Agregação: **mediana** por pixel dentro do ano — mesmo método de SV-06, para que a diferença
     entre as eras venha do sensor e não do método.
   - Reprojeção para EPSG:31983 a **30 m** (resolução nativa — **não reamostre para 10 m**, isso
     inventaria precisão inexistente). Grade idêntica entre todos os anos do mesmo site, e com
     origem combinada com SV-06 de modo que a grade de 10 m seja um refinamento exato desta.
   - Escala de gravação: int16 com fator 10000, nodata `-9999` — igual a SV-06.

2. **CLI:** `python -m sentinela.gee.landsat --site <id|all> --ano <ano|all> [--force]`, idempotente.

3. **Validação de qualidade** por site/ano: `pct_pixels_validos` e `n_imagens_usadas`.
   **Atenção à expectativa correta:** o Landsat 8 tem revisita de 16 dias contra 5 do Sentinel-2, ou
   seja, ~8 cenas na janela seca contra ~20. Menos cenas por composto é **normal aqui**, não um bug.
   Mantenha o piso de `pct_pixels_validos >= 90%`, mas se um ano não bater, amplie a janela sazonal
   antes de concluir que o ano é inutilizável — e registre a janela efetivamente usada no manifest.

4. **Manifest** `data/manifests/landsat_{site_id}_{ano}.json` (**commitado**), mesmo esquema de SV-06,
   com `sensor` = `landsat`, `resolucao_m` = 30, mais `satelites_usados` (`LC08`, `LC09` ou ambos) e
   `janela_efetiva` (se diferiu da padrão).

5. **PNG de conferência:** `reports/figures/composto_landsat_{site}_{ano}.png` em RGB para o primeiro
   e o último ano da era Landsat, por site.

## Fora de escopo

- Sentinel-2 (SV-06).
- Landsat 5/7 e a Faixa B (2000–2011) — fora da V1 por decisão de SV-02.
- Definir *como* harmonizar (SV-02b).
- Comparar as duas eras (SV-20).

## Critérios de aceite

- [ ] Existe `data/raw/landsat/{site_id}/{ano}.tif` para 2013–2018 **e** para cada ano de sobreposição.
- [ ] Cada tif tem **as mesmas 6 bandas canônicas, na mesma ordem** que os arquivos de SV-06
      (teste automatizado comparando os dois manifests).
- [ ] int16, fator 10000, nodata `-9999`, CRS EPSG:31983, pixel **30 m**.
- [ ] Grade idêntica entre todos os anos do mesmo site.
- [ ] A grade de 30 m e a de 10 m de SV-06 são compatíveis: mesma origem, e a de 10 m subdivide
      exatamente a de 30 m (teste automatizado).
- [ ] **Sanidade física da escala:** reflectância no intervalo [0, 1] após aplicar o fator; `red`
      sobre vegetação < 0.1 e `nir` sobre vegetação > 0.2 — os mesmos números esperados em SV-06.
      Valores negativos abaixo de −0.05 ou acima de 1.2 indicam escala/offset errados.
- [ ] `pct_pixels_validos >= 90%` por site/ano, ou desvio justificado e registrado.
- [ ] Conferência visual: o RGB de 2013 e o de 2018 do mesmo site são reconhecíveis e mostram a
      região; comparando com o RGB de 2019 (Sentinel-2), as cores são **parecidas** — um salto
      grosseiro de cor entre as duas eras significa harmonização mal aplicada, e é para pegar aqui.
- [ ] Manifests commitados, `sha256` batendo.
- [ ] `git status` limpo quanto a `.tif`.

## Cenários de teste

1. **Um site, um ano:** gera tif + manifest + PNG.
2. **Idempotência e determinismo:** dois runs → mesmo `sha256`.
3. **Contrato de bandas:** `manifest_landsat["bandas"] == manifest_s2["bandas"]`, elemento a elemento.
4. **Escala:** um pixel de água (reflectância NIR notoriamente baixa) tem `nir < 0.1`. Se tiver
   `nir` na casa dos milhares, o fator 0.0000275/−0.2 não foi aplicado.
5. **Alinhamento entre grades:** `(transform_10m.c - transform_30m.c) % 30 == 0` e idem no eixo y.
6. **Continuidade visual:** comparar lado a lado o composto de 2018 (Landsat) e o de 2019 (S2) do
   mesmo site — a diferença de NDVI médio sobre uma área de mata estável deve ser pequena
   (use a tolerância definida em SV-02b). Este é o teste mais importante da tarefa.
7. **Máscara:** um pixel notoriamente nublado é removido.

## Como reportar

Informe: tabela `site | ano | satelites | n_imagens | pct_pixels_validos`, o resultado do teste de
continuidade visual 2018→2019 (item 6) com o número de diferença de NDVI, e qualquer ano em que a
janela sazonal precisou ser ampliada.
