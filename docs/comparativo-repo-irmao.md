# Comparativo — `modelo-imagens-satelite` vs. `datacenter-extracao-modelos`

- **Autor:** frente de Modelagem/ML · **Data:** 2026-09-01
- **Repositório comparado:** `Sentinela-Verde/datacenter-extracao-modelos`, branches `main`
  (Guilherme) e `modelo-teste-tai` (Taimara) — **idênticas no momento desta análise** (mesmos 2
  commits: `ccbba0b`, `745c457`; Taimara ainda não divergiu de `main`).
- **Objetivo deste documento:** dar base para explicar, em linguagem não técnica, o que os dois
  repositórios têm em comum, o que fazem de diferente, e por que a nossa frente está levando mais
  tempo — sem sugerir que o outro time está "errado": são estágios de maturidade diferentes do
  mesmo objetivo.

---

## 1. Mesma missão, mesmo ponto de partida

Os dois projetos nasceram do mesmo objetivo do MBA: usar imagens de satélite para acompanhar, ao
longo do tempo, como a área ao redor de um data center muda (vegetação some, solo é exposto,
construção aparece). Os dois inclusive compartilham o mesmo primeiro site (**Ascenty Vinhedo**).

A partir daí, os caminhos divergem — o repo irmão prioriza ter um pipeline completo rodando rápido
em 1 site; o nosso prioriza que o resultado aguente uma banca crítica em ~20-25 sites.

## 2. O que cada um entrega, de fato (o produto final)

**Deles, hoje:** para 1 site (Ascenty Vinhedo), mapas de cobertura do solo classificados ano a
ano (2016-2026), uma tabela de % de área e km² por classe por ano, um gráfico da evolução dessas
classes no tempo, e imagens de sobreposição (RGB + máscara) para inspeção visual. O indicador de
impacto — a parte que diria "isso foi causado pelo data center" — **não está implementado**, só
desenhado no papel (`impact.py`).

**Nosso, na forma final:** o mesmo tipo de entrega — mapas classificados, tabela de área por
classe, evolução no tempo — só que para ~20-25 sites em vez de 1, com uma categoria dedicada para
"início de obra" (o sinal que o projeto existe para detectar, e que o deles nem tenta isolar), e,
quando SV-29/SV-30 terminarem, um indicador de impacto de verdade: contraste contra sites parecidos
sem data center, não só antes/depois do mesmo site.

**Ou seja:** não é um produto diferente — é o mesmo tipo de resultado, escalado e blindado contra
as perguntas que derrubam a versão deles numa arguição.

## 3. Perguntas de banca que o modelo deles não responde

| Pergunta da banca | Resposta deles | Resposta nossa |
|---|---|---|
| O gabarito de treino é do mesmo ano da imagem? | Não — é uma foto única de 2021 (WorldCover) aplicada a 2016-2026 inteiro | Sim — gabarito anual (MapBiomas), casado ano a ano |
| Como você separou treino e teste? | Pixel aleatório — risco de o modelo "colar" pixels vizinhos e inflar a acurácia, sem forma de provar que não aconteceu | Blocos geográficos, com experimento medindo o tamanho desse risco |
| A queda de vegetação foi causada pelo data center ou aconteceria de qualquer jeito? | Sem grupo de controle — só antes/depois de 1 site, não isola a causa | Grupo de controle pareado (em construção, SV-29/30) — compara contra sites parecidos sem data center |
| Como você distingue obra em andamento de solo exposto natural? | Não distingue — cai tudo em "Outro" | Categoria dedicada + rotulagem manual com guia por bioma |
| Isso generaliza para outros data centers? | Não é possível afirmar com N=1 | ~20-25 sites em múltiplos biomas |
| A coordenada usada é a do data center certo? | Lista manual em .txt, sem checagem declarada | 5 camadas de validação automática por site |

## 4. Comparativo lado a lado

| Dimensão | `datacenter-extracao-modelos` | `modelo-imagens-satelite` (este repo) |
|---|---|---|
| Sites processados | 1 (Ascenty Vinhedo) de 10 listados | 16 hoje, meta ~20-25, em múltiplos biomas |
| Satélites usados | Só Sentinel-2, 2016-2026 inteiro | Landsat 8/9 (2013-2018) + Sentinel-2 (2019-2025), "traduzidos" para a mesma escala |
| Gabarito (label) | 1 única foto do WorldCover (2021), aplicada a todos os anos | Gabarito ano a ano (MapBiomas Coleção 9), casado com o ano de cada imagem |
| Classes de cobertura | 5, sem categoria própria para "obra em andamento" (cai em "Outro") | 5, com categoria dedicada "solo exposto/em obras" — a mais importante do projeto |
| Rotulagem manual | Não tem | Sim — obrigatória, porque nenhuma fonte automática identifica "canteiro de obras" de verdade |
| Separação treino/teste | Pixels aleatórios (risco de o modelo "colar" áreas vizinhas quase idênticas) | Blocos geográficos, com 2 experimentos medindo esse risco, não só evitando-o |
| Validação de coordenada | Lista manual, sem checagem formal declarada | 5 camadas de checagem automática por site (país, município, uso do solo, colisão com outro site, distância a coordenada conhecida) |
| Modelos treinados | Random Forest + rede neural (Keras) | Random Forest (V1); rede neural é "Plus", adiada por decisão consciente de prazo |
| Indicador de impacto | Desenhado no papel (`impact.py`, placeholder), não implementado | Em construção: grupo de controle pareado (SV-29) + perfil pré/durante/pós (SV-30) |
| Registro de proveniência | Não declarado | Cada dataset tem manifest com hash, parâmetros e métricas versionados |

## 5. O que o repo irmão já tem que nós ainda não temos

- **Pipeline ponta a ponta rodando de verdade**, com imagens baixadas, rótulo aplicado, modelo
  treinado e gráfico de evolução temporal gerado — para 1 site.
- **Desenho pronto no papel para o indicador de impacto causal** (diferença-em-diferenças +
  event-study com grupo de controle) — nós temos a mesma ideia (SV-29/SV-30), mas ainda não
  implementada.
- Uma segunda arquitetura de modelo (rede neural) já testada, ainda que sem o cuidado de split
  espacial que tornaria essa métrica confiável.

## 6. Catálogo de robustez — por que o nosso está demorando mais

Cada item abaixo é um passo que o pipeline do repo irmão **não faz**, e que só existe no nosso
porque, sem ele, o resultado não resistiria a uma pergunta simples de banca. Nenhum é
"perfeccionismo" — cada um resolve um jeito específico e real do modelo mentir para a gente mesmo.

### 4.1 Harmonizar dois satélites diferentes

Sentinel-2 e Landsat enxergam a mesma cor do mundo com sensores fisicamente diferentes. Sem
correção, um pixel pode mudar de valor **só porque o satélite mudou**, mesmo que nada tenha
mudado no chão — e o modelo aprenderia a diferença de satélite como se fosse diferença de
paisagem. Medimos esse desvio banda a banda (3 de 6 bandas ficaram fora da tolerância sem
correção) e aplicamos coeficientes de ajuste publicados pela NASA para o produto HLS antes de
misturar as duas eras no mesmo modelo, mais uma feature explícita dizendo ao modelo "esta imagem
veio de qual satélite". O repo irmão usa só Sentinel-2 o tempo todo — não precisa resolver isso,
mas também não cobre 2013-2018.

### 4.2 Gabarito que muda com o ano, não uma foto congelada

Usar uma única foto de referência de 2021 para "ensinar" o modelo o que é floresta em 2013 ou em
2025 embute um erro sistemático: o gabarito não sabe que o mundo mudou entre um ano e outro. Nós
medimos esse efeito (até 8 anos de defasagem geraram 4-6% de pixels rotulados errado em alguns
sites) e trocamos para um gabarito anual, casado ano a ano com a imagem correspondente.

### 4.3 Ensinar o modelo a reconhecer canteiro de obras de verdade

Nenhuma fonte automática (nem WorldCover, nem MapBiomas) tem uma categoria "obra em andamento" —
ambas confundem isso com solo exposto genérico ou vegetação rala. Como essa é a classe mais
importante do projeto (é o sinal de "aqui vai nascer um data center"), criamos um processo de
rotulagem manual com guia próprio por bioma (porque o mesmo padrão visual — vegetação sem folha,
por exemplo — significa coisas diferentes na Caatinga e na Mata Atlântica), quotas mínimas por
região, e um teste de auto-consistência (rotular a mesma amostra duas vezes e medir se bate) antes
de aceitar o resultado como confiável.

### 4.4 Garantir que o modelo não está "colando"

Separar treino e teste por pixels aleatórios é fácil, mas se dois pixels vizinhos (quase idênticos)
caem um no treino e outro no teste, o modelo "acerta" sem ter aprendido nada generalizável — é
como estudar para a prova com a prova em mãos. Separamos por blocos geográficos inteiros e,
**mais importante, medimos o tamanho desse efeito** com um experimento de controle (comparando o
desempenho com separação aleatória vs. por bloco) em vez de simplesmente presumir que o cuidado
resolveu o problema.

### 4.5 Confirmar que cada coordenada é o data center certo

Antes de qualquer site entrar no projeto, a coordenada passa por 5 checagens automáticas
(está no Brasil, bate com o município declarado, tem uso do solo compatível com um empreendimento
desse tipo no entorno, não colide com outro site já cadastrado, e está perto de qualquer
coordenada de referência conhecida). Errar isso silenciosamente treinaria o modelo em cima do
lugar errado sem ninguém perceber.

### 4.6 Comparar contra um grupo de controle, não só "antes x depois"

"A vegetação caiu 12% ao redor do data center" só vira evidência de impacto quando comparada com
"quanto caiu num lugar parecido, no mesmo período, sem data center". Sem isso, 12% pode ser só o
que aconteceu na região inteira (clima, expansão urbana geral). Isso está em construção (SV-29/
SV-30) e é também a peça que falta no repo irmão (`impact.py` ainda é só o desenho).

### 4.7 Escala: 16-25 sites em vários biomas, não 1

Cada bioma novo (Caatinga, Cerrado, Amazônia) tem seus próprios "confusores" — coisas que parecem
solo exposto mas não são (vegetação decídua na seca, pastagem degradada, estrada de terra). Cada
bioma exige uma leitura própria do guia de rotulagem, testada, antes de confiar no resultado ali.
Processar 1 site não expõe esses problemas; processar em múltiplos biomas expõe — e resolver cada
um leva tempo real.

## 7. O que ainda falta do nosso lado

- **Indicador de impacto com grupo de controle** (SV-29/SV-30) — o repo irmão já tem o desenho no
  papel; nós ainda estamos implementando.
- **Rede neural / deep learning** — adiada conscientemente para depois do prazo do V1 (decisão de
  escopo, não esquecimento).
- Variáveis externas (clima, áreas protegidas, dados socioeconômicos) — decisão deliberada de não
  coletar dentro deste repositório; ver `docs/requisitos-dados-externos.md` para o que foi
  delegado à Engenharia.

## 8. Como resumir isso numa frase, para quem não é de ML

> "Os dois projetos têm o mesmo objetivo. O do Guilherme e da Taimara já roda ponta a ponta rápido
> em 1 site; o nosso está mais lento porque decidimos resolver antes os problemas que só aparecem
> quando o modelo precisa valer para 20+ sites em biomas diferentes — sensores diferentes,
> gabarito desatualizado, vazamento de dados entre treino e teste, coordenada errada. Um modelo
> bonito treinado em cima de um desses problemas escondidos não resiste à primeira pergunta crítica
> de uma banca."
