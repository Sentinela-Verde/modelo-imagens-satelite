# Entregáveis — quem produz o quê, em que formato, para qual modelo

Mapa de navegação deste repositório para o grupo. Cada linha diz **onde o arquivo está de
verdade** e **qual código o produz**.

Atualizado em 2026-09-12.

---

## As duas pastas de código

Desde 2026-09-13 a árvore separa por **assunto**, não por cronograma:

| pasta | o que é |
|---|---|
| `src/sentinela/` + `config/`, `data/`, `models/`, `tests/`, `scripts/` | **o modelo de imagem** |
| `modelo-impacto/` | **tudo de impacto** — controles, passos 01–41, boletim por eixo |
| `notebooks/` | os 9 notebooks, dos dois lados |

Antes eram três pastas, e a fronteira não correspondia a nada: os geradores de notebook do modelo
de **imagem** moravam dentro de `modelo-impacto-score/`, porque era onde já havia gerador de
notebook. Quem abrisse a pasta pelo nome achava outra coisa.

---

## Os quatro modelos

| | modelo | responsável | onde mora |
|---|---|---|---|
| **1** | classificação de imagem | Gabriel | `src/sentinela/` |
| **2** | seleção de grupo de controle | Gabriel | `modelo-impacto/scripts/impacto_dc_03_gerar_controles.py` |
| **3** | impacto | Guilherme | fora deste repositório |
| **4** | impacto melhorado | — | **WIP** — ver "Não entregue" no fim |

> **O modelo 3 tem uma implementação paralela aqui.** Os `modelo-impacto/scripts/score_*.py` são
> a versão desta frente: medição por eixo com selo de evidência, placebo e testes de robustez.
> Vale o grupo conferir se as duas concordam antes da apresentação — se divergirem, a divergência
> é informação.

---

## Entradas

| # | o quê | quem sobe | origem | formato | usa em | onde |
|---|---|---|---|---|---|---|
| 1 | Dados base dos data centers | Gabriel | pesquisa + `datacentermap` | GeoJSON | 1, 2 | `config/sites.geojson` |
| 2 | Imagens de satélite | Gabriel | API Earth Engine | **GeoTIFF, 6 bandas, int16** | 1 | `data/raw/{landsat,s2}/{site}/{ano}.tif` |
| 3 | Rótulos MapBiomas / Dynamic World | Gabriel | API Earth Engine | **GeoTIFF, 1 banda, uint8** | 1 | `data/raw/labels/` e `data/raw/labels-dw/` |
| 4 | Dados IBGE | Guilherme | BigQuery | CSV | 2, 3 | fora deste repositório |

**A entrada 1 é a única versionada no git.** As 2 e 3 somam ~1 GB e são gitignored — reproduzem
com `python -m sentinela.gee.landsat` / `.sentinel2` / `.labels`, ou vêm do S3 (camada Bronze).

---

## Saídas

| # | o quê | gerado por | formato | onde |
|---|---|---|---|---|
| 5 | **13 features** (6 bandas + 7 índices) | cálculo, `sentinela.features.indices` | **GeoTIFF, 13 bandas, float32** | `data/interim/features/{sensor}/{site}/{ano}.tif` |
| 6 | Mapa de classes + confiança (data center) | modelo 1 | **GeoTIFF uint8** + `_confianca.tif` | `data/processed/classificado/` |
| 7 | Mapa de classes + confiança (controle) | modelo 1 | idem | `modelo-impacto/raw/controles-rf/classificado/` |
| 8 | Candidatos a controle avaliados | modelo 2 | CSV | `modelo-impacto/raw/controles-rf/candidatos_avaliados_rf.csv` |
| 9 | Pares tratamento/controle | modelo 2 | CSV | `.../pareamento_controle_rf.csv` |
| 10 | Boletim de impacto por eixo | análise | CSV | `modelo-impacto/outputs/boletim_por_eixo.csv` |
| 11 | Selos de evidência | análise | CSV | `modelo-impacto/outputs/selos_de_evidencia.csv` |
| 12 | Área por classe (indicadores) | modelo 1 | CSV | `outputs/indicadores/area_por_classe.csv` |
| 13 | **Os classificadores treinados** | `sentinela.train` | joblib comprimido | **S3** — ver abaixo |

### ⚠ O item 5 não é JSON

A tabela original marcava o formato dos 7 índices espectrais com `????`. **São bandas de um
GeoTIFF**, não um JSON:

```
['blue','green','red','nir','swir1','swir2',        ← 6 bandas harmonizadas
 'ndvi','evi','ndwi','mndwi','ndbi','bsi','ndmi']   ← os 7 índices
```

Um `.tif` de 13 bandas `float32` por site/ano. JSON não serviria: são 111 mil pixels × 13
valores por arquivo, e o alinhamento pixel a pixel com o rótulo depende da grade
georreferenciada — que só o GeoTIFF carrega.

### O item 13 — onde os modelos moram, e qual é qual

Os `.joblib` não cabem no git (6,5 GB e 3,7 GB sem compressão). Comprimidos com `compress=3` e
conferidos pixel a pixel contra o original, estão em:

```
s3://plataforma-artifacts-149465616406-us-east-1-an/models/
  ├── manifest.json           ← leia este primeiro
  ├── rf_v1.0-tuned.joblib    2,33 GB   PRODUÇÃO
  └── rf_v2.0-dw.joblib       1,31 GB   candidato melhor, reprovado no critério de adoção
```

**São duas versões do mesmo modelo, e a melhor não é a de produção.** O `rf_v2.0-dw` ganha em
toda métrica de acurácia (macro-F1 0,776 → 0,828; F1 da classe 3 0,580 → **0,804**), mas o
critério que decide adoção neste projeto não é acurácia — é estabilidade temporal em terreno onde
nada mudou (`ADR-006 §4`). Nesse eixo ele melhora de 17,5% para 13,1% e ainda assim não alcança a
barra, que são os 7,2% do próprio Dynamic World. O `manifest.json` no bucket conta essa história
inteira; sem ele, quem baixar os dois escolhe pelo número errado.

### O que cabe no git e o que não cabe

| | tamanho | no git? |
|---|---:|---|
| entradas 2, 3 e saída 5 | ~4 GB | **não** — gitignored, vêm do S3 ou se reproduzem |
| saídas 6 e 7 (rasters) | ~880 MB | **não** — mesma razão |
| saídas 8–12 (CSVs) | < 5 MB | **sim** |
| manifests de proveniência | < 10 MB | **sim** — é o registro de como cada raster foi gerado |

---

## Notebooks

Dois por modelo, como o grupo combinou. Todos são **gerados por script** e reexecutados, para
não virarem documento morto.

Os 9 ficam em `notebooks/`, na raiz. O **gerador** de cada um mora na pasta do assunto que ele
documenta — os do modelo de imagem em `scripts/`, os de impacto em `modelo-impacto/scripts/`.

| notebook | modelo | mostra | gerador |
|---|---|---|---|
| `06_modelo1_construcao` | 1 | rótulos, amostragem, split de 3 eixos, avaliação | `scripts/nb_06_modelo1_construcao.py` |
| `04_demo_visual_classificador` | 1 | imagem → falsa-cor → classificação, interativo | `scripts/nb_04_demo_visual.py` |
| `07_modelo2_construcao` | 2 | grade de 168 candidatos, filtros, funil de 2 estágios | `modelo-impacto/scripts/nb_07_08_modelo2.py` |
| `08_modelo2_demo` | 2 | um campus: 168 → 5 finalistas → 1 escolhido | `modelo-impacto/scripts/nb_07_08_modelo2.py` |
| `02_impacto_score` | 3 | o boletim por eixo e os selos | `modelo-impacto/scripts/nb_02_impacto_score.py` |
| `05_caracterizacao_americas` | — | descritivo de 612 campi, sem causalidade | `modelo-impacto/scripts/nb_05_descritivo.py` |
| `03_status_e_proximos_passos` | — | retrato de estado | `modelo-impacto/scripts/nb_03_status.py` |

Todos entram no runner (`S4` a `S10`). Até 2026-09-13, os geradores dos notebooks 05, 06, 07 e 08
não estavam registrados nele — eram os únicos do repositório que ninguém reproduzia com um
comando, e são justamente os que o grupo combinou entregar como "construção" e "demo".

---

## Como reproduzir

```bash
pip install -r requirements-dev.txt && pip install -e .
python -m sentinela.check                      # confere o ambiente

python scripts/reproduzir_impacto.py --listar  # os passos, com custo e dependência
python scripts/reproduzir_impacto.py           # só o que roda offline, ~4 min
```

O runner declara cada passo e se ele depende de rede/credencial. Os passos de rede são
idempotentes: pulam o que já está em disco com sha256 conferido.

---

## Não entregue

**Modelo 4 — impacto melhorado.** O grupo decidiu em 2026-09-12 não seguir com ele.

O código existe e **passou** na validação (`modelo-impacto/scripts/impacto_dc_40_*.py`,
relatório em `reports/experiments/EXP-004-modelo-conversao.md`): prevê, por pixel, onde a
conversão vai acontecer, com PR-AUC de 0,2954 contra 0,1613 do baseline sob leave-one-site-out
— +83% e positivo em 20 de 20 sítios.

Fica registrado como WIP, não como entrega. Quem retomar deve ler antes
`docs/handoff-modelo-conversao-pixel.md`, especialmente a ressalva de que o score é **ranking**,
não probabilidade calibrada.

> **Ele não reproduzia, e isso só apareceu em 2026-09-13**, quando o passo entrou no runner e
> alguém rodou `--fase dataset` do zero. O script chamava duas funções que nunca existiram —
> `P11.grade_distancia_km` e `P26.mascara_footprint_do_campus`. A sequência: o dataset foi gerado
> às 17:02, o script foi refatorado depois, e as fases seguintes continuaram passando porque leem
> o parquet que já estava em disco. A revisão daquele commit conferiu a lógica do
> leave-one-site-out e não conferiu que o script rodava do início.
>
> As duas funções existiam como código, sem nome próprio: uma era o miolo de `mascaras_por_raio`,
> a outra a `_mascara_footprint` privada do passo 26. Extraídas e nomeadas, o parquet regenerado
> é **idêntico célula a célula** ao commitado — 6.779.792 linhas, 181.187 positivos. Os números
> acima valem; o que estava quebrado era só a capacidade de refazê-los.
