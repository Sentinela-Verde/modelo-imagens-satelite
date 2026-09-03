"""Script ad-hoc (SV-14) — agrega todos os manifests `classificado_{sensor}_{site}_{ano}.json`
em estatísticas para o relatório final: distribuição de classes agregada (geral, por tier, por
sensor/era), contagem de site/ano/sensor processados por tier, e uma checagem cruzada de que
todo raster de features ativo tem um classificado correspondente."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sentinela.config import REPO_ROOT, SETTINGS


def _sites_meta() -> dict[str, dict]:
    data = json.loads((REPO_ROOT / "config" / "sites.geojson").read_text(encoding="utf-8"))
    return {
        f["properties"]["site_id"]: {"tier": f["properties"]["tier"], "bioma": f["properties"]["bioma"]}
        for f in data["features"]
        if f["properties"]["ativo"]
    }


def main() -> None:
    sites_meta = _sites_meta()
    manifests = sorted(SETTINGS.manifests_dir.glob("classificado_*.json"))
    print(f"{len(manifests)} manifests de classificado_*.json encontrados.\n")

    dist_geral: Counter = Counter()
    dist_por_tier: dict[int, Counter] = defaultdict(Counter)
    dist_por_sensor: dict[str, Counter] = defaultdict(Counter)
    n_por_tier_sensor: Counter = Counter()
    confiancas_media = []
    itens = []

    for mp in manifests:
        m = json.loads(mp.read_text(encoding="utf-8"))
        site_id = m["site_id"]
        sensor = m["sensor"]
        ano = m["ano"]
        tier = sites_meta.get(site_id, {}).get("tier", "?")
        itens.append((tier, site_id, sensor, ano))
        for slug, n in m["distribuicao_classes"].items():
            dist_geral[slug] += n
            dist_por_tier[tier][slug] += n
            dist_por_sensor[sensor][slug] += n
        n_por_tier_sensor[(tier, sensor)] += 1
        if m.get("confianca"):
            confiancas_media.append(m["confianca"]["media"])

    print("=== Distribuição de classes agregada (todos os pixels válidos, todos os site/ano/sensor) ===")
    total = sum(dist_geral.values())
    for slug, n in sorted(dist_geral.items(), key=lambda kv: -kv[1]):
        print(f"  {slug}: {n:>12,} ({100*n/total:.2f}%)")
    print(f"  TOTAL válidos: {total:,}")

    print("\n=== Por tier ===")
    for tier in sorted(dist_por_tier, key=str):
        sub_total = sum(dist_por_tier[tier].values())
        print(f" tier {tier} (total {sub_total:,} px):")
        for slug, n in sorted(dist_por_tier[tier].items(), key=lambda kv: -kv[1]):
            print(f"    {slug}: {n:>12,} ({100*n/sub_total:.2f}%)")

    print("\n=== Por sensor/era ===")
    for sensor in sorted(dist_por_sensor):
        sub_total = sum(dist_por_sensor[sensor].values())
        print(f" {sensor} (total {sub_total:,} px):")
        for slug, n in sorted(dist_por_sensor[sensor].items(), key=lambda kv: -kv[1]):
            print(f"    {slug}: {n:>12,} ({100*n/sub_total:.2f}%)")

    print("\n=== Contagem de itens processados por tier x sensor ===")
    for (tier, sensor), n in sorted(n_por_tier_sensor.items(), key=lambda kv: str(kv[0])):
        print(f"  tier={tier} sensor={sensor}: {n} itens")

    if confiancas_media:
        print(f"\nConfiança média (predict_proba.max) — média dos manifests: {sum(confiancas_media)/len(confiancas_media):.2f}%")
        print(f"Confiança média — min/max entre manifests: {min(confiancas_media):.2f}% / {max(confiancas_media):.2f}%")

    # checagem cruzada: todo (sensor, site, ano) com features deveria ter um classificado
    esperados = set()
    for sensor_token in ("s2", "landsat"):
        base = SETTINGS.interim_dir / "features" / sensor_token
        if not base.exists():
            continue
        for site_dir in base.iterdir():
            if not site_dir.is_dir() or site_dir.name not in sites_meta:
                continue
            for tif in site_dir.glob("*.tif"):
                esperados.add((sensor_token, site_dir.name, int(tif.stem)))

    obtidos = {(sensor, site_id, ano) for (_, site_id, sensor, ano) in itens}
    faltando = sorted(esperados - obtidos)
    print(f"\n=== Cobertura: {len(obtidos)}/{len(esperados)} combos (sensor,site,ano) com classificado pronto ===")
    if faltando:
        print(f"FALTANDO ({len(faltando)}): {faltando}")
    else:
        print("Nenhum combo faltando — cobertura completa.")


if __name__ == "__main__":
    main()
