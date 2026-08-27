# Classes de cobertura do solo

Decisão fechada do time (ver `CLAUDE.md`) — este documento só descreve o que já foi decidido.
Fonte de verdade em código: `config/classes.yml` + `src/sentinela/classes.py`. Nenhum outro
módulo deve hardcodar número de classe.

## As 5 classes (+ nodata)

| id | slug | nome | cor | descrição |
|---|---|---|---|---|
| 0 | `nodata` | Sem dado | ⬛ `#000000` | Fora da AOI, mascarado por nuvem, ou código de origem sem mapeamento. |
| 1 | `vegetacao_densa` | Vegetação densa | 🟩 `#1B5E20` | Cobertura arbórea nativa ou cultivo denso — estado "antes", linha de base do território. |
| 2 | `vegetacao_rala` | Vegetação rala / pasto / agricultura leve | 🟢 `#8BC34A` | Já degradado em relação à densa, mas ainda não é obra. |
| 3 | `solo_exposto_obras` | Solo exposto / em obras | 🟧 `#C87137` | **Classe crítica** — sinal mais forte de início de construção. |
| 4 | `construida_urbana` | Área construída / urbana | 🟥 `#B03A2E` | Estado "depois" — inclui o data center e infraestrutura associada (viário entra aqui, não é classe separada). |
| 5 | `agua` | Água | 🟦 `#1565C0` | Corpos d'água permanentes. |

## ⚠️ Sobre a classe 3 (solo_exposto_obras)

A classe 3 vinda do remap do **WorldCover é solo natural exposto, não canteiro de obra**. O
WorldCover é um produto de safra fixa (~2020/2021) que classifica cobertura de solo genérica —
ele não distingue "sempre foi terra nua" de "estava vegetado e virou canteiro de obra em 2022".
Por isso existe a rotulagem manual complementar (`docs/tarefas/SV-09-kit-rotulagem-solo-exposto.md`
e `SV-10-rotulagem-manual-execucao.md`): é a única forma de capturar esse estado transitório, que
é exatamente o sinal mais importante do projeto (transição vegetação → obra → construído).

## Mapeamento ESA WorldCover v200 → nossas classes

| WorldCover | Descrição original | → Nossa classe | Observação |
|---|---|---|---|
| 10 | Tree cover | 1 `vegetacao_densa` | |
| 20 | Shrubland | 2 `vegetacao_rala` | |
| 30 | Grassland | 2 `vegetacao_rala` | |
| 40 | Cropland | 2 `vegetacao_rala` | Agricultura leve, conforme `CLAUDE.md` |
| 50 | Built-up | 4 `construida_urbana` | |
| 60 | Bare / sparse vegetation | 3 `solo_exposto_obras` | **Label fraco** — ver aviso acima |
| 70 | Snow and ice | 0 `nodata` | Não ocorre na AOI |
| 80 | Permanent water bodies | 5 `agua` | |
| 90 | Herbaceous wetland | 0 `nodata` | Ambíguo entre água e vegetação rala — descartar é mais seguro que rotular errado |
| 95 | Mangroves | 0 `nodata` | Não ocorre na AOI |
| 100 | Moss and lichen | 0 `nodata` | Não ocorre na AOI |

## Mapeamento MapBiomas Coleção 9 → nossas classes (SV-05b)

A tabela completa está em `config/classes.yml`, seção `remaps.mapbiomas`, conferida código a código
contra a legenda oficial da Coleção 9. O raciocínio completo — incluindo as decisões de julgamento
(mineração, afloramento rochoso, wetland, dendê) e por que nenhum código do MapBiomas isola
"canteiro de obras" — está em `docs/decisoes/ADR-004-fonte-de-labels.md`. **Qual fonte (WorldCover,
MapBiomas ou as duas) a V1 efetivamente usa é decisão pendente de confirmação do time em ADR-004** —
`remap(array, "mapbiomas")` já funciona em código, mas isso não implica que SV-07 deva usá-lo sem
essa confirmação.

## Adicionando uma nova fonte de remap

Edite só a seção `remaps` de `config/classes.yml`, adicionando uma nova chave com a tabela
`codigo_origem: nosso_id`. `src/sentinela/classes.py` não precisa mudar — `remap(array, "fonte")`
passa a funcionar automaticamente.
