Fecha a frente de impacto com o que faltava de robustez, responde a pergunta de temperatura na escala certa, e entrega as demos.

## O achado — corrigido, e mais forte

O anel de 0–500 m **sem o prédio** converte **+1,50 p.p.** a mais que o controle pareado (12/14, p=0,0065).

A versão anterior media um **disco** que continha o próprio data center — leitura circular ("depois de construir um data center, detectamos um data center"). Descontando o footprint, **~73% do efeito está fora da cerca**, e a vegetação passou de *sugestivo* a **forte** (11/14, p=0,0287).

Em hectares: DC mediano de 1,29 ha, excesso convertido fora dele de ~1,2 ha. Aproximadamente um hectare a mais se converte ao redor para cada hectare construído.

## Robustez — 7 verificações

| verificação | resultado | número |
|---|---|---|
| Placebo (controle vs controle) | **PASSOU** | 8/15, p=0,50 — não acha nada onde nada foi construído |
| Tendências pré-obra paralelas | **PASSOU** | 6/14, p=0,79 |
| Gradiente de distância | **PASSOU** | some em 2 km |
| Circularidade | **PASSOU** | corrigida, achado sobrevive |
| Reprodução ponta a ponta | **PASSOU** | 21/21 passos, 2×, idêntica |
| Janela longa (t≥4) | INCONCLUSIVO | n=9, os dois anéis apontam para lados opostos |
| Validação cruzada (Dynamic World) | PARCIAL | direção replica, significância não |

**Sobre a validação cruzada, sem maquiagem:** o DW replica a direção nos três raios mas não a significância. Testei a desculpa fácil ("o DW é ruidoso demais") medindo trocas de classe ano a ano nos controles — **o nosso classificador é 2,3× mais instável que o dele** (16,8% contra 7,3%). A hipótese estava invertida, e a replicação parcial fica registrada como limitação.

O que segura o achado apesar disso é o placebo: ele usou o nosso classificador, com todo esse ruído, e não achou nada.

## Temperatura — medida duas vezes

MODIS de 1 km diluía o sinal **427×** num disco de 5 km (nulo sem poder). Refeito com **Landsat 30 m no anel** (872 pixels em vez de uma fração de um): **+0,51 °C** com gradiente de distância coerente, mas precisaria de **n=31** e temos 12.

Achado contraintuitivo registrado: **a resolução melhorou 33× e o poder estatístico piorou** (MDE 0,82 contra 0,64 °C), porque `MDE = 2,80·σ/√n` e trocar de sensor não mexe em nenhum dos dois termos a favor.

## Entregáveis

- `scripts/reproduzir_impacto.py` — 31 passos, um comando, determinístico (verificado 2×)
- `reports/sumario-executivo.md` — 1 página, sem um p-valor no corpo
- `reports/relatorio-impacto.md` — técnico, com a reconciliação das evidências que pareciam discordar
- **`notebooks/04_demo_visual_classificador.ipynb`** — o modelo funcionando com imagem de satélite: RGB → falsa-cor → classificação, série ano a ano, mapa de confiança, anéis de medição, e uma célula interativa
- `notebooks/03_status_e_proximos_passos.ipynb` — retrato de estado
- `notebooks/02_impacto_score.ipynb` — demo do modelo de impacto
- `docs/decisoes/ADR-006` — desenho do classificador global BR+EUA (**proposto**, aguarda decisão)

## O que NÃO afirmamos, e está escrito

- **emprego, PIB, população** — o dado só existe por município
- **tipo de edificação** — o OSM tem viés de cobertura: os *controles* não são mapeados (0 a 4 feições contra 15–5.447 dos tratamentos), e o confundidor corre na mesma direção da hipótese
- **data da obra** — vem de fonte externa; o modelo erra 1,7 a 2,8 anos
- **magnitude num site novo** — 13 modelos, todos com R² LOOCV negativo, permutação p=0,64

## Como conferir

```bash
python scripts/reproduzir_impacto.py --listar   # os 31 passos, com custo e dependência
python scripts/reproduzir_impacto.py            # 21 passos offline, ~3 min
```

## Notas de revisão

- Não toca em `src/sentinela/` — o classificador entra como artefato pronto, que é a relação correta entre as frentes.
- Dois pontos ficaram **fora** deste PR por não serem meus: `config/classes.yml` modificado e 35 PNGs regenerados em `reports/figures/`.
- A expansão da amostra para ~25 campi (passo 25) está com o pareamento rodando e entra num PR seguinte.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
