# SV-19b — Página de demo + ensaio da apresentação

- **Fase:** 5 — Entrega · **Data-alvo:** 12/09 · **Tamanho:** P (~2h)
- **Responsável sugerido:** `ml-engineer` (página) + **humano** (ensaio — não delegável)
- **Bloqueado por:** SV-19
- **Desbloqueia:** — (é entrega final)
- **Tem seção de risco:** não

## Contexto

SV-19 entregou a API. Esta tarefa entrega o que a banca de fato vai ver: uma página onde alguém
arrasta uma imagem e vê o mapa classificado aparecer, mais o **ensaio cronometrado** que garante que
isso funcione na hora certa, na frente das pessoas certas.

O ensaio não é formalidade. Demo ao vivo falha por motivos banais — arquivo que não estava na pasta,
porta ocupada, projetor que corta a lateral da tela, servidor que ninguém subiu. Um ensaio de 20
minutos elimina praticamente todos.

## Objetivo

Uma demonstração de 5 minutos que funciona na primeira tentativa, com plano B pronto.

## Escopo — o que fazer

1. **`src/sentinela/api/static/index.html`** — página única, servida pelo próprio FastAPI via
   `StaticFiles`. **HTML + CSS + JavaScript puro, sem framework e sem build step** (nenhum npm num
   repo de ML). Conteúdo:
   - Área de **arrastar-e-soltar** um GeoTIFF, chamando `POST /predict`.
   - Botões de **exemplo pré-carregado** por site e ano, chamando `/predict/exemplo/...` —
     é por aqui que a demo ao vivo começa; o upload manual vem depois, como bis.
   - Resultado lado a lado: **RGB original × mapa classificado**, com legenda das 5 classes usando
     as cores de `config/classes.yml` (as mesmas dos mapas de SV-14 — cor inconsistente entre a
     apresentação e o relatório confunde quem assiste).
   - Tabela de área por classe e o valor de confiança média.
   - **Gráfico da série 2013–2025** para o site selecionado, lendo `/serie/{site_id}`, com a
     **troca de sensor marcada visualmente** (linha vertical ou mudança de traço em 2019). Este é o
     gráfico que conta a história do projeto — e marcar a troca de sensor é o que o mantém honesto.
   - Rodapé com `modelo_versao`, F1 da classe 3 e uma linha de limitação
     ("classificação automática de cobertura do solo; não constitui laudo ambiental").
   - Exibir os `avisos` devolvidos pela API quando houver.

2. **Roteiro da demo** — `docs/roteiro-demo.md`, com script minuto a minuto para **5 minutos**:
   - 0:00–0:30 — o problema (data center, entorno, série temporal).
   - 0:30–2:00 — exemplo pré-carregado: Vinhedo 2015 vs. 2024, lado a lado.
   - 2:00–3:00 — o gráfico da série, com a marca da troca de sensor explicada em uma frase.
   - 3:00–4:00 — upload ao vivo de um recorte novo.
   - 4:00–5:00 — `/docs` do Swagger, mostrando que é uma API de verdade.
   - Mais: as **3 perguntas prováveis** da banca com resposta de uma linha cada — vazamento de dados
     (SV-11), troca de sensor (SV-20), e "por que não usar MapBiomas direto" (SV-05b).

3. **Plano B gravado:** um **vídeo de 2–3 minutos** da demo funcionando, salvo fora do repo (é
   pesado) e com o caminho registrado em `docs/roteiro-demo.md`. Se algo falhar ao vivo, o vídeo
   entra em 10 segundos e ninguém perde a apresentação.

4. **Script de subida em um passo:** `scripts/demo.ps1` (e `.sh`) que verifica se o modelo existe,
   sobe o uvicorn e abre o navegador na página. Quem apresenta não deve precisar lembrar de comando
   nenhum.

5. **Ensaio (humano, obrigatório):** executar a demo inteira, cronometrada, **em outra máquina** que
   não a de desenvolvimento e **com a rede desligada**. Anotar tudo que travou e corrigir.

## Fora de escopo

- Refatorar a API (SV-19).
- Slides da apresentação (fora do repo).
- Responsividade para celular — a demo roda em projetor.
- Qualquer framework de front-end.

## Critérios de aceite

- [ ] A página abre em `http://127.0.0.1:8000/` e funciona **sem internet**.
- [ ] Os botões de exemplo devolvem resultado em menos de 5 s.
- [ ] Arrastar um GeoTIFF válido funciona; arrastar um JPEG mostra a mensagem de erro da API de forma
      legível — **não um alerta com JSON cru na tela**.
- [ ] As cores das classes são idênticas às dos mapas de `reports/figures/` (mesmo `classes.yml`).
- [ ] O gráfico da série mostra 2013–2025 **com a troca de sensor marcada e legendada**.
- [ ] O rodapé traz `modelo_versao`, F1 da classe 3 e a linha de limitação.
- [ ] `docs/roteiro-demo.md` existe, com o script de 5 minutos e as 3 perguntas prováveis respondidas.
- [ ] O vídeo de plano B existe e o caminho está registrado.
- [ ] `scripts/demo.ps1` sobe tudo em um comando.
- [ ] **Ensaio feito em outra máquina, com rede desligada, cronometrado em ≤ 5 min**, com o relato do
      que travou e a correção aplicada. Sem isso, a tarefa não fecha.
- [ ] Legibilidade em projetor: fonte e contraste conferidos a ~2 m de distância da tela.

## Cenários de teste

1. **Máquina limpa:** clonar, seguir o README, rodar `scripts/demo.ps1` → página funcionando.
2. **Modo avião:** todos os exemplos e o upload funcionam sem rede.
3. **Erro amigável:** JPEG arrastado → mensagem em português, sem stack trace.
4. **Porta ocupada:** subir com a porta 8000 já em uso → o script avisa e sugere outra porta, em vez
   de falhar com traceback (é o modo de falha mais comum em sala de aula).
5. **Consistência visual:** a cor da classe 3 na página é a mesma da matriz de confusão de SV-13.
6. **Cronômetro:** a demo completa cabe em 5 minutos, com folga para uma pergunta no meio.

## Como reportar

Informe: o que o ensaio revelou e como foi corrigido, o tempo cronometrado, a confirmação de
funcionamento offline em outra máquina, e onde está o vídeo de plano B.
