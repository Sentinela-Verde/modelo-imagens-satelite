"""Passo 9 — população, emprego formal e PIB dos municípios de TODOS os pontos do painel.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_09_socioeconomico_pontos.py [--force]

Duas lacunas que este passo fecha em `processed/{populacao,emprego,pib}_municipal.csv`:

1. **Só cobrem tratamento.** Os 15 pontos de controle caem em 13 municípios que nunca foram
   coletados — sem eles, as variáveis socioeconômicas ficam sem contrafactual.
2. **Começam em 2016.** É o "10 anos de histórico" do briefing anterior, não limite de fonte. A
   janela deste estudo vai a 2013 (`ascenty-maracanau`), então a série é recoletada de 2013.

**A coleta não é reimplementada.** Este script importa `coletar_serie_municipio` de
`extrair_populacao_ibge.py` e de `extrair_emprego.py`, e lê o PIB do mesmo CSV bronze que
`extrair_pib.py` usa. Municípios de tratamento e de controle passam pelo MESMO código, na MESMA
execução, contra as MESMAS tabelas do IBGE — pela mesma razão que a cobertura do solo usa um
sensor só dos dois lados da comparação: fonte diferente entre as pontas transforma diferença de
método em diferença aparente de resultado.

## Ressalva que precisa acompanhar estes dados

Estas variáveis são de **nível municipal**. Isso tem duas consequências que o modelo de impacto
precisa levar em conta:

- Elas **não variam dentro do município**. O "controle" socioeconômico de um data center é um
  município vizinho inteiro, não um recorte de 5 km — um contraste muito mais grosseiro que o da
  cobertura do solo.
- Em `everest-goiania` o controle caiu no **mesmo município** do tratamento (Goiânia). Ali as
  colunas socioeconômicas são literalmente idênticas nas duas pontas: contraste zero. A coluna
  `municipio_compartilhado_com_par` marca esse caso explicitamente, para ninguém interpretar um
  delta de zero como ausência de efeito.

Isso reforça, não contradiz, o que `dados-modelo-impacto/README.md` e
`docs/requisitos-dados-externos.md` já registram: população, emprego e PIB municipais servem como
**contexto/estratificação dos casos**, não como evidência de efeito causado por um data center
específico.

Saída: `raw/controles-rf/socioeconomico_pontos.csv` — 1 linha por (ponto, ano).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _sites_ibge_common as CM
import extrair_emprego as EMP
import extrair_pib as PIB
import extrair_populacao_ibge as POP
import impacto_dc_04_painel_features as P4
import impacto_dc_comum as C

SAIDA = C.DIR_SAIDA / "socioeconomico_pontos.csv"
RAW_DIR = C.DIR_SAIDA / "raw_ibge"

# Piso da janela deste estudo (`ascenty-maracanau`, obra 2014 -> janela começa em 2013). Os
# extratores originais usam 2016; a diferença é o recorte do briefing anterior, não a fonte.
ANO_INICIO = 2013
ANO_FIM = 2025


def pontos_e_municipios(
    pares: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[tuple[str, str], str]]:
    """Os 30 pontos com anos e município, a lista deduplicada de municípios a coletar, e o mapa
    (nome normalizado, uf) -> grafia crua usada na coleta."""
    props = C.carregar_sites_validados()
    campi = {c["site_id"]: c for c in C.carregar_campi()}
    pontos: list[dict[str, Any]] = []

    for _, r in pares[pares["status"] == "ok"].iterrows():
        site_id = r["site_id"]
        anos, _fim = P4.anos_do_par(campi[site_id], props[site_id], r["sensor"])
        pontos.append({
            "site_id": site_id, "tipo": "tratamento", "pareado_com": site_id,
            "municipio": campi[site_id]["municipio"], "uf": campi[site_id]["uf"], "anos": anos,
        })
        pontos.append({
            "site_id": r["site_id_controle"], "tipo": "controle", "pareado_com": site_id,
            "municipio": r["municipio_controle"], "uf": r["uf_controle"], "anos": anos,
        })

    # Deduplica por nome NORMALIZADO: o município do tratamento vem de `config/sites.geojson` e o
    # do controle vem do reverse-geocode do Nominatim, então o mesmo município pode aparecer com
    # grafias diferentes (acento, caixa) e seria coletado duas vezes.
    vistos: dict[tuple[str, str], str] = {}
    municipios = []
    for p in pontos:
        chave = (CM.normalize(p["municipio"]), p["uf"])
        if chave not in vistos:
            # Guarda a grafia CRUA escolhida: `resolve_codigos_ibge` devolve um dict chaveado por
            # (municipio, uf) exatamente como recebeu, não pelo nome normalizado.
            vistos[chave] = p["municipio"]
            municipios.append({"site_id": p["site_id"], "municipio": p["municipio"], "uf": p["uf"]})
    return pontos, municipios, vistos


def carregar_pib_bronze() -> dict[tuple[int, int], float]:
    """{(codigo_ibge, ano): pib_mil_reais} do CSV bronze — a mesma fonte de `extrair_pib.py`,
    que já cobre os ~5570 municípios do Brasil, então serve para qualquer controle sem
    nenhuma chamada nova de API."""
    if not PIB.GUILHERME_CSV.exists():
        print(f"AVISO: {PIB.GUILHERME_CSV} não encontrado — PIB ficará vazio nesta rodada.")
        return {}
    tabela: dict[tuple[int, int], float] = {}
    with PIB.GUILHERME_CSV.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            pib = (linha.get("pib") or "").strip()
            if not pib:
                continue
            try:
                tabela[(int(linha["codigo_ibge"]), int(linha["ano"]))] = float(pib)
            except ValueError:
                continue
    return tabela


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Socioeconômico por ponto do painel (passo 9).")
    parser.add_argument("--force", action="store_true", help="ignora o checkpoint e recoleta tudo")
    args = parser.parse_args(argv)

    caminho_pares = C.DIR_SAIDA / "pareamento_controle_rf.csv"
    if not caminho_pares.exists():
        print(f"ERRO: {caminho_pares} não existe — rode o passo 3 antes.", file=sys.stderr)
        return 1
    pares = pd.read_csv(caminho_pares)
    pontos, municipios, grafia_por_norm = pontos_e_municipios(pares)
    print(f"Passo 9 — {len(pontos)} pontos em {len(municipios)} municípios distintos, "
          f"anos {ANO_INICIO}-{ANO_FIM}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    codigos = CM.resolve_codigos_ibge(municipios, RAW_DIR)
    print(f"  {len(codigos)} código(s) IBGE resolvidos")

    # A janela dos extratores é lida das constantes do módulo no momento da chamada. Ajustamos
    # para a janela deste estudo em vez de duplicar o coletor — o código que fala com o IBGE
    # continua sendo um só, para tratamento e controle.
    EMP.ANO_INICIO, EMP.ANO_FIM = ANO_INICIO, ANO_FIM

    anos_estimativa = [a for a in POP.get_periodos_estimativa() if ANO_INICIO <= a <= ANO_FIM]
    print(f"  estimativas de população disponíveis na janela: {len(anos_estimativa)} anos")

    pib_bronze = carregar_pib_bronze()
    checkpoint = C.Checkpoint(C.DIR_SAIDA / "_checkpoint_passo9.json")
    if args.force:
        checkpoint.dados = {}

    por_municipio: dict[tuple[str, str], dict[str, Any]] = {}
    for m in municipios:
        chave_norm = (CM.normalize(m["municipio"]), m["uf"])
        chave_ck = f"{m['municipio']}/{m['uf']}"
        info = codigos.get((m["municipio"], m["uf"]))
        if not info:
            print(f"  ACHADO: código IBGE não resolvido para {chave_ck} — ficará sem dado.")
            continue
        codigo = int(info["codigo_ibge"])

        dados = checkpoint.get(chave_ck)
        if dados is None:
            print(f"  coletando {chave_ck} (código {codigo})...")
            pop = POP.coletar_serie_municipio(m["municipio"], m["uf"], codigo, anos_estimativa)
            emp = EMP.coletar_serie_municipio(m["municipio"], m["uf"], codigo)
            dados = {
                "codigo_ibge": codigo,
                "populacao": {str(a): v[0] for a, v in pop.items()},
                "populacao_tipo": {str(a): v[1] for a, v in pop.items()},
                "emprego": {str(a): v for a, v in emp.items()},
            }
            checkpoint.set(chave_ck, dados)
        por_municipio[chave_norm] = dados

    # marca os pares em que tratamento e controle caem no mesmo município — contraste zero
    mun_por_par: dict[str, set] = {}
    for p in pontos:
        mun_por_par.setdefault(p["pareado_com"], set()).add((CM.normalize(p["municipio"]), p["uf"]))
    pares_mesmo_municipio = {k for k, v in mun_por_par.items() if len(v) == 1}

    linhas: list[dict[str, Any]] = []
    for p in pontos:
        d = por_municipio.get((CM.normalize(p["municipio"]), p["uf"]), {})
        codigo = d.get("codigo_ibge")
        for ano in p["anos"]:
            emp_ano = (d.get("emprego") or {}).get(str(ano)) or {}
            linhas.append({
                "site_id": p["site_id"], "tipo": p["tipo"], "pareado_com": p["pareado_com"],
                "municipio": p["municipio"], "uf": p["uf"], "codigo_ibge": codigo, "ano": ano,
                "populacao": (d.get("populacao") or {}).get(str(ano)),
                "populacao_tipo_estimativa": (d.get("populacao_tipo") or {}).get(str(ano)),
                "emprego_formal_total": emp_ano.get("emprego_formal_total"),
                "pessoal_ocupado_total": emp_ano.get("pessoal_ocupado_total"),
                "numero_empresas": emp_ano.get("numero_empresas"),
                "pib_mil_reais": pib_bronze.get((codigo, ano)) if codigo else None,
                "municipio_compartilhado_com_par": p["pareado_com"] in pares_mesmo_municipio,
                "data_extracao": datetime.now(UTC).date().isoformat(),
            })

    df = pd.DataFrame(linhas).sort_values(["pareado_com", "tipo", "ano"]).reset_index(drop=True)
    C.salvar_csv(df, SAIDA)

    print()
    for col in ("populacao", "emprego_formal_total", "pib_mil_reais"):
        cob = df.groupby("tipo")[col].apply(lambda s: f"{s.notna().sum()}/{len(s)}")
        print(f"  {col:22} {cob.to_dict()}")
    if pares_mesmo_municipio:
        print(f"  ACHADO: {len(pares_mesmo_municipio)} par(es) com tratamento e controle no MESMO "
              f"município (contraste socioeconômico zero): {sorted(pares_mesmo_municipio)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
