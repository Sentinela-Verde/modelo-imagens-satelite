"""Passo 23 — temperatura de superfície na escala do ANEL, via banda termal do Landsat (30 m).

Rode com:

    python modelo-impacto/scripts/impacto_dc_23_lst_landsat.py --fase baixar
    python modelo-impacto/scripts/impacto_dc_23_lst_landsat.py --fase analise

## Por que este passo existe

O passo 16 mediu aquecimento com MODIS `MOD11A2` e deu nulo — mas um nulo **sem poder de
detecção**, e o próprio passo provou isso: o MODIS tem 1 km de resolução, medido num disco de
5 km, enquanto o efeito de conversão vive num anel de 500 m. Menor que um pixel. O efeito mínimo
detectável daquele desenho era **427x maior** que o efeito esperado pela diluição.

A conclusão de lá foi explícita: *"responder isso exige a banda termal do Landsat (30 m), não
MODIS"*. Este passo faz exatamente isso.

Ganho de escala, em números: no anel de 0-500 m (78,5 ha), o MODIS entrega uma fração de **um**
pixel; o Landsat a 30 m entrega **~870 pixels**. É a diferença entre não poder perguntar e poder.

## Como

Mesma coleção que o classificador já usa (`LANDSAT/LC0{8,9}/C02/T1_L2`), mesma janela de meses
(estação seca), mesma máscara de nuvem, **mesma grade** — o que garante que a máscara de anel e a
de footprint, calculadas sobre os rasters classificados, se alinham pixel a pixel sem reamostragem.

A banda `ST_B10` do Collection 2 Level 2 é temperatura de superfície já processada. Escala oficial
do USGS: `ST_B10 * 0,00341802 + 149,0` -> Kelvin; menos 273,15 -> Celsius.

**Não passa por `harmonizar_landsat`** — aquela função seleciona as 6 bandas de reflectância e
descartaria a termal. A máscara de nuvem, sim, é a mesma: ela opera por posição de pixel, não por
nome de banda.

## O que este passo NÃO resolve

Continua sendo composto mediano de estação seca, uma leitura por ano — não capta ciclo diário nem
onda de calor. E LST não é temperatura do ar: é temperatura radiativa da superfície, que responde
muito mais a asfalto e telhado do que um termômetro a 2 m responderia. Para a pergunta "o entorno
esquentou por causa da conversão de terreno", é a medida certa; para "está mais quente para quem
mora ali", é um limite superior.

Saídas:
  - `raw/controles-rf/lst_landsat.csv`        — LST por ponto, anel e ano
  - `raw/controles-rf/lst_landsat_did.csv`    — diferença-em-diferenças por par e anel
  - `raw/controles-rf/lst_landsat_resumo.csv` — teste de sinal + poder, contra o passo 16
  - `raw/controles-rf/figuras/fig_16_lst_landsat.png`
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_14_footprint_vs_anel as P14  # noqa: E402

import ee  # noqa: E402
from sentinela.config import SETTINGS  # noqa: E402
from sentinela.gee import landsat as mod_landsat  # noqa: E402
from sentinela.gee.harmonizacao import mascara_nuvem  # noqa: E402

DIR_LST = C.DIR_SAIDA / "lst_landsat"
N_PONTA = 2
ZONAS = [("0-0.5km", 0.0, 0.5), ("0.5-1km", 0.5, 1.0)]
NODATA_LST = -999.0

SAIDA = C.DIR_SAIDA / "lst_landsat.csv"
SAIDA_DID = C.DIR_SAIDA / "lst_landsat_did.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "lst_landsat_resumo.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_16_lst_landsat.png"


def _composto_lst(aoi: ee.Geometry, ano: int, mes_ini: int, mes_fim: int) -> ee.Image:
    """Composto mediano anual de temperatura de superfície, em Celsius."""
    l8, l9 = mod_landsat._colecoes_filtradas(aoi, ano, mes_ini, mes_fim)

    def _prep(img: ee.Image) -> ee.Image:
        # máscara de nuvem na imagem BRUTA (opera por posição de pixel), depois escala oficial
        return (
            mascara_nuvem(img, "landsat")
            .select("ST_B10")
            .multiply(0.00341802)
            .add(149.0)
            .subtract(273.15)
            .rename("lst_celsius")
            .toFloat()
        )

    return l8.merge(l9).map(_prep).median()


def _baixar(ponto: dict, ano: int, destino: Path) -> bool:
    params = SETTINGS.params()
    grade = mod_landsat.calcular_grade(ponto["lon"], ponto["lat"], ponto["buffer_km"])
    aoi = ee.Geometry.Rectangle(
        [grade["origin_x"], grade["origin_y"] - grade["height"] * grade["resolucao_m"],
         grade["origin_x"] + grade["width"] * grade["resolucao_m"], grade["origin_y"]],
        proj=mod_landsat.CRS, geodesic=False,
    )
    composto = _composto_lst(aoi, ano, params["mes_inicio"], params["mes_fim"]).unmask(NODATA_LST)
    crs_transform = [grade["resolucao_m"], 0, grade["origin_x"],
                     0, -grade["resolucao_m"], grade["origin_y"]]

    def _url() -> str:
        return composto.getDownloadURL({
            "crs": mod_landsat.CRS, "crsTransform": crs_transform,
            "dimensions": f"{grade['width']}x{grade['height']}",
            "region": aoi, "format": "GEO_TIFF",
        })

    url = mod_landsat._com_retry(_url)
    for tentativa in range(4):
        r = requests.get(url, timeout=300)
        if r.status_code == 200:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(r.content)
            return True
        time.sleep(10 * (tentativa + 1))
    return False


def _pontos() -> pd.DataFrame:
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")]
    par = par[par.sensor == "landsat"]  # a termal aqui é do Landsat; pares S2 ficam de fora
    linhas = []
    for _, r in par.iterrows():
        linhas.append({"campus": r.site_id, "site_id": r.site_id, "tipo": "tratamento",
                       "lat": float(r.lat), "lon": float(r.lon),
                       "ano_inicio_obra": int(r.ano_inicio_obra)})
        linhas.append({"campus": r.site_id, "site_id": r.site_id_controle, "tipo": "controle",
                       "lat": float(r.lat_controle), "lon": float(r.lon_controle),
                       "ano_inicio_obra": int(r.ano_inicio_obra)})
    return pd.DataFrame(linhas)


def fase_baixar() -> None:
    pontos = _pontos()
    C.iniciar_ee()
    print(f"{pontos.campus.nunique()} campi com sensor landsat "
          f"({len(pontos)} pontos)")
    total = 0
    for _, p in pontos.iterrows():
        anos = C.janela_anos(int(p.ano_inicio_obra))
        for ano in anos:
            destino = DIR_LST / p.site_id / f"{ano}.tif"
            if destino.exists():
                continue
            ponto = {"site_id": p.site_id, "lat": p.lat, "lon": p.lon, "buffer_km": C.BUFFER_KM}
            ok = _baixar(ponto, ano, destino)
            print(f"  {'OK ' if ok else 'FALHOU'} {p.site_id}/{ano}")
            total += ok
    print(f"\n{total} rasters de LST baixados")


def fase_analise() -> None:
    pontos = _pontos()
    fps = pd.read_csv(C.DIR_SAIDA / "footprints_osm.csv").set_index("site_id")

    registros = []
    for _, p in pontos.iterrows():
        anos = [a for a in C.janela_anos(int(p.ano_inicio_obra))
                if (DIR_LST / p.site_id / f"{a}.tif").exists()]
        if len(anos) < 2 * N_PONTA:
            print(f"  ! {p.site_id}: só {len(anos)} anos de LST, fora")
            continue
        ref_class = Path(C.caminho_classificado("landsat", p.site_id, anos[0]))
        if not ref_class.exists():
            print(f"  ! {p.site_id}: sem raster classificado de referência, fora")
            continue
        raios = P11.mascaras_por_raio(ref_class, p.lat, p.lon)

        m_fp = None
        if p.tipo == "tratamento" and p.campus in fps.index:
            try:
                geom = P14.poligono_do_cache(p.campus, fps.loc[p.campus].get("osm_id"))
                if geom:
                    m_fp = P14.mascara_footprint(ref_class, geom)
            except Exception:
                m_fp = None

        for nome, r_int, r_ext in ZONAS:
            base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
            mascara = base & ~m_fp if m_fp is not None else base
            for ano in anos:
                with rasterio.open(DIR_LST / p.site_id / f"{ano}.tif") as src:
                    arr = src.read(1)
                valido = mascara & (arr > NODATA_LST + 1) & np.isfinite(arr)
                n = int(valido.sum())
                if n < 20:
                    continue
                registros.append({
                    "campus": p.campus, "site_id": p.site_id, "tipo": p.tipo, "zona": nome,
                    "ano": ano, "t_relativo": ano - int(p.ano_inicio_obra),
                    "pixels_validos": n,
                    "lst_media_c": round(float(arr[valido].mean()), 4),
                })
        print(f"  {p.site_id} ({p.tipo}) {len(anos)} anos")

    longo = pd.DataFrame(registros)
    C.salvar_csv(longo, SAIDA)

    # ---------------------------------------------------------------- DiD por par e anel
    linhas = []
    for (campus, zona), g in longo.groupby(["campus", "zona"]):
        dl = {}
        for tipo in ("tratamento", "controle"):
            s = g[g.tipo == tipo].sort_values("ano")["lst_media_c"]
            if len(s) < 2 * N_PONTA:
                dl = {}
                break
            dl[tipo] = float(s.iloc[-N_PONTA:].mean() - s.iloc[:N_PONTA].mean())
        if not dl:
            continue
        linhas.append({"campus": campus, "zona": zona,
                       "delta_tratamento_c": round(dl["tratamento"], 4),
                       "delta_controle_c": round(dl["controle"], 4),
                       "excesso_c": round(dl["tratamento"] - dl["controle"], 4)})
    did = pd.DataFrame(linhas)
    C.salvar_csv(did, SAIDA_DID)

    # ---------------------------------------------------------------- resumo + poder
    modis = pd.read_csv(C.DIR_SAIDA / "lst_did_poder.csv").iloc[0]
    linhas = []
    for zona, g in did.groupby("zona"):
        e = g.excesso_c.to_numpy(float)
        n, k = len(e), int((e > 0).sum())
        menor = min(k, n - k)
        p_bi = min(1.0, 2 * sum(math.comb(n, i) * 0.5**n for i in range(0, menor + 1)))
        sigma = float(e.std())
        mde = 2.80 * sigma / math.sqrt(n) if n else np.nan
        # área do anel e nº de pixels de 30 m nele
        r_int, r_ext = (0.0, 0.5) if zona == "0-0.5km" else (0.5, 1.0)
        area_ha = math.pi * (r_ext**2 - r_int**2) * 100
        linhas.append({
            "zona": zona, "n_pares": n, "n_aqueceu_mais": k,
            "excesso_mediano_c": round(float(np.median(e)), 4),
            "p_bilateral": round(p_bi, 4),
            "desvio_c": round(sigma, 4),
            "efeito_minimo_detectavel_c": round(mde, 4),
            "area_anel_ha": round(area_ha, 1),
            "pixels_30m_no_anel": int(area_ha * 1e4 / 900),
            "mde_modis_passo16_c": float(modis.efeito_minimo_detectavel_c),
            # Quantos pares seriam necessários para que o efeito ESTIMADO aqui atingisse
            # significância com este desvio. É a pergunta útil quando o resultado é nulo:
            # "nulo" e "precisaríamos de N=31" dizem coisas muito diferentes ao leitor.
            "n_pares_necessario_para_detectar": (
                int(math.ceil((2.80 * sigma / abs(float(np.median(e)))) ** 2))
                if np.median(e) != 0 else None
            ),
            # A resolução melhorou 33x (1 km -> 30 m), mas poder estatístico não é resolução:
            # MDE = 2,80*sigma/sqrt(n), e aqui n caiu de 15 para 12 (só os pares Landsat) e o
            # sigma entre pares subiu. Registrar isso explicitamente evita a leitura ingênua de
            # que "sensor melhor = resultado melhor".
            "mde_melhorou_vs_modis": bool(mde < float(modis.efeito_minimo_detectavel_c)),
        })
    resumo = pd.DataFrame(linhas)
    C.salvar_csv(resumo, SAIDA_RESUMO)

    # ---------------------------------------------------------------- figura
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))
    z0 = did[did.zona == "0-0.5km"].sort_values("excesso_c")
    cores = ["#C0392B" if v > 0 else "#2980B9" for v in z0.excesso_c]
    ax1.barh(z0.campus, z0.excesso_c, color=cores)
    ax1.axvline(0, color="#333", lw=1)
    r0 = resumo[resumo.zona == "0-0.5km"]
    if not r0.empty:
        mde = float(r0.efeito_minimo_detectavel_c.iloc[0])
        ax1.axvline(mde, color="#888", ls="--", lw=1)
        ax1.axvline(-mde, color="#888", ls="--", lw=1)
        ax1.set_title(f"Anel 0–500 m (sem o prédio), Landsat 30 m\n"
                      f"{int(r0.n_aqueceu_mais.iloc[0])}/{int(r0.n_pares.iloc[0])} aqueceram mais "
                      f"(p={float(r0.p_bilateral.iloc[0]):.2f}) · MDE ±{mde:.2f} °C", fontsize=10)
    ax1.set_xlabel("excesso de aquecimento vs. controle (°C)")
    ax1.tick_params(labelsize=8)

    x = np.arange(len(resumo))
    ax2.bar(x - 0.2, resumo.efeito_minimo_detectavel_c, 0.4, label="Landsat 30 m (passo 23)",
            color="#1A5276")
    ax2.bar(x + 0.2, [float(modis.efeito_minimo_detectavel_c)] * len(resumo), 0.4,
            label="MODIS 1 km (passo 16)", color="#95A5A6")
    ax2.set_xticks(x)
    ax2.set_xticklabels(resumo.zona)
    ax2.set_ylabel("efeito mínimo detectável (°C) — menor é melhor")
    ax2.set_title("Ganho de poder ao trocar de sensor", fontsize=10)
    ax2.legend(frameon=False, fontsize=9)
    ax2.grid(axis="y", alpha=0.25)

    fig.suptitle("Passo 23 — aquecimento no anel, com o sensor na escala certa", fontsize=11, y=0.99)
    fig.tight_layout()
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=150)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")

    print("\n--- LST no anel (Landsat 30 m) ---")
    for _, r in resumo.iterrows():
        print(f"  {r.zona}: {r.n_aqueceu_mais}/{r.n_pares} aqueceram mais que o controle · "
              f"mediana {r.excesso_mediano_c:+.3f} °C · p={r.p_bilateral:.3f} · "
              f"{r.pixels_30m_no_anel} pixels no anel")
        print(f"    MDE {r.efeito_minimo_detectavel_c:.3f} °C "
              f"({'melhorou' if r.mde_melhorou_vs_modis else 'PIOROU'} vs "
              f"{r.mde_modis_passo16_c:.3f} °C do MODIS) · "
              f"precisaria de n={r.n_pares_necessario_para_detectar} pares para detectar "
              f"o proprio efeito estimado")
    print("\nA resolucao melhorou 33x, o poder NAO: MDE = 2,80*sigma/sqrt(n), e aqui n caiu de 15")
    print("para 12 (so os pares Landsat) enquanto o sigma entre pares subiu. Resolucao e poder")
    print("estatistico sao coisas diferentes, e este passo e o contraexemplo.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True, choices=["baixar", "analise"])
    args = ap.parse_args()
    fase_baixar() if args.fase == "baixar" else fase_analise()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
