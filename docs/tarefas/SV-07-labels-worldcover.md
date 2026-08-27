# SV-07 — Geração dos rasters de label, remapeados e alinhados

- **Fase:** 2 — Dataset · **Data-alvo:** 02/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-02 (AOI), SV-04 (auth EE), SV-05 (remap em código), **SV-05b (fonte de label)**, SV-06, SV-06b
- **Desbloqueia:** SV-09, SV-11
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: a fonte de label deixou de ser dada e passa a vir da decisão de
> **SV-05b** (WorldCover safra fixa vs. MapBiomas anual), e os labels agora precisam ser alinhados a
> **duas grades** (10 m e 30 m). Consequência da série longa multi-sensor de SV-02.

## Contexto

O `CLAUDE.md` fixa **ESA WorldCover v200 como label fraco/inicial**. "Fraco" é literal: safra fixa
(~2021), 10 m, produzida globalmente — erra em detalhe local e não enxerga estados transitórios como
canteiro de obra.

Com a janela estendida a 2013–2025, essa fraqueza deixou de ser tolerável sozinha, e **SV-05b** avalia
a troca por uma fonte anual (MapBiomas). **Leia `docs/decisoes/ADR-004-fonte-de-labels.md` antes de
começar** — ele diz qual das três formas implementar:
- **(a)** MapBiomas anual como fonte única;
- **(b)** MapBiomas como principal + WorldCover como verificação cruzada (peso maior onde concordam);
- **(c)** WorldCover safra fixa, replicado para todos os anos.

O código desta tarefa deve suportar a forma escolhida **sem hardcodar a fonte**: a fonte vem de
`config/params.yml`, para que trocá-la não exija reescrever o pipeline.

Os remaps já existem em código, vindos de SV-05: **use `sentinela.classes`, não reescreva tabela aqui.**

## Objetivo

Rasters de label alinhados à **exata grade de cada era de sensor**, prontos para leitura pixel a
pixel junto com as features.

## Escopo — o que fazer

1. **`src/sentinela/gee/labels.py`**, CLI
   `python -m sentinela.gee.labels --site <id|all> --ano <ano|all> --sensor <s2|landsat|all>`:
   - Coleção conforme `config/params.yml` / ADR-004: `ESA/WorldCover/v200` e/ou a coleção MapBiomas
     registrada no ADR.
   - Recorte pela AOI do site; remap via `sentinela.classes`.
   - **Alinhamento — a parte que mudou:** gerar **um raster de label por grade**, reprojetando para o
     CRS, `transform` e `shape` **lidos do manifest do raster de imagem correspondente** — o de
     Sentinel-2 (10 m) para os anos da era moderna e o de Landsat (30 m) para a era antiga.
     Não recalcule grade. Reamostragem **`nearest`** (dado categórico; bilinear inventaria classes).
   - **Se a fonte for anual:** um arquivo por site × ano × grade →
     `data/raw/labels/{sensor}/{site_id}/{ano}.tif`.
     **Se a fonte for de safra fixa:** um arquivo por site × grade, replicado logicamente para todos
     os anos — e a coluna `distancia_safra` de SV-11 passa a carregar essa informação.
   - Saída **uint8**, valores 0–5, `nodata = 0`.
   - **Se ADR-004 escolheu a forma (b)**, gerar também `concordancia_{...}.tif` (uint8: 1 onde as
     duas fontes concordam, 0 onde divergem) — é o que SV-11 usa para ponderar as amostras.
2. **Estatísticas de sanidade**, impressas e gravadas no manifest: contagem e percentual por classe,
   por site, por ano e por grade. **Se a fonte for anual, reportar também a variação da distribuição
   entre 2013 e 2025** — é o sinal de mudança de uso que o projeto quer capturar, e vê-lo já aqui é
   uma boa validação de que a fonte está certa.
3. **Manifest** `data/manifests/labels_{sensor}_{site_id}_{ano}.json` (commitado): `site_id`, `ano`,
   `sensor`, `fonte`, `colecao`, `safra` (ou `anual: true`), `remap_usado`, `crs`, `transform`,
   `shape`, `resolucao_m`, `nodata`, `distribuicao_classes`, `sha256`, `git_sha`, `gerado_em`.
4. **Anotar a limitação** em `docs/classes.md`: se a fonte for de safra fixa, dizer explicitamente
   que os labels valem para ~2021 e são aplicados a 13 anos, e que a defasagem chega a 8 anos nas
   pontas — isso muda como SV-11 pondera e como SV-13 lê as métricas. Se for anual, registrar que a
   defasagem foi eliminada e qual é o último ano coberto pela coleção (os anos além dele usam o
   último disponível, e isso também precisa estar escrito).

## Fora de escopo

- **Decidir** a fonte de label (SV-05b) — aqui se implementa o que o ADR-004 determinou.
- Rotulagem manual da classe 3 (SV-09/SV-10).
- Redefinir o remap (SV-05).
- Corrigir o label fraco — não é para "melhorar" a fonte aqui.

## Critérios de aceite

- [ ] Existe raster de label alinhado **para cada grade em uso** (10 m e 30 m), em todo site ativo.
- [ ] `rasterio`: CRS, `transform` e `shape` **idênticos** ao raster de imagem correspondente
      (teste automatizado, para as duas eras).
- [ ] dtype uint8, valores ⊆ {0,1,2,3,4,5}. Nenhum código da legenda original sobrou.
- [ ] A distribuição de classes é plausível para a região: em Vinhedo/Hortolândia espera-se
      predominância de 1 e 2, presença relevante de 4, pouco 3 e pouco 5.
      **Se a classe 5 (água) passar de ~10% ou a 3 passar de ~20%, algo está errado no remap** — investigue.
- [ ] Sobrepondo o label ao RGB do composto: corpos d'água caem sobre água, área urbana sobre urbana.
- [ ] Se a fonte for anual: a distribuição muda de 2013 para 2025 nos sites com construção no período
      — **se não mudar nada, você provavelmente replicou o mesmo ano 13 vezes por engano.**
- [ ] Manifests commitados, `sha256` conferindo.
- [ ] `git status` limpo quanto a `.tif`.

## Cenários de teste

1. **Alinhamento, era moderna:** `labels_s2.shape == s2.shape` e mesmo `transform`.
2. **Alinhamento, era antiga:** `labels_landsat.shape == landsat.shape` e mesmo `transform`.
3. **Coerência entre grades:** um ponto (x, y) do terreno recebe a **mesma classe** nos dois rasters
   de label do mesmo ano (salvo efeito de pixel misto na borda). Divergência sistemática no interior
   de manchas homogêneas indica erro de reprojeção.
4. **Domínio:** `set(np.unique(labels)) - {0,1,2,3,4,5} == set()`.
5. **Sem interpolação:** nenhum valor fora do conjunto, prova de que foi `nearest`.
6. **Validação visual:** exportar PNG colorido (`sentinela.classes.colormap()`) para
   `reports/figures/labels_{sensor}_{site}_{ano}.png` e conferir contra o RGB.
7. **Idempotência:** rodar duas vezes → mesmo `sha256`.

## Como reportar

Informe: qual forma do ADR-004 foi implementada, tabela `site | ano | classe | n_pixels | pct` (ao
menos primeiro e último ano), sua avaliação sobre se a distribuição faz sentido, e — se a fonte for
anual — a variação observada entre 2013 e 2025. Sinalize explicitamente se a classe 3 tiver
representação muito baixa: isso define o quanto SV-09/SV-10 são urgentes.
