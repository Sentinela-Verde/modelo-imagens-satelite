# SV-23 — Avaliação do Plus vs. baseline pós-classificação

- **Fase:** 4 — Output e Plus · **Data-alvo:** 10/09 · **Tamanho:** M (~3h)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-14 (classificações do RF), SV-22 (modelo siamês)
- **Desbloqueia:** SV-17
- **Tem seção de risco:** não
- **Escopo:** ❌ **CANCELADA em 2026-08-31** — usuário confirmou cortar o Plus pra caber a expansão de sites (era: Plus, contribuição)

> **Suspensa em 2026-08-31**, junto com SV-21 e SV-22. Ver a justificativa no topo de `SV-21`.
>
> **O que se perde é menos do que parece.** A comparação pós-classificação que esta tarefa faria —
> diferença entre classificações do RF em dois anos — **continua sendo entregue**, agora por SV-30,
> sobre ~25 AOIs em vez de 3 e com grupo de controle pareado. O que se perde é o braço "Siamese" da
> comparação, não a análise de mudança.

## Contexto

Treinar uma rede siamesa não é, por si só, uma contribuição — é um exercício. A contribuição é
**responder a uma pergunta**:

> Um modelo bitemporal treinado de ponta a ponta detecta mudança melhor do que simplesmente comparar
> duas classificações independentes do Random Forest?

Essa é a comparação que a banca vai achar interessante, e é a única forma de o Plus significar algo.
Sem ela, o Siamese é um apêndice.

**Declare o resultado possível antes de medir:** é perfeitamente plausível que o **RF pós-classificação
ganhe**. Ele é forte, foi treinado com muito mais pixels, e a rede siamesa tem labels de mudança
fracos e poucas amostras. **Se o RF ganhar, isso é um resultado válido e deve ser apresentado como
tal** — com a explicação de por quê. Resultado negativo bem medido é entrega; resultado maquiado é
problema. Escreva esta expectativa no relatório **antes** de rodar a avaliação, para não haver
tentação depois.

## Objetivo

Uma comparação justa, no mesmo conjunto de teste, entre as duas abordagens de change detection, com
veredito escrito.

## Escopo — o que fazer

1. **`src/sentinela/plus/avaliar.py`**, CLI:
   `python -m sentinela.plus.avaliar --siamese models/siamese_v0.1.pt --rf models/rf_v0.1.joblib`

2. **Construir o baseline a bater — comparação pós-classificação:**
   Para cada par (site, ano_A, ano_B) do conjunto de **teste** de SV-21:
   - `mudou = (classe_RF(A) != classe_RF(B))`, usando os rasters de SV-14.
   - **Duas variantes**, porque a ingênua é injustamente fraca: (i) diferença crua;
     (ii) diferença com filtro de área mínima (descartar manchas < 0.5 ha), que remove o ruído de
     pixel isolado. **Reporte as duas** — comparar o Siamese só contra a variante crua seria inflar
     artificialmente a vantagem dele.

3. **Avaliar as duas abordagens no mesmo conjunto de teste**, contra a máscara de mudança de SV-21:
   - Precision, recall, **F1 da classe "mudou"**, e **IoU** — a acurácia global é inútil aqui, porque
     prever "nada mudou" em tudo já dá 95%+. **Não reporte acurácia global sem o F1 ao lado.**
   - Quebrar por `delta_anos`: as duas abordagens se comportam igual em mudança de 1 ano e de 6 anos?
     A hipótese é que o pós-classificação vai bem em mudança grande e mal em mudança sutil.
   - Quebrar por **tipo de mudança**, com foco no que o projeto quer: transições `→ 3`
     (virou obra) e `→ 4` (virou construído). Um método pode ganhar no agregado e perder justamente
     na transição que interessa.

4. **Comparação visual (é o que vai para o slide):**
   `reports/figures/plus/comparacao_metodos.png` — para 4 pares do teste, cinco painéis lado a lado:
   RGB do ano A, RGB do ano B, máscara de referência, predição do RF pós-classificação, predição do
   Siamese. Escolha pares que incluam **pelo menos um acerto claro e um erro claro** de cada método —
   um painel só com acertos é propaganda, não avaliação.

5. **Análise honesta das limitações do próprio experimento**, obrigatória:
   - Os labels de mudança são **fracos** (derivados de uma fonte de label anual, não de anotação
     humana), então ambos os métodos estão sendo medidos contra uma referência imperfeita.
   - O Siamese viu poucas amostras em comparação com o RF.
   - A comparação é da era Sentinel-2 apenas.

6. **`reports/avaliacao_plus.md`** (commitado): a pergunta, a expectativa declarada antes de medir,
   as tabelas, as figuras, o veredito, e o que você faria com mais tempo.

7. **Decisão de apresentação:** o Plus **entra na apresentação de qualquer forma**, ganhando ou
   perdendo — como comparação metodológica. Registre em `reports/avaliacao_plus.md` a frase de uma
   linha que resume o achado, pronta para o slide.

## Fora de escopo

- Re-treinar o Siamese para melhorar o número (o congelamento de escopo é 10/09).
- Ajustar o RF.
- Change detection na era Landsat.

## Critérios de aceite

- [ ] As duas abordagens avaliadas **exatamente no mesmo conjunto de teste** de SV-21 (mesmos chips).
- [ ] Precision, recall, F1 e IoU da classe "mudou" reportados para: Siamese, RF-diff crua e
      RF-diff com filtro de área.
- [ ] Métricas quebradas por `delta_anos` e por tipo de mudança (`→3` e `→4`).
- [ ] A figura comparativa existe, com 4 pares incluindo acerto e erro de cada método.
- [ ] A expectativa está escrita **antes** das tabelas no relatório, e o veredito é coerente com os
      números — inclusive se o veredito for "o RF ganhou".
- [ ] Seção de limitações do experimento escrita, cobrindo os três pontos acima.
- [ ] Frase de uma linha para o slide, com número dentro.
- [ ] Rodar de novo produz os mesmos números.

## Cenários de teste

1. **Mesmo conjunto:** o número de chips avaliados é idêntico para os dois métodos.
2. **Sem contaminação:** nenhum chip de treino entrou na avaliação.
3. **Piso de referência:** avaliar também um preditor trivial "nada mudou" — o F1 dele deve ser ~0
   e a acurácia global dele deve ser alta. **Isso demonstra, na própria tabela, por que a acurácia
   global não serve aqui** e é um ótimo argumento para a banca.
4. **Coerência:** o IoU nunca é maior que o F1 da mesma classe.
5. **Sanidade de domínio:** ambos os métodos devem detectar a construção do data center no par
   2019–2025 de Vinhedo. Se nenhum detectar, o problema está na referência, não nos métodos.

## Como reportar

Informe: a tabela comparativa (Siamese × RF-diff crua × RF-diff filtrada), o veredito com o número,
o comportamento por `delta_anos` e nas transições `→3`/`→4`, a frase de uma linha para o slide, e sua
avaliação honesta sobre o que a comparação realmente demonstra e o que não demonstra.
