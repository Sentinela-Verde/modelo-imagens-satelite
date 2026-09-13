"""Passo 10 — o consolidado: um painel longo (ponto × ano) pronto para o modelo de impacto.

Rode com:

    python modelo-impacto/scripts/impacto_dc_10_consolidar.py

Junta, numa tabela só, tudo que esta frente produziu:

| bloco | origem | tratamento | controle |
|---|---|---|---|
| cobertura do solo (5 classes, ha e proporção) | classificador `rf_v1.0-tuned`, passo 4 | sim | sim |
| temperatura de superfície (LST) | MODIS MOD11A2, passo 8 | sim | sim |
| população, emprego formal, PIB | IBGE (SIDRA), passo 9 | sim | sim |
| atributos estáticos do data center (MW, tier, nº prédios) | scraping do Guilherme, `consolidado_facilities.csv` | sim | **não existe** |
| qualidade do pareamento (L1, distância) | passo 3 | sim | sim |

O bloco de atributos estáticos ficar vazio no controle não é lacuna: **o controle é um lugar sem
data center** — é exatamente essa a definição dele. As colunas ficam nulas de propósito e a coluna
`tipo` diz quando esperar isso.

## O que ficou deliberadamente de fora

`consolidado_renda.csv`, `consolidado_desemprego.csv` e `consolidado_escolaridade.csv` existem em
`processed/`, mas **só do lado do tratamento e com cobertura irregular** (renda só em 2022;
desemprego só em 5 dos 18 municípios, porque o IBGE só publica a taxa municipal para capitais;
escolaridade com cortes etários diferentes entre os censos de 2010 e 2022). Entrar com elas
apenas no tratamento quebraria a simetria que os passos 8 e 9 foram feitos para garantir — e uma
variável que existe de um lado só da comparação não é utilizável num desenho com grupo de
controle. Elas continuam disponíveis nas tabelas originais para uso como contexto.

## Ressalva que precisa acompanhar o painel

As colunas socioeconômicas são de **nível municipal** e não variam dentro do município: o
contraste tratamento/controle nelas é entre dois municípios inteiros, muito mais grosseiro que o
contraste de cobertura do solo (buffers de 5 km). Em `everest-goiania` as duas pontas caem no
mesmo município e o contraste é literalmente zero — marcado em
`municipio_compartilhado_com_par`. Ver `modelo-impacto/README.md` e
`docs/requisitos-dados-externos.md`.

Saídas:
  - `processed/consolidado_impacto_painel.csv` — o painel
  - `processed/consolidado_impacto_dicionario.csv` — dicionário de colunas
  - `processed/consolidado_impacto_modelo.xlsx` — as duas acima + o pareamento, uma aba cada
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C

SAIDA_PAINEL = C.DIR_PROCESSED / "consolidado_impacto_painel.csv"
SAIDA_DICIONARIO = C.DIR_PROCESSED / "consolidado_impacto_dicionario.csv"
SAIDA_XLSX = C.DIR_PROCESSED / "consolidado_impacto_modelo.xlsx"

COLUNAS_FACILITY = [
    "regiao", "bioma", "tier", "mw_construido_total", "whitespace_construido_sqm_total",
    "tier_projetado_max", "n_predios_datacentermap",
]

ORDEM_COLUNAS = [
    # identidade do ponto
    "site_id", "tipo", "pareado_com", "ids_datacenter", "n_predios_no_campus",
    "municipio", "uf", "codigo_ibge", "lat", "lon", "buffer_km",
    # tempo
    "ano", "ano_inicio_obra", "ano_fim_obra", "ano_relativo_ao_inicio_obra", "fase",
    # qualidade do pareamento
    "l1_rf", "qualidade_par", "dist_tratamento_controle_km", "municipio_compartilhado_com_par",
    # cobertura do solo
    "sensor", "resolucao_m", "pixels_validos", "modelo_versao",
    "area_ha_vegetacao_densa", "area_ha_vegetacao_rala", "area_ha_solo_exposto_obras",
    "area_ha_construida_urbana", "area_ha_agua",
    "prop_vegetacao_densa", "prop_vegetacao_rala", "prop_solo_exposto_obras",
    "prop_construida_urbana", "prop_agua",
    # ambiental
    "lst_media_celsius", "lst_mediana_celsius", "lst_desvio_celsius", "lst_n_cenas",
    # socioeconômico (município)
    "populacao", "populacao_tipo_estimativa", "emprego_formal_total", "pessoal_ocupado_total",
    "numero_empresas", "pib_mil_reais",
    # estáticos do data center (nulos no controle, por definição)
    *COLUNAS_FACILITY,
]

DICIONARIO = [
    ("site_id", "identidade", "id do ponto; `ctrl-*` é ponto de controle", "passos 3/4"),
    ("tipo", "identidade", "`tratamento` (data center) ou `controle` (par sem data center)", "passo 3"),
    ("pareado_com", "identidade", "site_id do tratamento do par; é a chave do par", "passo 3"),
    ("ids_datacenter", "identidade", "id_datacenter da lista do Guilherme, separados por `;` — vazio nos campi que não estavam nela e em todo controle", "passo 1"),
    ("n_predios_no_campus", "identidade", "quantos prédios da lista do Guilherme caem neste campus", "passo 1"),
    ("codigo_ibge", "identidade", "código IBGE do município do ponto", "passo 9"),
    ("ano", "tempo", "ano da observação", "—"),
    ("ano_inicio_obra", "tempo", "início da obra do data center do par, validado em `config/sites.geojson`", "repo"),
    ("ano_fim_obra", "tempo", "último ano de `periodo_durante` — a melhor aproximação de fim de obra que o repo tem", "repo"),
    ("ano_relativo_ao_inicio_obra", "tempo", "`ano - ano_inicio_obra`; alinha pares com obras em anos diferentes", "passo 4"),
    ("fase", "tempo", "`pre` / `durante` / `pos`, derivado de início e fim de obra", "passo 4"),
    ("l1_rf", "qualidade", "distância L1 entre as distribuições de classe do par, no ano anterior à obra; menor é mais parecido", "passo 3"),
    ("qualidade_par", "qualidade", "`bom` (L1<=0,10) / `aceitavel` (<=0,20) / `ruim` — limiares de SV-29, calibrados no MapBiomas (ver METODOLOGIA)", "passo 3"),
    ("dist_tratamento_controle_km", "qualidade", "distância geodésica entre tratamento e controle", "passo 3"),
    ("municipio_compartilhado_com_par", "qualidade", "True quando tratamento e controle caem no MESMO município: contraste socioeconômico zero", "passo 9"),
    ("sensor", "cobertura", "`landsat` ou `s2`; constante dentro de cada par, por desenho (SV-20)", "passo 4"),
    ("area_ha_*", "cobertura", "área da classe no buffer de 5 km, em hectares", "classificador `rf_v1.0-tuned`"),
    ("prop_*", "cobertura", "proporção da classe sobre os pixels válidos; soma 1 por linha", "classificador `rf_v1.0-tuned`"),
    ("pixels_validos", "cobertura", "pixels classificados no buffer; base das proporções", "passo 4"),
    ("lst_media_celsius", "ambiental", "média das cenas MOD11A2 do ano no buffer de 5 km, em Celsius", "passo 8"),
    ("lst_n_cenas", "ambiental", "quantas cenas de 8 dias entraram na média; baixo = ano nublado", "passo 8"),
    ("populacao", "socioeconômico", "população do MUNICÍPIO (não do buffer) — contexto, não evidência de efeito", "passo 9"),
    ("emprego_formal_total", "socioeconômico", "pessoal ocupado assalariado no MUNICÍPIO", "passo 9"),
    ("pib_mil_reais", "socioeconômico", "PIB do MUNICÍPIO, mil reais correntes", "passo 9"),
    ("mw_construido_total", "data center", "MW construídos no campus — nulo no controle, por definição", "scraping do Guilherme"),
    ("whitespace_construido_sqm_total", "data center", "whitespace em m² — nulo no controle", "scraping do Guilherme"),
    ("tier / tier_projetado_max", "data center", "tier do campus — nulo no controle", "repo / scraping"),
    ("regiao / bioma", "data center", "atributos do campus de tratamento; nulos no controle", "repo"),
]


def main() -> int:
    print("Passo 10 — consolidando o painel")
    painel = pd.read_csv(C.DIR_PROCESSED / "painel_impacto_area_por_classe.csv")
    lst = pd.read_csv(C.DIR_SAIDA / "lst_pontos.csv")
    socio = pd.read_csv(C.DIR_SAIDA / "socioeconomico_pontos.csv")
    pares = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    facilities = pd.read_csv(C.DIR_PROCESSED / "consolidado_facilities.csv")
    print(f"  painel={len(painel)}  lst={len(lst)}  socio={len(socio)}  pares={len(pares)}")

    df = painel.merge(
        lst[["site_id", "ano", "lst_media_celsius", "lst_mediana_celsius", "lst_desvio_celsius", "lst_n_cenas"]],
        on=["site_id", "ano"], how="left", validate="one_to_one",
    ).merge(
        socio[["site_id", "ano", "codigo_ibge", "populacao", "populacao_tipo_estimativa",
               "emprego_formal_total", "pessoal_ocupado_total", "numero_empresas",
               "pib_mil_reais", "municipio_compartilhado_com_par"]],
        on=["site_id", "ano"], how="left", validate="one_to_one",
    ).merge(
        pares[["site_id", "l1_rf", "qualidade", "dist_tratamento_controle_km"]]
        .rename(columns={"site_id": "pareado_com", "qualidade": "qualidade_par"}),
        on="pareado_com", how="left", validate="many_to_one",
    )

    # Atributos estáticos do data center: entram SÓ nas linhas de tratamento. Fazer o merge pela
    # chave do par e depois anular no controle seria pior — daria a impressão de que o ponto de
    # controle tem MW construído.
    fac = facilities[["site_id", *COLUNAS_FACILITY]].copy()
    df = df.merge(fac, on="site_id", how="left", validate="many_to_one")
    df.loc[df["tipo"] != "tratamento", COLUNAS_FACILITY] = pd.NA

    faltando = [c for c in ORDEM_COLUNAS if c not in df.columns]
    if faltando:
        raise RuntimeError(f"colunas esperadas ausentes no consolidado: {faltando}")
    df = df[ORDEM_COLUNAS].sort_values(["pareado_com", "tipo", "ano"]).reset_index(drop=True)

    C.salvar_csv(df, SAIDA_PAINEL)
    dicionario = pd.DataFrame(DICIONARIO, columns=["coluna", "bloco", "descricao", "origem"])
    C.salvar_csv(dicionario, SAIDA_DICIONARIO)

    with pd.ExcelWriter(SAIDA_XLSX, engine="openpyxl") as xls:
        df.to_excel(xls, sheet_name="painel", index=False)
        pares.to_excel(xls, sheet_name="pareamento", index=False)
        dicionario.to_excel(xls, sheet_name="dicionario", index=False)
    print(f"  -> {SAIDA_XLSX.relative_to(C.REPO_ROOT)} (3 abas)")

    print()
    print(f"{len(df)} linhas x {len(df.columns)} colunas | {df.pareado_com.nunique()} pares | "
          f"anos {df.ano.min()}-{df.ano.max()}")
    print("cobertura por bloco (não-nulos, tratamento / controle):")
    for col in ("area_ha_solo_exposto_obras", "lst_media_celsius", "populacao",
                "emprego_formal_total", "pib_mil_reais", "mw_construido_total"):
        c = df.groupby("tipo")[col].apply(lambda s: f"{s.notna().sum()}/{len(s)}").to_dict()
        print(f"  {col:32} tratamento={c.get('tratamento')}  controle={c.get('controle')}")

    vazias = [c for c in df.columns if df[c].isna().all()]
    if vazias:
        print(f"ACHADO: colunas inteiramente vazias: {vazias}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
