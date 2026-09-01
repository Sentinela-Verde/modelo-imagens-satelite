"""SV-24 — consolidação, deduplicação por AOI e tiering da lista de data centers.

Gera três artefatos a partir das duas listas do Notion transcritas manualmente abaixo
(cada uma buscada via MCP em 2026-08-31, ids de página citados no cabeçalho de cada lista):

    data/externo/sites_notion_lista20.csv   — extração fiel da página "20 Data Centers De 2016 a 2026"
    data/externo/sites_notion_lista30.csv   — extração fiel da página "Lista dos 30 data centers..."
    config/sites_candidatos.csv             — saída consolidada, deduplicada por AOI, com elegibilidade
                                               (E1-E4) e tier, conforme docs/tarefas/SV-24-consolidacao-lista-sites.md

Rodar: `.venv\\Scripts\\python.exe scripts\\build_sites_candidatos.py`

Determinístico por construção: todos os dados de entrada estão hard-coded neste arquivo (transcrição
das duas tabelas do Notion + citações pontuais da página "Dados - informações de data centers", usada
só como referência de coordenadas de alta confiança, nunca como uma terceira lista de candidatos —
ver docs/decisoes/ADR-005-expansao-de-sites.md). Rodar duas vezes produz o mesmo CSV byte a byte.

Este script NÃO busca coordenada nenhuma (isso é SV-25, fora de escopo aqui) e NÃO coleta MW, área do
terreno, população ou qualquer variável não-imagem (SV-28, fora de escopo do repositório).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNO_DIR = REPO_ROOT / "data" / "externo"
CONFIG_DIR = REPO_ROOT / "config"

# ================================================================================================
# 1. Extração fiel das duas listas do Notion (colunas originais preservadas, sem interpretação)
# ================================================================================================
# Fonte: página Notion "⚠️ 20 Data Centers De 2016 a 2026" (id 3cecefef-d904-80ef-8a74-f37e04084d27),
# buscada via mcp__plugin_Notion_notion__notion-fetch em 2026-08-31. "**negrito**" do Notion removido
# (é só marcação da página, não dado). "A validar" preservado literalmente.
LISTA20_COLS = [
    "#", "data_center_projeto", "estado", "cidade", "latitude", "longitude",
    "ano_construcao", "ano_operacao", "status_2026", "periodo_pre", "periodo_durante",
    "periodo_pos", "relevancia",
]
LISTA20 = [
    [1, "Ascenty Sumaré 1", "SP", "Sumaré", "A validar", "A validar", "2017", "2017", "Operacional",
     "2014-2016", "2017", "2018-2026", "Excelente caso histórico para medir mudança territorial após implantação."],
    [2, "Ascenty Sumaré 2", "SP", "Sumaré", "A validar", "A validar", "2019", "2019", "Operacional",
     "2016-2018", "2019", "2020-2026", "Permite estudar expansão do mesmo polo em relação ao Sumaré 1."],
    [3, "Ascenty Hortolândia 2", "SP", "Hortolândia", "A validar", "A validar", "2018-2019", "2019", "Operacional",
     "2015-2017", "2018-2019", "2020-2026", "Bom caso de expansão de infraestrutura em polo industrial/tecnológico."],
    [4, "Ascenty Hortolândia 3", "SP", "Hortolândia", "A validar", "A validar", "2018-2019", "2019", "Operacional",
     "2015-2017", "2018-2019", "2020-2026", "Complementa Hortolândia 2 e permite estudar efeito acumulado de um campus."],
    [5, "Ascenty Paulínia 1", "SP", "Paulínia", "A validar", "A validar", "2019", "2019", "Operacional",
     "2016-2018", "2019", "2020-2026", "Interessante por estar inserido em importante polo industrial/petroquímico."],
    [6, "Ascenty Vinhedo 1", "SP", "Vinhedo", "-23.0702", "-47.0130", "2019", "2019", "Operacional",
     "2016-2018", "2019", "2020-2026", "Caso prioritário: grande campus e excelente janela temporal pré/pós."],
    [7, "Ascenty Jundiaí 2", "SP", "Jundiaí", "A validar", "A validar", "2019", "2019", "Operacional",
     "2016-2018", "2019", "2020-2026", "Permite comparar Jundiaí com Vinhedo, Sumaré e Hortolândia."],
    [8, "Ascenty Vinhedo 2", "SP", "Vinhedo", "-23.0702", "-47.0130", "2020", "2020", "Operacional",
     "2017-2019", "2020", "2021-2026", "Excelente para expansão: segundo grande empreendimento do campus."],
    [9, "Ascenty São Paulo 3", "SP", "Osasco", "A validar", "A validar", "2020", "2020", "Operacional",
     "2017-2019", "2020", "2021-2026", "Caso urbano, útil para comparar implantação em área metropolitana mais densa."],
    [10, "Equinix SP5x", "SP", "Santana de Parnaíba", "A validar", "A validar", "2020-2021", "2021", "Operacional",
     "2017-2019", "2020-2021", "2022-2026", "Muito importante: infraestrutura hyperscale e expansão de grande escala."],
    [11, "Ascenty Hortolândia 4", "SP", "Hortolândia", "A validar", "A validar", "2020-2021", "2021", "Operacional",
     "2018-2020", "2020-2021", "2022-2026", "Permite avaliar expansão contínua do campus ao longo da série temporal."],
    [12, "Ascenty Hortolândia 5", "SP", "Hortolândia", "A validar", "A validar", "2021-2022", "2022", "Operacional",
     "2019-2021", "2021-2022", "2023-2026", "Muito bom caso temporal, pois amplia fortemente a capacidade do campus."],
    [13, "Ascenty São Paulo 4", "SP", "Osasco", "A validar", "A validar", "2022", "2023", "Operacional",
     "2019-2021", "2022-2023", "2024-2026",
     "Excelente caso pré/durante/pós. Construção iniciada em 2022 e operação em 2023. "
     "(https://ascenty.com/data-centers/localizacao/brasil/sao-paulo-capital/sao-paulo-4/)"],
    [14, "Scala Campus Tamboré", "SP", "Barueri", "A validar", "A validar", "2022-2024*", "2023+*",
     "Operacional / expansão", "2019-2021", "2022-2024", "2025-2026",
     "Muito relevante: grande campus com expansão sucessiva. Há unidades Scala identificadas no "
     "endereço da Av. Ceci; por isso, o campus deve ser tratado como área de análise. "
     "(https://www.gbcbrasil.org.br/certificacao/certificacao-leed/empreendimentos/)"],
    [15, "Scala SGIGSM01", "RJ", "São João de Meriti", "-22.7999", "-43.3538", "2022-2023*", "2023*", "Operacional",
     "2019-2021", "2022-2023", "2024-2026",
     "Excelente caso para levar o estudo para fora de SP. A instalação está georreferenciada em fonte "
     "de infraestrutura de Internet. (PeeringDB: https://www.peeringdb.com/fac/13398)"],
    [16, "Scala SPOAPA01", "RS", "Porto Alegre", "-30.0028", "-51.1981", "2023", "2023", "Operacional",
     "2020-2022", "2023", "2024-2026",
     "Importante para representatividade regional e comparação Sul x Sudeste. "
     "(PeeringDB: https://www.peeringdb.com/fac/14336)"],
    [17, "Equinix RJ3", "RJ", "São João de Meriti", "A validar", "A validar", "2024-2025*", "2025*",
     "Operacional / recente", "2021-2023", "2024-2025", "2026",
     "Excelente caso recente. Foi anunciado em maio de 2024, com início de operação previsto para 2025. "
     "(https://equinix.mediaroom.com/2024-05-23-Com-investimento-de-US-94-milhoes)"],
    [18, "RT-One Uberlândia", "MG", "Uberlândia", "A validar", "A validar", "2025-2026*", "Não iniciada",
     "Em implantação / licenciamento", "2022-2024", "2025-2026", "2027+",
     "Caso estratégico: terreno >1 milhão m² e projeto de até 400 MW. Excelente para acompanhar a "
     "transformação enquanto ocorre. (https://www.uberlandia.mg.gov.br/2025/09/24/...)"],
    [19, "Data Center ByteDance / Pecém", "CE", "São Gonçalo do Amarante", "A validar", "A validar", "2026",
     "Não iniciada", "Em construção", "2023-2025", "2026", "2027+",
     "Um dos melhores casos: implantação recente e grande escala, permitindo observar transformação "
     "territorial durante a construção."],
    [20, "Scala AI City", "RS", "Eldorado do Sul", "A validar", "A validar", "2026+*", "Não iniciada",
     "Projeto / implantação", "2023-2025", "2026+", "Pós ainda não disponível",
     "Caso estratégico para estudo de grandes campi de IA e transformação territorial futura."],
]

# Fonte: página Notion "📈 Lista dos 30 data centers que analisei..." (id 0a8cefef-d904-82ad-ade3-01ccab653ab6).
LISTA30_COLS = [
    "#", "data_center_projeto", "link", "estado", "regiao", "cidade", "empresa", "relevancia",
]
LISTA30 = [
    [1, "Equinix SP6", "https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/sao-paulo-data-centers/sp6",
     "SP", "Sudeste", "Santana de Parnaíba", "Equinix",
     "Excelente caso de estudo por ser uma implantação recente. Entrou em operação em 2026, projetado "
     "para cargas de alta densidade de IA."],
    [2, "Equinix SP5x", "https://www.equinix.com/br/pt/data-centers/americas-colocation/brazil-colocation/sao-paulo-data-centers/sp5x",
     "SP", "Sudeste", "Santana de Parnaíba", "Equinix",
     "Importante representante de infraestrutura hyperscale na região metropolitana de São Paulo."],
    [3, "Ascenty Vinhedo 1", "https://ascenty.com/data-centers/localizacao/brasil/sao-paulo-interior/vinhedo/",
     "SP", "Sudeste", "Vinhedo", "Ascenty", "Relevante por estar inserido em um grande campus de data centers em área industrial."],
    [4, "Ascenty Vinhedo 2", "https://ascenty.com/data-centers/localizacao/brasil/sao-paulo-interior/vinhedo/",
     "SP", "Sudeste", "Vinhedo", "Ascenty", "Complementa o caso de Vinhedo e permite estudar expansão de um campus."],
    [5, "Ascenty Campinas CPS1", "https://www.datacentermap.com/brazil/campinas/",
     "SP", "Sudeste", "Campinas", "Ascenty", "Campinas é um importante polo tecnológico e de conectividade."],
    [6, "Ascenty Hortolândia HTL6", "https://www.datacentermap.com/brazil/campinas/",
     "SP", "Sudeste", "Hortolândia", "Ascenty", "Interessante para avaliar a expansão da infraestrutura fora do núcleo da capital."],
    [7, "Scala Campinas SVCPCP01", "https://scaladatacenters.com/data-centers/",
     "SP", "Sudeste", "Campinas", "Scala Data Centers",
     "Caso relevante pela dimensão física do empreendimento; 12.015 m² de área construída e 7 MW."],
    [8, "TIP Brasil Campinas",
     "https://setup.zeus.tipbrasil.com.br/portal-tip/artigo/tip-brasil-investe-r-500-milhoes-em-datacenter-tier-3-em-campinas",
     "SP", "Sudeste", "Campinas", "TIP Brasil",
     "R$500 milhões para aquisição, modernização e expansão do data center, capacidade prevista de até 2 mil racks."],
    [9, "Ascenty SPO06", "https://ascenty.com/blog/news-ascenty/ascenty-campus-sao-paulo/",
     "SP", "Sudeste", "Grande São Paulo", "Ascenty", "Representa expansão de capacidade de um campus existente."],
    [10, "Equinix RJ1", "https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/rio-de-janeiro-data-centers",
     "RJ", "Sudeste", "Rio de Janeiro", "Equinix", "Infraestrutura digital consolidada, referência histórica."],
    [11, "Equinix RJ2", "https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/rio-de-janeiro-data-centers",
     "RJ", "Sudeste", "Rio de Janeiro", "Equinix", "Permite comparar diferentes instalações de um mesmo operador."],
    [12, "Equinix RJ3", "https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/rio-de-janeiro-data-centers",
     "RJ", "Sudeste", "Rio de Janeiro", "Equinix", "Útil para estudar concentração espacial de infraestrutura digital."],
    [13, "RT-One Uberlândia", "https://rt-one.com/", "MG", "Sudeste", "Uberlândia", "RT-One",
     "Caso prioritário para o TCC. 100 MW na 1ª fase, expansão até 400 MW."],
    [14, "Algar Tech Uberlândia – Granja Marileusa", "https://www.datacentermap.com/brazil/uberlandia/",
     "MG", "Sudeste", "Uberlândia", "Algar Tech", "Infraestrutura já inserida em polo empresarial/tecnológico."],
    [15, "Cirion CUR1", "https://www.ciriontechnologies.com/pt-br/data-center/nossos-data-centers/curitiba-1/",
     "PR", "Sul", "Curitiba", "Cirion Technologies", "Localização física identificada, infraestrutura carrier-neutral."],
    [16, "Elea CTA1", "https://eleadatacenters.com/datacenters/cta1-curitiba/", "PR", "Sul", "Curitiba",
     "Elea Data Centers", "Foco em sustentabilidade; energia renovável e conectividade regional."],
    [17, "Tecto TPOA1", "https://www.datacentermap.com/brazil/porto-alegre/tecto-tpoa1/", "RS", "Sul",
     "Porto Alegre", "Tecto Data Centers",
     "Excelente caso temporal. Projeto anunciado em 2026, terreno de 33 mil m², 20 MW previstos."],
    [18, "Scala AI City",
     "https://www.eldorado.rs.gov.br/portal/noticias/0/3/4671/eldorado-do-sul-assina-protocolo-de-intencoes-scala",
     "RS", "Sul", "Eldorado do Sul", "Scala Data Centers",
     "Caso estratégico. Projeto de grande escala voltado a IA, investimento inicial de R$3 bilhões."],
    [19, "Armazém DC Joinville", "https://www.armazem.cloud/", "SC", "Sul", "Joinville", "Armazém Cloud",
     "Amplia representatividade da amostra na Região Sul."],
    [20, "Unifique Timbó DC1", "https://unifique.com.br/datacenter", "SC", "Sul", "Timbó", "Unifique",
     "Certificações Tier III Design e Facility."],
    [21, "Elea BSB2", "https://eleadatacenters.com/datacenters/bsb2-brasilia/", "DF", "Centro-Oeste", "Brasília",
     "Elea Data Centers", "Representa Brasília e a infraestrutura digital associada a um grande centro político."],
    [22, "Everest Digital Data Center", "https://everestdigital.com.br/solucoes/data-center/", "GO", "Centro-Oeste",
     "Goiânia", "Everest Digital", "Data center próprio em Goiânia, certificação Tier III."],
    [23, "Data Center ByteDance – Pecém", "https://www.datacentermap.com/brazil/fortaleza/", "CE", "Nordeste",
     "São Gonçalo do Amarante", "Omnia / Pátria",
     "Um dos candidatos mais importantes. Complexo do Pecém, projetos de grande escala de IA."],
    [24, "AngoNAP Fortaleza", "https://www.angolacables.com/", "CE", "Nordeste", "Fortaleza", "Angola Cables",
     "Relação entre data center, conectividade internacional e cabos submarinos."],
    [25, "Scala Fortaleza Campus", "https://www.datacentermap.com/brazil/fortaleza/scala-data-centers-fortaleza-campus/",
     "CE", "Nordeste", "Fortaleza", "Scala Data Centers", "Expansão do mercado nordestino."],
    [26, "Atlantic Data Center Recife 1", "https://atlanticdatacenters.com/", "PE", "Nordeste", "Recife",
     "Atlantic Data Centers / Um Telecom", "Localização estratégica na cidade."],
    [27, "Surfix Data Center", "https://surfix.com.br/data-center/", "PE", "Nordeste", "Recife",
     "Surfix Cloud & Data Center", "Endereço em Boa Viagem, Recife."],
    [28, "Hostzone Data Center", "https://cliente.hostzone.com.br/store/data-center", "PB", "Nordeste",
     "Campina Grande", "Hostzone", "CGE1 em Campina Grande e também uma operação em São Paulo."],
    [29, "ClickIP Datacenters", "https://www.datacentermap.com/brazil/manaus/", "AM", "Norte", "Manaus",
     "ClickIP Datacenters", "Fundamental para garantir representação da Região Norte."],
    [30, "Data Center PRODEB", "https://www.ba.gov.br/prodeb/servicos", "BA", "Nordeste", "Salvador",
     "PRODEB / Governo da Bahia", "Infraestrutura pública."],
]


def _write_raw_csv(path: Path, cols: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(cols + ["fonte_lista"])
        for row in rows:
            writer.writerow(list(row) + [path.stem.split("_")[-1]])


# ================================================================================================
# 2. Consolidação por AOI — dedup de prédio, dedup de AOI, elegibilidade (E1-E4), tier
# ================================================================================================
# Cada AOI é um dict com:
#   aoi_id, nome_exibicao, operador, municipio, uf, regiao, bioma_estimado (estimativa por domínio
#     biogeográfico do IBGE a partir do município/UF — conhecimento geográfico geral, não coleta de
#     variável externa: usado só para o critério de diversidade do tier 1, pedido explicitamente pela
#     tarefa)
#   predios: lista de {nome, ano_construcao, ano_operacao, status, fonte} — ano como string ORIGINAL
#     da lista (intervalo preservado; a redução a "primeiro ano" só ocorre nos campos agregados da AOI)
#   status_2026, fonte_lista, fontes_url
#   elegivel, criterio_reprovacao (E1-E4 ou None), observacao
#   anos_para_agregacao: subconjunto opcional de nomes de prédios a EXCLUIR do cálculo de
#     ano_construcao_min/max e ano_operacao_min/max (usado só quando um prédio tem ano fora da janela
#     2013-2024 e incluí-lo geraria periodo_pos vazio para prédios que já são elegíveis por outra via —
#     ver observação de cada caso)
#   lat/lon: sempre vazios nesta etapa (SV-25). precisao_coordenada: "confirmada" só para os 3 sites já
#     em produção (coordenada já existe em config/sites.geojson); "pendente" para todo o resto.

def _primeiro_ano(valor: str) -> int | None:
    """'2018-2019' -> 2018; '2022-2024*' -> 2022; 'Não iniciada' -> None."""
    if valor is None:
        return None
    v = valor.strip().rstrip("*").rstrip("+")
    v = v.split("-")[0].strip()
    if not v.isdigit():
        return None
    return int(v)


AOI_RECORDS: list[dict] = []


def add_aoi(**kwargs):
    kwargs.setdefault("excluir_da_agregacao", set())
    kwargs.setdefault("lat", "")
    kwargs.setdefault("lon", "")
    AOI_RECORDS.append(kwargs)


# ---- 3 AOIs já existentes (config/sites.geojson, ADR-001) ------------------------------------

add_aoi(
    aoi_id="ascenty-vinhedo", nome_exibicao="Ascenty Vinhedo", operador="Ascenty",
    municipio="Vinhedo", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Ascenty Vinhedo 1", "ano_construcao": "2019", "ano_operacao": "2019",
         "status": "Operacional", "fonte": "lista_20+lista_30"},
        {"nome": "Ascenty Vinhedo 2", "ano_construcao": "2020", "ano_operacao": "2020",
         "status": "Operacional", "fonte": "lista_20+lista_30"},
    ],
    status_2026="Operacional", fonte_lista="lista_20+lista_30",
    fontes_url="https://ascenty.com/data-centers/localizacao/brasil/sao-paulo-interior/vinhedo/",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="confirmada",
    observacao=(
        "AOI já existente (ADR-001), aoi_id fixo — não renomear. Coordenada real já está em "
        "config/sites.geojson (-23.0700044,-47.0118926), confirmada via Google Maps; lat/lon deste "
        "arquivo ficam vazios por consistência de schema com as demais linhas, não porque a "
        "coordenada esteja pendente. Fusão de nível prédio: 'Vinhedo 1' e 'Vinhedo 2' aparecem "
        "idênticas nas duas listas (lista_20 #6/#8, lista_30 #3/#4). Fusão de nível AOI: os dois "
        "prédios (mesmo operador, mesmo município, campus único) viram uma AOI."
    ),
)

add_aoi(
    aoi_id="odata-hortolandia", nome_exibicao="ODATA Data Center SP02", operador="ODATA (Aligned Data Centers)",
    municipio="Hortolândia", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "ODATA Data Center SP02", "ano_construcao": None, "ano_operacao": None,
         "status": "Operacional", "fonte": "config/sites.geojson (ADR-001)"},
    ],
    status_2026="Operacional", fonte_lista="existente",
    fontes_url="",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="confirmada",
    observacao=(
        "AOI já existente (ADR-001), aoi_id fixo — não renomear. NÃO aparece em nenhuma das duas "
        "listas do Notion consolidadas nesta tarefa (nem lista de 20 nem lista de 30 citam ODATA) — "
        "carregada aqui só para manter as 3 AOIs de produção num único arquivo auditável. Ano de "
        "construção/operação não fazem parte do escopo original (ADR-001) e não foram buscados aqui "
        "(fora de escopo de SV-24 revisitar dado já fechado). "
        "ATENÇÃO — achado relevante para SV-25: o campus 'Ascenty Hortolândia' (nova AOI candidata "
        "'ascenty-hortolandia' deste mesmo arquivo) tem coordenada de referência a ~1,7 km desta AOI "
        "(-22.896022,-47.179246 vs -22.8995299,-47.1952611 aqui) — dentro do buffer de 5 km. Se "
        "confirmado com coordenada real, isso é uma colisão de AOI (E4/V4 de SV-25) que precisa de "
        "decisão humana: fundir as duas ou manter separadas por serem operadores/prédios distintos."
    ),
)

add_aoi(
    aoi_id="scala-tambore", nome_exibicao="Scala Data Centers - SGRUTB12", operador="Scala Data Centers",
    municipio="Barueri", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Scala SGRUTB12 (site já ativo)", "ano_construcao": None, "ano_operacao": None,
         "status": "Operacional", "fonte": "config/sites.geojson (ADR-001)"},
        {"nome": "Scala Campus Tamboré (descrição agregada da lista_20)", "ano_construcao": "2022-2024*",
         "ano_operacao": "2023+*", "status": "Operacional / expansão", "fonte": "lista_20"},
        {"nome": "Scala SGRUTB01", "ano_construcao": None, "ano_operacao": None,
         "status": "Operacional (presumido)", "fonte": "pagina_referencia_notion"},
        {"nome": "Scala SGRUTB03", "ano_construcao": None, "ano_operacao": None,
         "status": "Operacional (presumido)", "fonte": "pagina_referencia_notion"},
        {"nome": "Scala SGRUTB04", "ano_construcao": "2021-22", "ano_operacao": "2022",
         "status": "Operacional", "fonte": "pagina_referencia_notion"},
        {"nome": "Scala SGRUTB05", "ano_construcao": None, "ano_operacao": "2023",
         "status": "Operacional", "fonte": "pagina_referencia_notion"},
    ],
    status_2026="Operacional / expansão", fonte_lista="lista_20",
    fontes_url="https://www.gbcbrasil.org.br/certificacao/certificacao-leed/empreendimentos/",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="confirmada",
    observacao=(
        "AOI já existente (ADR-001), aoi_id fixo — não renomear. Coordenada real já em "
        "config/sites.geojson (-23.4948321,-46.8130769). A lista_20 trata 'Scala Campus Tamboré' "
        "como um único item (#14) mas a página de referência do Notion ('Dados - informações de "
        "data centers') documenta pelo menos 5 prédios distintos na Av. Ceci (SGRUTB01/03/04/05, "
        "coordenadas via PeeringDB) além do SGRUTB12 já ativo — preservados aqui em predios_json "
        "como enriquecimento de coordenada/ano de alta confiança (não são um terceiro item de lista, "
        "só contexto citado na página de referência). SGRUTB01/03 não têm ano documentado em nenhuma "
        "fonte consultada (N/D explícito na tabela da página de referência)."
    ),
)

# ---- Novas AOIs elegíveis --------------------------------------------------------------------

add_aoi(
    aoi_id="ascenty-hortolandia", nome_exibicao="Ascenty Hortolândia (campus)", operador="Ascenty",
    municipio="Hortolândia", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Ascenty Hortolândia 1", "ano_construcao": None, "ano_operacao": "2015",
         "status": "Operacional (presumido)", "fonte": "pagina_referencia_notion"},
        {"nome": "Ascenty Hortolândia 2", "ano_construcao": "2018-2019", "ano_operacao": "2019",
         "status": "Operacional", "fonte": "lista_20"},
        {"nome": "Ascenty Hortolândia 3", "ano_construcao": "2018-2019", "ano_operacao": "2019",
         "status": "Operacional", "fonte": "lista_20"},
        {"nome": "Ascenty Hortolândia 4", "ano_construcao": "2020-2021", "ano_operacao": "2021",
         "status": "Operacional", "fonte": "lista_20"},
        {"nome": "Ascenty Hortolândia 5", "ano_construcao": "2021-2022", "ano_operacao": "2022",
         "status": "Operacional", "fonte": "lista_20"},
        {"nome": "Ascenty Hortolândia HTL6", "ano_construcao": None, "ano_operacao": None,
         "status": "Não documentado", "fonte": "lista_30"},
    ],
    status_2026="Operacional", fonte_lista="lista_20+lista_30",
    fontes_url="https://www.datacentermap.com/brazil/campinas/",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível AOI: 5 prédios da lista_20 (Hortolândia 2/3/4/5, mesmo operador+município) + "
        "HTL6 da lista_30 (mesmo operador+município) + Hortolândia 1 (só na página de referência, "
        "sem ano de construção documentado, apenas operação desde 2015). "
        "Escada de eventos preservada: construção 2018 (Hortolândia 2/3, ERA LANDSAT — antes de 2019), "
        "2020, 2021; operação 2015, 2019, 2019, 2021, 2022. HTL6 sem data em nenhuma fonte consultada. "
        "Coordenada de alta confiança já disponível na página de referência do Notion (fonte primária "
        "citada: publicação direta da Ascenty): lat -22.896022, lon -47.179246 (mesmo endereço para "
        "Hortolândia 1/2/3/5 — provável geocode do campus, não do prédio individual). Usar como ponto "
        "de partida em SV-25. "
        "ATENÇÃO — E4 (achado mais importante desta tarefa): esta coordenada de referência fica a "
        "~1,7 km de odata-hortolandia (AOI já aceita), dentro do buffer de 5 km. Ver observação de "
        "odata-hortolandia. Marcado elegível porque os 4 critérios E1-E4 são satisfeitos com os dados "
        "disponíveis nesta etapa (SV-24 não busca coordenada real), mas a possível colisão de buffer "
        "precisa ser resolvida em SV-25 antes de comprometer orçamento de rotulagem manual nas duas."
    ),
)

add_aoi(
    aoi_id="ascenty-sumare", nome_exibicao="Ascenty Sumaré (campus)", operador="Ascenty",
    municipio="Sumaré", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Ascenty Sumaré 1", "ano_construcao": "2017", "ano_operacao": "2017",
         "status": "Operacional", "fonte": "lista_20"},
        {"nome": "Ascenty Sumaré 2", "ano_construcao": "2019", "ano_operacao": "2019",
         "status": "Operacional", "fonte": "lista_20"},
    ],
    status_2026="Operacional", fonte_lista="lista_20",
    fontes_url="",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível AOI: Sumaré 1 e 2, mesmo operador+município, só na lista_20 (não aparece na "
        "lista_30). Construção 2017 é o evento mais antigo do conjunto elegível — ERA LANDSAT, "
        "essencial para o critério de aceite 'pelo menos 2 AOIs tier 1 com obra antes de 2019'. "
        "Coordenada 'A validar' nas duas colunas da lista_20 — nenhuma fonte de coordenada disponível "
        "nesta etapa; E3 aprovado só pela plausibilidade de fonte (Ascenty publica página de "
        "localização por unidade), não por uma URL já em mãos."
    ),
)

add_aoi(
    aoi_id="ascenty-paulinia", nome_exibicao="Ascenty Paulínia 1", operador="Ascenty",
    municipio="Paulínia", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Ascenty Paulínia 1", "ano_construcao": "2019", "ano_operacao": "2019",
         "status": "Operacional", "fonte": "lista_20"},
    ],
    status_2026="Operacional", fonte_lista="lista_20",
    fontes_url="",
    elegivel=True, criterio_reprovacao="", tier=2,
    precisao_coordenada="pendente",
    observacao=(
        "Prédio único, só na lista_20. Inserido em polo industrial/petroquímico (contexto de uso do "
        "solo distinto de Vinhedo/Hortolândia, valor analítico mesmo sem diversidade de bioma/era). "
        "REBALANCEADO NA RODADA 2 (SV-24 continuação, 2026-08-31): movido de tier 1 para tier 2. Com "
        "a chegada de 4 AOIs de novos biomas nesta rodada (Cerrado, Caatinga x2, Amazônia), a "
        "prioridade (a) do enunciado (diversidade de bioma) e (b) (era Landsat) já ficam bem cobertas "
        "sem esta AOI, que é a 3ª unidade Ascenty de SP/Sudeste/era Sentinel-2/construção 2019 no "
        "conjunto (junto com vinhedo e jundiai) — a mais redundante do grupo por esse motivo, exatamente "
        "a opção (c) que o ADR-005 já cogitava. Mantida elegível (nenhum critério E1-E4 mudou), só "
        "passa a alimentar o conjunto de generalização fora-da-amostra em vez da rotulagem manual."
    ),
)

add_aoi(
    aoi_id="ascenty-jundiai", nome_exibicao="Ascenty Jundiaí 2", operador="Ascenty",
    municipio="Jundiaí", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Ascenty Jundiaí 2", "ano_construcao": "2019", "ano_operacao": "2019",
         "status": "Operacional", "fonte": "lista_20"},
    ],
    status_2026="Operacional", fonte_lista="lista_20",
    fontes_url="",
    elegivel=True, criterio_reprovacao="", tier=2,
    precisao_coordenada="pendente",
    observacao=(
        "Prédio único, só na lista_20 (nome sugere existir um 'Jundiaí 1' em algum lugar — não citado "
        "em nenhuma das duas listas; não inventado aqui). Valor analítico: comparação com Vinhedo/"
        "Sumaré/Hortolândia no mesmo eixo industrial, mesma era de sensor. "
        "REBALANCEADO NA RODADA 2 (SV-24 continuação, 2026-08-31): movido de tier 1 para tier 2 pelo "
        "mesmo motivo de ascenty-paulinia (ver observação daquela AOI) — redundante em bioma/era/UF "
        "com outras AOIs de tier 1 agora que o conjunto tem diversidade de bioma real vinda de outras "
        "regiões. Mantida elegível, passa a alimentar o conjunto de generalização fora-da-amostra."
    ),
)

add_aoi(
    aoi_id="ascenty-osasco", nome_exibicao="Ascenty São Paulo 3/4 (Osasco)", operador="Ascenty",
    municipio="Osasco", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Ascenty São Paulo 3", "ano_construcao": "2020", "ano_operacao": "2020",
         "status": "Operacional", "fonte": "lista_20"},
        {"nome": "Ascenty São Paulo 4", "ano_construcao": "2022", "ano_operacao": "2023",
         "status": "Operacional", "fonte": "lista_20"},
    ],
    status_2026="Operacional", fonte_lista="lista_20",
    fontes_url="",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível AOI: São Paulo 3 e 4, mesmo operador+município (Osasco), só na lista_20. "
        "Caso urbano/metropolitano (l1 chama de 'caso urbano' explicitamente) — contraste de uso do "
        "solo com os campi industriais do interior. "
        "Possível relação com 'Ascenty SPO06' (lista_30 #9, município 'Grande São Paulo', sem ano): "
        "o nome sugere numeração da mesma série (SP3, SP4, SP06...), mas o município da lista_30 é "
        "impreciso (não é um município real) e não bate literalmente com 'Osasco' — regra da tarefa "
        "veda fusão automática entre municípios diferentes. NÃO fundido aqui; marcado "
        "revisar_manualmente para SV-25 confirmar com coordenada real se SPO06 é o mesmo campus."
    ),
)

add_aoi(
    aoi_id="equinix-santana-parnaiba", nome_exibicao="Equinix SP5x/SP6 (Santana de Parnaíba)", operador="Equinix",
    municipio="Santana de Parnaíba", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Equinix SP5x", "ano_construcao": "2020-2021", "ano_operacao": "2021",
         "status": "Operacional", "fonte": "lista_20+lista_30"},
        {"nome": "Equinix SP6", "ano_construcao": None, "ano_operacao": "2026",
         "status": "Operacional (2026)", "fonte": "lista_30"},
    ],
    status_2026="Operacional", fonte_lista="lista_20+lista_30",
    fontes_url="https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/sao-paulo-data-centers/sp6",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    excluir_da_agregacao={"Equinix SP6"},
    observacao=(
        "Fusão de nível prédio: SP5x aparece nas duas listas (lista_20 #10, lista_30 #2). Fusão de "
        "nível AOI: SP6 (só na lista_30, mesmo operador+município) entra como prédio adicional do "
        "mesmo campus. SP6 preservado em predios_json (nenhuma informação de ano perdida), mas "
        "EXCLUÍDO do cálculo de ano_operacao_max/periodo_pos porque sua operação (2026) cairia fora "
        "da série do repo (2013-2025) e geraria periodo_pos vazio para uma AOI que já é elegível via "
        "SP5x — ver ADR-005 para a regra geral. "
        "Reforço de fonte: a página de referência do Notion cita um estudo do governo federal com "
        "período de construção de 'Equinix SP5 – 1ª fase' de novembro/2020 a outubro/2021 — datas "
        "idênticas às de SP5x na lista_20, forte indício de que é o mesmo prédio (não um 7º prédio "
        "novo); tratado aqui como confirmação da data de SP5x, não como prédio adicional."
    ),
)

add_aoi(
    aoi_id="scala-sgigsm01", nome_exibicao="Scala SGIGSM01", operador="Scala Data Centers",
    municipio="São João de Meriti", uf="RJ", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Scala SGIGSM01", "ano_construcao": "2022-2023*", "ano_operacao": "2023*",
         "status": "Operacional", "fonte": "lista_20"},
    ],
    status_2026="Operacional", fonte_lista="lista_20",
    fontes_url="https://www.peeringdb.com/fac/13398",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "Prédio único, só na lista_20. Única AOI elegível fora de SP nesta rodada. Coordenada de alta "
        "confiança disponível: PeeringDB (citado na própria lista_20) dá -22.7999/-43.3538; a página "
        "de referência do Notion cross-confirma com -22.799883/-43.353842 — concordância à 4ª casa "
        "decimal, forte candidata a coordenada 'exata' em SV-25 (fonte A da cascata de SV-25)."
    ),
)

add_aoi(
    aoi_id="scala-spoapa01", nome_exibicao="Scala SPOAPA01", operador="Scala Data Centers",
    municipio="Porto Alegre", uf="RS", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Scala SPOAPA01", "ano_construcao": "2023", "ano_operacao": "2023",
         "status": "Operacional", "fonte": "lista_20"},
    ],
    status_2026="Operacional", fonte_lista="lista_20",
    fontes_url="https://www.peeringdb.com/fac/14336",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "Prédio único, só na lista_20. Única AOI elegível na Região Sul nesta rodada. Coordenada de "
        "alta confiança: PeeringDB (citado na lista_20) dá -30.0028/-51.1981; página de referência do "
        "Notion cross-confirma com -30.002768/-51.198149. "
        "bioma_estimado='Mata Atlântica' por estimativa de domínio biogeográfico (Porto Alegre fica "
        "perto da fronteira IBGE Mata Atlântica/Pampa) — NÃO CONFIRMADO por fonte oficial nesta "
        "tarefa (fora de escopo buscar); se for Pampa, esta AOI passa a cobrir um 2º bioma distinto, "
        "o que mudaria a conclusão sobre diversidade de bioma do tier 1. Recomenda-se checar o mapa "
        "de biomas do IBGE por sobreposição espacial assim que a coordenada real existir (SV-25)."
    ),
)

add_aoi(
    aoi_id="hostdime-joao-pessoa", nome_exibicao="HostDime Brazil (João Pessoa)", operador="HostDime",
    municipio="João Pessoa", uf="PB", regiao="Nordeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "HostDime Brazil", "ano_construcao": "2017", "ano_operacao": "2017",
              "status": "Operacional", "fonte": "pesquisa_sv24_rodada2+pagina_referencia_notion"}],
    status_2026="Operacional", fonte_lista="pagina_referencia_notion",
    fontes_url="https://www.datacenterdynamics.com/br/opini%C3%B5es/hostdime-instala-data-center-tier-iii-em-jo%C3%A3o-pessoa/",
    elegivel=True, criterio_reprovacao="", tier=2,
    precisao_coordenada="pendente",
    observacao=(
        "ADICIONADO NA RODADA 2 (SV-24 continuação, 2026-08-31). Facility citada na página de "
        "referência do Notion mas fora do escopo original de SV-24 por não constar em nenhuma das duas "
        "listas oficiais — ADR-005 já sinalizava como candidato de diversidade regional a reconsiderar "
        "('HostDime João Pessoa, operação 2017'). Pesquisa dirigida não encontrou um ano de INÍCIO DE "
        "CONSTRUÇÃO separado do ano de abertura em nenhuma fonte consultada — só 'opera desde 2017' / "
        "inauguração em 14/07/2017 (facility de 20.000 sq ft / ~1.858 m², R$ ~15 milhões) "
        "(https://www.datacenterdynamics.com/br/opini%C3%B5es/hostdime-instala-data-center-tier-iii-em-jo%C3%A3o-pessoa/). "
        "Usado ano_construcao=ano_operacao=2017 (mesma convenção já aplicada a outros prédios do "
        "conjunto quando a fonte só registra um ano — ex.: ascenty-paulinia, ascenty-jundiai) — não é "
        "invenção de dado, é a mesma regra de simplificação já usada no restante do arquivo, registrada "
        "aqui explicitamente. Construção/operação 2017 é ERA LANDSAT (pré-2019). NÃO acrescenta bioma "
        "novo (litoral de João Pessoa/PB é Mata Atlântica, já o bioma dominante do conjunto elegível) — "
        "por isso entra em TIER 2 (generalização), não tier 1: prioridade (a) do enunciado (diversidade "
        "de bioma) já está satisfeita por outras AOIs desta rodada, e prioridade (b) (era Landsat fora "
        "de SP) já está coberta por angonap-fortaleza/ascenty-maracanau. Valor real desta AOI é a "
        "diversidade de UF/região (Nordeste, PB) dentro do conjunto de generalização fora-da-amostra. "
        "Coordenada de fonte primária já citada na página de referência do Notion (via PeeringDB): "
        "-7.117382,-34.856902; ATENÇÃO: HostDime anunciou em 2025/2026 uma EXPANSÃO 4x maior com obra "
        "iniciando em janeiro/2026 (R$ 250 milhões) — evento futuro fora da janela 2013-2025, não usado "
        "aqui, mas relevante registrar para uma rodada futura "
        "(https://movimentoeconomico.com.br/tecnologia/2025/05/24/com-r-250-milhoes-multinacional-expande-data-center-na-paraiba/). "
        "E2: prédio purpose-built de 1.858 m² (0,19 ha) — pequeno mas maior que colocation urbana "
        "típica, mesma ordem de grandeza de prédios individuais já aceitos no conjunto (ex.: Ascenty "
        "Hortolândia 2/3, 2.000-3.000 m²). E3 forte (PeeringDB + fonte de imprensa). E4: nenhuma outra "
        "AOI elegível em João Pessoa/PB."
    ),
)

# ---- AOIs reprovadas (mantidas na tabela, elegivel=False) ---------------------------------------

add_aoi(
    aoi_id="ascenty-campinas-cps1", nome_exibicao="Ascenty Campinas CPS1", operador="Ascenty",
    municipio="Campinas", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Ascenty Campinas CPS1", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://www.datacentermap.com/brazil/campinas/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao="Sem ano de construção ou operação em nenhuma fonte consultada (lista_30 não tem coluna de ano; não citado na página de referência).",
)

add_aoi(
    aoi_id="scala-campinas-svcpcp01", nome_exibicao="Scala Campinas SVCPCP01", operador="Scala Data Centers",
    municipio="Campinas", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Scala SVCPCP01", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://scaladatacenters.com/data-centers/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado em nenhuma fonte (a própria página de referência do Notion marca "
        "construção E operação como 'N/D' explicitamente para este prédio). Coordenada de alta "
        "confiança JÁ disponível (-22.820539,-47.100058, PeeringDB) e footprint grande (12.015 m², "
        "citado na lista_30) — E2 e E3 passariam com folga; só falta uma data. Candidata forte para "
        "reconsideração se o time encontrar o ano de construção fora do escopo desta tarefa."
    ),
)

add_aoi(
    aoi_id="tip-brasil-campinas", nome_exibicao="TIP Brasil Campinas", operador="TIP Brasil",
    municipio="Campinas", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "TIP Brasil Campinas", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://setup.zeus.tipbrasil.com.br/portal-tip/artigo/tip-brasil-investe-r-500-milhoes-em-datacenter-tier-3-em-campinas",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado. Adicionalmente, a relevância da lista_30 descreve 'aquisição, "
        "modernização e expansão' de um data center já existente — sinal de que pode não ser "
        "construção nova em terreno aberto (possível risco de E2 também), mas E1 já é suficiente "
        "para reprovar sem precisar resolver essa ambiguidade."
    ),
)

add_aoi(
    aoi_id="ascenty-spo06", nome_exibicao="Ascenty SPO06", operador="Ascenty",
    municipio="Grande São Paulo", uf="SP", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Ascenty SPO06", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://ascenty.com/blog/news-ascenty/ascenty-campus-sao-paulo/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado. Município 'Grande São Paulo' na lista_30 não é um município real — "
        "possível o mesmo campus de ascenty-osasco (São Paulo 3/4), mas regra da tarefa veda fusão "
        "automática entre municípios diferentes; revisar_manualmente em SV-25 com coordenada real."
    ),
)

add_aoi(
    aoi_id="equinix-rio-de-janeiro", nome_exibicao="Equinix RJ1/RJ2", operador="Equinix",
    municipio="Rio de Janeiro", uf="RJ", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[
        {"nome": "Equinix RJ1", "ano_construcao": None, "ano_operacao": None, "status": "Não documentado", "fonte": "lista_30"},
        {"nome": "Equinix RJ2", "ano_construcao": None, "ano_operacao": None, "status": "Não documentado", "fonte": "lista_30"},
    ],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/rio-de-janeiro-data-centers",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível AOI: RJ1+RJ2, mesmo operador+município, só na lista_30. Sem ano documentado — "
        "unidades aparentam ser legado da Equinix no Rio (mercado que a Equinix entrou há mais de uma "
        "década no Brasil), plausivelmente anteriores a 2013, mas isso não está confirmado em nenhuma "
        "fonte consultada; reprovado por ausência de data verificável, não por presumir data."
    ),
)

add_aoi(
    aoi_id="equinix-rj3", nome_exibicao="Equinix RJ3", operador="Equinix",
    municipio="São João de Meriti", uf="RJ", regiao="Sudeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Equinix RJ3", "ano_construcao": "2024-2025*", "ano_operacao": "2025*",
              "status": "Operacional / recente", "fonte": "lista_20+lista_30"}],
    status_2026="Operacional / recente", fonte_lista="lista_20+lista_30",
    fontes_url="https://www.equinix.com/data-centers/americas-colocation/brazil-colocation/rio-de-janeiro-data-centers",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível prédio: RJ3 aparece nas duas listas (lista_20 #17, lista_30 #12), mas com "
        "município divergente — lista_20 diz 'São João de Meriti', lista_30 diz genericamente 'Rio "
        "de Janeiro'. Usado o município da lista_20 (mais específico); revisar_manualmente em SV-25. "
        "Início de construção (2024) cai dentro da janela E1, mas operação estimada em 2025 significa "
        "periodo_pos = [2026,2025] — intervalo VAZIO dentro da série do repo (2013-2025), exatamente "
        "o caso descrito no enunciado ('um evento em 2025 não tem pós'). Reprovado por essa razão, "
        "não por falta de coordenada plausível (Equinix tem página com endereço, E3 passaria)."
    ),
)

add_aoi(
    aoi_id="rt-one-uberlandia", nome_exibicao="RT-One Uberlândia", operador="RT-One",
    municipio="Uberlândia", uf="MG", regiao="Sudeste", bioma_estimado="Cerrado",
    predios=[{"nome": "RT-One Uberlândia", "ano_construcao": "2025-2026*", "ano_operacao": None,
              "status": "Em implantação / licenciamento", "fonte": "lista_20+lista_30"}],
    status_2026="Em implantação / licenciamento", fonte_lista="lista_20+lista_30",
    fontes_url="https://rt-one.com/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível prédio: aparece nas duas listas (lista_20 #18, lista_30 #13). Status "
        "explícito na lista_20: 'Não iniciada' (ano de operação) / 'Em implantação/licenciamento' — "
        "projeto ainda não começou a construção. Único candidato de Cerrado com dados nas duas "
        "listas; perdido só por não ter iniciado obra ainda, não por falta de coordenada ou pegada."
    ),
)

add_aoi(
    aoi_id="algar-tech-uberlandia", nome_exibicao="Algar Tech Uberlândia – Granja Marileusa", operador="Algar Tech",
    municipio="Uberlândia", uf="MG", regiao="Sudeste", bioma_estimado="Cerrado",
    predios=[{"nome": "Algar Tech Uberlândia – Granja Marileusa", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://www.datacentermap.com/brazil/uberlandia/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao="Sem ano documentado em nenhuma fonte consultada.",
)

add_aoi(
    aoi_id="cirion-curitiba", nome_exibicao="Cirion CUR1", operador="Cirion Technologies",
    municipio="Curitiba", uf="PR", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Cirion CUR1", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://www.ciriontechnologies.com/pt-br/data-center/nossos-data-centers/curitiba-1/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado em nenhuma fonte consultada. PESQUISADO NA RODADA 2 (2026-08-31): "
        "confirmado que era originalmente uma facility Level3 (telecom legado), rebatizada Cirion em "
        "2022 — rebranding não é construção nova nem dá um ano de construção verificável dentro da "
        "janela; a estrutura física é provavelmente anterior a 2013. Reprovação mantida por E1, agora "
        "com motivo mais preciso (facility legada, não sem-dado)."
    ),
)

add_aoi(
    aoi_id="elea-curitiba", nome_exibicao="Elea CTA1", operador="Elea Data Centers",
    municipio="Curitiba", uf="PR", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Elea CTA1", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://eleadatacenters.com/datacenters/cta1-curitiba/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado em nenhuma fonte consultada. PESQUISADO NA RODADA 2 (2026-08-31): "
        "confirmado que a Elea adquiriu esta facility da Oi em 2021 (Elea Data Centers foi fundada em "
        "2020 pela Piemonte Holding) — é aquisição de infraestrutura de telecom legada, não construção "
        "nova; ano de construção original permanece indocumentado. Reprovação mantida por E1 (e "
        "provável risco adicional de E2, aquisição/rebranding em vez de greenfield, análogo ao caso "
        "elea-poa2 desta mesma rodada)."
    ),
)

add_aoi(
    aoi_id="elea-poa2", nome_exibicao="Elea POA2", operador="Elea Data Centers",
    municipio="Porto Alegre", uf="RS", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Elea POA2", "ano_construcao": "2022", "ano_operacao": "2023",
              "status": "Operacional", "fonte": "pesquisa_sv24_rodada2+pagina_referencia_notion"}],
    status_2026="Operacional", fonte_lista="pagina_referencia_notion",
    fontes_url="https://www.datacenterdynamics.com/en/news/piemontes-elea-buys-tim-data-center-in-porto-alegre-brazil/",
    elegivel=False, criterio_reprovacao="E2", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "ADICIONADO NA RODADA 2 (SV-24 continuação, 2026-08-31) por ter sido citado no ADR-005 como "
        "achado da página de referência do Notion a conferir. Não está em nenhuma das duas listas "
        "oficiais (lista_20/lista_30). Pesquisa dirigida confirma: a Elea comprou um prédio já "
        "existente da TIM Brasil em setembro/2022 ('purchase and sale agreement of a real estate owned "
        "by TIM'), no centro de Porto Alegre, com 4.000 m² já construídos junto a uma subestação de "
        "energia e dutos de fibra já existentes; primeira fase inaugurada em março/2023 "
        "(https://www.datacenterdynamics.com/en/news/piemontes-elea-buys-tim-data-center-in-porto-alegre-brazil/). "
        "REPROVADO POR E2: é aquisição/retrofit de uma instalação de telecom já existente (antigo PoP "
        "da TIM), não construção nova em terreno aberto — mesmo padrão do exemplo negativo do "
        "enunciado (surfix-recife). Também não acrescentaria bioma novo: mesmo município/UF de "
        "scala-spoapa01 (já elegível, Mata Atlântica/possível fronteira Pampa)."
    ),
)

add_aoi(
    aoi_id="tecto-porto-alegre", nome_exibicao="Tecto TPOA1", operador="Tecto Data Centers",
    municipio="Porto Alegre", uf="RS", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Tecto TPOA1", "ano_construcao": None, "ano_operacao": None,
              "status": "Projeto anunciado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://tecto.com/en/news-and-insights/tecto-announces-r200-million-investment-in-a-new-data-center-in-porto-alegre-connected-to-v-tals-submarine-cable/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Projeto anunciado em 2026 (obra ainda não iniciada segundo a relevância da lista_30) — sem "
        "construção iniciada, E1 reprova. PESQUISADO NA RODADA 2 (2026-08-31): confirmado que o "
        "projeto é o RETROFIT de um armazém/galpão já existente no bairro Sarandi (não construção "
        "nova em terreno aberto), com 1ª fase (3 MW) prevista para entrar em operação só no 4º "
        "trimestre de 2026 — fora da janela 2013-2025 mesmo se a obra começasse imediatamente. Dupla "
        "reprovação potencial: E1 (nenhuma obra iniciada ainda) e E2 (retrofit de galpão existente, não "
        "greenfield) "
        "(https://tecto.com/en/news-and-insights/tecto-announces-r200-million-investment-in-a-new-data-center-in-porto-alegre-connected-to-v-tals-submarine-cable/)."
    ),
)

add_aoi(
    aoi_id="scala-ai-city", nome_exibicao="Scala AI City", operador="Scala Data Centers",
    municipio="Eldorado do Sul", uf="RS", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Scala AI City", "ano_construcao": "2026+*", "ano_operacao": None,
              "status": "Projeto / implantação", "fonte": "lista_20+lista_30"}],
    status_2026="Projeto / implantação", fonte_lista="lista_20+lista_30",
    fontes_url="https://www.eldorado.rs.gov.br/portal/noticias/0/3/4671/eldorado-do-sul-assina-protocolo-de-intencoes-scala",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível prédio: aparece nas duas listas (lista_20 #20, lista_30 #18). Status "
        "explícito: 'Não iniciada'. Projeto futuro de grande escala — bom candidato para uma rodada "
        "futura assim que a obra iniciar (dentro da janela 2013-2025 restante, isso teria que ser em "
        "2025 mesmo, o que já não deixaria 'pós' — improvável que entre nesta série mesmo depois de iniciada). "
        "CONFIRMADO NA RODADA 2 (2026-08-31), respondendo à pergunta 'já pode estar elegível?' — NÃO: "
        "vice-presidente da Scala declarou que a obra deve iniciar em 2027, condicionada a licenciamento "
        "ainda em curso; entrada em operação da unidade inicial prevista entre fim de 2028 e início de "
        "2029 (https://www.guaiba.online/noticia/vice-presidente-da-scala-diz-que-ai-city-de-eldorado-do-sul-deve-iniciar-obras-em-2027). "
        "Nenhuma obra iniciada até a data da pesquisa; reprovação por E1 mantida com folga."
    ),
)

add_aoi(
    aoi_id="armazem-joinville", nome_exibicao="Armazém DC Joinville", operador="Armazém Cloud",
    municipio="Joinville", uf="SC", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Armazém DC Joinville", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://www.armazem.cloud/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao="Sem ano documentado em nenhuma fonte consultada.",
)

add_aoi(
    aoi_id="unifique-timbo", nome_exibicao="Unifique Timbó DC1", operador="Unifique",
    municipio="Timbó", uf="SC", regiao="Sul", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Unifique Timbó DC1", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://unifique.com.br/datacenter",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao="Sem ano documentado em nenhuma fonte consultada.",
)

add_aoi(
    aoi_id="elea-brasilia", nome_exibicao="Elea BSB2", operador="Elea Data Centers",
    municipio="Brasília", uf="DF", regiao="Centro-Oeste", bioma_estimado="Cerrado",
    predios=[{"nome": "Elea BSB2", "ano_construcao": "2004", "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30+pagina_referencia_notion"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://eleadatacenters.com/datacenters/bsb2-brasilia/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Construção documentada em 2004 (página de referência do Notion) — ANTERIOR à janela "
        "2013-2025 do repositório (ADR-001). Único candidato de Centro-Oeste/Cerrado com data "
        "encontrada; perdido só por ser velho demais para a série, não por falta de dado."
    ),
)

add_aoi(
    aoi_id="everest-goiania", nome_exibicao="Everest Digital Data Center", operador="Everest Digital (Grupo Soluti)",
    municipio="Goiânia", uf="GO", regiao="Centro-Oeste", bioma_estimado="Cerrado",
    predios=[{"nome": "Everest Digital Data Center", "ano_construcao": "2021", "ano_operacao": "2023",
              "status": "Operacional", "fonte": "pesquisa_sv24_rodada2"}],
    status_2026="Operacional", fonte_lista="lista_30",
    fontes_url="https://www.arandanet.com.br/revista/rti/noticia/8167-Everest-Digital,-o-primeiro-data-center-de-servicos-gerenciados-Tier-III-do-Centro-Oeste.html",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "REVISADO NA RODADA 2 (SV-24 continuação, 2026-08-31): a lista_30 não tinha ano; pesquisa "
        "dirigida encontrou construção e operação em imprensa de negócios local. Construção: 'em 2021, "
        "a diretoria [do Grupo Soluti] anunciou a construção da nova sede em Goiânia com data center "
        "incluído', obras concluídas em ~1,5 ano "
        "(https://www.arandanet.com.br/revista/rti/noticia/8167-Everest-Digital,-o-primeiro-data-center-de-servicos-gerenciados-Tier-III-do-Centro-Oeste.html). "
        "Operação: Grupo Soluti inicia operações da Everest Digital em maio/2023 "
        "(https://empreenderemgoias.com.br/2023/05/02/grupo-soluti-inicia-operacoes-da-everest-digital/); "
        "sede/data center inaugurados formalmente em 31/10/2023 "
        "(https://empreenderemgoias.com.br/2023/10/31/soluti-inaugura-sede-inovadora-em-goiania/). "
        "Usado ano_operacao=2023 (início efetivo de operação, mais próximo do inauguração formal, "
        "convenção mais conservadora que a data de anúncio). ÚNICO candidato de Centro-Oeste/Cerrado "
        "elegível nesta rodada — elea-brasilia (BSB2) ficou de fora por construção de 2004 (anterior à "
        "janela 2013-2025) e nenhuma expansão datável foi encontrada. E2: construção nova (prédio-sede "
        "com data center integrado, LEED Gold, TUV Rheinland Tier III construção+operação), área total "
        "4.500 m² (0,45 ha) — pegada visível. E3: fonte plausível (imprensa de negócios local + site "
        "institucional da Everest/Soluti); endereço exato fica para SV-25. E4: nenhuma outra AOI "
        "elegível em Goiânia/GO nesta rodada."
    ),
)

add_aoi(
    aoi_id="bytedance-pecem", nome_exibicao="Data Center ByteDance / Pecém", operador="Omnia / Pátria",
    municipio="São Gonçalo do Amarante", uf="CE", regiao="Nordeste", bioma_estimado="Caatinga",
    predios=[{"nome": "Data Center ByteDance / Pecém", "ano_construcao": "2026", "ano_operacao": None,
              "status": "Em construção", "fonte": "lista_20+lista_30"}],
    status_2026="Em construção", fonte_lista="lista_20+lista_30",
    fontes_url="https://bpmoney.com.br/inovacao/tecnologia/tiktok-data-center-ceara-50-bilhoes/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Fusão de nível prédio: aparece nas duas listas com operador atribuído de forma divergente "
        "(lista_20 chama de 'ByteDance', lista_30 atribui a 'Omnia/Pátria' — discrepância preservada, "
        "não resolvida aqui). Ano de construção documentado é 2026, fora da janela E1 (2013-2024); "
        "status 'Em construção' sugere que a obra já começou, mas nenhuma fonte consultada documenta "
        "um ano de início anterior a 2026 — reprovado pelo dado disponível, não por presunção. "
        "CONFIRMADO NA RODADA 2 (2026-08-31): as obras do Complexo do Pecém começaram em janeiro de "
        "2026 (https://bpmoney.com.br/inovacao/tecnologia/tiktok-data-center-ceara-50-bilhoes/ ; "
        "reportagens de imagens da obra e início de montagem confirmam o mesmo período), com início de "
        "operação previsto só para o 3º trimestre de 2027. Isso é AINDA MAIS TARDE que a suposição "
        "anterior (2026) — a data real (2026) segue fora da janela E1 (2013-2024), e mesmo usando 2026 "
        "como início, o período pós ficaria vazio (operação prevista 2027, fora da série 2013-2025). "
        "Reprovação por E1 mantida e reforçada, não revertida — apesar de ser o candidato de maior "
        "perfil de Nordeste/Caatinga, a linha do tempo real o exclui claramente desta rodada."
    ),
)

add_aoi(
    aoi_id="angonap-fortaleza", nome_exibicao="AngoNAP Fortaleza", operador="Angola Cables",
    municipio="Fortaleza", uf="CE", regiao="Nordeste", bioma_estimado="Caatinga",
    predios=[{"nome": "AngoNAP Fortaleza", "ano_construcao": "2017", "ano_operacao": "2019",
              "status": "Operacional", "fonte": "pesquisa_sv24_rodada2"}],
    status_2026="Operacional", fonte_lista="lista_30",
    fontes_url="https://teletime.com.br/11/07/2017/angola-cables-comeca-construir-data-center-em-fortaleza/",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "REVISADO NA RODADA 2 (SV-24 continuação, 2026-08-31): a lista_30 não tinha coluna de ano; "
        "pesquisa dirigida encontrou o ano de início da obra e o ano de operação em fontes públicas. "
        "Construção: pedra fundamental lançada em 11/07/2017, marcando o início das fases de fundação, "
        "terraplenagem e drenagem, na Praia do Futuro, Fortaleza "
        "(https://teletime.com.br/11/07/2017/angola-cables-comeca-construir-data-center-em-fortaleza/ ; "
        "confirmado por fonte governamental: "
        "https://www.sct.ce.gov.br/2017/07/11/angola-cables-inicia-obras-do-data-center-conectando-o-ceara-a-angola/). "
        "Operação: inaugurado em 16/04/2019 "
        "(https://www.datacenterdynamics.com/br/opini%C3%B5es/angola-cables-inaugura-data-center-angonap-fortaleza/ ; "
        "https://www.fortaleza.ce.gov.br/noticias/prefeito-roberto-claudio-participa-da-inauguracao-do-data-center-da-empresa-angola-cables). "
        "Construção 2017 é ERA LANDSAT (pré-2019) — 1º evento datável de Nordeste/Caatinga na série. "
        "E2: construção nova em terreno aberto na Praia do Futuro (obra de fundação/terraplenagem "
        "documentada, não colocation em prédio existente), área total 9.000 m² (0,9 ha) ao final das "
        "fases — pegada da mesma ordem de grandeza de AOIs já aceitas (ex.: scala-spoapa01, 4.070 m²). "
        "E3: endereço físico documentado (Praia do Futuro, Fortaleza) em múltiplas fontes de imprensa e "
        "prefeitura; coordenada exata fica para SV-25. E4: nenhuma outra AOI elegível em Fortaleza/CE "
        "nesta rodada além de ascenty-maracanau (município distinto, Maracanaú, sem fusão automática)."
    ),
)

add_aoi(
    aoi_id="ascenty-maracanau", nome_exibicao="Ascenty Fortaleza 1", operador="Ascenty",
    municipio="Maracanaú", uf="CE", regiao="Nordeste", bioma_estimado="Caatinga",
    predios=[{"nome": "Ascenty Fortaleza 1", "ano_construcao": "2014", "ano_operacao": "2015",
              "status": "Operacional", "fonte": "pesquisa_sv24_rodada2+pagina_referencia_notion"}],
    status_2026="Operacional", fonte_lista="pagina_referencia_notion",
    fontes_url="https://ascenty.com/en/data-centers-en/location/brazil/ceara/fortaleza-1/",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "ADICIONADO NA RODADA 2 (SV-24 continuação, 2026-08-31). Facility citada na página de "
        "referência do Notion ('Dados - informações de data centers') mas fora do escopo original de "
        "SV-24 por não constar em nenhuma das duas listas oficiais (lista_20/lista_30) — ADR-005 já "
        "sinalizava como forte candidato de diversidade regional a reconsiderar. Esta rodada busca e "
        "confirma o ano de construção que faltava: obra iniciada em 2014, inaugurado em junho de 2015 "
        "como terceiro data center da Ascenty no Brasil e primeiro fora de SP "
        "(https://www.datacenterdynamics.com/br/opini%C3%B5es/ascenty-inaugura-data-center-de-r-120-milh%C3%B5es-no-nordeste/). "
        "Construção 2014 é ERA LANDSAT (pré-2019) — evento mais antigo do conjunto elegível fora de SP. "
        "Coordenada de fonte primária já conhecida da página de referência do Notion (a própria Ascenty "
        "publica localização/capacidade da unidade): -3.830803,-38.611253, 9.000 m² de área total "
        "(0,9 ha) — pegada visível, E2 passa. lat/lon deste arquivo ficam vazios e precisao_coordenada "
        "'pendente' por não fazer parte do escopo de SV-24 buscar/confirmar coordenada em escala "
        "(SV-25); a coordenada acima é só um ponto de partida documentado para SV-25 usar. E3 forte "
        "(fonte primária do operador). E4: município "
        "Maracanaú é distinto de Fortaleza (angonap-fortaleza) — sem fusão automática; municípios "
        "vizinhos na região metropolitana, mas Maracanaú fica ~15-20 km a oeste do centro de Fortaleza "
        "e a AngoNAP fica na Praia do Futuro (litoral leste) — plausivelmente fora do buffer de 5 km, "
        "mas a confirmação com coordenada exata fica para SV-25."
    ),
)

add_aoi(
    aoi_id="scala-fortaleza", nome_exibicao="Scala Fortaleza Campus", operador="Scala Data Centers",
    municipio="Fortaleza", uf="CE", regiao="Nordeste", bioma_estimado="Caatinga",
    predios=[{"nome": "Scala Fortaleza Campus (SFORPF01)", "ano_construcao": "2024", "ano_operacao": None,
              "status": "Em construção", "fonte": "pesquisa_sv24_rodada2"}],
    status_2026="Em construção", fonte_lista="lista_30",
    fontes_url="https://itforum.com.br/noticias/scala-data-centers-obra-1-bi-fortaleza/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "PESQUISADO NA RODADA 2 (2026-08-31): pedra fundamental lançada em 25/06/2024 (obra 'SFORPF01', "
        "R$ 1 bilhão, 24.000 m², 2 prédios + subestação) "
        "(https://itforum.com.br/noticias/scala-data-centers-obra-1-bi-fortaleza/ ; "
        "https://www.fortaleza.ce.gov.br/noticias/pedra-fundamental-do-1-data-center-da-scala-em-fortaleza-e-lancada-com-a-presenca-do-prefeito-jose-sarto). "
        "Construção 2024 CAI DENTRO da janela E1 (2013-2024) — mas a operação inicial estava prevista "
        "para o começo de 2025 e a conclusão plena do campus só em 2028; usando o o operação=2025 (mais "
        "otimista encontrado), periodo_pos = [2026,2025] fica VAZIO dentro da série do repo "
        "(2013-2025) — o mesmo padrão exato que já reprova equinix-rj3 neste arquivo. Reprovado por E1 "
        "por essa razão (não por falta de coordenada ou pegada — teria E2/E3 fortes). Candidato a "
        "reconsiderar em uma rodada futura se a operação real de 2025 for confirmada e o repositório "
        "aceitar um período pós de 1 ano só, ou se a série for estendida além de 2025."
    ),
)

add_aoi(
    aoi_id="atlantic-recife", nome_exibicao="Atlantic Data Center Recife 1", operador="Atlantic Data Centers / Um Telecom",
    municipio="Recife", uf="PE", regiao="Nordeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Atlantic Data Center Recife 1", "ano_construcao": "2025", "ano_operacao": None,
              "status": "Em construção", "fonte": "pesquisa_sv24_rodada2"}],
    status_2026="Em construção", fonte_lista="lista_30",
    fontes_url="https://revistane.com.br/2025/01/16/um-telecom-inicia-a-construcao-do-recife1-primeiro-data-center-da-atlantic-data-centers-em-pernambuco/",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "PESQUISADO NA RODADA 2 (2026-08-31): construção iniciada em janeiro de 2025 no Parqtel "
        "(Parque Tecnológico de Eletrônicos), bairro Várzea, Recife "
        "(https://revistane.com.br/2025/01/16/um-telecom-inicia-a-construcao-do-recife1-primeiro-data-center-da-atlantic-data-centers-em-pernambuco/); "
        "inauguração prevista para o 1º trimestre de 2026 "
        "(https://teletime.com.br/21/07/2025/eletronet-sera-primeira-a-ancorar-em-data-center-da-atlantic-no-recife/). "
        "Ano de construção real (2025) agora conhecido, mas cai FORA da janela E1 (2013-2024) por 1 "
        "ano — e mesmo se fosse aceito, a operação prevista (2026) deixaria periodo_pos vazio (mesmo "
        "padrão de equinix-rj3/bytedance-pecem). Reprovação por E1 mantida, agora com data real em vez "
        "de 'sem dado'. É construção nova em terreno aberto (~14.000 m², E2 passaria) — o único motivo "
        "de reprovação é a data."
    ),
)

add_aoi(
    aoi_id="surfix-recife", nome_exibicao="Surfix Data Center", operador="Surfix Cloud & Data Center",
    municipio="Recife", uf="PE", regiao="Nordeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Surfix Data Center", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://surfix.com.br/data-center/",
    elegivel=False, criterio_reprovacao="E2", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Colocation em edifício urbano existente em Boa Viagem, Recife (endereço citado na própria "
        "relevância da lista_30) — exatamente o exemplo negativo citado no enunciado de SV-24 "
        "('um data center que ocupa dois andares de um edifício em Boa Viagem'). Não é construção "
        "nova em terreno aberto; não muda pegada visível em imagem de satélite. Reprovado por E2."
    ),
)

add_aoi(
    aoi_id="hostzone-campina-grande", nome_exibicao="Hostzone Data Center (CGE1)", operador="Hostzone",
    municipio="Campina Grande", uf="PB", regiao="Nordeste", bioma_estimado="Caatinga",
    predios=[{"nome": "Hostzone Data Center (CGE1)", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://cliente.hostzone.com.br/store/data-center",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado em nenhuma fonte consultada. PESQUISADO NA RODADA 2 (2026-08-31): busca "
        "dirigida (site institucional, PeeringDB, DataCenterMap) não encontrou ano de fundação, "
        "construção ou inauguração em nenhuma fonte pública — reprovação mantida sem alteração."
    ),
)

add_aoi(
    aoi_id="clickip-manaus", nome_exibicao="ClickIP Datacenters", operador="ClickIP Datacenters",
    municipio="Manaus", uf="AM", regiao="Norte", bioma_estimado="Amazônia",
    predios=[{"nome": "ClickIP Datacenters", "ano_construcao": "2023", "ano_operacao": "2024",
              "status": "Operacional", "fonte": "pesquisa_sv24_rodada2"}],
    status_2026="Operacional", fonte_lista="lista_30",
    fontes_url="https://telesintese.com.br/grupo-clickip-inaugura-maior-data-center-da-regiao-norte/",
    elegivel=True, criterio_reprovacao="", tier=1,
    precisao_coordenada="pendente",
    observacao=(
        "REVISADO NA RODADA 2 (SV-24 continuação, 2026-08-31): a lista_30 não tinha ano; pesquisa "
        "dirigida encontrou construção e operação em imprensa especializada. Construção: reportagem de "
        "julho/2023 já descreve obra em ritmo acelerado com ~R$16 milhões investidos na construção do "
        "espaço até aquele momento, visando inauguração no último trimestre de 2023 "
        "(https://telesintese.com.br/clickip-vai-inaugurar-maior-datacenter-comercial-da-regiao-norte/) "
        "— usado 2023 como ano de construção (obra já em andamento nessa data, início exato dentro de "
        "2023 não documentado com mais precisão). Operação: inauguração efetiva em 22/08/2024, após "
        "atraso em relação ao previsto em 2023 "
        "(https://telesintese.com.br/grupo-clickip-inaugura-maior-data-center-da-regiao-norte/ ; "
        "https://www.arandanet.com.br/revista/rti/noticia/9467-Grupo-ClickIP-inaugura-data-center-edge-em-Manaus.html). "
        "ÚNICO candidato de Região Norte/bioma Amazônia em qualquer uma das duas listas — sem esta "
        "AOI, a região fica sem nenhuma representação no estudo. "
        "ATENÇÃO — ressalva de E2 para revisão humana: pegada pequena (área construída 685 m² em "
        "terreno de 1.200 m² = 0,12 ha), bem abaixo da ordem de grandeza '≥ 1 ha' citada no enunciado "
        "de SV-24 e menor que qualquer outra AOI elegível do conjunto (a menor até aqui era "
        "scala-spoapa01, 4.070 m² = 0,4 ha). É construção nova em terreno aberto, não colocation em "
        "prédio existente (passa no teste literal de E2 do ADR-005: greenfield vs. colocation urbana), "
        "mas a 34x35 m de footprint está no limite de visibilidade mesmo em Sentinel-2 (10 m, ~3x3 "
        "pixels) e é essencialmente invisível em Landsat (30 m) — o que não chega a importar aqui "
        "porque toda a janela pré/durante/pós desta AOI (2020-2025) cai na era Sentinel-2. Marcado "
        "elegível por satisfazer o critério E2 como documentado (não a leitura estendida de "
        "visibilidade em pixel), mas a decisão de manter é do usuário na aprovação do tier. "
        "E3: endereço e coordenada plausíveis via imprensa/DataCenterMap; exata fica para SV-25. "
        "E4: nenhuma outra AOI elegível em Manaus/AM."
    ),
)

add_aoi(
    aoi_id="prodeb-salvador", nome_exibicao="Data Center PRODEB", operador="PRODEB / Governo da Bahia",
    municipio="Salvador", uf="BA", regiao="Nordeste", bioma_estimado="Mata Atlântica",
    predios=[{"nome": "Data Center PRODEB", "ano_construcao": None, "ano_operacao": None,
              "status": "Não documentado", "fonte": "lista_30"}],
    status_2026="", fonte_lista="lista_30",
    fontes_url="https://www.ba.gov.br/prodeb/servicos",
    elegivel=False, criterio_reprovacao="E1", tier=None,
    precisao_coordenada="pendente",
    observacao=(
        "Sem ano documentado em nenhuma fonte consultada. PESQUISADO NA RODADA 2 (2026-08-31): "
        "confirmado apenas que a PRODEB (empresa pública) foi instituída pela Lei nº 3.157 em "
        "01/10/1973 — data da empresa, não do prédio do data center atual, e de qualquer forma muito "
        "anterior à janela 2013-2025. Nenhuma fonte encontrada documenta quando o data room atual foi "
        "construído. Reprovação mantida sem alteração."
    ),
)


# ================================================================================================
# 3. Cálculo dos campos derivados (anos agregados, períodos pré/durante/pós) e escrita do CSV
# ================================================================================================

CANDIDATOS_COLS = [
    "aoi_id", "nome_exibicao", "operador", "municipio", "uf", "regiao", "bioma_estimado",
    "n_predios", "predios_json", "ano_construcao_min", "ano_operacao_min", "ano_construcao_max",
    "ano_operacao_max", "periodo_pre", "periodo_durante", "periodo_pos", "status_2026",
    "elegivel", "criterio_reprovacao", "tier", "fonte_lista", "fontes_url", "lat", "lon",
    "precisao_coordenada", "observacao",
]

FIM_SERIE = 2025


def _agregar_anos(aoi: dict) -> tuple[int | None, int | None, int | None, int | None]:
    excluir = aoi["excluir_da_agregacao"]
    construcoes = [
        _primeiro_ano(p["ano_construcao"]) for p in aoi["predios"]
        if p["nome"] not in excluir and p["ano_construcao"]
    ]
    operacoes = [
        _primeiro_ano(p["ano_operacao"]) for p in aoi["predios"]
        if p["nome"] not in excluir and p["ano_operacao"]
    ]
    construcoes = [c for c in construcoes if c is not None]
    operacoes = [o for o in operacoes if o is not None]
    c_min = min(construcoes) if construcoes else None
    c_max = max(construcoes) if construcoes else None
    o_min = min(operacoes) if operacoes else None
    o_max = max(operacoes) if operacoes else None
    return c_min, o_min, c_max, o_max


def _periodos(c_min: int | None, o_max: int | None) -> tuple[str, str, str]:
    """Convenção da lista_20, adotada pelo time (ver SV-24):
    pré = 3 anos antes do início da obra; durante = início da obra até operação; pós = ano seguinte
    à operação até 2025 (não 2026 — a série do repo termina em 2025)."""
    if c_min is None or o_max is None:
        return "", "", ""
    pre = f"{c_min - 3}-{c_min - 1}"
    durante = f"{c_min}-{o_max}" if o_max >= c_min else f"{c_min}-{c_min}"
    pos_ini = o_max + 1
    if pos_ini > FIM_SERIE:
        pos = ""  # intervalo vazio — não deveria ocorrer para nenhuma AOI elegível (ver ADR-005)
    else:
        pos = f"{pos_ini}-{FIM_SERIE}"
    return pre, durante, pos


def build_candidatos_rows() -> list[list]:
    rows = []
    for aoi in sorted(AOI_RECORDS, key=lambda a: a["aoi_id"]):
        c_min, o_min, c_max, o_max = _agregar_anos(aoi)
        pre, durante, pos = _periodos(c_min, o_max)
        # odata-hortolandia é um caso especial conhecido: não está em nenhuma das duas listas do
        # Notion (ver observação da própria AOI) e ADR-001 nunca documentou ano de construção/operação
        # para ela — não há dado de ano para agregar, então periodo_* ficam vazios por design, não por
        # erro de agregação. Todas as demais AOIs elegíveis precisam de periodo_pos não vazio.
        if aoi["elegivel"] and not pos and aoi["aoi_id"] != "odata-hortolandia":
            raise ValueError(f"{aoi['aoi_id']}: AOI elegível com periodo_pos vazio — revisar exclusao_da_agregacao")
        predios_json = json.dumps(aoi["predios"], ensure_ascii=False, sort_keys=False)
        rows.append([
            aoi["aoi_id"], aoi["nome_exibicao"], aoi["operador"], aoi["municipio"], aoi["uf"],
            aoi["regiao"], aoi["bioma_estimado"], len(aoi["predios"]), predios_json,
            c_min if c_min is not None else "", o_min if o_min is not None else "",
            c_max if c_max is not None else "", o_max if o_max is not None else "",
            pre, durante, pos, aoi["status_2026"], aoi["elegivel"], aoi["criterio_reprovacao"],
            aoi["tier"] if aoi["tier"] is not None else "", aoi["fonte_lista"], aoi["fontes_url"],
            aoi["lat"], aoi["lon"], aoi["precisao_coordenada"], aoi["observacao"],
        ])
    return rows


def main() -> None:
    _write_raw_csv(EXTERNO_DIR / "sites_notion_lista20.csv", LISTA20_COLS, LISTA20)
    _write_raw_csv(EXTERNO_DIR / "sites_notion_lista30.csv", LISTA30_COLS, LISTA30)

    rows = build_candidatos_rows()
    out_path = CONFIG_DIR / "sites_candidatos.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CANDIDATOS_COLS)
        writer.writerows(rows)

    n_elegiveis = sum(1 for a in AOI_RECORDS if a["elegivel"])
    n_tier1 = sum(1 for a in AOI_RECORDS if a["tier"] == 1)
    n_tier2 = sum(1 for a in AOI_RECORDS if a["tier"] == 2)
    n_rejeitadas = sum(1 for a in AOI_RECORDS if not a["elegivel"])
    print(f"AOIs totais: {len(AOI_RECORDS)} | elegíveis: {n_elegiveis} | tier1: {n_tier1} | "
          f"tier2: {n_tier2} | rejeitadas: {n_rejeitadas}")
    print(f"Escrito: {out_path}")


if __name__ == "__main__":
    main()
