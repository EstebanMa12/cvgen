"""Menu, slash commands, key display, and match-report scores.

These functions do not import Textual, so the prompt behavior can be tested
without the UI extra.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from cvgen.config import Config

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
    MenuItem("build_all", "Build all", "/build", "Render every variant"),
    MenuItem("verify_all", "Verify all", "/verify", "Fact-check every variant"),
    MenuItem("tailor", "Tailor to a job", "/tailor", "Pick a posting and write a CV"),
    MenuItem("dashboard", "Dashboard", "/dashboard", "Variants, checks, and match scores"),
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

    An empty prompt activates the highlighted menu row. A path without a
    slash opens tailor for that file. ``/tailor jobs/x.txt`` does the same
    with an explicit command.
    """
    raw = text.strip()
    if not raw:
        return PromptAction("selected")
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


def tailored_reports(config: Config) -> list[tuple[str, int, int, int]]:
    directory = config.tailored_dir
    if not directory.is_dir():
        return []
    found: list[tuple[str, int, int, int]] = []
    for path in sorted(directory.glob("*-report.md"), key=lambda item: item.stat().st_mtime):
        met, partial, missing = parse_report(path.read_text(encoding="utf-8"))
        found.append((path.name.removesuffix(".md"), met, partial, missing))
    return found
