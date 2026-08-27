# SV-11 — Dataset de modelagem v0.1 (multi-sensor, split sem vazamento)

- **Fase:** 2 — Dataset · **Data-alvo:** 04/09 · **Tamanho:** M (~3h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-07 (labels), SV-08 (features das duas eras)
- **Desbloqueia:** SV-12
- **Tem seção de risco:** não (mas o vazamento de dados é o risco técnico #1 do projeto)

> **Revisada em 2026-08-27**: o dataset agora une **duas eras de sensor** (Landsat 30 m 2013–2018,
> Sentinel-2 10 m 2019–2025) e **duas resoluções**. Isso cria duas armadilhas novas — vazamento
> entre sensores e desequilíbrio por resolução — tratadas abaixo.

## Contexto

O `CLAUDE.md` é explícito: **"nunca split aleatório por pixel — usar split espacial e/ou temporal
explícito para evitar vazamento"**. Pixels vizinhos em imagem de satélite são quase idênticos; um
split aleatório coloca o vizinho do pixel de treino no teste e o modelo reporta 97% de acurácia que
não significa nada. Uma banca de MBA vai perguntar sobre isso — e deve.

Com a série multi-sensor, há **três** vetores de vazamento a fechar, não um:
1. **Espacial** — pixels vizinhos em treino e teste.
2. **Temporal** — o mesmo lugar em anos consecutivos é quase idêntico.
3. **Entre sensores (novo)** — o mesmo lugar, no **mesmo ano**, aparece duas vezes (uma por sensor)
   nos anos de sobreposição. Se uma cópia cai no treino e a outra no teste, é vazamento quase
   perfeito, e é invisível se você só olhar para `linha`/`coluna`.

Este dataset usa labels da fonte definida em SV-05b/SV-07. A rotulagem manual (SV-10) entra depois,
em SV-16. **Não espere por ela.**

## Objetivo

Um parquet tabular (features + label + chaves de split) versionado por manifest, unindo as duas
eras, com split espacial e temporal explícito, reprodutível com seed fixo.

## Escopo — o que fazer

1. **`src/sentinela/dataset.py`**, CLI `python -m sentinela.dataset --versao v0.1`.

2. **Amostragem** (não use todos os pixels):
   - Estratificada por classe, com teto de **8.000 pixels por classe × site × ano × sensor**.
     Classes raras entram com o que houver; registre a contagem real.
   - **Equilíbrio entre eras (importante):** um pixel Landsat de 30 m cobre 9× a área de um pixel
     S2 de 10 m. Se você amostrar proporcionalmente à contagem de pixels, a era Sentinel-2 domina o
     dataset ~9 para 1 e o modelo vira, na prática, um modelo da era moderna. **O teto é por
     sensor justamente para evitar isso** — confira a distribuição final e reporte.
   - **Erosão de 1 pixel nas bordas de classe** antes de amostrar (`scipy.ndimage.binary_erosion`
     por máscara de classe): pixels de fronteira são mistos e são a maior fonte de ruído do label.
     Note que 1 pixel erodido significa 10 m no S2 e 30 m no Landsat — documente o efeito.
   - Descartar qualquer pixel com nodata em features ou em label.

3. **Chaves de split — o coração da tarefa:**
   - **`bloco_id` (espacial):** grade regular de **1 km × 1 km** sobre cada site.
     **Calcule o bloco a partir das coordenadas projetadas (`x`, `y`) em EPSG:31983, nunca a partir
     de `linha`/`coluna`** — índices de pixel significam coisas diferentes a 10 m e a 30 m, e usá-los
     faria os blocos das duas eras não coincidirem, abrindo o vazamento entre sensores.
     Id no formato `{site_id}_{i}_{j}`.
   - Blocos, não pixels, são atribuídos a treino/teste: **70/30, `random_state=42`**, estratificado
     por site. Todos os pixels de um bloco vão juntos, **de todos os anos e de todos os sensores**.
     É isso que fecha os três vetores de vazamento de uma vez.
   - **`holdout_temporal`:** reservar o ano mais recente fora do treino.
   - Colunas resultantes: `bloco_id`, `site_id`, `ano`, `sensor`, `resolucao_m`, `split`
     (`treino`|`teste`), `holdout_temporal` (bool).
   - **`bloco_id` é o grupo para `GroupKFold` em SV-12** — deixe escrito no manifest.

4. **Anos de sobreposição:** os anos em que Landsat e Sentinel-2 coexistem geram linhas nas duas
   eras. **Mantenha as duas** (elas alimentam SV-20), mas marque-as com `sobreposicao = True` para
   que SV-12/SV-13 possam excluí-las quando quiserem uma série sem duplicidade.

5. **Ponderação do label:** conforme a fonte decidida em SV-05b:
   - se o label for de **safra fixa** (WorldCover), manter `distancia_safra = abs(ano - 2021)` e
     `peso_label` decrescente — com a série indo a 2013, essa distância chega a 8 anos e a coluna
     deixa de ser detalhe e passa a ser central;
   - se o label for **anual** (MapBiomas), `distancia_safra = 0` e `peso_label = 1.0`, e registre no
     manifest que o problema de defasagem foi eliminado.

6. **Saída:** `data/processed/dataset_v0.1.parquet` (gitignored), com: as features (nomes
   **exatamente** como no manifest de SV-08) + `classe_id` + `site_id`, `ano`, `sensor`,
   `resolucao_m`, `bloco_id`, `linha`, `coluna`, `x`, `y`, `split`, `holdout_temporal`,
   `sobreposicao`, `distancia_safra`, `peso_label`.

7. **Manifest** `data/manifests/dataset_v0.1.json` (**commitado** — é o versionamento, decisão D-05):
   `versao`, `n_linhas`, `n_features`, `lista_features`, `distribuicao_classes` (total, por split e
   **por sensor**), `n_blocos` (treino/teste), `sites`, `anos`, `sensores`, `fonte_label`, `seed`,
   `regra_split` em texto, `rasters_origem` (site/ano/sensor + sha256 de cada manifest de origem),
   `sha256` do parquet, `git_sha`, `gerado_em`.

8. **`tests/test_dataset.py`** com as verificações antivazamento abaixo — **elas são o entregável
   tanto quanto o parquet.**

## Fora de escopo

- Treinar (SV-12).
- Labels manuais (SV-16).
- Oversampling/SMOTE — resolva desbalanceamento com `class_weight` em SV-12, não sintetizando pixel
  de satélite.
- Normalização — Random Forest não precisa, e adicionar agora só cria mais um passo para vazar.

## Critérios de aceite

- [ ] `data/processed/dataset_v0.1.parquet` existe; `n_linhas` entre 300k e 2M (fora disso, revisar tetos).
- [ ] **Nenhum `bloco_id` aparece em treino e teste ao mesmo tempo** (teste automatizado — bloqueante).
- [ ] **Nenhum `bloco_id` tem linhas de sensores diferentes em splits diferentes** (bloqueante).
- [ ] `bloco_id` é derivado de `x`/`y` projetados, não de `linha`/`coluna` — verificável no código
      e por teste: um mesmo ponto do terreno recebe o mesmo `bloco_id` nas duas resoluções.
- [ ] As duas eras estão representadas no treino **e** no teste; nenhuma responde por mais de ~70%
      das linhas.
- [ ] As 5 classes estão presentes no treino e no teste. Classe 3 com < 1.000 amostras no teste é um
      achado a reportar (métricas dela ficarão instáveis).
- [ ] Nenhum `NaN` em coluna de feature.
- [ ] Rodar duas vezes com a mesma seed → **mesmo `sha256`**.
- [ ] Manifest commitado, com a regra de split escrita em português legível por quem não leu o código.
- [ ] O parquet não entrou no git.

## Cenários de teste

1. **Antivazamento espacial:** `set(blocos_treino) & set(blocos_teste) == set()`.
2. **Antivazamento entre sensores:** para todo `bloco_id`, `df.groupby('bloco_id')['split'].nunique() == 1`.
3. **Coerência de bloco entre resoluções:** tomar um ponto (x, y) fixo dentro da AOI, localizar a
   linha Landsat e a linha Sentinel-2 que o contêm, e conferir que ambas têm o mesmo `bloco_id`.
   **Se não tiverem, o vazamento entre sensores está aberto — pare.**
4. **Sem duplicata:** nenhum par (`site_id`, `ano`, `sensor`, `linha`, `coluna`) aparece duas vezes.
5. **Sanidade do split:** 25%–35% das linhas em teste.
6. **Determinismo:** duas execuções → mesmo hash.
7. **Nomes de feature:** `lista_features` idêntica, em ordem, à do manifest de SV-08.
8. **Teste de controle (faça este):** treinar um RF rápido com split **aleatório por pixel** e
   comparar com o split por bloco. Se o aleatório for muito melhor, isso **confirma** que o vazamento
   era real e que o split por bloco funciona. Registre os dois números — é excelente material para a
   apresentação da banca.
9. **Teste de controle #2 (novo, específico do multi-sensor):** treinar só na era Landsat e testar só
   na era Sentinel-2, e vice-versa. Se a queda for brutal, a harmonização de SV-02b não resolveu e
   SV-12 precisará tratar `sensor` explicitamente. Registre o número — ele alimenta SV-20.

## Como reportar

Informe: `n_linhas`, distribuição de classes por split **e por sensor**, nº de blocos em treino/teste,
quantos pixels a erosão descartou em cada era, e os resultados dos dois testes de controle (itens 8 e
9) — explicitamente, porque justificam as duas decisões de arquitetura mais importantes do projeto.
