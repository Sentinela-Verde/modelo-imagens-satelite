# modelo-imagens-satelite — Sentinela Verde (frente de Modelagem/ML)

Frente de Modelagem/Machine Learning do projeto **Sentinela Verde** (MBA Engenharia de Dados,
Mackenzie): monitoramento geoespacial de impacto ambiental/territorial no entorno de data centers
via séries temporais de imagens de satélite (Sentinel-2/Landsat).

Contexto completo, decisões já fechadas pelo time e regras do repositório: veja `CLAUDE.md`.
Plano de execução (fases, tarefas, cronograma): veja `docs/plano-execucao.md` e `docs/tarefas/`.

## Setup em 3 comandos

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements-dev.txt && pip install -e . && python -m sentinela.check
```

Se `python -m sentinela.check` imprimir `OK`, o ambiente está pronto. Se listar pendências, siga
o que cada linha pede (normalmente: copiar `.env.example` para `.env` e preencher `EE_PROJECT`).

`check.py` **não** autentica no Google Earth Engine — isso é feito por outra tarefa
(`docs/tarefas/SV-04-autenticacao-earth-engine.md`).

## Rodar os testes

```bash
pytest
```

## Estrutura do repositório

```
config/                     # sites.geojson, classes.yml, params.yml  (commitado)
data/
  raw/                      # GeoTIFF Sentinel-2/Landsat                (gitignored)
  interim/                  # features intermediárias                   (gitignored)
  processed/                # dataset parquet, rasters classificados    (gitignored)
  labels_manual/            # GeoJSON de rotulagem humana                (commitado)
  manifests/                # JSON de proveniência                      (commitado)
models/                     # artefatos de modelo (.joblib)              (gitignored)
notebooks/                  # notebooks narrativos
outputs/indicadores/        # entregável para a frente de Indicadores    (gitignored)
reports/
  figures/                  # PNGs de métricas/mapas                    (commitado)
  experiments/              # log de experimentos (EXP-XXX.md)          (commitado)
src/sentinela/               # código-fonte reutilizável
tests/
docs/
  plano-execucao.md         # plano de execução da frente de ML
  tarefas/                  # uma tarefa por arquivo, autocontida
  decisoes/                 # ADRs (registro de decisões técnicas)
```

## Segurança de dados

`data/raw`, `data/interim`, `data/processed`, `models/` e `outputs/` são gitignored — nunca
commite raster (`.tif`), dataset (`.parquet`) ou artefato de modelo pesado. Credenciais (chave de
service account do Google Cloud, `.env`) também nunca são commitadas — veja `.gitignore`.

**Se uma credencial for commitada por acidente:** revogue a chave no console do Google Cloud
**primeiro** (antes de mexer no histórico do git — a chave vazada continua válida até ser
revogada, reescrever o histórico não resolve isso sozinho).
