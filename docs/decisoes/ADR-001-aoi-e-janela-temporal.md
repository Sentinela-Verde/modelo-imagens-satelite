# ADR-001 — AOI (sites) e janela temporal multi-sensor

- **Status:** Aceito
- **Data:** 2026-08-27
- **Decisor:** usuário (owner da frente de Modelagem), com levantamento e proposta do `product-manager`

## Contexto

A tarefa SV-02 (`docs/tarefas/SV-02-definir-aoi-janela-temporal.md`) precisava fixar quais data
centers e quais anos entram na V1. A primeira proposta cortava a série em 2019 (Sentinel-2 puro,
por conveniência de sensor único). O usuário rejeitou esse corte explicitamente: *"se cobrir 2016
ou até anterior o projeto fica melhor? quero que seja o melhor, nem se precisarmos de outras
fontes"* — priorizar cobertura temporal defensável sobre simplicidade de engenharia.

## Levantamento de acervo

| Sensor | Cobertura | Resolução | Situação |
|---|---|---|---|
| Sentinel-2 L2A | 2017-03 →, densa a partir de 2019 | 10 m | Melhor qualidade, base da série moderna |
| Landsat 9 | 2021-10 → | 30 m | Complementa L8 |
| Landsat 8 | 2013-03 → | 30 m | Ponte sólida para 2013–2018, bem cross-calibrado com S2 |
| Landsat 7 | 1999 → 2022 | 30 m | SLC-off desde mai/2003 (~22% de faixas vazias por cena) |
| Landsat 5 | 1984 → nov/2011 | 30 m | Bom até 2011, radiometria TM exige segunda harmonização |

**O buraco de 2012 é real e sem solução completa:** Landsat 5 encerrou o imageamento em nov/2011;
Landsat 8 só entrou em operação em abr/2013. 2012 só tem Landsat 7 SLC-off disponível.

## Decisão

**Sites (3):** buffer de 5 km cada.
1. `ascenty-vinhedo` — Ascenty Vinhedo, Vinhedo/SP
2. `odata-hortolandia` — ODATA Data Center SP02, Hortolândia/SP
3. `scala-tambore` — Scala Data Centers (SGRUTB12), Barueri/SP

Coordenadas obtidas via Google Maps (busca pelo endereço/nome do estabelecimento, confirmação
visual de que o ponto cai sobre a instalação) — ver `fonte_coordenada` em cada feature de
`config/sites.geojson`. Coordenada da ODATA cross-validada contra fonte independente (dchub.cloud),
concordância até a 5ª casa decimal.

**Janela temporal — Faixa A (núcleo obrigatório da V1): 2013–2025, composto anual (jun–set).**
Landsat 8/9 para 2013–2018, Sentinel-2 para 2019–2025, com Landsat 8 *também* ingerido em
2019–2021 (faixa de sobreposição) para SV-20 medir o viés entre sensores.

**Faixa B (2000–2011, Landsat 5/7): NÃO entra na V1.** Fica como Plus de prioridade alta,
condicionada a (1) SV-02b validar que a harmonização TM→OLI fica dentro de tolerância aceitável, e
(2) SV-05b adotar uma fonte de label anual que cubra o período (WorldCover não cobre).

### Por que 2013 e não 2016

2016 não é um marco de sensor — cobrir 2016–2018 já exigiria Landsat 8 de qualquer forma (Sentinel-2
L2A não é confiável nesse intervalo). Se o custo de harmonizar com Landsat 8 já vai ser pago, 2013
"sai de graça": mesmo sensor, mesmo código, mesmo tratamento. Cortar em 2016 pagaria o preço inteiro
da complexidade por 3 anos a menos de série.

### Por que a Faixa B não é automática

As construções dos três data centers são todas posteriores a ~2013. Estender a série até 2000 não
adiciona sinal sobre o data center em si — adiciona contexto regional (ritmo de urbanização prévio
da região). É um argumento secundário, e custa uma segunda harmonização, o buraco de 2012, e uma
fonte de label que cubra o período.

### O que fica em aberto / consequências assumidas

- A troca de sensor ocorre em 2019, coincidindo com o período de maior crescimento dos data centers
  — risco de confundir instrumentação com sinal ambiental real. Mitigado por SV-20 (validação
  cruzada entre sensores), tarefa não-cortável do plano.
- Harmonizar dois sensores reduz as features de 17 para 13 bandas (perde as bandas red-edge,
  exclusivas do Sentinel-2).
- O ESA WorldCover (safra fixa ~2021) aplicado a uma série de 13 anos gera defasagem de label de
  até 8 anos — ver SV-05b (avaliação do MapBiomas como fonte de label anual).

## Alternativas descartadas

- **Sentinel-2 apenas, 2019–2025:** mais simples, mas corta 6 anos de série e não atende ao pedido
  explícito do usuário de maximizar cobertura temporal defensável.
- **Corte em 2016:** paga o custo total de harmonização com Landsat 8 por uma janela 3 anos menor
  que 2013, sem ganho real de simplicidade.
- **Faixa B habilitada desde já:** adicionaria uma segunda harmonização (TM→OLI) e o buraco de 2012
  antes de validar que a Faixa A (o núcleo da V1) está sólida — risco desnecessário ao cronograma.
