# SV-31 — Projeção de impacto para área candidata (por análogo histórico)

- **Fase:** 4 — Produto · **Data-alvo:** 08–09/09 · **Tamanho:** M (~4h)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-30 (a assinatura agregada é a base de referência)
- **Desbloqueia:** SV-19 (endpoint), SV-19b (é a peça central da demo)
- **Tem seção de risco:** **SIM** (projeta números sobre terreno de terceiros)
- **Requer decisão do usuário antes de começar** — ver §"Recomendação"

## Contexto

O usuário levantou um objetivo de modelagem **novo e conceitualmente diferente** do que existe:

> *"um modelo que mostra o impacto que uma área vai ter se construir um data center nela"*

O que o repositório tem hoje é **retrospectivo**: um classificador por pixel que diz o que a cobertura
do solo **é** em cada ano, e (com SV-30) o que **mudou** em volta de data centers que já existem.
O que está sendo pedido é **prospectivo**: dada uma área **sem** data center, dizer o que aconteceria
se um fosse construído ali.

São coisas diferentes, e a diferença não é de esforço — é de tipo de inferência.

### Por que um modelo preditivo treinado está fora de alcance (e por que insistir nele seria pior)

A tentação natural é treinar um regressor: variáveis do terreno candidato → deltas observados.
Isso não se sustenta aqui, por três motivos independentes, e qualquer um deles já bastaria:

1. **N = ~20 casos.** A unidade de observação de um modelo de impacto **é o data center**, não o
   pixel. Não são 3,5 milhões de amostras — são ~20. Com dezenas de covariáveis candidatas (bioma,
   porte, MW, cobertura inicial, distância a infraestrutura, ano), qualquer regressor ajusta ruído
   perfeitamente e não generaliza. Uma banca de MBA em Engenharia de Dados vai perguntar o N,
   e a resposta "20" encerra a discussão.
2. **As covariáveis mais explicativas não existem neste repositório.** Porte em MW, área do terreno,
   investimento e licenciamento são exatamente as variáveis (D) que SV-28 documenta como **não
   coletadas por esta frente**. Treinar sem elas é treinar sem os preditores que importam.
3. **Não há prazo.** Restam ~10 dias úteis com V1 e documentação ainda por fechar.

Fazer o modelo mal e apresentá-lo como preditivo seria a decisão mais arriscada do projeto: produz um
número com aparência de rigor sobre o terreno de uma empresa real, sem nada por trás.

### A alternativa que cabe, é honesta, e responde à mesma pergunta

**Projeção por análogo histórico.** Não se treina nada novo. Usa-se o que SV-30 já mediu:

1. Classificar a área candidata **hoje**, com o modelo que já existe (SV-14).
2. Caracterizá-la: distribuição de classes, bioma, região, declividade se houver.
3. **Casar** com as AOIs históricas cuja situação **pré-obra** mais se parece com ela — a mesma
   distância L1 de cobertura já usada no pareamento de SV-29, mais o filtro de bioma.
4. **Projetar** sobre a candidata a faixa de deltas líquidos que aqueles análogos de fato
   apresentaram, como **mediana e intervalo interquartil**, nunca como número único.
5. Devolver: *"áreas com este perfil, neste bioma, apresentaram entre X e Y ha de conversão de
   vegetação para construído nos 4 anos seguintes ao início da obra (mediana Z, N = n casos análogos,
   contra o controle pareado)."*

Isso responde exatamente à pergunta do usuário, é defensável linha por linha, custa ~4 h, **reaproveita
integralmente a base ampliada** — que é justamente o que justifica ter expandido de 3 para 25 AOIs —
e é honesto sobre a incerteza em vez de escondê-la atrás de um `.predict()`.

## Recomendação ao usuário (decisão a tomar antes de começar)

| Opção | Custo | O que entrega | Risco |
|---|---|---|---|
| **A — Projeção por análogo (recomendada)** | ~4 h | Responde à pergunta, com faixa e N declarados | Baixo. Ninguém pode acusar de sobreajuste: não há ajuste |
| **B — Regressor treinado sobre ~20 casos** | ~8–12 h | Um `.predict()` que parece mais sofisticado | **Alto.** N=20, covariáveis-chave ausentes, e é a peça mais fácil de derrubar na banca |
| **C — Adiar para backlog** | 0 h | Nada agora | Perde-se o item que mais diferencia o projeto de "mais um classificador de imagem" |

**Recomendação: A.** Ela entrega a capacidade pedida, custa um quarto de B, e é a única das três que
não pede desculpa. Se houver tempo sobrando depois do congelamento — não vai haver — B pode virar
backlog documentado.

**Esta tarefa está escrita para a opção A.** Se o usuário escolher B ou C, ela precisa ser reescrita
antes de executar.

## Objetivo

Uma função e um CLI que recebem uma coordenada (ou polígono) sem data center e devolvem uma projeção
de impacto por análogo histórico, com faixa de incerteza, N de análogos e limitações explícitas.

## Escopo — o que fazer

1. **`src/sentinela/impacto/projecao.py`**, CLI
   `python -m sentinela.impacto.projecao --lat X --lon Y [--buffer-km 5] [--horizonte 4]`:
   - Ingere a AOI candidata pelo pipeline existente (só o ano mais recente — não a série inteira;
     projeção não precisa de histórico da candidata).
   - Classifica com o modelo versionado (SV-14).
   - Monta o perfil: distribuição de classes, bioma, região, índices médios.
   - Casa com os análogos: bioma igual (ou, se não houver, região igual, **declarando o afrouxamento**);
     L1 de cobertura ≤ 0,20 contra o **perfil pré-obra** das AOIs históricas; ordena por L1.
   - Projeta os deltas líquidos dos análogos: mediana + P25/P75, por classe e por índice.

2. **Saída** `outputs/projecao_{lat}_{lon}.json` **e** `.md`, contendo obrigatoriamente:
   `perfil_candidata`, `analogos` (lista com `aoi_id`, `l1`, `bioma`, `delta_liquido` de cada um —
   **os casos que sustentam o número precisam estar visíveis, um a um**), `projecao` (mediana, P25,
   P75, por classe), `n_analogos`, `horizonte_anos`, `limitacoes` (texto), `versao_modelo`, `git_sha`.

3. **Regras de recusa — parte central da tarefa, não detalhe defensivo.** A função **recusa
   projetar** e diz por quê quando:
   - `n_analogos < 3` → *"não há base histórica suficiente para esta combinação de bioma e perfil"*.
     **Recusar é o comportamento correto**, e é infinitamente melhor que extrapolar de um caso só.
   - a candidata já é predominantemente `construida_urbana` (> 60%) → não há o que converter;
   - a candidata cai a menos de 5 km de uma AOI conhecida → já é área de data center, não candidata;
   - o pareamento só fecha afrouxando bioma para região → projeta, **mas marca a projeção como
     `confianca: baixa`** e diz no texto que o afrouxamento aconteceu.

4. **Validação por leave-one-out — é isto que dá direito de apresentar o método.** Para cada AOI
   histórica, esconda-a, projete-a a partir das outras, e compare a projeção com o delta que ela de
   fato teve. Reporte: erro absoluto mediano, e **em quantos casos o valor real caiu dentro do
   intervalo P25–P75 projetado** (o esperado, se o método for calibrado, é ~50%).
   **Reporte o número que sair.** Se a cobertura der 20%, o método é mal calibrado e isso precisa
   estar escrito na apresentação — um método honesto e mal calibrado é resultado; um método mal
   calibrado apresentado como bom é o único desfecho realmente ruim aqui.

5. **Uma seção de texto pronta para a demo**, em linguagem de negócio, explicando em cinco linhas o
   que o método faz e o que ele **não** faz. É o que evita que a audiência ouça "modelo preditivo de
   impacto ambiental" e entenda algo maior do que foi entregue.

## Fora de escopo

- Treinar qualquer modelo novo. **Nenhum `.fit()` nesta tarefa.**
- Coletar MW, área do terreno, investimento, licenciamento (SV-28).
- Projetar impacto socioeconômico (população, emprego, PIB). A escala municipal não sustenta —
  SV-28 explica por quê, e repetir aqui seria contradizer o próprio handoff.
- Projetar além de ~4–6 anos: o horizonte máximo é o que a série de 2013–2025 observou de fato.

## Seção de risco

| Risco | Por que importa | Mitigação |
|---|---|---|
| **A projeção ser lida como previsão certa sobre um terreno real** | Alguém pode usar o número para argumentar contra ou a favor de um empreendimento | Sempre faixa, nunca número único; `n_analogos` e os análogos visíveis no output; limitações no próprio JSON, não só no relatório |
| **Extrapolar para bioma sem base** | Projetar Amazônia a partir de análogos do Sudeste é inventar | Regra de recusa com `n_analogos < 3`; afrouxamento de bioma sempre marcado |
| **Confundir com o classificador** | O classificador é validado com métricas medidas; a projeção não tem essa validação | Nomes, arquivos e texto separados; a validação leave-one-out é a única métrica que a projeção pode citar |
| **Aparentar rigor estatístico que não existe** | Mediana e IQR sobre ~20 casos não são inferência causal | Dizer "faixa observada em N casos análogos", nunca "intervalo de confiança" |

## Critérios de aceite

- [ ] CLI roda para uma coordenada arbitrária e devolve JSON + MD, ou uma **recusa explicada**.
- [ ] O output lista os análogos usados individualmente, com `l1` e delta de cada um.
- [ ] As quatro regras de recusa funcionam (uma delas testada com coordenada urbana e outra com
      coordenada em bioma sem base).
- [ ] Leave-one-out executado sobre todas as AOIs históricas elegíveis, com erro mediano e taxa de
      cobertura do intervalo **reportados, quaisquer que sejam**.
- [ ] `limitacoes` está preenchido em **todo** output, incluindo: N pequeno, ausência de controle
      climático, e o fato de não haver variáveis de porte do empreendimento.
- [ ] Nenhuma linha de código chama `.fit()`.
- [ ] O texto de demo existe e não usa "prevê", "vai causar" ou "garante".
- [ ] Rodar duas vezes com a mesma entrada → mesmo resultado.

## Cenários de teste

1. Coordenada rural em bioma com ≥ 3 análogos → projeção com faixa e lista de análogos.
2. Coordenada no centro de São Paulo → recusa por área já construída.
3. Coordenada em bioma sem base histórica → recusa por `n_analogos < 3`.
4. Coordenada a 2 km de uma AOI conhecida → recusa por proximidade.
5. Leave-one-out em `ascenty-vinhedo` → produz projeção sem usar a própria AOI (verificável na
   lista de análogos do output).
6. Determinismo: mesma entrada, duas execuções, saída idêntica.

## Como reportar

Informe: o resultado do leave-one-out (erro mediano e taxa de cobertura do intervalo), quantas AOIs
puderam ser projetadas e quantas foram recusadas e por quê, um exemplo de output completo, e —
com franqueza — **quão calibrado o método ficou**. Um método honesto e mal calibrado, reportado como
tal, é entrega válida; um método mal calibrado apresentado como bom, não.
