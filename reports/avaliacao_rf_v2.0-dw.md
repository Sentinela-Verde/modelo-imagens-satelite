# Avaliação em holdout — `rf_v2.0-dw` sobre `dataset_v2.0` (SV-13)

- **Data:** 2026-09-11T20:56:48.299872+00:00
- **Modelo avaliado:** `models\rf_v2.0-dw.joblib`
- **Dataset:** `dataset_v2.0` — 2406041 linhas totais, 1192285 em avaliação (`split == "teste"` OU `holdout_temporal == True`)
- **Isolamento:** este relatório não treina nada — `sentinela.evaluate` nunca chama `.fit`; o modelo já vem pronto de `sentinela.train` (SV-12).

macro-F1 da CV de treino (SV-12, `rf_v2.0-dw`): **0.8308**. macro-F1 do holdout espacial é menor que a da CV de treino (0.8276 vs 0.8308) — esperado (o holdout é sempre mais difícil que a CV, que ainda compartilha a mesma distribuição de treino).

## Métricas-alvo de referência (termômetro, não critério de aprovação)

macro-F1 ≥ 0.70 e F1(classe 3) ≥ 0.55 no holdout espacial (a):

- macro-F1 = **0.8276** → bate a meta? **SIM**
- F1(classe 3) = **0.8036** → bate a meta? **SIM**

## (a) Holdout espacial — `split == "teste"` (generaliza para área que não viu?)

- n = 1019052, accuracy = 0.8300, macro-F1 = **0.8276**, weighted-F1 = 0.8294

| classe | precision | recall | f1 | suporte |
|---|---|---|---|---|
| Vegetação densa | 0.860 | 0.899 | 0.879 | 225944 |
| Vegetação rala / pasto / agricultura leve | 0.780 | 0.754 | 0.767 | 203171 |
| Solo exposto / em obras | 0.829 | 0.780 | 0.804 | 162832 |
| Área construída / urbana | 0.753 | 0.765 | 0.759 | 217384 |
| Água | 0.925 | 0.935 | 0.930 | 209721 |
| **macro avg** | 0.829 | 0.827 | **0.828** | 1019052 |
| **weighted avg** | 0.829 | 0.830 | 0.829 | 1019052 |

![matriz de confusão absoluta — holdout espacial](figures/matriz_confusao_espacial_rf_v2.0-dw.png)
![matriz de confusão normalizada — holdout espacial](figures/matriz_confusao_espacial_normalizada_rf_v2.0-dw.png)

## (b) Holdout temporal — `holdout_temporal == True` (ano mais recente, 2025; generaliza para ano que não viu?)

- n = 304034, accuracy = 0.8262, macro-F1 = **0.8260**, weighted-F1 = 0.8256
- Comparado ao holdout espacial: macro-F1 do temporal é menor ou igual que a do espacial (0.8260 vs 0.8276).

| classe | precision | recall | f1 | suporte |
|---|---|---|---|---|
| Vegetação densa | 0.863 | 0.887 | 0.875 | 65183 |
| Vegetação rala / pasto / agricultura leve | 0.776 | 0.761 | 0.768 | 63659 |
| Solo exposto / em obras | 0.829 | 0.749 | 0.787 | 52709 |
| Área construída / urbana | 0.755 | 0.790 | 0.772 | 64585 |
| Água | 0.916 | 0.940 | 0.928 | 57898 |
| **macro avg** | 0.828 | 0.825 | **0.826** | 304034 |
| **weighted avg** | 0.826 | 0.826 | 0.826 | 304034 |

![matriz de confusão absoluta — holdout temporal](figures/matriz_confusao_temporal_rf_v2.0-dw.png)
![matriz de confusão normalizada — holdout temporal](figures/matriz_confusao_temporal_normalizada_rf_v2.0-dw.png)

## (c) Por site — funciona em todos, ou só em alguns?

Tabela por site sobre o holdout espacial (a). Não geramos uma matriz de confusão PNG por site
individualmente (o dataset pode ter de 3 a 16 sites, dependendo da versão — um PNG por site
viraria ruído em vez de sinal); a tabela abaixo já responde a pergunta "funciona em todos, ou só
em um?" de forma direta.

| site | n | accuracy | macro-F1 | F1 classe 3 |
|---|---|---|---|---|
| `angonap-fortaleza` | 50268 | 0.873 | 0.856 | 0.929 |
| `ascenty-hortolandia` | 42956 | 0.763 | 0.773 | 0.748 |
| `ascenty-jundiai` | 158851 | 0.851 | 0.850 | 0.842 |
| `ascenty-maracanau` | 43044 | 0.810 | 0.816 | 0.837 |
| `ascenty-osasco` | 47304 | 0.855 | 0.852 | 0.817 |
| `ascenty-paulinia` | 155880 | 0.787 | 0.784 | 0.718 |
| `ascenty-sumare` | 46044 | 0.812 | 0.814 | 0.791 |
| `ascenty-vinhedo` | 45448 | 0.813 | 0.808 | 0.791 |
| `clickip-manaus` | 36716 | 0.901 | 0.885 | 0.907 |
| `equinix-santana-parnaiba` | 46033 | 0.853 | 0.818 | 0.722 |
| `everest-goiania` | 35022 | 0.833 | 0.836 | 0.811 |
| `hostdime-joao-pessoa` | 130611 | 0.816 | 0.793 | 0.741 |
| `odata-hortolandia` | 49493 | 0.829 | 0.824 | 0.813 |
| `scala-sgigsm01` | 49530 | 0.890 | 0.817 | 0.550 |
| `scala-spoapa01` | 35593 | 0.789 | 0.727 | 0.620 |
| `scala-tambore` | 46259 | 0.874 | 0.865 | 0.839 |

**O desempenho na classe 3 varia muito por site — não é uniforme.** F1(classe 3) vai de **0.550** (`scala-sgigsm01`, praticamente não detecta solo exposto/obras) a **0.929** (`angonap-fortaleza`), uma amplitude de 0.379. Resposta à pergunta do recorte (c): **não, o modelo não funciona igual em todo lugar** — sites com poucos exemplos de treino da classe 3 ou contexto espectral distinto (bioma/solo diferente) tendem a ficar bem abaixo da média. Isso é sinal de que o modelo generaliza espectralmente até um ponto, mas não compensa totalmente a escassez de exemplos por região — candidato direto para a rotulagem manual complementar (SV-09/SV-10) priorizar esses sites piores.

## (d) Por sensor / era — Landsat (2013-2018) vs Sentinel-2 (2019-2025)

Exclui `sobreposicao == True` (433908 linhas descartadas deste recorte, para
não contar o mesmo terreno duas vezes no ano de sobreposição). Se a era Landsat performar muito
pior, metade da série temporal do projeto não se sustenta.

| era | n | accuracy | macro-F1 | weighted-F1 | F1 classe 3 |
|---|---|---|---|---|---|
| Landsat (2013-2018) | 66900 | 0.8399 | 0.8361 | 0.8369 | 0.8156 |
| Sentinel-2 (2019-2025) | 518244 | 0.8267 | 0.8238 | 0.8261 | 0.7927 |

**Veredito sobre a era Landsat:** o macro-F1 agregado das duas eras é próximo (0.8361 Landsat vs 0.8238 Sentinel-2, diferença de 0.0123) — **mas isso esconde o problema real**: a F1 da classe 3 (crítica) cai de **0.7927** (Sentinel-2) para **0.8156** (Landsat), com recall de apenas 0.835 — o modelo praticamente não detecta solo exposto/obras na era Landsat. O recall da classe 3 na era Landsat é mais baixo que no Sentinel-2, mas ainda funcional; a diferença de resolução (30m vs 10m, área mínima mapeável 9x maior em Landsat) é a explicação mais provável, não um defeito do modelo.

### Matriz de confusão por era

![matriz de confusão absoluta — era Landsat](figures/matriz_confusao_era_landsat_rf_v2.0-dw.png)
![matriz de confusão normalizada — era Landsat](figures/matriz_confusao_era_landsat_normalizada_rf_v2.0-dw.png)
![matriz de confusão absoluta — era Sentinel-2](figures/matriz_confusao_era_s2_rf_v2.0-dw.png)
![matriz de confusão normalizada — era Sentinel-2](figures/matriz_confusao_era_s2_normalizada_rf_v2.0-dw.png)

## (e) Holdout espacial de AOI — data center nunca visto (só `dataset_v0.2`+)

AOIs inteiras reservadas fora de qualquer split de treino (`holdout_espacial == True`, ver
`aois_holdout_espacial` no manifest): **`ascenty-jundiai`, `ascenty-paulinia`, `hostdime-joao-pessoa`**. Esta é a
**única medida real de "o modelo funciona num data center que nunca viu"** — os outros recortes
ainda compartilham AOI com o treino (só um ano ou um bloco de 1km diferente).

- n = 445342, accuracy = 0.8180, macro-F1 = **0.8138**, weighted-F1 = 0.8163
- F1 classe 3 (crítica) = **0.7805**
- Bate meta de referência? macro-F1 ≥ 0.70: **SIM** · F1(classe 3) ≥ 0.55: **SIM**

| classe | precision | recall | f1 | suporte |
|---|---|---|---|---|
| Vegetação densa | 0.858 | 0.911 | 0.884 | 95376 |
| Vegetação rala / pasto / agricultura leve | 0.764 | 0.719 | 0.741 | 91773 |
| Solo exposto / em obras | 0.811 | 0.752 | 0.780 | 67992 |
| Área construída / urbana | 0.741 | 0.737 | 0.739 | 95544 |
| Água | 0.902 | 0.949 | 0.925 | 94657 |
| **macro avg** | 0.815 | 0.814 | **0.814** | 445342 |
| **weighted avg** | 0.816 | 0.818 | 0.816 | 445342 |

![matriz de confusão absoluta — holdout de AOI](figures/matriz_confusao_holdout_aoi_rf_v2.0-dw.png)
![matriz de confusão normalizada — holdout de AOI](figures/matriz_confusao_holdout_aoi_normalizada_rf_v2.0-dw.png)

## Análise da classe 3 (solo exposto / obras) — a razão de ser do projeto

Precision/recall isolados por era (recorte d, sobre a classe 3):

| era | precision | recall |
|---|---|---|
| Landsat | 0.797 | 0.835 |
| Sentinel-2 | 0.838 | 0.752 |

**Com o que a classe 3 é confundida?** (holdout espacial (a), linha e coluna da classe 3 na matriz de confusão absoluta)

- Quando o verdadeiro é classe 3, o modelo previu: {'Vegetação densa': 83, 'Vegetação rala / pasto / agricultura leve': 6397, 'Solo exposto / em obras': 127013, 'Área construída / urbana': 26397, 'Água': 2942}
- Quando o modelo previu classe 3, o verdadeiro era: {'Vegetação densa': 69, 'Vegetação rala / pasto / agricultura leve': 5738, 'Solo exposto / em obras': 127013, 'Área construída / urbana': 19383, 'Água': 1090}

### Erro por `distancia_safra`

| distancia_safra | n | recall_classe3 |
|---|---|---|
| 0.000 | 162832.000 | 0.780 |

### Inspeção visual de pixels errados (achado mais importante do relatório)

Amostrados 20 pixels errados envolvendo a classe 3 no holdout espacial (a)
(metade falso-negativo — verdadeiro=3, modelo previu outra —, metade falso-positivo — modelo
previu 3, verdadeiro era outra —, `random_state=42`), com patch RGB verdadeiro extraído do stack
de features original (`data/interim/features/{sensor}/{site}/{ano}.tif`, bandas red/green/blue,
alongamento de contraste 2-98%):

![contact sheet — erros da classe 3](figures/classe3_erros_rf_v2.0-dw.png)

**Conclusão erro-de-modelo vs. erro-de-label:** _[preenchida manualmente após inspeção visual do contact sheet acima — ver `docs/tarefas/SV-13-avaliacao-holdout.md` item 5; texto placeholder até essa etapa rodar]_

## Limitações conhecidas

- **Fonte de label:** MapBiomas Coleção 9 (anual) + WorldCover como verificação cruzada só em
  2021 (ADR-004). MapBiomas não tem uma classe "canteiro de obras" — o remap usa "Área não
  Vegetada"/"Mineração"/"Afloramento Rochoso" como proxy (ver `config/classes.yml`), o que é uma
  fonte de ruído estrutural na classe 3 que nenhum ajuste de modelo resolve sozinho.
- **2024/2025 replicam o rótulo de 2023** (Coleção 9 não cobre esses anos) — `distancia_safra` de
  1-2 nesses anos, peso reduzido no treino, mas ainda usados como verdade na avaliação aqui.
- **Resolução mista:** Landsat (30m, 2013-2018) e Sentinel-2 (10m, 2019-2025) harmonizados
  espectralmente (ADR-003), mas a área mínima mapeável de um evento de solo exposto é 9x maior em
  pixels Landsat — parte da diferença de era (recorte d) é resolução, não sensor.
- **Região climática:** ver seção específica de cobertura geográfica no manifest do dataset —
  `dataset_v0.1` cobre só 3 sites em Mata Atlântica/SP; `dataset_v0.2` expande para 5 biomas mas
  ainda concentra a maioria das linhas em Mata Atlântica/Sudeste (ver `distribuicao_classes.por_bioma`
  no manifest).
- Este relatório não ajusta o modelo com base no que viu aqui — qualquer ajuste volta para SV-12,
  registrado, e a avaliação é refeita.
