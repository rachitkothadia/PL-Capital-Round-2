"""Shared presentation/export redaction; never serialize SDK request objects."""

import re
from typing import Any

TOKEN = re.compile(r"(?:gsk_|gh[pousr]_|sk-proj-|AIza|AQ\.)[A-Za-z0-9_-]{12,}")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
PRIVATE_FIELDS = frozenset(
    {
        "api_key",
        "gemini_api_key",
        "google_api_key",
        "authorization",
        "password",
        "access_token",
        "refresh_token",
        "system_prompt",
        "hidden_prompt",
        "reasoning",
        "chain_of_thought",
    }
)


def clean_text(value: Any, secret: str = "") -> str:
    text = str(value)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return CONTROL.sub("", TOKEN.sub("[REDACTED]", text))


def redact(value: Any, secret: str = "") -> Any:
    if isinstance(value, dict):
        return {
            clean_text(k, secret): "[REDACTED]"
            if str(k).casefold() in PRIVATE_FIELDS
            else redact(v, secret)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, secret) for v in value]
    if isinstance(value, str):
        return clean_text(value, secret)
    return value
