"""Clipboard outcomes distinguish an OS copy from an unconfirmed terminal request."""

import shutil
import subprocess
import sys
from dataclasses import dataclass

from pl_capital.models import Answer
from pl_capital.redaction import clean_text


@dataclass(frozen=True)
class ClipboardOutcome:
    confirmed: bool
    mechanism: str
    message: str


def eligible_sql(answer: Answer, secret: str = "") -> str | None:
    sql = answer.executed_sql
    if answer.error or not sql or clean_text(sql, secret) != sql:
        return None
    return sql


class ClipboardService:
    def __init__(self, settings=None):
        self._secret = getattr(settings, "api_key", "")

    def copy_sql(self, answer: Answer, *, terminal_copy=None) -> ClipboardOutcome:
        sql = eligible_sql(answer, self._secret)
        if sql is None:
            return ClipboardOutcome(
                False, "none", "No safe executed SQL is available for this answer."
            )
        requested = False
        if terminal_copy is not None:
            try:
                terminal_copy(sql)
                requested = True
            except Exception:
                # Terminal transport errors must not prevent a supported native copy.
                requested = False
        candidates = []
        if sys.platform == "darwin":
            if executable := shutil.which("pbcopy"):
                candidates.append(("pbcopy", [executable]))
        elif sys.platform == "win32":
            executable = shutil.which("pwsh") or shutil.which("powershell")
            if executable:
                command = "[Console]::InputEncoding=[System.Text.UTF8Encoding]::new(); $s=[Console]::In.ReadToEnd(); Set-Clipboard -Value $s"
                candidates.append(
                    (
                        "Windows clipboard",
                        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
                    )
                )
        else:
            import os

            if os.getenv("WAYLAND_DISPLAY") and (executable := shutil.which("wl-copy")):
                candidates.append(("wl-copy", [executable, "--type", "text/plain"]))
            if os.getenv("DISPLAY") and (executable := shutil.which("xclip")):
                candidates.append(("xclip", [executable, "-selection", "clipboard"]))
        for name, args in candidates:
            try:
                outcome = subprocess.run(  # noqa: S603 -- fixed backend argv; SQL is stdin data
                    args,
                    input=sql,
                    text=True,
                    encoding="utf-8",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False,
                )
                if outcome.returncode == 0:
                    return ClipboardOutcome(True, name, f"SQL copied using {name}.")
            except (OSError, subprocess.TimeoutExpired):
                continue
        message = "Clipboard request sent but OS confirmation is unavailable. Use Show SQL for manual copying or Save SQL."
        if not requested:
            message = "Clipboard is unavailable. Use Show SQL for manual copying or Save SQL."
        return ClipboardOutcome(False, "terminal-request" if requested else "unavailable", message)
