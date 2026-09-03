# dados-modelo-impacto

Pasta separada dentro deste repositório, dedicada a **apoiar o modelo de impacto do Guilherme**
(a frente seguinte do time: dado um data center, como ficam os indicadores ambientais e
socioeconômicos no entorno). **Não é o mesmo modelo deste repositório** — o classificador de
cobertura do solo (`src/sentinela/`) segue sendo a frente principal daqui, com seu próprio escopo,
prazo e regras (ver `CLAUDE.md` na raiz). Esta pasta existe só para não espalhar esse apoio em
outro repositório, e para deixar claro, pra quem ler o projeto depois, que é uma frente distinta
rodando em paralelo.

## Objetivo (do briefing do time)

Dado uma latitude/longitude, projetar como ficariam ~6 indicadores no entorno (rodando o cenário
de 2026):

- **Ambientais:** cobertura vegetal, água (pode não existir em todo site), temperatura de
  superfície.
- **Socioeconômicos/demográficos:** aumento de área construída no entorno, aumento do número de
  empregos (a confirmar se é sustentável de medir — ver ressalva abaixo).

Divisão combinada com o time:
- **Guilherme:** terminar de levantar os dados do datacentermap.com para os outros facilities.
- **Gabriel (este apoio):** baixar dados de temperatura, população e número de empregos, para os
  ~20 facilities (10 anos de histórico), com possibilidade de expansão da amostra.

## Antes de baixar qualquer coisa, leia isto

Este repositório já fez um levantamento equivalente para o classificador de imagem (SV-28) e
achou coisas que afetam diretamente este apoio:

1. **População e número de empregos, em nível municipal, não sustentam afirmação de impacto** —
   servem só como contexto/estratificação. Um data center é uma fração ínfima da população/economia
   de um município inteiro; qualquer variação observada tem mais causas concorrentes plausíveis que
   o empreendimento sozinho. Ver `docs/requisitos-dados-externos.md` (seção 2, "parecer honesto de
   granularidade") e `docs/contrato-dados-externos.yml` (`soc_populacao`, `soc_emprego_formal`,
   papel `D`) na raiz deste repo. Se o objetivo é uma afirmação causal ("o data center gerou N
   empregos"), a única granularidade defensável é setor censitário — e isso tem custo alto
   (compatibilizar malha do Censo 2010↔2022). Vale decidir isso **antes** de baixar, não depois.
2. **Temperatura de superfície (LST) não precisa vir de fonte externa** — dá pra extrair da mesma
   imagem de satélite (Landsat banda termal / MODIS), via Google Earth Engine, sem download manual.
   Fora do escopo do classificador principal (quebraria a harmonização de 13 features dele), mas
   não fora do escopo deste apoio.
3. **Grupo de controle / isolamento de causalidade já está desenhado** — ver
   `docs/tarefas/SV-29-grupo-controle-pareado.md`. Ponto de atenção: a distância mínima usada lá é
   **15–40 km** do data center (não 3 km) — perto demais cai dentro do raio de influência do
   próprio empreendimento, é "tratamento disfarçado de controle", o erro mais grave possível nesse
   desenho. O pareamento lá usa cobertura do solo pré-obra como critério de similaridade, não
   população.
4. **Sobre o modelo em si (regressão linear múltipla ou outro):** com N~20 sites, um regressor
   treinado é estatisticamente frágil — ajusta ruído, não sinal, e é a peça mais fácil de derrubar
   numa banca. A decisão equivalente tomada no classificador principal (`ADR` ainda não formalizado
   aqui, mas confirmada com o usuário) foi projeção por **análogo histórico** em vez de regressor
   treinado. Vale considerar o mesmo caminho aqui, a menos que a amostra cresça bem além de 20.

## Estrutura

```
dados-modelo-impacto/
├── raw/          # dados baixados, brutos (gitignored — pesado/específico de fonte)
├── processed/    # dados tratados, prontos para o modelo do Guilherme (gitignored por ora)
├── scripts/      # scripts de download/tratamento (committáveis)
└── README.md     # este arquivo
```

`raw/` e `processed/` estão no `.gitignore` por padrão, seguindo a mesma regra do resto do
repositório (nunca commitar dado bruto pesado). Se os arquivos finais forem pequenos (séries de
temperatura/população/emprego para ~20 sites × 10 anos tendem a ser leves — CSVs de poucos KB a
poucos MB), vale reavaliar e commitar `processed/` explicitamente, do mesmo jeito que
`data/labels_manual/` e `data/manifests/` têm exceção aberta no `.gitignore` principal.

## Status

Só a estrutura de pastas foi criada até agora — nenhum dado baixado, nenhum script escrito. Este
README é o ponto de partida.
