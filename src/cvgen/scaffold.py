"""Copy the fictional example workspace into a directory."""

from __future__ import annotations

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
    return written
