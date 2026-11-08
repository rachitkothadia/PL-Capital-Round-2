"""Private, generated export names; no user/model path or shell command is accepted."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pl_capital.clipboard import eligible_sql
from pl_capital.errors import CapitalError
from pl_capital.models import Answer
from pl_capital.presentation import build_answer_view
from pl_capital.redaction import redact


class ExportService:
    def __init__(self, settings):
        self.settings = settings

    def _write(self, suffix: str, content: str) -> Path:
        target = None
        created = False
        try:
            cache = Path(self.settings.cache_dir).resolve()
            directory = cache / "exports"
            if directory.is_symlink():
                raise CapitalError("Export directory must not be a symbolic link.")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if directory.resolve().parent != cache:
                raise CapitalError("Export path escaped the configured cache directory.")
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            target = directory / f"answer-{stamp}-{uuid4().hex}.{suffix}"
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            return target
        except OSError as exc:
            if target is not None and created:
                target.unlink(missing_ok=True)
            raise CapitalError(
                "Export could not be saved; check the configured cache directory permissions."
            ) from exc

    def save_sql(self, answer: Answer) -> Path:
        sql = eligible_sql(answer, getattr(self.settings, "api_key", ""))
        if sql is None:
            raise CapitalError("No safe executed SQL is available to save.")
        return self._write("sql", sql + "\n")

    def export_answer(self, answer: Answer) -> Path:
        view = build_answer_view(answer)
        payload = {
            "exported_at_utc": datetime.now(UTC).isoformat(),
            "question": answer.question,
            "answer": view.headline,
            "intent": answer.intent,
            "status": answer.status,
            "next_step": answer.next_step,
            "tool": answer.tool,
            "result": answer.result,
            "sql": answer.executed_sql,
            "parameters": answer.executed_parameters
            or (answer.parameters if answer.executed_sql else {}),
            "assumptions": answer.assumptions,
            "source_dates": answer.source_dates,
            "how_calculated": view.steps,
            "provenance": view.provenance,
            "warnings": answer.warnings,
            "error": answer.error,
        }
        safe = redact(payload, getattr(self.settings, "api_key", ""))
        try:
            serialized = json.dumps(safe, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        except (ValueError, TypeError) as exc:
            raise CapitalError(
                "Answer contains values that cannot be safely exported as JSON."
            ) from exc
        if len(serialized.encode("utf-8")) > 1_000_000:
            raise CapitalError("Answer export exceeds the size budget.")
        return self._write("json", serialized)
