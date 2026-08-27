# SV-18 — Revisão final (código + segurança)

- **Fase:** 5 — Entrega · **Data-alvo:** 13/09 · **Tamanho:** M (~2h)
- **Responsável sugerido:** `code-reviewer` e `security-reviewer` (agentes de nível usuário), em paralelo
- **Bloqueado por:** SV-15, SV-16, SV-19, SV-23
- **Desbloqueia:** — (portão da entrega, 13/09 — véspera da apresentação)
- **Tem seção de risco:** SIM (é a própria varredura de risco)

> **Revisada em 2026-08-27**: a API de SV-19 entra no escopo da revisão de segurança — é a primeira
> superfície do projeto que aceita entrada de terceiro.

## Contexto

Portão final antes de declarar a V1 fechada e de o repo ser visto pelo resto do time e pela banca.
O `CLAUDE.md` tem regras duras — nada de raster pesado, credencial ou artefato grande no git;
seed fixo em todo split/treino; todo experimento registrado — e ninguém verificou o conjunto ainda.

## Objetivo

Confirmar que o repo está publicável, reproduzível e sem segredo vazado, ou produzir a lista
priorizada do que corrigir antes.

## Escopo — o que fazer

### Parte A — `security-reviewer`

1. **Varredura de segredos em todo o histórico**, não só no working tree:
   `git log -p` procurando por `private_key`, `service_account`, `client_secret`, `BEGIN PRIVATE KEY`,
   `.json` de credencial, tokens do Earth Engine. Ferramenta (`gitleaks`, `trufflehog`) se disponível.
2. Confirmar que `.gitignore` cobre: `.env`, `*service-account*.json`, `*credentials*.json`,
   `.config/earthengine/`, `*.tif`, `*.parquet`, `models/`, `outputs/`.
3. `git ls-files` → nenhum arquivo > 5 MB; nenhum `.tif`, `.parquet`, `.joblib`.
4. Verificar que os notebooks (SV-17) não contêm caminho com nome de usuário, id de projeto GCP,
   e-mail pessoal ou token em output de célula.
5. Verificar o princípio do menor privilégio na service account do Earth Engine, se houver
   (papel `Earth Engine Resource Viewer`, não `Editor`/`Owner`).
6. **Revisão de exposição de dados:** os artefatos de `outputs/` nomeiam empresas reais e fazem
   afirmações sobre uso do solo no entorno delas. Confirmar que `docs/schema-indicadores.md` e
   `docs/model-card.md` trazem as limitações e a ressalva de não-causalidade em destaque, e não
   escondidas no rodapé.
7. **API de SV-19 (novo, e é o item de maior severidade desta revisão)** — é a primeira superfície do
   projeto que aceita entrada de terceiro:
   - Os drivers do GDAL estão restritos a `GTiff` no processo da API?
   - Os limites de tamanho e dimensão são aplicados **antes** de o raster ser aberto?
   - **Nenhuma rota desserializa conteúdo enviado** (`pickle`/`joblib` sobre upload = execução remota
     de código). O modelo é carregado só do caminho local do `.env`, no startup?
   - O nome do arquivo recebido é descartado (nada de path traversal)?
   - O bind é em `127.0.0.1`, não `0.0.0.0`? CORS restrito?
   - Erros devolvem mensagem genérica, sem traceback nem caminho absoluto?
   - Os arquivos de exemplo commitados não contêm nada além de recorte de imagem pública?

### Parte B — `code-reviewer`

1. **Aderência ao `CLAUDE.md`:** seed fixo em todo split/treino; nenhum código copiado do repo
   irmão `datacenter-extracao-modelos`; todo experimento com registro em `reports/experiments/`;
   e **as mudanças de fonte de label e de janela temporal foram levadas ao time** (ADR-001, ADR-004),
   não implementadas em silêncio.
2. **Vazamento de dados** — releia com olhos de revisor: `GroupKFold` por `bloco_id` de fato?
   O conjunto de teste é tocado em algum lugar antes de SV-13? Coordenada (`x`,`y`,`linha`,`coluna`)
   ou `ano` entraram como feature por acidente?
2b. **Vazamento entre sensores (novo):** `bloco_id` é derivado de coordenada projetada e não de
   índice de pixel? Nos anos de sobreposição, as duas cópias do mesmo terreno caem no mesmo split?
   Este é o vazamento mais fácil de introduzir e o mais difícil de enxergar em revisão superficial.
3. **Contrato de features:** a ordem de colunas é validada por nome em `predict.py` (SV-14), não
   assumida posicionalmente.
4. **Consistência de constantes:** ninguém hardcodou id de classe fora de `sentinela.classes`.
5. **Reprodutibilidade:** manifests batem com os arquivos; `sha256` confere; versões fixadas.
6. **Duplicação e altitude:** lógica repetida entre notebook e `src/`; funções longas demais.
7. Testes existem e passam; os testes antivazamento de SV-11 e o de banda reordenada de SV-14
   estão presentes (são os dois mais importantes do repo).
8. **Trilha do Plus (SV-21/22/23):** o `requirements-plus.txt` está separado e o pipeline da V1 roda
   sem PyTorch instalado? Os chips bitemporais herdaram o split de SV-11 sem criar um novo? A
   avaliação de SV-23 usa o mesmo conjunto de teste para os dois métodos? O relatório do Plus declara
   a expectativa **antes** dos números?

## Fora de escopo

- Implementar as correções (viram tarefas novas, priorizadas pelo PM).
- Refatoração ampla a 3 dias da entrega.
- Refatoração ampla — a esta altura restam menos de 48h para a apresentação.

## Critérios de aceite

- [ ] Relatório de segurança entregue, achados ranqueados por severidade.
- [ ] Relatório de código entregue, achados ranqueados por severidade.
- [ ] **Zero achados críticos abertos** (segredo no histórico, vazamento de dados no split,
      arquivo pesado commitado). Crítico aberto = V1 **não** fechada.
- [ ] Achados médios/baixos registrados como tarefas de backlog com responsável sugerido.
- [ ] Confirmação explícita de que `git ls-files` não traz `.tif`, `.parquet`, `.joblib` ou credencial.

## Cenários de teste

1. `git ls-files | xargs ls -la` ordenado por tamanho → maior arquivo < 5 MB.
2. Busca por padrões de segredo no histórico completo → nada.
3. Clone limpo + `pytest` → tudo passa.
4. Grep por `random_state` / `seed` → presente em todo ponto estocástico.
5. Grep por `classe == 3` ou literais de classe fora de `sentinela/classes.py` → nada.

## Riscos e mitigação

| Risco | Severidade | Mitigação |
|---|---|---|
| Credencial GCP no histórico do git de um repo de organização | **Alta** | Se encontrada: **revogar a chave no console GCP primeiro**, depois limpar o histórico (`git filter-repo`) e forçar o push com o time avisado. Revogar é o passo que importa; limpar o git sozinho não protege nada |
| Vazamento de dados no split passando despercebido até a apresentação | **Alta** — inviabiliza o resultado inteiro | Revisão explícita do `GroupKFold`, do split por blocos e do agrupamento entre sensores; os testes de SV-11 rodando localmente antes da entrega |
| Execução remota de código pela API (desserialização de upload) ou falha de parsing do GDAL | **Alta** | Checagem da Parte A item 7, integralmente. Nenhum item desse bloco pode ficar em aberto |
| Repo público com afirmações não qualificadas sobre empresas nomeadas | Média | Checagem da Parte A item 6 (limitações e não-causalidade em destaque) |
| Série de 13 anos apresentada sem a ressalva da troca de sensor | Média | Confirmar que a marcação da troca aparece no CSV (SV-15), no notebook 04 (SV-17) e na demo (SV-19b) |

**Kill-switch:** achado crítico bloqueia a declaração de V1 até a correção. O plano tem folga
até 07/09 para isso.

## Como reportar

Informe: achados por severidade, quais bloqueiam a V1, quais viram backlog, e uma frase de veredito:
a V1 pode ser declarada fechada, sim ou não.
