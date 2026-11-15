"""Small path helpers shared by the CLI."""

from __future__ import annotations

from pathlib import Path


def display_path(path: Path, root: Path | None = None) -> str:
    """Return a cwd-relative path when that stays inside root."""
    resolved = path.resolve()
    base = (root or Path.cwd()).resolve()
    try:
        return str(resolved.relative_to(base))
    except ValueError:
        return str(resolved)
