"""Passo 6 — gera `raw/controles-rf/METODOLOGIA.md` a partir dos resultados reais.

Rode com:

    python modelo-impacto/scripts/impacto_dc_06_metodologia.py

Mesmo padrão dos `METODOLOGIA.md` já existentes em `modelo-impacto/raw/*/`: o documento é
gerado pelo código, não escrito à mão, para os números do texto não descolarem dos CSVs. Rode de
novo depois de qualquer reprocessamento.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gerar_controles_pareados as G
import impacto_dc_03_gerar_controles as P3
import impacto_dc_comum as C

SAIDA = C.DIR_SAIDA / "METODOLOGIA.md"


def secao_resultado(par: pd.DataFrame) -> str:
    ok = par[par["status"] == "ok"]
    if ok.empty:
        return "Nenhum par foi gerado ainda — rode o passo 3.\n"

    dist = ok["qualidade"].value_counts().to_dict()
    linhas = [
        f"- **{len(ok)} de {len(par)}** campi com controle gerado.",
        (
            "- Distribuição de qualidade (pelo L1 do classificador): "
            + ", ".join(f"**{k}={v}**" for k, v in sorted(dist.items()))
            + "."
        ),
        f"- Distância tratamento↔controle: {ok['dist_tratamento_controle_km'].min():.1f} a "
        f"{ok['dist_tratamento_controle_km'].max():.1f} km "
        f"(mediana {ok['dist_tratamento_controle_km'].median():.1f} km).",
        (
            "- Método de vizinhança: "
            + ", ".join(f"`{k}`={v}" for k, v in ok["metodo_municipio"].value_counts().items())
            + "."
        ),
    ]

    falhas = par[par["status"] != "ok"]
    if len(falhas):
        linhas.append(f"- **{len(falhas)}** campus/campi sem controle:")
        for _, r in falhas.iterrows():
            linhas.append(f"  - `{r['site_id']}` [{r['status']}]: {r['motivo']}")

    tabela = ["", "| campus | controle | dist. | L1 (RF) | L1 (MapBiomas) | qualidade | vizinhança |",
              "|---|---|---:|---:|---:|---|---|"]
    for _, r in ok.sort_values("l1_rf").iterrows():
        tabela.append(
            f"| `{r['site_id']}` | `{r['site_id_controle']}` | {r['dist_tratamento_controle_km']:.1f} km "
            f"| {r['l1_rf']:.4f} | {r['l1_mapbiomas']:.4f} | {r['qualidade']} | {r['metodo_municipio']} |"
        )
    return "\n".join(linhas + tabela) + "\n"


def secao_concordancia(cand: pd.DataFrame) -> str:
    """Quanto o pré-ranqueamento por MapBiomas concordou com a decisão final do RF.

    É a prestação de contas do funil descrito no passo 5: se os dois critérios discordassem
    sistematicamente, o pré-filtro estaria descartando bons candidatos antes de o RF os ver.
    """
    if cand.empty:
        return "_Sem finalistas registrados._\n"
    d = cand.dropna(subset=["l1_mapbiomas", "l1_rf"])
    if len(d) < 3:
        return "_Finalistas insuficientes para medir concordância._\n"

    rho = d[["l1_mapbiomas", "l1_rf"]].corr(method="spearman").iloc[0, 1]
    por_site = d.groupby("site_id")
    n_sites = por_site.ngroups
    concordou = 0
    for _, g in por_site:
        if len(g) < 2:
            continue
        melhor_mb = g.loc[g["l1_mapbiomas"].idxmin(), "site_id_controle"]
        melhor_rf = g.loc[g["l1_rf"].idxmin(), "site_id_controle"]
        concordou += int(melhor_mb == melhor_rf)

    return (
        f"Correlação de Spearman entre `l1_mapbiomas` e `l1_rf` nos {len(d)} finalistas avaliados: "
        f"**{rho:.3f}**. Em **{concordou} de {n_sites}** campi o candidato que o MapBiomas colocaria "
        f"em primeiro é o mesmo que o classificador escolheu.\n\n"
        f"Uma correlação alta é o que justifica o funil: o pré-filtro do MapBiomas raramente joga "
        f"fora o candidato que o classificador escolheria. Onde os dois discordam, **quem decide é "
        f"o classificador** — o `l1_mapbiomas` está publicado em `candidatos_avaliados_rf.csv` só "
        f"para permitir esta conferência, nunca entra na escolha final.\n"
    )


def secao_escala(par: pd.DataFrame) -> str:
    """Compara, no MESMO controle escolhido, o L1 do classificador com o do MapBiomas.

    Existe porque os limiares `bom`/`aceitavel`/`ruim` vêm de SV-29, onde foram calibrados sobre o
    L1 do MapBiomas. Se as duas métricas correm em escalas diferentes, aplicar a mesma régua às
    duas aprova mais pares de um lado do que do outro — e a contagem "X de 15 dentro do limiar"
    deixa de ser comparável entre as rodadas.
    """
    ok = par[par["status"] == "ok"].dropna(subset=["l1_rf", "l1_mapbiomas"])
    if ok.empty:
        return "_Sem pares para comparar escala._"

    menor = int((ok["l1_rf"] < ok["l1_mapbiomas"]).sum())
    razao = (ok["l1_rf"] / ok["l1_mapbiomas"]).median()
    dentro_rf = int((ok["l1_rf"] <= 0.20).sum())
    dentro_mb = int((ok["l1_mapbiomas"] <= 0.20).sum())
    return (
        f"- Mediana de `l1_rf`: **{ok['l1_rf'].median():.4f}**; de `l1_mapbiomas` nos mesmos "
        f"controles: **{ok['l1_mapbiomas'].median():.4f}**.\n"
        f"- `l1_rf` é menor que `l1_mapbiomas` em **{menor} de {len(ok)}** pares "
        f"(razão mediana `l1_rf`/`l1_mapbiomas` = **{razao:.2f}**).\n"
        f"- Pelo limiar de 0,20: **{dentro_rf} de {len(ok)}** pares passam medindo pelo "
        f"classificador, contra **{dentro_mb} de {len(ok)}** medindo pelo MapBiomas."
    )


def secao_painel(painel: pd.DataFrame) -> str:
    if painel.empty:
        return "_Painel ainda não gerado — rode o passo 4._\n"
    por_sensor = painel.groupby("sensor")["pareado_com"].nunique().to_dict()
    anos_por_par = painel.groupby(["pareado_com", "tipo"])["ano"].nunique()
    truncados = sorted(
        painel.groupby("pareado_com")["ano"].nunique().loc[lambda s: s < 7].index.tolist()
    )
    linhas = [
        f"- **{len(painel)} linhas**: {painel['site_id'].nunique()} pontos "
        f"({painel['pareado_com'].nunique()} pares x 2) x os anos de cada janela.",
        f"- Anos cobertos: {painel['ano'].min()}–{painel['ano'].max()}.",
        (
            "- Pares por sensor: "
            + ", ".join(f"**{k}={v}**" for k, v in sorted(por_sensor.items()))
            + "."
        ),
        f"- Tratamento e controle têm sempre o mesmo número de anos: "
        f"{'sim' if anos_por_par.groupby(level=0).nunique().eq(1).all() else 'NÃO — conferir'}.",
    ]
    if truncados:
        linhas.append(
            "- Janela truncada (menos de 7 anos) em: "
            + ", ".join(f"`{s}`" for s in truncados)
            + " — reportado, não corrigido: os anos que faltam não existem na cobertura do sensor."
        )

    linhas.append(
        "- Distribuição das fases: "
        + ", ".join(f"`{k}`={v}" for k, v in painel["fase"].value_counts().items())
        + " (a fase vem de `ano_inicio_obra` e `ano_fim_obra`, este último o fim de "
        "`periodo_durante` em `config/sites.geojson`)."
    )

    # Campi em que a obra terminou tão tarde que a janela obra+3 acaba antes de existir um ano
    # pós-obra. Não é bug: é o dado dizendo que a construção durou mais que a metade da janela.
    trat = painel[painel["tipo"] == "tratamento"]
    sem_pos = []
    for site_id, g in trat.groupby("pareado_com"):
        if "pos" not in set(g["fase"]):
            sem_pos.append(
                f"`{site_id}` (obra {int(g['ano_inicio_obra'].iloc[0])}–"
                f"{int(g['ano_fim_obra'].iloc[0])}, janela até {int(g['ano'].max())})"
            )
    if sem_pos:
        linhas.append(
            "- **Sem nenhum ano `pos` no painel**: " + ", ".join(sem_pos) + ". A obra desses "
            "campi durou mais que os 3 anos posteriores ao início, então a janela termina antes de "
            "haver um ano pós-construção. Para uma leitura de efeito depois da obra, esses dois "
            "precisariam de uma janela ancorada no FIM da obra, não no início — decisão de desenho "
            "que não foi tomada aqui (o briefing ancora no início) e fica registrada como lacuna."
        )
    return "\n".join(linhas) + "\n"


def main() -> int:
    agora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    par = pd.read_csv(P3.OUT_PAREAMENTO) if P3.OUT_PAREAMENTO.exists() else pd.DataFrame()
    cand = pd.read_csv(P3.OUT_CANDIDATOS) if P3.OUT_CANDIDATOS.exists() else pd.DataFrame()
    painel_path = C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv"
    painel = pd.read_csv(painel_path) if painel_path.exists() else pd.DataFrame()

    campi = C.carregar_campi()
    linhas_janela = []
    for c in campi:
        anos = C.janela_anos(c["ano_inicio_obra"])
        s = C.sensor_da_janela(anos)
        linhas_janela.append(
            f"| `{c['site_id']}` | {c['municipio']}/{c['uf']} | {c['ano_inicio_obra']} | "
            f"{c['ano_inicio_obra'] - 1} | {min(anos)}–{max(anos)} | {len(anos)} | "
            f"{'Landsat 8/9' if s == 'landsat' else 'Sentinel-2'} |"
        )

    doc = f"""# Metodologia — grupo de controle pareado pelo classificador (frente do modelo de impacto)

Gerado por `modelo-impacto/scripts/impacto_dc_06_metodologia.py` em {agora}.
Ver `modelo-impacto/README.md` para o contexto geral desta pasta e
`DIAGNOSTICO-TABELA-GUILHERME.md` (mesma pasta) para por que a tabela de pontos de controle que
veio do Guilherme não foi usada.

## O que esta rodada é, e como difere da anterior

`raw/controles/` (2026-09-03) já tinha gerado um grupo de controle para os 16 sites, escolhendo o
par pela distribuição de classes do **MapBiomas Coleção 9**. Esta rodada refaz o pareamento com o
mesmo desenho geométrico, mas decidindo pela **saída do nosso classificador Random Forest**
(`models/rf_v1.0-tuned.joblib`), que é o que o modelo de impacto vai consumir. As duas rodadas
coexistem de propósito: são critérios diferentes, e vale poder comparar.

A geração de candidatos não foi reescrita — `impacto_dc_03_gerar_controles.py` importa
`gerar_controles_pareados.py` e chama as mesmas funções de grade, sorteio, filtros geométricos e
filtro de município.

## Escopo: {len(campi)} campi

Os 16 sites validados de `config/sites.geojson` menos `{C.SITE_SEM_ANO_OBRA}`, que não tem
`ano_inicio_obra` em nenhuma fonte — sem ano de obra não há como definir "1 ano antes" nem a janela
de 3 anos antes/depois. É a mesma lacuna que já o deixou sem controle na rodada anterior.

Os 12 `id_datacenter` da planilha do Guilherme correspondem a 8 destes campi (vários são prédios do
mesmo campus, a dezenas de metros um do outro). Os outros {len(campi) - 8} entraram porque já
estavam validados aqui e ampliam a amostra sem exigir pesquisa nova. A correspondência está em
`reconciliacao_datacenters.csv`.

| campus | município | início da obra | ano de pareamento | janela | anos | sensor |
|---|---|---:|---:|---|---:|---|
{chr(10).join(linhas_janela)}

## Passo a passo

1. **Grade de candidatos** — para cada campus, {len(G.RAIOS_GRADE_KM)} raios
   ({", ".join(str(r) for r in G.RAIOS_GRADE_KM)} km) x {len(G.AZIMUTES_GRADE_DEG)} azimutes
   (a cada 15°) = {len(G.RAIOS_GRADE_KM) * len(G.AZIMUTES_GRADE_DEG)} pontos, com geodésia WGS84
   exata (`pyproj.Geod.fwd`).

2. **Sorteio determinístico e independente por campus** —
   `numpy.random.default_rng([{C.SEED}, crc32(site_id)])` embaralha a ordem de exploração. Cada
   campus tem seu próprio gerador: a ordem de um campus não depende de quais outros foram
   processados antes, então reprocessar um subconjunto (`--sites`) dá o mesmo resultado.

3. **Filtros geométricos** (sem custo de rede):
   - distância entre {G.DIST_MIN_KM:.0f} e {G.DIST_MAX_KM:.0f} km do tratamento — longe o
     bastante para sair do raio de influência do empreendimento, perto o bastante para manter
     regime de licenciamento, pressão de expansão urbana e regime de chuva comparáveis;
   - ≥ {G.CONTAM_MIN_KM:.0f} km de todo ponto da lista de contaminação;
   - ≥ {G.NO_OVERLAP_MIN_KM:.0f} km (a soma dos dois buffers de 5 km) de qualquer site de
     tratamento ou controle já colocado nesta rodada.

4. **Filtro de município** (com rede, só nos que passaram no 3) — reverse-geocode via Nominatim.
   Aceito se o município for o mesmo do tratamento, ou se estiver na mesma **microrregião do
   IBGE**. Para quando junta {G.MIN_CANDIDATOS_MUNICIPIO_VALIDO} candidatos válidos ou após
   {G.MAX_TENTATIVAS_MUNICIPIO} tentativas.

5. **Pareamento em funil — MapBiomas ranqueia, o classificador decide.**
   - **5a. Pré-ranqueamento (MapBiomas Coleção 9).** Distância L1 entre as distribuições das 5
     classes num buffer de 5 km, no ano de pareamento (1 ano antes do início da obra, grampeado à
     janela 2013-2023 da Coleção 9). É uma consulta server-side no Earth Engine: custa uma
     chamada e nenhum download.
   - **5b. Final (classificador Random Forest).** Os **{P3.FINALISTAS_RF} melhores** passam pelo
     pipeline de verdade — ingestão do composto harmonizado, cálculo dos 7 índices, inferência com
     `rf_v1.0-tuned` — e a área por classe resultante é comparada com a do tratamento, no mesmo
     ano e no mesmo sensor. **Vence o menor L1 do classificador.**

   **Por que o funil, e o que ele custa.** Cada ponto-ano no classificador leva ~23 s (download +
   índices + inferência). Avaliar todos os ~{G.MIN_CANDIDATOS_MUNICIPIO_VALIDO} candidatos válidos
   de {len(campi)} campi seriam ~300 pontos e quase 2 h de chamadas encadeadas. O funil reduz para
   {P3.FINALISTAS_RF} x {len(campi)} = {P3.FINALISTAS_RF * len(campi)}. **O custo real assumido:**
   se o melhor candidato pelo classificador estivesse fora do top-{P3.FINALISTAS_RF} do MapBiomas,
   ele não seria avaliado. A seção "Concordância entre os dois critérios" abaixo mede o tamanho
   desse risco com os dados desta rodada.

6. **Lista de contaminação** — os 16 sites de `config/sites.geojson` mais todas as linhas de
   `config/sites_candidatos.csv`, **inclusive as rejeitadas**: são justamente lugares onde há data
   center que não entrou no estudo, e usar um deles como controle contaminaria a comparação.

7. **Painel final** (passo 4) — para cada par, área por classe em `obra-3 .. obra+3`, mais o ano de
   fim de obra quando ele cai fora dessa faixa. Tratamento e controle sempre nos mesmos anos e no
   mesmo sensor.

## A regra do sensor único — o ponto mais importante deste desenho

SV-20 (`reports/validacao_sensores.md`) mediu, nos 16 sites x 3 anos de sobreposição: em **48 de 48
pares**, o degrau 2018→2019 da classe "solo exposto/obras" (~1.253 ha em média) é **indistinguível**
do artefato de troca de instrumento (~1.263 ha). A mudança real medida no mesmo sensor
(Landsat 2018→2019) é de −9,5 ha. Uma série emendada sem cuidado atribuiria à obra um crescimento
que é, na prática, inteiramente do satélite.

Por isso a janela de cada par **nunca cruza a fronteira 2018/2019**. Para que isso fosse possível,
a ingestão Landsat foi estendida de 2021 para **2024** (passo 2) — Landsat 8/9 cobre esses anos, o
repositório simplesmente tinha parado antes. Resultado: {sum(1 for c in campi if C.sensor_da_janela(C.janela_anos(c['ano_inicio_obra'])) == 'landsat')} campi
inteiramente em Landsat e {sum(1 for c in campi if C.sensor_da_janela(C.janela_anos(c['ano_inicio_obra'])) == 's2')} inteiramente em Sentinel-2
(os de obra em 2022/2023, cuja janela inteira já está na era do Sentinel-2).

Efeito colateral registrado: os anos Landsat 2022-2024 agora existem em
`data/processed/classificado/`, então a próxima execução de `sentinela.export_indicadores`
acrescenta linhas a `outputs/indicadores/area_por_classe.csv`. Isso muda o output consumido pela
etapa de Indicadores e foi sinalizado antes de implementar, como pede o `CLAUDE.md` da raiz.

O passo 5 (`impacto_dc_05_grafico_sanidade.py`) gera, por par, uma figura com a série mono-sensor
em cima e, embaixo, a comparação contra a leitura emendada — a confirmação visual de que a janela
escolhida não está inflada pela troca de satélite.

## Limiares de qualidade — e a ressalva de que eles foram calibrados noutra métrica

`l1_rf` ≤ 0,10 → `bom` · ≤ 0,20 → `aceitavel` · acima → `ruim`. São os mesmos limiares de SV-29 e
da rodada anterior. **Pares `ruim` são reportados, não escondidos nem descartados, e nenhum limiar
foi afrouxado.**

**Mas os dois números não estão na mesma escala.** Os limiares de SV-29 foram calibrados sobre o L1
do **MapBiomas**; aqui eles são aplicados ao L1 do **classificador**, que para o mesmo par tende a
ser menor:

{secao_escala(par)}

Ou seja: contar quantos pares ficaram "dentro do limiar" nesta rodada e comparar com a contagem da
rodada anterior **não é uma comparação justa** — a mesma régua sobre uma métrica que corre mais
baixa aprova mais. Os limiares foram mantidos assim mesmo, de propósito, porque recalibrá-los
exigiria uma referência externa que não temos, e mudar a régua no meio do estudo é pior que usar
uma régua declaradamente aproximada. **Quando for comparar as duas rodadas, compare a coluna
`l1_mapbiomas` desta com a `l1_cobertura` daquela** — essas sim estão na mesma escala.

## Resultado desta rodada

{secao_resultado(par)}

## Concordância entre os dois critérios (prestação de contas do funil)

{secao_concordancia(cand)}

## Painel final

{secao_painel(painel)}

## Limitações conhecidas (documentadas, não escondidas)

- **O pré-filtro do MapBiomas pode, em princípio, descartar o melhor candidato pelo classificador**
  antes que ele seja avaliado. Medido acima; não eliminado. Eliminar exigiria rodar o classificador
  em todos os candidatos válidos (~2 h).
- **A adjacência de município usa "mesma microrregião do IBGE" como proxy de "município vizinho"**,
  não a malha poligonal oficial de fronteiras — herdado da rodada anterior, mesma ressalva.
- **A lista de contaminação usa centróide de município** para os candidatos de
  `config/sites_candidatos.csv` que nunca tiveram coordenada validada. Em municípios grandes o
  centróide pode estar longe do data center real, então a checagem de 5 km pode não pegar uma
  contaminação real fora do centro — risco residual herdado, não mitigado aqui.
- **`ascenty-maracanau` tem janela truncada** (obra 2014, precisaria de 2011-2012): a faixa_b de
  `config/params.yml` está desabilitada porque a harmonização TM→OLI nunca foi validada e o
  MapBiomas Coleção 9 começa em 2013. Ele entra com 5 anos em vez de 7.
- **`clickip-manaus` e `scala-spoapa01` têm 6 anos em vez de 7** — a obra é de 2023, e o terceiro
  ano depois (2026) ainda não existe.
- **Um controle não prova ausência de efeito.** Ele isola mudança de cobertura do solo que teria
  acontecido de qualquer jeito na mesma região; não controla nada que seja específico do terreno do
  tratamento e não da região. Vale com a mesma força a ressalva geral do
  `modelo-impacto/README.md` sobre variáveis municipais não sustentarem afirmação causal.

## Arquivos desta rodada

| arquivo | conteúdo |
|---|---|
| `reconciliacao_datacenters.csv` | os 12 `id_datacenter` do Guilherme → `site_id` deste repo |
| `diagnostico_candidatos_guilherme.csv` | os 72 candidatos dele, ponto a ponto, com a marca de contaminação |
| `DIAGNOSTICO-TABELA-GUILHERME.md` | o documento explicando por que a tabela dele não foi usada |
| `pareamento_controle_rf.csv` | **a tabela de pareamento** (1 controle por campus) |
| `candidatos_avaliados_rf.csv` | todos os finalistas, com `l1_mapbiomas` e `l1_rf` lado a lado |
| `sites_controle_rf.geojson` | os controles no schema de `config/sites.geojson` |
| `figuras/serie_*.png` | os gráficos de sanidade com o sensor marcado |
| `../../processed/painel_impacto_area_por_classe.csv` | **o painel final** consumido pelo modelo de impacto |
"""
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(doc, encoding="utf-8")
    print(f"  -> {SAIDA.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
