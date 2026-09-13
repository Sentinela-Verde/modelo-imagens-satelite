"""Passo 17 — empacota os RESULTADOS numa planilha, do jeito que o painel já foi empacotado.

Rode com:

    python modelo-impacto/scripts/impacto_dc_17_planilha_resultados.py

## Por que este passo existe

`consolidado_impacto_modelo.xlsx` entrega o **painel** — cobertura, LST e socioeconômico por ponto
e por ano. É o insumo, e é o que já circulou com o time.

O problema é que o painel carrega, nas colunas `area_ha_*` / `prop_*`, exatamente a estatística que
os passos 10-11 **testaram em 6 raios e refutaram**: somar área por classe no disco não detecta a
obra (fração de pares com excesso ~0,5 em toda a faixa, cara ou coroa). Quem receber só o painel e
modelar em cima dessas colunas vai bater nessa parede — e ela já está medida aqui.

O que funciona está nas tabelas de resultado (passos 12 a 16), e elas não estavam empacotadas em
lugar nenhum. Este script junta as sete que importam num arquivo só, com dicionário de abas.

Saída:
  - `processed/consolidado_impacto_resultados.xlsx`
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

# aba -> (arquivo, o que é, como ler)
ABAS = {
    "leia_primeiro": None,
    "trajetoria_pixel": (
        "trajetoria_pixel.csv",
        "Contagem de pixels com trajetória ordenada e persistente, por ponto e raio. "
        "É a estatística que DETECTA a obra — use esta, não área agregada.",
    ),
    "trajetoria_resumo": (
        "trajetoria_pixel_resumo.csv",
        "Teste de sinal por raio e assinatura. virou_construida a 0,5 e 1 km: 13/15, p=0,0037.",
    ),
    "footprint_vs_anel": (
        "footprint_vs_anel.csv",
        "Conversão por zona (footprint, 0-0,5 km, 0,5-1 km, 1-2 km) por ponto. "
        "Mostra que o excesso está no ENTORNO, não no prédio.",
    ),
    "anel_resumo": (
        "footprint_vs_anel_resumo.csv",
        "Teste de sinal por zona. 0-0,5 km: 12/14, p=0,0065, excesso mediano +2,06 p.p. "
        "ATENCAO: essa zona e um DISCO e inclui o predio do data center. Descontando o "
        "footprint o excesso cai para +1,50 p.p., com os mesmos 12/14 e o mesmo p — e e esse "
        "o numero que deve ser citado. Some em 1-2 km (8/14, p=0,395).",
    ),
    "greenfield_brownfield": (
        "greenfield_brownfield.csv",
        "excesso_pp por par e zona, com pct_ja_construida e tipo de sítio. "
        "Greenfield: 6/6 positivos, p=0,016. É a feature mais forte que existe nesta frente.",
    ),
    "footprints_osm": (
        "footprints_osm.csv",
        "Footprint real de cada campus no OpenStreetMap. 14/15 campi, área mediana 1,29 ha.",
    ),
    "lst_did": (
        "lst_did.csv",
        "Diferença-em-diferenças de temperatura de superfície, por par (passo 16).",
    ),
    "lst_poder": (
        "lst_did_poder.csv",
        "ATENÇÃO: o efeito mínimo detectável do desenho de LST é 427x MAIOR que o efeito "
        "esperado. O nulo de temperatura NÃO é evidência de ausência de aquecimento.",
    ),
    "tendencias_paralelas": (
        "trajetoria_pixel_tendencias_paralelas.csv",
        "Pré-teste da hipótese identificadora: antes da obra, tratamento e controle cresciam "
        "no mesmo ritmo (6/14, p=0,79). É o que sustenta a leitura causal do desenho.",
    ),
}


def main() -> int:
    destino = C.DIR_PROCESSED / "consolidado_impacto_resultados.xlsx"
    leia = pd.DataFrame(
        [{"aba": nome, "arquivo_de_origem": meta[0], "o_que_e": meta[1]}
         for nome, meta in ABAS.items() if meta]
    )
    avisos = pd.DataFrame(
        [
            {"aba": "!! AVISO 1", "arquivo_de_origem": "—",
             "o_que_e": "NÃO modele em cima de area_ha_* / prop_* do painel: somar área por "
                        "classe no disco foi testado em 6 raios (0,5 a 5 km) e NÃO detecta a "
                        "obra. Use trajetoria_pixel / footprint_vs_anel."},
            {"aba": "!! AVISO 2", "arquivo_de_origem": "—",
             "o_que_e": "População, emprego e PIB são de nível MUNICIPAL. Servem como contexto, "
                        "nunca como evidência de efeito de um data center. Os pares têm portes "
                        "municipais de razão 0,03 a 15,0 — só variação relativa é interpretável."},
            {"aba": "!! AVISO 3", "arquivo_de_origem": "—",
             "o_que_e": "mw_construido_total só existe para 10 dos 15 campi, e a lacuna é "
                        "geográfica (9/9 Sudeste, 0/5 Nordeste+Norte+Centro-Oeste). Usar MW como "
                        "feature elimina todo bioma fora da Mata Atlântica."},
            {"aba": "!! AVISO 4", "arquivo_de_origem": "—",
             "o_que_e": "A MAGNITUDE do impacto não é predizível com as features disponíveis: "
                        "R² LOOCV negativo em 13 modelos, permutação p=0,53 "
                        "(modelo-impacto/outputs/explicacao_modelos.csv). O que se sustenta "
                        "é o padrão/direção, não o coeficiente."},
        ]
    )

    with pd.ExcelWriter(destino, engine="openpyxl") as xl:
        pd.concat([leia, avisos], ignore_index=True).to_excel(
            xl, sheet_name="leia_primeiro", index=False
        )
        for nome, meta in ABAS.items():
            if not meta:
                continue
            caminho = C.DIR_SAIDA / meta[0]
            if not caminho.exists():
                print(f"  ! faltando: {meta[0]}")
                continue
            pd.read_csv(caminho).to_excel(xl, sheet_name=nome[:31], index=False)
            print(f"  aba {nome}")

    print(f"  -> {destino.relative_to(C.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
