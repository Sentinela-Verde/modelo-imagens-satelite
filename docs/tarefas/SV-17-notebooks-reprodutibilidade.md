# SV-17 — Notebooks técnicos + reprodução end-to-end + model card

- **Fase:** 5 — Entrega · **Data-alvo:** 12/09 · **Tamanho:** M (~3h30)
- **Responsável sugerido:** `ml-engineer` (notebooks) + **humano** (validação do clone limpo)
- **Bloqueado por:** SV-13, SV-15, SV-20
- **Desbloqueia:** — (é entrega final)
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: o entregável (D-06) foi **confirmado e ampliado** pelo usuário para
> incluir a API/demo (SV-19/SV-19b), e os notebooks ganham a narrativa multi-sensor.

## Contexto

Item 7 da Definition of Done: qualquer pessoa do time reproduz do zero. E é o entregável para a
banca — decisão **D-06, confirmada pelo usuário em 2026-08-27**: notebook técnico + scripts
reproduzíveis + artefato de modelo versionado + model card + relatório de métricas + **API/demo
funcional** (esta última entregue por SV-19 e SV-19b, não aqui).

Os notebooks **não reimplementam nada**: eles importam de `src/sentinela/` e narram. Notebook com
lógica duplicada diverge do código na primeira mudança e é exatamente o tipo de coisa que a banca
pega.

## Objetivo

Um caminho narrado de ponta a ponta, executável, mais a prova de que um clone limpo chega ao
mesmo resultado.

## Escopo — o que fazer

1. **Quatro notebooks em `notebooks/`**, cada um curto e com texto entre as células explicando
   *por quê*, não só *o quê*:
   - **`01_dados_e_labels.ipynb`** — AOI e sites no mapa; compostos em RGB e falsa-cor **das duas
     eras** (Landsat 2013 e Sentinel-2 2025, lado a lado); a harmonização explicada com os scatter
     plots de SV-02b; o label remapeado sobreposto; distribuição de classes por site. Fecha com as
     limitações da fonte de label (ADR-004) e do buraco de 2012.
   - **`02_dataset_e_split.ipynb`** — as 17 features e por que cada uma; a amostragem estratificada;
     **o split por blocos visualizado no mapa** (treino em uma cor, teste em outra — esta figura
     vale mais que três parágrafos); e o **teste de controle de SV-11** (split aleatório vs. por
     bloco), que justifica a decisão de arquitetura mais importante do projeto.
   - **`03_baseline_e_avaliacao.ipynb`** — treino do RF, CV por grupo, matrizes de confusão,
     F1 por classe, importância de features, e a análise da classe 3 (incluindo os pixels errados
     inspecionados em SV-13).
   - **`04_output_e_serie_temporal.ipynb`** — mapas classificados lado a lado (**2013 vs. 2025** de
     cada site) e o gráfico de área por classe ao longo de 13 anos, **com a troca de sensor marcada**
     e com o resultado de SV-20 citado ao lado. **Esta é a figura que conta a história do Sentinela
     Verde** — invista nela. Fecha com a validação cruzada entre sensores, que é o que sustenta a
     leitura da série.

2. **`docs/model-card.md`** (commitado) — no formato de model card:
   uso pretendido e **usos não pretendidos** (não é laudo ambiental, não atribui causalidade),
   dados de treino e sua procedência (**as duas eras de sensor, com a harmonização declarada**),
   classes, métricas por classe no holdout **e por era** (os números reais de SV-13/SV-16),
   limitações, vieses conhecidos (região única, fonte de label, duas resoluções, viés entre sensores
   medido em SV-20), versão do modelo, autor, data.

3. **Reprodução em um comando** — `scripts/run_all.ps1` (e `.sh`) encadeando:
   `check → gee.check → sentinel2 → landsat → labels → indices → dataset → train → evaluate →`
   `predict → validacao_sensores → export_indicadores`
   Cada passo idempotente, com log do que pulou e do que rodou.

4. **`README.md` atualizado** com: o que o projeto faz, a figura da série temporal 2013–2025,
   resultado principal (macro-F1 e F1 da classe 3), setup, reprodução em um comando, **como subir a
   demo (SV-19b)**, estrutura de pastas, e links para `plano-execucao.md`, `model-card.md`,
   `schema-indicadores.md`, `api.md` e os ADRs.

5. **Validação de clone limpo (obrigatória, feita por um humano que não escreveu o código):**
   clonar em pasta nova, seguir só o README, rodar tudo. Anotar cada ponto onde travou e corrigir
   a documentação. **A tarefa não fecha sem esse teste.**

## Fora de escopo

- Slides da apresentação (fora do repo).
- Dashboard (é a frente 05).
- Reimplementar lógica dentro dos notebooks.

## Critérios de aceite

- [ ] Os 4 notebooks executam do topo ao fim sem erro (`Restart & Run All`) com os dados presentes.
- [ ] Nenhum notebook define lógica de negócio — só importa de `sentinela.*`, plota e narra.
- [ ] Notebooks commitados **com output** (as figuras são o entregável para a banca), mas **sem**
      nada sensível: sem caminho absoluto com nome de usuário, sem token, sem id de projeto GCP.
- [ ] `docs/model-card.md` completo, com os números reais e a seção de usos não pretendidos.
- [ ] O pipeline completo roda com um comando.
- [ ] **Clone limpo validado por outra pessoa**, com o relato do que travou e a doc corrigida.
- [ ] Os números do README, do model card e de `reports/avaliacao_*.md` são **os mesmos**.
      Divergência entre eles é o erro mais comum e o mais constrangedor na apresentação.

## Cenários de teste

1. `Restart & Run All` em cada notebook, do zero.
2. `grep` nos `.ipynb` por `C:\Users`, `token`, `key`, `secret` → nenhum resultado.
3. Clone limpo em outra pasta → chega ao CSV final seguindo só o README.
4. Consistência: a macro-F1 citada no README = a do model card = a de `reports/avaliacao_*.md`.
5. Tamanho: nenhum notebook com output passa de ~5 MB (imagem embutida gigante incha o repo).

## Como reportar

Informe: o que o clone limpo travou e como foi corrigido, o número final de macro-F1 e F1 da
classe 3 (geral e por era), e confirme que os quatro notebooks, o model card, os relatórios e a demo
de SV-19b contam a mesma história com os mesmos números.
