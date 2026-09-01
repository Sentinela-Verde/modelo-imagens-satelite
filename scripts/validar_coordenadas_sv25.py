"""SV-25 — validação de coordenadas em escala: monta config/sites.geojson expandido.

Implementa a cascata de fontes (A PeeringDB -> B OSM/Overpass -> C geocode Nominatim -> D fila
visual) e as 5 verificações automáticas (V1-V5) descritas em
docs/tarefas/SV-25-validacao-coordenadas-escala.md, para as 16 AOIs elegíveis de
config/sites_candidatos.csv (ADR-005, tier 1 + tier 2, aprovadas pelo usuário).

**Como este script foi construído (leia antes de mudar os números abaixo):** a resolução de
coordenada de cada AOI nova foi feita nesta sessão por um agente (não um matcher genérico
automático) que consultou ao vivo: o cache completo do PeeringDB (`data/externo/peeringdb_fac_br.json`,
352 facilities do Brasil — ver `scripts/fetch_peeringdb.py` sobre como foi obtido), uma busca
Overpass (OSM) por nome de operador em todo o Brasil, e geocodificação Nominatim para os 3 casos em
que nem PeeringDB nem OSM tinham coordenada. Cada resolução está documentada em `FONTE_COORDENADA`
abaixo com o id do registro/endpoint exato usado — isso é o que torna a cadeia auditável, não um
algoritmo de fuzzy-match genérico rodando aqui (que arriscaria casar nome errado silenciosamente,
exatamente o risco que a cascata deveria evitar). As verificações V1/V2/V3/V4/V5, em contraste, SÃO
recomputadas por código determinístico (nunca hardcoded) — ver `sentinela.sites` e as chamadas de
rede batched em `scripts/sv25_reverse_geocode_v2.py` (V2) e `scripts/sv25_mapbiomas_v3.py` (V3),
cujos resultados ficam em `data/interim/sv25_v2_reverse_geocode.json` /
`data/interim/sv25_v3_mapbiomas.json` (gerados por esses scripts, lidos aqui) — reproduzir a
tarefa é rodar os 3 scripts em sequência:
    .venv\\Scripts\\python.exe scripts\\fetch_peeringdb.py
    .venv\\Scripts\\python.exe scripts\\sv25_reverse_geocode_v2.py
    .venv\\Scripts\\python.exe scripts\\sv25_mapbiomas_v3.py
    .venv\\Scripts\\python.exe scripts\\validar_coordenadas_sv25.py
    .venv\\Scripts\\python.exe scripts\\gerar_imagens_fila_visual.py

Rodar (só a montagem final, assumindo os 3 primeiros já rodaram): `.venv\\Scripts\\python.exe scripts\\validar_coordenadas_sv25.py`
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "config" / "sites_candidatos.csv"
GEOJSON_PATH = REPO_ROOT / "config" / "sites.geojson"
FILA_MD_PATH = REPO_ROOT / "docs" / "fila-conferencia-coordenadas.md"

DATA_CONSULTA_HOJE = "2026-09-01"
DATA_CONSULTA_ADR001 = "2026-08-27"  # as 3 AOIs existentes foram confirmadas manualmente nessa data

BUFFER_KM = 5  # ADR-001 — nunca mudar (invalidaria data/ já ingerido para os 3 sites em produção)

# ================================================================================================
# 1. Coordenadas já em produção (ADR-001) — NUNCA alteradas por esta tarefa.
# ================================================================================================
COORD_EXISTENTE = {
    "ascenty-vinhedo": {
        "lat": -23.0700044, "lon": -47.0118926,
        "fonte_coordenada": (
            "https://www.google.com/maps/place/Av.+Jo%C3%A3o+Batista+Nunes,+50+-+Distrito+Industrial+"
            "Benedito+Storani,+Vinhedo+-+SP,+13288-162/@-23.0700044,-47.0118926,17z"
        ),
        "metodo_coordenada": "manual", "precisao_coordenada": "exata", "data_consulta": DATA_CONSULTA_ADR001,
        "observacao_extra": (
            "Cross-check SV-25 (cenário de teste 6 — conferência cruzada obrigatória): cascata A/B "
            "encontrou PeeringDB fac 7589/7590 (Ascenty VIN01/VIN02) sem lat/lon no registro, e OSM "
            "way 713810347 ('Ascenty') em -23.0700247,-47.0118315 — a 0.01 km da coordenada manual "
            "de produção (reverse-geocode confirma município 'Vinhedo'). PASSOU com folga o limite "
            "de 1 km do cenário 6 — o casamento de nome da cascata está correto; segue confiável para "
            "as demais 13 AOIs novas."
        ),
    },
    "odata-hortolandia": {
        "lat": -22.8995299, "lon": -47.1952611,
        "fonte_coordenada": "https://www.google.com/maps/place/ODATA+Data+Center+SP02/@-22.8995299,-47.1952611,17z",
        "metodo_coordenada": "manual", "precisao_coordenada": "exata", "data_consulta": DATA_CONSULTA_ADR001,
        "observacao_extra": (
            "Cross-check SV-25: PeeringDB fac 15093 (Odata DC SP02, Hortolândia SP) em "
            "-22.89953,-47.195261 (0.02 km da coordenada de produção) e OSM way 1385101584 ('Odata') "
            "em -22.9017352,-47.1939053 (0.28 km) — confirmação independente por 2 fontes."
        ),
    },
    "scala-tambore": {
        "lat": -23.4948321, "lon": -46.8130769,
        "fonte_coordenada": "https://www.google.com/maps/place/Scala+Data+Centers+-+SGRUTB12/@-23.4948321,-46.8130769,17z",
        "metodo_coordenada": "manual", "precisao_coordenada": "exata", "data_consulta": DATA_CONSULTA_ADR001,
        "observacao_extra": (
            "Cross-check SV-25: PeeringDB fac 14821 (Scala SGRUTB12, Tamboré SP) em "
            "-23.497787,-46.816241 (0.33 km) confirma o campus da Av. Ceci; outros prédios do mesmo "
            "campus (SGRUTB01/03/04/05/08) todos no mesmo cluster (~200-400 m entre si)."
        ),
    },
}

# ================================================================================================
# 2. Coordenadas novas resolvidas pela cascata A (PeeringDB) -> B (OSM) -> C (Nominatim geocode).
#    Cada entrada documenta o id do registro/endpoint exato consultado (proveniência auditável).
# ================================================================================================
COORD_NOVA = {
    "ascenty-hortolandia": {
        "lat": -22.896022, "lon": -47.179246,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/7586 (Ascenty HTL01 - Hortolândia, PeeringDB fac id 7586)",
        "observacao_extra": (
            "Nível A. Campus com 6 registros PeeringDB (fac 7586/7587/7588/11686/11687/12197, "
            "HTL01-06), cluster de ~50 m entre si; usada a coordenada de HTL01 como ponto do campus "
            "(mesmo valor já citado como referência em ADR-005/sites_candidatos.csv). "
            "V4: colide com odata-hortolandia (~1.7 km, ver seção de colisões) — decisão: manter as "
            "duas AOIs ativas (operadores/campi distintos — Ascenty vs. ODATA/Aligned — no mesmo polo "
            "industrial de Hortolândia; buffer de 5 km cobre ambas sem perda de sinal agregado)."
        ),
    },
    "ascenty-sumare": {
        "lat": -22.8069862, "lon": -47.2200481,
        "metodo_coordenada": "geocode", "precisao_coordenada": "aproximada",
        "fonte_coordenada": (
            "Nominatim https://nominatim.openstreetmap.org/search?q=Nova+Veneza,+Sumar%C3%A9,+SP,+Brazil "
            "(bairro citado no endereço do PeeringDB fac 7584/7585 'Ascenty SUM01/SUM02': 'Rod. "
            "Anhanguera, s/n Sumaré - SP - Parque das Industrias (Nova Veneza)')"
        ),
        "observacao_extra": (
            "PeeringDB tem os registros (fac 7584 SUM01, fac 7585 SUM02, org 'Ascenty DataCenters e "
            "Telecom', cidade 'Sumaré SP') mas SEM lat/lon — endereço 's/n' (sem número) não geocodifica "
            "com precisão de edifício. Testados 3 candidatos Nominatim (rua, bairro, loteamento "
            "'Parque das Indústrias'); usado o centróide do bairro 'Nova Veneza' (maior score de "
            "relevância, 0.229, entre os candidatos). V2 aprovou (reverse-geocode confirma município "
            "Sumaré). V3 aprovou com folga (95.2% construída+solo em 500 m). MESMO ASSIM incluída na "
            "fila de conferência visual por precaução: é uma das 2 únicas AOIs tier 1 com obra "
            "pré-2019 (critério de aceite do ADR-005), e a imagem de satélite (ver "
            "reports/figures/coordenadas/ascenty-sumare.png) mostra o ponto próximo à Rodovia "
            "Anhanguera mas não claramente sobre um único prédio grande — vale confirmação humana "
            "antes de comprometer orçamento de rotulagem manual nesta AOI específica."
        ),
    },
    "ascenty-osasco": {
        "lat": -23.492259, "lon": -46.777232,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/7579 (Ascenty SPO01 - São Paulo, PeeringDB fac id 7579)",
        "observacao_extra": (
            "Nível A. Cluster de 4 registros PeeringDB (fac 7579/7580/7581/13720, SPO01-04) em "
            "Osasco SP, ~15 m entre si; usado SPO01. Cross-validado por OSM (ways 'Ascenty SP1/SP2/SP3/"
            "SP4', operador tag 'Digital Realty', mesmo cluster). V4: colide com scala-tambore "
            "(~3.7 km, ver seção de colisões) — decisão: manter ativas (campi de operadores "
            "distintos na Grande São Paulo; buffer de 5 km cobre ambas)."
        ),
    },
    "equinix-santana-parnaiba": {
        "lat": -23.460369, "lon": -46.859912,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/15047 (Equinix SP6 - São Paulo, PeeringDB fac id 15047)",
        "observacao_extra": (
            "Nível A. Usado SP6 (fac 15047) em vez de SP5x (fac 14845, sem lat/lon no registro) "
            "porque ambos são o mesmo campus operacional em Santana de Parnaíba SP (confirmado por "
            "PeeringDB fac 4309 'Equinix SP3', também no mesmo campus, e por OSM ways 'Equinix SP3/"
            "SP5/SP6', cluster de ~500 m)."
        ),
    },
    "scala-sgigsm01": {
        "lat": -22.799883, "lon": -43.353842,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/13398 (Scala Data Centers SGIGSM01, PeeringDB fac id 13398)",
        "observacao_extra": (
            "Nível A — já citada como fonte em SV-24/ADR-005. Cross-validado por OSM way 770978294 "
            "('Scala SGIGSM01', operador tag 'Scala Datacenters'), 0.5 km de distância."
        ),
    },
    "scala-spoapa01": {
        "lat": -30.002768, "lon": -51.198149,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/14336 (Scala Data Centers SPOAPA01, PeeringDB fac id 14336)",
        "observacao_extra": "Nível A — já citada como fonte em SV-24/ADR-005.",
    },
    "angonap-fortaleza": {
        "lat": -3.734736, "lon": -38.462636,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/6702 (AngoNAP Fortaleza, PeeringDB fac id 6702)",
        "observacao_extra": (
            "Nível A. Cross-validado por OSM way 808900331 ('AngoNap Fortaleza', operador tag "
            "'Angola Cables'), 0.11 km de distância. Endereço confere com a imprensa citada em "
            "SV-24 (Praia do Futuro, Fortaleza)."
        ),
    },
    "ascenty-maracanau": {
        "lat": -3.830803, "lon": -38.611253,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/5140 (Ascenty FTZ01 - Fortaleza, PeeringDB fac id 5140, cidade='Maracanaú')",
        "observacao_extra": (
            "Nível A. Registro PeeringDB tem nome 'Fortaleza' mas cidade='Maracanaú' — mesmo valor "
            "já citado como referência primária em ADR-005/SV-24. Cross-validado por OSM way "
            "1167125352 ('Ascenty Infraestrutura de Data Centers'), <10 m de distância — praticamente "
            "coordenada idêntica entre as duas fontes independentes. V4: nenhuma colisão com "
            "angonap-fortaleza (19.6 km de distância real, confirma a suspeita de ADR-005 de que "
            "os dois municípios cearenses ficam bem além do buffer de 5 km)."
        ),
    },
    "everest-goiania": {
        "lat": -16.6915189, "lon": -49.2371899,
        "metodo_coordenada": "geocode", "precisao_coordenada": "aproximada",
        "fonte_coordenada": (
            "Nominatim https://nominatim.openstreetmap.org/search?q=Av.+Fued+Jos%C3%A9+Sebba,+700,+"
            "Jardim+Goi%C3%A1s,+Goi%C3%A2nia,+GO,+Brazil (endereço do PeeringDB fac 16750 'PIX "
            "Everest Digital', que não tem lat/lon no registro)"
        ),
        "observacao_extra": (
            "PeeringDB tem o registro (fac 16750, org 'Everest Digital', cidade 'Goiania GO') mas SEM "
            "lat/lon; o nome do fac ('PIX...') sugere um ponto de troca de tráfego hospedado no "
            "prédio, não necessariamente georreferenciado ao prédio-sede em si. Nominatim resolveu 3 "
            "candidatos com a MESMA importância (0.053) ao longo da Av. Fued José Sebba — não chegou "
            "ao nível de número predial 700; usado o 1º candidato retornado. V2 aprovou (reverse-"
            "geocode confirma Goiânia). V3 aprovou com folga (99.9% construída em 500 m — região "
            "urbana densa do Jardim Goiás). MESMO ASSIM incluída na fila de conferência visual por "
            "precaução: geocode de rua sem número resolvido, único candidato de Cerrado/Centro-Oeste "
            "do tier 1 — vale confirmação humana antes de comprometer orçamento de rotulagem manual."
        ),
    },
    "clickip-manaus": {
        "lat": -3.055564, "lon": -59.989801,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/15825 (Click IP Data Centers - Manaus, PeeringDB fac id 15825)",
        "observacao_extra": (
            "Nível A. Cross-validado por OSM way 1331645888 ('ClickIP DataCenter', cidade 'Manaus'), "
            "0.01 km de distância — coordenada praticamente idêntica entre as duas fontes "
            "independentes. Ressalva de pegada pequena (0.12 ha) já registrada em ADR-005/SV-24 e "
            "aprovada pelo usuário na aprovação do tier — não é um problema de coordenada, é uma "
            "característica física real da instalação."
        ),
    },
    "ascenty-paulinia": {
        "lat": -22.7974087, "lon": -47.1345476,
        "metodo_coordenada": "osm", "precisao_coordenada": "aproximada",
        "fonte_coordenada": "OSM way 993659689 ('Subestação Ascenty', Overpass API, consulta por nome de operador em todo o Brasil)",
        "observacao_extra": (
            "PeeringDB tem o registro (fac 7591 PLN01, org 'Ascenty DataCenters e Telecom', cidade "
            "'Paulínia SP') mas SEM lat/lon, só endereço 's/n'. Nível B usado em vez de Nível A: OSM "
            "tem um ativo nomeado 'Subestação Ascenty' (way 993659689) na região — é a subestação de "
            "energia associada ao campus, não necessariamente o prédio do data center em si, por "
            "isso classificada como precisão 'aproximada' (desvio deliberado da tabela do enunciado, "
            "que trata nível B como sempre 'exata' — aqui o ativo encontrado não é o prédio-alvo, é "
            "uma infraestrutura associada). Cross-validado por geocode Nominatim do endereço PeeringDB "
            "('Rua Sebastião Cardoso, Paulínia, SP'): 2 candidatos de rua a 0.34-0.53 km da subestação "
            "— triangulação consistente. V2 aprovou (reverse-geocode confirma Paulínia). V3 aprovou "
            "com folga (72.3%). MESMO ASSIM incluída na fila de conferência visual por precaução "
            "(mesmo motivo estrutural de ascenty-sumare: fonte primária sem coordenada exata, só "
            "endereço 's/n')."
        ),
    },
    "ascenty-jundiai": {
        "lat": -23.191744, "lon": -46.974604,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/7582 (Ascenty JDI01 - Jundiaí, PeeringDB fac id 7582)",
        "observacao_extra": (
            "Nível A. Cross-validado por OSM way 545983830 ('Subestação Ascenty-Jundiai'), 0.02 km "
            "de distância — coordenada praticamente idêntica entre as duas fontes independentes."
        ),
    },
    "hostdime-joao-pessoa": {
        "lat": -7.117382, "lon": -34.856902,
        "metodo_coordenada": "peeringdb", "precisao_coordenada": "exata",
        "fonte_coordenada": "https://www.peeringdb.com/api/fac/5210 (HostDime JPA Brazil DataCenter, PeeringDB fac id 5210)",
        "observacao_extra": (
            "Nível A — já citada como fonte em SV-24/ADR-005 (via página de referência do Notion, "
            "que também cita PeeringDB). Cross-validado por OSM node 2669226345 ('HostDime', "
            "addr:city='João Pessoa'), 0.05 km de distância."
        ),
    },
}

# Referências conhecidas da lista_20 (SV-24) — usadas na V5 (distância à coordenada já conhecida).
REFERENCIA_V5 = {
    "ascenty-vinhedo": (-23.0702, -47.0130),
    "scala-sgigsm01": (-22.7999, -43.3538),
    "scala-spoapa01": (-30.0028, -51.1981),
}

# AOIs que entram na fila de conferência visual (nível D) apesar de V1-V5 terem aprovado — decisão
# de precaução do agente, registrada explicitamente (ver observacao_extra de cada uma acima).
FILA_VISUAL_PRECAUCAO = {
    "ascenty-sumare": (
        "Precisão 'aproximada' (geocode de bairro, endereço-fonte 's/n'); AOI crítica para o "
        "critério de aceite 'era Landsat pré-2019' do tier 1. Imagem mostra o ponto perto da "
        "Rodovia Anhanguera, não claramente sobre um prédio único."
    ),
    "ascenty-paulinia": (
        "Precisão 'aproximada' (coordenada é de uma subestação associada, não do prédio "
        "confirmado; endereço-fonte 's/n')."
    ),
    "everest-goiania": (
        "Precisão 'aproximada' (geocode não resolveu ao número predial, 3 candidatos com "
        "importância idêntica); único candidato de Cerrado/Centro-Oeste do tier 1."
    ),
}


def main() -> None:
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from sentinela.sites import v1_caixa_brasil, v4_colisoes, v5_distancia

    with CSV_PATH.open("r", encoding="utf-8") as f:
        candidatos = {row["aoi_id"]: row for row in csv.DictReader(f) if row["elegivel"] == "True"}

    assert len(candidatos) == 16, f"esperado 16 AOIs elegíveis, achei {len(candidatos)}"

    resultado_v2 = json.loads(
        (REPO_ROOT / "data" / "interim" / "sv25_v2_reverse_geocode.json").read_text(encoding="utf-8")
    )
    resultado_v3 = json.loads(
        (REPO_ROOT / "data" / "interim" / "sv25_v3_mapbiomas.json").read_text(encoding="utf-8")
    )

    sites: list[dict] = []
    for aoi_id, row in candidatos.items():
        coord = COORD_EXISTENTE.get(aoi_id) or COORD_NOVA[aoi_id]
        lat, lon = coord["lat"], coord["lon"]

        v1_ok = v1_caixa_brasil(lat, lon)

        v2_info = resultado_v2[aoi_id]
        municipio_geo = (v2_info["municipio_geocodificado"] or "").strip()
        v2_ok = municipio_geo.lower() == row["municipio"].strip().lower()

        v3_info = resultado_v3[aoi_id]

        props = {
            "site_id": aoi_id,
            "nome": row["nome_exibicao"],
            "operador": row["operador"],
            "municipio": row["municipio"],
            "uf": row["uf"],
            "lat": lat,
            "lon": lon,
            "buffer_km": BUFFER_KM,
            "fonte_coordenada": coord["fonte_coordenada"],
            "ano_inicio_operacao_estimado": int(row["ano_operacao_min"]) if row["ano_operacao_min"] else None,
            "ativo": True,
            # --- novos campos de expansão (ADR-005 / SV-25) ---
            "tier": int(row["tier"]),
            "regiao": row["regiao"],
            "bioma": row["bioma_estimado"],
            "metodo_coordenada": coord["metodo_coordenada"],
            "precisao_coordenada": coord["precisao_coordenada"],
            "data_consulta": coord.get("data_consulta", DATA_CONSULTA_HOJE),
            "ano_inicio_obra": int(row["ano_construcao_min"]) if row["ano_construcao_min"] else None,
            "periodo_pre": row["periodo_pre"] or None,
            "periodo_durante": row["periodo_durante"] or None,
            "periodo_pos": row["periodo_pos"] or None,
            "n_predios": int(row["n_predios"]),
            # --- verificação automática (V1-V5), gravada para tests/test_sites.py e auditoria ---
            "v1_aprovado": v1_ok,
            "v2_aprovado": v2_ok,
            "v2_municipio_geocodificado": municipio_geo or None,
            "v3_nao_aplicavel": False,
            "v3_aprovado": v3_info["aprovado"],
            "v3_pct_construida_solo_500m": v3_info["pct_construida_solo_exposto"],
            "v3_ano_mapbiomas": v3_info["ano_mapbiomas"],
            # v4 preenchido abaixo, depois de ter todos os sites carregados
            "fila_visual": aoi_id in FILA_VISUAL_PRECAUCAO,
            "motivo_fila_visual": FILA_VISUAL_PRECAUCAO.get(aoi_id),
            "observacao": coord.get("observacao_extra"),
        }
        sites.append(props)

    # V4 — colisão de AOI (<5 km), calculada sobre TODAS as 16 AOIs simultaneamente.
    colisoes = v4_colisoes(sites)
    for props in sites:
        pares = colisoes[props["site_id"]]
        props["v4_colisoes"] = ";".join(f"{outro}:{d}km" for outro, d in pares) or None
        props["v4_aprovado"] = True  # V4 nunca reprova sozinha — colisão exige decisão, não rejeição
        if pares:
            decisao = (
                f"Colisão V4 com {', '.join(o for o, _ in pares)} "
                f"({', '.join(f'{d} km' for _, d in pares)}) — decidido manter ambas ativas "
                "(operadores/campi distintos no mesmo polo industrial; buffer de 5 km cobre as duas "
                "sem perda de sinal agregado). Ver observacao de cada AOI envolvida para o raciocínio "
                "completo."
            )
            props["observacao_v4"] = decisao

    # V5 — distância à coordenada já conhecida (lista_20/SV-24), só onde existe referência.
    for props in sites:
        ref = REFERENCIA_V5.get(props["site_id"])
        if ref is None:
            props["v5_aprovado"] = None
            props["v5_distancia_km"] = None
            continue
        d, ok = v5_distancia(props["lat"], props["lon"], ref[0], ref[1])
        props["v5_distancia_km"] = d
        props["v5_aprovado"] = ok

    # --- checagens de sanidade antes de escrever (falha alto e cedo, não silenciosamente) ---
    for props in sites:
        assert props["v1_aprovado"], f"{props['site_id']}: V1 reprovou — não deveria estar ativo"
        assert props["v2_aprovado"], f"{props['site_id']}: V2 reprovou — não deveria estar ativo"
        assert props["v3_aprovado"] or props["v3_nao_aplicavel"], f"{props['site_id']}: V3 reprovou sem justificativa"
        for campo in ("metodo_coordenada", "precisao_coordenada", "fonte_coordenada", "data_consulta"):
            assert props[campo], f"{props['site_id']}: campo de proveniência '{campo}' vazio"

    # --- as 3 AOIs originais continuam com site_id/lat/lon/buffer_km inalterados (checagem direta) ---
    originais_esperados = {
        "ascenty-vinhedo": (-23.0700044, -47.0118926),
        "odata-hortolandia": (-22.8995299, -47.1952611),
        "scala-tambore": (-23.4948321, -46.8130769),
    }
    for props in sites:
        if props["site_id"] in originais_esperados:
            lat_esp, lon_esp = originais_esperados[props["site_id"]]
            assert props["lat"] == lat_esp and props["lon"] == lon_esp and props["buffer_km"] == BUFFER_KM

    features = []
    for props in sites:
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
            }
        )
    # ordem estável: tier, depois site_id
    features.sort(key=lambda ft: (ft["properties"]["tier"], ft["properties"]["site_id"]))

    fc = {"type": "FeatureCollection", "features": features}
    GEOJSON_PATH.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gravado {GEOJSON_PATH} com {len(features)} AOIs ativas.")

    _escrever_fila_md(sites, candidatos)
    _imprimir_resumo(sites, colisoes)


def _escrever_fila_md(sites: list[dict], candidatos: dict) -> None:
    linhas = [
        "# Fila de conferência visual — coordenadas (SV-25)",
        "",
        (
            "Gerada automaticamente por `scripts/validar_coordenadas_sv25.py`. Cada AOI abaixo passou "
            "em V1-V5 (nenhuma foi reprovada pela verificação automática), mas foi incluída aqui por "
            "**precaução do agente que rodou a cascata** — não pela regra padrão do nível D do enunciado "
            "(que só coloca na fila o que sobrou de A-C ou reprovou em V3). Ver o motivo específico de "
            "cada uma na tabela e em `properties.observacao`/`properties.motivo_fila_visual` de "
            "`config/sites.geojson`."
        ),
        "",
        (
            "**Status desta fila nesta rodada:** as imagens foram geradas e uma primeira leitura visual "
            "já foi feita pelo agente Claude que coordenou esta tarefa (não pelo usuário humano) — ver "
            "notas de leitura na coluna correspondente. **Nenhum item está marcado como conferido "
            "definitivamente** — os 3 casos ficam pendentes de decisão do usuário antes de comprometer "
            "orçamento de rotulagem manual nessas AOIs específicas (as outras 13 AOIs não dependem desta "
            "fila)."
        ),
        "",
        "| # | aoi_id | município/UF | endereço-fonte | motivo na fila | leitura visual do agente | conferido |",
        "|---|--------|--------------|-----------------|-----------------|---------------------------|-----------|",
    ]
    leituras = {
        "ascenty-sumare": (
            "Ponto cai a poucos metros da Rodovia Anhanguera, entre um pátio/galpões amarelados a "
            "oeste e quarteirões residenciais a leste/sul; não há um prédio isolado claramente maior "
            "que os vizinhos sob o marcador na resolução Sentinel-2 (10 m). Plausível mas não "
            "confirmável com certeza nesta resolução."
        ),
        "ascenty-paulinia": (
            "Ponto cai perto de um cruzamento de vias e de um curso d'água, com telhados residenciais "
            "ao redor e alguns telhados maiores (industriais) a nordeste. Não há um prédio isolado "
            "obviamente maior sob o marcador; consistente com estar próximo da subestação, não "
            "necessariamente sobre o prédio do data center."
        ),
        "everest-goiania": (
            "Ponto cai em quarteirão urbano denso do Jardim Goiás, próximo a um estádio visível no "
            "canto do recorte — compatível com a descrição de 'prédio-sede com data center integrado' "
            "em área comercial/urbana consolidada, mas não é possível confirmar QUAL prédio do "
            "quarteirão é o correto nesta resolução."
        ),
    }
    for i, aoi_id in enumerate(sorted(FILA_VISUAL_PRECAUCAO), start=1):
        row = candidatos[aoi_id]
        site = next(s for s in sites if s["site_id"] == aoi_id)
        linhas.append(
            f"| {i} | `{aoi_id}` | {row['municipio']}/{row['uf']} | {site['fonte_coordenada']} | "
            f"{FILA_VISUAL_PRECAUCAO[aoi_id]} | {leituras[aoi_id]} | [ ] pendente (decisão do usuário) |"
        )
    linhas += [
        "",
        (
            "Imagens: `reports/figures/coordenadas/{aoi_id}.png` (painel esquerdo: recorte ~2x2 km "
            "centrado no ponto; painel direito: contexto mais amplo com o buffer de 5 km desenhado)."
        ),
        "",
        (
            f"Total na fila: **{len(FILA_VISUAL_PRECAUCAO)}** (meta do enunciado: no máximo 8 — não "
            "atingida, não é preciso kill-switch)."
        ),
    ]
    FILA_MD_PATH.write_text("\n".join(linhas), encoding="utf-8")
    print(f"Gravado {FILA_MD_PATH}.")


def _imprimir_resumo(sites: list[dict], colisoes: dict) -> None:
    print()
    print("=" * 100)
    print(f"{'aoi_id':28s} {'metodo':10s} {'precisao':11s} V1 V2 V3 V4 V5")
    print("-" * 100)
    for s in sorted(sites, key=lambda x: x["site_id"]):
        v5 = "-" if s["v5_aprovado"] is None else ("OK" if s["v5_aprovado"] else "FALHOU")
        print(
            f"{s['site_id']:28s} {s['metodo_coordenada']:10s} {s['precisao_coordenada']:11s} "
            f"{'OK' if s['v1_aprovado'] else 'X':2s} {'OK' if s['v2_aprovado'] else 'X':2s} "
            f"{'OK' if s['v3_aprovado'] else 'X':2s} "
            f"{'COLIDE' if colisoes[s['site_id']] else 'OK':6s} {v5}"
        )
    print("=" * 100)
    n_tier1 = sum(1 for s in sites if s["tier"] == 1)
    n_tier2 = sum(1 for s in sites if s["tier"] == 2)
    n_a = sum(1 for s in sites if s["metodo_coordenada"] == "peeringdb")
    n_b = sum(1 for s in sites if s["metodo_coordenada"] == "osm")
    n_c = sum(1 for s in sites if s["metodo_coordenada"] == "geocode")
    n_manual = sum(1 for s in sites if s["metodo_coordenada"] == "manual")
    print(f"tier1={n_tier1} tier2={n_tier2} total_ativo={len(sites)}")
    print(f"nivel A (peeringdb)={n_a} nivel B (osm)={n_b} nivel C (geocode)={n_c} manual(existente)={n_manual}")
    print(f"fila visual (precaução): {len(FILA_VISUAL_PRECAUCAO)} -> {sorted(FILA_VISUAL_PRECAUCAO)}")


if __name__ == "__main__":
    main()
