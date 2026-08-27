# SV-04 — Autenticação Earth Engine + smoke test

- **Fase:** 1 — Dados · **Data-alvo:** 28/08 · **Tamanho:** M (~2h, boa parte é burocracia de conta Google)
- **Responsável sugerido:** `data-engineer`
- **Bloqueado por:** SV-01
- **Desbloqueia:** SV-06, SV-07
- **Tem seção de risco:** SIM (credenciais Google Cloud)

## Contexto

Todo o dado deste repo vem do Google Earth Engine. Sem autenticação funcionando e **reproduzível
por outro integrante**, nada da Onda 3 acontece. Desde 2023 o Earth Engine exige um **Cloud
Project** registrado (não basta a conta) — o `ee.Initialize()` sem `project=` falha.

## Objetivo

Qualquer integrante do time consegue autenticar e confirmar acesso ao acervo Sentinel-2 na AOI,
com uma prova visual, em menos de 15 minutos seguindo a documentação do repo.

## Escopo — o que fazer

1. **`src/sentinela/gee/auth.py`** — função `init_ee()` que:
   - Lê `EE_PROJECT` do `.env` (falha com mensagem clara se ausente).
   - Suporta **dois modos**, nesta ordem de preferência:
     a. **Service account** — se `EE_SERVICE_ACCOUNT_KEY` estiver definido, usa
        `ee.ServiceAccountCredentials`. Modo preferido para rodar em CI/em lote.
     b. **Usuário** — senão, `ee.Authenticate()` (fluxo de browser, uma vez) + `ee.Initialize(project=...)`.
   - É idempotente: chamar duas vezes não reautentica.
2. **`src/sentinela/gee/check.py`** — executável: `python -m sentinela.gee.check --site <site_id>`.
   Para o site informado (lido de `config/sites.geojson`, ou um bbox default se SV-02 ainda não
   terminou), deve:
   - Inicializar o EE.
   - Contar imagens de `COPERNICUS/S2_SR_HARMONIZED` na AOI para cada ano de `config/params.yml`,
     na janela jun–set. Imprimir uma tabela `ano | n_imagens`.
   - Confirmar que `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` e `ESA/WorldCover/v200` são acessíveis.
   - Salvar um thumbnail RGB (`getThumbURL`) em `reports/figures/smoke_test_{site_id}.png`.
3. **`docs/setup-earth-engine.md`** — passo a passo: criar/registrar o Cloud Project no Earth Engine,
   escolher entre conta pessoal e service account, onde guardar a chave (**fora** do repo), e
   como rodar o smoke test. Inclua o erro mais comum e o que ele significa
   (`not registered to use Earth Engine` → falta registrar o project).

## Fora de escopo

- Baixar/exportar rasters (SV-06).
- Máscara de nuvem e composto (SV-06).

## Critérios de aceite

- [ ] `python -m sentinela.gee.check --site <site_id>` roda do zero e termina com exit code 0.
- [ ] A tabela `ano | n_imagens` mostra **≥ 8 imagens por ano** em cada ano da janela.
      Se algum ano tiver menos, isso é um achado a reportar (afeta SV-06), não uma falha da tarefa.
- [ ] `reports/figures/smoke_test_{site_id}.png` existe e, olhando a imagem, dá para reconhecer
      o local (não é uma tela branca nem toda nublada).
- [ ] Rodar duas vezes seguidas não pede reautenticação.
- [ ] `docs/setup-earth-engine.md` permite a outro integrante autenticar sem perguntar nada.
- [ ] `git status` limpo depois de tudo (nenhum token, nenhuma chave, nenhum `.config/earthengine`).

## Cenários de teste

1. **Feliz:** `.env` correto → tabela + thumbnail.
2. **Sem `EE_PROJECT`:** mensagem dizendo exatamente qual variável falta e onde obter o valor — não traceback.
3. **Project não registrado no EE:** mensagem traduzindo o erro do Google para o que fazer.
4. **Service account:** com `EE_SERVICE_ACCOUNT_KEY` apontando para uma chave válida fora do repo,
   funciona sem abrir browser.
5. **Segredo:** com `.env` preenchido e chave na raiz, `git status` continua limpo.

## Riscos e mitigação

| Risco | Severidade | Mitigação |
|---|---|---|
| Chave de service account (JSON com private key) commitada ou colada em issue/chat | **Alta** — permite consumir quota e, dependendo dos papéis do IAM, acessar outros recursos do projeto GCP | Chave vive **fora** do repo, referenciada só por caminho no `.env`; `.gitignore` de SV-01 cobre os padrões de nome; conceder à service account **apenas** o papel `Earth Engine Resource Viewer`, nunca `Editor`/`Owner` do projeto |
| Token de usuário do `ee.Authenticate()` gravado em `~/.config/earthengine/` e sincronizado por engano | Média | Documentar que é local; `.gitignore` cobre o caso de alguém apontar o diretório para dentro do repo |
| Quota do Earth Engine estourada por script em loop | Baixa | Smoke test consulta metadados e um thumbnail, não exporta |

**Kill-switch:** se houver suspeita de vazamento da chave, **revogar a chave no console GCP
primeiro** (IAM → Service Accounts → Keys → Delete), depois limpar o git. Chave revogada é inócua;
chave apagada só do git ainda funciona. Deixe isso escrito em `docs/setup-earth-engine.md`.

**Rollback:** a tarefa não altera dado nenhum. Reverter é apagar os arquivos criados.

## Como reportar

Informe: modo de autenticação usado, a tabela `ano | n_imagens` completa, e qualquer ano com
cobertura fraca (isso muda o plano de SV-06).
