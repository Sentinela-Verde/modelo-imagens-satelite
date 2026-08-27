"""Configuração central do projeto: variáveis de ambiente + YAML de config/."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

load_dotenv(REPO_ROOT / ".env")


class ConfigError(RuntimeError):
    """Erro de configuração com mensagem acionável (não é pra virar traceback cru)."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"Variável de ambiente '{name}' não definida. Copie .env.example para .env "
            f"e preencha '{name}'."
        )
    return value


def _load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise ConfigError(
            f"Arquivo de config '{path}' não existe. Ele é criado por uma tarefa específica "
            f"(veja docs/plano-execucao.md) — este bootstrap só cria o esqueleto."
        )
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Settings:
    """Acesso preguiçoso e com mensagem clara às configurações do projeto."""

    def __init__(self) -> None:
        self.data_root = Path(os.environ.get("DATA_ROOT", "./data")).resolve()
        self.seed = int(os.environ.get("RANDOM_SEED", "42"))

    @property
    def ee_project(self) -> str:
        return _require_env("EE_PROJECT")

    @property
    def ee_service_account_key(self) -> Path:
        return Path(_require_env("EE_SERVICE_ACCOUNT_KEY")).expanduser().resolve()

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_root / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.data_root / "processed"

    @property
    def labels_manual_dir(self) -> Path:
        return self.data_root / "labels_manual"

    @property
    def manifests_dir(self) -> Path:
        return self.data_root / "manifests"

    def params(self) -> dict:
        return _load_yaml("params.yml")

    def classes(self) -> dict:
        return _load_yaml("classes.yml")


SETTINGS = Settings()
