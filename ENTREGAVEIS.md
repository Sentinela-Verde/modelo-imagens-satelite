# Entregáveis — quem produz o quê, em que formato, para qual modelo

Mapa de navegação deste repositório para o grupo. Cada linha diz **onde o arquivo está de
verdade** e **qual código o produz**.

Atualizado em 2026-09-12.

---

## Os quatro modelos

| | modelo | responsável | onde mora |
|---|---|---|---|
| **1** | classificação de imagem | Gabriel | `src/sentinela/` |
| **2** | seleção de grupo de controle | Gabriel | `dados-modelo-impacto/scripts/impacto_dc_03_gerar_controles.py` |
| **3** | impacto | Guilherme | fora deste repositório |
| **4** | impacto melhorado | — | **WIP** — ver "Não entregue" no fim |

> **O modelo 3 tem uma implementação paralela aqui.** `modelo-impacto-score/` é a versão desta
> frente: medição por eixo com selo de evidência, placebo e testes de robustez. Vale o grupo
> conferir se as duas concordam antes da apresentação — se divergirem, a divergência é
> informação.

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
| 7 | Mapa de classes + confiança (controle) | modelo 1 | idem | `dados-modelo-impacto/raw/controles-rf/classificado/` |
| 8 | Candidatos a controle avaliados | modelo 2 | CSV | `dados-modelo-impacto/raw/controles-rf/candidatos_avaliados_rf.csv` |
| 9 | Pares tratamento/controle | modelo 2 | CSV | `.../pareamento_controle_rf.csv` |
| 10 | Boletim de impacto por eixo | análise | CSV | `modelo-impacto-score/outputs/boletim_por_eixo.csv` |
| 11 | Selos de evidência | análise | CSV | `modelo-impacto-score/outputs/selos_de_evidencia.csv` |
| 12 | Área por classe (indicadores) | modelo 1 | CSV | `outputs/indicadores/area_por_classe.csv` |

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

| notebook | modelo | mostra | gerador |
|---|---|---|---|
| `06_modelo1_construcao` | 1 | rótulos, amostragem, split de 3 eixos, avaliação | `modelo-impacto-score/scripts/10_*.py` |
| `04_demo_visual_classificador` | 1 | imagem → falsa-cor → classificação, interativo | `.../07_*.py` |
| `07_modelo2_construcao` | 2 | grade de 168 candidatos, filtros, funil de 2 estágios | `.../09_*.py` |
| `08_modelo2_demo` | 2 | um campus: 168 → 5 finalistas → 1 escolhido | `.../09_*.py` |
| `02_impacto_score` | 3 | o boletim por eixo e os selos | `.../04_*.py` |
| `05_caracterizacao_americas` | — | descritivo de 612 campi, sem causalidade | `.../08_*.py` |
| `03_status_e_proximos_passos` | — | retrato de estado | `.../05_*.py` |

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

O código existe e **passou** na validação (`dados-modelo-impacto/scripts/impacto_dc_40_*.py`,
relatório em `reports/experiments/EXP-004-modelo-conversao.md`): prevê, por pixel, onde a
conversão vai acontecer, com PR-AUC de 0,2954 contra 0,1613 do baseline sob leave-one-site-out
— +83% e positivo em 20 de 20 sítios.

Fica registrado como WIP, não como entrega. Quem retomar deve ler antes
`docs/handoff-modelo-conversao-pixel.md`, especialmente a ressalva de que o score é **ranking**,
não probabilidade calibrada.
