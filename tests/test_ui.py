"""Pilot tests for the Textual screen. Skipped when the ui extra is absent."""

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from cvgen.cli import main
from cvgen.config import load_config
from cvgen.ui.app import CvgenApp, progress_text
from cvgen.ui.commands import matching_commands, parse_prompt, parse_report, shortcut_for, ui_key_overrides
from textual.widgets import Button, Label, RichLog, Static, Switch


async def _skip_intro(pilot) -> None:
    await pilot.pause()
    if pilot.app.screen.__class__.__name__ == "WelcomeModal":
        await pilot.press("escape")
        await pilot.pause()


def _run(coro):
    return asyncio.run(coro)


def test_parse_prompt_and_report():
    assert parse_prompt("").kind == "hint"
    action = parse_prompt("/tailor jobs/role.txt")
    assert action.kind == "tailor"
    assert action.arg == "jobs/role.txt"
    assert parse_prompt("jobs/role.txt").kind == "tailor"
    assert parse_prompt("https://jobs.example.com/harbor").kind == "tailor"
    assert parse_prompt("/").kind == "palette"
    assert parse_prompt("/nope").kind == "unknown"
    hits = matching_commands("/ta")
    assert any(item.action == "tailor" for item in hits)
    report = """
## Requirements met
- Python
- FastAPI
## Partially met
- Docker
## Missing
- Kubernetes
- Oracle
"""
    assert parse_report(report) == (2, 1, 2)


def test_key_override_is_read_from_config(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    path = tmp_path / "cvgen.toml"
    path.write_text(path.read_text(encoding="utf-8") + '\n[ui.keys]\nbuild_all = "f2"\n', encoding="utf-8")
    config = load_config(path)
    assert ui_key_overrides(config)["build_all"] == "f2"
    assert shortcut_for("build_all", config) == "f2"
    assert shortcut_for("quit", config) == "ctrl+q"


def test_progress_labels_name_each_step():
    reading = progress_text("Reading the job", preview=False)
    assert reading.startswith("> Reading job")
    assert "Asking AI" in reading
    assert "Verifying facts" in reading
    assert "Building PDF" in reading
    asking = progress_text("Asking the model", preview=False)
    assert "Reading job  done" in asking
    assert "> Asking AI" in asking
    preview = progress_text("Writing the prompt", preview=True)
    assert "> Writing the prompt" in preview
    assert "Asking AI" not in preview


def test_start_screen_shows_menu_logo_and_version(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    app = CvgenApp(cwd=tmp_path, make_pdf=False)

    async def body():
        async with app.run_test(size=(100, 34)) as pilot:
            await _skip_intro(pilot)
            menu = str(pilot.app.query_one("#menu", Static).render())
            logo = str(pilot.app.query_one("#logo", Static).render())
            version = str(pilot.app.query_one("#version", Label).render())
            assert "Build all" in menu
            assert "ctrl+b" in menu
            assert "Quit" in menu
            assert "ctrl+q" in menu
            assert "⣿" in logo or "⢀" in logo
            assert "Avery Quinn" in str(pilot.app.query_one("#who", Static).render())
            assert version.strip()
            await pilot.press("ctrl+q")

    _run(body())


def test_first_run_opens_the_folder_modal(tmp_path: Path):
    app = CvgenApp(cwd=tmp_path, make_pdf=False)

    async def body():
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            text = str(pilot.app.screen.query_one("#body", Static).render())
            assert "source/" in text
            assert "cv/" in text
            assert "jobs/" in text
            assert "out/" in text
            for _ in range(6):
                screen = pilot.app.screen
                if not hasattr(screen, "action_next"):
                    break
                screen.action_next()
                await pilot.pause()
            assert (tmp_path / "cvgen.toml").is_file()
            assert (tmp_path / "source").is_dir()
            assert (tmp_path / "out").is_dir()

    _run(body())


def test_dashboard_and_verify_popup(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    app = CvgenApp(cwd=tmp_path, make_pdf=False)

    async def body():
        async with app.run_test(size=(110, 36), notifications=True) as pilot:
            await _skip_intro(pilot)
            await pilot.press("ctrl+d")
            await pilot.pause()
            table = str(pilot.app.screen.query_one("#variants-body", Static).render())
            assert "Short" in table
            assert "English" in table
            assert "Pages" in table
            assert "not built" in table
            assert "░" not in table
            details = str(pilot.app.screen.query_one("#verify-body", Static).render())
            assert "Markdown" in details
            assert "avery-quinn-short-en.md" in details
            assert "Base CVs" in str(pilot.app.screen.query_one("#dash-help", Static).render())
            empty = str(pilot.app.screen.query_one("#matches-body", Static).render())
            assert "Paste a job link" in empty
            await pilot.press("v")
            for _ in range(40):
                await pilot.pause(0.1)
                if app.last_verify:
                    break
            assert "passed" in app.last_verify
            check = str(pilot.app.screen.query_one("#verify-body", Static).render())
            assert "passed" in check

    _run(body())


def test_slash_tailor_opens_the_modal(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    app = CvgenApp(cwd=tmp_path, make_pdf=False)

    async def body():
        async with app.run_test(size=(100, 36)) as pilot:
            await _skip_intro(pilot)
            for key in ("/", "t", "a", "i", "l", "o", "r", " ", "j", "o", "b", "s", "/", "x", ".", "t", "x", "t"):
                await pilot.press(key)
            await pilot.press("enter")
            await pilot.pause()
            assert pilot.app.screen.query_one("#job-path").value.endswith("jobs/x.txt")
            assert pilot.app.screen.query_one("#dialog-title", Label).render() is not None
            assert pilot.app.screen.query_one("#preview", Switch).value is False
            assert "Generate CV" in str(pilot.app.screen.query_one("#generate", Button).label)
            assert pilot.app.screen.query_one("#log", RichLog).wrap is True

    _run(body())


def test_job_list_passes_the_jobs_directory_path(tmp_path: Path):
    """Selecting a saved posting must not hand the bare filename to the loader."""
    assert main(["init", "--dir", str(tmp_path)]) == 0
    target = tmp_path / "jobs" / "harbor-role.txt"
    target.write_text("Harbor & Co. is hiring a Python engineer for the lantern service.\n")
    app = CvgenApp(cwd=tmp_path, make_pdf=False)

    async def body():
        async with app.run_test(size=(100, 40)) as pilot:
            await _skip_intro(pilot)
            await pilot.press("ctrl+t")
            await pilot.pause()
            screen = pilot.app.screen
            listing = screen.query_one("#jobs")
            index = next(i for i, path in enumerate(screen._jobs) if path.name == "harbor-role.txt")
            listing.highlighted = index
            screen.query_one("#job-path").value = ""
            chosen = screen._job_text()
            assert chosen.endswith("jobs/harbor-role.txt")
            assert Path(chosen).is_file()
            assert Path(chosen).parent.name == "jobs"
            option_id = str(listing.get_option_at_index(index).id)
            assert option_id.endswith("jobs/harbor-role.txt")
            screen.query_one("#preview", Switch).value = True
            screen._start()
            for _ in range(40):
                await pilot.pause(0.1)
                if screen.query_one("#result").has_class("hidden") is False:
                    break
            summary = str(screen.query_one("#summary", Static).render())
            assert "Preview only" in summary
            assert screen.query_one("#error-box").has_class("hidden")
            assert "Job file not found" not in summary

    _run(body())
