# SV-24 — Consolidação, deduplicação por AOI e tiering da lista de data centers

- **Fase:** 1b — Expansão · **Data-alvo:** 31/08 · **Tamanho:** M (~2h30 agente + ~40 min de decisão humana)
- **Responsável sugerido:** `data-engineer` (produz) · **humano** (aprova o tier 1)
- **Bloqueado por:** — (nada; pode começar imediatamente)
- **Desbloqueia:** SV-25
- **Tem seção de risco:** não

## Contexto

O projeto foi construído para **3 sites** (`ascenty-vinhedo`, `odata-hortolandia`, `scala-tambore`).
O time levantou no Notion **duas listas** de candidatos que o usuário decidiu incorporar:

- **"20 Data Centers De 2016 a 2026"** — tem ano de construção, ano de operação, status em 2026 e
  períodos pré/durante/pós já sugeridos. Só 4 linhas têm coordenada; o resto está "A validar".
- **"Lista dos 30 data centers que analisei..."** — tem link da fonte, UF, região, cidade e empresa,
  mas **nenhuma coordenada** e nenhum ano.

As duas listas se sobrepõem, e — o ponto mais importante desta tarefa — **elas listam prédios, não
áreas de estudo**. A unidade de análise deste repositório é a **AOI: um buffer de 5 km em volta de um
ponto** (ADR-001). Ascenty Hortolândia 2, 3, 4, 5 e HTL6 são cinco prédios **dentro de uma mesma AOI
de 5 km**. Ingerir os cinco significaria baixar cinco vezes o mesmo raster.

Isso corta custo, mas há um ganho maior: **um campus com prédios de 2018, 2019, 2021 e 2022 não é uma
duplicata — é uma AOI com uma escada de eventos de construção**, que vale mais que quatro AOIs de
evento único. A deduplicação precisa **preservar** essa informação como metadado da AOI, não descartá-la.

## Objetivo

Uma tabela única, versionada e auditável de AOIs candidatas, deduplicada no nível de AOI, com
elegibilidade avaliada por critério escrito e separada em **tier 1** (pipeline completo + rotulagem
manual) e **tier 2** (pipeline sem rotulagem, usada como teste de generalização fora-da-amostra).

## Escopo — o que fazer

1. **Extrair as duas tabelas do Notion** para `data/externo/sites_notion_lista20.csv` e
   `data/externo/sites_notion_lista30.csv` (**commitados** — são leves e são a matéria-prima
   rastreável). Preserve as colunas originais **sem interpretá-las**, inclusive os "A validar" e as
   URLs de fonte. Uma coluna extra `fonte_lista` identifica a origem.

2. **Deduplicar em dois níveis**, nesta ordem, e registrar cada fusão:
   - **Nível prédio:** mesma instalação aparecendo nas duas listas com nomes diferentes
     (ex.: `Equinix SP5x` está nas duas; `Scala Campus Tamboré` é o nosso `scala-tambore`;
     `Ascenty Vinhedo 1/2` é o nosso `ascenty-vinhedo`).
   - **Nível AOI (o que importa):** prédios cujo ponto cai a **menos de 5 km** de outro viram **uma
     AOI**. Como a maioria ainda não tem coordenada nesta etapa, use a chave
     `(operador_ou_polo, município)` como proxy e marque a fusão como `provisoria: true` — SV-25
     confirma ou desfaz com a coordenada real. **Municípios diferentes nunca são fundidos
     automaticamente**, mesmo vizinhos: sinalize como `revisar_manualmente`.
   - Para cada AOI resultante, preencha `predios` como lista de objetos
     `{nome, ano_construcao, ano_operacao, status, fonte}` — é isso que preserva a escada de eventos.

3. **Aplicar o critério de elegibilidade.** Uma AOI só entra no estudo se **as quatro** forem
   verdadeiras. Registre a avaliação de cada uma, inclusive das reprovadas, com a justificativa:
   - **(E1) Evento datável na janela:** existe pelo menos um prédio com início de construção
     entre **2013 e 2024** (a janela do repo é 2013–2025; um evento em 2025 não tem "pós").
     *Reprova quem só tem prédio anterior a 2013 ou projeto que ainda não começou.*
   - **(E2) Pegada visível:** o empreendimento é uma construção nova em terreno aberto
     (greenfield/brownfield) com área da ordem de **≥ 1 ha**. *Reprova colocation instalada dentro de
     prédio urbano existente* — um data center que ocupa dois andares de um edifício em Boa Viagem
     não muda um pixel de 10 m, e incluí-lo dilui o estudo com ruído.
   - **(E3) Coordenada obtível:** existe pelo menos uma fonte plausível de georreferenciamento
     (PeeringDB, página do operador com endereço, OSM, release com endereço). *Reprova quem só tem
     nome de empresa.*
   - **(E4) Sem sobreposição de AOI:** não é o mesmo buffer de 5 km de outra AOI já aceita.

4. **Classificar em tiers.** O orçamento de rotulagem manual é humano e não escala (ver SV-09b/SV-10),
   então o tier decide **onde o tempo humano é gasto**, não quem entra no estudo:
   - **Tier 1 — alvo de 12 AOIs** (inclui as 3 atuais): elegíveis, com evento datável de boa
     qualidade, e escolhidas para **maximizar diversidade de bioma e de era de sensor**, não para
     maximizar contagem. Recebem pipeline completo **+ rotulagem manual estratificada**.
   - **Tier 2 — o resto das elegíveis (alvo de 13 a 18)**: recebem ingestão, features e **inferência**,
     mas **nenhuma rotulagem manual**. São o conjunto de generalização fora-da-amostra e alimentam o
     painel pré/durante/pós de SV-30.
   - **Rejeitadas:** ficam na tabela com `elegivel: false` e o critério que reprovou. **Não apague
     linha** — a lista de rejeitados com motivo é material de apresentação e evita re-discussão.
   - Regra de seleção do tier 1, nesta ordem de prioridade: **(a)** cobrir o maior número de biomas
     distintos; **(b)** cobrir as duas eras de sensor com evento de construção (é raro: eventos
     pré-2019 são o que dá exemplo de obra a 30 m); **(c)** coordenada de fonte primária;
     **(d)** pegada maior.

5. **Saída principal:** `config/sites_candidatos.csv` (**commitado**), uma linha por AOI:
   `aoi_id` (slug estável, ex.: `ascenty-hortolandia`), `nome_exibicao`, `operador`, `municipio`,
   `uf`, `regiao`, `bioma_estimado`, `n_predios`, `predios_json`, `ano_construcao_min`,
   `ano_operacao_min`, `ano_construcao_max`, `ano_operacao_max`, `periodo_pre`, `periodo_durante`,
   `periodo_pos`, `status_2026`, `elegivel` (bool), `criterio_reprovacao`, `tier` (1|2|null),
   `fonte_lista`, `fontes_url`, `lat`, `lon` (vazios nesta etapa), `precisao_coordenada`
   (`pendente`), `observacao`.

   **Os períodos seguem a convenção da lista de 20**, que o time já adotou:
   pré = 3 anos antes do início da obra; durante = início da obra até o ano de operação;
   pós = ano seguinte à operação até 2025 (**2025, não 2026** — a série do repo termina em 2025).
   Onde o ano é intervalo (`2018–2019`), use o **primeiro** ano e registre a incerteza em `observacao`.

6. **`docs/decisoes/ADR-005-expansao-de-sites.md`**, curto e direto: o número final de AOIs, o critério
   de elegibilidade acima, a regra de dedup por AOI, a lógica dos dois tiers, e — explicitamente —
   **o que muda e o que não muda** no que já está fechado. Classes (5), fonte de labels (ADR-004),
   harmonização (ADR-003) e a janela 2013–2025 (ADR-001) **não são reabertas** por esta tarefa.

## Fora de escopo

- **Buscar coordenadas** — é SV-25 inteira, e misturar as duas coisas faz esta tarefa nunca terminar.
- Ingerir qualquer imagem.
- Reabrir classes, fonte de labels ou janela temporal.
- Coletar população, PIB, MW, área do terreno ou qualquer variável externa — **este repositório não
  coleta variável não-imagem** (ver SV-28). Copie do Notion apenas o que já está nas duas listas.

## Critérios de aceite

- [ ] `config/sites_candidatos.csv` existe, commitado, e abre em `pandas` sem erro.
- [ ] As 3 AOIs atuais aparecem com o **mesmo `aoi_id` que já está em `config/sites.geojson`**
      (`ascenty-vinhedo`, `odata-hortolandia`, `scala-tambore`) — renomear quebraria todo o
      `data/` já produzido.
- [ ] Nenhum `aoi_id` duplicado; nenhum par de AOIs elegíveis no mesmo município com o mesmo operador.
- [ ] Toda linha com `elegivel: false` tem `criterio_reprovacao` preenchido com E1/E2/E3/E4.
- [ ] O tier 1 tem entre 10 e 14 AOIs e cobre **≥ 3 biomas distintos**; se não cobrir, isso é um
      achado a reportar, não um número a forçar.
- [ ] Pelo menos **2 AOIs do tier 1 têm início de obra antes de 2019** (era Landsat) — sem isso a
      classe "solo exposto/obras" fica sem exemplo de canteiro a 30 m.
- [ ] `predios_json` de toda AOI multi-prédio lista todos os prédios com seus anos; nenhuma
      informação de ano das listas originais foi perdida na fusão.
- [ ] Os dois CSVs de origem estão commitados e é possível reconstruir cada fusão a partir deles.
- [ ] `ADR-005` está escrito e diz o número final de AOIs por tier.
- [ ] **O usuário aprovou o tier 1 antes de SV-25 começar.** Esta é a única aprovação humana da
      tarefa e ela é bloqueante: o tier 1 define onde as ~4 h de rotulagem manual vão ser gastas.

## Cenários de teste

1. Carregar o CSV e agrupar por `(municipio, operador)` → nenhum grupo com mais de uma AOI elegível.
2. Para `ascenty-hortolandia`: `n_predios >= 4` e `predios_json` contém os anos 2018/2019, 2020/2021
   e 2021/2022 vindos da lista de 20.
3. Para cada AOI elegível: `periodo_pre`, `periodo_durante` e `periodo_pos` são intervalos não vazios,
   não sobrepostos, e contidos em 2010–2025 (pré pode começar antes de 2013; registre que nesse caso
   a série do repo cobre só parte do pré).
4. Rodar o script duas vezes → CSV byte-idêntico (determinístico).
5. Conferência manual de 3 linhas contra o Notion → nome, município, operador e anos batem.

## Como reportar

Informe: nº de linhas nas duas listas originais, nº de AOIs após dedup, quantas fusões de nível prédio
e quantas de nível AOI, quantas reprovaram e por qual critério, a composição do tier 1 (AOI, bioma,
ano de obra, era de sensor) e a do tier 2, e **quais fusões estão marcadas `provisoria: true`** para
SV-25 confirmar.
