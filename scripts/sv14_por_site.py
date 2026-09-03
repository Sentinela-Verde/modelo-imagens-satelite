"""Script ad-hoc (SV-14) — distribuição de classes por site (agregando todos os anos/sensores),
com foco em tier 2 (teste de generalização) e nos biomas fora de Mata Atlântica."""

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

    dist_por_site: dict[str, Counter] = defaultdict(Counter)
    for mp in manifests:
        m = json.loads(mp.read_text(encoding="utf-8"))
        site_id = m["site_id"]
        for slug, n in m["distribuicao_classes"].items():
            dist_por_site[site_id][slug] += n

    for site_id in sorted(dist_por_site, key=lambda s: (sites_meta.get(s, {}).get("tier", 9), s)):
        meta = sites_meta.get(site_id, {})
        c = dist_por_site[site_id]
        total = sum(c.values())
        partes = ", ".join(f"{slug}={100*n/total:.1f}%" for slug, n in sorted(c.items(), key=lambda kv: -kv[1]))
        print(f"tier={meta.get('tier')} bioma={meta.get('bioma'):20s} {site_id:28s} (n={total:>9,}) {partes}")


if __name__ == "__main__":
    main()
