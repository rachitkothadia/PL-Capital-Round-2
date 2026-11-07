import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_cache_path

from pl_capital.errors import ConfigurationError

MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")


@dataclass(frozen=True)
class Settings:
    data_root: Path
    cache_dir: Path
    api_key: str = field(default="", repr=False)
    model: str = MODELS[0]
    graph_backend: str = "auto"

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
        chosen = model or os.getenv("GROQ_MODEL", MODELS[0])
        backend = os.getenv("GRAPH_BACKEND", "auto").lower()
        if chosen not in MODELS:
            raise ConfigurationError("Choose openai/gpt-oss-120b or openai/gpt-oss-20b.")
        if backend not in {"auto", "lite", "off"}:
            raise ConfigurationError("GRAPH_BACKEND must be auto, lite, or off.")
        return cls(root, cache_dir, os.getenv("GROQ_API_KEY", ""), chosen, backend)
