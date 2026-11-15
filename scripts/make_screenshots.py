#!/usr/bin/env python3
"""Save headless screenshots of the cvgen screen.

Uses only the fictional example from ``cvgen init`` (Avery Quinn, Northwind
Labs, Harbor & Co., Lumenfield, and the other example names). No provider
key is required: the tailor result is a prerecorded match report.

    pip install '.[ui]' cairosvg
    python scripts/make_screenshots.py

SVG files come from ``App.save_screenshot``. PNG copies are written beside
them for the README.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import cairosvg
from textual.css.query import NoMatches

import cvgen.ui.app as app_module
from cvgen.cli import main
from cvgen.scaffold import init_workspace
from cvgen.ui.app import CvgenApp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
DEMO = Path("/tmp/cv")
EMPTY = Path("/tmp/cv-onboard")
# Tall enough that the tailor form shows both length choices, and wide enough
# that absolute paths fit on one line in the dashboard and the result popup.
SIZE = (148, 46)

REPORT = """\
# Match report — Lumenfield backend

## Requirements met
- Python
- FastAPI
- PostgreSQL

## Partially met
- Docker

## Missing
- Kubernetes
- Oracle PL/SQL
"""


def prepare_demo(root: Path) -> None:
    """Build the example workspace and drop in one prerecorded match report."""
    if root.exists():
        shutil.rmtree(root)
    init_workspace(root, force=True)
    code = main(["--config", str(root / "cvgen.toml"), "build"])
    if code != 0:
        raise SystemExit(f"example build failed with status {code}")
    tailored = root / "out" / "tailored"
    tailored.mkdir(parents=True, exist_ok=True)
    (tailored / "lumenfield-backend-es-short-report.md").write_text(REPORT, encoding="utf-8")
    (root / "out" / ".cvgen-intro").write_text("seen\n", encoding="utf-8")


def stub_tailor(config, **kwargs) -> int:
    """Pretend the model ran, using the report already stored in the demo."""
    on_stage = kwargs.get("on_stage")
    for message in (
        "Reading the job",
        "Asking the model",
        "Checking the facts",
        "Building the document",
    ):
        print(message)
        if on_stage is not None:
            on_stage(message)
    report = config.tailored_dir / "lumenfield-backend-es-short-report.md"
    if not report.is_file():
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(REPORT, encoding="utf-8")
    print("Done. Read the match report before sending the CV.")
    return 0


def save(app: CvgenApp, name: str) -> Path:
    """Write the Textual SVG, then a PNG that uses a font with box drawing and braille."""
    app.clear_notifications()
    svg = Path(app.save_screenshot(f"{name}.svg", path=str(OUT)))
    png = svg.with_suffix(".png")
    text = svg.read_text(encoding="utf-8")
    # Fira Code is referenced from a CDN and is not installed here. Cairo then
    # drops box-drawing and braille. DejaVu Sans Mono is installed and has both.
    text = text.replace("Fira Code, monospace", "DejaVu Sans Mono, monospace")
    cairosvg.svg2png(bytestring=text.encode("utf-8"), write_to=str(png))
    print(svg)
    print(png)
    return png


async def _until(pilot, ready) -> None:
    for _ in range(80):
        if ready():
            return
        await pilot.pause(0.1)
    raise SystemExit("timed out waiting for the screen")


async def capture_workspace(root: Path) -> None:
    app_module.run_tailor = stub_tailor
    app = CvgenApp(cwd=root, make_pdf=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        if pilot.app.screen.__class__.__name__ == "WelcomeModal":
            await pilot.press("escape")
            await pilot.pause()
        save(app, "start")

        await pilot.press("/")
        await pilot.press("enter")
        await pilot.pause()
        save(app, "palette")
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("ctrl+y")

        def verified() -> bool:
            screen = pilot.app.screen
            return screen.__class__.__name__ == "Dashboard" and "passed" in pilot.app.last_verify

        await _until(pilot, verified)
        await pilot.pause()
        save(app, "dashboard")

        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        screen = pilot.app.screen
        listing = screen.query_one("#jobs")
        listing.highlighted = 0
        screen.query_one("#fields").scroll_home(animate=False)
        await pilot.pause()
        save(app, "tailor")
        # Mouse clicks do not activate Button in Textual 8.2 (mouse-down marks
        # it active, and the click handler then skips press). press() is the
        # documented way to activate it from a pilot.
        screen.query_one("#generate").press()
        await pilot.pause()

        def finished() -> bool:
            screen = pilot.app.screen
            if not hasattr(screen, "query_one"):
                return False
            try:
                return screen.query_one("#result").has_class("hidden") is False
            except NoMatches:
                return False

        await _until(pilot, finished)
        await pilot.pause()
        save(app, "tailor-result")


async def capture_onboarding() -> None:
    if EMPTY.exists():
        shutil.rmtree(EMPTY)
    EMPTY.mkdir()
    app = CvgenApp(cwd=EMPTY, make_pdf=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        if pilot.app.screen.__class__.__name__ != "OnboardModal":
            raise SystemExit("expected the onboarding wizard")
        save(app, "onboard")


def main_script() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prepare_demo(DEMO)
    asyncio.run(capture_workspace(DEMO))
    asyncio.run(capture_onboarding())


if __name__ == "__main__":
    try:
        main_script()
    except KeyboardInterrupt:
        sys.exit(130)
