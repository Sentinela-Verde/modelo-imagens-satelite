# SV-09b — Kit de rotulagem estratificado (amostragem por estrato, não por site)

- **Fase:** 2 — Dataset · **Data-alvo:** 02/09 · **Tamanho:** M (~2h)
- **Responsável sugerido:** `data-engineer` · critérios revisados por `ml-engineer`
- **Bloqueado por:** SV-24 (tier 1 definido). Para os estratos novos, também SV-26.
- **Desbloqueia:** SV-10 (revisada)
- **Tem seção de risco:** não
- **Substitui:** a lógica de amostragem de SV-09 (que continua válida no resto: heurística de
  candidatos, recortes visuais, template, guia de critérios)

## Contexto — o problema que esta tarefa resolve

SV-09 gera candidatos **por site**, com teto de 60 por site. SV-10 mediu: **~180 polígonos em
~2h30–3h**, ou seja **~70 polígonos por hora** de trabalho humano real (desenhar, julgar, preencher
oito campos).

Escalando por site para 25 AOIs: 25 × 60 = **1.500 polígonos ≈ 21 horas de trabalho humano.**
O projeto tem **14 dias** e uma pessoa. 21 h de rotulagem não cabem, e — diferente de tudo o mais
neste repositório — **isso não escala com mais agentes nem com mais dinheiro.** É o gargalo #1 do
replanejamento.

**Mas a premissa "60 polígonos por site" está errada, e é aí que está a saída.** O classificador é
por pixel, sobre reflectância harmonizada e índices espectrais. Ele **não tem `site_id` como feature**
(e SV-27 proíbe explicitamente que tenha). Rotular a segunda AOI de Hortolândia não ensina nada que a
primeira não tenha ensinado: mesmo solo, mesmo bioma, mesma estação, mesmo sensor.

O que o modelo de fato ainda não viu, e que a expansão trouxe, é **outro tipo de solo**. Canteiro de
obra sobre latossolo vermelho de Vinhedo e canteiro sobre solo arenoso claro do Ceará têm assinaturas
espectrais diferentes de verdade — e é justamente aí que um modelo treinado só no interior de São
Paulo erra.

Portanto: **a unidade de amostragem correta é o estrato (bioma × era de sensor), não o site.**

| Regra de amostragem | Polígonos | Horas humanas |
|---|---|---|
| 60 por site × 25 AOIs (escala ingênua) | 1.500 | **~21 h** |
| **40 por estrato × ~6 estratos** | **~240** | **~3,5 h** |

A redução de 6× **não é um corte de qualidade** — é a correção de uma unidade de amostragem errada.
Um estrato é uma população espectral; um site não é.

## Objetivo

Candidatos, recortes visuais e cotas de rotulagem organizados **por estrato**, dimensionados para uma
sessão humana de **até 4 horas**, cobrindo a diversidade que a expansão trouxe em vez de repetir a
diversidade que já foi coberta.

## Escopo — o que fazer

1. **Definir os estratos** a partir de `config/sites.geojson` (`bioma` × era de sensor), listando as
   AOIs de tier 1 de cada um. Estratos esperados, a confirmar com o tier 1 real de SV-24:

   | Estrato | Bioma / região | Era | Por que existe |
   |---|---|---|---|
   | `mataatlantica_landsat` | Mata Atlântica / Sudeste | Landsat 2013–2018 | **Já parcialmente coberto** pelos 3 sites atuais — só completar a cota |
   | `mataatlantica_s2` | Mata Atlântica / Sudeste | S2 2019–2025 | idem |
   | `cerrado_s2` | Cerrado / Centro-Oeste, MG | S2 | Solo e vegetação sazonal diferentes do Sudeste úmido |
   | `caatinga_s2` | Caatinga / Nordeste | S2 | **O caso mais divergente**: solo claro, vegetação decídua. Onde um modelo só-Sudeste mais erra |
   | `pampa_s2` | Pampa / Sul | S2 | Campo nativo confunde com pasto e com solo |
   | `amazonia_s2` | Amazônia / Norte | S2 | Só se houver AOI de tier 1 no Norte |

   **Estrato sem AOI de tier 1 não é criado.** Um estrato vazio é uma cota que ninguém consegue
   cumprir e que faz SV-10 falhar no critério de aceite por um motivo que não é culpa de quem rotula.

2. **Cotas por estrato** (em vez do teto de 60 por site de SV-09), por estrato existente:
   - **≥ 15 polígonos de classe 3** (solo exposto / obras);
   - **≥ 20 negativos difíceis** (classes 2 e 4 que *parecem* obra naquele bioma — atenção: o
     confusor muda de bioma para bioma; lavoura colhida no Sudeste, campo nativo seco no Pampa,
     caatinga decídua no período seco no Nordeste, que é o confusor mais traiçoeiro do conjunto);
   - **≥ 5 âncoras** das classes 1 e 5.
   - **Total por estrato: ~40. Total geral: ~240.**

   **Aproveite o que já existe.** Os estratos de Mata Atlântica já foram cobertos pelo material de
   SV-09; se `data/labels_manual/` já tiver polígonos deles, **desconte da cota**. Não faça a pessoa
   rotular de novo o que ela já rotulou.

3. **Candidatos por estrato**, reusando a heurística de SV-09 sem alterá-la: teto de **até 25
   candidatos por estrato**, sorteados entre as AOIs de tier 1 daquele estrato, **priorizando anos na
   fase `durante`** (é onde o canteiro de obra de fato existe — a coluna `fase` vem de SV-27, ou é
   calculada dos períodos de `config/sites.geojson`). Saída:
   `data/interim/candidatos_estrato_{estrato}.geojson`.

   **Percentis por AOI, nunca globais.** Os limiares de BSI/NDVI de SV-09 são percentis do próprio
   site justamente porque os valores absolutos mudam com o solo. Aplicar um percentil global sobre 25
   AOIs faria a Caatinga inteira parecer canteiro de obra e o Sul inteiro parecer que nunca houve obra.

4. **Recortes visuais por estrato** em `reports/figures/rotulagem/{estrato}/`, no mesmo formato de
   SV-09 (RGB + falsa-cor SWIR B12/B8/B4, candidatos numerados). Acrescente uma **prancha de contexto
   por estrato**: um painel lado a lado mostrando como classe 3 e seus confusores se parecem **naquele
   bioma**. É o material que impede o erro de calibração de quem rotula ao pular do Sudeste para o
   Nordeste no meio da sessão.

5. **Atualizar `docs/guia-rotulagem.md`** com uma seção nova, **"Como a classe 3 muda de bioma para
   bioma"**, resolvendo explicitamente:
   - Caatinga no período seco: vegetação decídua sem folha **é classe 2**, não 3 — este é o erro mais
     provável do conjunto todo e vai contaminar dezenas de polígonos se não estiver escrito;
   - Pampa: campo nativo seco vs. solo raspado;
   - Cerrado: solo exposto natural em área de pastagem degradada vs. terraplenagem;
   - Amazônia (se houver): estrada de terra e pátio de madeira vs. canteiro.
   - E a regra de desempate: **na dúvida, `confianca: baixa` e siga.** Um polígono honesto de baixa
     confiança vale mais que um polígono confiante e errado — SV-16 pode filtrar por confiança,
     mas só se o campo for honesto.

6. **Planilha de cotas** `data/labels_manual/_cotas.csv` (**commitada**): `estrato`, `classe_id`,
   `cota`, `ja_rotulado`, `restante`. É o que faz quem rotula saber quando parar, em vez de rotular
   até cansar. Sem isso, a sessão termina com 90 polígonos de Vinhedo e zero do Nordeste.

## Fora de escopo

- Rotular (SV-10).
- Usar a heurística como label automático. **Continua proibido** — ela é localizador, não classificador.
  Se virar label, o modelo aprende BSI/NDVI e a avaliação vira circular.
- Rotular AOIs de tier 2. Elas são o conjunto de generalização; rotular nelas destruiria justamente
  o teste que elas existem para dar.
- Alterar as 5 classes ou o schema do template de SV-09.

## Critérios de aceite

- [ ] `data/interim/candidatos_estrato_{estrato}.geojson` existe para cada estrato com AOI de tier 1,
      com ≤ 25 features, todas ≥ 0,5 ha (≥ 1 ha nos estratos Landsat, como em SV-09).
- [ ] Cada estrato tem candidatos de **≥ 2 AOIs distintas** — senão o estrato virou um site com
      outro nome e a estratificação não fez nada.
- [ ] ≥ 60% dos candidatos de cada estrato caem em anos de fase `durante`.
- [ ] Recortes RGB + falsa-cor + prancha de contexto existem por estrato e são legíveis.
- [ ] `docs/guia-rotulagem.md` tem a seção por bioma e resolve, sem ambiguidade, o caso
      "caatinga decídua no seco é 2 ou 3?".
- [ ] `_cotas.csv` está commitado, com `ja_rotulado` preenchido a partir do que já existe em
      `data/labels_manual/`.
- [ ] **Soma das cotas ≤ 260 polígonos.** Acima disso, a sessão de SV-10 não cabe em 4 h e a tarefa
      falhou no seu propósito — reduza as cotas antes de entregar.
- [ ] Conferência dos candidatos: abrir 3 candidatos aleatórios **de estratos diferentes** em imagem
      de alta resolução; ≥ 2 são de fato área alterada. Se a taxa cair fora do Sudeste, **reporte** —
      isso significa que a heurística não transfere de bioma, o que é um achado real e afeta SV-30.

## Cenários de teste

1. Rodar para um estrato → GeoJSON + PNGs, contagem dentro do teto.
2. Rodar para um estrato de bioma novo → os limiares de percentil foram calculados por AOI, não
   globalmente (verificável no log dos limiares usados por AOI).
3. Abrir os candidatos da Caatinga sobre o composto RGB → os polígonos não são só vegetação decídua.
4. `_cotas.csv` somado bate com a soma das cotas do documento.
5. Verificação de honestidade (herdada de SV-09): `classe_id` dos candidatos vem **vazio**.

## Como reportar

Informe: os estratos criados e as AOIs de cada um, cotas por estrato, quantos polígonos já existiam e
foram descontados, os limiares de percentil por AOI, o resultado da conferência dos 3 candidatos, e a
**estimativa de horas de SV-10** com a cota final. Se a estimativa passar de 4 h, diga isso
explicitamente — é a informação mais importante do relatório.
