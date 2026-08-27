# SV-01 — Bootstrap do repositório

- **Fase:** 0 — Destravar · **Data-alvo:** 27/08 · **Tamanho:** M (~2h)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** — (nada)
- **Desbloqueia:** SV-04, SV-05
- **Tem seção de risco:** SIM (segredos / `.gitignore`)

## Contexto

O repositório está **completamente vazio** — só existem `.git`, `CLAUDE.md` e `.claude/agents/`.
Não há commits. Tudo abaixo é criação do zero. Leia `CLAUDE.md` antes de começar.

Não copie código do repo irmão `datacenter-extracao-modelos`. Este repo é independente por decisão do time.

## Objetivo

Deixar o repo em estado onde qualquer integrante clona, roda dois comandos e tem um ambiente
Python funcional com o stack geoespacial, sem risco de commitar raster pesado ou credencial.

## Escopo — o que fazer

1. **Estrutura de pastas** (com `.gitkeep` onde a pasta é gitignorada mas precisa existir):

```
config/                     # sites.geojson, classes.yml, params.yml  (COMMITADO)
data/
  raw/                      # GeoTIFF Sentinel-2                       (gitignored)
  interim/                  # features intermediárias                  (gitignored)
  processed/                # dataset parquet, rasters classificados   (gitignored)
  labels_manual/            # GeoJSON de rotulagem humana              (COMMITADO — ver D-07)
  manifests/                # JSON de proveniência                     (COMMITADO)
models/                     # .joblib                                  (gitignored)
notebooks/
outputs/indicadores/        # entregável para a frente 05              (gitignored)
reports/
  figures/                  # PNG de métricas/mapas                    (COMMITADO)
  experiments/              # EXP-XXX.md                               (COMMITADO)
src/sentinela/
  __init__.py
  config.py                 # carrega config/ + .env
  check.py                  # diagnóstico de ambiente
tests/
docs/
docs/tarefas/               # já existe
```

2. **`requirements.txt`** — Python 3.11 (wheels de `rasterio`/`geopandas` estáveis no Windows;
   3.13 ainda dá dor de cabeça). Fixar versões com `>=`/`<`:
   `earthengine-api`, `rasterio`, `geopandas`, `shapely`, `pyproj`, `numpy<2.1`, `pandas`,
   `pyarrow`, `scikit-learn`, `joblib`, `matplotlib`, `pyyaml`, `python-dotenv`, `tqdm`, `requests`.
   **Não** incluir PyTorch/TensorFlow — decisão D-01, o V1 não usa Deep Learning.
   `requirements-dev.txt`: `pytest`, `ruff`, `jupyter`.

3. **`.gitignore`** — obrigatoriamente cobrindo:
   `.venv/`, `__pycache__/`, `.ipynb_checkpoints/`, `.env`, `*.tif`, `*.tiff`, `*.parquet`,
   `data/raw/`, `data/interim/`, `data/processed/`, `models/`, `outputs/`,
   e **credenciais**: `*-service-account*.json`, `*credentials*.json`, `.config/earthengine/`.
   Exceções explícitas com `!`: `!data/labels_manual/`, `!data/manifests/`, `!.gitkeep`.

4. **`.env.example`** (commitado, sem valores reais):
   `EE_PROJECT=`, `EE_SERVICE_ACCOUNT_KEY=` (caminho absoluto para um arquivo **fora** do repo),
   `DATA_ROOT=./data`, `RANDOM_SEED=42`.

5. **`src/sentinela/config.py`** — carrega `.env` via `python-dotenv` e os YAML de `config/`,
   expõe `SEED`, caminhos como `pathlib.Path`, e falha com mensagem clara se faltar variável.

6. **`src/sentinela/check.py`** — executável via `python -m sentinela.check`: imprime versão do
   Python, versões das libs críticas, se `.env` foi encontrado, se as pastas de `data/` existem,
   e termina com `OK` ou lista o que falta. **Não** autentica no Earth Engine (isso é SV-04).

7. **`README.md`** — o que é o repo, link para `CLAUDE.md` e `docs/plano-execucao.md`,
   e um "Setup em 3 comandos" (criar venv, instalar, `python -m sentinela.check`).

8. **`tests/test_config.py`** — um teste mínimo de que `config.py` carrega e resolve caminhos.

## Fora de escopo

- Autenticação Earth Engine (SV-04).
- Conteúdo real de `config/sites.geojson` e `config/classes.yml` (SV-02 e SV-05) — criar apenas
  arquivos-placeholder com um comentário apontando para a tarefa que os preenche.
- Qualquer lógica de ingestão, feature ou modelo.

## Critérios de aceite

- [ ] `python -m venv .venv` + `pip install -r requirements.txt` conclui sem erro no Windows 11.
- [ ] `python -m sentinela.check` roda e imprime `OK` (ou lista pendências) com exit code 0.
- [ ] `pytest` passa.
- [ ] Colocar um arquivo dummy de 1 MB em `data/raw/teste.tif` → `git status` continua limpo.
- [ ] Criar um `.env` local com valores fake → `git status` continua limpo.
- [ ] Criar `data/labels_manual/teste.geojson` → `git status` **mostra** o arquivo (a exceção funciona).
- [ ] `README.md` permite a alguém que nunca viu o repo chegar em `OK` sem perguntar nada.

## Cenários de teste

1. **Clone limpo:** clonar em outra pasta, seguir só o README → chega em `OK`.
2. **Vazamento de raster:** `data/raw/x.tif` não aparece em `git status`.
3. **Vazamento de credencial:** `.env` e `minha-service-account.json` na raiz não aparecem em `git status`.
4. **Ativo preservado:** `data/labels_manual/x.geojson` aparece em `git status` (precisa ser commitável).
5. **Falha clara:** rodar `python -m sentinela.check` sem `.env` → mensagem dizendo o que fazer, não traceback.

## Riscos e mitigação

| Risco | Severidade | Mitigação |
|---|---|---|
| Chave de service account do Google Cloud commitada por acidente | **Alta** — chave GCP vazada em repo de org pública permite uso de quota e acesso a projeto | `.gitignore` cobre `*service-account*.json` e `*credentials*.json` **antes** do primeiro commit; `.env.example` instrui a guardar a chave **fora** do repo |
| Raster pesado no histórico do git (irreversível sem reescrever histórico) | Média | `.gitignore` criado no mesmo commit da estrutura de pastas, nunca depois |
| Divergência de ambiente entre os 6 integrantes | Média | `requirements.txt` com versões limitadas + `sentinela.check` como diagnóstico comum |

**Rollback:** repo sem commits ainda. Se algo sair errado, `git reset` e refazer — custo zero.
**Kill-switch de segredo:** se uma credencial for commitada, o procedimento é revogar a chave no
console GCP **primeiro** (o histórico é secundário), depois limpar. Documente isso no README.

## Como reportar

Ao terminar, informe: arquivos criados, versão do Python usada, saída do `python -m sentinela.check`,
e qualquer dependência que não instalou limpo no Windows.
