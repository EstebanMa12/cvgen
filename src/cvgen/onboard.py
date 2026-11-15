"""Guided creation of a cvgen workspace from the interactive screen."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from cvgen.scaffold import init_blank, init_workspace

WELCOME = (
    "Create the workspace folders",
    "",
    "cvgen keeps a CV in a few directories. This step creates them",
    "where you choose:",
    "",
    "  cvgen.toml     configuration, including your name",
    "  source/        the only facts a CV is allowed to use",
    "  cv/            Markdown for each language and length",
    "  jobs/          a posting, when you want to tailor",
    "  out/           the DOCX and PDF files",
    "",
    "Enter continues. Esc goes back. F10 quits.",
)


@dataclass
class Wizard:
    step: str = "welcome"
    folder: str = ""
    name: str = ""
    kind: str = "example"


def steps(kind: str) -> tuple[str, ...]:
    if kind == "blank":
        return ("welcome", "folder", "kind", "name", "review")
    return ("welcome", "folder", "kind", "review")


def folder_error(text: str) -> str | None:
    raw = text.strip() or "."
    path = Path(raw)
    if path.is_absolute():
        return "Use a relative folder, or . for this directory."
    if ".." in path.parts:
        return "The folder cannot climb out with .."
    if raw != "." and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", raw) is None:
        return "Use letters, numbers, dots, dashes and slashes."
    return None


def name_error(text: str) -> str | None:
    cleaned = text.strip()
    if len(cleaned) < 2:
        return "Type the name that should appear on the CV."
    if any(character in cleaned for character in "\n\r#"):
        return "The name cannot contain a new line or #."
    return None


def destination(base: Path, folder: str) -> Path:
    return (base / (folder.strip() or ".")).resolve()


def handle(wizard: Wizard, action: str) -> str:
    """Apply one action. Returns stay, create, or quit. The wizard is updated."""
    if action == "quit":
        return "quit"
    if action == "back":
        order = steps(wizard.kind)
        index = order.index(wizard.step) if wizard.step in order else 0
        wizard.step = order[max(0, index - 1)]
        return "stay"
    if action == "backspace":
        if wizard.step == "folder" and wizard.folder:
            wizard.folder = wizard.folder[:-1]
        elif wizard.step == "name" and wizard.name:
            wizard.name = wizard.name[:-1]
        return "stay"
    if action.startswith("type:"):
        character = action.removeprefix("type:")
        if wizard.step == "folder":
            wizard.folder += character
        elif wizard.step == "name":
            wizard.name += character
        return "stay"
    if action in {"up", "down"} and wizard.step == "kind":
        wizard.kind = "blank" if wizard.kind == "example" else "example"
        return "stay"
    if action != "next":
        return "stay"
    if wizard.step == "folder" and folder_error(wizard.folder):
        return "stay"
    if wizard.step == "name" and name_error(wizard.name):
        return "stay"
    if wizard.step == "review":
        return "create"
    order = steps(wizard.kind)
    index = order.index(wizard.step) if wizard.step in order else 0
    wizard.step = order[min(len(order) - 1, index + 1)]
    return "stay"


def screen_lines(wizard: Wizard, base: Path) -> list[tuple[str, str]]:
    """Lines for the current step. Each item is (role, text)."""
    if wizard.step == "welcome":
        return [("title", WELCOME[0]), *[("body", line) for line in WELCOME[1:]]]
    if wizard.step == "folder":
        typed = wizard.folder if wizard.folder else ""
        problem = folder_error(wizard.folder)
        lines = [
            ("title", "Where should the folders go?"),
            ("body", ""),
            ("field", f"  path: {typed}▏"),
            ("dim", "  . uses this directory. A name such as my-cv creates that folder."),
            ("dim", f"  result: {destination(base, wizard.folder)}"),
        ]
        if problem:
            lines.append(("alert", f"  {problem}"))
        return lines
    if wizard.step == "kind":
        example = ">" if wizard.kind == "example" else " "
        blank = ">" if wizard.kind == "blank" else " "
        return [
            ("title", "What goes inside the folders?"),
            ("body", ""),
            ("field" if wizard.kind == "example" else "body", f"  {example} Example    Avery Quinn and fictional companies, ready to build"),
            ("field" if wizard.kind == "blank" else "body", f"  {blank} Blank      your name only, you add every fact afterwards"),
            ("dim", ""),
            ("dim", "  j/k or arrows choose. Enter continues."),
        ]
    if wizard.step == "name":
        problem = name_error(wizard.name) if wizard.name else None
        lines = [
            ("title", "Name on the CV"),
            ("body", ""),
            ("field", f"  name: {wizard.name}▏"),
            ("dim", "  This is the only fact on the blank CV until you edit the source."),
        ]
        if problem and wizard.name:
            lines.append(("alert", f"  {problem}"))
        return lines
    kind = "Example, Avery Quinn" if wizard.kind == "example" else f"Blank, {wizard.name.strip()}"
    return [
        ("title", "Create these folders?"),
        ("body", ""),
        ("body", f"  where    {destination(base, wizard.folder)}"),
        ("body", f"  content  {kind}"),
        ("body", "  folders  source/   cv/   jobs/   out/"),
        ("dim", ""),
        ("dim", "  Enter creates them. Esc goes back."),
    ]


def hint(wizard: Wizard) -> str:
    if wizard.step == "review":
        return "Enter creates the folders    Esc back    F10 quit"
    if wizard.step == "kind":
        return "j/k choose    Enter next    Esc back    F10 quit"
    if wizard.step == "welcome":
        return "Enter next    F10 quit"
    return "Type, then Enter    Esc back    F10 quit"


def keys(wizard: Wizard) -> tuple[tuple[str, str], ...]:
    if wizard.step == "review":
        return (("Enter", "Create"), ("Esc", "Back"), ("F10", "Quit"))
    if wizard.step == "welcome":
        return (("Enter", "Next"), ("F10", "Quit"))
    return (("Enter", "Next"), ("Esc", "Back"), ("F10", "Quit"))


def create(base: Path, wizard: Wizard) -> Path:
    """Create the workspace and return the directory that now holds cvgen.toml."""
    root = destination(base, wizard.folder)
    root.mkdir(parents=True, exist_ok=True)
    if wizard.kind == "blank":
        problem = name_error(wizard.name)
        if problem:
            raise ValueError(problem)
        init_blank(root, wizard.name.strip())
    else:
        init_workspace(root, force=False)
    return root
