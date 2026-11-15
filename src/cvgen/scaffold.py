"""Copy the fictional example workspace into a directory."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from cvgen.config import ConfigError

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

SCAFFOLD_FILES = (
    ("cvgen.toml", "cvgen.toml"),
    ("consolidated.md", "source/consolidated.md"),
    ("short-en.md", "cv/avery-quinn-short-en.md"),
    ("short-es.md", "cv/avery-quinn-short-es.md"),
    ("extended-en.md", "cv/avery-quinn-extended-en.md"),
    ("extended-es.md", "cv/avery-quinn-extended-es.md"),
    ("job.txt", "jobs/lumenfield-backend.txt"),
)


def init_workspace(directory: Path, *, force: bool = False) -> list[Path]:
    root = directory.resolve()
    planned = [(TEMPLATE_DIR / name, root / relative) for name, relative in SCAFFOLD_FILES]
    missing = [source for source, _dest in planned if not source.is_file()]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise ConfigError(f"Package templates are missing: {joined}")
    existing = [dest for _source, dest in planned if dest.exists()]
    if existing and not force:
        listed = "\n".join(f"  {path}" for path in existing)
        raise ConfigError("Refusing to overwrite existing files. Pass --force to replace them:\n" + listed)
    written: list[Path] = []
    for source, dest in planned:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(dest)
    _ensure_dirs(root)
    return written


def slug_name(name: str) -> str:
    folded = unicodedata.normalize("NFD", name)
    ascii_text = "".join(char for char in folded if unicodedata.category(char) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:40] or "cv"


def init_blank(directory: Path, name: str) -> list[Path]:
    """Folders plus a CV that contains only this person's name."""
    root = directory.resolve()
    cleaned = name.strip()
    if len(cleaned) < 2:
        raise ConfigError("Type the name that should appear on the CV.")
    slug = slug_name(cleaned)
    files = {
        "cvgen.toml": _blank_config(cleaned, slug),
        "source/consolidated.md": _blank_source(cleaned),
        f"cv/{slug}-short-en.md": _blank_cv(cleaned, "en", "short"),
        f"cv/{slug}-short-es.md": _blank_cv(cleaned, "es", "short"),
        f"cv/{slug}-extended-en.md": _blank_cv(cleaned, "en", "extended"),
        f"cv/{slug}-extended-es.md": _blank_cv(cleaned, "es", "extended"),
        "jobs/posting.txt": (
            "Role title\n\n"
            "Describe the job here. This file is a posting, not a source of facts.\n"
        ),
    }
    planned = [(root / relative, text) for relative, text in files.items()]
    existing = [path for path, _text in planned if path.exists()]
    if existing:
        listed = "\n".join(f"  {path}" for path in existing)
        raise ConfigError("Refusing to overwrite existing files:\n" + listed)
    written: list[Path] = []
    for path, text in planned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    _ensure_dirs(root)
    return written


def _ensure_dirs(root: Path) -> None:
    for relative in ("source", "cv", "jobs", "out", "out/tailored"):
        (root / relative).mkdir(parents=True, exist_ok=True)


def _toml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _blank_config(name: str, slug: str) -> str:
    variants = []
    for length in ("short", "extended"):
        for lang in ("en", "es"):
            variant_id = f"{length}-{lang}"
            filename = f"{slug}-{variant_id}.md"
            variants.append(
                "\n".join(
                    [
                        "[[variants]]",
                        f"id = {_toml(variant_id)}",
                        f"input = {_toml(f'cv/{filename}')}",
                        f"output = {_toml(f'{slug}-{variant_id}.docx')}",
                        f"length = {_toml(length)}",
                        f"lang = {_toml(lang)}",
                        "",
                    ]
                )
            )
    header = "\n".join(
        [
            "# cvgen workspace. Do not put API keys in this file.",
            "",
            "[person]",
            f"name = {_toml(name)}",
            "",
            "[paths]",
            'source = "source/consolidated.md"',
            'output_dir = "out"',
            'tailored_dir = "out/tailored"',
            "",
            "[build]",
            'font = "Times New Roman"',
            'locale_es = "es"',
            'locale_en = "en-US"',
            "short_max_pages = 1",
            "extended_max_pages = 2",
            "",
            "[verify]",
            'forbidden = ["TODO", "lorem", "placeholder"]',
            "extra_known_tech = []",
            "",
            "[tailor]",
            'provider = "openai"',
            'model = "gpt-4o-mini"',
            "temperature = 0.2",
            "",
        ]
    )
    return header + "\n".join(variants)


def _blank_source(name: str) -> str:
    return (
        f"# Consolidated source of truth\n\n"
        f"{name}\n\n"
        f"Add employers, titles, dates and technologies here before they appear on a CV.\n"
    )


def _blank_cv(name: str, lang: str, length: str) -> str:
    if lang == "es":
        profile = "PERFIL PROFESIONAL"
        sentence = f"{name} mantiene los hechos de esta hoja de vida en la fuente consolidada."
    else:
        profile = "PROFILE"
        sentence = f"{name} keeps the facts for this CV in the consolidated source."
    extra = ""
    if length == "extended":
        extra = (
            "\nThe extended CV can grow until it fills two pages.\n"
            if lang == "en"
            else "\nLa versión extendida puede crecer hasta ocupar dos páginas.\n"
        )
    return f"# {name}\n\n## {profile}\n{sentence}\n{extra}"
