"""
Extrai serie anual de PIB municipal para os 19 sites (18 municipios unicos) deste apoio.

REAPROVEITAMENTO DE DADO JA COLETADO (nao rebaixa a API do zero): o colega Guilherme ja tinha
testado a API/tabela certa para PIB municipal, num teste funcional dele em
  C:\\Users\\gabri\\IdeaProjects\\datacenter-extracao-modelos\\data\\01_bronze\\
  teste_api_municipios_brasil_serie_historica_2010.csv
Esse CSV cobre TODOS os ~5570 municipios do Brasil, ano a ano, 2010-2023 para PIB (e 2010-2026
para populacao, nao usada aqui). Confirmado por amostragem cruzada com a API SIDRA (ver
raw/pib/METODOLOGIA.md) que o valor de PIB desse CSV bate exatamente com:
  GET https://servicodados.ibge.gov.br/api/v3/agregados/5938/periodos/{ano}/variaveis/37
      ?localidades=N6[{codigo_ibge}]
(tabela 5938 "Produto Interno Bruto dos Municipios - Referencia 2010", variavel 37 "Produto
Interno Bruto a precos correntes", unidade Mil Reais) — ou seja, o CSV do Guilherme e uma leitura
direta e correta dessa tabela SIDRA, so que ja baixada para o Brasil inteiro. Este script LE esse
CSV (so leitura, nunca escreve em datacenter-extracao-modelos/) e filtra para os 18 municipios
deste apoio, evitando rebaixar a mesma API.

Este script AINDA chama a API de Localidades do IBGE (mesmo endpoint usado pelos outros 3
coletores deste apoio, ver _sites_ibge_common.py) para resolver o codigo IBGE de cada municipio
de forma independente (nao confia soh no codigo_ibge do CSV do Guilherme) e cruzar/confirmar.

RESSALVA IMPORTANTE (ler antes de usar o CSV gerado): PIB em nivel municipal e dado de
CONTEXTO/ESTRATIFICACAO, nao evidencia de impacto causado por um data center especifico — mesma
logica ja registrada para populacao e emprego em dados-modelo-impacto/raw/{populacao,emprego}/
METODOLOGIA.md e em docs/requisitos-dados-externos.md (raiz do repo), secao 2.

Uso:
    python extrair_pib.py

Nao recebe argumentos. Le:
  - config/sites.geojson (raiz do repo) + os 3 sites novos hardcoded em _sites_ibge_common.py
  - C:\\Users\\gabri\\IdeaProjects\\datacenter-extracao-modelos\\data\\01_bronze\\
    teste_api_municipios_brasil_serie_historica_2010.csv (SO LEITURA)
Escreve:
  - dados-modelo-impacto/raw/pib/*.json (localidades) e pib_municipios_filtrado.csv (subset)
  - dados-modelo-impacto/processed/pib_municipal.csv
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from _sites_ibge_common import (
    APOIO_DIR,
    load_sites_19,
    municipios_unicos,
    resolve_codigos_ibge,
)

RAW_DIR = APOIO_DIR / "raw" / "pib"
PROCESSED_CSV = APOIO_DIR / "processed" / "pib_municipal.csv"

# Fonte bronze do Guilherme — repo irmao, SOMENTE LEITURA (nunca escrever aqui)
GUILHERME_CSV = Path(
    r"C:\Users\gabri\IdeaProjects\datacenter-extracao-modelos\data\01_bronze"
    r"\teste_api_municipios_brasil_serie_historica_2010.csv"
)

ANO_INICIO = 2016
ANO_FIM = 2025  # pedido; PIB municipal do IBGE so cobre ate 2023 (ver METODOLOGIA.md)

CSV_COLUMNS = [
    "site_id",
    "municipio",
    "uf",
    "codigo_ibge",
    "ano",
    "pib_mil_reais",
    "fonte",
    "data_extracao",
    "origem_lista",
]


def main() -> None:
    sites = load_sites_19()
    print(f"Sites carregados: {len(sites)} (16 validados + 3 datacentermap_novo)")

    municipios = municipios_unicos(sites)
    print(f"Municipios unicos: {len(municipios)}")

    codigos = resolve_codigos_ibge(sites, RAW_DIR)

    if not GUILHERME_CSV.exists():
        print(f"ERRO: nao encontrei o CSV do Guilherme em {GUILHERME_CSV}. "
              f"Sem ele, este script nao tem fonte de PIB (ver docstring: complementar via SIDRA "
              f"tabela 5938 diretamente seria o proximo passo, nao implementado aqui pois o "
              f"arquivo existe e cobre a janela pedida).")
        raise SystemExit(1)

    codigos_alvo = {str(v["codigo_ibge"]) for v in codigos.values()}

    linhas_filtradas = []
    with open(GUILHERME_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["codigo_ibge"] in codigos_alvo:
                linhas_filtradas.append(row)

    # salva subset filtrado em raw/ (evidencia do que foi reaproveitado, sem duplicar o Brasil inteiro)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    subset_path = RAW_DIR / "pib_municipios_filtrado_de_guilherme.csv"
    with open(subset_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas_filtradas[0].keys()) if linhas_filtradas else [])
        writer.writeheader()
        writer.writerows(linhas_filtradas)
    print(f"Subset filtrado (18 municipios, todo o historico) salvo em {subset_path} "
          f"({len(linhas_filtradas)} linhas)")

    # indexa por codigo_ibge -> {ano: pib}
    pib_por_codigo: dict[str, dict[int, float]] = {}
    for row in linhas_filtradas:
        cod = row["codigo_ibge"]
        ano = int(row["ano"])
        pib_str = row["pib"]
        if pib_str in ("", None):
            continue
        pib_por_codigo.setdefault(cod, {})[ano] = float(pib_str)

    data_extracao = date.today().isoformat()
    fonte = ("Reaproveitado de teste_api_municipios_brasil_serie_historica_2010.csv "
             "(Guilherme, datacenter-extracao-modelos/data/01_bronze/) — confirmado por amostragem "
             "cruzada como leitura de IBGE SIDRA tabela 5938 'Produto Interno Bruto dos Municipios "
             "- Referencia 2010', variavel 37 'Produto Interno Bruto a precos correntes' (Mil Reais)")

    linhas = []
    gaps = []
    for s in sites:
        key = (s["municipio"], s["uf"])
        codigo = str(codigos[key]["codigo_ibge"])
        serie = pib_por_codigo.get(codigo, {})
        for ano in range(ANO_INICIO, ANO_FIM + 1):
            if ano not in serie:
                gaps.append(f"{s['site_id']} ({s['municipio']}/{s['uf']}) - ano {ano} sem PIB publicado")
                continue
            linhas.append({
                "site_id": s["site_id"],
                "municipio": s["municipio"],
                "uf": s["uf"],
                "codigo_ibge": codigo,
                "ano": ano,
                "pib_mil_reais": serie[ano],
                "fonte": fonte,
                "data_extracao": data_extracao,
                "origem_lista": s["origem_lista"],
            })

    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sorted(linhas, key=lambda r: (r["site_id"], r["ano"])):
            writer.writerow(row)

    print()
    print(f"CSV escrito em {PROCESSED_CSV} — {len(linhas)} linhas (site x ano).")
    print(f"Sites x anos esperados no total: {len(sites)} x {ANO_FIM - ANO_INICIO + 1} = "
          f"{len(sites) * (ANO_FIM - ANO_INICIO + 1)}")
    if gaps:
        print(f"Lacunas (site/ano sem PIB publicado, deixadas ausentes, NAO estimadas): {len(gaps)}")
        for g in gaps:
            print(f"  - {g}")
    else:
        print("Nenhuma lacuna.")


if __name__ == "__main__":
    main()
