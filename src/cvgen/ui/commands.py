"""Menu, slash commands, key display, and match-report scores.

These functions do not import Textual, so the prompt behavior can be tested
without the UI extra.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cvgen.config import Config

_BOGOTA = ZoneInfo("America/Bogota")

DEFAULT_KEYS: dict[str, str] = {
    "build_all": "ctrl+b",
    "verify_all": "ctrl+y",
    "tailor": "ctrl+t",
    "dashboard": "ctrl+d",
    "new_workspace": "ctrl+n",
    "quit": "ctrl+q",
    "palette": "ctrl+p",
}

_KEY_ACTIONS = frozenset(DEFAULT_KEYS)


@dataclass(frozen=True)
class MenuItem:
    action: str
    title: str
    slash: str
    help: str


MENU: tuple[MenuItem, ...] = (
    MenuItem("build_all", "Build all", "/build", "Render every base CV"),
    MenuItem("verify_all", "Verify all", "/verify", "Fact-check every base CV"),
    MenuItem("tailor", "Tailor to a job", "/tailor", "Pick a posting and write a CV"),
    MenuItem("dashboard", "Dashboard", "/dashboard", "Base CVs, checks, and matches"),
    MenuItem("new_workspace", "New workspace", "/new", "Create source, cv, jobs, and out"),
    MenuItem("quit", "Quit", "/quit", "Leave the screen"),
)

_ALIASES = {
    "build": "build_all",
    "b": "build_all",
    "verify": "verify_all",
    "v": "verify_all",
    "tailor": "tailor",
    "t": "tailor",
    "dashboard": "dashboard",
    "variants": "dashboard",
    "d": "dashboard",
    "g": "dashboard",
    "new": "new_workspace",
    "init": "new_workspace",
    "n": "new_workspace",
    "quit": "quit",
    "q": "quit",
    "help": "help",
    "?": "help",
}


@dataclass(frozen=True)
class PromptAction:
    kind: str
    arg: str = ""


def parse_prompt(text: str) -> PromptAction:
    """Turn the bottom prompt into an action.

    An empty prompt asks what to paste. A URL, a path, or posting text
    without a slash opens tailor. ``/tailor jobs/x.txt`` does the same
    with an explicit command.
    """
    raw = text.strip()
    if not raw:
        return PromptAction("hint")
    if not raw.startswith("/"):
        return PromptAction("tailor", raw)
    body = raw[1:].strip()
    if not body:
        return PromptAction("palette")
    name, _, arg = body.partition(" ")
    kind = _ALIASES.get(name.lower())
    if kind is None:
        return PromptAction("unknown", raw)
    return PromptAction(kind, arg.strip())


def matching_commands(query: str) -> list[MenuItem]:
    needle = query.strip()
    if needle.startswith("/"):
        needle = needle[1:]
    needle = needle.split(" ", 1)[0].lower()
    if not needle:
        return list(MENU)
    return [item for item in MENU if needle in item.slash[1:] or needle in item.title.lower()]


def ui_key_overrides(config: Config) -> dict[str, str]:
    """Optional ``[ui.keys]`` table. Values are key strings, never secrets."""
    path = config.config_path
    if path is None or not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    ui = data.get("ui")
    if not isinstance(ui, dict):
        return {}
    keys = ui.get("keys")
    if not isinstance(keys, dict):
        return {}
    overrides: dict[str, str] = {}
    for name, value in keys.items():
        if name in _KEY_ACTIONS and isinstance(value, str) and value.strip():
            overrides[name] = value.strip()
    return overrides


def shortcut_for(action: str, config: Config | None = None) -> str:
    if config is not None:
        override = ui_key_overrides(config).get(action)
        if override:
            return override
    return DEFAULT_KEYS.get(action, "")


def parse_report(text: str) -> tuple[int, int, int]:
    """Count met, partial, and missing bullets in a tailor match report."""
    section: str | None = None
    counts = {"met": 0, "partial": 0, "missing": 0}
    for raw in text.splitlines():
        line = raw.strip().lower()
        if line.startswith("## "):
            if "missing" in line:
                section = "missing"
            elif "partial" in line:
                section = "partial"
            elif "met" in line:
                section = "met"
            else:
                section = None
            continue
        if section and raw.strip().startswith("- "):
            counts[section] += 1
    return counts["met"], counts["partial"], counts["missing"]


@dataclass(frozen=True)
class TailoredItem:
    title: str
    when: str
    met: int
    partial: int
    missing: int
    percent: int
    report: Path
    pdf: Path
    docx: Path


def _report_title(text: str, stem: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("# "):
            continue
        title = stripped[2:].strip()
        for prefix in ("Match report — ", "Match report - ", "Match report: "):
            if title.startswith(prefix):
                title = title[len(prefix) :].strip()
        return title or stem
    return stem.replace("-", " ")


def _match_percent(met: int, partial: int, missing: int) -> int:
    total = met + partial + missing
    if total == 0:
        return 0
    return round(100 * met / total)


def list_tailored(config: Config) -> list[TailoredItem]:
    directory = config.tailored_dir
    if not directory.is_dir():
        return []
    found: list[TailoredItem] = []
    reports = sorted(directory.glob("*-report.md"), key=lambda item: item.stat().st_mtime)
    for path in reports:
        body = path.read_text(encoding="utf-8")
        met, partial, missing = parse_report(body)
        stem = path.name.removesuffix("-report.md")
        cv = path.with_name(f"{stem}.md")
        stamp = datetime.fromtimestamp(path.stat().st_mtime, _BOGOTA)
        found.append(
            TailoredItem(
                title=_report_title(body, stem),
                when=stamp.strftime("%d %b %Y %H:%M"),
                met=met,
                partial=partial,
                missing=missing,
                percent=_match_percent(met, partial, missing),
                report=path.resolve(),
                pdf=cv.with_suffix(".pdf").resolve(),
                docx=cv.with_suffix(".docx").resolve(),
            )
        )
    return found


def format_tailored(items: list[TailoredItem], index: int) -> str:
    if not items:
        return "Paste a job link to create a tailored CV."
    lines: list[str] = []
    for position, item in enumerate(items):
        mark = ">" if position == index else " "
        lines.append(
            f"{mark} {item.title}\n"
            f"    {item.when}    {item.percent}% match"
            f"    met {item.met}  partial {item.partial}  missing {item.missing}"
        )
    return "\n".join(lines)


def tailored_reports(config: Config) -> list[tuple[str, int, int, int]]:
    return [(item.title, item.met, item.partial, item.missing) for item in list_tailored(config)]
