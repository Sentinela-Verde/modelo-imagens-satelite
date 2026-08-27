# SV-19 — API de inferência (FastAPI)

- **Fase:** 4 — Output e Plus · **Data-alvo:** 10/09 · **Tamanho:** M (~3h)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-14 (inferência), SV-15 (série de área por classe)
- **Desbloqueia:** SV-19b, SV-18
- **Tem seção de risco:** SIM (endpoint de upload que parseia arquivo binário não confiável)

## Contexto

Decisão do usuário (2026-08-27): além dos notebooks, scripts e model card, a entrega inclui uma
**API/demo funcional — upload de imagem → predição — para demonstração ao vivo na apresentação**.
Esta tarefa entrega a API; a página de demo e o ensaio são SV-19b.

Isso é **aditivo**: não substitui os notebooks de SV-17. Os notebooks provam o método; a API prova
que o método vira produto.

## Stack escolhida e por quê

**FastAPI + Uvicorn, rodando local, com página estática servida pelo próprio app.**

- **FastAPI** gera OpenAPI/Swagger automaticamente em `/docs`. Essa página **é**, por si só, parte do
  entregável "API" — dá para demonstrar a API ao vivo sem escrever front-end nenhum, e serve de
  documentação para a banca.
- **Pydantic** faz a validação de entrada, que aqui não é luxo: é o que impede o endpoint de aceitar
  um arquivo qualquer e devolver uma predição sem sentido.
- Uma dependência a mais no `requirements.txt`, sem build step, sem npm, sem Node num repo de ML.

**Descartadas, com motivo:**
- **Streamlit / Gradio** — ótimos para UI rápida, mas **não são uma API**: entregariam a demo e não o
  endpoint, e a metade "API" do pedido continuaria em aberto.
- **Flask** — funciona, mas sem OpenAPI automático e sem validação nativa, o que aqui custaria código.
- **Qualquer deploy em nuvem** — custo, e sobretudo **dependência de rede durante a apresentação ao
  vivo**, que é um risco desnecessário. Local é mais robusto e demonstra a mesma coisa.

## Objetivo

Um serviço local que carrega o modelo da V1 e responde a predições sobre recortes de imagem, com
documentação interativa funcionando e sem depender de internet.

## Escopo — o que fazer

1. **`src/sentinela/api/main.py`** com os endpoints:

   | Método | Rota | O que faz |
   |---|---|---|
   | `GET` | `/health` | status + `modelo_versao` carregado + `lista_features` esperada |
   | `GET` | `/sites` | sites e anos disponíveis nos exemplos embarcados |
   | `POST` | `/predict` | recebe um GeoTIFF multiespectral, devolve classificação |
   | `GET` | `/predict/exemplo/{site_id}/{ano}` | roda sobre um recorte já embarcado no repo — **a rede de segurança da demo ao vivo** |
   | `GET` | `/serie/{site_id}` | série de área por classe por ano, lida de `outputs/indicadores/area_por_classe.csv` |

2. **Resposta de `/predict` e `/predict/exemplo`** (JSON):
   `modelo_versao`, `sensor_detectado`, `resolucao_m`, `n_pixels_validos`,
   `area_por_classe` (lista com `classe_id`, `classe_nome`, `area_ha`, `pct`),
   `confianca_media`, `imagem_classificada_png` (base64), `imagem_rgb_png` (base64),
   e **`avisos`** (lista de strings) — para dizer, por exemplo, "menos de 60% dos pixels com
   confiança acima de 0.7".

3. **Validação de entrada (é o coração da tarefa, não um detalhe):**
   - Só GeoTIFF. Confirme pelos **magic bytes**, não pela extensão nem pelo `content-type`.
   - Contagem e nomes de banda compatíveis com `modelo["lista_features"]`. Se não bater,
     **HTTP 422 com mensagem dizendo exatamente quais bandas eram esperadas e quais chegaram** —
     nunca predizer "na sorte" com o que veio.
   - Limite de tamanho (**50 MB**) e de dimensão (**4000 × 4000 px**), rejeitando antes de ler.
   - Se o raster não tiver CRS, aceitar mas devolver aviso e omitir os números de área
     (sem CRS não há área confiável).
   - Detectar o sensor pela resolução do pixel e informar na resposta.

4. **Carregamento do modelo:** uma vez, no startup, a partir de caminho **local configurado**
   (`.env`). Nunca a partir do upload.

5. **`docs/api.md`** — como subir (`uvicorn sentinela.api.main:app --port 8000`), as rotas, um
   exemplo de `curl` para cada uma, e o formato de entrada esperado.

6. **`tests/test_api.py`** com `TestClient`, cobrindo os cenários abaixo.

## Fora de escopo

- Página de demo e ensaio da apresentação (SV-19b).
- Autenticação, multiusuário, banco de dados, fila.
- Deploy em nuvem, Docker, HTTPS.
- Treinar ou re-treinar qualquer coisa pela API.

## Critérios de aceite

- [ ] `uvicorn sentinela.api.main:app` sobe em **menos de 10 s** e `/health` responde com a versão do modelo.
- [ ] `/docs` (Swagger) abre e permite executar `/predict/exemplo` pelo próprio navegador.
- [ ] `/predict` com um recorte válido devolve classificação + área por classe em **menos de 5 s**.
- [ ] `/predict` com um JPEG comum, um PNG ou um GeoTIFF de 3 bandas → **HTTP 422 com mensagem
      compreensível**, nunca 500 e nunca uma predição inventada.
- [ ] `/predict/exemplo/{site}/{ano}` funciona para todos os sites, **com a máquina em modo avião**.
- [ ] `/serie/{site_id}` devolve a série completa 2013–2025 com o campo `sensor` por ponto
      (a mesma distinção de era que SV-15 exige no CSV).
- [ ] Os números de área devolvidos pela API **batem com os do CSV de SV-15** para o mesmo site/ano.
      Divergência aqui significa duas implementações do mesmo cálculo — unifique.
- [ ] `pytest tests/test_api.py` passa.
- [ ] Os recortes de exemplo embarcados somam **menos de 20 MB** no repo (são os únicos rasters que
      podem ser commitados, e apenas porque a demo depende deles; registre a exceção no `.gitignore`).

## Cenários de teste

1. **Feliz:** upload de um recorte válido → 200 com todos os campos preenchidos.
2. **Formato errado:** JPEG → 422 com mensagem sobre formato.
3. **Bandas erradas:** GeoTIFF de 3 bandas RGB → 422 listando as bandas esperadas.
4. **Grande demais:** arquivo de 80 MB → 413/422 **antes** de o servidor tentar ler o raster.
5. **Sem CRS:** GeoTIFF sem CRS → 200, com aviso e sem números de área.
6. **Offline:** desconectar a rede e rodar todos os exemplos.
7. **Consistência:** área devolvida pela API == área no CSV de SV-15, para o mesmo site/ano/sensor.
8. **Path traversal:** upload com nome `../../etc/passwd` → nada é escrito fora do diretório temporário.

## Riscos e mitigação

| Risco | Severidade | Mitigação |
|---|---|---|
| **Parsing de raster não confiável.** GDAL/rasterio tem dezenas de drivers de formato e histórico de CVEs de memória; abrir um arquivo arbitrário enviado por terceiro é superfície de ataque real | **Alta** | Restringir os drivers do GDAL apenas a `GTiff` no processo da API; validar magic bytes antes de abrir; limites de tamanho e dimensão aplicados **antes** da leitura; processar em diretório temporário isolado, com limpeza garantida |
| **Desserialização de arquivo enviado.** `joblib.load`/`pickle.load` sobre conteúdo de upload é execução remota de código, direta | **Alta** | O modelo é carregado **uma vez, no startup, de caminho local do `.env`**. Nenhuma rota aceita modelo, pickle ou joblib como entrada. Deixe isso escrito como comentário no código, para ninguém "melhorar" depois |
| Path traversal pelo nome do arquivo enviado | Média | Nunca usar o nome recebido para montar caminho; gerar nome próprio (uuid) no diretório temporário |
| Exposição acidental na rede (sem autenticação) | Média | Bind em **`127.0.0.1`** por padrão, nunca `0.0.0.0`; CORS restrito à própria origem; `docs/api.md` avisa que o serviço não tem autenticação e não deve ser exposto |
| Exaustão de recursos por upload grande ou requisição em rajada | Baixa | Limites de tamanho/dimensão, timeout por requisição, um worker |
| Vazamento de informação em erro (traceback com caminho absoluto do disco) | Baixa | Handler de exceção que devolve mensagem genérica; detalhe só no log local |

**Rollback:** a API é aditiva e não altera nenhum artefato de dados ou de modelo. Remover é apagar o
módulo e a dependência.

**Kill-switch:** é um processo local em primeiro plano — `Ctrl+C` encerra. Não há estado persistido
nem serviço em background para esquecer ligado.

## Como reportar

Informe: rotas implementadas, tempo de startup e de predição medidos, a confirmação de que os
exemplos rodam offline, a conferência de que os números batem com o CSV de SV-15, e o tamanho total
dos recortes de exemplo commitados.
