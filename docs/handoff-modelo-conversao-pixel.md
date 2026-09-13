# Handoff — modelo de conversão por pixel (SV-40)

- **Autor:** frente de Modelagem/ML · **Data:** 2026-09-12
- **Para:** quem for implementar. Este documento é a especificação completa; não precisa de
  contexto adicional além do repositório.
- **Prazo:** a apresentação é **17/09/2026**. Se a validação reprovar, isso é resultado — pare e
  reporte, não ajuste o protocolo para o número ficar bonito.

---

## 1. O que construir

Um classificador binário por pixel que responde:

> Dado um pixel e o contexto dele **antes da obra**, qual a probabilidade de ele virar área
> construída nos anos seguintes?

Saída desejada: para um site novo, um **mapa de probabilidade** — "se construir aqui, estas
manchas devem converter".

Isso é diferente do que já existe. A **camada 2** do modelo de impacto
(`modelo-impacto/scripts/score_02_explicacao.py`) pergunta *"quanto este SÍTIO vai converter?"* e
falhou — 13 modelos, todos com R² LOOCV negativo
(`modelo-impacto/outputs/explicacao_modelos.csv`). Este pergunta *"ONDE, dentro do sítio, vai
converter?"*.

A aposta é que a variação **dentro** de um sítio (perto de via, perto do que já é construído,
terreno plano) seja aprendível, mesmo que a variação **entre** sítios não seja.

---

## 2. Os dados que já existem

Tudo em disco, nada a baixar.

| o que | onde | como abrir |
|---|---|---|
| rasters classificados (5 classes, uint8, 30 m) | `data/processed/classificado/{sensor}/{site}/{ano}.tif` e `modelo-impacto/raw/controles-rf/classificado/...` | `C.caminho_classificado(sensor, site_id, ano)` |
| confiança do classificador (0–100) | mesmo caminho, sufixo `_confianca.tif` | `rasterio.open` |
| features de 13 bandas | `data/interim/features/{sensor}/{site}/{ano}.tif` | só para sites oficiais; controles têm os intermediários **descartados** |
| os 20 pares tratamento/controle | — | `P26.pares_unificados()` |
| janela de 7 anos de cada par | — | `C.janela_anos(ano_inicio_obra)` |

Helpers prontos, em `modelo-impacto/scripts/`:

```python
import impacto_dc_comum as C
import impacto_dc_11_sensibilidade_buffer as P11   # mascaras_por_raio(ref, lat, lon)
import impacto_dc_12_trajetoria_pixel as P12       # empilhar(site, sensor, anos)
import impacto_dc_26_analise_expandida as P26      # pares_unificados()
```

`P12.empilhar` devolve `(n_anos, altura, largura)` com a classe de cada pixel por ano.

**Tamanho:** 20 pares × 2 pontos × ~111 mil pixels. No anel de 0,5–1 km são ~2.600 pixels por
ponto; usando todos os raios até 5 km, ~10,5 milhões de pixels no total.

---

## 3. O rótulo

Idêntico ao que a análise já usa — **não invente outro**, senão o modelo deixa de ser comparável
com o achado publicado.

```python
CONSTRUIDA = 4
N_PONTA = 2   # anos em cada ponta

inicio = pilha[:N_PONTA]      # 2 primeiros anos da janela
fim    = pilha[-N_PONTA:]     # 2 ultimos

valido = np.all(pilha > 0, axis=0)                    # sem nodata em nenhum ano
y = (np.all(inicio != CONSTRUIDA, axis=0)             # nao era construida
     & np.all(fim == CONSTRUIDA, axis=0)              # virou e persistiu
     & valido)
```

Referência: `impacto_dc_12_trajetoria_pixel.py`, função `contar_assinaturas`.

**Desbalanceamento: a classe positiva é ~2–3% dos pixels (≈1:40).** Use `class_weight="balanced"`
ou equivalente, e **nunca reporte accuracy** — ela seria 97% chutando tudo negativo.

---

## 4. As features — e a regra que não pode ser quebrada

### Só do PRÉ-PERÍODO

**Toda feature sai dos 2 primeiros anos da janela.** Se qualquer feature tocar um ano do
pós-período, o modelo vê a resposta e o resultado inteiro é lixo. Este é o erro mais fácil de
cometer aqui.

### Sugeridas

| feature | de onde |
|---|---|
| classe do pixel no ano inicial | `pilha[0]` |
| fração construída na vizinhança 3×3, 5×5, 11×11 | convolução sobre `pilha[0] == 4` |
| fração de vegetação densa na vizinhança | idem para classe 1 |
| distância ao pixel construído mais próximo | `scipy.ndimage.distance_transform_edt` sobre `pilha[0] != 4` |
| distância ao centro do campus (metros) | `P11` já calcula a grade de distância |
| confiança média do classificador no pré-período | `*_confianca.tif` dos 2 primeiros anos |
| estabilidade do pixel no pré-período | trocou de classe entre ano 0 e 1? |
| sensor (`landsat` / `s2`) | do pareamento |

### Proibidas como feature

`site_id`, `município`, `UF`, `região`, `bioma`, `ano`, `x`, `y`, `linha`, `coluna`.

Mesma regra que o classificador já aplica (`src/sentinela/train.py`,
`COLUNAS_PROIBIDAS_COMO_FEATURE`, e a nota de revisão de SV-12): aprender geografia em vez de
padrão espacial quebra na primeira AOI nova. `bioma` é tentador e deve ficar de fora pelo mesmo
motivo — ele identifica o sítio.

---

## 5. Validação — leave-one-site-out, inegociável

**Split aleatório por pixel é proibido.** Pixels vizinhos são quase idênticos; um split aleatório
coloca o vizinho do pixel de teste dentro do treino e produz AUC de 0,95 que é mentira. Você tem
milhões de pixels mas **N efetivo = 20 sites**.

```
para cada um dos 20 campi:
    treina nos outros 19 (tratamento + controle de cada)
    prevê no campus retido (tratamento + controle)
agrega as 20 predições fora-da-amostra e mede uma vez só
```

O controle de um campus vai junto com o tratamento dele — nunca separados entre treino e teste.

### Métricas

Reporte **PR-AUC** (average precision) como principal. Com 1:40 de desbalanceamento, ROC-AUC
parece bom fácil demais.

### Os dois baselines que o modelo precisa bater

Um modelo que não bate os dois **não adiciona nada** e deve ser reportado como reprovado:

1. **Prevalência** — prever sempre a taxa base. PR-AUC ≈ 0,025.
2. **Distância ao construído mais próximo, sozinha** — uma única feature, sem modelo. Se o
   classificador completo não bate isso, ele só redescobriu "converte perto do que já é
   construído", que já sabíamos.

### Critério de aceite

> O modelo é adotado se, sob leave-one-site-out, o **PR-AUC superar o baseline de distância em
> pelo menos 20% relativo**, e se o ganho for consistente — positivo em pelo menos 14 dos 20
> sítios retidos.

Consistência importa: ganho médio alto puxado por 3 sítios e negativo em 12 não é modelo útil, é
sorte.

---

## 6. Saídas esperadas

```
modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py   # --fase dataset | treinar | avaliar
modelo-impacto/raw/controles-rf/
    conversao_dataset.parquet          # pixels, features, rotulo, site_id (para o split)
    conversao_loso_resultado.csv       # por sitio retido: PR-AUC do modelo e dos 2 baselines
    conversao_importancias.csv         # importancia de feature
    figuras/fig_20_conversao_loso.png  # PR-AUC por sitio, modelo vs baselines
models/conversao_v1.joblib             # so se PASSAR no criterio de §5
```

E um relatório curto em `reports/experiments/EXP-004-modelo-conversao.md` com: o protocolo, os
números, e o veredito contra o critério — **incluindo se reprovou**.

---

## 7. Armadilhas conhecidas

- **Vazamento temporal** — feature que toca o pós-período. A mais séria.
- **Split aleatório** — ver §5.
- **Reportar accuracy** — 97% sem fazer nada.
- **Incluir os pixels do próprio footprint do data center** — o prédio converte por construção e
  não é impacto no entorno. Use a máscara de anel (`P11.mascaras_por_raio`) e exclua o footprint
  onde ele existe, como o passo 26 faz.
- **Misturar tratamento e controle sem marcar** — o controle entra como dado de treino legítimo
  (é onde a conversão de fundo acontece), mas a coluna `tipo` deve existir no parquet para poder
  analisar separado depois.
- **Otimizar hiperparâmetro olhando o LOSO** — isso vaza. Se for tunar, use um loop interno
  dentro de cada treino de 19 sítios.

---

## 8. O que fazer se reprovar

Reportar. O trabalho já tem cinco resultados negativos documentados (portão §6, portão §4,
datação por Landsat, validação cruzada sob Dynamic World, cruzamento térmico greenfield) e eles são
parte da contribuição, não falhas escondidas.

Um "testamos prever onde a conversão acontece, com validação honesta, e não bateu o baseline
trivial" é publicável e defensável. Um PR-AUC de 0,95 obtido com split aleatório é o único
resultado deste projeto que não sobreviveria a uma pergunta da banca.
