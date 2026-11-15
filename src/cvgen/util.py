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


def friendly_path(path: Path) -> str:
    """Show a path under the home directory as ``~/...``."""
    resolved = path.resolve()
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    if str(relative) == ".":
        return "~"
    return f"~/{relative.as_posix()}"


GREEN = "#50fa7b"
YELLOW = "#f1fa8c"
ORANGE = "#ffb86c"
PINK = "#ff79c6"
CYAN = "#8be9fd"
RED = "#ff5555"
COMMENT = "#6272a4"


def tint(text: str, color: str) -> str:
    """Textual content markup for one colored span."""
    return f"[{color}]{text}[/]"
