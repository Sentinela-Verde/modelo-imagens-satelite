"""Diagnóstico de ambiente. Rode com: python -m sentinela.check

NÃO autentica no Earth Engine (isso é responsabilidade de outra tarefa) — só verifica se o
ambiente local está pronto: versões de libs críticas, .env encontrado, pastas de data/ existem.
"""

from __future__ import annotations

import sys
from importlib import metadata

from .config import REPO_ROOT, SETTINGS

CRITICAL_LIBS = [
    "earthengine-api",
    "rasterio",
    "geopandas",
    "shapely",
    "pyproj",
    "numpy",
    "pandas",
    "pyarrow",
    "scikit-learn",
    "joblib",
    "pyyaml",
    "python-dotenv",
]


def _lib_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "AUSENTE"


def main() -> int:
    problems: list[str] = []

    print(f"Python: {sys.version.split()[0]}")
    print(f"Repo root: {REPO_ROOT}")
    print()

    print("Bibliotecas críticas:")
    for lib in CRITICAL_LIBS:
        version = _lib_version(lib)
        print(f"  {lib:<20} {version}")
        if version == "AUSENTE":
            problems.append(f"biblioteca '{lib}' não instalada (rode: pip install -r requirements.txt)")
    print()

    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        print(f".env encontrado em {env_path}")
    else:
        problems.append(
            f".env não encontrado em {env_path} — copie .env.example para .env e preencha"
        )

    for name, path in [
        ("data/raw", SETTINGS.raw_dir),
        ("data/interim", SETTINGS.interim_dir),
        ("data/processed", SETTINGS.processed_dir),
        ("data/labels_manual", SETTINGS.labels_manual_dir),
        ("data/manifests", SETTINGS.manifests_dir),
    ]:
        if path.exists():
            print(f"{name}: OK ({path})")
        else:
            problems.append(f"pasta '{name}' não existe em {path}")

    print()
    if problems:
        print("PENDÊNCIAS:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
