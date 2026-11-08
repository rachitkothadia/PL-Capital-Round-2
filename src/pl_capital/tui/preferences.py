"""Small user preferences; no source, environment or credentials are written."""

import json
import os
import tempfile
from pathlib import Path

THEMES = {"dark": "capital-dark", "light": "capital-light"}


def load_theme(directory: Path) -> str:
    try:
        path = Path(directory) / "preferences.json"
        if path.stat().st_size > 1024:
            return THEMES["dark"]
        data = json.loads(path.read_text(encoding="utf-8"))
        choice = data.get("theme") if isinstance(data, dict) else None
        return choice if choice in THEMES.values() else THEMES["dark"]
    except (OSError, ValueError, TypeError):
        return THEMES["dark"]


def save_theme(directory: Path, theme: str) -> None:
    if theme not in THEMES.values():
        raise ValueError("Unknown portfolio theme.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="theme-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"theme": theme, "version": 1}, stream)
            stream.write("\n")
        os.replace(name, directory / "preferences.json")
    finally:
        Path(name).unlink(missing_ok=True)
