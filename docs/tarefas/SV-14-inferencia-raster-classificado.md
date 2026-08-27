# SV-14 — Inferência reproduzível → raster classificado

- **Fase:** 3 — Baseline · **Data-alvo:** 07/09 · **Tamanho:** M (~2h30)
- **Responsável sugerido:** `ml-engineer`
- **Bloqueado por:** SV-12
- **Desbloqueia:** SV-15, SV-19, SV-20
- **Tem seção de risco:** não

> **Revisada em 2026-08-27**: a inferência agora roda nas **duas eras de sensor**, cada uma na sua
> resolução nativa. Consequência da série multi-sensor de SV-02.

## Contexto

Item 5 da Definition of Done da V1: **classificação reproduzível**. Até aqui o modelo só viu
tabelas amostradas; esta tarefa aplica o modelo ao raster inteiro, produzindo o mapa de classes
por site/ano — que é o que vira indicador (SV-15) e o que aparece no dashboard do grupo.

O risco silencioso desta etapa é **ordem de colunas**: o raster de features tem 17 bandas em uma
ordem; o modelo foi treinado com uma `lista_features` em uma ordem. Se elas divergirem, o modelo
prediz feliz da vida e o mapa sai completamente errado, sem erro nenhum. Por isso o joblib de
SV-12 carrega `lista_features` — **use-a para reordenar, e falhe se não bater.**

## Objetivo

`data/processed/classificado/{site_id}/{ano}.tif` para todo site × ano, determinístico e com
metadados que digam qual modelo o produziu.

## Escopo — o que fazer

1. **`src/sentinela/predict.py`**, CLI:
   `python -m sentinela.predict --modelo models/rf_v0.1.joblib --sensor <s2|landsat|all> --site <id|all> --ano <ano|all> [--force]`
   Saída em `data/processed/classificado/{sensor}/{site}/{ano}.tif`.

2. **Fluxo por site/ano/sensor:**
   - Ler `data/interim/features/{sensor}/{site}/{ano}.tif` e o manifest correspondente.
   - **Resolução nativa:** classificar 10 m na era Sentinel-2 e 30 m na era Landsat. Não reamostrar
     para uma grade comum — a comparabilidade vem da harmonização espectral e do cálculo de área
     em m², e o efeito residual de resolução é medido em SV-20.
   - **O mesmo modelo roda nas duas eras**, porque o espaço de features é harmonizado (SV-02b).
     Se o código precisar de um `if sensor ==` para funcionar, a harmonização falhou — pare e volte
     a SV-02b.
   - **Validar contrato:** os nomes de banda do manifest devem conter todos os de
     `modelo["lista_features"]`. Reordenar para a ordem do modelo. Se faltar alguma, **erro
     explícito** com a lista do que falta — nunca prosseguir com o que der.
   - Processar em **janelas** (`rasterio.windows`), não o raster inteiro em memória — 1M px × 17
     bandas em float32 é gerenciável, mas a janela deixa o código pronto para AOI maior.
   - Pixels nodata em qualquer feature → classe `0` (nodata) na saída. Não inventar predição.
   - Saída: **uint8**, valores 1–5, `nodata = 0`, mesmo CRS/`transform`/`shape` do input,
     compressão `LZW`, e **colormap** escrito no GeoTIFF via `sentinela.classes.colormap()`
     (assim abre colorido no QGIS sem configuração).

3. **Camada de probabilidade (opcional, mas recomendada):**
   `data/processed/classificado/{site}/{ano}_confianca.tif` — uint8 0–100 com a probabilidade
   máxima (`predict_proba().max(axis=1)`). Custa pouco e permite a SV-15/Indicadores marcar áreas
   de baixa confiança em vez de tratar tudo como certo.

4. **Metadados no GeoTIFF** (tags `rasterio`): `modelo_versao`, `modelo_sha256`, `dataset_versao`,
   `git_sha`, `gerado_em`, `classes` (mapeamento id→slug). Um raster que circula pelo time sem
   dizer quem o gerou é um problema esperando para acontecer.

5. **Manifest** `data/manifests/classificado_{site}_{ano}.json` (commitado) com o mesmo conjunto de
   informação + distribuição de classes preditas + `sha256`.

6. **PNG de conferência:** `reports/figures/mapa_{sensor}_{site}_{ano}.png` com o mapa colorido e
   legenda. Gere pelo menos para **2013 (Landsat) e 2025 (Sentinel-2)** de cada site — essa
   comparação lado a lado, cobrindo 13 anos, é a melhor prova visual de que o projeto funciona, e é
   a figura que vai para os slides e para a demo de SV-19b.

## Fora de escopo

- Vetorização e cálculo de área (SV-15).
- Suavização/pós-processamento (filtro de maioria, remoção de pixels isolados). É tentador e
  melhora a aparência do mapa, mas muda os números de área sem que ninguém saiba. Se for fazer,
  vira tarefa própria, com o efeito medido.
- Change detection entre anos — item Plus.

## Critérios de aceite

- [ ] Existe `{ano}.tif` classificado para todo site × ano.
- [ ] uint8, valores ⊆ {0,1,2,3,4,5}, nodata = 0, CRS/`transform`/`shape` idênticos ao input.
- [ ] Abre colorido no QGIS sem configurar nada (colormap embutido).
- [ ] Tags de metadados presentes e legíveis (`rasterio.open(...).tags()`).
- [ ] **Determinismo:** rodar duas vezes → `sha256` idêntico.
- [ ] **Contrato de features:** rodar com um raster de features com bandas fora de ordem →
      o código reordena corretamente; com uma banda faltando → erro claro, não predição silenciosa.
- [ ] Conferência visual: no mapa de 2025 de Ascenty Vinhedo, a área do data center é
      classificada como 4 (construída) ou 3 (obras), não como 1 (vegetação densa).
      **Se estiver como vegetação, há bug de ordem de banda ou de reprojeção — pare.**
- [ ] Existe raster classificado para **as duas eras**, cada uma na sua resolução nativa.
- [ ] O código não ramifica por sensor no caminho de predição.
- [ ] Nenhum `.tif` entrou no git.

## Cenários de teste

1. **Feliz:** um site/ano → tif + PNG + manifest.
2. **Determinismo:** dois runs → mesmo hash.
3. **Banda faltando:** remover uma banda do features tif → erro nomeando a banda ausente.
4. **Banda reordenada:** embaralhar a ordem das bandas → resultado **idêntico** ao original
   (prova que a reordenação por nome funciona). Este teste é o mais valioso da tarefa.
5. **Nodata:** pixel nodata no input → classe 0 no output, não 1–5.
6. **Coerência temporal:** comparar o mapa de 2013 e o de 2025 do mesmo site — a área do data center
   deve mostrar a transição esperada (vegetação/pasto → obras → construído). Isso é validação de
   domínio, não de código, e é o teste que mais importa para o valor do projeto.
7. **Continuidade entre eras:** comparar 2018 (Landsat) e 2019 (Sentinel-2) do mesmo site. Fora das
   áreas que de fato mudaram, a classificação deve ser majoritariamente a mesma. Um salto grande em
   área de mata estável indica problema de harmonização — registre e avise SV-20.

## Como reportar

Informe: distribuição de classes preditas por site/ano/sensor, o resultado do teste de banda
reordenada, a leitura visual da transição 2013→2025 em pelo menos um site (com o PNG anexado), e o
resultado do teste de continuidade 2018→2019.
