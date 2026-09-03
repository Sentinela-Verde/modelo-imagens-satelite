"""Extrai temperatura de superfície (LST) via Google Earth Engine para os sites de
`config/sites.geojson`, dentro do buffer de cada site (campo `buffer_km`, 5 km para todos
atualmente), para os anos 2016-2025 (ajustado automaticamente se a coleção não cobrir algum ano).

Apoio ao modelo de impacto do Guilherme (frente separada do classificador principal deste
repositório — ver `dados-modelo-impacto/README.md`). NÃO mexe em `src/sentinela/`, `data/`,
`models/` ou `outputs/` do classificador.

Fonte: MODIS/061/MOD11A2 (Terra, LST diurna, composto de 8 dias, 1 km, banda `LST_Day_1km`).
Justificativa da escolha e detalhes de metodologia completos em
`dados-modelo-impacto/raw/temperatura/METODOLOGIA.md`.

Método de agregação anual: para cada site/ano, cada cena do composto de 8 dias é reduzida a uma
média regional (média dos pixels válidos dentro do buffer, `ee.Reducer.mean()`, escala nativa
1000 m). Cenas 100% nubladas dentro do buffer não produzem valor (o GEE já descarta via
`aggregate_array`, que ignora nulos). A média anual reportada é a média simples dessas médias de
cena — "média das médias" no sentido de: 1 valor por cena de 8 dias, depois média dessas cenas ao
longo do ano (não é média por mês; um ano tem ~46 cenas de 8 dias, não 12 meses, então agregar por
cena já dá uma ponderação praticamente uniforme ao longo do ano, sem precisar do passo intermediário
por mês). `n_observacoes` = número de cenas de 8 dias com pelo menos 1 pixel válido no buffer,
naquele ano — usar para desconfiar de médias baseadas em poucas cenas (nuvem persistente).

Reprodutível: se a lista de sites em `config/sites.geojson` crescer (ex.: quando o levantamento do
Guilherme via datacentermap.com com ~20 facilities estiver pronto), basta rodar de novo — o script
sobrescreve `processed/temperatura_lst.csv` e os artefatos brutos em `raw/temperatura/` com o
estado atual de `config/sites.geojson`.

Uso:
    .venv\\Scripts\\python.exe dados-modelo-impacto\\scripts\\extrair_temperatura_lst.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sentinela.gee.auth import init_ee  # noqa: E402

import ee  # noqa: E402

SITES_PATH = REPO_ROOT / "config" / "sites.geojson"
APOIO_DIR = REPO_ROOT / "dados-modelo-impacto"
PROCESSED_CSV = APOIO_DIR / "processed" / "temperatura_lst.csv"
RAW_DIR = APOIO_DIR / "raw" / "temperatura"
RAW_CENAS_CSV = RAW_DIR / "lst_cenas_brutas.csv"
RAW_LOG_JSON = RAW_DIR / "log_extracao.json"

COLLECTION_ID = "MODIS/061/MOD11A2"
BAND = "LST_Day_1km"
SCALE_FACTOR = 0.02
KELVIN_OFFSET = 273.15
NATIVE_SCALE_M = 1000
FONTE = "MODIS/Terra"

ANO_INICIO = 2016
ANO_FIM = 2025

# Sanity check documentado no pedido: LST de superfície no Brasil deveria ficar ~15-45 C.
# Fora dessa faixa é sinal de erro de escala/unidade, mas não é bloqueante (LST pode
# legitimamente passar de 45 C em solo exposto/urbano denso em dias quentes) — só reportar.
FAIXA_SANIDADE_C = (10.0, 50.0)


def carregar_sites(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sites = []
    for feat in data["features"]:
        props = feat["properties"]
        lon_geom, lat_geom = feat["geometry"]["coordinates"]
        sites.append(
            {
                "site_id": props["site_id"],
                "municipio": props.get("municipio"),
                "uf": props.get("uf"),
                "lat": props.get("lat", lat_geom),
                "lon": props.get("lon", lon_geom),
                "buffer_km": props.get("buffer_km", 5),
            }
        )
    return sites


def extrair_valores_ano(buffer_geom: "ee.Geometry", ano: int) -> list[float]:
    """Lista de médias regionais de LST (Celsius), uma por cena MOD11A2 (composto de 8 dias)
    com pelo menos 1 pixel válido dentro do buffer, no ano informado. Cenas sem pixel válido
    (100% nublado no buffer) são automaticamente omitidas pelo aggregate_array do GEE."""
    ic = (
        ee.ImageCollection(COLLECTION_ID)
        .select(BAND)
        .filterDate(f"{ano}-01-01", f"{ano + 1}-01-01")
        .filterBounds(buffer_geom)
    )

    def com_media_regional(img):
        celsius = img.multiply(SCALE_FACTOR).subtract(KELVIN_OFFSET)
        estat = celsius.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=buffer_geom,
            scale=NATIVE_SCALE_M,
            maxPixels=1_000_000_000,
            bestEffort=True,
        )
        return img.set("lst_c", estat.get(BAND))

    valores = ic.map(com_media_regional).aggregate_array("lst_c").getInfo()
    return [v for v in valores if v is not None]


def main() -> None:
    print("Inicializando Google Earth Engine...")
    init_ee()

    sites = carregar_sites(SITES_PATH)
    print(f"{len(sites)} sites carregados de {SITES_PATH}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)

    data_extracao = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    linhas_processed: list[dict] = []
    linhas_raw: list[dict] = []
    avisos: list[str] = []
    todos_valores: list[float] = []

    for i, site in enumerate(sites, start=1):
        site_id = site["site_id"]
        lon, lat = site["lon"], site["lat"]
        buffer_km = site["buffer_km"]
        buffer_geom = ee.Geometry.Point([lon, lat]).buffer(buffer_km * 1000)

        print(
            f"\n=== [{i}/{len(sites)}] {site_id} ({site['municipio']}/{site['uf']}) "
            f"— buffer {buffer_km} km ==="
        )

        for ano in range(ANO_INICIO, ANO_FIM + 1):
            try:
                valores = extrair_valores_ano(buffer_geom, ano)
            except Exception as e:  # noqa: BLE001 — relatar e seguir para o próximo ano/site
                msg = f"{site_id}/{ano}: ERRO na extração — {e}"
                print(f"  {ano}: ERRO — {e}")
                avisos.append(msg)
                continue

            n_obs = len(valores)
            media = round(sum(valores) / n_obs, 2) if n_obs > 0 else None

            if n_obs == 0:
                aviso = f"{site_id}/{ano}: 0 cenas válidas (sem dado ou 100% nublado no buffer)"
                print(f"  {ano}: 0 observações válidas")
                avisos.append(aviso)
            else:
                sinal_baixa_cobertura = " [COBERTURA BAIXA]" if n_obs < 20 else ""
                print(f"  {ano}: {media:.2f} C (n={n_obs} cenas){sinal_baixa_cobertura}")
                if n_obs < 20:
                    avisos.append(
                        f"{site_id}/{ano}: cobertura baixa, n_observacoes={n_obs} "
                        f"(esperado ~40-46 cenas/ano para MOD11A2)"
                    )
                if not (FAIXA_SANIDADE_C[0] <= media <= FAIXA_SANIDADE_C[1]):
                    avisos.append(
                        f"{site_id}/{ano}: media {media} C fora da faixa de sanidade "
                        f"{FAIXA_SANIDADE_C} — checar escala/unidade"
                    )
                todos_valores.extend(valores)

            linhas_processed.append(
                {
                    "site_id": site_id,
                    "municipio": site["municipio"],
                    "uf": site["uf"],
                    "ano": ano,
                    "lst_media_celsius": "" if media is None else media,
                    "n_observacoes": n_obs,
                    "fonte": FONTE,
                    "colecao_gee": COLLECTION_ID,
                    "data_extracao": data_extracao,
                }
            )

            for v in valores:
                linhas_raw.append({"site_id": site_id, "ano": ano, "lst_celsius": round(v, 3)})

    # --- grava processed/temperatura_lst.csv ---
    campos_processed = [
        "site_id",
        "municipio",
        "uf",
        "ano",
        "lst_media_celsius",
        "n_observacoes",
        "fonte",
        "colecao_gee",
        "data_extracao",
    ]
    with PROCESSED_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos_processed)
        writer.writeheader()
        writer.writerows(linhas_processed)
    print(f"\nSalvo: {PROCESSED_CSV} ({len(linhas_processed)} linhas)")

    # --- grava raw/temperatura/lst_cenas_brutas.csv (granularidade fina, auditoria) ---
    with RAW_CENAS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["site_id", "ano", "lst_celsius"])
        writer.writeheader()
        writer.writerows(linhas_raw)
    print(f"Salvo: {RAW_CENAS_CSV} ({len(linhas_raw)} linhas — 1 por cena de 8 dias)")

    # --- grava log de extração (avisos, sanity check, contagens) ---
    log = {
        "data_extracao": data_extracao,
        "colecao_gee": COLLECTION_ID,
        "banda": BAND,
        "n_sites": len(sites),
        "anos": [ANO_INICIO, ANO_FIM],
        "n_site_ano_esperado": len(sites) * (ANO_FIM - ANO_INICIO + 1),
        "n_site_ano_com_dado": sum(1 for r in linhas_processed if r["lst_media_celsius"] != ""),
        "n_site_ano_sem_dado": sum(1 for r in linhas_processed if r["lst_media_celsius"] == ""),
        "faixa_valores_encontrada_celsius": (
            [round(min(todos_valores), 2), round(max(todos_valores), 2)] if todos_valores else None
        ),
        "faixa_sanidade_celsius": list(FAIXA_SANIDADE_C),
        "avisos": avisos,
    }
    with RAW_LOG_JSON.open("w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {RAW_LOG_JSON}")

    print(f"\n{len(avisos)} avisos registrados (cobertura baixa / sem dado / fora da faixa).")
    if todos_valores:
        print(
            f"Faixa de valores de cena encontrada: "
            f"{min(todos_valores):.2f} C a {max(todos_valores):.2f} C"
        )


if __name__ == "__main__":
    main()
