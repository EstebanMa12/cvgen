"""Add a base CV: one Markdown file plus a [[variants]] entry."""

from __future__ import annotations

import re
from pathlib import Path

from cvgen.config import Config, ConfigError, load_config
from cvgen.scaffold import slug_name

_LENGTH = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")


def normalize_length(length: str, max_pages: int | None) -> tuple[str, int | None]:
    label = length.strip().lower().replace(" ", "-")
    if label in {"short", "extended"}:
        if max_pages is not None and max_pages < 1:
            raise ConfigError("max-pages must be 1 or more.")
        return label, max_pages
    if _LENGTH.fullmatch(label) is None:
        raise ConfigError("Length must be short, extended, or a label such as one-page.")
    if max_pages is None:
        raise ConfigError("A custom length needs a page limit (max-pages).")
    if max_pages < 1:
        raise ConfigError("max-pages must be 1 or more.")
    return label, max_pages


def add_base_cv(
    config: Config,
    *,
    name: str,
    lang: str,
    length: str,
    max_pages: int | None = None,
    copy_from: str | None = None,
    blank: bool = False,
) -> Path:
    """Write the Markdown CV and append it to cvgen.toml. Returns the new file."""
    if config.config_path is None:
        raise ConfigError("No cvgen.toml here. Run cvgen init or create a workspace first.")
    title = name.strip()
    if len(title) < 2:
        raise ConfigError("Give the base CV a name, such as Short English.")
    if lang not in {"es", "en"}:
        raise ConfigError("Language must be es or en.")
    length_label, pages = normalize_length(length, max_pages)
    variant_id = slug_name(title)
    if any(variant.id == variant_id for variant in config.variants):
        raise ConfigError(f"A base CV named {variant_id!r} already exists.")
    markdown = config.root / "cv" / f"{variant_id}.md"
    if markdown.exists():
        raise ConfigError(f"Refusing to overwrite {markdown}.")
    if copy_from and blank:
        raise ConfigError("Start from an existing CV or from blank, not both.")
    if copy_from:
        source = next((variant for variant in config.variants if variant.id == copy_from), None)
        if source is None or not source.input_path.is_file():
            raise ConfigError(f"No base CV {copy_from!r} to copy.")
        body = source.input_path.read_text(encoding="utf-8")
    else:
        body = _blank_cv(config.person_name or title, lang, length_label)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(body, encoding="utf-8")
    output = f"{variant_id}.docx"
    lines = [
        "",
        "[[variants]]",
        f'id = "{variant_id}"',
        f'input = "cv/{variant_id}.md"',
        f'output = "{output}"',
        f'length = "{length_label}"',
        f'lang = "{lang}"',
    ]
    if pages is not None:
        lines.append(f"max_pages = {pages}")
    lines.append("")
    with config.config_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    load_config(config.config_path)
    return markdown


def _blank_cv(name: str, lang: str, length: str) -> str:
    if lang == "es":
        heading = "PERFIL PROFESIONAL"
        sentence = f"{name} mantiene los hechos de esta hoja de vida en la fuente consolidada."
    else:
        heading = "PROFILE"
        sentence = f"{name} keeps the facts for this CV in the consolidated source."
    note = ""
    if length not in {"short", "extended"}:
        note = f"\nLength label: {length}.\n"
    return f"# {name}\n\n## {heading}\n{sentence}\n{note}"
