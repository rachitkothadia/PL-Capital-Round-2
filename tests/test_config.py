from pathlib import Path

import pytest

from pl_capital.config import Settings
from pl_capital.errors import ConfigurationError


@pytest.mark.parametrize(
    "folder", ["Windows User/Local Cache", "Linux cache", "Mac Application Support"]
)
def test_platform_cache_override_and_secret_repr(tmp_path, monkeypatch, folder):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "sensitive-test-value")
    monkeypatch.setenv("PL_CAPITAL_CACHE_DIR", str(tmp_path / folder))
    monkeypatch.setenv("GRAPH_BACKEND", "off")
    value = Settings.from_env()
    assert value.db_path == tmp_path / folder / "portfolio.db"
    assert "sensitive-test-value" not in repr(value)
    assert isinstance(value.data_root, Path)


@pytest.mark.parametrize(
    "key,value", [("GROQ_MODEL", "invented-model"), ("GRAPH_BACKEND", "cloud")]
)
def test_invalid_config(tmp_path, monkeypatch, key, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigurationError):
        Settings.from_env()
