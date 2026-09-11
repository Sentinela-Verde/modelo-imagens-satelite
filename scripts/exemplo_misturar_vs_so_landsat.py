"""Exemplo didatico: comparar a serie 'misturando satelites' (o que dataset ingenuo faria) contra
'so Landsat' (o jeito seguro), pra classe critica (solo_exposto_obras) em ascenty-vinhedo -- obra
comecou em 2019, exatamente na troca de sensor, o pior caso possivel.

Rode com: python scripts/exemplo_misturar_vs_so_landsat.py
Gera: reports/figures/exemplo_misturar_vs_so_landsat_ascenty-vinhedo.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

df = pd.read_csv(REPO_ROOT / "outputs" / "indicadores" / "area_por_classe.csv")
site = "ascenty-vinhedo"
d = df[(df.site_id == site) & (df.classe_nome == "solo_exposto_obras")].copy()

# Serie "misturando" -- o que a serie oficial recomendada (schema-indicadores.md) usa:
# Landsat pre-2019, Sentinel-2 2019 em diante.
misturada = pd.concat([
    d[(d.sensor == "landsat") & (d.ano < 2019)],
    d[(d.sensor == "sentinel2")],
]).sort_values("ano")

# Serie "so Landsat" -- mesmo sensor do inicio ao fim (Landsat foi ingerido ate 2021 pra este
# site, na janela de sobreposicao pensada exatamente pra este tipo de checagem).
so_landsat = d[d.sensor == "landsat"].sort_values("ano")

fig, ax = plt.subplots(figsize=(9, 5.5))

ax.plot(misturada["ano"], misturada["area_ha"], "o-", color="#C0392B", linewidth=2.5,
        markersize=7, label="Misturando satélites (Landsat até 2018, Sentinel-2 de 2019+)")
ax.plot(so_landsat["ano"], so_landsat["area_ha"], "o-", color="#1B5E20", linewidth=2.5,
        markersize=7, label="Só Landsat (mesmo sensor do início ao fim)")

ax.axvline(2019, color="gray", linestyle="--", linewidth=1.2, alpha=0.7)
ax.text(2019.15, 550, "obra começou\n(2019) = troca\nde satélite",
        fontsize=9, color="dimgray", va="center",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="lightgray", alpha=0.9))

ax.set_xlabel("Ano")
ax.set_ylabel("Área de solo exposto/obras (ha)")
ax.set_title(f"{site} — mesma obra, duas leituras muito diferentes")
ax.legend(loc="upper left", fontsize=9, bbox_to_anchor=(0.0, 0.88))
ax.grid(alpha=0.25)
fig.tight_layout()

out = REPO_ROOT / "reports" / "figures" / "exemplo_misturar_vs_so_landsat_ascenty-vinhedo.png"
fig.savefig(out, dpi=150)
print(f"Salvo: {out}")

print()
print("Misturando satelites:")
print(misturada[["ano", "sensor", "area_ha"]].to_string(index=False))
print()
print("So Landsat:")
print(so_landsat[["ano", "sensor", "area_ha"]].to_string(index=False))
