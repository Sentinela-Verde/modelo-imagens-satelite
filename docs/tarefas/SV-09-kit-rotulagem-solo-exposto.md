# SV-09 — Kit de rotulagem manual "solo exposto / em obras"

- **Fase:** 2 — Dataset · **Data-alvo:** 03/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `data-engineer` (prepara o material) — critérios de rotulagem revisados por `ml-engineer`
- **Bloqueado por:** SV-06, SV-06b, SV-07
- **Desbloqueia:** SV-10
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: a janela passou a ser 2013–2025 em dois sensores (SV-02). Gere
> candidatos e recortes **nas duas eras** — a transição vegetação→obra dos data centers mais antigos
> acontece na era Landsat, e ignorá-la deixaria a classe crítica sem exemplo justamente onde ela
> aparece pela primeira vez. Nos recortes de 30 m, use polígonos maiores (mínimo de 1 ha em vez de
> 0,5 ha) — abaixo disso são poucos pixels e a rotulagem fica mais chute que julgamento.

## Contexto

O `CLAUDE.md` prevê **rotulagem manual complementar da classe "solo exposto / em obras"**, porque
o WorldCover é de safra fixa (~2021) e marca *solo natural exposto*, não *canteiro de obra* —
justamente o estado transitório que o Sentinela Verde existe para detectar.

Rotular manualmente é caro em tempo humano. Esta tarefa existe para que a pessoa que for rotular
(SV-10) gaste o tempo dela **decidindo**, não procurando onde clicar. O kit precisa entregar
candidatos prováveis já recortados e um critério escrito do que é e do que não é a classe 3.

## Objetivo

Um conjunto de recortes visuais + polígonos candidatos + guia de critérios que permita a um humano
produzir ~200 polígonos rotulados em uma sessão de 2 horas.

## Escopo — o que fazer

1. **Detecção de candidatos** — `src/sentinela/labeling/candidatos.py`, CLI
   `python -m sentinela.labeling.candidatos --site <id|all>`:
   - Regra heurística (é só um *filtro de atenção*, não um classificador): pixels com
     **BSI alto e NDVI baixo** no ano N, que no ano N−1 tinham **NDVI alto**
     (ou seja, transição vegetação → solo). Use percentis do próprio site em vez de limiares
     absolutos, e documente os limiares escolhidos.
   - Agrupar pixels em polígonos (`rasterio.features.shapes`), descartar polígonos menores que
     **0.5 ha** (ruído).
   - Saída: `data/interim/candidatos_{site_id}.geojson`, com `site_id`, `ano`, `area_ha`,
     `ndvi_medio`, `bsi_medio`, `classe_worldcover` (o que o label fraco dizia ali).
   - Limitar a **até 60 candidatos por site**, ordenados por área — não despeje 5.000 polígonos
     em cima de quem vai rotular.

2. **Recortes visuais** — `reports/figures/rotulagem/{site_id}/{ano}_rgb.png` e `{ano}_falsacor.png`
   (falsa-cor SWIR: B12/B8/B4, onde solo exposto salta em magenta/rosa e vegetação fica verde),
   com os polígonos candidatos desenhados por cima e numerados. Mesma extensão e escala em todos
   os anos, para comparação lado a lado.

3. **Template de rotulagem** — `data/labels_manual/_template.geojson` (vazio, commitado), com o
   schema de propriedades que SV-10 vai preencher e SV-16 vai ler:
   `site_id` (str), `ano` (int), `classe_id` (int 1–5), `classe_slug` (str),
   `confianca` (`alta`|`media`|`baixa`), `autor` (str), `data_rotulagem` (ISO), `observacao` (str),
   `origem` (`candidato`|`manual`).

4. **Guia de critérios** — `docs/guia-rotulagem.md`, escrito para ser lido por um humano cansado:
   - O que **é** classe 3: terraplenagem, canteiro de obra, área raspada, pilha de terra, estrada
     de terra larga dentro do canteiro, solo natural exposto sem vegetação.
   - O que **não é** classe 3 e costuma ser confundido: telhado claro/laje (é 4), estacionamento
     de terra batida consolidado (caso de borda — decida uma regra e registre), campo de futebol
     seco, lavoura recém-colhida (é 2 — atenção, este é o erro mais comum na região).
   - Como usar a falsa-cor SWIR para desempatar.
   - **Quantas amostras rotular e de quê** (ver critérios de aceite de SV-10).
   - Instrução para rotular também **negativos difíceis**: polígonos de classes 2 e 4 que a
     heurística marcou como candidato mas não são obra. Sem esses, o modelo aprende a heurística,
     não a classe.
   - Ferramenta sugerida: QGIS abrindo o `.tif` de `data/raw/s2/` + o template GeoJSON como
     camada editável. Passo a passo curto.

## Fora de escopo

- Rotular de fato (SV-10 — é trabalho humano).
- Usar a heurística como classificador ou como label automático. **Ela é só um localizador.**
  Se ela virar label, o modelo aprende a decorar BSI/NDVI e a avaliação vira circular.
- Treinar qualquer coisa.

## Critérios de aceite

- [ ] `data/interim/candidatos_{site_id}.geojson` existe para cada site, com ≤ 60 features, todas ≥ 0.5 ha.
- [ ] Os PNGs de RGB e falsa-cor existem para cada site × ano, com candidatos numerados e legíveis.
- [ ] Abrindo 3 candidatos aleatórios no Google Earth / imagem de alta resolução, **pelo menos 2**
      são de fato área alterada. Se a taxa for pior que isso, ajuste os limiares antes de entregar.
- [ ] `data/labels_manual/_template.geojson` está commitado e abre no QGIS como camada editável.
- [ ] `docs/guia-rotulagem.md` responde, sem ambiguidade, "isto aqui é 3 ou é 2?" para os cinco
      casos de confusão listados acima.
- [ ] Uma pessoa que não participou do projeto consegue, lendo só o guia, rotular 5 polígonos.
      **Teste isso com alguém do time antes de fechar a tarefa.**

## Cenários de teste

1. Rodar para um site → GeoJSON + PNGs gerados, contagem dentro do limite.
2. Abrir o GeoJSON de candidatos no QGIS sobre o RGB → os polígonos caem sobre áreas visivelmente alteradas.
3. Abrir o template no QGIS, desenhar um polígono, preencher os campos, salvar → arquivo válido
   e legível por `geopandas`.
4. Verificação de honestidade: nenhum arquivo produzido aqui contém uma coluna que possa ser
   confundida com label pronto — o campo `classe_id` do candidato vem **vazio**.

## Como reportar

Informe: nº de candidatos por site, os limiares usados, o resultado da conferência visual dos 3
candidatos aleatórios, e quanto tempo você estima que SV-10 vai levar.
