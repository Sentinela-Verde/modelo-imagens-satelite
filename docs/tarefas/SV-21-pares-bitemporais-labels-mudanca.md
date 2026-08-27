# SV-21 — Dataset de pares bitemporais + labels de mudança

- **Fase:** 3 — Baseline · **Data-alvo:** 07/09 · **Tamanho:** M (~4h)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-07 (labels alinhados), SV-08 (features), SV-11 (chaves de split)
- **Desbloqueia:** SV-22
- **Tem seção de risco:** não
- **Escopo:** **Plus (Deep Learning)** — parte da meta de entrega, não item opcional

## Contexto

O Plus do projeto é **change detection bitemporal com rede siamesa**: em vez de classificar cada ano
de forma independente e comparar depois, um modelo recebe **duas datas do mesmo lugar** e aprende
diretamente onde houve mudança. É o que a literatura de sensoriamento remoto faz para detectar
construção, desmatamento e expansão urbana, e é a pergunta científica mais interessante que este
projeto pode fazer: *um modelo bitemporal ganha da simples diferença entre duas classificações?*

Esta tarefa constrói o insumo. Ela não treina nada.

> ## Pré-condição bloqueante: de onde vêm os labels de mudança
> Um modelo de change detection precisa saber **onde houve mudança**. Só existem três fontes:
> - **(A) Fonte de label anual** (MapBiomas, se adotado em SV-05b): mudança = a classe do pixel mudou
>   entre o ano A e o ano B. **É a única fonte viável no prazo, e é legítima.**
> - **(B) Diferença das classificações do nosso próprio RF.** **Proibido como fonte única** — o
>   Siamese aprenderia a imitar o RF, e a comparação de SV-23 viraria circular e sem valor.
> - **(C) Anotação manual de polígonos de mudança.** Correta, mas cara demais para 18 dias.
>
> **Se SV-05b tiver mantido o WorldCover (safra fixa), não existe (A)** — e então o Plus precisa ser
> replanejado antes de começar: ou se anota manualmente um conjunto pequeno de validação (C) e o
> treino usa (B) **declarando a circularidade**, ou o Plus vira uma comparação sem modelo treinado.
> **Leia `docs/decisoes/ADR-004-fonte-de-labels.md` antes da primeira linha de código.** Se a fonte
> não for anual, pare e escale — não improvise.

## Objetivo

Um conjunto de pares de recortes (chips) bitemporais com máscara de mudança, respeitando exatamente
o mesmo split de SV-11, pronto para treino.

## Escopo — o que fazer

1. **`src/sentinela/plus/pares.py`**, CLI:
   `python -m sentinela.plus.pares --sensor sentinel2 --tamanho-chip 128`

2. **Restrição de era (decisão de escopo, não a mude sem registrar):** gerar pares **dentro da mesma
   era de sensor**, não atravessando 2018→2019. Um par Landsat↔Sentinel-2 confunde mudança real com
   diferença de instrumento, que é exatamente o que SV-20 mostrou existir.
   - **Principal:** pares da era Sentinel-2 (2019–2025), 10 m.
   - **Opcional, se sobrar tempo:** pares da era Landsat (2013–2018) como conjunto separado. A 30 m,
     um chip de 128 px cobre 3,8 km e a mudança fica pequena demais — por isso é secundário.

3. **Pares a gerar,** por site:
   - **Consecutivos** (2019-2020, 2020-2021, …): mudança pequena, muitos exemplos negativos.
   - **De salto** (2019-2022, 2019-2025, 2021-2025): mudança grande e óbvia — são os exemplos que
     ensinam o modelo a reconhecer a transição completa vegetação → obra → construído.
   Gere os dois tipos e marque cada par com `delta_anos`.

4. **Chips:** 128 × 128 px, com sobreposição de 50% entre chips vizinhos para aumentar o número de
   amostras. Entrada por data: as **13 features** de SV-08 (ou um subconjunto — registre qual).

5. **Máscara de mudança** (a saída que o modelo prediz), por par:
   - **Binária** `mudou` (0/1): a classe do pixel difere entre A e B, segundo a fonte de label anual.
   - **Adicional, `tipo_mudanca`:** o par ordenado `(classe_A, classe_B)`, guardado como metadado.
     **A mudança que interessa ao projeto é `→ 3` (virou solo exposto/obras) e `→ 4` (virou
     construído).** Marcar cada chip com quantos pixels de cada tipo ele tem permite, em SV-22,
     ponderar ou filtrar o treino para a transição que importa, em vez de tratar toda mudança igual.

6. **Desbalanceamento — trate aqui, não no treino:** pixels de mudança são tipicamente menos de 5%.
   Chips inteiramente sem mudança dominariam o dataset e o modelo aprenderia a prever "nada mudou"
   com 97% de acurácia. Regra: **manter todos os chips com ≥ 1% de pixels de mudança, e amostrar os
   demais até no máximo 3× essa quantidade.** Registre as contagens antes e depois.

7. **Split — reuse, não recrie:**
   - Cada chip herda o `bloco_id` do **seu centro**, calculado com a mesma regra de SV-11
     (coordenada projetada, grade de 1 km).
   - **Chips que cruzam a fronteira entre um bloco de treino e um de teste são descartados.**
     Aceitar contaminação de borda aqui desfaria todo o cuidado antivazamento de SV-11 — e um chip
     de 1,28 km sobre blocos de 1 km cruza fronteira com frequência, então **espere descartar uma
     fração relevante e reporte quanto**.
   - Nenhum split novo é criado nesta tarefa. Se você se pegar chamando `train_test_split`, parou de
     seguir a tarefa.

8. **Saída:** `data/processed/plus/pares_{sensor}.npz` (ou `.zarr`, se ficar grande demais), com
   `X_a`, `X_b` (float32), `y` (uint8), e um índice em parquet com `site_id`, `ano_a`, `ano_b`,
   `delta_anos`, `bloco_id`, `split`, `pct_mudanca`, `tipo_mudanca_contagem`, `linha`, `coluna`.

9. **Manifest** `data/manifests/pares_{sensor}.json` (commitado): n de pares, n de chips por split,
   distribuição de `pct_mudanca`, chips descartados por cruzar fronteira, features usadas, fonte do
   label de mudança (com o ADR-004 citado), seed, sha256, git_sha.

10. **Figura de sanidade:** `reports/figures/plus/exemplos_pares.png` — 6 pares lado a lado
    (RGB de A, RGB de B, máscara de mudança). **Se a máscara não coincidir visualmente com o que
    mudou na imagem, o dataset está errado e o treino seria desperdício de tempo.**

## Fora de escopo

- Treinar (SV-22).
- Avaliar (SV-23).
- Criar novo split (use o de SV-11).
- Usar a saída do RF como label de treino (ver pré-condição).

## Critérios de aceite

- [ ] A fonte do label de mudança está registrada e **não é** a saída do nosso RF.
- [ ] `data/processed/plus/pares_sentinel2.npz` existe, com pares consecutivos e de salto.
- [ ] Todo chip tem `bloco_id` e `split` herdados de SV-11; **nenhum chip cruza blocos de splits diferentes**.
- [ ] `set(blocos_treino) & set(blocos_teste) == set()` também no nível de chip (teste automatizado).
- [ ] Pelo menos 30% dos chips têm `pct_mudanca ≥ 1%` após a regra de balanceamento.
- [ ] A figura de 6 exemplos existe e a máscara **bate visualmente** com a mudança na imagem.
- [ ] Manifest commitado, com a contagem de chips descartados por cruzarem fronteira.
- [ ] Rodar duas vezes com a mesma seed → mesmo sha256.
- [ ] Nenhum `.npz` entrou no git.

## Cenários de teste

1. **Antivazamento:** nenhum `bloco_id` aparece em treino e teste.
2. **Simetria:** para um par (A, B), inverter para (B, A) produz a mesma máscara binária de mudança
   (a mudança é simétrica; o *tipo* não é).
3. **Par idêntico:** montar um par artificial com A = B → máscara de mudança toda zero. Se não for
   zero, há bug de alinhamento entre as duas datas.
4. **Alinhamento:** `X_a` e `X_b` do mesmo chip cobrem exatamente as mesmas coordenadas.
5. **Balanceamento:** a distribuição de `pct_mudanca` após a regra bate com o manifest.
6. **Sanidade de domínio:** o chip com maior `pct_mudanca` em Vinhedo deve cair sobre a área do data
   center, não sobre uma mancha aleatória de mata.

## Como reportar

Informe: qual fonte de label de mudança foi usada (e o que o ADR-004 decidiu), n de chips por split,
distribuição de `pct_mudanca`, quantos chips foram descartados por cruzarem fronteira de bloco, e o
resultado da conferência visual dos 6 exemplos.
