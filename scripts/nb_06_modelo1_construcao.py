"""Gera `notebooks/06_modelo1_construcao.ipynb` — como o classificador foi construído.

    python modelo-impacto/scripts/nb_06_modelo1_construcao.py

O notebook 04 mostra o modelo **funcionando** (imagem entra, classe sai). Este mostra como ele
foi **feito**: de onde vêm os rótulos, como o dataset foi amostrado, por que o split não é
aleatório, e o que a avaliação em holdout diz — incluindo onde o modelo é fraco.

Não treina nada e não toca rede: lê o manifest do `dataset_v1.0`, o relatório de avaliação e o
parquet já gerados.
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

RAIZ = Path(__file__).resolve().parents[2]
DIR_NB = RAIZ / "notebooks"
MANIFEST = RAIZ / "data" / "manifests" / "dataset_v1.0.json"


def md(t: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(t.strip("\n"))


def code(t: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(t.strip("\n"))


CELULAS = [
    md("""
# Modelo 1 — construção do classificador

**O instrumento do projeto inteiro.** Ele olha um pixel de imagem de satélite e diz a que
classe de cobertura do solo ele pertence. Tudo o que o estudo de impacto afirma é contagem
sobre a saída dele.

Este notebook mostra **como ele foi feito**. Para vê-lo **funcionando**, com imagem de verdade,
use `04_demo_visual_classificador.ipynb`.
"""),
    code("""
import json
from pathlib import Path
import pandas as pd, numpy as np
import matplotlib.pyplot as plt

RAIZ = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
m = json.loads((RAIZ / "data" / "manifests" / "dataset_v1.0.json").read_text(encoding="utf-8"))

print(f"dataset  : {m['versao']}")
print(f"linhas   : {m['n_linhas']:,}")
print(f"features : {m['n_features']}")
print(f"sites    : {len(m['sites'])}   ·   anos: {min(m['anos'])}–{max(m['anos'])}")
print(f"sensores : {', '.join(m['sensores'])}")
print(f"seed     : {m['seed']}")
"""),
    md("""
## 1. As 5 classes

Fechadas pelo time em 2026-08-27 e não renegociadas depois. Infraestrutura viária como classe
separada ficou fora do V1 — entra em "construída".
"""),
    code("""
import yaml
cls = yaml.safe_load((RAIZ / "config" / "classes.yml").read_text(encoding="utf-8"))["classes"]
for cid, meta in sorted(cls.items()):
    if cid == 0:
        continue
    print(f"  {cid}  {meta['cor_hex']}  {meta['nome_exibicao']}")
"""),
    md("""
## 2. De onde vêm os rótulos — e o defeito de origem

Ninguém rotulou 3,8 milhões de pixels à mão. O rótulo automático vem do **MapBiomas Coleção 9**
(anual, 2013–2023), com o **ESA WorldCover** como verificação cruzada em 2021 — o único ano de
sobreposição real entre as duas fontes.

A decisão está no `ADR-004`, e trocou a escolha original (WorldCover puro) porque a janela do
projeto virou 2013–2025: uma safra fixa aplicada a 13 anos gerava defasagem de até 8 anos, um
erro sistemático medido em **4–6% dos pixels por site**.

> **O defeito que isso carrega, e que explica o resto do notebook:** nem o MapBiomas nem o
> WorldCover têm uma classe de **canteiro de obras**. A classe 3 é rotulada por um proxy de solo
> nu natural. Por isso a rotulagem manual complementar é obrigatória — e por isso a classe 3 é a
> mais fraca do modelo.
"""),
    code("""
print(f"fonte do rótulo: {m['fonte_label']}\\n")
lm = m.get("labels_manuais", {})
if lm:
    print("rotulagem manual complementar (SV-09/SV-10):")
    for k, v in lm.items():
        if isinstance(v, dict):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v}")
"""),
    md("""
## 3. A amostragem — e um bug que ela escondia

Amostragem estratificada por classe, com teto por classe × site × ano × sensor.

**O teto era por contagem de pixel, e isso estava errado.** Um pixel Landsat de 30 m cobre 9× a
área de um de 10 m do Sentinel-2, então o mesmo teto significava áreas muito diferentes. As
classes abundantes enchiam o teto nos dois sensores; a classe 3 **nunca** enchia no Landsat.

Resultado medido: a classe 3 era **2,8%** das linhas Landsat contra **17,6%** das S2. E como
`sensor` é feature do modelo, ele aprendeu o prior condicionado ao sensor e o reproduzia na
saída — 2,4% previsto no Landsat contra 19,3% no S2.

A correção (teto por **área**, `ADR-006 §3`) está implementada em `sentinela.dataset` e foi
aplicada no `dataset_v2.0`. O `v1.0` documentado aqui é o de produção e ainda carrega o viés.
"""),
    code("""
d = pd.DataFrame(m["distribuicao_classes"]).T
print("distribuição de classes no dataset_v1.0:")
print(d.to_string())
print()
am = m.get("amostragem", {})
for k, v in am.items():
    print(f"  {k}: {v}")
"""),
    md("""
## 4. O split — nunca aleatório por pixel

Esta é a regra mais importante do `CLAUDE.md`, e a razão é simples: pixels vizinhos são quase
idênticos. Um split aleatório coloca o vizinho do pixel de teste dentro do treino, e a métrica
vira ficção.

São **três eixos** de separação:

| eixo | regra | o que protege |
|---|---|---|
| espacial | blocos de 1 km × 1 km inteiros | autocorrelação espacial |
| AOI (holdout) | **sites inteiros** fora do treino | generalizar para área nunca vista |
| temporal | anos inteiros | vazamento por série |
"""),
    code("""
print(f"regra de split : {m['regra_split']}")
print(f"blocos         : {m['n_blocos']}")
print(f"\\nAOIs em holdout espacial (o modelo NUNCA as viu no treino):")
for a in m["aois_holdout_espacial"]:
    print(f"  · {a}")
print(f"\\nestratos que NÃO podem ser feature: {m['estratos_nao_sao_features']}")
"""),
    md("""
A última linha é a trava contra o erro clássico: **região, bioma e UF nunca entram como
feature.** Aprender geografia em vez de espectro funciona bem no teste e quebra na primeira AOI
nova.
"""),
    md("""
## 5. O modelo

Random Forest, o baseline V1 definido pelo time. As 13 features são as 6 bandas harmonizadas
entre sensores mais os 7 índices espectrais.
"""),
    code("""
print("as 13 features:")
for i, f in enumerate(m["lista_features"], 1):
    marca = "  ← índice calculado" if i > 6 else "  ← banda harmonizada"
    print(f"  {i:2d}. {f:<8}{marca}")
"""),
    md("""
**Uma variante foi testada e decidida com número.** O treino compara duas versões — com e sem
`sensor` como feature binária — e adota a melhor. No `v1.0-tuned` a variante **com sensor**
ganhou, e o relatório registrou isso como "dependência de época residual".

Depois descobrimos que boa parte dessa dependência **era o bug do teto de amostragem**: no
`v2.0`, com o teto corrigido, a diferença entre as variantes caiu para +0,0024 e o modelo passou
a adotar a versão **sem** sensor.
"""),
    md("""
## 6. A avaliação — e onde o modelo é fraco

Holdout espacial: os 3 sites que o modelo nunca viu.
"""),
    code("""
import re
rel = (RAIZ / "reports" / "avaliacao_rf_v1.0-tuned.md").read_text(encoding="utf-8")
bloco = rel.split("## (a) Holdout espacial")[1].split("![")[0]
linhas = [l for l in bloco.splitlines() if l.strip().startswith("|")]
print("\\n".join(linhas))
"""),
    md("""
**A classe 3 é a pior, e não por acaso.** F1 de 0,579 contra 0,879 da vegetação densa e 0,920 da
água. A causa está na seção 2: o rótulo dela é um proxy, porque nenhuma das fontes automáticas
tem classe de canteiro de obras.

Isso foi **confirmado depois**: o retreino com rótulos do Dynamic World — que tem uma classe
`bare` nativa — levou a classe 3 de **0,580 para 0,804**. O diagnóstico estava certo.

Esse mesmo retreino, porém, **reprovou** no critério que decide adoção (estabilidade temporal,
`ADR-006 §4`), e por isso o `rf_v1.0-tuned` continua sendo o modelo de produção. A história
completa está em `modelo-impacto/reports/relatorio-impacto.md`, seção 4.4.
"""),
    md("""
## O que este modelo é, e o que ele não é

**É** um instrumento: entra imagem, sai classe por pixel, com um mapa de confiança junto.

**Não é** um detector de data center. Ele não sabe o que é um data center, não sabe o que é
"antes" e "depois", e não sabe que existe grupo de controle. Tudo isso é o **modelo 2**
(seleção de controle) e a **análise de impacto**, que consomem a saída dele.

**Não é perfeito, e o erro está medido:** ele troca a classe de **17,5%** dos pixels entre anos
consecutivos em terrenos onde nada mudou — 2,4× mais que o Dynamic World. Essa instabilidade é a
principal limitação conhecida do trabalho, e está documentada no relatório.
"""),
]


def main() -> int:
    if not MANIFEST.exists():
        print(f"ERRO: {MANIFEST} não existe — rode `python -m sentinela.dataset` antes.",
              file=sys.stderr)
        return 1
    nb = nbf.v4.new_notebook(cells=CELULAS)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3",
                                 "language": "python"}
    DIR_NB.mkdir(parents=True, exist_ok=True)
    print(f"  executando {len(CELULAS)} células...")
    NotebookClient(nb, timeout=600, kernel_name="python3",
                   resources={"metadata": {"path": str(DIR_NB)}}).execute()
    destino = DIR_NB / "06_modelo1_construcao.ipynb"
    nbf.write(nb, destino)
    print(f"  -> {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
