import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_cache_path, user_config_path

from pl_capital.errors import ConfigurationError

GEMINI_MODELS = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview")
MODELS = GEMINI_MODELS
DEFAULT_MODEL = "gemini-3.1-flash-lite"


@dataclass(frozen=True)
class Settings:
    data_root: Path
    cache_dir: Path
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    graph_backend: str = "auto"
    config_dir: Path | None = None

    @property
    def provider(self) -> str:
        return "gemini"

    @property
    def db_path(self) -> Path:
        return self.cache_dir / "portfolio.db"

    @classmethod
    def from_env(cls, model: str | None = None) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False)
        root = Path(os.getenv("PL_CAPITAL_DATA_DIR", Path.cwd())).expanduser().resolve()
        if not (root / "database_schema.sql").exists() and not os.getenv("PL_CAPITAL_DATA_DIR"):
            root = Path(__file__).parent / "resources"
        cache = os.getenv("PL_CAPITAL_CACHE_DIR")
        tag = hashlib.sha256(str(root).encode()).hexdigest()[:12]
        cache_dir = Path(cache).expanduser() if cache else user_cache_path("pl-capital") / tag
        provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        if provider != "gemini":
            raise ConfigurationError("LLM_PROVIDER must be gemini.")
        chosen = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        backend = os.getenv("GRAPH_BACKEND", "auto").lower()
        allowed = MODELS
        if chosen not in allowed:
            raise ConfigurationError("Choose a documented Gemini model.")
        if backend not in {"auto", "lite", "off"}:
            raise ConfigurationError("GRAPH_BACKEND must be auto, lite, or off.")
        config_dir = Path(
            os.getenv("PL_CAPITAL_CONFIG_DIR", user_config_path("pl-capital"))
        ).expanduser()
        key_name = "GEMINI_API_KEY"
        return cls(root, cache_dir, os.getenv(key_name, ""), chosen, backend, config_dir)
