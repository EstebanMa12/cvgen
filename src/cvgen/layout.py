"""Page budgets and the shrink steps used to meet them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

PAGE_LIMITS = {"short": 1, "extended": 2}

# Spacing profiles. "short" targets one page; "extended" targets two.
STYLES: dict[str, dict[str, float]] = {
    "extended": {
        "margin": 0.7,
        "body_size": 10.5,
        "tech_size": 9.5,
        "name_size": 16,
        "headline_size": 10.5,
        "contact_size": 10,
        "heading_size": 11.5,
        "heading_before": 5,
        "heading_after": 3,
        "bullet_after": 1,
        "entry_before": 3,
        "tech_after": 1,
        "body_after": 2,
        "line_spacing": 1.0,
    },
    "short": {
        "margin": 0.5,
        "body_size": 10,
        "tech_size": 9,
        "name_size": 15,
        "headline_size": 9.5,
        "contact_size": 9,
        "heading_size": 11,
        "heading_before": 4,
        "heading_after": 2,
        "bullet_after": 0,
        "entry_before": 2,
        "tech_after": 1,
        "body_after": 1,
        "line_spacing": 0.95,
    },
}

MAX_FIT_STEPS = 6
FIT_FACTOR = 0.97
MIN_BODY_SIZE = {"short": 9.0, "extended": 9.5}
MIN_MARGIN = {"short": 0.45, "extended": 0.6}
MIN_LINE_SPACING = 0.9

LENGTHS = ("short", "extended")


def shrink_style(style: dict[str, float], length: str) -> dict[str, float] | None:
    """Return a slightly tighter copy of style, or None at the floor.

    The input dict is not modified. Font size stops at 9 pt (short) or
    9.5 pt (extended); past that the caller must trim the Markdown.
    """
    if length not in MIN_BODY_SIZE:
        raise ValueError(f"Unknown length {length!r}. Expected 'short' or 'extended'.")
    if style["body_size"] * FIT_FACTOR < MIN_BODY_SIZE[length]:
        return None
    tighter: dict[str, float] = {}
    for key, value in style.items():
        if key == "margin":
            tighter[key] = max(MIN_MARGIN[length], round(value - 0.05, 2))
        elif key == "line_spacing":
            tighter[key] = max(MIN_LINE_SPACING, round(value - 0.01, 2))
        else:
            tighter[key] = round(value * FIT_FACTOR, 2)
    return tighter


@dataclass(frozen=True)
class FitResult:
    style: dict[str, float]
    pages: int
    steps: int
    ok: bool


def fit_style(
    style: dict[str, float],
    length: str,
    measure: Callable[[dict[str, float]], int],
    *,
    limit: int,
    max_steps: int = MAX_FIT_STEPS,
) -> FitResult:
    """Shrink style until measure(style) is within limit, or the floor is hit.

    measure is called with the style that should be rendered. It returns a
    page count. The original style dict is not modified.
    """
    current = dict(style)
    pages = measure(current)
    steps = 0
    while pages > limit and steps < max_steps:
        nxt = shrink_style(current, length)
        if nxt is None:
            break
        steps += 1
        current = nxt
        pages = measure(current)
    return FitResult(style=current, pages=pages, steps=steps, ok=pages <= limit)
