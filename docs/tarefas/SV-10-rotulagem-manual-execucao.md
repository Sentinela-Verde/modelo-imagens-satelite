# SV-10 — Rotulagem manual (execução)

- **Fase:** 2 — Dataset · **Data-alvo:** 03–04/09 · **Tamanho:** M (**timebox duro de 4h** de trabalho humano)
- **Responsável sugerido:** **humano** (1 ou 2 integrantes do time)
- **Bloqueado por:** SV-09b (kit estratificado)
- **Desbloqueia:** SV-16
- **Tem seção de risco:** não
- **Tipo:** **TRABALHO HUMANO — o único gargalo do projeto que não escala com agentes nem com dinheiro**

> **Revisada em 2026-08-27**: com a série em 2013–2025, as metas de quantidade passam a exigir
> cobertura das **duas eras de sensor**, não só de anos diferentes.
>
> **Revisada em 2026-08-31 (expansão para ~25 AOIs) — leia isto antes de tudo:**
> as metas de quantidade deixam de ser **por site** e passam a ser **por estrato (bioma × era de
> sensor)**, definidas em `data/labels_manual/_cotas.csv` (SV-09b). Escalar 60 polígonos por site
> para 25 AOIs daria ~1.500 polígonos ≈ **21 horas de trabalho humano**, que não cabem nos dias
> restantes. A correção não é apressar a rotulagem: é que **a unidade de amostragem "site" estava
> errada**. O classificador não tem `site_id` como feature — rotular a segunda AOI de Hortolândia não
> ensina nada que a primeira não tenha ensinado. O que ele ainda não viu é **outro tipo de solo**.
> Daí ~240 polígonos em ~6 estratos ≈ **3,5 h**, cobrindo mais diversidade espectral que os 1.500.
>
> **Esta tarefa tem timebox duro de 4 horas.** Ao fim das 4 h, entrega-se o que houver, com a
> contagem por estrato reportada. Ela não bloqueia a V1 — SV-27/SV-12/SV-13 rodam com labels
> automáticos, e o resultado desta rotulagem entra em SV-16.

## Contexto

O `CLAUDE.md` decide que a classe "solo exposto / em obras" precisa de rotulagem manual
complementar, porque o WorldCover não a captura. Esta é a única tarefa do plano que **não pode
ser feita por um agente** — exige julgamento visual sobre imagem.

**Ela não bloqueia a V1.** SV-11/SV-12/SV-13 rodam com labels WorldCover puros (`dataset v0.1`).
Esta rotulagem entra em SV-16 para produzir o `dataset v1.0` e melhorar justamente a classe que
mais importa para o projeto. Se o tempo não permitir, a V1 fecha sem ela e a limitação é
documentada — mas o valor do projeto cai.

## Objetivo

Um conjunto de polígonos rotulados por humano, commitado no repo, cobrindo a classe crítica e
seus confusores.

## Escopo — o que fazer

1. Ler `docs/guia-rotulagem.md` (produzido em SV-09) inteiro antes de começar. Sério.
2. Abrir no QGIS: `data/raw/s2/{site}/{ano}.tif` (RGB e falsa-cor SWIR), os PNGs de
   `reports/figures/rotulagem/`, e `data/interim/candidatos_{site}.geojson`.
3. Rotular polígonos em uma cópia de `data/labels_manual/_template.geojson`, salva como
   `data/labels_manual/{site_id}.geojson`.
4. **Metas de quantidade — por estrato, não por site** (revisão de 31/08). A fonte de verdade é
   `data/labels_manual/_cotas.csv`, gerado por SV-09b. Por estrato existente:
   - **≥ 15 polígonos de classe 3** (solo exposto/obras), preferencialmente em anos de fase
     `durante` — é onde o canteiro de fato existe.
   - **≥ 20 negativos difíceis** (classes 2 e 4 que *parecem* obra **naquele bioma** — o confusor
     muda: lavoura colhida no Sudeste, campo nativo seco no Pampa, **caatinga decídua no período seco
     no Nordeste**, que é o mais traiçoeiro de todos). Estes valem tanto quanto os positivos.
   - **≥ 5 âncoras** das classes 1 e 5.
   - **Total ~40 por estrato · ~240 no geral.**

   Duas garantias que a estratificação não pode perder de vista:
   - **≥ 12 polígonos de classe 3 na era Landsat (2013–2018)** no total. Metade da série é Landsat,
     e sem exemplo de obra a 30 m o modelo não reconhece canteiro justamente no período em que os
     data centers mais antigos foram construídos.
   - **Nenhum estrato zerado.** Terminar com 90 polígonos do Sudeste e nenhum do Nordeste é o pior
     resultado possível desta sessão — seria pagar as 4 h e não comprar diversidade nenhuma.
     **Rode os estratos em ordem crescente de cobertura atual**, começando pelo que tem menos.
   - Polígonos de **0.5 a 20 ha** (≥ 1 ha nos estratos Landsat). Polígono gigante mistura classes;
     minúsculo não sobrevive à amostragem.
5. Preencher **todos** os campos do schema, incluindo `confianca` e `autor`. Marque `confianca: baixa`
   sem constrangimento — SV-16 pode filtrar por confiança, mas só se o campo estiver honesto.
6. **Controle de consistência.** O objetivo é detectar critério ambíguo *antes* de ele contaminar
   120 polígonos:
   - **Se houver dois rotuladores:** cada um usa `data/labels_manual/{site_id}_{autor}.geojson` e
     ambos rotulam **10 polígonos em comum**, para medir concordância entre pessoas.
   - **Se a rotulagem for solo** (cenário atual do projeto): rotule os 10 primeiros polígonos,
     siga com o resto, e ao final **volte e rotule os mesmos 10 de novo, sem olhar a primeira
     resposta**. A concordância consigo mesmo mede a mesma coisa: se você discorda de você mesmo em
     mais de 2 de 10, o guia está ambíguo e o problema está nele, não em você.
7. Commitar os GeoJSON. **Sim, estes vão para o git** — são leves e são o ativo mais caro do repo
   (decisão D-07 do plano).

## Fora de escopo

- Alterar os critérios de classe (se o guia estiver ambíguo, **anote e avise**, não improvise
  em silêncio — improviso não documentado vira label inconsistente).
- Rotular pixel a pixel. Polígonos homogêneos.
- Rotular fora da AOI dos sites.

## Critérios de aceite

- [ ] `data/labels_manual/{site_id}.geojson` existe e está commitado.
- [ ] **Todo estrato de `_cotas.csv` tem pelo menos 1 polígono de classe 3.** Estrato zerado é falha
      da sessão, mesmo que o total esteja alto.
- [ ] ≥ 15 polígonos de classe 3 por estrato, **ou** a cota do estrato foi atingida.
- [ ] ≥ 12 polígonos de classe 3 na era Landsat, no total.
- [ ] ≥ 20 negativos difíceis por estrato.
- [ ] ≥ 200 polígonos no total, cobrindo ≥ 4 anos distintos e ≥ 4 AOIs distintas — **ou** o timebox
      de 4 h estourou e a contagem parcial por estrato está reportada. **Estourar o timebox é uma
      opção válida; empurrar a rotulagem para o dia seguinte não é.**
- [ ] Todos os campos do schema preenchidos, sem `null` em `classe_id`, `ano`, `autor`, `confianca`.
- [ ] Todas as geometrias são polígonos válidos (`geometry.is_valid`), em EPSG:4326, dentro da AOI do site.
- [ ] Nenhum polígono se sobrepõe a outro com classe diferente (conflito de label).
- [ ] Concordância ≥ 80% nos 10 polígonos de controle — entre rotuladores, ou consigo mesmo na
      segunda passada, conforme o item 6. Abaixo disso, o guia está ambíguo: **corrija o guia e
      revise os polígonos afetados**, não force o número.

## Cenários de teste

1. `geopandas.read_file(...)` carrega sem erro; `crs` é EPSG:4326.
2. `gdf.geometry.is_valid.all() == True`.
3. `gdf.groupby(['classe_id','ano']).size()` mostra a distribuição pedida.
4. Overlay espacial do arquivo consigo mesmo não retorna par com `classe_id` divergente.
5. Todos os polígonos caem dentro do buffer do site correspondente.

## Como reportar

Informe: contagem por classe × ano × site, quanto tempo levou, quais casos o guia não resolveu
(isso volta como correção em `docs/guia-rotulagem.md`), e a concordância entre rotuladores se
houve mais de um.
