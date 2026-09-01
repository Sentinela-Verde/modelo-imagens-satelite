# SV-27 — Dataset de modelagem v0.2 (conjunto expandido, teto de amostragem recalibrado)

- **Fase:** 1b — Expansão · **Data-alvo:** 03–04/09 · **Tamanho:** M (~3h)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-26
- **Desbloqueia:** SV-12 (re-treino), SV-30
- **Tem seção de risco:** não (mas herda o risco #1 do projeto: vazamento de dados)

## Contexto

SV-11 produziu `dataset_v0.1.parquet`: **1,31 M de linhas, 61 MB, 3 sites, 13 features, 363 blocos**,
com os dois testes de controle antivazamento medidos e documentados. Esta tarefa produz a **v0.2**:
mesma lógica, mesmo split, mesmos testes — sobre ~25 AOIs.

**A armadilha é aritmética.** O teto de amostragem de SV-11 é de **8.000 pixels por classe × site ×
ano × sensor**. Ele é linear no número de sites. Aplicado a 25 AOIs, projeta:

| | v0.1 (medido) | v0.2 com o teto de 8.000 (projetado) |
|---|---|---|
| Linhas | 1,31 M | **~11 M** |
| Parquet | 61 MB | ~510 MB |
| RAM em `pandas` (com `object` em `site_id`/`bloco_id`/`sensor`) | ~0,5 GB | **6–10 GB** |
| Um fit de Random Forest | minutos | **30–80 min** |
| `GroupKFold` de 5 folds em SV-12 | ~20 min | **3–7 h** |

Com 32 GB de RAM, o parquet carrega. **O treino é que não cabe no calendário**: SV-12 e SV-16 juntos
passariam de meio dia de relógio de parede cada, e o ciclo "treinou, olhou a métrica, ajustou" morre.

**Mais amostras do mesmo lugar não são mais informação.** Pixels vizinhos em imagem de satélite são
quase idênticos — é exatamente por isso que o split é por bloco. O que a expansão trouxe de valioso
não foi mais pixels; foi **mais diversidade de bioma, de solo e de contexto**. A resposta certa é
baixar o teto e deixar a diversidade entrar, não inflar a contagem.

## Objetivo

`data/processed/dataset_v0.2.parquet` cobrindo todas as AOIs ativas, entre **3 M e 4,5 M de linhas**,
com os três vetores de vazamento fechados como na v0.1 e com estratos regionais explícitos.

## Escopo — o que fazer

1. **Recalibrar o teto de amostragem.** Ponto de partida: **2.000 pixels por classe × AOI × ano ×
   sensor** (de 8.000). Rode, meça, e ajuste para cair na faixa de 3–4,5 M de linhas.
   **Registre no manifest o teto usado e o motivo da mudança** — a v0.1 e a v0.2 vão ser comparadas em
   SV-12 e a diferença de teto precisa estar explícita, senão a comparação vira armadilha.

2. **Colunas novas de estrato** (não são features do modelo; são chaves de análise e de estratificação):
   `regiao`, `bioma`, `uf`, `tier` (1|2), e as três colunas de fase do empreendimento
   `fase` (`pre`|`durante`|`pos`|`fora`), derivada de `ano` contra `periodo_pre/durante/pos` da AOI
   em `config/sites.geojson`. **`fase` é o que torna SV-30 possível** e custa quase nada agora.
   Deixe explícito no manifest: **`regiao`, `bioma`, `tier` e `fase` não entram como feature do
   Random Forest.** Bioma como feature faria o modelo aprender "no Nordeste é solo exposto" em vez de
   aprender a assinatura espectral do solo exposto, e o resultado desabaria em qualquer AOI nova.

3. **Split — a regra não muda, e é isso que importa.** Continua `bloco_id` de 1 km derivado de
   `x`/`y` projetados em EPSG:31983, blocos inteiros sorteados 70/30 com `random_state=42`.
   Duas mudanças de estratificação, ambas por causa da escala:
   - Estratificar o sorteio de blocos **por AOI e por região** (antes era só por site). Sem isso, com
     25 AOIs, é perfeitamente possível o sorteio jogar as duas únicas AOIs do Norte inteiras para
     treino e o teste ficar cego para aquele bioma.
   - **Verificar que cada bioma presente aparece em treino E em teste.** Se algum bioma tiver uma só
     AOI, ele não pode ser dividido sem quebrar a estratificação por AOI: registre a limitação e
     **não a esconda** — ela é a resposta honesta para "o modelo generaliza para o Norte?".

4. **Reserva de generalização fora-da-amostra (novo, e é o principal ganho científico da expansão).**
   Marque **`holdout_espacial: true`** em ~3 AOIs de tier 2 escolhidas para serem *inteiramente*
   ficadas fora do treino — não blocos delas, elas inteiras. É o teste que responde "o modelo funciona
   num data center que ele nunca viu, em outro bioma?", que é a pergunta que a banca vai fazer, e que
   o dataset de 3 sites simplesmente não conseguia responder.
   `holdout_espacial` é **ortogonal** a `split`: uma AOI reservada não tem linha em `treino`.

5. **Tipos de dado (o que evita os 10 GB de RAM):** `site_id`, `bloco_id`, `sensor`, `regiao`,
   `bioma`, `uf`, `fase` como **`category`**; features como `float32`; `ano`, `linha`, `coluna` como
   inteiros estreitos. Reporte o consumo de memória de `df.memory_usage(deep=True).sum()`.

6. **Manifest** `data/manifests/dataset_v0.2.json` (**commitado**), no mesmo formato da v0.1, mais:
   `teto_amostragem` e a justificativa da mudança, `aois` com tier e bioma, `distribuicao_classes`
   por região e por bioma além de por split e por sensor, `aois_holdout_espacial`, `memoria_mb`,
   e a lista de biomas que **não** puderam ser divididos entre treino e teste.

7. **Reexecutar os dois testes de controle de SV-11** — split aleatório por pixel vs. por bloco, e
   treino-em-Landsat/teste-em-S2 — **agora com 25 AOIs**. Os números da v0.1 já estão medidos e
   documentados; a comparação v0.1 → v0.2 é material direto de apresentação:
   *o vazamento aumenta ou diminui quando o estudo cobre 25 lugares em vez de 3?*

8. **`tests/test_dataset.py` estendido:** todos os testes antivazamento da v0.1 continuam
   bloqueantes, mais os novos de estratificação regional e de holdout espacial.

## Fora de escopo

- Treinar (SV-12).
- Labels manuais (entram em SV-16, sobre a v0.2).
- Reescrever a lógica de split. **Se você se pegar mudando a regra de `bloco_id`, pare** — ela é o
  ativo mais defensável do repositório e foi validada por teste de controle medido.
- Oversampling/SMOTE. Continua proibido, pelo mesmo motivo de SV-11.

## Critérios de aceite

- [ ] `data/processed/dataset_v0.2.parquet` existe, entre 3 M e 4,5 M de linhas.
- [ ] `df.memory_usage(deep=True).sum() < 2,5 GB` — reportado explicitamente.
- [ ] **Nenhum `bloco_id` em treino e teste ao mesmo tempo** (bloqueante).
- [ ] **Nenhum `bloco_id` com sensores diferentes em splits diferentes** (bloqueante).
- [ ] Um mesmo ponto (x, y) recebe o mesmo `bloco_id` nas duas resoluções (bloqueante).
- [ ] Nenhuma AOI marcada `holdout_espacial` tem linha com `split == 'treino'`.
- [ ] As 5 classes estão em treino e em teste. Classe 3 com < 5.000 amostras no teste é achado a reportar.
- [ ] Toda região presente aparece em treino e em teste, **ou** a exceção está listada no manifest.
- [ ] `regiao`, `bioma`, `tier` e `fase` **não** estão em `lista_features`.
- [ ] Duas execuções com a mesma seed → mesmo `sha256`.
- [ ] Os dois testes de controle rodaram e os números v0.1 vs. v0.2 estão na tabela.
- [ ] O parquet não entrou no git; o manifest entrou.

## Cenários de teste

1. Antivazamento espacial: `set(blocos_treino) & set(blocos_teste) == set()`.
2. Antivazamento entre sensores: `df.groupby('bloco_id')['split'].nunique().max() == 1`.
3. Coerência de bloco entre resoluções, como em SV-11 cenário 3.
4. Holdout espacial: `df[df.holdout_espacial].split.unique() == ['teste']`.
5. Estratificação: `df.groupby(['regiao','split']).size()` — nenhuma região com 0 em treino ou em teste,
   salvo as exceções declaradas.
6. Determinismo: duas execuções → mesmo hash.
7. Sanidade de teto: nenhuma combinação classe × AOI × ano × sensor acima do teto declarado.
8. **Teste de custo (faça este antes de entregar):** cronometre **um** fit de
   `RandomForestClassifier(n_estimators=100)` sobre o treino da v0.2. Se passar de **15 minutos**,
   o teto ainda está alto — baixe e regenere. SV-12 e SV-16 vão fazer isso muitas vezes, e um fit de
   40 minutos come um dia inteiro sem entregar nada.

## Como reportar

Informe: `n_linhas`, teto final e por que esse, memória, distribuição de classes por split / sensor /
região / bioma, nº de blocos, quais AOIs ficaram em holdout espacial e por quê, quais biomas não
puderam ser divididos, os dois testes de controle **lado a lado com os números da v0.1**, e o tempo
cronometrado de um fit.
