from pathlib import Path

from sentinela.config import REPO_ROOT, Settings


def test_repo_root_is_correct():
    assert (REPO_ROOT / "CLAUDE.md").exists()
    assert (REPO_ROOT / "src" / "sentinela").exists()


def test_settings_resolves_data_paths(monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(REPO_ROOT / "data"))
    settings = Settings()
    assert settings.raw_dir == (REPO_ROOT / "data" / "raw").resolve()
    assert isinstance(settings.raw_dir, Path)


def test_settings_default_seed():
    settings = Settings()
    assert settings.seed == 42
