# ADR-006 — Classificador global (Brasil + EUA): rótulos, base de treino e validação

- **Status:** **Proposto** — aguarda decisão do owner
- **Proposto em:** 2026-09-10
- **Contexto que gerou:** a amostra brasileira tem teto medido de ~25 campi (passo 25); a
  temperatura precisaria de n=31 e a janela longa é inconclusiva com n=9. N não melhora com método
  melhor — melhora com mais casos, e os casos estão nos EUA.
- **Não redecide** as 5 classes (fechado, `docs/classes.md`) nem a janela 2013–2025 (ADR-001).

## Contexto

Hoje o classificador é treinado com rótulos do **MapBiomas**, que só existe para o Brasil. Isso
trava a expansão da amostra em dois pontos:

1. **Não há como classificar um site americano** — o rótulo não existe lá.
2. **A classe 3 (`solo_exposto_obras`) é a pior do modelo** (F1 0,579), porque o MapBiomas **não
   tem** classe de canteiro de obras e os rótulos são um proxy de solo nu natural (ADR-004).

O **Google Dynamic World** resolve os dois de uma vez: é global (10 m, jun/2015 em diante) e tem
uma classe **`bare` nativa**. Verificado em 2026-09-10 via `ee`: 44 cenas em Ashburn/VA em 2018,
43 em 2022 — o maior cluster de data centers do mundo tem cobertura equivalente à brasileira.

## Decisão proposta

### 1. UM modelo, não dois

Um classificador único treinado com Brasil e EUA juntos.

**Por quê:** se cada país tiver seu modelo, os resultados dos dois não são comparáveis — o
instrumento mudaria entre as duas metades do estudo, e a comparação entre elas viraria uma
comparação de instrumentos. É a mesma lógica da regra de **sensor único por par** (SV-20), pela
mesma razão.

**O risco disso, e como controlar:** um modelo único pode aprender *região* em vez de *cobertura* —
"pixel na Virgínia" em vez de "pixel de floresta". Três travas:

- **País, bioma e ecorregião NÃO entram como feature.** Mesma regra que SV-27 já aplica a bioma.
- **`sensor` continua como feature** (ADR-003), mas com o teto de amostragem corrigido — ver §3.
- O teste de generalização é **entre países**, não dentro — ver §4.

### 2. Rótulos: Dynamic World, com remapeamento explícito

```
water(0), flooded_vegetation(3), snow_and_ice(8) -> 5  agua
trees(1)                                          -> 1  vegetacao_densa
grass(2), crops(4), shrub_and_scrub(5)            -> 2  vegetacao_rala
built(6)                                          -> 4  construida_urbana
bare(7)                                           -> 3  solo_exposto_obras
```

**Composto anual:** moda da estação seca, mesma janela de meses da pipeline atual. Para dado
categórico, moda é o equivalente do composto mediano usado para reflectância.

**Ressalva que precisa acompanhar a decisão:** o `bare` do DW **também não é** "canteiro de obras".
É solo nu — o que inclui deserto, praia e lavoura arada. No Brasil isso é gerenciável; **nos EUA é
um problema maior** (Arizona, Nevada, Utah têm data centers em deserto). Duas consequências:

- a **rotulagem manual de canteiro de obras continua obrigatória**, agora nos dois países;
- sites em bioma desértico entram com marcação própria e devem ser analisados em estrato separado.

### 3. A base de treino, e o bug que ela precisa NÃO repetir

**Unidade:** pixel × site × ano × sensor. **Features:** as 13 atuais (6 bandas harmonizadas +
índices espectrais). **Rótulo:** DW remapeado.

**O bug a corrigir, medido em 2026-09-10:** o teto de amostragem atual é de 4.000 pixels por
classe × site × ano × sensor, **por contagem de pixel**. As classes abundantes enchem o teto nos
dois sensores, mas a classe 3 **nunca** enche no Landsat (mediana 229 px, máximo 1.205), porque um
pixel de 30 m cobre 9× a área de um de 10 m. Resultado: a classe 3 é **2,9%** das linhas Landsat
contra **17,3%** das S2 — e como `sensor` é feature, o modelo aprendeu o prior condicionado ao
sensor e o reproduz na saída (2,4% previsto no Landsat contra 19,3% no S2).

**Correção obrigatória:** teto por **ÁREA** (hectares), não por contagem de pixel. Equivalente:
teto de `N/9` para Landsat quando o de S2 for `N`. Sem isso, o modelo global nasce com o mesmo
defeito e ele fica pior, porque a mistura de sensores por país é desbalanceada.

**Estratificação da amostra:** país × ecorregião × sensor × classe. Nenhum país pode dominar uma
classe — se 90% dos exemplos de `bare` vierem do deserto americano, a classe 3 vira "deserto".

**Splits, em três eixos:**

| eixo | regra | o que protege |
|---|---|---|
| espacial | segura **sites inteiros**, nunca pixels | vazamento por autocorrelação espacial |
| temporal | segura **anos inteiros** | vazamento por série |
| **entre países** | treina BR → testa EUA, e treina EUA → testa BR | é o único teste real de "global" |

### 4. Critério de sucesso — e ele NÃO é acurácia

Acurácia contra o DW mede só quão bem destilamos o DW. A pergunta que importa para esta frente é
outra: **o modelo é temporalmente estável?** A estatística de trajetória exige que um pixel
mantenha a classe por anos; um classificador que oscila destrói o sinal antes de qualquer análise.

A métrica já existe e já foi medida (passo 24): **% de pixels que trocam de classe entre anos
consecutivos nos pontos de CONTROLE**, onde por construção quase nada mudou e toda troca é ruído.

| instrumento | instabilidade nos controles |
|---|---:|
| Dynamic World | **7,3%** |
| `rf_v1.0-tuned` (atual) | **16,8%** |

**O modelo atual é 2,3× mais instável que o DW.** Isso define o critério de aceite do retreino:

> O modelo global só substitui o atual se ficar **abaixo de 7,3%** de instabilidade nos controles —
> ou seja, se for mais estável que o próprio rótulo que o treinou. Se não for, usar o Dynamic World
> direto é a decisão certa, e treinar modelo próprio não se justifica.

É um critério que pode reprovar a própria decisão deste ADR, e é de propósito.

### 5. O que muda no desenho de impacto para os EUA

| peça | Brasil | EUA |
|---|---|---|
| pareamento | mesmo estado + mesmo bioma, 15–40 km | mesmo estado + mesma **ecorregião EPA nível III** |
| ano da obra | imprensa (SV-24) + datacentermap | **em aberto** — é o gargalo, ver §6 |
| contaminação | nenhum controle perto de DC conhecido | idem, com lista americana |
| placebo | controle vs controle | **repetir nos EUA**, não herdar o resultado brasileiro |

O placebo **não se herda**. Ele mede a taxa de falso positivo do método *naquele território*, com
aquele classificador e aquela paisagem. Rodar de novo é obrigatório.

## 6. O risco que pode matar a expansão — e o funil é mais estreito do que eu escrevi

**Não é o classificador nem o rótulo.** A expansão brasileira (passo 25) foi executada e mediu o
funil inteiro, em vez de estimá-lo:

| etapa | restam | perda |
|---|---:|---|
| registros no `datacentermap` | 242 | — |
| campi distintos (prédios <2 km agrupados) | 118 | duplicidade de campus |
| com ano documentado | 53 | **65 sem data** |
| com janela de satélite utilizável | 16 | 22 antes de 2016, 15 recentes demais |
| **novos** (fora dos 16 validados) | 10 | 6 já eram nossos |
| **com controle pareável** | **5** | **4 urbanos demais, 1 sem `uf` na fonte** |

**O gargalo tem dois estágios, não um.** Eu havia escrito só o primeiro (a data). O segundo só
apareceu ao rodar: **metade dos campi que têm data não consegue controle**. São sites urbanos densos
onde o anel de 15–40 km cai em outro município ou perto de outro data center. Isso não é defeito do
filtro — é o filtro funcionando: um "controle" contaminado seria pior que nenhum.

Nota de leitura, para não superestimar a perda: os 5 que passaram saem como `ruim` (L1 > 0,20), mas
os **15 pares originais também são 10 `ruim`**, com L1 mediano de 0,489. "Ruim" é a norma deste
dataset, não uma degradação dos novos.

**Portanto o portão antes do retreino precisa medir as DUAS etapas:**

> Levantar a lista americana e medir **quantos campi têm data, janela 2018–2022 utilizável E
> sobrevivem ao pareamento**. Pela taxa brasileira, espere perder ~50% na etapa de pareamento — o
> que significa que uma lista com 60 campi datados pode render 30, não 60.
>
> Se o resultado final for menos de ~30 campi novos **pareados**, o retreino não se paga: o custo é
> o mesmo e o ganho de N não resolve nenhum dos resultados que hoje travam por amostra.

Há uma razão para esperar taxa **melhor** nos EUA, e ela deve ser verificada e não assumida: muitos
data centers americanos ficam em áreas rurais ou peri-urbanas (Virgínia rural, Iowa, Oregon), onde
achar um par a 15–40 km com cobertura parecida é bem mais fácil que em São Paulo.

É a mesma disciplina do portão do CEP (que aprovou) e do portão de acesso ao CNPJ (que reprovou):
**medir a viabilidade antes de construir em cima dela** — e, agora, medir o funil inteiro em vez de
só a primeira peneira.

## Alternativas consideradas

**(a) Usar o Dynamic World direto, sem classificador próprio.** Mais simples, sem risco de
retreino, e global de imediato. Perde a contribuição de modelagem da frente e o controle sobre a
definição das classes. **Torna-se a decisão correta automaticamente se o critério de §4 reprovar o
retreino.**

**(b) Dois modelos, um por país.** Rejeitado: destrói a comparabilidade entre as duas metades do
estudo, que é justamente o motivo de expandir.

**(c) Manter MapBiomas e expandir só no Brasil.** É o caminho de menor risco, e continua disponível
— mas o teto medido é ~25 campi, insuficiente para os eixos que travam por N.

## Consequências se aceito

- `config/params.yml`: nova seção `labels.fonte = dynamic_world`, com o remapeamento de §2.
- `dataset.py`: teto por área (§3). **Muda todos os números a jusante** e exige refazer a cadeia.
- Novo eixo de split (país) em `atribuir_split`.
- `docs/classes.md`: registrar que a classe 3 passa a ter `bare` como proxy, e a implicação para
  sites desérticos.
- **Toda a análise de impacto precisa ser reexecutada.** Enquanto o retreino não fecha e não passa
  no critério de §4, o `rf_v1.0-tuned` continua sendo o modelo de produção.
