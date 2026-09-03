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

`raw/` fica de fora do git (respostas brutas de API, ~7,5MB, reproduzível rodando os scripts de
novo). `processed/` **é commitado** (~384KB, é o resultado útil — mesma lógica de
`data/manifests/` no repositório principal).

## Lista de trabalho: 19 facilities

16 sites já validados deste repositório (`config/sites.geojson`) + 3 novos, reconciliados a partir
do scraping do Guilherme
(`datacenter-extracao-modelos/data/02_silver/datacentermap_enriquecido.csv`, 21 facilities, 17 já
batiam com os nossos 16 — inclusive confirmando de forma independente o agrupamento de campus com
vários prédios que já tínhamos): **Scala AI City** (Eldorado do Sul/RS), **Pecém Data Center** (São
Gonçalo do Amarante/CE — aparecia duplicado no scraping do Guilherme, vale avisar ele), **RT-One
Uberlândia** (MG, primeira facility em Triângulo Mineiro). Essas 3 não passaram pela validação de
coordenada em 5 camadas que os 16 originais tiveram — ver coluna `origem_lista` nas planilhas.

## Arquivos finais (`processed/`)

| Arquivo | Conteúdo | Cobertura |
|---|---|---|
| `consolidado_painel_anual.csv` | 1 linha por site×ano: temperatura (LST), população, emprego formal, PIB, área por classe do classificador (vegetação/água/construída/solo exposto) | 232 linhas, 19 sites — **os 3 sites novos só têm PIB e área do classificador; temperatura/população/emprego cobrem só os 16 originais** (coletados antes da reconciliação) |
| `consolidado_desemprego.csv` | Taxa de desocupação anual | Só **5 dos 18 municípios** — o IBGE só publica essa taxa em nível municipal pras capitais de estado |
| `consolidado_renda.csv` | Renda média/mediana per capita | 19 sites, só 2022 (Censo, não é anual) |
| `consolidado_escolaridade.csv` | Nível de instrução por faixa etária, formato longo | 19 sites × 2 censos (2010, 2022) — cortes etários diferentes entre os dois, não é 1:1 comparável |
| `consolidado_facilities.csv` | Atributos estáticos por site: bioma/região/tier (nosso) + MW construído/tier projetado/nº prédios (scraping do Guilherme) | 19 sites |
| `consolidado_apoio_impacto.xlsx` | As 5 tabelas acima, uma aba cada | — |

Script que gera tudo isso: `scripts/montar_planilha_consolidada.py` (idempotente, roda de novo se
qualquer fonte for atualizada).

## Ressalva que vale repetir sempre que esses dados forem usados

**Nenhuma das variáveis socioeconômicas/demográficas acima (população, emprego, PIB, renda,
desemprego, escolaridade) tem granularidade suficiente pra sustentar uma afirmação de impacto
causado por um data center específico** — são todas em nível de município, e um empreendimento de
dezenas de hectares é uma fração ínfima da população/economia de um município inteiro. Servem como
**contexto/estratificação dos casos**, não como evidência de efeito. Detalhe completo em
`docs/requisitos-dados-externos.md` (raiz do repositório).

## Status

Coleta inicial concluída (2026-09-03): temperatura, população, emprego, PIB, renda, desemprego e
escolaridade levantados; lista reconciliada com o scraping do Guilherme; planilha consolidada
montada. Pendências conhecidas: (1) temperatura/população/emprego não cobrem os 3 sites novos; (2)
desemprego municipal só existe pra 5 dos 18 municípios; (3) nada foi validado com a mesma cascata
de 5 camadas (V1-V5) que os 16 sites originais tiveram.
