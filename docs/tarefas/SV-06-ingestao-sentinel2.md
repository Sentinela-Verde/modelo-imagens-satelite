# SV-06 — Ingestão Sentinel-2 (era moderna, 2019–2025)

- **Fase:** 1 — Dados · **Data-alvo:** 01/09 · **Tamanho:** M (~3h)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-02 (AOI e faixas), SV-02b (contrato de harmonização), SV-04 (auth EE)
- **Desbloqueia:** SV-08, SV-09
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: a série passou a ser multi-sensor (SV-02). Esta tarefa agora cobre
> **apenas a era Sentinel-2 (2019–2025)**; a era Landsat (2013–2018 + sobreposição) é SV-06b.
> As duas devem produzir arquivos com **os mesmos nomes de banda**, definidos em SV-02b.

## Contexto

Um GeoTIFF por site/ano na era moderna, mascarado de nuvem e agregado. Grade, CRS e resolução
definidos aqui viram contrato para o resto do repo.

O ponto que mudou em relação à versão anterior desta tarefa: as bandas de saída **não são mais**
`B2..B12` cruas do Sentinel-2. São as **6 bandas harmonizadas** (`blue, green, red, nir, swir1,
swir2`) produzidas por `sentinela.gee.harmonizacao.harmonizar_s2`, para que o Landsat de SV-06b
produza exatamente o mesmo esquema e o modelo possa atravessar as duas eras.

**Consequência que você precisa conhecer:** as bandas de red-edge (B5, B6, B7) e B8A largo ficam de
fora do conjunto harmonizado, porque o Landsat não as tem. Elas são úteis para separar vegetação
densa de rala. **Esse é o preço da série longa** e está aceito na decisão de SV-02. Se quiser
preservá-las, veja "Saída opcional" abaixo — mas o conjunto harmonizado é o principal da V1.

## Objetivo

`data/raw/s2/{site_id}/{ano}.tif` para todo site ativo e todo ano da era S2, reproduzível com um
comando, com manifest auditável.

## Escopo — o que fazer

1. **`src/sentinela/gee/sentinel2.py`:**
   - Coleção: `COPERNICUS/S2_SR_HARMONIZED`.
   - Máscara de nuvem: **Cloud Score+** (`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`), via
     `linkCollection`, banda **`cs_cdf`**, mantendo `cs_cdf >= 0.60`. *Não use QA60.* (Decisão D-04.)
   - Filtro: AOI (buffer do site) + janela `mes_inicio`–`mes_fim` de `config/params.yml`.
   - Agregação: **mediana** por pixel dentro do ano.
   - **Harmonização:** aplicar `sentinela.gee.harmonizacao.harmonizar_s2` — reflectância float,
     ajuste band-pass, e renomeação para as 6 bandas canônicas. Não reimplemente aqui.
   - Reprojeção para `crs_analise` (EPSG:31983) a **10 m**, com grade **alinhada e idêntica entre
     todos os anos do mesmo site** (mesmo `transform`, mesmo `shape`). Obrigatório: SV-11 e o change
     detection dependem de o pixel de 2019 ser o mesmo pixel de 2025.
   - **Alinhamento entre sensores:** a grade de 10 m deve ser um refinamento exato da grade de 30 m
     de SV-06b — origem coincidente e 30 divisível por 10. Combine a origem com quem fizer SV-06b
     **antes** de exportar; corrigir depois custa reprocessar tudo.
   - Escala: gravar reflectância como **int16 com fator 10000** (economiza 50% de espaço vs. float32);
     documentar o fator no manifest. Nodata = `-9999`.

2. **CLI:** `python -m sentinela.gee.sentinel2 --site <id|all> --ano <ano|all> [--force]`.
   Idempotente: se o `.tif` existe e o manifest confere, pula.

3. **Download:** prefira download direto (`ee.Image.getDownloadURL` / `geemap.download_ee_image`) —
   o AOI é pequeno (10×10 km, ~1000×1000 px, 6 bandas int16 ≈ 12 MB). Se estourar o limite, caia
   para `Export.image.toDrive` e **documente o passo manual** — mas evite: passo manual quebra a
   reprodutibilidade exigida pelo `CLAUDE.md`.

4. **Validação de qualidade** por site/ano: `pct_pixels_validos` (não-nodata após a máscara) e
   `n_imagens_usadas`. **Se `pct_pixels_validos < 90%`**, ampliar a janela sazonal em ±1 mês e tentar
   de novo; se ainda assim ficar abaixo, gravar e **reportar como achado**.

5. **Manifest** `data/manifests/s2_{site_id}_{ano}.json` (**commitado**): `site_id`, `ano`, `sensor`
   (`sentinel2`), `colecao`, `janela`, `mascara` + limiar, `bandas` (lista ordenada canônica),
   `harmonizacao` (método e versão, de SV-02b), `crs`, `transform`, `shape`, `resolucao_m` (10),
   `nodata`, `fator_escala`, `n_imagens_usadas`, `pct_pixels_validos`, `sha256`, `git_sha`, `gerado_em`.

6. **Saída opcional (não bloqueia a V1):** um segundo arquivo
   `data/raw/s2_extendido/{site}/{ano}.tif` com as bandas red-edge adicionais, para que o "Plus"
   possa avaliar quanto elas melhorariam a era moderna. Só gere se sobrar tempo.

## Fora de escopo

- Landsat (SV-06b).
- Definir *como* harmonizar (SV-02b) — aqui só se consome a função.
- Índices espectrais (SV-08).

## Critérios de aceite

- [ ] Existe `data/raw/s2/{site_id}/{ano}.tif` para todo site ativo × todo ano da era S2.
- [ ] Cada tif tem **as 6 bandas canônicas de SV-02b, nessa ordem**, int16, CRS EPSG:31983, pixel 10 m.
- [ ] Para um mesmo site, todos os anos têm `transform` e `shape` idênticos (teste automatizado).
- [ ] A grade de 10 m é refinamento exato da grade de 30 m de SV-06b: a origem coincide e
      `(origem_10m - origem_30m) % 30 == 0` nos dois eixos (teste automatizado).
- [ ] `pct_pixels_validos >= 90%` em todos os site/ano — ou o desvio está reportado com justificativa.
- [ ] Abrindo em RGB (`red, green, blue`), a imagem parece uma imagem: sem faixa de nuvem residual
      grosseira, sem buraco enorme.
- [ ] Reflectância em faixa física: mediana de `red` sobre vegetação < 0.1; mediana de `nir` sobre
      vegetação > 0.2. **Se os valores saírem na casa dos milhares, o fator de escala foi esquecido.**
- [ ] Manifest commitado para cada site/ano, `sha256` batendo com o arquivo.
- [ ] Rodar de novo sem `--force` não rebaixa nada e termina em segundos.
- [ ] `git status` limpo quanto a `.tif`.

## Cenários de teste

1. **Um site, um ano:** gera tif + manifest, com `pct_pixels_validos` impresso.
2. **Idempotência:** rodar de novo → "já existe, pulando".
3. **`--force`:** regera e o `sha256` é idêntico (o composto é determinístico).
4. **Alinhamento temporal:** `rasterio.open(2019).transform == rasterio.open(2025).transform`.
5. **Alinhamento entre sensores:** conferir a origem contra o manifest do Landsat do mesmo site.
6. **Contrato de bandas:** os nomes no manifest são exatamente `bandas_harmonizadas()` de SV-02b.
7. **Ano ruim:** forçar `cs_cdf >= 0.99` → `pct_pixels_validos` despenca e o código **reporta** em
   vez de gravar em silêncio.

## Como reportar

Informe: tabela `site | ano | n_imagens | pct_pixels_validos | tamanho_mb`, qualquer site/ano abaixo
de 90%, os valores de reflectância do teste de sanidade física, e a origem de grade acordada com SV-06b.
