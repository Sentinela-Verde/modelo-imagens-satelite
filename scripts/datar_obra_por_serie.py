"""Script ad-hoc — testa se dá para DATAR o fim da obra de um data center a partir da série de
classes já classificada, e compara três montagens de série para isolar o efeito do degrau de sensor:

  serie_mista     Landsat 2013-2018 + Sentinel-2 2019-2025  (a série oficial de SV-15)
  serie_landsat   Landsat 2013-2021                          (sensor único, sem degrau)
  serie_s2        Sentinel-2 2019-2025                       (sensor único, sem degrau)

NÃO reclassifica e NÃO retreina nada — lê `outputs/nucleo_{raio}m_por_ano.csv`
(gerado por scripts/nucleo_datacenter_por_ano.py) e aplica os detectores abaixo.

Detectores (todos operam só dentro de uma série, nunca cruzando eras):
  pico_solo      ano de máximo de `pct_solo_exposto_obras`  -> proxy do auge do canteiro
  recuo_solo     1o ano após o pico em que o solo exposto recua até metade do caminho de volta
                 ao baseline do próprio site -> proxy do fim da obra
  passo_constr   ano t que maximiza  media(construida[t..t+2]) - media(construida[t-3..t-1])
                 -> proxy do ano em que a área construída sobe de patamar

Verdade de referência: `ano_inicio_operacao_estimado` de config/sites.geojson (SV-24). Um site só
entra no placar de uma série se o ano-verdade cair DENTRO da janela daquela série com pelo menos um
ano anterior disponível — senão o detector não teria como acertar e o placar viraria ficção.

Uso:  python scripts/datar_obra_por_serie.py [raio_m]   (padrão 500)
Gera: outputs/datacao_obra_comparacao.csv  + resumo no stdout
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]


def _serie(df: pd.DataFrame, nome: str) -> pd.DataFrame:
    """Recorta uma das três montagens de série a partir da tabela núcleo."""
    if nome == "serie_mista":
        return df[df.faixa_oficial]
    if nome == "serie_landsat":
        return df[df.sensor == "landsat"]
    if nome == "serie_s2":
        return df[df.sensor == "sentinel2"]
    raise ValueError(nome)


def detectar(g: pd.DataFrame) -> dict:
    """Aplica os três detectores a uma série de um site já ordenada por ano."""
    g = g.sort_values("ano")
    anos = g.ano.tolist()
    solo = g.pct_solo_exposto_obras.tolist()
    con = g.pct_construida_urbana.tolist()

    i_pico = solo.index(max(solo))
    ano_pico = anos[i_pico]

    # baseline do proprio site = mediana dos anos fora do entorno do pico
    fora = [s for j, s in enumerate(solo) if abs(j - i_pico) > 1] or solo
    base = sorted(fora)[len(fora) // 2]
    limiar = (max(solo) + base) / 2
    ano_recuo = next((anos[j] for j in range(i_pico + 1, len(anos)) if solo[j] <= limiar), None)

    melhor = (float("-inf"), None)
    for t in range(1, len(anos)):
        antes = con[max(0, t - 3):t]
        depois = con[t:t + 3]
        if not antes or not depois:
            continue
        passo = sum(depois) / len(depois) - sum(antes) / len(antes)
        if passo > melhor[0]:
            melhor = (passo, anos[t])

    return {
        "ano_min": anos[0],
        "ano_max": anos[-1],
        "n_anos": len(anos),
        "pico_solo": ano_pico,
        "recuo_solo": ano_recuo,
        "passo_constr": melhor[1],
        "passo_constr_pp": round(melhor[0], 2),
        "amplitude_solo_pp": round(max(solo) - min(solo), 2),
        "amplitude_constr_pp": round(max(con) - min(con), 2),
        "constr_no_1o_ano_pct": round(con[0], 1),
    }


def main(raio_m: int = 500) -> None:
    df = pd.read_csv(RAIZ / "outputs" / f"nucleo_{raio_m}m_por_ano.csv")
    sites = json.loads((RAIZ / "config" / "sites.geojson").read_text(encoding="utf-8"))
    meta = {f["properties"]["site_id"]: f["properties"] for f in sites["features"]}

    linhas = []
    for nome in ("serie_mista", "serie_landsat", "serie_s2"):
        sub = _serie(df, nome)
        for site, g in sub.groupby("site_id"):
            d = detectar(g)
            verdade = meta[site].get("ano_inicio_operacao_estimado")
            obra = meta[site].get("ano_inicio_obra")
            # elegivel: verdade dentro da janela E com pelo menos 1 ano anterior na serie
            elegivel = verdade is not None and d["ano_min"] < verdade <= d["ano_max"]
            linhas.append(
                {
                    "serie": nome,
                    "site_id": site,
                    "ano_inicio_obra": obra,
                    "verdade_op": verdade,
                    "elegivel": elegivel,
                    "verdade_incoerente": bool(obra and verdade and verdade < obra),
                    **d,
                    "erro_recuo": (d["recuo_solo"] - verdade) if (elegivel and d["recuo_solo"]) else None,
                    "erro_passo": (d["passo_constr"] - verdade) if (elegivel and d["passo_constr"]) else None,
                }
            )

    out = pd.DataFrame(linhas)
    destino = RAIZ / "outputs" / "datacao_obra_comparacao.csv"
    out.to_csv(destino, index=False, encoding="utf-8")

    print(f"escrito: {destino}\n")
    for nome in ("serie_mista", "serie_landsat", "serie_s2"):
        s = out[(out.serie == nome) & out.elegivel]
        if s.empty:
            print(f"{nome:14s} sem sites elegiveis")
            continue
        for det in ("recuo", "passo"):
            e = s[f"erro_{det}"].dropna()
            if e.empty:
                continue
            print(
                f"{nome:14s} {det:6s} n={len(e):2d}  "
                f"EMA={e.abs().mean():.2f} anos  mediana={e.abs().median():.1f}  "
                f"vies={e.mean():+.2f}  acerto<=1ano={(e.abs() <= 1).mean():.0%}"
            )
        print()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500)
