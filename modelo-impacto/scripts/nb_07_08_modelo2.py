"""Gera `notebooks/07_modelo2_construcao.ipynb` e `notebooks/08_modelo2_demo.ipynb`.

    python modelo-impacto/scripts/nb_07_08_modelo2.py

**Modelo 2 = seleção do grupo de controle.** É o que torna o estudo de impacto uma
comparação e não uma observação: sem um terreno equivalente para comparar, "o entorno do data
center construiu 2,6%" não significa nada — a região inteira podia estar crescendo.

Dois notebooks, como combinado com o grupo:

- **07 — construção:** o desenho. A grade de candidatos, os filtros, o funil em dois estágios
  e por que a escolha final é do classificador, não do MapBiomas.
- **08 — demo:** um campus real, os 5 finalistas lado a lado, e qual ganhou.

Não toca rede: lê `candidatos_avaliados_rf.csv` e `pareamento_controle_rf.csv`, já gerados pelo
passo 3 (`impacto_dc_03_gerar_controles.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

RAIZ = Path(__file__).resolve().parents[2]
DIR_NB = RAIZ / "notebooks"
DADOS = RAIZ / "modelo-impacto" / "raw" / "controles-rf"


def md(t: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(t.strip("\n"))


def code(t: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(t.strip("\n"))


PRELUDIO = """
from pathlib import Path
import pandas as pd, numpy as np
import matplotlib.pyplot as plt

RAIZ = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
DADOS = RAIZ / "modelo-impacto" / "raw" / "controles-rf"

cand = pd.read_csv(DADOS / "candidatos_avaliados_rf.csv")
par  = pd.read_csv(DADOS / "pareamento_controle_rf.csv")
print(f"{cand.site_id.nunique()} campi · {len(cand)} finalistas avaliados · {len(par)} pares fechados")
"""

# ==================================================================== construção
CELULAS_CONSTRUCAO = [
    md("""
# Modelo 2 — seleção do grupo de controle

**O que ele resolve.** O estudo de impacto afirma que o entorno de um data center converteu
mais. Mais **que o quê**? Sem um terreno de comparação, o número não significa nada — a região
inteira podia estar urbanizando.

Este modelo escolhe, para cada data center, **um terreno equivalente que não recebeu obra**.
Tudo que o estudo afirma é a diferença entre os dois.

> Se este modelo escolher mal, todo o resto do trabalho desaba junto. É a peça mais
> silenciosa e uma das mais críticas.
"""),
    code(PRELUDIO),
    md("""
## 1. De onde saem os candidatos

Não é busca livre. Para cada data center, uma **grade determinística**:

| | |
|---|---|
| raios | 15, 19, 23, 27, 31, 35, 40 km |
| azimutes | 24 (de 15 em 15 graus) |
| **candidatos por campus** | **168** |

O anel de 15–40 km é uma decisão de desenho com dois lados. **Perto demais** e o controle cai
dentro da própria área de influência do data center — deixaria de ser controle. **Longe demais**
e ele deixa de compartilhar o contexto regional: clima, relevo, dinâmica econômica, pressão
urbana. O anel é o compromisso.
"""),
    md("""
## 2. Os filtros — o que elimina um candidato

Aplicados em ordem, do mais barato ao mais caro:

**Geométricos** (grátis, eliminam a maioria)
- não pode sobrepor o buffer de 5 km do próprio data center
- não pode cair perto de **outro** data center conhecido — um controle contaminado é pior que
  nenhum controle
- não pode cair em água ou fora da área com imagem

**Administrativo** (rede — Nominatim + IBGE)
- mesmo município, ou município vizinho da **mesma microrregião do IBGE**

Este último existe para controlar confundidor não observável: dois pontos no mesmo município
compartilham prefeitura, plano diretor, zoneamento e ciclo econômico. É a variável que não dá
para medir por satélite e que mais explicaria crescimento diferente.
"""),
    md("""
## 3. O funil em dois estágios, e por que ele existe

Aqui está a decisão de engenharia que define o modelo.

O critério **certo** de semelhança é a saída do nosso próprio classificador: dois terrenos são
parecidos se o modelo vê as mesmas classes neles. Mas isso custa caro — cada candidato exige
baixar 6 bandas, calcular 7 índices e rodar o RF: **~23 s por ponto-ano**. Com ~20 candidatos
válidos por campus × 15 campi, seriam ~300 pontos e quase **2 horas** de rede encadeada.

A solução é um funil:

| estágio | critério | custo | o que decide |
|---|---|---|---|
| 1 | distância L1 da distribuição de classes do **MapBiomas** | grátis (consulta server-side) | quem entra na final |
| 2 | distância L1 da saída do **`rf_v1.0-tuned`** | ~23 s/ponto | **o vencedor** |

Só os **5 melhores** do estágio 1 passam pelo estágio 2.

**O custo dessa escolha, declarado:** se o melhor candidato pelo RF estivesse fora do top-5 do
MapBiomas, ele nunca seria avaliado. As duas medidas são correlacionadas — medem a mesma
cobertura, no mesmo buffer, no mesmo ano — mas não são a mesma coisa. Por isso o CSV publica
**os dois L1 lado a lado** de todos os finalistas: dá para conferir o quanto os critérios
concordam, em vez de confiar que concordam.
"""),
    code("""
concordancia = cand.groupby("site_id").apply(
    lambda g: g.sort_values("l1_mapbiomas").iloc[0]["site_id_controle"]
              == g.sort_values("l1_rf").iloc[0]["site_id_controle"],
    include_groups=False,
)
n_igual = int(concordancia.sum())
print(f"Em {n_igual} de {len(concordancia)} campi, MapBiomas e RF elegeriam o MESMO controle.")
print(f"Nos outros {len(concordancia) - n_igual}, o pré-ranqueamento teria escolhido diferente —")
print("é exatamente por isso que a decisão final é do RF.")

fig, ax = plt.subplots(figsize=(6.4, 6))
ax.scatter(cand.l1_mapbiomas, cand.l1_rf, s=46, alpha=.75,
           c=np.where(cand.escolhido, "#B03A2E", "#8FA396"),
           edgecolors="white", linewidths=.8)
lim = [0, max(cand.l1_mapbiomas.max(), cand.l1_rf.max()) * 1.05]
ax.plot(lim, lim, ls="--", c="#999", lw=1, label="concordância perfeita")
ax.set_xlabel("L1 pelo MapBiomas  (estágio 1 — quem entra na final)")
ax.set_ylabel("L1 pelo rf_v1.0-tuned  (estágio 2 — quem vence)")
ax.set_title("Os dois critérios não são o mesmo critério", fontsize=11)
ax.scatter([], [], c="#B03A2E", label="escolhido", s=46)
ax.scatter([], [], c="#8FA396", label="finalista não escolhido", s=46)
ax.legend(fontsize=8); ax.grid(alpha=.25)
plt.tight_layout(); plt.show()
"""),
    md("""
## 4. A escala de qualidade, e o que ela admite

O L1 varia de 0 (distribuições idênticas) a 2 (sem sobreposição nenhuma).

| selo | L1 |
|---|---|
| `bom` | ≤ 0,10 |
| `aceitavel` | ≤ 0,20 |
| `ruim` | > 0,20 |
"""),
    code("""
q = par.qualidade.value_counts().reindex(["bom", "aceitavel", "ruim"]).fillna(0).astype(int)
print(q.to_string())
print(f"\\nL1 mediano dos pares fechados: {par.l1_rf.median():.3f}")
"""),
    md("""
**A maioria dos pares é `ruim`, e isso está reportado, não escondido.**

O motivo é estrutural: data center brasileiro fica em tecido urbano heterogêneo — a
caracterização de 612 campi (notebook 05) mostra que o entorno mediano é **85,5% construído**.
Achar um terreno a 15–40 km com a mesma composição é difícil por natureza.

O que sustenta o estudo apesar disso não é a qualidade do pareamento individual — é o
**placebo**: a mesma estatística, aplicada a 15 pares controle-contra-controle, dá 8/15
(p=0,50). Se pares `ruim` fabricassem sinal, o placebo teria achado algo. Não achou.
"""),
    md("""
## O que este modelo NÃO faz

- **Não afirma que o controle é idêntico.** Afirma que é o mais parecido que a grade encontrou,
  e publica o quanto ele é parecido.
- **Não controla o que não é visível por satélite** além do filtro de município — incentivo
  fiscal, chegada de rodovia, loteamento aprovado.
- **Não garante sucesso.** Na expansão da amostra, 4 de 10 campi ficaram `sem_candidato`:
  sítios urbanos densos onde o anel de 15–40 km cai em outro município ou perto de outro data
  center. Falhar é o filtro funcionando.
"""),
]

# ==================================================================== demo
CELULAS_DEMO = [
    md("""
# Modelo 2 — demonstração

**Um data center, 168 candidatos, 5 finalistas, 1 escolhido.** Este notebook percorre o funil
inteiro num caso real.

O desenho e as decisões estão em `07_modelo2_construcao.ipynb`.
"""),
    code(PRELUDIO),
    code("""
CAMPUS = "ascenty-vinhedo"   # troque por qualquer site_id da lista abaixo
print("campi disponíveis:", ", ".join(sorted(cand.site_id.unique())))
"""),
    md("## 1. O funil, em números"),
    code("""
g = cand[cand.site_id == CAMPUS].sort_values("posicao_final_rf")
alvo = par[par.site_id == CAMPUS].iloc[0]

print(f"data center : {CAMPUS}  ({alvo.municipio}/{alvo.uf})")
print(f"coordenada  : {alvo.lat:.4f}, {alvo.lon:.4f}")
print(f"ano da obra : {int(alvo.ano_inicio_obra)}\\n")
print(f"{'grade de candidatos':<44}{7 * 24:>6}")
print(f"{'sobreviveram aos filtros':<44}{int(alvo.n_candidatos_validos):>6}")
print(f"{'avaliados pelo classificador (finalistas)':<44}{len(g):>6}")
print(f"{'escolhido':<44}{1:>6}")
"""),
    md("## 2. Os 5 finalistas, lado a lado"),
    code("""
cols = ["site_id_controle", "dist_ao_tratamento_km", "municipio",
        "l1_mapbiomas", "l1_rf", "qualidade_rf", "escolhido"]
print(g[cols].to_string(index=False))
"""),
    code("""
fig, ax = plt.subplots(figsize=(8.4, 3.6))
y = np.arange(len(g))[::-1]
cores = np.where(g.escolhido, "#B03A2E", "#8FA396")
ax.barh(y, g.l1_rf, color=cores, height=.62)
ax.barh(y, g.l1_mapbiomas, color="none", edgecolor="#3A4A40", height=.62, ls="--", lw=1.1)
for yi, (_, r) in zip(y, g.iterrows()):
    marca = "  ← escolhido" if r.escolhido else ""
    ax.text(r.l1_rf + .012, yi, f"{r.l1_rf:.3f}{marca}", va="center", fontsize=9)
ax.set_yticks(y); ax.set_yticklabels(g.site_id_controle, fontsize=9)
ax.set_xlabel("distância L1 — barra cheia: classificador (decide) · contorno: MapBiomas (pré-rank)")
ax.set_title(f"{CAMPUS}: os 5 finalistas", fontsize=11)
ax.set_xlim(0, g[["l1_rf", "l1_mapbiomas"]].to_numpy().max() * 1.28)
ax.grid(axis="x", alpha=.25)
plt.tight_layout(); plt.show()
"""),
    md("""
Repare que o **contorno tracejado** (MapBiomas) e a **barra cheia** (classificador) não
ordenam igual. O pré-ranqueamento serve só para cortar o custo — quem decide é o classificador.
"""),
    md("## 3. Onde eles estão no mapa"),
    code("""
fig, ax = plt.subplots(figsize=(7.4, 7))
for raio in (15, 40):
    a = np.linspace(0, 2 * np.pi, 200)
    dlat = raio / 111.0
    dlon = raio / (111.0 * np.cos(np.radians(alvo.lat)))
    ax.plot(alvo.lon + dlon * np.cos(a), alvo.lat + dlat * np.sin(a),
            c="#C2CFBC", lw=1.1, ls="--", zorder=1)

ax.scatter(g.lon, g.lat, s=110, c=np.where(g.escolhido, "#B03A2E", "#8FA396"),
           edgecolors="white", linewidths=1.4, zorder=3)
for _, r in g.iterrows():
    ax.annotate(f"{int(r.posicao_final_rf)}º", (r.lon, r.lat), fontsize=8,
                xytext=(7, 5), textcoords="offset points")
ax.scatter([alvo.lon], [alvo.lat], marker="*", s=430, c="#1B5E20",
           edgecolors="white", linewidths=1.4, zorder=4, label="data center")
ax.scatter([], [], c="#B03A2E", s=110, label="controle escolhido")
ax.scatter([], [], c="#8FA396", s=110, label="finalistas")
ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
ax.set_title(f"{CAMPUS} e seus finalistas\\n(tracejado: anel de 15 e 40 km)", fontsize=11)
ax.legend(fontsize=8, loc="best"); ax.grid(alpha=.25); ax.set_aspect("equal", "datalim")
plt.tight_layout(); plt.show()
"""),
    md("""
## 4. O par que entra no estudo
"""),
    code("""
venc = g[g.escolhido].iloc[0]
print(f"  tratamento : {alvo.site_id:<32} {alvo.lat:>10.4f}, {alvo.lon:.4f}")
print(f"  controle   : {venc.site_id_controle:<32} {venc.lat:>10.4f}, {venc.lon:.4f}")
print(f"  distância  : {venc.dist_ao_tratamento_km:.0f} km")
print(f"  L1 (RF)    : {venc.l1_rf:.3f}   →  {venc.qualidade_rf}")
print(f"  município  : {venc.municipio}/{venc.uf}  ({venc.metodo_municipio})")
print()
print("É deste par que sai uma linha do achado: a conversão medida no anel do tratamento")
print("MENOS a conversão medida no mesmo anel do controle. Repetido em 20 campi, vira o")
print("teste de sinal de 18/20 (p=0,0002).")
"""),
]


def gerar(nome: str, celulas: list) -> None:
    nb = nbf.v4.new_notebook(cells=celulas)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3",
                                 "language": "python"}
    destino = DIR_NB / nome
    print(f"  executando {nome} ({len(celulas)} células)...")
    NotebookClient(nb, timeout=600, kernel_name="python3",
                   resources={"metadata": {"path": str(DIR_NB)}}).execute()
    nbf.write(nb, destino)
    print(f"  -> {destino.relative_to(RAIZ)}")


def main() -> int:
    faltando = [p.name for p in (DADOS / "candidatos_avaliados_rf.csv",
                                 DADOS / "pareamento_controle_rf.csv") if not p.exists()]
    if faltando:
        print(f"ERRO: falta {faltando} — rode `impacto_dc_03_gerar_controles.py` antes.",
              file=sys.stderr)
        return 1
    DIR_NB.mkdir(parents=True, exist_ok=True)
    gerar("07_modelo2_construcao.ipynb", CELULAS_CONSTRUCAO)
    gerar("08_modelo2_demo.ipynb", CELULAS_DEMO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
