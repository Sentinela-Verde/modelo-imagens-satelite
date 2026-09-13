Fecha a frente de impacto: expande a amostra para N=20, corrige um bug meu que inflava um dos eixos, responde a pergunta de temperatura na escala certa, e entrega as demos.

## O achado

Em **18 de 20** campi, o anel entre **500 m e 1 km** converteu para área construída mais que o controle pareado: excesso mediano de **+1,05 p.p.**, **p=0,0002**.

Esse é o número de destaque, e por três razões que se somam:

- **maior N** (20) — não depende de o footprint do OSM existir;
- **menor p** (0,0002);
- **livre do prédio por construção** — um anel com raio interno de 500 m nunca contém o empreendimento, então não há correção de circularidade a fazer nem hipótese a checar.

O boletim tem quatro eixos e **nenhum score único** (um agregado exigiria pesos arbitrários e misturaria eixos com qualidade de evidência incompatível):

| eixo | n | efeito mediano | p | selo |
|---|---:|---:|---:|---|
| Construída, anel **500 m–1 km** | **20** | **+1,05 p.p.** | **0,0002** | `forte` |
| Construída, anel 0–500 m (sem o prédio) | 16 | +1,49 p.p. | 0,0384 | `forte` |
| Vegetação → construída, anel 0–500 m | 16 | +0,52 p.p. | 0,105 | `sugestivo` |
| Aquecimento (LST Landsat 30 m), 0–500 m | 12 | +0,51 °C | 0,388 | `nulo_amostra_pequena` |

O efeito **decai com a distância e some**: 18/20 em 0,5–1 km, 12/16 em 0–500 m, e **13/20 sem significância em 1–2 km** (p=0,13). De 0,5 km para 5 km o disco cresce 100× e o excesso só 11,6× — a densidade cai 7×. É mudança local, não a região urbanizando por inteiro.

**Onde havia terreno, o efeito é maior:** greenfield (< 50% do footprint já construído) dá **6 de 6** positivos, p=0,016, +2,40 p.p.; brownfield dá 5 de 7, p=0,227, +0,77 p.p. Isso explica os dois únicos pares negativos do estudo — `ascenty-jundiai` e `ascenty-sumare`, com 86% e 88% do footprint já construídos: em sítio saturado sobra pouco terreno convertível, e o excesso encolhe por motivo **mecânico**, não por ausência de efeito.

## A amostra expandida — e um bug meu que ela expôs

A amostra foi de 15 para 20 campi. Os 5 novos vêm do `datacentermap` **sem** a validação de coordenada em 5 camadas dos originais, então o teste roda em três recortes separados:

| recorte | anel 0,5–1 km | p |
|---|---|---|
| só os 15 validados | 13/15 | 0,0037 |
| **só os 5 novos** | **5/5** | **0,031** |
| **conjunto** | **18/20** | **0,0002** |

Os cinco novos são positivos **todos os cinco** e sozinhos já atingem significância.

**Ao recalcular por mascaramento direto sobre o raster, dois números que este repositório já havia reportado se mostraram errados.** A correção de circularidade anterior subtraía *aritmeticamente* as contagens do footprint das do disco — o que só vale se o footprint estiver **dentro** do disco de 500 m. Não está em **4 dos 14** campi: `ascenty-vinhedo` tem o polígono 100% fora (a 615 m do ponto validado), `ascenty-sumare` 67%, `scala-sgigsm01` 15%, `equinix-santana-parnaiba` 3%.

| | antes (aritmético, errado) | agora (mascaramento direto) |
|---|---|---|
| `ascenty-hortolandia` | +0,25 p.p. | **−1,31 p.p.** — troca de sinal |
| eixo de vegetação | 11/14, p=0,029, `forte` | **16 pares, p=0,105, `sugestivo`** |

**O eixo de vegetação não é `forte`.** A significância que ele tinha era artefato da subtração indevida, e a leitura anterior — de que tornar a análise mais estrita havia *fortalecido* o resultado — não se sustenta. O achado que se sustenta é o de conversão para área construída.

Dois campi ficam **fora** do anel interno por não terem footprint sobrepondo a zona (`everest-goiania`, sem polígono no OSM; `ascenty-vinhedo`, polígono a 615 m). Mantê-los ali deixaria o próprio prédio dentro da conta.

## Robustez — 7 verificações

| verificação | resultado | número |
|---|---|---|
| Placebo (controle vs controle) | **PASSOU** | 8/15, p=0,50 — não acha nada onde nada foi construído |
| Tendências pré-obra paralelas | **PASSOU** | 6/14, p=0,79 |
| Gradiente de distância | **PASSOU** | some em 1–2 km (13/20, p=0,13) |
| Circularidade | **PASSOU** | recalculada por mascaramento direto; achado sobrevive |
| Amostra expandida | **PASSOU, mais forte** | 5/5 nos novos; 18/20 no conjunto |
| Janela longa (t≥4) | INCONCLUSIVO | n=9, os dois anéis apontam para lados opostos |
| Validação cruzada (Dynamic World) | PARCIAL | direção replica, significância não |

**O placebo é a verificação que mais importa.** 15 pares controle-contra-controle, mesma janela, ano de obra fictício, método idêntico: 8/15 (p=0,50) a 0,5 km, 7/15 (p=0,70) a 1 km e a 2 km — **com sinal invertido em dois dos três raios**. Isso transforma o selo `forte` de um p-valor solto numa taxa de falso positivo *medida*.

**Sobre a validação cruzada, sem maquiagem:** o Dynamic World replica a direção nos três raios mas não a significância. Testei a desculpa fácil ("o DW é ruidoso demais") medindo trocas de classe ano a ano nos controles — **o nosso classificador é 2,3× mais instável que o dele** (16,8% contra 7,3%). A hipótese estava invertida, e a replicação parcial fica registrada como limitação. O que segura o achado apesar disso é o placebo: ele rodou com o nosso classificador, com todo esse ruído, e não achou nada.

## Temperatura — medida duas vezes

MODIS de 1 km diluía o sinal **427×** num disco de 5 km (nulo sem poder). Refeito com **Landsat 30 m no anel** (872 pixels em vez de uma fração de um): **+0,51 °C** com gradiente de distância coerente, mas precisaria de **n=31** e temos 12.

Achado contraintuitivo registrado: **a resolução melhorou 33× e o poder estatístico piorou** (MDE 0,82 contra 0,64 °C), porque `MDE = 2,80·σ/√n` e trocar de sensor não mexe em nenhum dos dois termos a favor.

## Entregáveis

- `scripts/reproduzir_impacto.py` — 41 passos declarados (15 de rede), **26 offline em ~4 min**, um comando, determinístico
- `modelo-impacto/reports/sumario-executivo.md` — 1 página, sem um p-valor no corpo
- `modelo-impacto/reports/relatorio-impacto.md` — técnico, com a reconciliação das evidências que pareciam discordar e o registro do bug acima
- **`notebooks/04_demo_visual_classificador.ipynb`** — o modelo funcionando com imagem de satélite: RGB → falsa-cor → classificação, série ano a ano, mapa de confiança, anéis de medição, e uma célula interativa
- `notebooks/03_status_e_proximos_passos.ipynb` — retrato de estado
- `notebooks/02_impacto_score.ipynb` — demo do modelo de impacto
- `docs/decisoes/ADR-006` — desenho do classificador global BR+EUA (**proposto**, aguarda decisão)

## O que NÃO afirmamos, e está escrito

- **emprego, PIB, população** — o dado só existe por município, e um empreendimento de dezenas de hectares é fração ínfima de um município
- **tipo de edificação** — o OSM tem viés de cobertura: os *controles* não são mapeados (0 a 4 feições contra 15–5.447 dos tratamentos), e o confundidor corre na mesma direção da hipótese
- **data da obra** — vem de fonte externa; o modelo erra 1,7 a 2,8 anos
- **persistência além de 3 anos** — n=9, os dois anéis divergem
- **magnitude num site novo** — 13 modelos, **todos** com R² LOOCV negativo, permutação **p=0,77**. A direção é predizível; a magnitude não.

## Como conferir

```bash
python scripts/reproduzir_impacto.py --listar   # os 41 passos, com custo e dependência
python scripts/reproduzir_impacto.py            # 26 passos offline, ~4 min
```

## Notas de revisão

- Não toca em `src/sentinela/` — o classificador entra como artefato pronto, que é a relação correta entre as frentes.
- Ficam **fora** deste PR, por não serem desta frente: `config/classes.yml` modificado (troca de cor da classe `solo_exposto_obras`, de 05/set), 46 PNGs regenerados em `reports/figures/`, `AGENTS.md` e `docs/handoff-engenharia-jobs-etl.md` (ainda não rastreados).
- Próximo na fila, fora deste PR: retreino com rótulos do Dynamic World, conforme o ADR-006.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01SJ4igELmiWqFDcBCo1yBBt
