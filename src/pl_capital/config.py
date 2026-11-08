import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_cache_path, user_config_path

from pl_capital.errors import ConfigurationError

GROQ_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")
GEMINI_MODELS = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite")
MODELS = GROQ_MODELS + GEMINI_MODELS


@dataclass(frozen=True)
class Settings:
    data_root: Path
    cache_dir: Path
    api_key: str = field(default="", repr=False)
    model: str = MODELS[0]
    graph_backend: str = "auto"
    config_dir: Path | None = None

    @property
    def provider(self) -> str:
        return "gemini" if self.model in GEMINI_MODELS else "groq"

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
        provider = os.getenv("LLM_PROVIDER", "groq").lower()
        if provider not in {"groq", "gemini"}:
            raise ConfigurationError("LLM_PROVIDER must be groq or gemini.")
        chosen = model or (os.getenv("GEMINI_MODEL", GEMINI_MODELS[0]) if provider == "gemini" else os.getenv("GROQ_MODEL", GROQ_MODELS[0]))
        backend = os.getenv("GRAPH_BACKEND", "auto").lower()
        allowed = MODELS if model is not None else (GEMINI_MODELS if provider == "gemini" else GROQ_MODELS)
        if chosen not in allowed:
            raise ConfigurationError("Choose a documented Groq or Gemini model.")
        if backend not in {"auto", "lite", "off"}:
            raise ConfigurationError("GRAPH_BACKEND must be auto, lite, or off.")
        config_dir = Path(
            os.getenv("PL_CAPITAL_CONFIG_DIR", user_config_path("pl-capital"))
        ).expanduser()
        key_name = "GEMINI_API_KEY" if chosen in GEMINI_MODELS else "GROQ_API_KEY"
        return cls(root, cache_dir, os.getenv(key_name, ""), chosen, backend, config_dir)
