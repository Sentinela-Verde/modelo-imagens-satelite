# SV-26 — Execução do pipeline de dados no conjunto expandido (SV-06 / SV-06b / SV-07 / SV-08)

- **Fase:** 1b — Expansão · **Data-alvo:** 02–03/09 · **Tamanho:** G (~2h de trabalho + **5 a 9 h de relógio de parede**)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-25
- **Desbloqueia:** SV-27, SV-09b
- **Tem seção de risco:** não

## Contexto

**Não há código novo de ingestão nesta tarefa.** SV-06, SV-06b, SV-07 e SV-08 já estão implementados,
já têm CLI com `--site all`, já são idempotentes e já produziram 48 rasters + labels + features para
3 sites. O que muda é a **escala**: de 3 AOIs para ~25.

Esta tarefa existe separada porque o custo dela não é de escrita de código, é de **relógio de parede
e de gestão de falhas**. Ela precisa ser tratada como uma operação: disparar cedo, monitorar, retomar
o que falhar, e — o ponto crítico — **não bloquear a trilha de modelagem enquanto roda**.

### O orçamento medido, e o que ele projeta

Números reais da execução de 27/08 (3 sites):

| Item | 3 sites (medido) | ~25 AOIs novas (projetado) |
|---|---|---|
| Rasters S2 (7 anos) | 21 · 7,8 MB cada · 161 MB | 175 · ~1,4 GB |
| Rasters Landsat (9 anos) | 27 · ~1 MB cada · 27 MB | 225 · ~230 MB |
| Rasters de label (13 anos) | 39 · 1,5 MB | 325 · ~13 MB |
| Stack de features | 894 MB | **~7,5 GB** |
| **Total de exports do Earth Engine** | ~87 | **~725** |
| **Relógio de parede** | ~30–45 min | **~5–9 h** |

Disco livre na máquina hoje: **26 GB**. A expansão consome ~9–10 GB. Cabe, mas a folga cai para
~16 GB e some se alguém repetir a ingestão com `--force`. Ver "Controle de disco" abaixo.

## Objetivo

`data/raw/`, `data/interim/features/` e `data/raw/labels/` completos e validados para todas as AOIs
ativas, com o mesmo contrato de grade, bandas e manifest que já vale para as 3 originais.

## Escopo — o que fazer

1. **Disparar na ordem certa, e cedo no dia:**
   `SV-06b (Landsat) → SV-06 (S2) → SV-07 (labels) → SV-08 (features)`.
   Landsat primeiro **de propósito**: SV-06 exige que a grade de 10 m seja refinamento exato da grade
   de 30 m, e é mais barato descobrir um problema de origem de grade nos rasters de 1 MB do que nos
   de 7,8 MB.

2. **Execução em lote com retomada.** Um wrapper
   `python -m sentinela.gee.executar_lote --etapa <ingestao|labels|features> --tier <1|2|all>`:
   - Itera as AOIs ativas de `config/sites.geojson`, chamando os CLIs existentes.
     **Não reimplemente nada** — se algo estiver faltando lá, corrija lá.
   - **Retoma de onde parou**: as tarefas já são idempotentes por manifest; confie nisso e rode de
     novo em vez de inventar controle de estado paralelo.
   - Grava `data/manifests/execucao_lote_{etapa}.json`: por AOI/ano, `status`
     (`ok`|`falha`|`pulado`), mensagem de erro, duração, tentativa.
   - **Backoff em erro de quota do Earth Engine** (429/`too many`): espera exponencial, até 3
     tentativas por raster, e segue para o próximo em vez de abortar o lote inteiro.
     Um lote de 725 exports que morre no item 300 por causa de um 429 custa o dia.

3. **Ordem de prioridade dentro do lote: tier 1 primeiro, tier 2 depois.** Se o relógio estourar, o
   que sobra sem ingerir é tier 2 — que não entra na rotulagem nem no treino. Se o lote for na ordem
   alfabética, o que sobra é aleatório, e pode ser justamente a AOI que sustenta o único bioma novo.

4. **Controle de disco (obrigatório, não opcional):**
   - Checar espaço livre **antes** de iniciar cada etapa; abortar com mensagem clara se houver menos
     de **12 GB** livres. Um lote que enche o disco em 80% corrompe o que estava escrevendo.
   - Gravar o stack de features de SV-08 como **int16 com fator de escala** em vez de float32, se ele
     ainda não for. Os índices espectrais vivem em [-1, 1]; float32 aqui é o dobro do tamanho sem
     ganho de informação, e é o que faz `data/interim/features` ser o maior diretório do repo.
   - `git status` continua limpo quanto a `.tif` — a regra do `CLAUDE.md` não muda com a escala.

5. **Relatório de qualidade agregado** — `reports/qualidade_ingestao.csv` e um resumo em
   `reports/qualidade_ingestao.md`: por AOI × ano × sensor, `pct_pixels_validos`, `n_imagens_usadas`,
   `tamanho_mb`, `status`. E a lista explícita de:
   - AOI × ano com `pct_pixels_validos < 90%` (o limiar já definido em SV-06);
   - **AOIs em que algum ano falhou de vez.** Estas precisam de decisão: ou entram com série
     incompleta e a lacuna documentada, ou saem (`ativo: false`). **Decida e registre — não deixe uma
     AOI com buraco de 3 anos entrar em SV-30 em silêncio.**

6. **Validação de contrato, rodando sobre tudo** (é a mesma de SV-06/06b, aplicada em lote):
   grade idêntica entre anos da mesma AOI; grade de 10 m refinando exatamente a de 30 m; nomes de
   banda canônicos; sanidade física da reflectância. Um AOI que falhar qualquer uma delas é **falha
   bloqueante**, não aviso.

## Fora de escopo

- Alterar a lógica de ingestão, máscara de nuvem, harmonização ou fonte de label. **Nada de ADR-003 ou
  ADR-004 é reaberto aqui.** Se a expansão para outros biomas expuser um problema de harmonização,
  isso é um **achado a reportar**, não uma correção a fazer nesta tarefa a 12 dias da entrega.
- Rotulagem manual (SV-09b/SV-10).
- Construir o dataset tabular (SV-27).

## Critérios de aceite

- [ ] Toda AOI ativa tem série completa em `data/raw/landsat/`, `data/raw/s2/`, `data/raw/labels/` e
      `data/interim/features/`, **ou** está registrada em `reports/qualidade_ingestao.md` com a lacuna
      e a decisão tomada.
- [ ] `pct_pixels_validos >= 90%` em ≥ 95% dos pares AOI × ano; os desvios estão listados.
- [ ] Para toda AOI: `transform` e `shape` idênticos entre todos os anos do mesmo sensor (teste
      automatizado sobre todas as AOIs, não sobre uma amostra).
- [ ] Para toda AOI: `(origem_10m - origem_30m) % 30 == 0` nos dois eixos.
- [ ] Todos os manifests novos commitados; `sha256` conferindo.
- [ ] `git status` limpo quanto a `.tif`.
- [ ] Espaço livre em disco ao final **> 10 GB** — reportado.
- [ ] Rodar o lote de novo sem `--force` termina em minutos e não rebaixa nada.
- [ ] **Inspeção visual de 3 AOIs novas de biomas diferentes** (composto RGB do ano mais recente):
      parecem imagens, sem faixa de nuvem grosseira e sem buraco. Fora do Sudeste a janela seca
      jun–set de `config/params.yml` pode não ser a melhor estação — **se a Amazônia ou o Nordeste
      vierem ruins, reporte como achado**, com o número, e deixe a decisão de ajustar a janela para o
      usuário. Ajustar `mes_inicio`/`mes_fim` por região é uma mudança de contrato que afeta a
      comparabilidade entre AOIs e não se faz sozinho.

## Cenários de teste

1. Lote de uma AOI nova, uma etapa → arquivos + manifests + linha no relatório de execução.
2. Interromper o lote no meio (Ctrl+C) e relançar → retoma sem refazer o que já estava pronto.
3. Simular erro de quota (mock 429) → backoff acontece, o item é remarcado e o lote **não aborta**.
4. Disco simulado abaixo de 12 GB → aborta antes de escrever qualquer coisa.
5. Contrato de grade: para 5 AOIs sorteadas, conferir alinhamento 10 m vs. 30 m.
6. Uma AOI de bioma novo (Nordeste/Sul) → conferir que a reflectância passa na sanidade física.
   *Solo de Caatinga é muito mais claro que latossolo do Sudeste; se o teste falhar, o limiar de
   sanidade é que está estreito demais, e isso é achado — não force o número.*

## Como reportar

Informe: nº de rasters gerados por etapa e sensor, relógio de parede total e por etapa, taxa de falha
e o que causou, AOIs com série incompleta e a decisão de cada uma, `pct_pixels_validos` médio e mínimo
por região, disco consumido e restante, e **qualquer sinal de que a janela sazonal jun–set não serve
para as regiões novas**.
