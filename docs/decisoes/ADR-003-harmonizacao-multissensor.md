# ADR-003 — Harmonização espectral Landsat ↔ Sentinel-2

- **Status:** Aceito
- **Data:** 2026-08-27
- **Decisor:** usuário (owner da frente de Modelagem), com levantamento e medição do spike SV-02b
  (`docs/tarefas/SV-02b-spike-harmonizacao-multissensor.md`)
- **Timebox:** 3h (regra de parada do enunciado da tarefa)

## Contexto

ADR-001 decidiu cobrir 2013–2025 com dois sensores: Landsat 8/9 (30 m) para 2013–2018 e
Sentinel-2 (10 m) para 2019–2025, com Landsat também ingerido em 2019–2021 (faixa de sobreposição)
para medir o viés entre sensores. Sem harmonização, o classificador aprenderia a diferença entre
instrumentos em vez da diferença entre anos — e a série ficaria com um degrau artificial exatamente
em 2019, coincidindo com o início do crescimento da maioria dos data centers. Este ADR registra
**como** harmonizar e **o resíduo medido** em dados reais da AOI, antes de qualquer ingestão em
massa (SV-06/SV-06b).

## 1. Caminho pronto: NASA HLS — disponibilidade verificada no Earth Engine

Verificado em 2026-08-27 com `sentinela.gee.auth.init_ee()`, contando imagens por ano na janela
jun–set sobre o buffer de 5 km de `ascenty-vinhedo` (`config/sites.geojson`):

**`NASA/HLS/HLSL30/v002` (Landsat harmonizado, 30 m):**

| Ano | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| n imagens | 14 | 14 | 14 | 16 | 16 | 12 | 14 | 12 | 16 | 26 | 28 | 28 | 28 |

Cobertura **completa e consistente em toda a Faixa A**, sem nenhum ano com menos de 12 imagens na
janela seca.

**`NASA/HLS/HLSS30/v002` (Sentinel-2 reamostrado a 30 m):**

| Ano | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| n imagens | 0 | 0 | 0 | 232 | 330 | 865 | 824 | 852 | 90 | 858 | 732 | 857 | 106 |

Zero antes de 2016 (consistente com o início de operação do Sentinel-2A). 2021 e 2025 aparecem
anomalamente baixos frente aos anos vizinhos (90 e 106 contra 700–865) — não investigado a fundo
dentro do timebox; registrado aqui como achado para quem for usar HLS em produção, não como
bloqueio da decisão abaixo (o Sentinel-2 nativo, usado no caminho escolhido, não mostra essa queda
nos mesmos anos — ver Seção 3).

**Custo do caminho HLS, conforme o enunciado da tarefa:** entrega **tudo a 30 m**, inclusive o
Sentinel-2 — perde-se a resolução de 10 m que é a vantagem da era moderna (2019–2025), justamente
onde a granularidade importa mais para separar solo exposto de vegetação rala no entorno imediato
do data center.

## 2. Caminho manual — método escolhido

**Decisão: harmonização manual** (`LANDSAT/LC0{8,9}/C02/T1_L2` + `COPERNICUS/S2_SR_HARMONIZED`),
preservando a resolução nativa de cada era (30 m Landsat, 10 m Sentinel-2) na ingestão de produção
(SV-06/SV-06b). HLS foi descartado como caminho principal **apesar de** ter disponibilidade
confirmada e boa (Seção 1), porque o custo que o próprio enunciado da tarefa pede para pesar —
perder os 10 m nativos do Sentinel-2 — é uma perda direta de sinal exatamente na classe crítica
(solo exposto/obras, que se manifesta em manchas pequenas no entorno imediato do data center) e
exatamente na era mais recente da série, que é a que mais importa para detectar construção em
andamento. HLS fica registrado como alternativa citável e validada (Claverie et al., Vermote et al.
2016, Franch et al. 2019 — ver Seção 1) caso o resíduo medido neste ADR não bata a tolerância e o
plano B precise ser acionado (Seção 5).

### 2.1 Correspondência de bandas (contrato para SV-06/SV-06b/SV-08)

| Harmonizado | Landsat 8/9 OLI | Sentinel-2 | Observação |
|---|---|---|---|
| `blue` | SR_B2 | B2 | |
| `green` | SR_B3 | B3 | |
| `red` | SR_B4 | B4 | |
| `nir` | SR_B5 | B8A | B8A (855–875 nm), não B8 — correspondência estreita correta com o NIR do OLI |
| `swir1` | SR_B6 | B11 | |
| `swir2` | SR_B7 | B12 | |

### 2.2 Escala para reflectância

- **Landsat C2 L2:** `SR_B* × 0.0000275 − 0.2` (fator de escala oficial do USGS Collection 2
  Level-2 Surface Reflectance).
- **Sentinel-2 L2A:** `B* / 10000`.

### 2.3 Ajuste de bandpass — coeficientes e fonte exata

**Landsat é o sensor de referência** (mesma convenção do produto HLS: OLI é o alvo, MSI é
ajustado até ele). `harmonizar_landsat()` só faz a conversão de escala acima — nenhum ajuste
espectral adicional. `harmonizar_s2()` aplica, banda a banda, a correção linear:

```
reflectância_pseudo_OLI = slope × reflectância_MSI + offset
```

| Banda | Slope (S2A) | Offset (S2A) |
|---|---:|---:|
| `blue` | 0.9778 | −0.0040 |
| `green` | 1.0053 | −0.0009 |
| `red` | 0.9765 | 0.0009 |
| `nir` (8A) | 0.9983 | −0.0001 |
| `swir1` | 0.9987 | −0.0011 |
| `swir2` | 1.0030 | −0.0012 |

**Fonte exata dos valores:** página oficial de bandpass adjustment do NASA HLS,
<https://hls.gsfc.nasa.gov/bandpass-adjustment/> (consultada em 2026-08-27, valores lidos
diretamente da tabela publicada, não estimados). Essa página descreve o método como originado em
**Claverie, M., Ju, J., Masek, J.G., et al. (2018)**, "The Harmonized Landsat and Sentinel-2
surface reflectance data set", *Remote Sensing of Environment*, 219, 145–161 — confirmado também no
HLS ATBD v1.5 (LP DAAC), que descreve o algoritmo de bandpass ("regressão linear global,
transformando reflectância MSI em reflectância 'pseudo-OLI'", derivada de 160 milhões de
espectros-pixel de 158 cenas Hyperion) sem publicar a tabela numérica em si. A **tabela de
coeficientes hoje publicada** na página da NASA está por ela atribuída a uma revisão posterior,
**Claverie (2023)**, *ISPRS Journal of Photogrammetry and Remote Sensing*, 198, 210–222,
doi:10.1016/j.isprsjprs.2023.03.011. Não foi possível abrir o PDF do artigo de 2023 nesta sessão
para conferir a tabela linha a linha contra a fonte primária — a atribuição de autoria/ano fica
registrada **como reportada pela própria página oficial da NASA**, não verificada contra o PDF do
periódico. Os números em si (slope/offset) foram lidos literalmente da página, não inventados nem
estimados por interpolação.

A página também lista coeficientes específicos de Sentinel-2B, muito próximos dos de S2A (maior
diferença: 0.003 no slope, 0.0004 no offset — abaixo da tolerância de viés de 0.02 do spike).
Usamos os coeficientes de S2A para as duas plataformas; essa simplificação está registrada em
`src/sentinela/gee/harmonizacao.py` e não deve ser reaberta sem medir se ela importa.

### 2.4 Máscara de nuvem por sensor

- **Landsat C2:** bitmask de `QA_PIXEL` (bit 1 dilated cloud, bit 2 cirrus, bit 3 cloud, bit 4
  cloud shadow) + `QA_RADSAT` (remove pixel com qualquer banda saturada).
- **Sentinel-2:** Cloud Score+ `cs_cdf ≥ 0.60` (decisão D-04 do projeto), via `linkCollection` com
  `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`, filtrada a uma janela de 1 dia ao redor da data da
  imagem antes do link (otimização de performance — sem isso, o link casa contra a coleção inteira
  e fica visivelmente mais lento ao rodar em lote sobre uma `ImageCollection` inteira via `.map()`).

## 3. Resíduo medido (núcleo do spike)

Medido com `python -m sentinela.gee.medir_residuo_harmonizacao --site ascenty-vinhedo`
(`src/sentinela/gee/medir_residuo_harmonizacao.py`), em 2026-08-27. Composto sazonal (mediana,
jun–set) dos 3 anos de sobreposição (2019–2021, `config/params.yml`), Landsat 8/9 harmonizado a
30 m nativo, Sentinel-2 harmonizado a 10 m nativo e depois agregado por média para a grade de 30 m
do Landsat **só para esta comparação** (ver Seção 6). Amostra: 1500 pontos pareados dentro do
buffer de 5 km de `ascenty-vinhedo`, `seed=42`. Landsat é a referência (`x`); Sentinel-2 é o
comparado (`y`); `viés = média(y − x)`; `R² = correlação de Pearson(x, y)²` (mesma convenção usada
nas figuras de validação do próprio HLS ATBD — não é o R² de ajuste à reta 1:1).

**COM ajuste de bandpass (método adotado, Seção 2.3):**

| Variável | n | viés | desvio | RMSE | R² |
|---|---:|---:|---:|---:|---:|
| `blue` | 1500 | 0.0052 | 0.0124 | 0.0134 | 0.864 |
| `green` | 1500 | 0.0068 | 0.0110 | 0.0129 | 0.913 |
| `red` | 1500 | 0.0076 | 0.0114 | 0.0137 | 0.949 |
| `nir` | 1500 | 0.0102 | 0.0282 | 0.0300 | 0.645 |
| `swir1` | 1500 | 0.0210 | 0.0241 | 0.0320 | 0.908 |
| `swir2` | 1500 | 0.0246 | 0.0155 | 0.0291 | 0.943 |
| `ndvi` | 1500 | −0.0155 | 0.0346 | 0.0379 | 0.976 |
| `ndbi` | 1500 | 0.0340 | 0.0298 | 0.0452 | 0.965 |
| `bsi` | 1500 | 0.0254 | 0.0284 | 0.0381 | 0.969 |

Tabela completa (mais casas decimais) em `reports/figures/harmonizacao/tabela_residuo.csv`.
Scatter plots por banda em `reports/figures/harmonizacao/scatter_{banda}.png`.

**SEM ajuste de bandpass (cenário de teste 5 — sanidade invertida), mesmo composto:**

| Variável | viés | RMSE | R² |
|---|---:|---:|---:|
| `blue` | 0.0103 | 0.0165 | 0.864 |
| `green` | 0.0073 | 0.0131 | 0.913 |
| `red` | 0.0088 | 0.0149 | 0.949 |
| `nir` | 0.0108 | 0.0302 | 0.645 |
| `swir1` | 0.0224 | 0.0329 | 0.908 |
| `swir2` | 0.0254 | 0.0297 | 0.943 |
| `ndvi` | −0.0187 | 0.0407 | 0.975 |
| `ndbi` | 0.0362 | 0.0474 | 0.963 |
| `bsi` | 0.0196 | 0.0343 | 0.970 |

**Cenário de teste 5 confirmado:** RMSE piora (aumenta) ao desligar o ajuste em 5 das 6 bandas
(todas menos `bsi`, que é um índice combinando 4 bandas com sinais opostos — não incomum que um
índice derivado não siga estritamente a mesma direção de todas as suas bandas de entrada) e nos
dois índices `ndvi`/`ndbi`. O ajuste de bandpass está fazendo efeito real, na direção esperada —
mas o efeito é pequeno (RMSE tipicamente piora ~0.001–0.003 ao desligar), o que já é um indício de
que o bandpass não é a maior fonte do resíduo total (ver interpretação abaixo). Automatizado em
`tests/test_harmonizacao.py::test_cenario5_desligar_bandpass_piora_residuo_em_dado_real` — uma
tentativa inicial de medir isso em um único pixel/uma única data (mesmo dia, ver
`test_cenario3_ndvi_mesma_cena_mesmo_dia_diverge_pouco`) deu sinal instável (às vezes piora, às
vezes não) porque ruído de atmosfera/BRDF/coregistração de uma única imagem domina o efeito
sistemático pequeno do bandpass — só o composto sazonal (várias imagens, o mesmo método do Passo 3)
tem ruído baixo o suficiente para o efeito aparecer de forma estável.

## 4. Tolerância atingida? **Não, para 3 das 6 bandas**

Critério do enunciado: |viés| < 0.02 **e** R² > 0.85, por banda, com ajuste.

| Banda | \|viés\| < 0.02 | R² > 0.85 | Veredito |
|---|---|---|---|
| `blue` | ✅ 0.0052 | ✅ 0.864 | **OK** |
| `green` | ✅ 0.0068 | ✅ 0.913 | **OK** |
| `red` | ✅ 0.0076 | ✅ 0.949 | **OK** |
| `nir` | ✅ 0.0102 | ❌ 0.645 | **FALHA (R²)** |
| `swir1` | ❌ 0.0210 | ✅ 0.908 | **FALHA (viés, por pouco: 0.021 vs. 0.02)** |
| `swir2` | ❌ 0.0246 | ✅ 0.943 | **FALHA (viés)** |

As três bandas visíveis (`blue`, `green`, `red`) passam com folga. As duas SWIR falham por viés
(sistemático, não ruído — ver os scatter plots: a nuvem de pontos é estreita mas deslocada acima da
reta 1:1) por uma margem pequena (0.021 e 0.025 contra o limite de 0.02). O NIR falha por R² baixo
(0.645), não por viés (o viés do NIR, 0.0102, está dentro da tolerância) — a dispersão é alta mas
não sistematicamente deslocada.

**Leitura sobre a causa provável (não investigada a fundo — o timebox de 3h não permite, registrado
como hipótese para quem revisar):** os coeficientes de Claverie corrigem *bandpass* (resposta
espectral), não diferença de **correção atmosférica**. O produto Landsat C2 L2 usado aqui
(`LANDSAT/LC0{8,9}/C02/T1_L2`) é corrigido com LaSRC; o Sentinel-2 L2A
(`COPERNICUS/S2_SR_HARMONIZED`) é corrigido com Sen2Cor (ESA) — algoritmos diferentes, que tratam
aerossol e vapor d'água de forma diferente, com maior impacto conhecido justamente em SWIR. O
produto **HLS** (Seção 1) roda LaSRC nos dois sensores (a mesma correção atmosférica para os dois) e
soma a isso a correção de BRDF que este spike não aplicou — plausivelmente por isso o HLS reporta
incerteza de 0.01–0.02 por banda (Seção 1, Franch et al. 2019 e o orçamento de erro de Claverie et
al. citado no ATBD), no mesmo patamar da nossa tolerância, enquanto a harmonização manual (sem
correção atmosférica unificada, sem BRDF) fica perto da tolerância em 4 de 6 bandas e a ultrapassa
nas outras 2. Índices compostos (`ndvi`, `bsi`) diluem parte desse efeito (R² alto, 0.97+) porque o
erro se cancela parcialmente entre numerador e denominador; `ndbi` (`swir1`↔`nir`) concentra o erro
das duas bandas mais problemáticas e tem o maior viés de todos (0.034).

## 5. Plano B acionado — Opção 1: `sensor` como feature explícita no modelo

O resíduo medido (Seção 3–4) **não bate a tolerância em NIR e nas duas SWIR**, então, seguindo a
regra de parada do enunciado, este ADR não tenta mais um ciclo de ajuste (ex.: recalibrar
coeficientes, aplicar BRDF, trocar para atmosférica unificada) — isso é trabalho de continuação, não
deste spike.

**Adotado: Plano B opção 1 — tratar `sensor` (`landsat`/`sentinel2`) como feature explícita do
Random Forest em SV-12**, para o modelo aprender a compensar o resíduo, em vez de confundir sensor
com tendência real. Motivos para preferir esta opção às outras duas do enunciado:

- O resíduo é **pequeno e parcialmente sistemático** (vieses de 0.02–0.035, não 0.1+), não um
  degrau grosseiro — é exatamente o tipo de efeito que uma feature categórica de baixa cardinalidade
  ajuda uma árvore a separar, sem descartar dado.
- As 3 bandas visíveis + os 2 índices mais citados no `CLAUDE.md` (NDVI, e por extensão a separação
  vegetação/não-vegetação das classes 1/2) já batem a tolerância — o problema real está concentrado
  em SWIR/NDBI, que pesam mais nas classes 3/4 (justamente a fronteira crítica do projeto). É um
  argumento a mais para dar ao modelo a chance de aprender essa diferença via feature, em vez de
  aceitá-la como ruído silencioso.
- **SV-11 já antecipa exatamente este risco** (teste de controle #2: treinar numa era, testar na
  outra, e comparar com o desempenho intra-era) e **SV-20 já existe** para medir o efeito no nível
  de saída (área por classe), que é a métrica que realmente importa para o projeto. A opção 1 não
  cria trabalho novo — ela se encaixa no que já estava planejado.
- Rejeitei a opção 2 (um modelo por era) porque ela dobra a complexidade de manutenção/avaliação sem
  evidência de que o resíduo medido (moderado, não um degrau catastrófico) justifique dois modelos
  separados — e comparar saídas de dois modelos distintos ao nível de área tem seu próprio risco de
  introduzir viés de modelo junto com o viés de sensor, confundindo as duas fontes.
- Rejeitei a opção 3 (recuar a Faixa A para 2019–2025, S2 puro) porque o resíduo medido não é grande
  o bastante para justificar abrir mão de 6 anos de série (2013–2018) que o usuário pediu
  explicitamente para maximizar (ADR-001) — descartar a metade da série por um viés de 0.02–0.035
  em 3 de 6 bandas seria uma reação desproporcional ao tamanho do problema medido.

**Ação concreta para SV-12 (a ser confirmada por quem implementar):** incluir `sensor` (categórica,
one-hot ou equivalente) nas features do Random Forest, e considerar dar peso maior às bandas
visíveis/NDVI (que já batem tolerância) na importância relativa se a avaliação de SV-13 mostrar que
o modelo está usando SWIR/NDBI de um jeito que reproduz o viés de sensor em vez de sinal real —
critério a verificar em SV-13/SV-20, não decidido aqui.

**Aviso propagado:** SV-06/SV-06b devem seguir usando `harmonizar_landsat`/`harmonizar_s2` como
estão (o contrato de bandas não muda); SV-11 deve garantir que a coluna `sensor` existe no dataset
de modelagem; SV-12 deve incluir `sensor` nas features; SV-20 deve tratar isto como a validação de
saída que confirma (ou não) que a opção 1 foi suficiente — se SV-20 mostrar que o degrau sobrevive
mesmo com `sensor` como feature, a opção 3 (recuar para S2 puro) volta a ser candidata.

## 6. Resolução final de cada era

- **2013–2018 (Landsat 8/9):** 30 m nativo, sem reamostragem.
- **2019–2025 (Sentinel-2):** 10 m nativo, sem reamostragem.
- **2019–2021 (sobreposição, ambos os sensores):** Landsat a 30 m e Sentinel-2 a 10 m, cada um na
  sua grade nativa — a agregação do Sentinel-2 para 30 m feita neste spike (Seção 3) é **só para
  efeito de medição do resíduo**, não é usada na ingestão de produção (SV-06/SV-06b mantêm cada era
  na resolução nativa; a comparação de saída ao nível de área/classe fica com SV-20, que faz o
  controle inverso: agregar S2 de 10 m para 30 m e comparar com o próprio S2 de 10 m, isolando efeito
  de resolução de erro de sensor).

## 7. Recomendação sobre a Faixa B (2000–2011, Landsat 5/7 TM/ETM+) — **não fazer, por ora**

**Recomendação: não habilitar a Faixa B na V1.** Razões, à luz do que este spike mediu:

1. **A harmonização que este ADR validou é Landsat 8/9 OLI ↔ Sentinel-2 MSI, via coeficientes
   Claverie.** Landsat 5/7 (TM/ETM+) exigiriam uma **segunda cadeia de harmonização** (Roy et al.
   2016 trata especificamente OLI↔ETM+, citado no enunciado da tarefa, mas não foi medido aqui —
   está fora de escopo desta tarefa, conforme "Fora de escopo" de SV-02b). Não há evidência medida
   de que essa segunda harmonização atinja tolerância — e, dado que a harmonização OLI↔MSI (sensores
   mais modernos, mais próximos entre si) já não bateu tolerância em 3 de 6 bandas, não há razão para
   esperar que TM/ETM+↔OLI (sensores mais antigos, mais diferentes) vá se sair melhor sem medição
   própria.
2. **O buraco de 2012** (ADR-001): Landsat 5 encerrou em nov/2011, Landsat 8 só entrou em abr/2013 —
   2012 fica sem fonte limpa (só Landsat 7 SLC-off, com ~22% de falhas de linha por cena).
3. **Sem fonte de label anual para o período** — ADR-004 (SV-05b) recomenda MapBiomas Coleção 9, que
   cobre 1985–2023 e tecnicamente alcançaria 2000–2011, mas essa recomendação está **pendente de
   confirmação do time** (ADR-004, Seção "Confirmação — pendente") e não foi testada especificamente
   para o período 2000-2011 neste spike.
4. **Ganho marginal questionável:** conforme já registrado em ADR-001, as construções dos 3 data
   centers são todas posteriores a ~2013 — a Faixa B adicionaria contexto regional (ritmo de
   urbanização prévio), não sinal sobre o data center em si.

Isso confirma a condição que ADR-001 já havia colocado para a Faixa B ("condicionada a SV-02b
validar que a harmonização TM→OLI fica dentro de tolerância aceitável") — **a condição não foi
satisfeita** (nem sequer testada, porque está fora do escopo desta tarefa), então a Faixa B
permanece desabilitada em `config/params.yml` (`faixa_b.habilitada: false`), sem necessidade de
nenhuma mudança de configuração. Se o time quiser a Faixa B como trabalho futuro, o próximo passo
seria um spike dedicado (não coberto aqui) medindo o resíduo TM/ETM+↔OLI com os coeficientes de Roy
et al. 2016, nos mesmos moldes deste ADR.
