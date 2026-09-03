"""Consolida os dados levantados em dados-modelo-impacto/ (+ area_por_classe.csv do classificador
principal) numa planilha unica, pra apoio ao modelo de impacto do Guilherme.

Rode com: python dados-modelo-impacto/scripts/montar_planilha_consolidada.py

Gera:
  dados-modelo-impacto/processed/consolidado_painel_anual.csv    -- site x ano, series continuas
  dados-modelo-impacto/processed/consolidado_desemprego.csv      -- so 5/18 municipios (capitais)
  dados-modelo-impacto/processed/consolidado_renda.csv           -- so 2022 (Censo)
  dados-modelo-impacto/processed/consolidado_escolaridade.csv    -- 2 censos, formato longo
  dados-modelo-impacto/processed/consolidado_facilities.csv      -- atributos estaticos por site
  dados-modelo-impacto/processed/consolidado_apoio_impacto.xlsx  -- as 5 tabelas acima, uma aba cada

Nao mistura os 4 arquivos de formato/cobertura muito diferente numa unica tabela "wide" sem buraco
disfarcado de zero -- painel_anual junta so as series realmente anuais e continuas (temperatura,
populacao, emprego, PIB, area por classe do classificador). Desemprego (so capitais), renda (so
2022) e escolaridade (categorico, 2 censos) ficam em abas separadas porque forcar isso numa unica
linha por site-ano geraria NaN demais e esconderia a razao de cada lacuna.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
APOIO_DIR = REPO_ROOT / "dados-modelo-impacto"
PROCESSED = APOIO_DIR / "processed"


def carregar_sites() -> pd.DataFrame:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[gdf["ativo"] == True]  # noqa: E712
    cols = [
        "site_id", "nome", "operador", "municipio", "uf", "lat", "lon", "buffer_km",
        "regiao", "bioma", "tier", "ano_inicio_obra", "periodo_pre", "periodo_durante",
        "periodo_pos", "n_predios", "precisao_coordenada",
    ]
    df = gdf[cols].copy()
    df["origem_lista"] = "sites_validados"
    return df


def carregar_sites_novos() -> pd.DataFrame:
    """Os 3 sites reconciliados do scraping do Guilherme, mesmas colunas de carregar_sites()."""
    novos = [
        {
            "site_id": "scala-ai-city", "nome": "Scala AI City", "operador": "Scala Data Centers",
            "municipio": "Eldorado do Sul", "uf": "RS", "lat": -30.07425077314578,
            "lon": -51.49400150419427, "buffer_km": 5,
        },
        {
            "site_id": "pecem-datacenter", "nome": "Pecém Data Center", "operador": None,
            "municipio": "São Gonçalo do Amarante", "uf": "CE", "lat": -3.653321,
            "lon": -38.8251428, "buffer_km": 5,
        },
        {
            "site_id": "rtone-uberlandia", "nome": "RT-One Uberlândia", "operador": "RT-One",
            "municipio": "Uberlândia", "uf": "MG", "lat": None, "lon": None, "buffer_km": 5,
        },
    ]
    df = pd.DataFrame(novos)
    for c in ["regiao", "bioma", "tier", "ano_inicio_obra", "periodo_pre", "periodo_durante",
              "periodo_pos", "n_predios", "precisao_coordenada"]:
        df[c] = None
    df["origem_lista"] = "datacentermap_novo"
    df["observacao"] = (
        "Coordenada reconciliada do scraping datacentermap.com do Guilherme "
        "(datacenter-extracao-modelos/data/02_silver/datacentermap_enriquecido.csv) — "
        "NAO passou pela validacao em 5 camadas (V1-V5) que os sites_validados tiveram."
    )
    return df


def carregar_facility_attrs_guilherme() -> pd.DataFrame:
    """MW/tier/whitespace do scraping do Guilherme, agregado por site_id nosso (soma entre
    prédios do mesmo campus). Só leitura do repo irmão, nunca escrita."""
    guilherme_csv = (
        REPO_ROOT.parent / "datacenter-extracao-modelos" / "data" / "02_silver"
        / "datacentermap_enriquecido.csv"
    )
    if not guilherme_csv.exists():
        print(f"AVISO: {guilherme_csv} não encontrado — pulando atributos de facility do Guilherme.")
        return pd.DataFrame()
    df = pd.read_csv(guilherme_csv, sep=";", encoding="utf-8-sig")
    # mapa id_datacenter -> site_id nosso, pela reconciliação já feita (ver conversa/relatório).
    mapa_id_para_site = {
        "dc_1e8c6816f0": "ascenty-jundiai", "dc_211c584638": "ascenty-sumare",
        "dc_23c0e2a666": "ascenty-hortolandia", "dc_2858682b7b": "scala-tambore",
        "dc_2b7c5d95d1": "ascenty-hortolandia", "dc_3357273eaa": "ascenty-hortolandia",
        "dc_363da00599": "ascenty-osasco", "dc_541dfaf17f": "ascenty-paulinia",
        "dc_5ee8bb7ed9": "ascenty-vinhedo", "dc_6fba998120": "ascenty-hortolandia",
        "dc_708ead2d07": "scala-spoapa01", "dc_9977316327": "scala-sgigsm01",
        "dc_a2fa58a743": "ascenty-vinhedo", "dc_c81b687e80": "scala-sgigsm01",
        "dc_dd22938cb6": "equinix-santana-parnaiba", "dc_ef06bc479b": "ascenty-sumare",
        "dc_f7606e1e75": "ascenty-osasco",
        "dc_166467565d": "scala-ai-city", "dc_bc34fbde0a": "pecem-datacenter",
        "dc_c79290add5": "rtone-uberlandia",
        # dc_dced39dd76 = linha duplicada do Pecem no bronze do Guilherme (mesmo nome, mesma
        # coordenada, mesmo mw_construido=900 que dc_bc34fbde0a) -- deliberadamente NAO mapeada,
        # senao a soma de mw_construido_total dobra (900 -> 1800) por contar o mesmo prédio 2x.
    }
    df["site_id"] = df["id_datacenter"].map(mapa_id_para_site)
    df = df[df["site_id"].notna()].copy()
    agg = df.groupby("site_id").agg(
        mw_construido_total=("mw_construido", "sum"),
        whitespace_construido_sqm_total=("whitespace_construido_sqm", "sum"),
        tier_projetado_max=("tier_projetado", "max"),
        n_predios_datacentermap=("id_datacenter", "count"),
        operadoras_datacentermap=("operadora", lambda s: "; ".join(sorted(set(s.dropna())))),
    ).reset_index()
    return agg


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------------------------------
    # 1. Painel anual (site x ano): temperatura, populacao, emprego, PIB, area por classe
    # ---------------------------------------------------------------------------------------
    temp = pd.read_csv(PROCESSED / "temperatura_lst.csv")[
        ["site_id", "ano", "lst_media_celsius", "n_observacoes"]
    ].rename(columns={"n_observacoes": "temp_n_observacoes"})

    pop = pd.read_csv(PROCESSED / "populacao_municipal.csv")[
        ["site_id", "ano", "populacao", "tipo_estimativa"]
    ].rename(columns={"tipo_estimativa": "populacao_tipo_estimativa"})

    emp = pd.read_csv(PROCESSED / "emprego_municipal.csv")[
        ["site_id", "ano", "emprego_formal_total", "numero_empresas"]
    ]

    pib = pd.read_csv(PROCESSED / "pib_municipal.csv")[["site_id", "ano", "pib_mil_reais"]]

    # area_por_classe.csv: escolhe 1 sensor por ano (sentinel2 quando existe, senao landsat) --
    # mesma recomendacao de serie oficial documentada em ADR-002/schema-indicadores.md.
    area = pd.read_csv(REPO_ROOT / "outputs" / "indicadores" / "area_por_classe.csv")
    area["prioridade_sensor"] = area["sensor"].map({"sentinel2": 0, "landsat": 1})
    area = area.sort_values(["site_id", "ano", "classe_id", "prioridade_sensor"])
    area = area.drop_duplicates(subset=["site_id", "ano", "classe_id"], keep="first")
    area_wide = area.pivot_table(
        index=["site_id", "ano"], columns="classe_nome", values="area_ha", aggfunc="first"
    ).reset_index()
    area_wide = area_wide.rename(columns={
        "vegetacao_densa": "area_vegetacao_densa_ha",
        "vegetacao_rala": "area_vegetacao_rala_ha",
        "solo_exposto_obras": "area_solo_exposto_obras_ha",
        "construida_urbana": "area_construida_urbana_ha",
        "agua": "area_agua_ha",
    })
    sensor_usado = area[["site_id", "ano", "sensor", "faixa_serie"]].drop_duplicates(
        subset=["site_id", "ano"]
    ).rename(columns={"sensor": "classificador_sensor_usado"})
    area_wide = area_wide.merge(sensor_usado, on=["site_id", "ano"], how="left")

    painel = temp.merge(pop, on=["site_id", "ano"], how="outer")
    painel = painel.merge(emp, on=["site_id", "ano"], how="outer")
    painel = painel.merge(pib, on=["site_id", "ano"], how="outer")
    painel = painel.merge(area_wide, on=["site_id", "ano"], how="outer")
    painel = painel.sort_values(["site_id", "ano"]).reset_index(drop=True)

    sites_todos = pd.concat([carregar_sites(), carregar_sites_novos()], ignore_index=True)
    painel = painel.merge(
        sites_todos[["site_id", "nome", "municipio", "uf", "regiao", "bioma", "origem_lista"]],
        on="site_id", how="left",
    )
    cols_ordem = [
        "site_id", "nome", "municipio", "uf", "regiao", "bioma", "origem_lista", "ano",
        "lst_media_celsius", "temp_n_observacoes",
        "populacao", "populacao_tipo_estimativa",
        "emprego_formal_total", "numero_empresas",
        "pib_mil_reais",
        "area_vegetacao_densa_ha", "area_vegetacao_rala_ha", "area_solo_exposto_obras_ha",
        "area_construida_urbana_ha", "area_agua_ha",
        "classificador_sensor_usado", "faixa_serie",
    ]
    painel = painel[[c for c in cols_ordem if c in painel.columns]]
    painel.to_csv(PROCESSED / "consolidado_painel_anual.csv", index=False)
    print(f"painel_anual: {len(painel)} linhas, {painel['site_id'].nunique()} sites")

    # ---------------------------------------------------------------------------------------
    # 2-4. As tabelas de formato/cobertura diferente, sem forcar no painel wide
    # ---------------------------------------------------------------------------------------
    desemprego = pd.read_csv(PROCESSED / "desemprego_municipal.csv")
    desemprego.to_csv(PROCESSED / "consolidado_desemprego.csv", index=False)
    print(f"desemprego: {len(desemprego)} linhas, {desemprego['site_id'].nunique()} sites")

    renda = pd.read_csv(PROCESSED / "renda_municipal.csv")
    renda.to_csv(PROCESSED / "consolidado_renda.csv", index=False)
    print(f"renda: {len(renda)} linhas, {renda['site_id'].nunique()} sites")

    escolaridade = pd.read_csv(PROCESSED / "escolaridade_municipal.csv")
    escolaridade.to_csv(PROCESSED / "consolidado_escolaridade.csv", index=False)
    print(f"escolaridade: {len(escolaridade)} linhas, {escolaridade['site_id'].nunique()} sites")

    # ---------------------------------------------------------------------------------------
    # 5. Facilities (atributos estaticos, 1 linha por site)
    # ---------------------------------------------------------------------------------------
    guilherme_attrs = carregar_facility_attrs_guilherme()
    facilities = sites_todos.merge(guilherme_attrs, on="site_id", how="left")
    facilities.to_csv(PROCESSED / "consolidado_facilities.csv", index=False)
    print(f"facilities: {len(facilities)} linhas")

    # ---------------------------------------------------------------------------------------
    # XLSX com as 5 abas
    # ---------------------------------------------------------------------------------------
    xlsx_path = PROCESSED / "consolidado_apoio_impacto.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        painel.to_excel(writer, sheet_name="painel_anual", index=False)
        desemprego.to_excel(writer, sheet_name="desemprego", index=False)
        renda.to_excel(writer, sheet_name="renda", index=False)
        escolaridade.to_excel(writer, sheet_name="escolaridade", index=False)
        facilities.to_excel(writer, sheet_name="facilities", index=False)
    print(f"\nXLSX salvo: {xlsx_path}")


if __name__ == "__main__":
    main()
