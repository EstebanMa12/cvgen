"""CV Markdown grammar.

    # Name                         centered name
    > Headline                     optional line under the name
    plain lines before the first ## contact lines
    ## SECTION                     section heading
    **Left** | Right               bold entry, right-aligned place or date
    **Left**                       bold entry without a right-hand side
    *Left | Right*                 italic role and dates
    *...*                          italic technologies line (no pipe)
    - text                         bullet, with optional inline **bold** / *italic*
    plain text                     paragraph
    <!-- ... -->                   comment, never rendered
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

SPANISH_HEADINGS = frozenset(
    {
        "PERFIL PROFESIONAL",
        "EXPERIENCIA PROFESIONAL",
        "FORMACIÓN ACADÉMICA",
        "HABILIDADES TÉCNICAS",
        "IDIOMAS",
        "PROYECTOS",
        "CERTIFICACIONES",
    }
)
SKILL_HEADINGS = ("SKILLS", "HABILIDADES")

_ENTRY_WITH_RIGHT = re.compile(r"\*\*.+?\*\*\s*\|.+")
_ENTRY_ONLY = re.compile(r"\*\*[^*]+\*\*")


class Section(TypedDict):
    title: str
    items: list[tuple]


class CvModel(TypedDict):
    name: str
    headline: str
    contact: list[str]
    sections: list[Section]


def strip_comments(text: str) -> str:
    """Remove <!-- ... --> comments, including multi-line ones."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def parse_markdown(text: str) -> CvModel:
    """Parse a CV markdown string into a document model."""
    lines = strip_comments(text).splitlines()
    model: CvModel = {"name": "", "headline": "", "contact": [], "sections": []}
    section: Section | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and not line.startswith("## "):
            model["name"] = line[2:].strip()
        elif line.startswith("## "):
            section = {"title": line[3:].strip(), "items": []}
            model["sections"].append(section)
        elif section is None and line.startswith(">"):
            model["headline"] = line.lstrip(">").strip()
        elif section is None:
            model["contact"].append(line)
        elif line.startswith("- "):
            section["items"].append(("bullet", line[2:].strip()))
        elif _ENTRY_WITH_RIGHT.fullmatch(line):
            left, right = line.split("|", 1)
            section["items"].append(("entry", left.strip().strip("*").strip(), right.strip()))
        elif _ENTRY_ONLY.fullmatch(line):
            section["items"].append(("entry", line.strip("*").strip(), ""))
        elif re.fullmatch(r"\*[^*].*?\*", line):
            inner = line[1:-1].strip()
            if "|" in inner:
                left, right = inner.split("|", 1)
                section["items"].append(("subentry", left.strip(), right.strip()))
            else:
                section["items"].append(("tech", inner))
        else:
            section["items"].append(("text", line))
    return model


def parse_markdown_file(path: Path) -> CvModel:
    return parse_markdown(path.read_text(encoding="utf-8"))


def detect_language(model: CvModel) -> str:
    titles = {section["title"].upper() for section in model["sections"]}
    return "es" if titles & SPANISH_HEADINGS else "en"


def extract_skills(model: CvModel) -> list[str]:
    """Flatten skill bullets ("**Category:** a, b") into a keyword list."""
    skills: list[str] = []
    for section in model["sections"]:
        if not section["title"].upper().startswith(SKILL_HEADINGS):
            continue
        for item in section["items"]:
            if item[0] != "bullet":
                continue
            text = re.sub(r"^\*\*[^*]+\*\*\s*", "", item[1])
            for skill in text.split(","):
                cleaned = skill.strip().strip(".")
                if cleaned and cleaned not in skills:
                    skills.append(cleaned)
    return skills


def model_text(model: CvModel) -> str:
    parts: list[str] = [model["name"], model["headline"], *model["contact"]]
    for section in model["sections"]:
        parts.append(section["title"])
        for item in section["items"]:
            parts.extend(str(part) for part in item[1:] if part)
    return "\n".join(part for part in parts if part)
