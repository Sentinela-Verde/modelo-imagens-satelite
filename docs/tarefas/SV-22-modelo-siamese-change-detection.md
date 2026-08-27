# SV-22 — Modelo Siamese de change detection (treino)

- **Fase:** 4 — Output e Plus · **Data-alvo:** 10/09 · **Tamanho:** G (~6h, o maior do plano)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-21
- **Desbloqueia:** SV-23
- **Tem seção de risco:** não
- **Escopo:** **Plus (Deep Learning)** — parte da meta de entrega

## Contexto

SV-21 entregou pares bitemporais com máscara de mudança. Esta tarefa treina a rede siamesa que
recebe as duas datas e prediz onde houve mudança.

**Contexto de prazo, e ele importa para as escolhas técnicas:** a apresentação é 14/09 e esta tarefa
tem data-alvo 10/09, no dia do congelamento de escopo. Portanto: **arquitetura pequena e conhecida,
não pesquisa.** O objetivo não é o estado da arte; é um modelo bitemporal treinado, honestamente
avaliado e comparável ao baseline. Um Siamese pequeno que converge vale infinitamente mais que um
transformer que não terminou de treinar.

## Objetivo

Um modelo siamês treinado, com experimento registrado e artefato versionado, pronto para a
comparação de SV-23.

## Escopo — o que fazer

1. **Ambiente isolado (faça isto primeiro):** `requirements-plus.txt` separado, com `torch`,
   `torchvision` e, se usado, `segmentation-models-pytorch` / `torchgeo`.
   **Não adicione PyTorch ao `requirements.txt` principal** — a V1 inteira roda sem Deep Learning
   (decisão D-01), e quebrar o ambiente do pipeline principal a 4 dias da entrega seria um
   autogol caro.

2. **Onde treinar — decidido, não é escolha sua (D-11): GPU no Google Colab.**
   O caminho de exportação dos chips de SV-21 para o Colab deve estar **montado e testado até o
   dia 14 (09/09)**, com um treino-fumaça de 2 épocas rodando de ponta a ponta. Montar esse caminho
   no dia 15, sob pressão, é o jeito mais fácil de perder a tarefa.

   **Por que não CPU:** cada época em CPU leva de 5 a 20 min sobre milhares de chips de 128×128×13;
   com 30–50 épocas e as 3–5 execuções que normalmente são necessárias até acertar, são **10–40 h de
   relógio de parede**. Isso é mais do que a Fase 4 inteira tem, e não encolhe com mais atenção nem
   com mais horas de trabalho — é tempo de máquina. Em GPU, cada execução cai para ~30 min.

   **Se a GPU não estiver disponível no dia 14**, não tente CPU: acione a alavanca de corte 3 do
   plano (Plus reduzido — entrega-se a comparação pós-classificação de SV-23 mais este protótipo
   documentado como trabalho em andamento). Essa decisão é do dia 14, não do dia 15.

3. **Arquitetura — comece pela recomendada:**
   - **FC-Siam-diff** (Daudt et al., 2018): encoder U-Net com **pesos compartilhados** entre os dois
     ramos, fusão por **diferença absoluta** das features em cada nível do skip connection, decoder
     que prediz a máscara de mudança. ~1,3 M de parâmetros: pequena, canônica, citável, e treina em
     CPU. **É a escolha certa para este prazo.**
   - Variante a testar se sobrar tempo: **FC-Siam-conc** (fusão por concatenação em vez de diferença).
   - Só se houver GPU e tempo: encoder ResNet-18 pré-treinado em Sentinel-2 (TorchGeo / SSL4EO-S12)
     como backbone compartilhado. Melhor resultado esperado, maior risco de consumir o prazo.
   - **Não** parta para transformers (BIT, ChangeFormer). Não cabe.

4. **Entrada:** as 13 features de SV-08 por data (não só RGB — descartar SWIR e os índices jogaria
   fora justamente o sinal de solo exposto). Normalização por banda com média/desvio calculados
   **apenas no conjunto de treino** — calcular no dataset inteiro é vazamento.

5. **Perda:** a mudança é rara, então `BCEWithLogitsLoss` puro converge para "nada mudou".
   Use **BCE ponderada pela frequência inversa + Dice**, e registre os pesos usados.

6. **Treino:**
   - Split: **exatamente o de SV-21**, que herda o de SV-11. Nenhum split novo.
   - `torch.manual_seed(42)`, `numpy.random.seed(42)`, e `torch.use_deterministic_algorithms(True)`
     quando possível — a regra de seed fixo do `CLAUDE.md` vale aqui igual.
   - Early stopping por F1 de mudança no conjunto de validação (um recorte do treino, **nunca** o teste).
   - Augmentação: flips e rotações de 90°, aplicados **identicamente** às duas datas e à máscara.
     Se A e B receberem augmentações diferentes, você destrói o alinhamento e o modelo não aprende nada.

7. **Artefatos:**
   - `models/siamese_v0.1.pt` (gitignored) — salvar `state_dict` **mais** a configuração:
     arquitetura, lista de features na ordem, estatísticas de normalização, seed, versão do dataset
     de pares, `git_sha`.
   - Curvas de treino/validação em `reports/figures/plus/curvas_treino.png`.
   - `reports/experiments/EXP-003-siamese.md` (commitado): arquitetura, hiperparâmetros, perda usada,
     nº de épocas, tempo de treino, hardware, F1 de mudança na validação por época, e uma frase sobre
     o que você esperava e o que aconteceu.

8. **Regra de parada (timebox real):** se ao fim de **6 horas** o modelo não estiver convergindo
   (F1 de mudança na validação ainda próximo de zero), **pare e entregue o que tem** com o diagnóstico
   escrito. Um Plus documentado como "treinado, não convergiu, hipóteses A/B/C" é entrega honesta e
   defensável. Um Plus que consome o dia 11 e 12 e come a documentação é falha de projeto — e a
   documentação é critério de nota explícito do professor.

## Fora de escopo

- Avaliar contra o baseline (SV-23).
- Ajustar a arquitetura para bater um número — sem tempo e sem propósito.
- Tocar em `requirements.txt` principal ou em qualquer código do pipeline da V1.

## Critérios de aceite

- [ ] `requirements-plus.txt` separado; o pipeline da V1 continua rodando sem PyTorch instalado
      (verifique de fato, em ambiente limpo).
- [ ] **Até o dia 14 (09/09):** caminho de exportação dos chips para o Colab montado e validado com
      um treino-fumaça de 2 épocas. Se não estiver de pé nessa data, acione a alavanca de corte 3.
- [ ] `models/siamese_v0.1.pt` existe e carrega, trazendo configuração e estatísticas de normalização.
- [ ] O treino usou apenas chips de `split == "treino"` (assertion no código, não confiança).
- [ ] Normalização calculada só no treino.
- [ ] Augmentação aplicada de forma idêntica a `X_a`, `X_b` e `y` (teste automatizado).
- [ ] Seed fixo; dois treinos produzem predições iguais (ou a não-determinismo residual está
      documentada, com a causa).
- [ ] `EXP-003` commitado, com curvas e tempo de treino.
- [ ] **F1 de mudança na validação substancialmente acima de zero.** Se não estiver, a tarefa entrega
      o diagnóstico — mas isso precisa estar explícito, não implícito num número ruim sem comentário.
- [ ] Nenhum `.pt` entrou no git.

## Cenários de teste

1. **Overfit proposital (faça este primeiro, antes do treino real):** treinar em **8 chips** por
   muitas épocas. O modelo **precisa** conseguir decorá-los (F1 perto de 1). Se não conseguir, há bug
   no modelo, na perda ou no carregamento — e é muito mais barato descobrir isso aqui do que depois
   de três horas de treino completo. **Este é o teste mais valioso da tarefa.**
2. **Isolamento:** nenhum chip de teste é lido durante o treino.
3. **Augmentação:** aplicar um flip e conferir que `X_a`, `X_b` e `y` viraram juntos.
4. **Simetria do par:** trocar A por B na entrada produz máscara de mudança praticamente igual.
5. **Determinismo:** dois treinos com a mesma seed → mesmas predições num lote fixo.
6. **Sanidade de forma:** entrada `(B, 13, 128, 128)` × 2 → saída `(B, 1, 128, 128)`.

## Como reportar

Informe: arquitetura escolhida e por quê, onde treinou (CPU/Colab) e quanto tempo levou, o resultado
do teste de overfit proposital, F1 de mudança na validação, e — se não convergiu — o diagnóstico com
as hipóteses. Diga explicitamente se a data-alvo de 10/09 foi respeitada.
