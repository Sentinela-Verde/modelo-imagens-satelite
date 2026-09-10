# Sentinela Verde — sumário executivo

**O que acontece com o território ao redor de um data center no Brasil?**

MBA Engenharia de Dados · Mackenzie · setembro de 2026

---

## O problema

O Brasil está construindo data centers rápido, e a conversa pública sobre eles é feita de
afirmações sem medida: que consomem energia demais, que aquecem a região, que dinamizam a economia
local. Nenhuma dessas frases vinha com um número, e nenhuma vinha com uma comparação — porque medir
exigiria saber o que teria acontecido naquele terreno **sem** o data center.

## O que construímos

Não um estudo sobre 15 empresas. Um **instrumento**:

> Dado um par de coordenadas em qualquer lugar do Brasil, ele mede a mudança territorial induzida
> por um empreendimento, comparando contra um terreno equivalente escolhido automaticamente — por
> imagem de satélite gratuita, sem visita ao local, de forma auditável e repetível.

Os data centers são o caso de validação. O mesmo instrumento serve para mineração, porto, rodovia
ou qualquer empreendimento pontual.

Para cada data center, o sistema escolhe sozinho um **terreno de comparação**: mesmo estado, mesmo
bioma, a 15–40 km de distância, com cobertura do solo parecida no ano anterior à obra. Tudo o que
se afirma é a diferença entre os dois — o que aconteceu ao redor do data center **menos** o que
aconteceu num lugar equivalente sem data center.

## O que encontramos

**Um data center adensa o terreno imediatamente ao redor dele.**

Em **12 de 14** casos, o anel de 500 metros no entorno — **excluído o prédio do próprio data
center** — converteu-se em área construída mais do que o terreno de comparação. Em números
concretos:

| | |
|---|---|
| Data center típico | **1,3 hectare** de prédio |
| Convertido a mais no entorno, dentro de 500 m | **~1,2 hectare** |

**Para cada hectare de data center, aproximadamente outro hectare se converte ao redor** — fora da
cerca, em terreno que não é do empreendimento.

Três características tornam esse achado difícil de contestar:

1. **É local.** Forte a 500 metros, metade a 1 quilômetro, some depois de 2. Não é a região
   urbanizando por inteiro — é mudança concentrada no terreno.
2. **Não é seleção de lugar.** Antes da obra, os dois grupos cresciam no mesmo ritmo. Os data
   centers não foram construídos justamente onde já se adensava.
3. **Depende de haver terreno livre.** Nos seis casos onde o sítio tinha espaço, **todos os seis**
   apresentaram o efeito. Onde o terreno já estava ocupado, o efeito encolhe — por falta de espaço,
   não por falta de efeito.

**E a mudança vem de vegetação.** A conversão de área vegetada em área construída também aparece de
forma consistente no anel de 500 metros.

## Por que se pode confiar no número

A objeção óbvia a qualquer resultado desses é: *e se o método simplesmente produzisse sinal do
nada?*

Testamos. Aplicamos o método idêntico a **15 pares de lugares onde nenhum data center foi
construído**. O resultado foi indistinguível de cara-ou-coroa, com sinal invertido em dois dos três
raios. **Aplicado onde nada aconteceu, o instrumento não encontra nada.**

## O que este trabalho não afirma

Esta lista vale tanto quanto a anterior.

**Não sabemos se esquentou.** Medimos duas vezes. Na primeira, o sensor tinha resolução grosseira
demais para enxergar um anel de 500 metros — e provamos isso, em vez de reportar um "não houve
efeito" enganoso. Na segunda, com o sensor na escala certa, a estimativa aponta para **meio grau a
mais**, com o mesmo padrão de decaimento com a distância que a conversão de terreno. Mas com 12
casos não dá para confirmar: seriam necessários cerca de 30.

**Não sabemos se gerou emprego, renda ou população.** Esses dados só existem por município, e um
empreendimento de algumas dezenas de hectares é uma fração ínfima de um município inteiro.
Verificamos que a granularidade adequada é obtível — mas a base necessária não está acessível hoje.

**Não sabemos que tipo de construção apareceu.** O satélite vê "virou construção", não vê se virou
galpão, comércio ou moradia.

**Não conseguimos prever a intensidade num site novo.** Testamos treze modelos diferentes; nenhum
supera simplesmente chutar a média. O padrão é previsível; a magnitude não. O sistema devolve, por
isso, uma **faixa esperada** calibrada — não um número que fingiria precisão inexistente.

## Para quem isso serve

- **Prefeituras e órgãos de licenciamento** — um data center induz adensamento mensurável num raio
  de 1 km. É insumo de zoneamento e de planejamento de infraestrutura, disponível antes da obra.
- **Operadores e investidores** — sítios com terreno livre carregam mais mudança territorial
  induzida, o que é exposição concreta em licenciamento ambiental e relato de sustentabilidade.
- **Sociedade e imprensa** — um método barato, nacional e auditável para verificar afirmações sobre
  impacto, sem depender de dado fornecido pelo próprio empreendedor.

## Em uma frase

> Data centers adensam o entorno imediato — cerca de um hectare convertido para cada hectare
> construído, num raio de 500 metros, principalmente onde havia terreno livre. Sabemos disso porque
> comparamos com terrenos equivalentes e porque testamos o método onde nada aconteceu. E sabemos
> exatamente quais perguntas ainda não conseguimos responder.

---

*Detalhamento técnico, com todos os números, testes e limitações:*
`modelo-impacto-score/reports/relatorio-impacto.md`
*Demonstração interativa:* `notebooks/02_impacto_score.ipynb`
*Reprodução completa:* `python scripts/reproduzir_impacto.py --etapa completo`
