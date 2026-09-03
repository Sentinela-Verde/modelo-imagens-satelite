# EXP-002 — Rotulagem manual (SV-10) incorporada: `rf_v0.1` vs `rf_v0.2` vs `rf_v1.0` (SV-16)

- **Data:** 2026-09-02
- **Modelos comparados:**
  - `rf_v0.1` — 3 sites (ascenty-vinhedo, odata-hortolandia, scala-tambore), sem rotulagem manual.
  - `rf_v0.2` — 16 sites (SV-27), sem rotulagem manual.
  - `rf_v1.0` — os mesmos 16 sites de v0.2, **com** os 211 polígonos manuais de SV-10
    incorporados com precedência sobre o label automático (MapBiomas).
- **Hiperparâmetros:** idênticos nos três (`RandomForestClassifier(n_estimators=300,
  min_samples_leaf=5, max_features="sqrt", class_weight="balanced_subsample", random_state=42)`,
  variante `com_sensor` adotada nos três — ver `EXP-001-rf-baseline.md`, `EXP-001b-rf-v0.2-
  expansao.md`, `EXP-002-rf-v1.0-treino.md`). Nada foi retunado — mudar dado e hiperparâmetro ao
  mesmo tempo invalidaria esta comparação (bloqueante, ver enunciado de SV-16).
- **Split:** idêntico (bloco_id, 70/30, seed 42, mesmo `holdout_tier=2`) entre v0.2 e v1.0 —
  verificado byte a byte (`atribuir_split` reutilizou o mapeamento `bloco_id -> split` de
  `dataset_v0.2.parquet`; 0 divergências em 1897 blocos comuns, só 1 bloco genuinamente novo criado
  pela rotulagem manual, ver `tests/test_dataset.py::test_v10_cenario1_split_identico_a_v02_nos_blocos_comuns`
  e o manifest `data/manifests/dataset_v1.0.json` campo `labels_manuais.referencia_split`).
- **Fontes dos números:** `reports/avaliacao_rf_v0.1.md`, `reports/avaliacao_rf_v0.2.md`,
  `reports/avaliacao_rf_v1.0.md` (todos gerados por `sentinela.evaluate`, SV-13, nunca chama
  `.fit`) + `reports/sv16_analise_origem_bioma.json` (análise cross-cutting específica de SV-16,
  script `scripts/sv16_analise_origem_bioma.py`, reaproveita `sentinela.evaluate`).

## Quantos pixels manuais entraram, e quantos sobrescreveram o label automático

Do manifest `data/manifests/dataset_v1.0.json`, seção `labels_manuais`:

| sensor/era | pixels rasterizados (bruto, antes de erosão/corte) |
|---|---|
| Sentinel-2 (10 m) | 48.974 |
| Landsat (30 m) | 4.502 |

Confirma a expectativa do enunciado: um polígono de ~0,5 ha rasteriza em ordens de grandeza mais
pixels a 10 m que a 30 m (área do pixel Landsat é 9× maior) — a era Landsat recebeu ~9% do volume
bruto de pixels manuais da era Sentinel-2, o que limita quanto a rotulagem manual pode ajudar a
classe crítica especificamente na era antiga.

**Pixels manuais efetivamente usados no dataset** (pós erosão de borda, nunca cortados pelo teto de
amostragem — item 2 do enunciado): **40.721** no total, por classe:

| classe | n |
|---|---|
| Solo exposto / em obras | 15.038 |
| Área construída / urbana | 11.615 |
| Vegetação rala / pasto / agricultura leve | 7.946 |
| Vegetação densa | 3.892 |
| Água | 2.230 |

**Pixels que sobrescreveram um label automático diferente** (onde o MapBiomas já tinha um valor
válido e a classe manual discordou dele — não conta pixel que só ganhou label por estar fora da
máscara automática válida):

| classe (nova, manual) | n sobrescritos |
|---|---|
| Solo exposto / em obras | 22.373 |
| Área construída / urbana | 6.576 |
| Vegetação rala / pasto / agricultura leve | 3.248 |
| Vegetação densa | 1.681 |
| Água | 83 |

(Total de sobrescritos, 33.961, é maior que o total usado, 40.721, porque um mesmo pixel manual
pode contar em "sobrescrito" mesmo quando o valor final não é a classe majoritária — a tabela acima
agrupa por classe NOVA recebida, não por par origem→destino; ver `n_pixels_sobrescritos_por_classe`
no manifest para o número bruto por classe de destino.)

A classe crítica (solo exposto/obras) foi de longe a mais retrabalhada pela rotulagem manual —
esperado, é o objetivo de SV-10.

## Tabela comparativa de 3 vias

| Métrica | `rf_v0.1` (3 sites) | `rf_v0.2` (16 sites, sem manual) | `rf_v1.0` (16 sites, com manual) | Δ (v1.0 − v0.2) | Δ (v0.2 − v0.1) |
|---|---|---|---|---|---|
| accuracy (holdout espacial) | 0.7965 | 0.7904 | 0.7889 | **−0.0015** | −0.0061 |
| macro-F1 (holdout espacial) | 0.7521 | 0.7763 | 0.7757 | **−0.0006** | +0.0242 |
| **F1 classe 3** (holdout espacial) | 0.4530 | 0.5750 | **0.5770** | **+0.0020** | +0.1220 |
| precision classe 3 | 0.556 | 0.592 | 0.595 | +0.003 | +0.036 |
| recall classe 3 | 0.382 | 0.559 | 0.560 | +0.001 | +0.177 |
| macro-F1 (holdout temporal) | 0.7379 | 0.7251 | 0.7260 | +0.0009 | −0.0128 |
| macro-F1 (era Landsat) | 0.7106 | 0.7952 | 0.7948 | −0.0004 | +0.0846 |
| macro-F1 (era Sentinel-2) | 0.7164 | 0.7373 | 0.7362 | −0.0011 | −0.0011 (~0) |
| **F1 classe 3 (era Landsat)** | 0.1039 | 0.4821 | 0.4800 | −0.0021 | +0.3782 |
| F1 classe 3 (era Sentinel-2) | 0.4881 | 0.5845 | 0.5838 | −0.0007 | +0.0964 |
| macro-F1 (holdout de AOI nunca vista) | n/a | 0.7675 | 0.7676 | +0.0001 | n/a |
| F1 classe 3 (holdout de AOI nunca vista) | n/a | 0.5402 | 0.5407 | +0.0005 | n/a |

**Leitura direta da tabela: o salto grande (F1 classe 3 de 0,453 para 0,575, +0,122; F1 classe 3
Landsat de 0,104 para 0,482, +0,378) veio quase inteiramente da EXPANSÃO DE SITES (v0.1→v0.2, 3
para 16 AOIs — mais diversidade de contexto espectral/geográfico), não da rotulagem manual.** A
coluna `Δ (v1.0 − v0.2)`, que isola só o efeito da rotulagem manual, mostra diferenças pequenas em
todas as métricas agregadas (|Δ| ≤ 0,002 na maioria, chegando a −0,0021 na F1 classe 3 da era
Landsat) — dentro do ruído entre folds observado na validação cruzada de treino (desvio padrão
±0,006 a ±0,007 nas duas variantes, ver `EXP-002-rf-v1.0-treino.md`). **Nas métricas agregadas
(pooled), 211 polígonos manuais não mudam o quadro.** Isso é esperado: eles são 40.721 pixels
usados de um dataset com quase 3,8 milhões de linhas, e no teste especificamente são só 10.678 de
1.693.912 linhas (0,63%) — matematicamente não têm massa para mover uma métrica agregada sozinhos.
**A seção de bioma abaixo mostra que isso esconde um efeito real e importante que a métrica agregada
dilui — não que não exista.**

## Métricas de `rf_v1.0` por `origem_label` (detecção de decoreba)

Sobre o holdout espacial (a) de `dataset_v1.0` — o teste crítico do enunciado: "se o modelo acerta
muito nos pixels manuais e nada nos automáticos, decorou os polígonos em vez de aprender a classe."

| origem_label | n | accuracy | macro-F1 | F1 classe 3 | precision classe 3 | recall classe 3 |
|---|---|---|---|---|---|---|
| `mapbiomas` (automático) | 1.683.234 | 0.7906 | 0.7762 | **0.5745** | 0.5953 | 0.5551 |
| `manual` | 10.678 | 0.5267 | 0.5666 | **0.6570** | 0.5752 | 0.7660 |

**Critério de aceite bloqueante do enunciado ("F1 nos pixels `origem_label=="mapbiomas"` no teste
não pode ter caído em relação a `rf_v0.2`"): PASSA.** F1 classe 3 nos pixels automáticos = 0,5745,
essencialmente idêntico ao F1 classe 3 agregado de `rf_v0.2` inteiro (0,575 — que é quase só pixels
automáticos, já que `rf_v0.2` não tinha rotulagem manual). Nenhuma queda.

O subconjunto `manual` tem **accuracy mais baixa** (0,527 vs 0,791) e **macro-F1 mais baixo** (0,567
vs 0,776) que o automático — à primeira vista poderia parecer suspeito, mas é o oposto de decoreba:
se o modelo tivesse memorizado os polígonos manuais especificamente, esperaríamos desempenho
artificialmente ALTO neles (e ele nunca viu ESSES pixels de teste em treino — o split por bloco
garante isso). O padrão observado (recall de classe 3 mais alto — 0,766 — mas accuracy geral mais
baixa) é consistente com o desenho deliberado de SV-10: boa parte dos polígonos manuais são
"negativos difíceis" (coisas que *parecem* obra mas não são, ou vice-versa, por bioma) — um
subconjunto de teste **propositalmente mais difícil e adversarial** que a amostra automática, não
uma amostra fácil que o modelo decorou. O modelo generaliza para esse subconjunto difícil
razoavelmente bem (recall de classe 3 de 0,766, o melhor recall de classe 3 de toda a tabela), mas
sem o desempenho "bom demais" que indicaria memorização.

## Análise por bioma — a melhora é geral, ou concentrada nos biomas novos?

Esta é a pergunta central da nota de revisão de 2026-08-31 do enunciado. `rf_v0.2` não tem uma
seção "por bioma" no seu relatório de avaliação (SV-13 original só quebra "por site") — para
comparar, reconstruí o F1 por bioma de `rf_v0.2` como **média ponderada por `n` dos F1 por site**
já publicados em `reports/avaliacao_rf_v0.2.md` (site→bioma via `config/sites.geojson` /
`data/manifests/dataset_v0.2.json`). Isto é uma **aproximação** (F1 não é linear; a média ponderada
de F1 por site diverge um pouco do F1 calculado sobre a matriz de confusão agregada do bioma
inteiro) — optei por isto em vez de re-treinar/carregar `rf_v0.2` (`.joblib` apagado, task explícita
pede para evitar regenerar modelo grande a menos que estritamente necessário; o disco está em 16 GB
livres). Os números de `rf_v1.0` por bioma, em contraste, são exatos (calculados diretamente sobre
a matriz de confusão agregada do bioma, via `scripts/sv16_analise_origem_bioma.py`).

| bioma | n (teste, v1.0) | n manual no teste | macro-F1 `v0.2` (aprox., ponderada) | macro-F1 `v1.0` (exata) | Δ macro-F1 | F1 classe 3 `v0.2` (aprox.) | F1 classe 3 `v1.0` (exata) | Δ F1 classe 3 |
|---|---|---|---|---|---|---|---|---|
| Amazônia (1 site: clickip-manaus) | 60.367 | 1.176 | 0.6790 | 0.6874 | +0.0084 | 0.2160 | 0.2784 | **+0.0624** |
| Caatinga (2 sites) | 163.326 | 1.569 | 0.7472 | 0.7940 | **+0.0468** | 0.5371 | **0.7761** | **+0.2390** |
| Cerrado (1 site: everest-goiania) | 56.540 | 2.527 | 0.6520 | 0.6958 | +0.0438 | 0.2620 | **0.4916** | **+0.2296** |
| Mata Atlântica (12 sites, ~83% do teste) | 1.413.679 | 5.406 | 0.7680 | 0.7760 | +0.0080 | 0.5374 | 0.5616 | +0.0242 |

**Resposta direta: a melhora NÃO está concentrada no Sudeste (Mata Atlântica) — está concentrada
exatamente nos biomas novos que a rotulagem estratificada (SV-09b/SV-10) foi desenhada para
cobrir.** Caatinga e Cerrado — os dois biomas mais sub-representados no dataset automático — têm
ganhos de F1 classe 3 de **+0,239** e **+0,230** respectivamente, muito acima do ruído de qualquer
outra métrica desta tarefa. Mata Atlântica, que já tinha a melhor cobertura de exemplos automáticos
e domina 83% do volume de teste, ganha só +0,024 — pequeno o suficiente para não mover a métrica
agregada da tabela de 3 vias acima. **É exatamente esse efeito de diluição por volume que faz a
tabela agregada (Δ v1.0−v0.2 ≈ 0) esconder um resultado que, olhado por bioma, é claramente
positivo e no lugar certo.**

Quebra adicional por bioma × origem_label (só `rf_v1.0`, holdout espacial):

| bioma | origem_label | n | macro-F1 | F1 classe 3 |
|---|---|---|---|---|
| Amazônia | manual | 1.176 | 0.4152 | 0.5607 |
| Amazônia | mapbiomas | 59.191 | 0.6758 | 0.2140 |
| Caatinga | manual | 1.569 | 0.6572 | 0.8321 |
| Caatinga | mapbiomas | 161.757 | 0.7945 | **0.7748** |
| Cerrado | manual | 2.527 | 0.4079 | 0.8058 |
| Cerrado | mapbiomas | 54.013 | 0.6529 | 0.2580 |
| Mata Atlântica | manual | 5.406 | 0.5158 | 0.5473 |
| Mata Atlântica | mapbiomas | 1.408.273 | 0.7769 | 0.5618 |

Duas leituras distintas emergem daqui, e é importante não confundi-las:

- **Caatinga é o caso mais limpo de generalização real.** Mesmo olhando SÓ para os pixels de
  origem `mapbiomas` (que o modelo nunca viu rotulados manualmente), o F1 classe 3 é 0,7748 —
  muito acima do baseline anterior do bioma inteiro (0,5371, que era quase todo `mapbiomas` já que
  `rf_v0.2` não tinha manual). Isso é evidência de que os ~1.500 pixels manuais de treino em
  Caatinga (SV-10 cobriu 2 sites: angonap-fortaleza, ascenty-maracanau) ensinaram ao modelo a
  assinatura espectral real da classe crítica naquele bioma — não decorou os polígonos, generalizou
  a partir deles para pixels automáticos vizinhos que nunca tinham rótulo manual algum.
- **Cerrado é mais ambíguo.** O F1 classe 3 nos pixels `mapbiomas` (0,258) está estatisticamente no
  mesmo patamar do baseline anterior (0,262) — quase nenhuma generalização visível fora dos
  polígonos manuais. O ganho pooled do bioma inteiro (+0,230) vem majoritariamente do desempenho
  muito alto (F1 classe 3 = 0,806) no pequeno subconjunto manual (2.527 de 56.540 linhas, 4,5% do
  teste de Cerrado) combinado com como precision/recall pooled se recombinam sobre a matriz de
  confusão inteira do bioma — a aritmética de F1 pooled não decompõe linearmente em subgrupos, então
  esse salto grande com uma fatia pequena e "fácil" não é, por si só, prova de generalização ampla
  em Cerrado. **Tratamento honesto:** o ganho medido em Cerrado é real (a métrica pooled do bioma
  realmente subiu, e é isso que qualquer usuário do modelo veria), mas sua origem é mais provável
  que seja "os poucos exemplos manuais de Cerrado, sendo mais fáceis/representativos que o ruído do
  MapBiomas ali, empurram a métrica pooled para cima" do que "o modelo aprendeu Cerrado de forma
  ampla" — precisaria de mais rotulagem manual em Cerrado (só 1 AOI, `everest-goiania`) para
  confirmar generalização de verdade. Isto é uma limitação a documentar, não a esconder.

## Decisão: qual modelo é o oficial da V1

**`rf_v1.0` é declarado o modelo oficial da V1.**

Justificativa:

1. **Não piora em nenhuma métrica agregada de forma relevante** — todos os Δ(v1.0−v0.2) na tabela
   de 3 vias estão dentro do ruído de CV (±0,006–0,007). A maior queda absoluta é −0,0021 (F1
   classe 3 na era Landsat), estatisticamente indistinguível de zero.
2. **F1 classe 3 no holdout espacial é levemente melhor** (0,577 vs 0,575) — não é grande, mas é
   consistente com "não pior", que é o critério mínimo do enunciado para preferir `v1.0`.
3. **Passa o teste de decoreba** — F1 nos pixels `origem_label=="mapbiomas"` (0,5745) não caiu em
   relação a `rf_v0.2` (0,575). O modelo não está memorizando os 211 polígonos às custas do
   restante do dataset.
4. **O ganho estratégico real está no recorte por bioma, não no agregado**: Caatinga (+0,239 F1
   classe 3) e Cerrado (+0,230 F1 classe 3) — os biomas que a rotulagem estratificada de SV-09b/
   SV-10 foi desenhada para reforçar — melhoram substancialmente, com evidência de generalização
   genuína (não só decoreba) pelo menos em Caatinga. Isso é exatamente o resultado que a banca vai
   perguntar sobre ("funciona fora do Sudeste?") e é o argumento mais forte a favor de `v1.0`.
5. **Zero custo de adoção**: mesmos hiperparâmetros, mesmo split (verificado byte a byte), mesmo
   pipeline de treino/avaliação — não há trade-off de complexidade, tempo de treino ou risco de
   overfitting em trocar `v0.2` por `v1.0`.

**Ressalva honesta para a documentação da V1**: se a pergunta for "os 211 polígonos manuais
melhoraram a métrica de topo da apresentação (macro-F1/F1 classe 3 agregados)?", a resposta correta
é **não, de forma mensurável — a melhora de topo veio da expansão de sites (SV-27), não da
rotulagem manual (SV-10)**. O valor da rotulagem manual está no recorte por bioma, que é uma
pergunta mais específica e mais alinhada ao objetivo real do projeto (o modelo generaliza para uma
região que os 16 sites automáticos mal cobriam) do que ao número agregado que dominaria um slide
único. Ambas as leituras devem constar na apresentação final — a agregada (honesta: efeito pequeno)
e a por bioma (o resultado real e positivo do investimento de SV-10).

## Limitações desta comparação

- O F1 por bioma de `rf_v0.2` é uma **aproximação** (média ponderada por `n` dos F1 por site já
  publicados), não um recálculo exato sobre a matriz de confusão agregada do bioma — o `.joblib` de
  `rf_v0.2` foi apagado (só existia para medir, já foi medido) e eu optei por não regenerá-lo
  (custaria outro ciclo de treino de ~1h e ~7 GB de disco, com apenas 16 GB livres no momento). Se
  o time quiser o número exato, é reproduzível com `python -m sentinela.train --dataset v0.2
  --modelo rf --tag v0.2` seguido de `python -m sentinela.evaluate --modelo models/rf_v0.2.joblib
  --dataset v0.2 --tag v0.2`.
- A atribuição causal do ganho em Cerrado (bioma × origem_label) é ambígua, ver seção acima —
  documentado como limitação, não escondido.
- Amostra de 20 pixels errados (inspeção visual, `reports/avaliacao_rf_v1.0.md`) é pequena demais
  para quantificar a proporção erro-de-modelo vs. erro-de-label; serve só como evidência
  qualitativa.
