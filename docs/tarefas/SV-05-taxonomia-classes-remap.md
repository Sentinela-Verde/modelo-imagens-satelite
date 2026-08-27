# SV-05 — Taxonomia de classes + remap WorldCover em código

- **Fase:** 1 — Dados · **Data-alvo:** 28/08 · **Tamanho:** P (~1h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-01
- **Desbloqueia:** SV-05b, SV-07
- **Tem seção de risco:** não

> **Nota de 2026-08-27:** a janela do projeto foi estendida a 2013–2025 (SV-02), o que colocou a
> fonte de labels em reavaliação (**SV-05b**: WorldCover de safra fixa vs. MapBiomas anual).
> **A taxonomia das 5 classes não muda em cenário nenhum** — é decisão fechada do time. O que pode
> mudar é *de qual legenda* se remapeia para ela. Por isso, escreva `sentinela/classes.py` de forma a
> aceitar **mais de uma tabela de remap** (uma por fonte), em vez de assumir só o WorldCover.

## Contexto

As 5 classes já estão **decididas** no `CLAUDE.md` — esta tarefa **não redecide nada**, ela
transforma a decisão em uma única fonte de verdade em código, para que ingestão, treino,
inferência e export nunca divirjam sobre o que é a classe 3.

Classes (do `CLAUDE.md`):
1. Vegetação densa
2. Vegetação rala / pasto / agricultura leve
3. **Solo exposto / em obras** — classe crítica, sinal de início de construção
4. Área construída / urbana
5. Água

Infraestrutura viária **não** é classe separada na V1 — entra em "construída".

## Objetivo

Um módulo e um YAML que definem id, nome, cor e mapeamento WorldCover→classe, usados por todo
o resto do pipeline. Ninguém mais escreve `if classe == 3` com número solto.

## Escopo — o que fazer

1. **`config/classes.yml`** — por classe: `id`, `slug` (`solo_exposto_obras`), `nome_exibicao`,
   `cor_hex` (para os mapas de SV-14; use cores intuitivas: verde escuro, verde claro, marrom/laranja,
   cinza/vermelho, azul), `descricao` (1–2 frases sobre o que entra e o que não entra).
   Inclua também `0: nodata`.

2. **Mapeamento ESA WorldCover v200 → nossas 5 classes.** Proposta a implementar
   (se discordar de alguma linha, **pare e sinalize** antes de mudar — é decisão de time):

| WorldCover | Descrição | → Nossa classe | Observação |
|---|---|---|---|
| 10 | Tree cover | 1 vegetação_densa | |
| 20 | Shrubland | 2 vegetacao_rala | |
| 30 | Grassland | 2 vegetacao_rala | |
| 40 | Cropland | 2 vegetacao_rala | agricultura leve, conforme `CLAUDE.md` |
| 50 | Built-up | 4 construida_urbana | |
| 60 | Bare / sparse vegetation | 3 solo_exposto_obras | **label fraco**: WorldCover marca solo natural, não obra |
| 70 | Snow and ice | 0 nodata | não ocorre na AOI |
| 80 | Permanent water bodies | 5 agua | |
| 90 | Herbaceous wetland | 0 nodata | ambíguo entre água e vegetação rala — descartar é mais seguro que rotular errado |
| 95 | Mangroves | 0 nodata | não ocorre na AOI |
| 100 | Moss and lichen | 0 nodata | não ocorre na AOI |

3. **`src/sentinela/classes.py`** — carrega o YAML e expõe:
   `CLASSES` (dict id→metadados), `SLUG_TO_ID`, `ID_TO_SLUG`,
   `REMAPS` (dict `fonte -> {codigo_origem: classe_id}`, começando com a chave `worldcover` e
   **preparado para receber `mapbiomas` sem alteração de código** — a tabela vem do YAML),
   `remap(array, fonte) -> array` (numpy, vetorizado, valores desconhecidos → 0),
   `colormap()` (dict id→RGB tuple, para escrever no GeoTIFF em SV-14).

4. **`docs/classes.md`** — a tabela de classes com descrição e a tabela de remap acima, mais
   uma nota explícita: *a classe 3 vinda do WorldCover é solo natural exposto, não canteiro de obra;
   por isso existe a rotulagem manual complementar de SV-09/SV-10*.

5. **`tests/test_classes.py`** — cobrindo os casos abaixo.

## Fora de escopo

- Baixar o WorldCover (SV-07).
- Rotulagem manual (SV-09/SV-10).
- Qualquer decisão nova sobre classes — se aparecer divergência com o Notion, **é bloqueante**: pare e avise.

## Critérios de aceite

- [ ] `config/classes.yml` tem as 5 classes + nodata, com id, slug, nome, cor e descrição.
- [ ] `remap(array, "worldcover")` mapeia corretamente os 11 códigos da tabela acima.
- [ ] Adicionar uma nova fonte de remap exige **apenas** editar o YAML, sem tocar em `classes.py`
      (teste: cadastre uma fonte fictícia no YAML e confirme que `remap(array, "ficticia")` funciona).
- [ ] Valor desconhecido (ex.: 42) vira `0`, não estoura exceção.
- [ ] `remap` preserva shape e dtype do array de entrada.
- [ ] Nenhum outro arquivo do repo hardcoda número de classe — tudo importa de `sentinela.classes`.
- [ ] `pytest tests/test_classes.py` passa.

## Cenários de teste

1. `remap(np.array([10,20,30,40,50,60,70,80,90,95,100]), "worldcover")` → `[1,2,2,2,2,4,3,0,5,0,0]`
   — **atenção**, confira a ordem contra a tabela ao escrever o teste, não copie este vetor sem verificar.
2. `remap(np.array([42]), "worldcover")` → `[0]`.
3. Array 2D 100×100 entra, array 2D 100×100 sai.
4. `len(CLASSES) == 6` (5 classes + nodata) e todos os `slug` são únicos.
5. `colormap()` retorna uma cor para cada id, sem repetição.

## Como reportar

Informe: o YAML final, e **explicitamente** se você discordou de alguma linha do remap proposto
(especialmente 40 Cropland e 90 Wetland) — isso precisa ir para o time, não ficar no commit.
