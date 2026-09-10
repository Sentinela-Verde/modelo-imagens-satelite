"""Passo 1 — reconciliar a lista de data centers do Guilherme com os sites já validados aqui,
e diagnosticar a tabela de candidatos a controle que veio junto.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_01_reconciliar.py

Entradas (CSVs do Guilherme, `;` como separador, em ~/Downloads):
  - `datacenter_filtrado (1).csv`            — 12 data centers
  - `datacenter_expandido_6_pontos (1).csv`  — 6 candidatos a controle por data center (72 linhas)

Saídas:
  - `raw/controles-rf/reconciliacao_datacenters.csv` — id_datacenter -> site_id do repositório
  - `raw/controles-rf/diagnostico_candidatos_guilherme.csv` — os 72 candidatos, ponto a ponto
  - `raw/controles-rf/DIAGNOSTICO-TABELA-GUILHERME.md` — o documento para mandar pro Guilherme

Este passo não consome rede nem Earth Engine: é só geodésia sobre os CSVs e o
`config/sites.geojson`. Roda em segundos e é o pré-requisito honesto dos passos seguintes —
descobrir que os 12 pontos "novos" já eram sites validados muda o que precisa ser calculado.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C

# Um data center do CSV do Guilherme e um site de `config/sites.geojson` são considerados o MESMO
# lugar abaixo deste raio. Não é um chute: o maior desvio observado nos 12 pontos é 1,03 km
# (`ascenty-sumare`), e o menor desvio para um site DIFERENTE é de ordens de grandeza maior — não
# há nenhum par ambíguo na faixa entre os dois. O buffer de análise é de 5 km, então dois pontos a
# menos de 2 km compartilham a maior parte do recorte de terreno de qualquer jeito.
RAIO_MESMO_LUGAR_KM = 2.0

# Distância abaixo da qual um candidato a controle está contaminado: os buffers de 5 km do
# candidato e de um site de tratamento se sobrepõem. É o erro mais grave possível neste desenho —
# "tratamento disfarçado de controle" — e é o critério que a rodada anterior já usava
# (`raw/controles/METODOLOGIA.md`, passo 3: ">= 10 km, a soma dos dois buffers de 5 km").
DIST_MINIMA_CONTAMINACAO_KM = 10.0


def carregar_dcs_guilherme() -> pd.DataFrame:
    df = pd.read_csv(C.CSV_GUILHERME_DCS, sep=";", encoding="utf-8-sig")
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)
    return df


def carregar_candidatos_guilherme() -> pd.DataFrame:
    df = pd.read_csv(C.CSV_GUILHERME_CANDIDATOS, sep=";", encoding="utf-8-sig")
    for col in (
        "latitude_datacenter",
        "longitude_datacenter",
        "latitude_municipio",
        "longitude_municipio",
        "latitude_similar",
        "longitude_similar",
        "distancia_km",
        "ponto_latitude",
        "ponto_longitude",
    ):
        df[col] = df[col].astype(float)
    return df


def reconciliar(dcs: pd.DataFrame, sites: dict) -> pd.DataFrame:
    """Casa cada `id_datacenter` com o site validado mais próximo."""
    linhas = []
    for _, r in dcs.iterrows():
        melhor_id, melhor_d = None, float("inf")
        for site_id, p in sites.items():
            d = C.distancia_km(r["latitude"], r["longitude"], p["lat"], p["lon"])
            if d < melhor_d:
                melhor_id, melhor_d = site_id, d
        casou = melhor_d <= RAIO_MESMO_LUGAR_KM
        props = sites[melhor_id]
        linhas.append(
            {
                "id_datacenter": r["id_datacenter"],
                "nome_datacenter": r["nome_datacenter"],
                "cidade_guilherme": r["cidade"],
                "lat_guilherme": r["latitude"],
                "lon_guilherme": r["longitude"],
                "ano_operacional_guilherme": r["ano_operacional"],
                "site_id": melhor_id if casou else None,
                "distancia_ao_site_km": round(melhor_d, 3),
                "casou": casou,
                "ano_inicio_obra_repo": props.get("ano_inicio_obra") if casou else None,
                "ano_inicio_operacao_repo": props.get("ano_inicio_operacao_estimado") if casou else None,
                "municipio_repo": props.get("municipio") if casou else None,
                "uf_repo": props.get("uf") if casou else None,
            }
        )
    df = pd.DataFrame(linhas)
    n_predios = df.groupby("site_id")["id_datacenter"].transform("size")
    df["n_predios_no_campus"] = n_predios
    return df.sort_values(["site_id", "id_datacenter"]).reset_index(drop=True)


def diagnosticar_candidatos(cand: pd.DataFrame, recon: pd.DataFrame, sites: dict) -> pd.DataFrame:
    """Para cada um dos 72 candidatos: distância ao próprio DC, ao site de tratamento mais
    próximo (qualquer um dos 16, não só o dele), e o veredito de contaminação."""
    site_por_dc = recon.set_index("id_datacenter")["site_id"].to_dict()
    linhas = []
    for _, r in cand.iterrows():
        pl, pn = r["ponto_latitude"], r["ponto_longitude"]
        d_dc = C.distancia_km(pl, pn, r["latitude_datacenter"], r["longitude_datacenter"])
        prox_id, prox_d = None, float("inf")
        for site_id, p in sites.items():
            d = C.distancia_km(pl, pn, p["lat"], p["lon"])
            if d < prox_d:
                prox_id, prox_d = site_id, d
        linhas.append(
            {
                "id_datacenter": r["id_datacenter"],
                "site_id": site_por_dc.get(r["id_datacenter"]),
                "ponto_num": int(r["ponto_num"]),
                "ponto_latitude": pl,
                "ponto_longitude": pn,
                "raio_hexagono_km": r["distancia_km"],
                "dist_ao_proprio_dc_km": round(d_dc, 2),
                "site_tratamento_mais_proximo": prox_id,
                "dist_ao_tratamento_mais_proximo_km": round(prox_d, 2),
                "contaminado": prox_d < DIST_MINIMA_CONTAMINACAO_KM,
            }
        )
    return pd.DataFrame(linhas)


def _fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def gerar_documento(recon: pd.DataFrame, diag: pd.DataFrame, cand: pd.DataFrame) -> str:
    agora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    campi = sorted(recon["site_id"].dropna().unique())
    n_contaminados = int(diag["contaminado"].sum())

    # Tabela por campus
    linhas_campus = []
    for site_id in campi:
        sub = diag[diag["site_id"] == site_id]
        rec = recon[recon["site_id"] == site_id]
        mun = rec["municipio_repo"].iloc[0]
        uf = rec["uf_repo"].iloc[0]
        cont = int(sub["contaminado"].sum())
        d_min, d_max = sub["dist_ao_proprio_dc_km"].min(), sub["dist_ao_proprio_dc_km"].max()
        prox = sub["dist_ao_tratamento_mais_proximo_km"].min()
        quem = sub.loc[sub["dist_ao_tratamento_mais_proximo_km"].idxmin(), "site_tratamento_mais_proximo"]
        linhas_campus.append(
            f"| `{site_id}` | {mun}/{uf} | {len(rec)} | {_fmt(d_min)}–{_fmt(d_max)} km | "
            f"{_fmt(prox)} km (`{quem}`) | {cont}/{len(sub)} |"
        )

    # Prédios por campus
    linhas_predios = []
    for site_id in campi:
        rec = recon[recon["site_id"] == site_id]
        if len(rec) > 1:
            nomes = ", ".join(rec["nome_datacenter"].tolist())
            linhas_predios.append(f"| `{site_id}` | {len(rec)} | {nomes} |")

    doc = f"""# Por que não usamos a tabela de pontos de controle — diagnóstico numérico

**Para:** Guilherme (frente do modelo de impacto)
**De:** Gabriel (frente do classificador de imagem / `modelo-imagens-satelite`)
**Gerado em:** {agora} por `dados-modelo-impacto/scripts/impacto_dc_01_reconciliar.py`

Recebi `datacenter_filtrado.csv` (12 data centers) e `datacenter_expandido_6_pontos.csv`
(6 candidatos a controle por data center, 72 pontos). Antes de rodar o classificador em cima
deles, medi os pontos contra a lista de sites já validados deste repositório. Achei três coisas
que impedem usar a tabela como está. **Nenhuma delas é erro de digitação — são consequências do
desenho do gerador**, e por isso valem uma conversa antes de você rodar de novo.

Tudo aqui é reproduzível: rode o script acima e ele regenera este documento e os dois CSVs de
apoio a partir dos seus arquivos originais.

---

## 1. Os 12 data centers são {len(campi)} lugares, não 12

Todos os 12 estão a **no máximo {recon["distancia_ao_site_km"].max():.2f} km** de um site que este
repositório já validou (`config/sites.geojson`, validação de coordenada em 5 camadas). Não são
pontos novos — e, principalmente, **vários deles são o mesmo lugar**:

| campus | prédios na sua lista | quais |
|---|---:|---|
{chr(10).join(linhas_predios)}

Os {int(recon[recon["site_id"] == "ascenty-hortolandia"].shape[0])} prédios de Hortolândia estão a
**56–193 m** um do outro; os de Osasco, a **164 m**. O buffer de análise do classificador é de
**5 km de raio**. Nessa escala eles são o mesmo recorte de terreno: rodar o modelo nos 4 prédios de
Hortolândia produz quatro linhas praticamente idênticas, o que infla a contagem de amostras sem
adicionar informação nenhuma ao modelo de impacto.

**Consequência prática boa:** como todos já são sites validados, o `ano_inicio_obra` de cada um já
está pesquisado e conferido aqui — não precisamos ir atrás dele. Vale notar que
`ano_operacional` (o que está no seu CSV) **não é** o ano de início da obra: nos 15 sites
validados, a defasagem entre obra e operação é de 0 ano em 7 casos, 1 ano em 4 e 2 anos em 2.
Usar `ano_operacional` como se fosse o começo da obra deslocaria a janela "antes/depois" em até
2 anos, justamente na direção que borra o efeito que você quer medir.

---

## 2. Os candidatos a controle: {n_contaminados} dos 72 caem dentro do raio de influência de outro data center

Reconstruí a geometria do gerador para ter certeza de que estava lendo certo. Ele:

1. escolhe um **município "similar"** ao do data center;
2. mede a distância do data center até o centróide do **próprio** município (a coluna
   `distancia_km`);
3. monta um **hexágono de 6 pontos com esse mesmo raio** em volta do ponto de referência do
   município similar (colunas `latitude_similar`/`longitude_similar`).

A ideia por trás disso é boa — replicar "a que distância do centro urbano o empreendimento fica"
num município comparável. O problema é que **o passo 3 não checa se o lugar onde os 6 pontos caem
já tem um data center do estudo dentro**. E tem:

| campus | município | prédios | dist. dos candidatos ao próprio DC | tratamento mais próximo de um candidato | contaminados |
|---|---|---:|---|---|---:|
{chr(10).join(linhas_campus)}

(O denominador da última coluna é 6 candidatos por **prédio** — campi com mais de um prédio na sua
lista aparecem com 12 ou 24, porque a tabela repete os 6 pontos para cada `id_datacenter`.)

Os casos mais graves:

- **São João de Meriti (RJ)** → o município similar escolhido foi **Carapicuíba/SP**, a 364 km.
  Os **6 de 6** candidatos caem a **2,2–5,4 km** do `scala-tambore` (Barueri/SP), que é um data
  center do estudo. Os buffers de 5 km se sobrepõem quase inteiramente: esses pontos medem o
  entorno de um data center, não um controle.
- **Paulínia** → município similar Louveira/SP. **4 de 6** candidatos caem a **2,4–7,7 km** do
  `ascenty-vinhedo` / `ascenty-jundiai`.
- **Osasco** → o município similar escolhido foi **Jundiaí/SP**, que **hospeda** o
  `ascenty-jundiai` — um dos data centers da sua própria lista. 2 dos 6 pontos de cada prédio
  (4 das 12 linhas de Osasco) ficam a 5,3–6,0 km dele.

Um ponto de controle dentro do raio de influência de um data center é o erro mais grave possível
neste desenho: ele é tratamento disfarçado de controle, e o efeito medido encolhe na direção de
zero sem que nada no resultado indique que houve problema.

---

## 3. Os 6 candidatos de cada data center não são 6 amostras independentes

O raio do hexágono é a distância data center → centróide do município, que na sua tabela varia de
**1,76 km a 9,14 km**. Como o buffer de análise tem 5 km de raio, os buffers de candidatos
vizinhos se sobrepõem:

| raio do hexágono | exemplo | sobreposição entre buffers vizinhos |
|---|---|---|
| 9,12 km | Jundiaí | 3% |
| 5,90 km | Hortolândia | 30% |
| 4,58 km | Paulínia | 44% |
| **1,76 km** | **São João de Meriti** | **78%** |

Em São João de Meriti, escolher "o melhor dos 6" é escolher entre 6 recortes que compartilham
quase 80% da mesma área. Na prática é 1 candidato, não 6 — e o pareamento por similaridade fica
sem margem de escolha real.

---

## 4. Três candidatos ficam em outro estado, um deles em outro bioma

| data center | município similar escolhido | distância |
|---|---|---|
| Scala Porto Alegre (RS) | **Curitiba/PR** | 537–546 km |
| Scala São João de Meriti (RJ) | **Carapicuíba/SP** | 363–367 km |
| Equinix Santana de Parnaíba (SP) | **Pouso Alegre/MG** | 161–172 km |

O caso de Porto Alegre é o mais problemático: sai do **Pampa** e entra na **Mata Atlântica**. A
vegetação de base, o regime de chuva e a sazonalidade são outros — o classificador vai acusar
diferença de cobertura entre tratamento e controle que não tem nada a ver com o data center. Um
controle precisa diferir do tratamento **só** por não ter recebido o empreendimento.

---

## O que fizemos no lugar

Regeneramos os candidatos com o método que este repositório já tinha desenhado e documentado
(`docs/tarefas/SV-29-grupo-controle-pareado.md`, aplicado em
`dados-modelo-impacto/scripts/gerar_controles_pareados.py`), que resolve exatamente os quatro
pontos acima:

- **anel de 15 a 40 km** do data center — longe o bastante para sair do raio de influência do
  empreendimento, perto o bastante para manter regime de licenciamento, pressão de expansão urbana
  e regime de chuva comparáveis;
- **mesmo município ou mesma microrregião do IBGE** — o que também mantém bioma e clima, sem
  precisar cruzar meio país atrás de um município socioeconomicamente parecido;
- **checagem de contaminação explícita**: todo candidato precisa estar a ≥ 10 km (a soma dos dois
  buffers de 5 km) de qualquer site de tratamento e de qualquer controle já escolhido, e a ≥ 5 km
  de uma lista de 38 pontos de contaminação (que inclui os data centers **rejeitados** do estudo —
  são justamente lugares onde há data center e que não entraram na amostra);
- **candidatos espalhados pelo anel** (7 raios × 24 azimutes), então os candidatos de um mesmo
  site não são recortes sobrepostos um do outro.

A escolha final entre os candidatos usa a **saída do nosso classificador Random Forest** (área por
classe de cobertura do solo num buffer de 5 km, no ano anterior ao início da obra), pegando o
candidato de menor distância L1 contra o tratamento. Detalhe completo em
`dados-modelo-impacto/raw/controles-rf/METODOLOGIA.md`.

## O que ainda vale de você

- **A ideia do município socioeconomicamente similar não foi descartada** — ela é melhor que a
  nossa para as variáveis socioeconômicas (população, emprego, PIB). O que ela não serve é para
  parear **cobertura do solo**, que é o que o classificador mede. Se você quiser manter os dois
  critérios, dá para usar o município similar como estratificação e o anel geográfico como
  controle de cobertura — mas aí são dois controles com papéis diferentes, não um só.
- **Se você regerar a tabela**, os dois checks que faltam no gerador são baratos: (a) rejeitar
  candidato a menos de 10 km de qualquer data center conhecido (não só os 12 da lista); (b) exigir
  raio de hexágono ≥ 10 km, senão os 6 pontos se sobrepõem.
- **A duplicação de prédios** (`Ascenty Hortolandia HTL2/3/4/5`, `Ascenty SP3/SP4`) vale corrigir
  na origem: se o modelo de impacto tratar cada prédio como uma observação, Hortolândia entra com
  peso 4 e Porto Alegre com peso 1, sem que isso seja uma decisão de ninguém.

## Arquivos de apoio (números crus, para conferir)

- `reconciliacao_datacenters.csv` — os 12 `id_datacenter`, o site validado que cada um casou, a
  distância do casamento e o `ano_inicio_obra` que passamos a usar.
- `diagnostico_candidatos_guilherme.csv` — os 72 candidatos, ponto a ponto, com distância ao
  próprio data center, distância ao site de tratamento mais próximo e a marca de contaminação.
"""
    return doc


def main() -> int:
    print("Passo 1 — reconciliação e diagnóstico (sem rede, sem Earth Engine)")
    sites = C.carregar_sites_validados()
    dcs = carregar_dcs_guilherme()
    cand = carregar_candidatos_guilherme()
    print(f"  {len(dcs)} data centers, {len(cand)} candidatos a controle, {len(sites)} sites validados")

    recon = reconciliar(dcs, sites)
    nao_casaram = recon[~recon["casou"]]
    if len(nao_casaram):
        print(f"  ACHADO: {len(nao_casaram)} data center(s) NÃO casaram com nenhum site validado:")
        for _, r in nao_casaram.iterrows():
            print(f"    {r['id_datacenter']} {r['nome_datacenter']} (mais próximo a {r['distancia_ao_site_km']} km)")
    else:
        print(f"  todos os {len(recon)} casaram — {recon['site_id'].nunique()} campi distintos")

    diag = diagnosticar_candidatos(cand, recon, sites)
    print(f"  candidatos contaminados (< {DIST_MINIMA_CONTAMINACAO_KM:.0f} km de um tratamento): "
          f"{int(diag['contaminado'].sum())} de {len(diag)}")

    C.salvar_csv(recon, C.DIR_SAIDA / "reconciliacao_datacenters.csv")
    C.salvar_csv(diag, C.DIR_SAIDA / "diagnostico_candidatos_guilherme.csv")

    doc_path = C.DIR_SAIDA / "DIAGNOSTICO-TABELA-GUILHERME.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(gerar_documento(recon, diag, cand), encoding="utf-8")
    print(f"  -> {doc_path.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
