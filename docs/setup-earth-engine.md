# Setup do Google Earth Engine

Todo dado deste repo vem do Google Earth Engine (GEE). Desde 2023 o GEE exige um **Cloud Project**
registrado — não basta ter uma conta Google.

## 1. Criar/registrar o Cloud Project

1. Acesse https://code.earthengine.google.com/register.
2. Escolha **"Acadêmico e pesquisa"** (unpaid/noncommercial) como caso de uso — é gratuito e serve
   para este projeto de MBA.
3. Crie um Google Cloud Project novo (ou use um existente) e registre-o para o Earth Engine nessa
   mesma tela. Anote o **Project ID** (não é o nome de exibição — é o identificador, ex.:
   `sentinela-verde-123456`).

## 2. Configurar o `.env`

```bash
cp .env.example .env
```

Edite `.env` e preencha:

```
EE_PROJECT=seu-project-id-aqui
```

Deixe `EE_SERVICE_ACCOUNT_KEY` vazio por enquanto — isso é só para rodar sem browser (CI/lote),
ver seção 4.

## 3. Autenticar (modo usuário — o normal para desenvolvimento)

```bash
python -m sentinela.gee.check --site ascenty-vinhedo
```

Na primeira execução, isso abre o **navegador padrão do seu sistema** pedindo login na sua conta
Google e permissão para o Earth Engine. Faça login com a conta associada ao Project ID do passo 1.
Depois de autorizar, o token fica salvo localmente em `~/.config/earthengine/` (fora do repo — não
é versionado, não precisa e não deve ser commitado). Execuções seguintes não pedem login de novo.

**Isso precisa ser feito no seu terminal, não por um agente/CLI headless** — o fluxo de login é
interativo e a conta é sua.

## 4. Alternativa: service account (sem browser, para lote/CI)

Só necessário se for automatizar em algo que não tem browser interativo:

1. No console do Google Cloud (IAM & Admin → Service Accounts), crie uma service account no mesmo
   projeto do passo 1.
2. Conceda a ela **apenas** o papel `Earth Engine Resource Viewer` — nunca `Editor`/`Owner` do
   projeto. Papel mais amplo do que o necessário é a forma mais comum de uma chave vazada virar
   incidente sério.
3. Gere uma chave JSON e salve **fora deste repositório** (ex.: numa pasta pessoal, nunca dentro de
   `modelo-imagens-satelite/`).
4. No `.env`, preencha `EE_SERVICE_ACCOUNT_KEY` com o **caminho absoluto** para essa chave.

## 5. Rodar o smoke test

```bash
python -m sentinela.gee.check --site <site_id>
```

`site_id` vem de `config/sites.geojson` (ex.: `ascenty-vinhedo`, `odata-hortolandia`,
`scala-tambore`). O script:

- Confirma acesso às coleções `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` e `ESA/WorldCover/v200`.
- Imprime uma tabela `ano | n_imagens` com a contagem de cenas Sentinel-2 disponíveis para cada
  ano da Faixa A (2013–2025), na janela jun–set.
- Salva `reports/figures/smoke_test_{site_id}.png` — um thumbnail RGB pra você confirmar
  visualmente que a AOI está no lugar certo (dá pra reconhecer a região, não está totalmente
  nublado).

## Erros comuns

**`ERRO DE CONFIGURAÇÃO: Variável de ambiente 'EE_PROJECT' não definida.`**
Falta copiar `.env.example` para `.env` e preencher `EE_PROJECT`.

**`O projeto '...' não está registrado para usar o Earth Engine.`**
O Cloud Project existe, mas não foi registrado no Earth Engine (passo 1). Volte em
https://code.earthengine.google.com/register e registre esse Project ID específico.

**Nenhuma imagem para algum ano (`n_imagens = 0` ou `< 8`)**
Não é erro do script — é um achado real sobre a AOI/janela, e afeta o planejamento de SV-06
(ingestão). Reporte junto com o resultado da tarefa.

**`[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Basic Constraints of CA cert not marked critical`**
Bug conhecido do Python 3.13 no Windows: a checagem de certificado ficou mais rígida (RFC 5280) e
rejeita uma CA que antivírus/VPN às vezes injetam no Windows pra inspecionar HTTPS — a mesma CA que
o navegador aceita sem problema. `src/sentinela/gee/auth.py` já corrige isso via `truststore`
(faz o Python validar TLS pela store de certificados do próprio Windows). Se aparecer mesmo assim,
confirme que `truststore` está instalado (`pip install -r requirements.txt`) e que `auth.py` chama
`truststore.inject_into_ssl()` **antes** de importar `ee`.

**`Google Earth Engine API has not been used in project ... or it is disabled`**
O projeto foi registrado em code.earthengine.google.com, mas a API não ficou habilitada no Cloud
Console. Acesse o link que o próprio erro imprime
(`console.developers.google.com/apis/api/earthengine.googleapis.com/overview?project=SEU_PROJETO`),
clique em "Enable", espere 2-3 minutos e rode de novo.

## Segurança

- Nunca cole o conteúdo de uma chave de service account em chat, issue ou PR — só o caminho do
  arquivo (que fica fora do repo).
- **Se suspeitar que uma chave vazou:** revogue-a primeiro no console GCP
  (IAM & Admin → Service Accounts → [conta] → Keys → Delete) — só depois disso limpe o git se ela
  tiver sido commitada por acidente. Uma chave revogada é inócua mesmo se continuar no histórico;
  uma chave só removida do git, mas não revogada, continua funcionando para quem a copiou.
