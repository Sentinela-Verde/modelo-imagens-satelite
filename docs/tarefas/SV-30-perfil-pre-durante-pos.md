# SV-30 — Perfil pré / durante / pós por AOI e assinatura territorial agregada

- **Fase:** 3 — Análise · **Data-alvo:** 07–08/09 · **Tamanho:** G (~4h)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-14 (inferência nas AOIs), SV-15 (contrato de output), SV-29 (controles)
- **Desbloqueia:** SV-31, SV-17, SV-19b
- **Tem seção de risco:** **SIM** (produz afirmações quantitativas sobre empresas nomeadas)

## Contexto

**Esta é a tarefa pela qual a expansão de 3 para ~25 AOIs existe.** Com 3 sites, o resultado do
projeto era "aqui está um classificador de cobertura do solo que funciona". Com ~25 AOIs e um grupo
de controle pareado, o resultado passa a ser: **"existe (ou não existe) uma assinatura territorial
recorrente na implantação de data centers no Brasil, e ela tem esta forma."** É uma conclusão de outra
categoria, e é o que justifica ter gasto o orçamento na expansão em vez de no Deep Learning.

O enquadramento pré/durante/pós **já foi definido pelo time** na lista de 20 do Notion e é o que esta
tarefa consome (via `periodo_pre` / `periodo_durante` / `periodo_pos` em `config/sites.geojson`):
pré = 3 anos antes do início da obra · durante = início da obra até a operação · pós = ano seguinte
à operação até 2025.

## Objetivo

Uma tabela por AOI × ano com áreas e índices por classe, alinhada em **tempo relativo ao evento**
(não em tempo de calendário), com contraste contra o controle pareado — e a curva agregada que sai
disso.

## Escopo — o que fazer

1. **Tabela base** `outputs/perfil_aoi_ano.csv`, reutilizando o output de SV-15 (não recalcule área
   por outro caminho — dois caminhos divergem e ninguém sabe qual está certo):
   `aoi_id`, `tipo` (`tratamento`|`controle`), `pareado_com`, `ano`, `sensor`, `resolucao_m`,
   `fase` (`pre`|`durante`|`pos`|`fora`), **`t_relativo`** (`ano - ano_inicio_obra`),
   área em ha por classe (5 colunas), `pct_` por classe, NDVI/NDBI/NDWI médios da AOI,
   e `precisao_coordenada` propagado de SV-25.

   **`t_relativo` é a chave da tarefa.** Uma obra de 2015 e uma de 2022 não são comparáveis no eixo
   de calendário, mas são no eixo do evento. É isso que permite empilhar ~25 casos numa curva só.

2. **Deltas por AOI**, com a mesma definição para todas: pré = média dos anos de fase `pre`;
   pós = média dos anos de fase `pos`. Para cada classe e cada índice:
   `delta_absoluto` (ha), `delta_relativo` (%), e — o número que importa —
   **`delta_liquido` = delta do tratamento − delta do controle pareado.**
   Uma AOI sem controle aceitável (`ruim` em SV-29) entra na tabela com `delta_liquido` **nulo e
   marcado**, não com o delta bruto travestido de líquido.

3. **Curva agregada** `outputs/assinatura_agregada.csv` + figura: mediana e faixa interquartil de
   cada métrica em função de `t_relativo`, de −3 a +6 anos, sobre as AOIs com pareamento aceitável.
   **Mediana e IQR, não média e desvio** — com N ~20 e casos muito heterogêneos (um campus de 400 MW
   e um prédio de 3 MW), a média é dominada pelo maior caso.

4. **Recorte por estrato**, porque é onde pode estar o achado de verdade: a curva por região/bioma,
   por porte (nº de prédios como proxy) e por era de sensor. Se a assinatura do Sudeste não se repetir
   no Nordeste, **isso é resultado**, não falha — e é mais interessante que a curva média.

5. **Controle de qualidade da leitura — obrigatório, e é o que impede as três leituras erradas mais
   prováveis:**
   - **Degrau de sensor:** a troca Landsat→S2 acontece em 2019 e cai bem no meio do período de obra de
     vários casos. Toda série tem que carregar `sensor` visível na figura, e o viés medido em SV-20
     precisa estar aplicado ou declarado. **Uma queda de vegetação em 2019 que na verdade é troca de
     instrumento é o erro mais provável do projeto inteiro** — o plano já classifica isso como risco
     crítico desde 27/08.
   - **Confundidor climático:** se a série de precipitação de SV-28 não existir (e não vai existir,
     porque é da frente de Engenharia), **declare a limitação em cada afirmação de queda de NDVI.**
     Não é opcional. É a primeira pergunta que a banca faz.
   - **Séries incompletas:** AOIs com anos faltando (de SV-26) entram com lacuna explícita, nunca com
     interpolação silenciosa.

6. **Ficha por AOI** — `reports/fichas/{aoi_id}.md` + figura: a série temporal de área por classe, com
   as três fases sombreadas, o controle sobreposto, e um parágrafo em linguagem simples. São as fichas
   que alimentam a demo de SV-19b, e é o que a banca vai olhar. Faça as **do tier 1** primeiro; se o
   tempo apertar, as de tier 2 saem só como linha na tabela agregada.

## Fora de escopo

- Prever impacto de área candidata (SV-31).
- Coletar população, PIB, MW (SV-28 — não é deste repositório).
- Inferência causal formal. Ver a seção de risco.

## Seção de risco

| Risco | Por que importa | Mitigação |
|---|---|---|
| **Afirmar causa onde só há contraste** | O output nomeia empresas reais. "O data center X destruiu N ha" é uma acusação; "a AOI de X perdeu N ha contra M ha no controle pareado" é uma medida | Linguagem de contraste obrigatória **no CSV e na figura**, não só no rodapé do relatório. Cada número sai acompanhado do seu controle |
| **Degrau de sensor lido como impacto** | A troca de 2019 coincide com o período de obra de vários casos | `sensor` visível em toda série e figura; viés de SV-20 aplicado ou declarado; **nenhuma conclusão apoiada só na transição 2018→2019** |
| **Clima não controlado** | Ano seco derruba NDVI em todo lugar | Limitação declarada em toda afirmação de vegetação; requisito registrado em SV-28 para a frente de Engenharia |
| **Coordenada aproximada tratada como exata** | Uma AOI de `precisao: aproximada` pode estar medindo o terreno do vizinho | `precisao_coordenada` propagado até o CSV final; AOIs `inferida` **excluídas do agregado** e reportadas à parte |
| **Generalizar de N pequeno** | ~20 casos, muito heterogêneos, quase todos no Sudeste | Reportar N por estrato em toda afirmação; IQR sempre visível; não apresentar mediana de estrato com N < 3 |

## Critérios de aceite

- [ ] `outputs/perfil_aoi_ano.csv` cobre todas as AOIs ativas (tratamento e controle) × todos os anos
      com dado, com `fase` e `t_relativo` preenchidos.
- [ ] As áreas batem com o output de SV-15 para as AOIs em comum (diferença < 0,1%) — se não baterem,
      há dois caminhos de cálculo e um está errado.
- [ ] `delta_liquido` existe para toda AOI de tratamento com controle `bom`/`aceitavel`, e é nulo e
      marcado para as demais.
- [ ] `outputs/assinatura_agregada.csv` + figura com mediana e IQR por `t_relativo`.
- [ ] Toda figura de série temporal indica visualmente onde o sensor muda.
- [ ] Nenhuma AOI com `precisao_coordenada: inferida` entra no agregado.
- [ ] Fichas geradas para 100% do tier 1.
- [ ] **Teste de linguagem:** ler 5 afirmações do relatório em voz alta e verificar que nenhuma diz ou
      insinua que o data center *causou* algo. Se disser, reescreva.
- [ ] O relatório declara N por estrato e as três limitações (clima, sensor, N pequeno).

## Cenários de teste

1. Para `ascenty-vinhedo`: `t_relativo == 0` cai no ano de início de obra registrado.
2. Uma AOI cuja obra começou em 2015 e outra em 2022 se sobrepõem corretamente no eixo `t_relativo`.
3. AOI sem controle aceitável → `delta_liquido` nulo, não zero, não bruto.
4. AOI com ano faltando → lacuna na série, sem interpolação.
5. Recalcular a área de uma AOI/ano por caminho independente → bate com SV-15.
6. **Teste do controle negativo:** rodar o pipeline de delta sobre **um par controle × controle**.
   O `delta_liquido` deve ficar próximo de zero. Se der grande, o método está medindo ruído de
   pareamento e não impacto — **pare e reporte antes de publicar qualquer número de tratamento.**

## Como reportar

Informe: nº de AOIs no agregado e quantas foram excluídas (e por quê), a curva agregada por
`t_relativo`, os deltas líquidos por AOI ordenados, o recorte por estrato com N de cada um, o
resultado do teste de controle negativo, e as três a cinco afirmações que o projeto pode sustentar —
**e uma que não pode**, escrita explicitamente. Essa última é a mais valiosa numa banca.
