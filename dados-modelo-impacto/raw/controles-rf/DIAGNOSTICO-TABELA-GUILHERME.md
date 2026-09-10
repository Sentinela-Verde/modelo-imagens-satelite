# Por que não usamos a tabela de pontos de controle — diagnóstico numérico

**Para:** Guilherme (frente do modelo de impacto)
**De:** Gabriel (frente do classificador de imagem / `modelo-imagens-satelite`)
**Gerado em:** 2026-09-10 21:35 UTC por `dados-modelo-impacto/scripts/impacto_dc_01_reconciliar.py`

Recebi `datacenter_filtrado.csv` (12 data centers) e `datacenter_expandido_6_pontos.csv`
(6 candidatos a controle por data center, 72 pontos). Antes de rodar o classificador em cima
deles, medi os pontos contra a lista de sites já validados deste repositório. Achei três coisas
que impedem usar a tabela como está. **Nenhuma delas é erro de digitação — são consequências do
desenho do gerador**, e por isso valem uma conversa antes de você rodar de novo.

Tudo aqui é reproduzível: rode o script acima e ele regenera este documento e os dois CSVs de
apoio a partir dos seus arquivos originais.

---

## 1. Os 12 data centers são 8 lugares, não 12

Todos os 12 estão a **no máximo 1.02 km** de um site que este
repositório já validou (`config/sites.geojson`, validação de coordenada em 5 camadas). Não são
pontos novos — e, principalmente, **vários deles são o mesmo lugar**:

| campus | prédios na sua lista | quais |
|---|---:|---|
| `ascenty-hortolandia` | 4 | Ascenty - Hortolandia HTL2, Ascenty - Hortolandia HTL4, Ascenty - Hortolandia HTL3, Ascenty - Hortolandia HTL5 |
| `ascenty-osasco` | 2 | Ascenty - Sao Paulo SP3, Ascenty - Sao Paulo SP4 |

Os 4 prédios de Hortolândia estão a
**56–193 m** um do outro; os de Osasco, a **164 m**. O buffer de análise do classificador é de
**5 km de raio**. Nessa escala eles são o mesmo recorte de terreno: rodar o modelo nos 4 prédios de
Hortolândia produz quatro linhas praticamente idênticas, o que infla a contagem de amostras sem
adicionar informação nenhuma ao modelo de impacto.

**Consequência prática boa:** como todos já são sites validados, o `ano_inicio_obra` de cada um já
está pesquisado e conferido aqui — não precisamos ir atrás dele. Vale notar que
`ano_operacional` (o que está no seu CSV) **não é** o ano de início da obra: nos 15 sites
validados, a defasagem entre obra e operação é de 0 ano em 7 casos, 1 ano em 4 e 2 anos em 2.
Usar `ano_operacional` como se fosse o começo da obra deslocaria a janela "antes/depois" em até
2 anos, justamente na direção que borra o efeito que você quer medir.

---

## 2. Os candidatos a controle: 14 dos 72 caem dentro do raio de influência de outro data center

Reconstruí a geometria do gerador para ter certeza de que estava lendo certo. Ele:

1. escolhe um **município "similar"** ao do data center;
2. mede a distância do data center até o centróide do **próprio** município (a coluna
   `distancia_km`);
3. monta um **hexágono de 6 pontos com esse mesmo raio** em volta do ponto de referência do
   município similar (colunas `latitude_similar`/`longitude_similar`).

A ideia por trás disso é boa — replicar "a que distância do centro urbano o empreendimento fica"
num município comparável. O problema é que **o passo 3 não checa se o lugar onde os 6 pontos caem
já tem um data center do estudo dentro**. E tem:

| campus | município | prédios | dist. dos candidatos ao próprio DC | tratamento mais próximo de um candidato | contaminados |
|---|---|---:|---|---|---:|
| `ascenty-hortolandia` | Hortolândia/SP | 4 | 126,4–138,2 km | 79,8 km (`ascenty-osasco`) | 0/24 |
| `ascenty-jundiai` | Jundiaí/SP | 1 | 11,7–29,7 km | 11,6 km (`ascenty-jundiai`) | 0/6 |
| `ascenty-osasco` | Osasco/SP | 2 | 31,0–40,2 km | 5,3 km (`ascenty-jundiai`) | 4/12 |
| `ascenty-paulinia` | Paulínia/SP | 1 | 33,2–41,1 km | 2,4 km (`ascenty-vinhedo`) | 4/6 |
| `ascenty-sumare` | Sumaré/SP | 1 | 24,9–36,0 km | 15,6 km (`odata-hortolandia`) | 0/6 |
| `equinix-santana-parnaiba` | Santana de Parnaíba/SP | 1 | 161,1–172,1 km | 132,3 km (`ascenty-paulinia`) | 0/6 |
| `scala-sgigsm01` | São João de Meriti/RJ | 1 | 363,5–366,9 km | 2,2 km (`scala-tambore`) | 6/6 |
| `scala-spoapa01` | Porto Alegre/RS | 1 | 537,3–545,6 km | 323,2 km (`equinix-santana-parnaiba`) | 0/6 |

(O denominador da última coluna é 6 candidatos por **prédio** — campi com mais de um prédio na sua
lista aparecem com 12 ou 24, porque a tabela repete os 6 pontos para cada `id_datacenter`.)

Os casos mais graves:

- **São João de Meriti (RJ)** → o município similar escolhido foi **Carapicuíba/SP**, a 364 km.
  Os **6 de 6** candidatos caem a **2,2–5,4 km** do `scala-tambore` (Barueri/SP), que é um data
  center do estudo. Os buffers de 5 km se sobrepõem quase inteiramente: esses pontos medem o
  entorno de um data center, não um controle.
- **Paulínia** → município similar Louveira/SP. **4 de 6** candidatos caem a **2,4–7,7 km** do
  `ascenty-vinhedo` / `ascenty-jundiai`.
- **Osasco** → o município similar escolhido foi **Jundiaí/SP**, que **hospeda** o
  `ascenty-jundiai` — um dos data centers da sua própria lista. 2 dos 6 pontos de cada prédio
  (4 das 12 linhas de Osasco) ficam a 5,3–6,0 km dele.

Um ponto de controle dentro do raio de influência de um data center é o erro mais grave possível
neste desenho: ele é tratamento disfarçado de controle, e o efeito medido encolhe na direção de
zero sem que nada no resultado indique que houve problema.

---

## 3. Os 6 candidatos de cada data center não são 6 amostras independentes

O raio do hexágono é a distância data center → centróide do município, que na sua tabela varia de
**1,76 km a 9,14 km**. Como o buffer de análise tem 5 km de raio, os buffers de candidatos
vizinhos se sobrepõem:

| raio do hexágono | exemplo | sobreposição entre buffers vizinhos |
|---|---|---|
| 9,12 km | Jundiaí | 3% |
| 5,90 km | Hortolândia | 30% |
| 4,58 km | Paulínia | 44% |
| **1,76 km** | **São João de Meriti** | **78%** |

Em São João de Meriti, escolher "o melhor dos 6" é escolher entre 6 recortes que compartilham
quase 80% da mesma área. Na prática é 1 candidato, não 6 — e o pareamento por similaridade fica
sem margem de escolha real.

---

## 4. Três candidatos ficam em outro estado, um deles em outro bioma

| data center | município similar escolhido | distância |
|---|---|---|
| Scala Porto Alegre (RS) | **Curitiba/PR** | 537–546 km |
| Scala São João de Meriti (RJ) | **Carapicuíba/SP** | 363–367 km |
| Equinix Santana de Parnaíba (SP) | **Pouso Alegre/MG** | 161–172 km |

O caso de Porto Alegre é o mais problemático: sai do **Pampa** e entra na **Mata Atlântica**. A
vegetação de base, o regime de chuva e a sazonalidade são outros — o classificador vai acusar
diferença de cobertura entre tratamento e controle que não tem nada a ver com o data center. Um
controle precisa diferir do tratamento **só** por não ter recebido o empreendimento.

---

## O que fizemos no lugar

Regeneramos os candidatos com o método que este repositório já tinha desenhado e documentado
(`docs/tarefas/SV-29-grupo-controle-pareado.md`, aplicado em
`dados-modelo-impacto/scripts/gerar_controles_pareados.py`), que resolve exatamente os quatro
pontos acima:

- **anel de 15 a 40 km** do data center — longe o bastante para sair do raio de influência do
  empreendimento, perto o bastante para manter regime de licenciamento, pressão de expansão urbana
  e regime de chuva comparáveis;
- **mesmo município ou mesma microrregião do IBGE** — o que também mantém bioma e clima, sem
  precisar cruzar meio país atrás de um município socioeconomicamente parecido;
- **checagem de contaminação explícita**: todo candidato precisa estar a ≥ 10 km (a soma dos dois
  buffers de 5 km) de qualquer site de tratamento e de qualquer controle já escolhido, e a ≥ 5 km
  de uma lista de 38 pontos de contaminação (que inclui os data centers **rejeitados** do estudo —
  são justamente lugares onde há data center e que não entraram na amostra);
- **candidatos espalhados pelo anel** (7 raios × 24 azimutes), então os candidatos de um mesmo
  site não são recortes sobrepostos um do outro.

A escolha final entre os candidatos usa a **saída do nosso classificador Random Forest** (área por
classe de cobertura do solo num buffer de 5 km, no ano anterior ao início da obra), pegando o
candidato de menor distância L1 contra o tratamento. Detalhe completo em
`dados-modelo-impacto/raw/controles-rf/METODOLOGIA.md`.

## O que ainda vale de você

- **A ideia do município socioeconomicamente similar não foi descartada** — ela é melhor que a
  nossa para as variáveis socioeconômicas (população, emprego, PIB). O que ela não serve é para
  parear **cobertura do solo**, que é o que o classificador mede. Se você quiser manter os dois
  critérios, dá para usar o município similar como estratificação e o anel geográfico como
  controle de cobertura — mas aí são dois controles com papéis diferentes, não um só.
- **Se você regerar a tabela**, os dois checks que faltam no gerador são baratos: (a) rejeitar
  candidato a menos de 10 km de qualquer data center conhecido (não só os 12 da lista); (b) exigir
  raio de hexágono ≥ 10 km, senão os 6 pontos se sobrepõem.
- **A duplicação de prédios** (`Ascenty Hortolandia HTL2/3/4/5`, `Ascenty SP3/SP4`) vale corrigir
  na origem: se o modelo de impacto tratar cada prédio como uma observação, Hortolândia entra com
  peso 4 e Porto Alegre com peso 1, sem que isso seja uma decisão de ninguém.

## Arquivos de apoio (números crus, para conferir)

- `reconciliacao_datacenters.csv` — os 12 `id_datacenter`, o site validado que cada um casou, a
  distância do casamento e o `ano_inicio_obra` que passamos a usar.
- `diagnostico_candidatos_guilherme.csv` — os 72 candidatos, ponto a ponto, com distância ao
  próprio data center, distância ao site de tratamento mais próximo e a marca de contaminação.
