# EXP-004 — Modelo de conversão por pixel (SV-40): onde, dentro do sítio, a conversão acontece?

- **Data:** 2026-09-12
- **Frente:** `dados-modelo-impacto/` (passo 40) — fora do escopo do classificador `src/sentinela/`
- **Especificação:** `docs/handoff-modelo-conversao-pixel.md`
- **Script:** `dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py`
  (`--fase dataset | treinar | avaliar | ablacao`)
- **Dataset:** `dados-modelo-impacto/raw/controles-rf/conversao_dataset.parquet`
- **Seed:** 42 (`impacto_dc_comum.SEED`) em todo sorteio e treino

## 1. A pergunta

Um classificador binário por pixel: **dado um pixel e o contexto dele antes da obra, qual a
probabilidade de ele virar área construída nos anos seguintes?**

É uma pergunta diferente da que já falhou. A camada 2 do modelo de impacto
(`modelo-impacto-score/scripts/02_explicacao.py`) pergunta *quanto este SÍTIO vai converter* e não
se sustentou — 13 modelos, todos com R² LOOCV negativo, permutação p=0,77. Aqui a pergunta é
*ONDE, dentro do sítio, vai converter*. A aposta é que a variação **dentro** de um sítio seja
aprendível mesmo quando a variação **entre** sítios não é; as duas coisas são independentes.

## 2. Dados

Nada foi baixado. Tudo vem dos rasters classificados que já estavam em disco desde o passo 4.

- **20 pares** tratamento/controle (`P26.pares_unificados()`): 15 de procedência
  `validado_5_camadas` e 5 de `datacentermap`.
- **Janela de 7 anos** por par (`C.janela_anos`), com três exceções já conhecidas:
  `ascenty-maracanau` tem 5 anos (precisaria de 2011–2012, faixa_b desabilitada) e
  `clickip-manaus`, `scala-spoapa01`, `exp-elea-rjo1`, `exp-netwise-empresas` têm 6. Todas acima do
  mínimo de `2·N_PONTA + 1 = 5`, então nenhum par foi descartado.
- **Sensor único por janela**, como o resto da frente exige (SV-20): 15 pares em Landsat (30 m),
  5 em Sentinel-2 (10 m).

## 3. O rótulo

Idêntico ao de `impacto_dc_12_trajetoria_pixel.contar_assinaturas`, assinatura `virou_construida` —
não foi inventado outro, para o modelo continuar comparável com o achado publicado:

```python
inicio = pilha[:2]      # 2 primeiros anos da janela
fim    = pilha[-2:]     # 2 últimos
valido = np.all(pilha > 0, axis=0)                    # sem nodata em nenhum ano
y = (np.all(inicio != CONSTRUIDA, axis=0)             # não era construída
     & np.all(fim == CONSTRUIDA, axis=0)              # virou e persistiu
     & valido)
```

## 4. O conjunto de risco — a única divergência em relação ao handoff, e por quê

O handoff define `y` sobre todos os pixels válidos. **O dataset aqui guarda apenas os pixels que
podem converter** — não construídos nos 2 primeiros anos —, e é sobre esse conjunto que todas as
métricas são medidas. A razão não é conveniência:

Um pixel já construído no pré-período é **negativo garantido pela própria definição do rótulo**
(`np.all(inicio != CONSTRUIDA)` é falso). Ele também tem `dist_construida_m = 0`, o menor valor
possível. O baseline 2 do §5 do handoff — "distância ao construído mais próximo, sozinha" — é
obrigado a colocar esse pixel no **topo** do ranking, onde ele é sempre um erro. O modelo, que vê
`pre_classe`, aprenderia a peneirar esses pixels numa única feature e "ganharia" do baseline por
uma tautologia da definição do alvo, não por saber onde a obra vem.

Ou seja: manter os pixels inelegíveis **inflaria** a margem do modelo sobre o baseline, que é
exatamente o tipo de número bonito que o handoff manda não produzir. Restringir ao conjunto de
risco é a leitura estrita, não a permissiva.

Duas conferências de que essa é a leitura pretendida:

| quantidade | disco inteiro | conjunto de risco | handoff previa |
|---|---|---|---|
| prevalência da classe positiva | 1,70% | **2,672%** | "~2–3% (≈1:40)" |
| PR-AUC do baseline de prevalência | 0,0170 | **0,0267** | "PR-AUC ≈ 0,025" |

Os dois números do handoff batem no conjunto de risco e não no disco inteiro.

## 5. Escopo espacial e exclusões

- **Disco de 5 km** em torno do ponto, por máscara **geodésica** exata
  (`P11.grade_distancia_km`) — não euclidiana no plano, porque os rasters estão todos em
  EPSG:31983 inclusive Manaus e Fortaleza.
- **Footprint do próprio prédio excluído** nos pontos de tratamento (§7 do handoff): o prédio
  converte por construção e não é impacto no entorno. Usa a mesma resolução de footprint do passo
  26 (`P26.mascara_footprint_do_campus`), incluindo a regra de só contar como excluído quando o
  polígono de fato **sobrepõe** o disco — dois campi têm polígono OSM fora dele, e tratá-los como
  "prédio excluído" seria falso.
- **`everest-goiania` não tem footprint no OSM** (já era assim no passo 13). O ponto de tratamento
  dele entra com o prédio dentro. Fica registrado na coluna `footprint_excluido` do parquet.
- **Tratamento e controle entram juntos**, marcados na coluna `tipo`: o controle é onde a conversão
  de fundo acontece e é dado de treino legítimo.

## 6. Features — todas do pré-período

**Toda feature sai dos 2 primeiros anos da janela** (`pilha[0]` e `pilha[1]`). A fase `dataset` é a
única que toca raster; depois dela não há caminho pelo qual um ano do pós-período chegue a uma
coluna.

| feature | origem |
|---|---|
| `pre_classe` (1–5, one-hot no treino) | `pilha[0]` |
| `frac_{veg_densa,solo_exposto,construida}_{90,150,330}m` | convolução sobre `pilha[0]` |
| `delta_frac_construida_150m` | fração em `pilha[1]` menos a de `pilha[0]` |
| `dist_construida_m` | `distance_transform_edt` sobre `pilha[0] != 4`, em metros |
| `dist_centro_m` | grade geodésica de distância ao centro |
| `confianca_media_pre` | média dos `*_confianca.tif` dos 2 primeiros anos |
| `estavel_pre` | `pilha[0] == pilha[1]` |
| `sensor_landsat` | do pareamento |

**Vizinhança em metros, não em pixels.** Uma janela "3×3" valeria 90 m em Landsat e 30 m em
Sentinel-2, e a mesma coluna carregaria duas escalas físicas diferentes. As escalas são 90, 150 e
330 m (= 3×3, 5×5 e 11×11 na grade de 30 m) convertidas para a janela de pixels de cada sensor.

**Fração normalizada por vizinhos válidos**, não pela janela inteira: contar um pixel sem dado como
"não é construída" inventaria vizinhança vazia onde só houve nuvem — mesma razão de
`contar_assinaturas` exigir classe válida em todos os anos.

**Proibidas como feature** (`COLUNAS_PROIBIDAS_COMO_FEATURE`, conferida antes de qualquer treino,
mesma regra de `sentinela.train`): `site_id`, `campus`, `tipo`, `linha`, `coluna`, `sensor` (o
texto; a versão binária `sensor_landsat` é feature por decisão de SV-12), `procedencia`, e
`municipio`/`uf`/`regiao`/`bioma`, que nem chegam a ser materializados. `bioma` fica de fora pelo
mesmo motivo dos outros: identifica o sítio.

## 7. Protocolo de validação

**Leave-one-site-out, 20 folds.** Split aleatório por pixel é proibido — pixels vizinhos são quase
idênticos e o vizinho do pixel de teste cairia no treino. O N efetivo é **20 sítios**, não 6,8
milhões de pixels. O controle de cada campus vai junto com o tratamento dele, sempre do mesmo lado
do split.

**Treino subamostrado, avaliação completa.** Um ponto Sentinel-2 tem ~1 milhão de pixels contra
~111 mil de um Landsat; treinar no bruto deixaria 5 pares decidirem o modelo. O treino usa todos os
positivos e um teto de 20.000 negativos **por ponto** (sorteio determinístico por site via
`C.rng_do_site`), o que equaliza a contribuição de cada ponto. A avaliação **nunca** é
subamostrada: cada campus retido é predito em todos os seus pixels, com a prevalência de verdade —
que é o que o PR-AUC precisa para significar alguma coisa.

**Sem tuning.** Escolher hiperparâmetro olhando o placar LOSO vaza e faria o LOSO deixar de ser
fora-da-amostra. Os parâmetros são fixos e herdados de `sentinela.train.RF_PARAMS_BASE`, com folha
maior por causa do volume:

```python
RF_PARAMS = {"n_estimators": 200, "min_samples_leaf": 50, "max_features": "sqrt",
             "class_weight": "balanced", "n_jobs": -1, "random_state": 42}
```

**Métrica: PR-AUC (average precision).** Accuracy não é reportada em lugar nenhum — seria 97,3%
chutando tudo negativo. ROC-AUC aparece no CSV como contexto, nunca como veredito: com 1:37 ela
parece boa fácil demais.

## 8. Os dois baselines e o critério de aceite

1. **Prevalência** — prever a taxa base para todo mundo. PR-AUC = a própria prevalência.
2. **Distância ao construído mais próximo, sozinha** — uma feature, sem modelo, score `-dist`.

> O modelo é adotado se o **PR-AUC agregado superar o baseline de distância em ≥20% relativo** e o
> ganho for positivo em **≥14 dos 20** sítios retidos.

Um modelo que não bate os dois não adiciona nada e é reportado como reprovado. Se só bater o
baseline de distância em média, puxado por poucos sítios, também reprova: ganho médio alto com
sinal trocado na maioria é sorte, não modelo.

## 9. Resultado

**O modelo passa nos dois critérios, com folga.**

| | PR-AUC agregado |
|---|---|
| **modelo (Random Forest)** | **0,2954** |
| baseline 2 — distância ao construído mais próximo | 0,1613 |
| baseline 1 — prevalência | 0,0267 |

- **Ganho sobre o baseline de distância: +83,1%** (exigido ≥ +20%).
- **Ganho positivo em 20 dos 20 sítios retidos** (exigido ≥ 14). O pior sítio ganha +67,6%
  (`exp-to-host-data-centers`), o melhor +273,8% (`equinix-santana-parnaiba`), mediana +119,4%.
- ROC-AUC agregado 0,915 — reportado só como contexto. Com 1:37 ele parece bom fácil demais, e
  não entra no critério. Accuracy não é reportada em lugar nenhum.

O ganho **não** é puxado por poucos sítios: nenhum campus fica abaixo de +67%, o que é três vezes
o limiar do critério agregado. A média macro entre sítios (0,2604 modelo contra 0,1213 distância,
+114,7%) é até maior que o agregado, ou seja, o número agregado é o mais conservador dos dois — os
sítios grandes em pixels (`exp-netwise-empresas`, `exp-to-host-data-centers`, ambos Sentinel-2)
são justamente os de ganho relativo menor.

### Placar por sítio retido

| campus retido | pixels | prevalência | modelo | distância | ganho |
|---|---:|---:|---:|---:|---:|
| equinix-santana-parnaiba | 123.862 | 2,73% | 0,3000 | 0,0803 | +273,8% |
| ascenty-sumare | 100.433 | 3,72% | 0,2020 | 0,0693 | +191,3% |
| angonap-fortaleza | 114.825 | 1,01% | 0,3116 | 0,1109 | +181,0% |
| ascenty-jundiai | 122.417 | 2,49% | 0,2487 | 0,0898 | +176,9% |
| scala-tambore | 109.159 | 1,73% | 0,2123 | 0,0798 | +166,1% |
| ascenty-vinhedo | 125.710 | 2,32% | 0,1870 | 0,0708 | +164,2% |
| exp-netwise-empresas | 1.417.118 | 0,60% | 0,1792 | 0,0735 | +143,6% |
| ascenty-osasco | 66.621 | 3,62% | 0,2228 | 0,0965 | +130,8% |
| exp-asap-sp1 | 40.376 | 5,42% | 0,2870 | 0,1249 | +129,7% |
| everest-goiania | 77.111 | 4,65% | 0,2282 | 0,1029 | +121,8% |
| exp-elea-rjo1 | 101.525 | 1,67% | 0,1723 | 0,0794 | +117,1% |
| ascenty-maracanau | 109.453 | 5,35% | 0,3061 | 0,1437 | +113,1% |
| ascenty-hortolandia | 80.290 | 4,99% | 0,2187 | 0,1059 | +106,6% |
| exp-idx-data-centers---it-services | 106.460 | 5,56% | 0,3367 | 0,1793 | +87,8% |
| clickip-manaus | 1.091.436 | 1,97% | 0,3481 | 0,1916 | +81,7% |
| scala-sgigsm01 | 502.555 | 7,18% | 0,4807 | 0,2650 | +81,4% |
| hostdime-joao-pessoa | 105.469 | 2,52% | 0,2184 | 0,1243 | +75,8% |
| ascenty-paulinia | 93.767 | 5,73% | 0,1739 | 0,1006 | +73,0% |
| scala-spoapa01 | 875.629 | 4,59% | 0,3373 | 0,1974 | +70,9% |
| exp-to-host-data-centers | 1.415.576 | 1,77% | 0,2364 | 0,1410 | +67,6% |
| **AGREGADO** | **6.779.792** | **2,67%** | **0,2954** | **0,1613** | **+83,1%** |

Tabela completa (com ROC-AUC e ganho sobre a prevalência) em
`raw/controles-rf/conversao_loso_resultado.csv`. Figura:
`raw/controles-rf/figuras/fig_20_conversao_loso.png`.

### Uma ressalva sobre a curva PR da figura

No painel da direita, o baseline de distância aparece **acima** do modelo em recall baixo. É
artefato de desenho, não resultado. `dist_construida_m` só assume os valores discretos que a
transformada de distância produz numa grade (30 m, 42,4 m, 60 m, …), então cada limiar carrega um
bloco enorme de empates, e `precision_recall_curve` liga dois limiares consecutivos por uma reta
que **não é atingível** — dentro de um bloco empatado não há como escolher os positivos primeiro. A
average precision, que é o número do veredito, soma por degrau e não interpola. O artefato favorece
o baseline, não o modelo.

## 10. O que o modelo está usando

A importância reportada é a de **permutação fora-da-amostra**: em cada fold, embaralha-se uma
coluna no campus **retido** e mede-se a queda de PR-AUC. Permutar no treino mediria o quanto o
modelo decorou.

| feature | permutação (ΔPR-AUC) | folds com ganho | impureza |
|---|---:|---:|---:|
| `frac_construida_90m` | +0,0348 | 20/20 | 0,143 |
| `confianca_media_pre` | +0,0321 | 20/20 | 0,029 |
| `dist_construida_m` | +0,0190 | 20/20 | 0,179 |
| `delta_frac_construida_150m` | +0,0180 | 20/20 | 0,028 |
| `frac_construida_150m` | +0,0175 | 20/20 | 0,091 |
| `pre_classe_solo_exposto_obras` | +0,0168 | 19/20 | 0,047 |
| `frac_veg_densa_90m` | +0,0137 | 20/20 | 0,018 |
| `frac_construida_330m` | +0,0097 | 20/20 | 0,049 |
| … | | | |
| `dist_centro_m` | +0,0008 | 15/20 | 0,016 |
| `frac_solo_exposto_330m` | +0,0002 | 11/20 | 0,089 |

Três leituras que importam:

1. **A impureza mente, e a permutação mostra onde.** `frac_solo_exposto_90m/150m/330m` somam 0,33
   de importância por impureza — mais que qualquer outro grupo — e praticamente nada por
   permutação (+0,008, +0,002, +0,0002, com 11 a 16 folds positivos). É o viés clássico da
   impureza a favor de feature contínua de alta cardinalidade. Por isso o placar aqui é o de
   permutação, e o CSV publica as duas para que a divergência fique visível.
2. **`dist_centro_m` é quase inútil (+0,0008, positiva em 15/20).** Isso responde a uma objeção
   óbvia: o modelo **não** está apenas reaprendendo o achado do passo 26 ("converte perto do
   campus"). O que carrega a predição é o contexto local de vizinhança — quanto já é construído
   em volta e a que distância — não onde fica o centro.
3. **`sensor_landsat` e `pre_classe_construida_urbana` dão exatamente 0,0.** Nos dois casos é
   esperado e é uma conferência de sanidade que passou: `pre_classe_construida_urbana` é
   **constante falsa** por construção (o conjunto de risco exclui quem já era construída) e
   `sensor_landsat` é **constante dentro de cada campus retido** (cada par usa um sensor só), então
   permutá-la não pode mudar nada. A permutação fora-da-amostra simplesmente não consegue medir
   `sensor`; a impureza a coloca em 0,0125.

## 11. Ablações — o resultado sobrevive às duas explicações alternativas?

O placar sozinho não distingue "o modelo aprendeu onde a obra vem" de duas leituras bem menos
interessantes. As duas ablações foram **declaradas antes** de olhar o resultado (`ABLACOES` no
script), refazem o LOSO inteiro sem a feature, e não mudam o modelo adotado — que continua sendo o
completo.

| variante | features | PR-AUC | vs. completo | ganho sobre distância | sítios | critério |
|---|---:|---:|---:|---:|---:|---|
| completo | 20 | 0,2954 | — | +83,1% | 20/20 | PASSA |
| `sem_confianca` | 19 | 0,2892 | −2,1% | +79,3% | 20/20 | PASSA |
| `sem_dist_centro` | 19 | 0,2942 | −0,4% | +82,4% | 20/20 | PASSA |

**`sem_confianca` — o risco de acoplamento com ruído do rótulo.** `confianca_media_pre` é a 2ª
feature por permutação, e isso merecia desconfiança: `y` sai do **mesmo** classificador que produz
a confiança. Um pixel onde o classificador é inseguro no pré-período tende a continuar inseguro
depois, e uma troca espúria para a classe 4 que dure 2 anos vira positivo. Parte do ganho poderia
ser "prever a instabilidade do classificador" em vez de "prever conversão". **Tirar a feature custa
2,1% do PR-AUC** e o critério continua passando por larga margem em 20/20 sítios: a informação dela
é largamente redundante com o contexto de vizinhança. O acoplamento existe, mas não é o que sustenta
o resultado.

**`sem_dist_centro` — o risco de só reaprender o passo 26.** Se o modelo dependesse de distância ao
centro, ele estaria reproduzindo o achado "converte perto do campus" (18/20, p=0,0002) em vez de ler
o terreno — e não serviria para prever dentro de um sítio novo. **Custa 0,4%**, consistente com a
importância por permutação quase nula. O que carrega a predição é o contexto local.

## 12. Veredito

> **APROVADO.** Sob leave-one-site-out, o modelo supera o baseline de distância em **+83,1%** de
> PR-AUC agregado (exigido ≥ +20%) e o ganho é positivo em **20 dos 20** sítios retidos (exigido
> ≥ 14). O modelo foi salvo em `models/conversao_v1.joblib` (refit nos 20 campi, 175 MB, ignorado
> pelo git conforme a regra de artefato pesado).

A resposta à pergunta que motivou o passo: **a variação DENTRO de um sítio é aprendível, mesmo com
a magnitude ENTRE sítios não sendo** (R² LOOCV negativo em 13 modelos na camada 2). As duas coisas
são independentes e agora estão medidas as duas.

## 13. O que este resultado NÃO autoriza dizer

1. **O rótulo não é obra verificada em campo — é a saída do próprio classificador.** O modelo
   prediz onde o Random Forest de cobertura vai mudar de ideia, que é o melhor proxy disponível
   nesta frente, não construção conferida. A classe 3 (solo exposto/obras) tem F1 0,579
   (`reports/avaliacao_rf_v1.0-tuned.md`), e o rótulo herda esse ruído. A ablação `sem_confianca`
   limita o tamanho do problema, não o elimina.
2. **O N efetivo continua sendo 20 sítios, não 6,8 milhões de pixels.** A confiança no "+83,1%"
   vem de o ganho ser positivo em 20/20 folds independentes por sítio, não do volume de pixels.
3. **O score não é probabilidade calibrada.** `class_weight="balanced"` mais a subamostragem de
   negativos por ponto deslocam o prior de propósito. A average precision depende só do
   *ordenamento*, então o veredito vale; mas um "mapa de probabilidade" cujos números sejam lidos
   como probabilidade precisa de calibração (isotônica ou Platt) ajustada **em sítios retidos**, e
   isso não foi feito aqui. Hoje o artefato entrega um **mapa de ranking**, não de probabilidade.
4. **O modelo diz ONDE, não QUANDO.** O horizonte é o da janela (obra−3..obra+3, 5 a 7 anos). Não
   há nada aqui sobre em que ano dentro da janela a conversão acontece — isso é o passo 18.
5. **A PR-AUC agregada é dominada pelos 5 pares Sentinel-2**: eles são 5,30 dos 6,78 milhões
   de pixels avaliados (**78%**), porque 10 m de resolução gera 9x mais pixels por hectare que
   os 30 m do Landsat. Por isso a média macro entre sítios está
   reportada junto (0,2604 contra 0,1213, +114,7%): ela é **maior** que o agregado, ou seja, o
   número publicado é o mais conservador dos dois.
6. **`everest-goiania` entra com o próprio prédio dentro** — é o único campus sem footprint no OSM.
   Ele fica em 11º lugar de 20 em ganho (+121,8%), então não é ele que carrega o resultado, mas o
   número dele está inflado em relação aos outros 19.
7. **Não há DEM.** "Terreno plano", citado como intuição no handoff, não entrou porque não existe
   modelo de elevação nesta frente. É a extensão mais óbvia.

## 14. Reprodução

```bash
python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase dataset   # ~30 s
python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase treinar   # ~18 min
python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase avaliar   # ~3 min
python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase ablacao   # ~34 min
```

Zero rede: tudo lê os rasters classificados que já estão em disco desde o passo 4. Seed 42 em todo
sorteio (`C.rng_do_site` por ponto, `random_state` do RF), então as quatro fases são determinísticas.

Medido em 16 núcleos / 34 GB. O pool de treino tem 974.567 linhas; cada fit leva ~50 s.

Artefatos versionados: `conversao_loso_resultado.csv`, `conversao_importancias.csv`,
`conversao_ablacao.csv` e `figuras/fig_20_conversao_loso.png`. Ficam fora do git, por serem pesados
e reproduzíveis, `conversao_dataset.parquet` (76 MB), `conversao_loso_predicoes.parquet` e
`models/conversao_v1.joblib` (175 MB).
