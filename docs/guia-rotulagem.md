# Guia de rotulagem manual — "solo exposto / em obras"

Produzido em SV-09, para ser usado em SV-10. Leia inteiro antes de abrir o QGIS — é mais rápido
ler 10 minutos agora do que rotular 30 polígonos errado e ter que refazer.

Se você está cansado(a) lendo isto: a seção que mais importa é **"Os 5 casos que confundem"**.
Se só der para ler uma parte, leia essa.

## 1. O que este kit te entrega

- `data/interim/candidatos_{site_id}.geojson` — até 60 polígonos por site, já localizados por uma
  heurística (BSI alto + NDVI baixo, ver `src/sentinela/labeling/candidatos.py`), **ordenados por
  área**, numerados (`candidato_id`). Eles são só sugestões de onde olhar — **nenhum campo aqui é
  um label**. `classe_id` vem sempre `null` de propósito.
- `reports/figures/rotulagem/{site_id}/{ano}_rgb.png` e `{ano}_falsacor.png` — um par de imagens
  por ano disponível do site, com os candidatos numerados desenhados por cima. Mesma extensão
  física em todos os anos do mesmo site, então dá para comparar "antes/depois" só olhando duas
  imagens lado a lado.
- `data/labels_manual/_template.geojson` — copie para `data/labels_manual/{site_id}.geojson` e
  rotule em cima dessa cópia (nunca edite o template original).

## 2. O que é classe 3 (`solo_exposto_obras`)

Marque como classe 3 quando o polígono é, predominantemente:

- **Terraplenagem** — terreno raspado/nivelado, sem vegetação, com marcas de máquina.
- **Canteiro de obra** — qualquer área com movimentação de terra, maquinário, contêineres de
  obra, material de construção empilhado.
- **Área raspada** — vegetação removida recentemente, solo cru à mostra, contornos irregulares.
- **Pilha de terra / entulho** — monte de material solto, sombra própria visível na imagem.
- **Estrada de terra larga dentro do canteiro** — via de acesso temporária, informal, ligada a uma
  área de obra ativa (ver caso de confusão 5 abaixo para separar isso de via pública).
- **Solo natural exposto sem vegetação** — mesmo sem ser obra visível, se não há nenhuma cobertura
  vegetal nem uso construído.

**Regra prática:** se, olhando a imagem, sua primeira reação for "aqui não tem nada crescendo e
não tem prédio", é candidato forte a classe 3. O que resta é descartar os "quase" — a seção 3.

## 3. Os 5 casos que confundem (decisão fechada — não reabra dúvida sobre estes)

### 3.1 Telhado claro / laje → **é classe 4** (`construida_urbana`), nunca 3

Telhado metálico claro, laje de concreto exposta e pátio pavimentado claro podem ter reflectância
tão alta quanto solo exposto no RGB. Diferencie por:

- **Forma**: telhado/laje tem contorno **reto e geométrico** (retângulos, ângulos de 90°). Obra e
  solo exposto têm contorno **irregular, orgânico**, seguindo o relevo/uso do terreno.
- **Contexto**: telhado está cercado de outras estruturas construídas (ruas, estacionamento,
  outros prédios). Solo exposto costuma estar isolado ou cercado de vegetação/terra.
- **Falsa-cor** (seção 4): telhado muito claro tende a ficar **branco estourado** nas três bandas
  ao mesmo tempo (sem dominância de nenhum canal). Solo mineral exposto tende a **magenta/rosa**
  (SWIR1 e Red altos, NIR mais baixo que os dois).

### 3.2 Estacionamento de terra batida consolidado → **regra de borda, decida por uso**

Não existe um sinal espectral que separe isso de forma limpa — a decisão é por **evidência de
uso**:

- Se há **veículos estacionados, marcação de vagas, ou o padrão se repete ano a ano sem virar
  vegetação nem obra** → **classe 4** (é infraestrutura consolidada, mesmo sem pavimento formal).
- Se o "estacionamento" é só um pátio de terra batida **dentro de um canteiro de obra ativo**,
  sem marcação nem veículos regulares, que muda de forma ano a ano → **classe 3**.
- Na dúvida: marque `confianca: baixa` e registre em `observacao` o que você viu. Não é permitido
  deixar o campo em branco só porque é difícil — decida e documente.

### 3.3 Campo de futebol seco → **é classe 2** (`vegetacao_rala`), nunca 3

Grama seca/amarelada na estação seca (jun-set, mesma janela de composição do projeto) pode parecer
solo exposto no RGB. Sinais de que é campo, não obra:

- **Forma retangular muito regular**, geralmente com marcações (linhas, área de gol visível em
  alta resolução) ou contexto de bairro residencial/escola.
- **NDVI baixo mas não nulo** — grama seca ainda tem alguma resposta de vegetação, diferente do
  solo mineral. Se tiver acesso ao valor de NDVI do candidato (`ndvi_medio` no GeoJSON), campo seco
  costuma ficar na faixa intermediária, não no extremo baixo.
- Continua sendo **vegetação rala** mesmo sem estar verde — "seco" não é sinônimo de "solo exposto".

### 3.4 Lavoura recém-colhida → **é classe 2**, nunca 3 — **erro mais comum da região**

Depois da colheita, um talhão agrícola fica com solo à mostra por semanas/meses e é visualmente
muito parecido com terraplenagem. Diferencie por:

- **Padrão de sulcos/linhas de plantio regulares e paralelos**, visíveis mesmo sem vegetação —
  obra não tem esse padrão geométrico repetitivo.
- **Geometria do talhão**: bordas retas alinhadas a estradas rurais ou a outros talhões vizinhos,
  formando um mosaico regular. Canteiro de obra tem geometria ditada pelo projeto de construção,
  não pelo parcelamento agrícola.
- **Localização**: se o polígono está longe do perímetro construído/em expansão do data center e
  cercado de outros talhões agrícolas (alguns ainda verdes, outros colhidos), é lavoura.
- Se restar dúvida real depois desses três pontos, prefira classe 2 com `confianca: baixa` — é o
  erro mais comum, então o viés default deve ser "provavelmente lavoura", não "provavelmente obra".

### 3.5 Estrada de terra dentro do canteiro vs. via pública não pavimentada → **depende do uso**

CLAUDE.md decide que infraestrutura viária em geral entra em classe 4 (construída), não é classe
separada. Mas uma via de acesso **temporária**, aberta só para a obra, é parte do canteiro:

- **Via de acesso temporária de canteiro** (largura irregular, sem ligação com a malha viária
  formal do entorno, muda de traçado entre anos, termina dentro da área de obra) → **classe 3**.
- **Via pública/rural não pavimentada** (conecta bairros/propriedades, aparece com o mesmo traçado
  em vários anos seguidos, mesmo sem pavimentação) → **classe 4**.
- Teste rápido: compare o mesmo local em 2 ou 3 anos diferentes (os PNGs facilitam isso, mesma
  extensão em todos os anos). Se a "estrada" muda de forma/desaparece, é canteiro. Se é estável
  ano após ano, é via.

## 4. Como usar a falsa-cor SWIR para desempatar

Os PNGs `{ano}_falsacor.png` usam **SWIR1 no canal vermelho, NIR no canal verde, Red no canal
azul** (não é o RGB natural — é uma composição feita para realçar solo/vegetação):

- **Vegetação** (qualquer densidade) → **verde vivo** (NIR alto domina o canal verde).
- **Solo mineral exposto / obra** → **magenta / rosa / terracota** (SWIR1 e Red altos, NIR baixo
  em relação aos outros dois).
- **Água** → **azul escuro / quase preto** (todas as bandas baixas).
- **Telhado/laje/pavimento muito claro** → tende a **branco estourado**, sem dominância de cor
  (as três bandas saturam juntas), diferente do magenta saturado do solo.

Regra de bolso: **se está magenta/rosa e tem contorno irregular, é forte candidato a classe 3.
Se está branco estourado e tem contorno reto, é classe 4.**

## 5. Quantas amostras rotular e de quê

Resumo das metas de SV-10 (ver `docs/tarefas/SV-10-rotulagem-manual-execucao.md` para o texto
completo e os critérios de aceite):

- **≥ 40 polígonos de classe 3**, cobrindo **≥ 4 anos diferentes** e **≥ 2 sites**, com **≥ 12 na
  era Landsat (2013-2018)** — não concentre tudo na era moderna, metade da série é Landsat.
- **≥ 60 negativos difíceis**: polígonos de classe 2 ou 4 que a heurística marcou como candidato
  mas que, olhando com calma, **não são obra** (ver seção 6). Valem tanto quanto os positivos.
- **≥ 20 polígonos** das classes 1 (vegetação densa) e 5 (água) como âncora.
- **≥ 120 polígonos no total.**
- Tamanho de polígono: **0.5 a 20 ha**. Muito grande mistura classes dentro do mesmo polígono;
  muito pequeno não sobrevive à amostragem de 10 m (e nem a 30 m, na era Landsat).
- Todos os campos do template preenchidos, `confianca` honesta (marque `baixa` sem
  constrangimento), `data_rotulagem` e `autor` sempre preenchidos.

## 6. Negativos difíceis — por que são obrigatórios

O `candidatos_{site_id}.geojson` inclui o campo `classe_worldcover`: o que o label fraco (MapBiomas
remapeado, ver `docs/decisoes/ADR-004-fonte-de-labels.md`) já dizia ali. Se um candidato tem
`classe_worldcover: "vegetacao_rala"` ou `"construida_urbana"` e, olhando a imagem, você concorda
que **não é obra** — isso é exatamente um negativo difícil, e precisa ser rotulado com a classe
correta (2 ou 4), **não descartado**.

Por quê: a heurística que gerou os candidatos usa BSI/NDVI. Se todo polígono rotulado vier de um
candidato que "deu certo" (realmente é obra), o modelo aprende a decorar o comportamento de
BSI/NDVI, não a reconhecer obra de verdade — e a avaliação fica circular (a classe 3 já é definida
em cima desses mesmos índices). Os negativos difíceis são o que ensina o modelo a diferença.

Se, rotulando os candidatos, você perceber que sobraram poucos negativos difíceis (ex.: a
heurística acertou quase tudo), **desenhe manualmente** mais alguns em cima de lavoura colhida,
campo seco ou telhado claro que você identificar nas imagens — marque `origem: manual` nesses.

## 7. Ferramenta sugerida: QGIS

Passo a passo curto (assume QGIS já instalado; qualquer versão 3.x recente serve):

1. **Abra o raster de imagem**: `Camada → Adicionar Camada → Adicionar Camada Raster`, selecione
   `data/raw/s2/{site_id}/{ano}.tif` (era moderna) ou `data/raw/landsat/{site_id}/{ano}.tif` (era
   Landsat, anos ≤ 2018 ou 2019-2021). O arquivo tem 6 bandas na ordem
   `blue, green, red, nir, swir1, swir2` (bandas 1 a 6, 1-indexado) — os valores são reflectância
   escalada por 10000 (inteiro), não 0-255, então a imagem aparece escura até você ajustar o
   contraste.
2. **Configure RGB natural**: `Propriedades da camada → Simbologia → Renderizador multibanda
   colorido`: Vermelho = banda 3, Verde = banda 2, Azul = banda 1. Em "Configurações de contraste",
   use "Realce cumulativo de contagem de corte" com 2%–98% para a imagem ficar legível.
3. **Configure falsa-cor SWIR** (duplique a camada ou troque a simbologia): Vermelho = banda 5
   (swir1), Verde = banda 4 (nir), Azul = banda 3 (red). Mesmo ajuste de contraste.
4. Ou, mais rápido: **abra direto os PNGs já prontos** em `reports/figures/rotulagem/{site_id}/`
   como camada raster — já vêm com o contraste ajustado e os candidatos numerados, bons para
   escolher visualmente por onde começar antes de ir para o `.tif` de verdade desenhar o polígono
   com precisão.
5. **Abra os candidatos como referência**: `Adicionar Camada Vetorial` em
   `data/interim/candidatos_{site_id}.geojson` — não edite este arquivo, é só referência/guia de
   onde olhar.
6. **Prepare seu arquivo de trabalho**: copie `data/labels_manual/_template.geojson` para
   `data/labels_manual/{site_id}.geojson` (ou `{site_id}_{autor}.geojson` se houver mais de um
   rotulador) e adicione essa cópia como camada vetorial editável.
   - **O template vem com zero feições de propósito** (não é um label pronto disfarçado — ver
     seção "verificação de honestidade" da tarefa). Se o QGIS abrir a camada sem nenhum campo
     disponível para preencher (acontece com GeoJSON vazio, é uma limitação do formato, não bug),
     adicione os 9 campos manualmente uma vez, na aba **Editar → Alternar edição → botão "Nova
     coluna"** da tabela de atributos, com estes nomes e tipos (documentados também dentro do
     próprio `_template.geojson`, chave `"schema_campos"`):
     `site_id` (texto), `ano` (inteiro), `classe_id` (inteiro), `classe_slug` (texto), `confianca`
     (texto), `autor` (texto), `data_rotulagem` (texto), `observacao` (texto), `origem` (texto).
7. **Desenhe**: alterne para modo de edição, use a ferramenta de polígono, desenhe em cima da
   área que você decidiu ser uma classe (candidato ou negativo difícil), preencha os 9 campos na
   janela que abre ao terminar o desenho, salve a edição.
8. Repita até bater as metas da seção 5, salve o arquivo (`Camada → Salvar como`, mantenha GeoJSON,
   confirme CRS EPSG:4326).

## 8. Controle de consistência (ver SV-10, item 6 do escopo)

Depois de rotular os primeiros 10 polígonos, **volte e rotule os mesmos 10 de novo sem olhar a
resposta anterior**, ao final da sessão. Se você discordar de si mesmo em mais de 2 de 10, o
critério deste guia está ambíguo — pare, anote onde travou, e trate como um achado a corrigir
aqui, não como um erro seu.

## 9. Como a classe 3 muda de bioma para bioma (SV-09b)

**Acrescentado em SV-09b.** SV-09 (seções 1-8 acima) foi escrito rotulando só Mata Atlântica/Sudeste
(`ascenty-vinhedo`, `odata-hortolandia`, `scala-tambore`). A expansão para 13 AOIs de tier 1 (SV-24/
SV-25) trouxe Caatinga, Cerrado e Amazônia — biomas onde a classe 3 (`solo_exposto_obras`) tem
**confusores diferentes** dos 5 casos da seção 3, porque o clima e a vegetação de fundo são outros.
Os candidatos agora vêm por **estrato** (bioma x era de sensor, ver
`docs/tarefas/SV-09b-kit-rotulagem-estratificado.md`):
`data/interim/candidatos_estrato_{estrato}.geojson` +
`reports/figures/rotulagem/{estrato}/` (inclui `prancha_contexto.png`, um painel lado a lado com o
candidato mais "classe 3 provável" daquele estrato ao lado do confusor mais provável — abra essa
imagem primeiro ao trocar de bioma no meio de uma sessão, é o que evita o erro de calibração de
"acabei de ver 30 polígonos de SP e agora estou vendo os do Ceará com o mesmo olho").

Leia esta seção inteira **antes de rotular o primeiro polígono de um estrato fora de Mata
Atlântica** — é rápido e evita ter que refazer.

### 9.1 Caatinga — ERRO MAIS PROVÁVEL DO CONJUNTO TODO

**Vegetação decídua sem folha no período seco (jun-set, mesma janela de composição do projeto) é
classe 2 (`vegetacao_rala`), nunca classe 3.** Isto é o oposto do que a primeira impressão sugere:
caatinga sem folha, no RGB, aparece cinza-acastanhada, sem verde, muito parecida com solo exposto —
mas é **vegetação lenhosa viva, só sem folhas**, não solo raspado nem canteiro.

Como diferenciar (nesta ordem):

- **Textura na falsa-cor SWIR**: solo mineral exposto de verdade fica **magenta/rosa uniforme**
  (seção 4). Caatinga decídua, mesmo sem folha, mantém uma textura **heterogênea, pontilhada** —
  copas e galhos ainda respondem de forma diferente do solo nu entre eles. Se a falsa-cor mostra
  "salpicado" em vez de um bloco uniforme de cor, é vegetação, não solo.
- **NDVI não é zero**: mesmo decídua, a caatinga seca tem NDVI baixo mas **positivo e não-extremo**
  (`ndvi_medio` no candidato). Solo mineral puro (canteiro real) tende ao extremo mais baixo da
  distribuição do estrato — é por isso que os candidatos deste estrato ordenam por menor NDVI, mas
  "mais baixo relativo" não é o mesmo que "solo nu": compare com a prancha de contexto do estrato
  antes de decidir.
- **Contexto**: canteiro de obra real tem contorno ditado pelo projeto de construção (bordas retas
  ou curvas de raio de máquina, ligado a estrutura construída/via de acesso). Caatinga decídua segue
  o relevo natural, sem geometria de projeto.
- **Teste temporal**: se você tiver o mesmo local em outro ano com chuva (folhas), compare —
  vegetação decídua **fica verde de novo**; solo raspado de canteiro real não.

Por que isto importa mais aqui do que em qualquer outro bioma: a Caatinga tem a maior proporção de
solo mineral naturalmente exposto (mesmo sem nenhuma obra) de todos os biomas do projeto — a
heurística de BSI/NDVI (que não conhece bioma) confunde os dois com mais frequência aqui do que em
qualquer outro lugar. Ver seção "Conferência dos candidatos" da tarefa SV-09b: a taxa de acerto
visual dos candidatos caiu especificamente na Caatinga nesta rodada — trate cada candidato deste
estrato com mais ceticismo do que os de Mata Atlântica, não menos.

### 9.2 Cerrado

Confusor principal: **solo exposto natural em pastagem degradada** (curral/pasto sobrepastejado,
processo erosivo natural, "voçoroca") **vs. terraplenagem real de canteiro de obra**.

- **Terraplenagem/canteiro** → contorno **geométrico, ditado pelo projeto** (retângulos, curvas de
  raio de máquina), muitas vezes com maquinário, pilha de material ou contêiner visível na imagem de
  maior resolução, e **muda de forma de um ano para o outro** conforme a obra avança.
- **Solo exposto natural / pastagem degradada** → contorno **irregular, ditado pelo relevo e pelo
  manejo do gado** (trilhas de gado convergindo para bebedouro/cocho são um sinal característico),
  estável ou piorando gradualmente ano a ano (erosão), não aparecendo repentinamente como um
  polígono novo e bem definido.
- Cerrado tem estação seca marcada (mesma janela jun-set do projeto): pasto e vegetação rala ficam
  amarelados/secos, não confundir com solo exposto — mesma lógica da seção 3.3 (campo de futebol
  seco), aplicada a pastagem em vez de campo urbano.

### 9.3 Amazônia (se houver candidato do estrato `amazonia`)

Confusor principal: **estrada de terra e pátio de madeira/serraria** (uso consolidado de extração
madeireira ou acesso rural) **vs. canteiro de obra do data center**.

- **Canteiro de obra** → ligado à estrutura construída do site (ver ponto do site em
  `config/sites.geojson`), contorno muda de forma entre anos consecutivos, aparece e evolui na
  janela de `periodo_durante` daquela AOI.
- **Estrada/pátio de extração madeireira** → traçado **linear e estável ano após ano** (mesma lógica
  de teste temporal da seção 3.5: se o "clareira"/pátio não muda de forma entre anos, não é canteiro
  ativo), frequentemente **desconectado** do perímetro do site (não converge para o ponto do data
  center).
- Atenção redobrada à escala: a AOI de Amazônia deste projeto (`clickip-manaus`) tem pegada pequena
  (~0.12 ha, já documentado em SV-24) — um polígono grande demais em relação ao tamanho conhecido do
  site é mais provavelmente clareira/desmatamento de fundo do que canteiro do próprio
  empreendimento.

### 9.4 Pampa

**Nenhum candidato deste estrato existe nesta rodada de SV-09b** — nenhuma AOI de tier 1 em
`config/sites.geojson` tem `bioma == "Pampa"` (a única AOI do Sul, `scala-spoapa01` em Porto Alegre,
está no domínio de Mata Atlântica, que é o bioma oficial IBGE ali). Documentado aqui mesmo assim
porque a tabela de SV-09b previa este estrato e uma AOI de Pampa pode entrar em rodadas futuras:

- Confusor principal: **campo nativo seco** (textura de gramínea baixa, comum em toda a metade sul
  do estado) **vs. solo raspado de verdade**. Campo nativo seco tem NDVI baixo mas positivo (mesma
  lógica da caatinga decídua, seção 9.1) e textura de grama, visível em alta resolução como um
  padrão fino e uniforme, não "cru"; solo mineral exposto é liso/sem textura na escala do pixel.
  Não existe atualmente sinal espectral fácil de separar os dois de forma automática — se este
  estrato for criado no futuro, trate como regra de borda (mesmo padrão da seção 3.2) até haver
  material visual de referência.

### 9.5 Regra de desempate — vale para qualquer bioma, não só os novos

**Na dúvida, `confianca: baixa` e siga.** Um polígono honesto de baixa confiança vale mais para o
dataset do que um polígono confiante e errado: SV-16 pode filtrar por confiança na hora de montar o
dataset de treino, mas só se o campo for preenchido com honestidade. Não é permitido pular um
polígono difícil sem rotular — decida com a informação que você tem (falsa-cor, prancha de
contexto, comparação entre anos), registre o raciocínio em `observacao`, e marque `baixa` sem
constrangimento. Isso vale em dobro fora de Mata Atlântica: você tem menos anos de experiência
visual acumulada nesses biomas dentro desta sessão do que tinha em SP depois de 100 polígonos — é
esperado errar mais no começo, o campo `confianca` existe exatamente para isso ficar registrado em
vez de escondido.

---

## Pendente de confirmação

**Este guia ainda não foi testado com uma pessoa do time que não participou da construção do
projeto**, rotulando 5 polígonos de forma independente — esse teste é um critério de aceite
explícito de SV-09 e não pode ser feito pelo agente que escreveu o guia (falta de acesso a uma
pessoa real, e o próprio viés de quem escreveu não serve como teste de clareza).

O que foi feito no lugar: revisão crítica do próprio guia, como se fosse a primeira leitura,
conferindo que os 5 casos de confusão da seção 3 têm resposta fechada e acionável (não
"depende", exceto onde a própria tarefa pede uma regra de borda documentada — caso 3.2).

**Antes de SV-10 começar de verdade**: peça para alguém do time (idealmente que não trabalhou
nesta tarefa) ler só este arquivo e rotular 5 polígonos do `candidatos_*.geojson` de qualquer
site, sem ajuda. Se a pessoa travar em algum ponto ou perguntar "isso é 2 ou é 3?" para um caso
não coberto aqui, é sinal de gap no guia — corrija esta seção antes de liberar a rotulagem em
escala. Mesmo padrão de pendência formal usado em
`docs/decisoes/ADR-002-contrato-indicadores.md`.
