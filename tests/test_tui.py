import sys
from pathlib import Path

import pytest

from cvgen.cli import main
from cvgen.config import load_config
from cvgen.tui import (
    bar,
    collect_rows,
    format_pages,
    header_labels,
    perform_build,
    perform_init,
    perform_verify,
    table_line,
)
from cvgen.ui.commands import MENU

def test_meter_and_page_labels():
    assert bar(0, 4) == "░░░░"
    assert bar(1, 4) == "████"
    assert bar(0.5, 4) == "██░░"
    assert format_pages(None, 1) == "—"
    assert format_pages(1, 2) == "1/2"


def _workspace(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    return load_config(tmp_path / "cvgen.toml")


def test_rows_follow_the_example_variants(tmp_path: Path):
    config = _workspace(tmp_path)
    rows = collect_rows(config)
    assert [row.id for row in rows] == ["short-en", "short-es", "extended-en", "extended-es"]
    assert all(row.markdown_ok for row in rows)
    assert all(not row.docx_ok for row in rows)
    assert len(header_labels()) == len(table_line(rows[0], True))
    assert "short-en" in table_line(rows[0], True)
    assert table_line(rows[0], True).startswith(" > ")


def test_build_and_verify_from_the_screen_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    rows = collect_rows(config)
    code, build_log = _capture(lambda: perform_build(config, rows, [0], make_pdf=False))
    assert code == 0
    assert "Generated" in build_log
    assert (tmp_path / "out" / "avery-quinn-short-en.docx").is_file()
    code, text = _capture(lambda: perform_verify(config, rows, [0]))
    assert code == 0
    assert "All checks passed." in text


def test_init_from_the_screen_action(tmp_path: Path):
    code, text = _capture(lambda: perform_init(tmp_path))
    assert code == 0
    assert "Initialized" in text
    assert (tmp_path / "cvgen.toml").is_file()


def test_command_bar_lists_the_actions():
    titles = {item.title for item in MENU}
    assert {"Build all", "Verify all", "Tailor to a job", "Dashboard", "New workspace", "Quit"} <= titles


def test_plain_cvgen_without_a_terminal_prints_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert main([]) == 2
    assert "usage: cvgen" in capsys.readouterr().out


def test_ui_without_a_terminal_explains_why(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert main(["ui"]) == 2
    assert "terminal" in capsys.readouterr().err


def _capture(action):
    import io
    from contextlib import redirect_stderr, redirect_stdout

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = action()
    return code, stdout.getvalue() + stderr.getvalue()
