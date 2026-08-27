# SV-05b — Spike: fonte de labels anual (MapBiomas) para a série longa

- **Fase:** 1 — Dados · **Data-alvo:** 30/08 · **Tamanho:** M (~3h, **timeboxed**)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-04 (auth EE), SV-05 (taxonomia em código)
- **Desbloqueia:** SV-07
- **Tem seção de risco:** não
- **Tipo:** **SPIKE com decisão de time** — ver aviso abaixo

> ## Aviso: esta tarefa toca uma decisão fechada do time
> O `CLAUDE.md` registra **ESA WorldCover v200 + rotulagem manual** como fonte de labels, e diz que
> decisões do time não devem ser renegociadas sem alinhar. **Esta tarefa não decide nada sozinha.**
> Ela existe porque a premissa daquela decisão mudou: o WorldCover foi escolhido quando a janela era
> curta e próxima de 2021. Com a janela agora em 2013–2025 (SV-02), aplicar uma safra fixa de 2021 a
> 13 anos deixou de ser uma imprecisão aceitável e passou a ser o maior erro sistemático do projeto.
> A entrega desta tarefa é **evidência medida + recomendação** para o time decidir. Se a recomendação
> for trocar de fonte, isso **precisa ser levado ao time antes de implementar** — é exatamente o caso
> que a regra do `CLAUDE.md` cobre.

## Contexto

O problema concreto: um pixel que era pasto em 2013, virou canteiro em 2017 e é galpão desde 2019
recebe, hoje, **o mesmo label nos 13 anos** — o que o WorldCover viu em 2021. O modelo é então
treinado para chamar de "construído" uma imagem de pasto de 2013. Isso não é ruído: é erro
sistemático correlacionado exatamente com o fenômeno que o projeto quer detectar.

O **MapBiomas** (Coleção 9, `projects/mapbiomas-public/assets/brazil/lulc/collection9/...`) é uma
alternativa óbvia para o Brasil: **anual**, 30 m, cobrindo de 1985 até ~2023, com legenda detalhada e
metodologia publicada. Se funcionar, resolve o problema da defasagem de uma vez.

## Objetivo

Uma recomendação fundamentada em medição sobre qual fonte de label a V1 deve usar, com a resposta
pronta para a pergunta mais difícil que a banca vai fazer.

## A pergunta que você precisa responder antes de recomendar MapBiomas

**"Se o MapBiomas já classifica uso do solo no Brasil todo, anualmente, o que o modelo de vocês
acrescenta?"**

Se o time não souber responder isso, adotar MapBiomas como label **enfraquece** o projeto em vez de
fortalecê-lo. A resposta defensável precisa estar escrita no ADR desta tarefa. Argumentos a avaliar
(confirme cada um, não copie):
- **Resolução:** MapBiomas é 30 m; o Sentinel-2 dá 10 m. No entorno imediato de um data center,
  30 m borra o canteiro de obras. Verifique isso visualmente em um site.
- **Latência:** a coleção é publicada com defasagem de cerca de um ano. Um sistema de monitoramento
  precisa classificar a imagem do mês passado, não esperar a próxima coleção.
- **Granularidade da classe crítica:** verifique se a legenda do MapBiomas isola "canteiro de obras".
  A hipótese é que não isola (cai em classes genéricas de área não vegetada), e que é justamente por
  isso que a rotulagem manual de SV-09/SV-10 continua necessária **em qualquer cenário**.
- **Generalização:** o pipeline deste repo roda em qualquer site e qualquer data; o MapBiomas roda
  no Brasil, em safras anuais fechadas.

Se a conclusão honesta for "o MapBiomas é melhor que o que vamos produzir", a recomendação correta é
**usar MapBiomas como label e posicionar o projeto como destilação para 10 m e tempo real** — e isso
precisa estar explícito, não implícito.

## Escopo — o que fazer

1. **Verificar disponibilidade no Earth Engine:** o asset do MapBiomas está acessível? Qual a
   coleção mais recente e até que ano vai? Cobre os 3 sites? Registre versão e ano final exatos.
2. **Propor o remap MapBiomas → nossas 5 classes**, no mesmo formato da tabela de SV-05, cobrindo
   pelo menos: formação florestal / savânica / silvicultura → 1; campo, pastagem, agricultura,
   mosaico → 2; área não vegetada, mineração, afloramento → 3 ou 4 conforme análise; infraestrutura
   urbana → 4; rio/lago/oceano, aquicultura → 5. **Não trate esta lista como pronta** — abra a
   legenda oficial da coleção e confira código a código.
3. **Medir a concordância** entre WorldCover e MapBiomas, no ano em que ambos existem (2021),
   sobre os 3 sites, já remapeados para as 5 classes:
   - matriz de concordância entre as duas fontes, e concordância global (%);
   - concordância por classe, com atenção às classes 3 e 4.
   Onde discordam, amostre ~15 pixels e olhe a imagem: **qual das duas está certa?** Esta inspeção é
   o dado mais importante do spike.
4. **Medir o custo real da defasagem:** para um site, comparar o label MapBiomas de 2013 com o de
   2021 e reportar **quantos por cento dos pixels mudaram de classe**. Esse número é a magnitude do
   erro que o WorldCover introduziria na série longa — é o argumento quantitativo da recomendação.
5. **Registrar em `docs/decisoes/ADR-004-fonte-de-labels.md`:** disponibilidade, remap proposto,
   concordância medida, o percentual de mudança 2013→2021, a resposta à pergunta difícil acima, e a
   recomendação em uma das três formas:
   - **(a)** MapBiomas como label principal, WorldCover descartado;
   - **(b)** MapBiomas como principal e WorldCover como verificação cruzada (pixels onde as duas
     concordam entram com peso maior — costuma ser a opção mais robusta e é barata);
   - **(c)** manter WorldCover, com justificativa de por que a defasagem é tolerável.
   Em **qualquer** cenário, a rotulagem manual da classe 3 (SV-09/SV-10) permanece.
6. **Levar ao time.** A tarefa não fecha com o ADR escrito: fecha quando alguém do time confirmar a
   direção. Se o time não responder em 48h, escale para o usuário.

## Regra de parada (timebox)

São **3 horas**. Se o asset do MapBiomas não estiver acessível ou a legenda não fechar com as 5
classes nesse prazo, **pare e recomende a opção (c)** com a justificativa — e registre a adoção de
labels anuais como trabalho futuro. Não gaste a sprint tentando.

## Fora de escopo

- Implementar a geração dos labels (SV-07 faz isso, com a fonte que sair daqui).
- Rotulagem manual (SV-09/SV-10) — necessária em qualquer cenário.
- Alterar a taxonomia das 5 classes. Ela está fechada.

## Critérios de aceite

- [ ] Disponibilidade e versão exata da coleção MapBiomas verificadas no EE e registradas.
- [ ] Tabela de remap MapBiomas → 5 classes, conferida contra a legenda oficial, código a código.
- [ ] Concordância WorldCover × MapBiomas medida em 2021 nos 3 sites: global e por classe.
- [ ] Os ~15 pixels de discordância inspecionados visualmente, com veredito de qual fonte acertou.
- [ ] Percentual de pixels que mudam de classe entre 2013 e 2021 reportado por site.
- [ ] `ADR-004` com recomendação explícita (a, b ou c) e a resposta à pergunta
      "o que o nosso modelo acrescenta?" escrita em no máximo dois parágrafos.
- [ ] Confirmação do time registrada — ou o registro de que foi escalado ao usuário.

## Cenários de teste

1. O remap não deixa nenhum código da legenda oficial sem destino (nem que seja `0` nodata).
2. Os dois labels remapeados, no mesmo site e ano, estão na mesma grade e têm o mesmo shape antes de
   qualquer comparação — comparar grades desalinhadas produziria concordância falsa.
3. A concordância global fica em faixa plausível (60–90%). Acima de 98% sugere que você comparou uma
   fonte consigo mesma; abaixo de 40% sugere erro de remap.
4. O percentual de mudança 2013→2021 é maior nos sites com data center construído no período do que
   em uma área de controle de mata contínua na mesma região.

## Como reportar

Informe: recomendação (a/b/c) em uma linha, a concordância medida, o percentual de mudança
2013→2021, o veredito da inspeção visual, a resposta à pergunta difícil, e o que o time respondeu.
