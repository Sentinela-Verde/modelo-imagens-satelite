# SV-25 — Validação de coordenadas em escala (cascata de fontes + verificação automática)

- **Fase:** 1b — Expansão · **Data-alvo:** 01/09 · **Tamanho:** G (~4h agente + ~1h de conferência humana)
- **Responsável sugerido:** `data-engineer` · conferência visual residual: **humano**
- **Bloqueado por:** SV-24 (tier 1 aprovado)
- **Desbloqueia:** SV-26
- **Tem seção de risco:** **SIM** (uma coordenada errada produz uma afirmação ambiental sobre o
  terreno errado de uma empresa real)

## Contexto

As 3 AOIs atuais foram georreferenciadas **uma a uma no Google Maps**: buscar o endereço, confirmar
visualmente que o ponto cai sobre a instalação, colar a URL em `fonte_coordenada`. Funciona para 3.
Para ~28, são horas de trabalho humano gastas em algo que não exige julgamento na maioria dos casos —
e o tempo humano é o recurso escasso do projeto (ver §2 do plano de execução).

A saída é inverter o processo: **resolver por fonte primária o que der, e reservar o olho humano para
o resíduo e para o que falhar na verificação automática.** Da lista de 30, nenhuma linha tem
coordenada; da lista de 20, quatro têm — e duas delas vêm do PeeringDB, que é exatamente a fonte
primária que esta tarefa vai consultar em lote.

**Por que isso é uma tarefa com seção de risco:** todo output do projeto — "o data center X perdeu N
hectares de vegetação" — é uma afirmação sobre uma empresa real, ancorada nesta coordenada. Um ponto
5 km deslocado não gera erro nenhum no pipeline: gera um relatório perfeitamente formatado sobre o
terreno do vizinho. Nada a jusante detecta isso. **Só esta tarefa detecta.**

## Objetivo

`config/sites.geojson` expandido para todas as AOIs elegíveis, cada uma com coordenada, fonte
rastreável e **grau de precisão declarado**, tendo passado por uma verificação automática de
plausibilidade e — quando necessário — por conferência visual humana.

## Escopo — o que fazer

1. **Cascata de fontes**, nesta ordem. Pare na primeira que resolver e **registre qual foi**.

   | Nível | Fonte | Como | `precisao_coordenada` |
   |---|---|---|---|
   | **A** | **PeeringDB** | `GET https://www.peeringdb.com/api/fac?country=BR` (leitura pública, sem chave). Baixe **uma vez**, cacheie em `data/externo/peeringdb_fac_br.json`, e case por nome/operador/cidade. Retorna `latitude`, `longitude`, `address1`, `city`, `name` | `exata` |
   | **B** | **OpenStreetMap / Overpass** | Overpass API na UF: `nwr["telecom"="data_center"]`, `nwr["building"="data_center"]`, `nwr["office"="telecommunication"]`. Devolve **polígono** em muitos casos, não só ponto — melhor que A quando existe | `exata` (+ `tem_poligono: true`) |
   | **C** | **Página do operador / release** | Endereço textual da URL já registrada em `fontes_url` (SV-24) → geocodificação (Nominatim, respeitando 1 req/s e `User-Agent` identificado) | `aproximada` |
   | **D** | **Conferência visual humana** | Só o que sobrou de A–C, **e todo caso reprovado na verificação do passo 3** | `exata` ou `inferida` |

   Ordem A antes de B de propósito: PeeringDB é preenchido pelo próprio operador para fins de
   interconexão, é a fonte com menos incentivo a estar errada, e resolve em uma requisição a maior
   parte dos casos de colocation comercial (Equinix, Scala, Ascenty, Cirion, Elea, Tecto).

2. **Sempre grave a proveniência**, mesmo quando A resolve: `fonte_coordenada` (URL ou endpoint +
   id do registro), `metodo_coordenada` (`peeringdb`|`osm`|`geocode`|`manual`),
   `precisao_coordenada` (`exata`|`aproximada`|`inferida`), `data_consulta` (ISO).
   Sem isso a coordenada é um número sem defesa, e a defensibilidade é metade do valor do trabalho.

3. **Verificação automática de plausibilidade — o coração da tarefa.** É o que substitui "olhar 28
   mapas" por "olhar os 4 que falharam". Para cada coordenada candidata, sem intervenção humana:

   - **(V1) Caixa do Brasil:** `lat` em [-34, 6], `lon` em [-74, -34]. Pega troca de lat/lon e sinal
     invertido, que é o erro de digitação mais comum e o mais silencioso.
   - **(V2) Coerência município/UF:** o ponto cai dentro do polígono do município declarado
     (malha municipal do IBGE, ou reverse-geocode). **Falhou = candidata rejeitada, vai para o nível D.**
   - **(V3) Contexto de cobertura (o teste que realmente importa):** amostre o raster de label
     MapBiomas do ano mais recente disponível num raio de **500 m** em volta do ponto. Um data center
     está sobre área construída ou sobre canteiro. Aprova se a soma de
     `construida_urbana + solo_exposto_obras` **≥ 30%** dos pixels válidos.
     **Reprova e manda para o nível D** se o entorno for predominantemente `vegetacao_densa` ou `agua` —
     um ponto no meio de mata fechada ou de um rio é coordenada errada, não data center.
     *Exceção declarada:* AOIs cuja obra ainda não começou (`status: não iniciada`) legitimamente
     caem sobre vegetação. Para essas, **V3 não se aplica** — marque `v3_nao_aplicavel: true` com o
     motivo, e mande para o nível D de qualquer forma, porque são justamente as de coordenada mais frágil.
   - **(V4) Colisão de AOI:** nenhum par de AOIs a menos de **5 km**. Colisão = as duas fusões
     provisórias de SV-24 estavam certas e as AOIs devem ser fundidas; ou uma das duas coordenadas
     está errada. **Decida caso a caso e registre** — não funda automaticamente.
   - **(V5) Distância à coordenada da lista:** onde a lista de 20 já tinha coordenada, a distância
     entre ela e a resolvida deve ser < 2 km; acima disso, é discordância entre fontes e vai para D.

4. **Fila de conferência visual (nível D).** Gere `reports/figures/coordenadas/{aoi_id}.png`: recorte
   do composto Sentinel-2 mais recente disponível, ~2 × 2 km, com o ponto e o buffer de 5 km
   desenhados. Uma imagem por AOI da fila, numerada, e um `docs/fila-conferencia-coordenadas.md` com
   uma linha por AOI: nome, município, endereço da fonte, motivo de estar na fila, e um checkbox.
   **Meta: a fila tem no máximo 8 AOIs.** Se tiver mais, a cascata A–C foi mal explorada — volte a ela
   antes de gastar tempo humano.

5. **Escrever `config/sites.geojson`** no **mesmo schema já em uso** (não invente campos novos onde já
   existe um), acrescentando os campos de proveniência e de expansão:
   existentes → `site_id`, `nome`, `operador`, `municipio`, `uf`, `lat`, `lon`, `buffer_km`,
   `fonte_coordenada`, `ano_inicio_operacao_estimado`, `ativo`;
   novos → `tier` (1|2), `regiao`, `bioma`, `metodo_coordenada`, `precisao_coordenada`,
   `data_consulta`, `ano_inicio_obra`, `periodo_pre`, `periodo_durante`, `periodo_pos`, `n_predios`.
   `buffer_km` continua **5** para todas (ADR-001) — mudar o buffer agora invalidaria os 3 sites já
   ingeridos e a grade de blocos de 1 km de SV-11.

   **`ativo` é o interruptor de escopo.** AOIs elegíveis mas não selecionadas ficam no arquivo com
   `ativo: false` — o pipeline as ignora, e reativar uma delas é editar um booleano, não refazer a tarefa.

6. **`tests/test_sites.py`:** as verificações V1, V2, V4 e o schema viram teste automatizado, rodando
   sobre `config/sites.geojson`. A partir daqui, qualquer AOI adicionada ao projeto passa pelo mesmo
   crivo sem ninguém precisar lembrar.

## Fora de escopo

- Ingerir imagem (SV-26). A verificação V3 usa **só** o raster de label do MapBiomas num raio de 500 m,
  que é barato; não baixe a série inteira para validar um ponto.
- Desenhar o polígono do empreendimento à mão. Se o OSM deu polígono, guarde-o em
  `data/externo/footprints_osm.geojson`; senão, ponto + buffer basta para a V1.
- Corrigir os anos de construção/operação (isso é SV-24).
- Coletar MW, área do terreno, investimento — não é deste repositório (SV-28).

## Seção de risco

| Risco | Por que importa | Mitigação |
|---|---|---|
| **Coordenada 5 km deslocada** | Não gera erro nenhum. Gera um relatório impecável sobre o terreno errado, com o nome de uma empresa real em cima | V2 + V3 + V5 automáticas; fila visual para todo reprovado; `precisao_coordenada` propagado até o output de SV-15 |
| **Geocode "resolve" um endereço aproximado no centro do município** | O nível C é o mais frágil e o mais silencioso: sempre devolve um ponto | Todo resultado de nível C nasce `precisao: aproximada`, **passa obrigatoriamente por V3**, e vai para a fila visual se V3 reprovar |
| **Confundir o data center com o vizinho no mesmo polo industrial** | Em Hortolândia/Sumaré há vários operadores no mesmo distrito | Buffer de 5 km torna a distinção pouco relevante para o resultado agregado — **mas registre a ambiguidade em `observacao`** e não afirme precisão que não existe |
| **Publicar coordenada de instalação com restrição de divulgação** | Nem todo operador divulga endereço exato | Só use fonte pública (PeeringDB, OSM, página do próprio operador, release). **Não infira por imagem** o que a empresa não publicou, e cite a fonte em todo output |
| **Site "não iniciado" validado como se existisse** | Scala AI City, RT-One, ByteDance ainda não têm obra visível | `v3_nao_aplicavel` explícito + conferência humana obrigatória + `precisao: inferida`. **Não são casos de pré/durante/pós completo** e SV-30 precisa saber disso |

**Kill-switch:** se ao fim do timebox a fila visual tiver mais de 8 AOIs, **não estenda a tarefa**.
Reduza o escopo: mantenha ativas apenas as AOIs de precisão `exata` + as de tier 1 conferidas, marque
o resto `ativo: false`, e siga. Um estudo com 18 AOIs bem georreferenciadas vale mais que um com 28
das quais 10 são chute.

## Critérios de aceite

- [ ] `config/sites.geojson` tem uma feature por AOI ativa, e **as 3 originais estão inalteradas**
      em `site_id`, `lat`, `lon` e `buffer_km` (conferir por diff — mexer nelas invalida `data/`).
- [ ] Toda feature tem `metodo_coordenada`, `precisao_coordenada`, `fonte_coordenada` e `data_consulta`
      preenchidos. Nenhum `null` nesses quatro.
- [ ] **Nenhuma AOI ativa com `precisao_coordenada: aproximada` que não tenha passado por V3.**
- [ ] V1, V2 e V4 passam para 100% das AOIs ativas (teste automatizado bloqueante).
- [ ] V3 passa, ou está justificada como `v3_nao_aplicavel` **e** conferida visualmente.
- [ ] `docs/fila-conferencia-coordenadas.md` existe com todos os itens marcados como conferidos, ou
      com a AOI correspondente marcada `ativo: false`.
- [ ] `data/externo/peeringdb_fac_br.json` está cacheado e commitado — reproduzir a tarefa não pode
      depender de a API estar no ar no dia da apresentação.
- [ ] `tests/test_sites.py` roda verde.
- [ ] Contagem final por tier e por `precisao_coordenada` está reportada.

## Cenários de teste

1. `geopandas.read_file('config/sites.geojson')` carrega; CRS EPSG:4326; todas as geometrias são `Point`.
2. Rodar a validação com uma coordenada propositalmente trocada (lat↔lon de Vinhedo) → V1 ou V2 reprova.
3. Rodar com uma coordenada deslocada 8 km para dentro de área de mata → **V3 reprova** e a AOI entra
   na fila visual. *Se V3 aprovar, a verificação não está funcionando e o resto da tarefa é decorativo.*
4. Duplicar uma AOI com deslocamento de 1 km → V4 acusa colisão.
5. Rodar duas vezes sem rede, com o cache do PeeringDB → mesmo resultado (idempotência offline).
6. Conferência cruzada: para `ascenty-vinhedo`, o método A/B deve cair a < 1 km da coordenada já
   registrada manualmente. **Se cair longe, a cascata está com casamento de nome errado** — corrija
   antes de confiar nas outras 25.

## Como reportar

Informe: nº de AOIs resolvidas por nível (A/B/C/D), a tabela `aoi_id | método | precisão | V1..V5`,
quantas entraram na fila visual e por quê, quantas colisões V4 e como cada uma foi decidida, quantas
AOIs terminaram `ativo: false` e o motivo, e a contagem final `tier 1 / tier 2 / inativas`.
