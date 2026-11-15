#!/usr/bin/env python3
"""Save headless screenshots of the cvgen screen.

Uses only the fictional example from ``cvgen init`` (Avery Quinn, Northwind
Labs, Harbor & Co., Lumenfield, and the other example names). No provider
key is required: the tailor result is a prerecorded match report.

The process clears ``NO_COLOR`` before Textual starts, otherwise the
Dracula CSS is flattened to gray. PNG conversion embeds DejaVu Sans Mono
and redraws the braille logo as filled dots, because Cairo paints U+2800
as empty boxes once ``textLength`` is set.

    pip install '.[ui]' cairosvg
    python scripts/make_screenshots.py
"""

from __future__ import annotations

import os

os.environ.pop("NO_COLOR", None)
os.environ["FORCE_COLOR"] = "1"
os.environ["TERM"] = "xterm-256color"
os.environ["COLORTERM"] = "truecolor"
os.environ["TEXTUAL_COLOR_SYSTEM"] = "truecolor"

import asyncio
import re
import shutil
import sys
from html import unescape
from pathlib import Path

import cairosvg
from textual.css.query import NoMatches

import cvgen.ui.app as app_module
from cvgen.cli import main
from cvgen.scaffold import init_workspace
from cvgen.ui.app import CvgenApp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
HOME = Path("/tmp/cvgen-home")
os.environ["HOME"] = str(HOME)
DEMO = HOME / "cv-workspace"
EMPTY = HOME / "cv-new"
SIZE = (148, 46)
DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")

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


_BRAILLE_DOTS = (
    (0, 0, 0x01),
    (0, 1, 0x02),
    (0, 2, 0x04),
    (1, 0, 0x08),
    (1, 1, 0x10),
    (1, 2, 0x20),
    (0, 3, 0x40),
    (1, 3, 0x80),
)


def _draw_braille(svg: str) -> str:
    """Replace braille text with filled dots.

    Cairo draws U+2800 from the usual monospace fonts as empty boxes, and
    ``textLength`` makes a real braille font do the same. Dots keep the logo.
    """

    def repl(match: re.Match[str]) -> str:
        tag, body = match.group(1), match.group(2)
        raw = unescape(body)
        if not any(0x2800 <= ord(char) <= 0x28FF for char in raw):
            return match.group(0)
        x_match = re.search(r'\bx="([^"]+)"', tag)
        y_match = re.search(r'\by="([^"]+)"', tag)
        length_match = re.search(r'textLength="([^"]+)"', tag)
        if x_match is None or y_match is None:
            return match.group(0)
        origin_x = float(x_match.group(1))
        baseline = float(y_match.group(1))
        chars = list(raw)
        width = float(length_match.group(1)) if length_match else 12.2 * len(chars)
        cell = width / max(len(chars), 1)
        fill = "#bd93f9"
        class_match = re.search(r'class="([^"]+)"', tag)
        if class_match:
            rule = re.search(
                rf"\.{re.escape(class_match.group(1))}\s*\{{[^}}]*fill:\s*(#[0-9A-Fa-f]+)",
                svg,
            )
            if rule:
                fill = rule.group(1)
        radius = max(1.15, cell * 0.13)
        circles: list[str] = []
        for index, char in enumerate(chars):
            code = ord(char)
            if not 0x2800 <= code <= 0x28FF:
                continue
            bits = code - 0x2800
            left = origin_x + index * cell
            top = baseline - cell * 1.45
            for column, row, bit in _BRAILLE_DOTS:
                if bits & bit:
                    cx = left + cell * (0.30 + column * 0.42)
                    cy = top + cell * 0.36 * row + radius
                    circles.append(
                        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" fill="{fill}"/>'
                    )
        return "".join(circles)

    return re.sub(r"(<text\b[^>]*>)(.*?)</text>", repl, svg, flags=re.DOTALL)


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
    """Write the Textual SVG, then a 2x PNG.

    The PNG uses the installed DejaVu Sans Mono. A data-URI font plus
    ``textLength`` makes Cairo drop box-drawing glyphs, so the braille logo
    is drawn as filled dots instead.
    """
    app.clear_notifications()
    svg_path = Path(app.save_screenshot(f"{name}.svg", path=str(OUT)))
    svg = svg_path.read_text(encoding="utf-8")
    lowered = svg.lower()
    if "282a36" not in lowered and "bd93f9" not in lowered and "1e1f29" not in lowered:
        raise SystemExit(f"{name}.svg lost the Dracula colors. Is NO_COLOR set?")
    styled = svg.replace(
        "font-family: Fira Code, monospace;",
        'font-family: "DejaVu Sans Mono", monospace;',
    )
    styled = _draw_braille(styled)
    png = svg_path.with_suffix(".png")
    cairosvg.svg2png(bytestring=styled.encode("utf-8"), write_to=str(png), scale=2)
    print(svg_path)
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
    EMPTY.mkdir(parents=True)
    app = CvgenApp(cwd=EMPTY, make_pdf=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        if pilot.app.screen.__class__.__name__ != "OnboardModal":
            raise SystemExit("expected the onboarding wizard")
        save(app, "onboard")


def main_script() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    HOME.mkdir(parents=True, exist_ok=True)
    if not DEJAVU.is_file():
        raise SystemExit("Need DejaVu Sans Mono. Debian: sudo apt install fonts-dejavu-core")
    prepare_demo(DEMO)
    asyncio.run(capture_workspace(DEMO))
    asyncio.run(capture_onboarding())


if __name__ == "__main__":
    try:
        main_script()
    except KeyboardInterrupt:
        sys.exit(130)
