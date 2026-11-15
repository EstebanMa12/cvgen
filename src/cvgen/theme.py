"""Dracula palette for the interactive screen.

The 256-color values are the usual xterm approximations of Dracula:
background #282a36, purple #bd93f9, pink #ff79c6, cyan #8be9fd.
Terminals with only 16 colors fall back to magenta on black.
"""

from __future__ import annotations

import curses

DRACULA_256 = {
    "bg": 236,
    "current": 238,
    "fg": 255,
    "comment": 103,
    "purple": 141,
    "pink": 212,
    "cyan": 117,
    "green": 84,
    "orange": 215,
    "red": 203,
    "ink": 236,
}


def palette(colors: int) -> dict[str, int]:
    if colors >= 256:
        return dict(DRACULA_256)
    return {
        "bg": curses.COLOR_BLACK,
        "current": curses.COLOR_BLACK,
        "fg": curses.COLOR_WHITE,
        "comment": curses.COLOR_CYAN,
        "purple": curses.COLOR_MAGENTA,
        "pink": curses.COLOR_MAGENTA,
        "cyan": curses.COLOR_CYAN,
        "green": curses.COLOR_GREEN,
        "orange": curses.COLOR_YELLOW,
        "red": curses.COLOR_RED,
        "ink": curses.COLOR_BLACK,
    }


def apply_theme(window: curses.window) -> None:
    """Install color pairs. Pair 1 is the window background."""
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    colors = palette(curses.COLORS)
    bg = colors["bg"]
    fg = colors["fg"]
    purple = colors["purple"]
    pink = colors["pink"]
    current = colors["current"]
    ink = colors["ink"]
    pairs = (
        (1, fg, bg),
        (2, ink, purple),
        (3, purple, bg),
        (4, colors["red"], bg),
        (5, ink, pink),
        (6, pink, current),
        (7, colors["green"], bg),
        (8, colors["orange"], bg),
        (9, ink, purple),
        (10, pink, bg),
        (11, colors["comment"], bg),
        (12, colors["cyan"], bg),
    )
    for number, foreground, background in pairs:
        curses.init_pair(number, foreground, background)
    window.bkgd(" ", curses.color_pair(1))
