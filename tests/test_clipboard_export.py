import json
import subprocess

import pytest

from pl_capital.models import Answer


def executed_answer():
    sql = "SELECT COUNT(*) FROM portfolios"
    return Answer(
        question="How many portfolios?",
        intent="sql_query",
        tool="sql_query",
        message="13 portfolios",
        sql=sql,
        executed_sql=sql,
        result={"columns": ["count"], "rows": [[13]], "row_count": 1},
        source_dates={"historical_prices": ["2023-09-25", "2023-10-09"]},
    )


def test_native_clipboard_copies_exact_executed_sql(monkeypatch):
    from pl_capital import clipboard

    calls = []
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard.shutil, "which", lambda _: "/usr/bin/pbcopy")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(clipboard.subprocess, "run", run)
    requested = []
    result = clipboard.ClipboardService().copy_sql(
        executed_answer(), terminal_copy=requested.append
    )
    assert result.confirmed and result.mechanism == "pbcopy"
    assert requested == [executed_answer().executed_sql]
    assert calls[0][1]["input"] == executed_answer().executed_sql
    assert not calls[0][1].get("shell", False)


def test_unavailable_clipboard_never_reports_confirmation(monkeypatch):
    from pl_capital import clipboard

    monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)
    outcome = clipboard.ClipboardService().copy_sql(executed_answer(), terminal_copy=lambda _: None)
    assert not outcome.confirmed
    assert "Save SQL" in outcome.message or "manual" in outcome.message.lower()


def test_copy_is_unavailable_for_unexecuted_or_failed_query():
    from pl_capital.clipboard import ClipboardService

    for answer in [
        Answer(sql="DELETE FROM portfolios", error="Rejected"),
        Answer(tool="exposure_calculator"),
    ]:
        outcome = ClipboardService().copy_sql(answer)
        assert not outcome.confirmed
        assert "executed SQL" in outcome.message


def test_exports_are_unique_safe_and_do_not_leak_key(settings):
    from pl_capital.exporting import ExportService

    answer = executed_answer()
    answer.question = "A question " + settings.api_key
    service = ExportService(settings)
    first, second = service.export_answer(answer), service.export_answer(answer)
    assert first != second and first.parent == settings.cache_dir / "exports"
    data = json.loads(first.read_text())
    assert data["sql"] == answer.executed_sql
    assert data["result"]["rows"] == [[13]]
    assert data["source_dates"]["historical_prices"][0] == "2023-09-25"
    assert settings.api_key not in first.read_text()
    assert service.save_sql(answer).read_text() == answer.executed_sql + "\n"


def test_save_sql_refuses_proposals_and_control_bytes(settings):
    from pl_capital.errors import CapitalError
    from pl_capital.exporting import ExportService

    with pytest.raises(CapitalError):
        ExportService(settings).save_sql(Answer(sql="SELECT 1"))
    with pytest.raises(CapitalError):
        ExportService(settings).save_sql(Answer(executed_sql="SELECT '\x1b[31m'"))


def test_export_collision_does_not_delete_existing_file(settings, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from pl_capital import exporting
    from pl_capital.errors import CapitalError

    class Clock:
        @staticmethod
        def now(_tz):
            return datetime(2026, 11, 8, tzinfo=UTC)

    monkeypatch.setattr(exporting, "datetime", Clock)
    monkeypatch.setattr(exporting, "uuid4", lambda: SimpleNamespace(hex="collision"))
    service = exporting.ExportService(settings)
    first = service.save_sql(executed_answer())
    before = first.read_bytes()
    with pytest.raises(CapitalError):
        service.save_sql(executed_answer())
    assert first.read_bytes() == before


def test_export_does_not_follow_symlink_outside_cache(settings, tmp_path):
    from pl_capital.errors import CapitalError
    from pl_capital.exporting import ExportService

    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (settings.cache_dir / "exports").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable on this platform")
    with pytest.raises(CapitalError):
        ExportService(settings).export_answer(executed_answer())
    assert list(outside.iterdir()) == []


def test_google_key_formats_are_redacted_from_diagnostics():
    from pl_capital.redaction import clean_text, redact

    for token in ("AQ." + "Z" * 44, "AIza" + "Z" * 35):
        assert token not in clean_text("Failure " + token)
        assert token not in str(
            redact({"gemini_api_key": token, "google_api_key": token, "detail": token})
        )
