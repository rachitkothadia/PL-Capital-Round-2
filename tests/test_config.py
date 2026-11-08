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


def test_gemini_selection_uses_its_own_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-value")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-value")
    value = Settings.from_env()
    assert value.provider == "gemini"
    assert value.api_key == "gemini-test-value"
    alternate = Settings.from_env(model="openai/gpt-oss-120b")
    assert alternate.provider == "groq"
    assert alternate.api_key == "groq-test-value"


def test_provider_default_cannot_silently_select_another_provider(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "openai/gpt-oss-120b")
    with pytest.raises(ConfigurationError):
        Settings.from_env()
