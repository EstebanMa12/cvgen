import fcntl
import os
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

from cvgen.cli import main
from cvgen.config import load_config
from cvgen.tui import (
    BROWSE_KEYS,
    bar,
    collect_rows,
    format_pages,
    header_labels,
    perform_build,
    perform_init,
    perform_verify,
    table_line,
)

ROOT = Path(__file__).resolve().parents[1]


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
    labels = {label for _key, label in BROWSE_KEYS}
    assert {"Help", "Init", "Build", "Verify", "Tailor", "Quit"} <= labels


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


def test_interactive_screen_shows_keys_and_quits(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    code, screen = _drive(tmp_path, b"q")
    assert code == 0
    assert "F1" in screen
    assert "Help" in screen
    assert "F5" in screen
    assert "Build" in screen
    assert "F10" in screen
    assert "Quit" in screen
    assert "short-en" in screen
    assert "Avery Quinn" in screen


def test_new_directory_offers_to_create_folders(tmp_path: Path):
    code, screen = _drive(tmp_path, b"q")
    assert code == 0
    assert "source/" in screen
    assert "cv/" in screen
    assert "jobs/" in screen
    assert "out/" in screen
    assert "F10" in screen


def test_help_overlay_lists_shell_commands(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    code, screen = _drive(tmp_path, b"?q")
    assert code == 0
    assert "cvgen build" in screen
    assert "cvgen verify" in screen
    assert "cvgen tailor" in screen


def _capture(action):
    import io
    from contextlib import redirect_stderr, redirect_stdout

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = action()
    return code, stdout.getvalue() + stderr.getvalue()


def _drive(cwd: Path, keys: bytes) -> tuple[int, str]:
    import pty
    import select

    master, slave = pty.openpty()
    winsize = struct.pack("HHHH", 32, 110, 0, 0)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["LINES"] = "32"
    env["COLUMNS"] = "110"
    process = subprocess.Popen(
        [sys.executable, "-m", "cvgen"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=cwd,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    chunks = b""
    deadline = time.time() + 8
    sent = False
    while time.time() < deadline and process.poll() is None:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                chunks += os.read(master, 8192)
            except OSError:
                break
        if not sent and b"F10" in chunks:
            os.write(master, keys)
            sent = True
            deadline = time.time() + 3
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=2)
    os.close(master)
    text = chunks.decode("utf-8", errors="replace")
    return process.returncode if process.returncode is not None else 1, text
