"""Interactive screen.

Running ``cvgen`` in a terminal opens this view. The bottom bar lists the
keys, in the same spirit as htop: the commands stay on screen while you move
through the variants.
"""

from __future__ import annotations

import curses
import io
import os
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from cvgen import __version__
from cvgen.build import BuildJob, build_one, soffice_available
from cvgen.config import Config, ConfigError, load_workspace
from cvgen.pdf import count_pdf_pages
from cvgen.providers.base import DEFAULT_MODELS, ProviderError, canonicalize
from cvgen.scaffold import init_workspace
from cvgen.tailor import run_tailor
from cvgen.util import display_path
from cvgen.verify import verify_paths

BROWSE_KEYS = (
    ("F1", "Help"),
    ("F2", "Init"),
    ("F5", "Build"),
    ("F6", "Verify"),
    ("F7", "Tailor"),
    ("F10", "Quit"),
)
HELP_KEYS = (("Esc", "Close"), ("F10", "Quit"))
JOB_KEYS = (("Enter", "Dry-run"), ("F5", "Run"), ("Esc", "Cancel"))
BROWSE_HINT = "j/k move    Enter build    B build all    v verify    V verify all    r refresh    q quit"
HELP_TEXT = (
    "The bar at the bottom lists the keys. Letters do the same thing.",
    "",
    "Up/Down, j/k     move",
    "Enter, b, F5     build the highlighted CV",
    "B                build every variant",
    "v, F6            verify the highlighted CV",
    "V                verify every variant",
    "t, F7            tailor. Enter writes the prompt, F5 calls the provider",
    "r refresh       F1 or ? help       q or F10 quit       Esc back",
    "",
    "Shell:  cvgen build",
    "        cvgen verify",
    "        cvgen tailor --job FILE --lang es --length short --dry-run",
)


@dataclass
class VariantRow:
    id: str
    lang: str
    length: str
    limit: int
    markdown: Path
    docx: Path
    pdf: Path
    markdown_ok: bool
    docx_ok: bool
    pages: int | None


@dataclass
class Screen:
    root: Path
    config: Config
    rows: list[VariantRow] = field(default_factory=list)
    selected: int = 0
    mode: str = "browse"
    job: str = ""
    log: list[str] = field(default_factory=list)
    status: str = ""
    soffice: bool = False

    def clamp(self) -> None:
        if not self.rows:
            self.selected = 0
            return
        self.selected = max(0, min(self.selected, len(self.rows) - 1))


def bar(ratio: float, width: int = 10) -> str:
    """A one-line meter. ratio 0 is empty, 1 is full."""
    slots = max(1, width)
    bounded = min(1.0, max(0.0, ratio))
    filled = round(bounded * slots)
    return "█" * filled + "░" * (slots - filled)


def format_pages(pages: int | None, limit: int) -> str:
    if pages is None:
        return "—"
    return f"{pages}/{limit}"


def page_ratio(pages: int | None, limit: int) -> float:
    if pages is None or limit <= 0:
        return 0.0
    return min(1.0, pages / limit)


def collect_rows(config: Config) -> list[VariantRow]:
    rows: list[VariantRow] = []
    for variant in config.variants:
        docx = config.output_dir / variant.output_name
        pdf = docx.with_suffix(".pdf")
        pages = None
        if pdf.is_file():
            try:
                pages = count_pdf_pages(pdf)
            except OSError:
                pages = None
        rows.append(
            VariantRow(
                id=variant.id,
                lang=variant.lang,
                length=variant.length,
                limit=config.page_limits[variant.length],
                markdown=variant.input_path,
                docx=docx,
                pdf=pdf,
                markdown_ok=variant.input_path.is_file(),
                docx_ok=docx.is_file(),
                pages=pages,
            )
        )
    return rows


def load_screen(config_path: Path | None, root: Path | None = None) -> Screen:
    base = (root or Path.cwd()).resolve()
    config = load_workspace(config_path, cwd=base)
    screen = Screen(root=config.root, config=config, soffice=soffice_available())
    screen.rows = collect_rows(config)
    if config.config_path is None:
        screen.log = ["No cvgen.toml here. Press F2 to create the example workspace."]
    else:
        screen.log = [f"{len(screen.rows)} variants. F5 builds the highlighted row, F6 checks it."]
    return screen


def busiest(rows: list[VariantRow]) -> tuple[float, str]:
    """The variant using the largest share of its page budget."""
    measured = [row for row in rows if row.pages is not None]
    if not measured:
        return 0.0, "no PDF yet"
    row = max(measured, key=lambda item: page_ratio(item.pages, item.limit))
    return page_ratio(row.pages, row.limit), f"{row.id} {format_pages(row.pages, row.limit)}"


def provider_label(config: Config) -> str:
    if config.config_path is None:
        return "no workspace"
    try:
        provider = canonicalize(config.provider)
    except ConfigError:
        return config.provider
    model = config.model or DEFAULT_MODELS[provider]
    return f"{provider}  {model}"


def table_line(row: VariantRow, selected: bool) -> str:
    marker = ">" if selected else " "
    pages = format_pages(row.pages, row.limit)
    meter = bar(page_ratio(row.pages, row.limit))
    docx = "yes" if row.docx_ok else "no"
    pdf = "yes" if row.pages is not None else "no"
    name = row.id if row.markdown_ok else f"{row.id} !"
    return f" {marker} {name:<16} {row.lang:<4} {row.length:<9} {docx:<4} {pdf:<4} {meter} {pages:>5} "


def header_labels() -> str:
    return f"   {'variant':<16} {'lang':<4} {'length':<9} {'docx':<4} {'pdf':<4} {'fill':<10} {'pages':>5} "


def capture(action: Callable[[], int]) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = action()
    except ProviderError as exc:
        code = exc.code
        stderr.write(f"{exc}\n")
    except ConfigError as exc:
        code = 1
        stderr.write(f"{exc}\n")
    except Exception as exc:
        code = 1
        stderr.write(f"{exc}\n")
    text = (stdout.getvalue() + stderr.getvalue()).strip()
    return code, text


def perform_init(directory: Path) -> int:
    written = init_workspace(directory, force=False)
    print(f"Initialized {len(written)} files in {directory}")
    return 0


def perform_build(
    config: Config,
    rows: list[VariantRow],
    indexes: list[int],
    *,
    make_pdf: bool | None = None,
) -> int:
    if not indexes:
        print("Nothing to build. Press F2 to create a workspace.")
        return 1
    if make_pdf is None:
        make_pdf = soffice_available()
    if not make_pdf:
        print("LibreOffice was not found. Writing DOCX files only.")
    ok = True
    for index in indexes:
        row = rows[index]
        if not row.markdown.is_file():
            print(f"Missing Markdown: {row.markdown}")
            ok = False
            continue
        job = BuildJob(row.markdown, row.docx, row.length)
        ok = build_one(job, config, make_pdf=make_pdf, autofit=True) and ok
    print("\nBuild finished." if ok else "\nBuild reported a problem.")
    return 0 if ok else 1


def perform_verify(config: Config, rows: list[VariantRow], indexes: list[int]) -> int:
    if not indexes:
        print("Nothing to verify. Press F2 to create a workspace.")
        return 1
    source = config.source_path
    if source is None or not source.is_file():
        print("No consolidated source. Set paths.source in cvgen.toml.")
        return 1
    paths = [rows[index].markdown for index in indexes]
    text = source.read_text(encoding="utf-8")
    ok, report = verify_paths(paths, text, config)
    print(report)
    return 0 if ok else 1


def perform_tailor(screen: Screen, *, dry_run: bool) -> int:
    if not screen.rows:
        print("Create a workspace with F2 before tailoring.")
        return 1
    row = screen.rows[screen.selected]
    job = screen.job.strip()
    if not job:
        print("Type a job file or URL first.")
        return 1
    return run_tailor(
        screen.config,
        job=job,
        lang=row.lang,
        length=row.length,
        provider_flag=None,
        model_flag=None,
        slug=None,
        base_url_flag=None,
        dry_run=dry_run,
        generate=not dry_run,
        source_path=None,
        template_path=row.markdown,
    )


def _put(window: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    height, width = window.getmaxyx()
    if y < 0 or y >= height or x >= width or not text:
        return
    clipped = text[: max(0, width - x - 1)]
    if not clipped:
        return
    try:
        window.addstr(y, x, clipped, attr)
    except curses.error:
        return


def _fill(window: curses.window, y: int, attr: int) -> None:
    _, width = window.getmaxyx()
    _put(window, y, 0, " " * (width - 1), attr)


def _commands(window: curses.window, y: int, commands: tuple[tuple[str, str], ...]) -> None:
    _, width = window.getmaxyx()
    key_attr = curses.color_pair(5) | curses.A_BOLD
    label_attr = curses.color_pair(6)
    x = 0
    for key, label in commands:
        key_text = f" {key} "
        label_text = f" {label} "
        if x + len(key_text) + len(label_text) >= width:
            break
        _put(window, y, x, key_text, key_attr)
        x += len(key_text)
        _put(window, y, x, label_text, label_attr)
        x += len(label_text)
    if x < width - 1:
        _put(window, y, x, " " * (width - x - 1), label_attr)


def _paint(window: curses.window, screen: Screen) -> None:
    window.erase()
    height, width = window.getmaxyx()
    if height < 12 or width < 40:
        _put(window, 0, 0, "Resize the terminal (at least 40x12).", curses.color_pair(4))
        _commands(window, height - 1, (("F10", "Quit"),))
        return

    title_attr = curses.color_pair(1) | curses.A_BOLD
    person = screen.config.person_name or "no workspace"
    _fill(window, 0, curses.color_pair(1))
    _put(window, 0, 1, f"cvgen {__version__}", title_attr)
    _put(window, 0, max(1, width - len(person) - 2), person, title_attr)

    ratio, fullest = busiest(screen.rows)
    _put(window, 1, 1, f"Pages {bar(ratio, 16)}  {fullest}", curses.color_pair(1))
    pdf_label = "LibreOffice ready" if screen.soffice else "DOCX only, no LibreOffice"
    source = screen.config.source_path
    if source is not None and source.is_file():
        source_label = display_path(source, screen.root)
    elif source is not None:
        source_label = f"missing {display_path(source, screen.root)}"
    else:
        source_label = "source not set"
    _put(window, 2, 1, f"{pdf_label}    {provider_label(screen.config)}    {source_label}", curses.color_pair(1))

    log_top = height - 5
    list_height = max(1, log_top - 5)
    if screen.mode == "help":
        for offset, line in enumerate(HELP_TEXT):
            if 4 + offset >= log_top - 1:
                break
            _put(window, 4 + offset, 1, line, curses.color_pair(1))
    else:
        _fill(window, 4, curses.color_pair(9))
        _put(window, 4, 0, header_labels(), curses.color_pair(9) | curses.A_BOLD)
    start = 0
    if len(screen.rows) > list_height:
        start = min(screen.selected, len(screen.rows) - list_height)
        start = max(0, start)
    if screen.mode != "help" and not screen.rows:
        _put(window, 5, 1, "No variants yet. F2 creates the fictional example.", curses.color_pair(4))
    elif screen.mode != "help":
        for offset, row in enumerate(screen.rows[start : start + list_height]):
            index = start + offset
            line = table_line(row, index == screen.selected)
            if index == screen.selected:
                _fill(window, 5 + offset, curses.color_pair(2))
                _put(window, 5 + offset, 0, line, curses.color_pair(2) | curses.A_BOLD)
                continue
            attr = curses.A_NORMAL
            if (row.pages is not None and row.pages > row.limit) or not row.markdown_ok:
                attr = curses.color_pair(4)
            _put(window, 5 + offset, 0, line, attr)

    _put(window, log_top - 1, 1, "log", curses.color_pair(1) | curses.A_DIM)
    visible_log = screen.log[-3:]
    for offset in range(3):
        text = visible_log[offset] if offset < len(visible_log) else ""
        _put(window, log_top + offset, 1, text, curses.A_NORMAL)

    hint = screen.status or _hint(screen)
    _put(window, height - 2, 1, hint, curses.color_pair(1))
    _commands(window, height - 1, _keys(screen.mode))


def _hint(screen: Screen) -> str:
    if screen.mode == "help":
        return "Esc closes help"
    if screen.mode == "job":
        shown = screen.job or ""
        return f"job: {shown}▏"
    return BROWSE_HINT


def _keys(mode: str) -> tuple[tuple[str, str], ...]:
    if mode == "help":
        return HELP_KEYS
    if mode == "job":
        return JOB_KEYS
    return BROWSE_KEYS


def _remember(screen: Screen, code: int, text: str) -> None:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        lines = ["Done." if code == 0 else f"Finished with status {code}."]
    screen.log = lines
    screen.status = ""


def _reload(screen: Screen, config_path: Path | None) -> None:
    fresh = load_screen(config_path, screen.root)
    screen.config = fresh.config
    screen.root = fresh.config.root
    screen.rows = fresh.rows
    screen.soffice = fresh.soffice
    screen.clamp()


def _run(screen: Screen, config_path: Path | None, action: Callable[[], int], config_after: Path | None = None) -> Path | None:
    previous = Path.cwd()
    try:
        os.chdir(screen.root)
        code, text = capture(action)
    finally:
        os.chdir(previous)
    _remember(screen, code, text)
    if config_after is not None and code == 0 and config_after.is_file():
        config_path = config_after
    _reload(screen, config_path)
    return config_path


def _selected_indexes(screen: Screen, all_rows: bool) -> list[int]:
    if not screen.rows:
        return []
    if all_rows:
        return list(range(len(screen.rows)))
    return [screen.selected]


def _job_suggestions(screen: Screen) -> list[str]:
    directory = screen.root / "jobs"
    if not directory.is_dir():
        return []
    found = sorted(path for path in directory.iterdir() if path.is_file())
    return [display_path(path, screen.root) for path in found[:6]]


def _on_browse(screen: Screen, key: int, config_path: Path | None) -> tuple[Path | None, bool]:
    """Handle a browse-mode key. The bool is True when the user quits."""
    if key in (curses.KEY_UP, ord("k")):
        screen.selected -= 1
        screen.clamp()
        return config_path, False
    if key in (curses.KEY_DOWN, ord("j")):
        screen.selected += 1
        screen.clamp()
        return config_path, False
    if key in (curses.KEY_F1, ord("?")):
        screen.mode = "help"
        return config_path, False
    if key == curses.KEY_F2:
        screen.status = "Creating the example workspace…"
        config_path = _run(screen, config_path, lambda: perform_init(screen.root), screen.root / "cvgen.toml")
        return config_path, False
    if key in (curses.KEY_F5, ord("b"), curses.KEY_ENTER, 10, 13):
        indexes = _selected_indexes(screen, False)
        label = screen.rows[indexes[0]].id if indexes else "CV"
        screen.status = f"Building {label}…"
        config_path = _run(screen, config_path, lambda: perform_build(screen.config, screen.rows, indexes))
        return config_path, False
    if key == ord("B"):
        screen.status = "Building every variant…"
        indexes = _selected_indexes(screen, True)
        config_path = _run(screen, config_path, lambda: perform_build(screen.config, screen.rows, indexes))
        return config_path, False
    if key in (curses.KEY_F6, ord("v")):
        indexes = _selected_indexes(screen, False)
        screen.status = "Verifying…"
        config_path = _run(screen, config_path, lambda: perform_verify(screen.config, screen.rows, indexes))
        return config_path, False
    if key == ord("V"):
        screen.status = "Verifying every variant…"
        indexes = _selected_indexes(screen, True)
        config_path = _run(screen, config_path, lambda: perform_verify(screen.config, screen.rows, indexes))
        return config_path, False
    if key in (curses.KEY_F7, ord("t")):
        if not screen.rows:
            screen.log = ["Create a workspace with F2 before tailoring."]
            return config_path, False
        screen.mode = "job"
        screen.job = ""
        suggestions = _job_suggestions(screen)
        screen.log = ["Type a job file or URL."] + [f"  {name}" for name in suggestions]
        return config_path, False
    if key == ord("r"):
        _reload(screen, config_path)
        screen.log = ["Refreshed."]
        return config_path, False
    if key in (curses.KEY_F10, ord("q")):
        return config_path, True
    return config_path, False


def _on_job(screen: Screen, key: int, config_path: Path | None) -> tuple[Path | None, bool]:
    if key in (27,):
        screen.mode = "browse"
        screen.status = ""
        return config_path, False
    if key in (curses.KEY_F10,):
        return config_path, True
    if key in (curses.KEY_BACKSPACE, 127, 8):
        screen.job = screen.job[:-1]
        return config_path, False
    if key in (curses.KEY_ENTER, 10, 13, curses.KEY_F5):
        if not screen.job.strip():
            screen.log = ["Type a job file or URL, or press Esc to cancel."]
            return config_path, False
        dry_run = key != curses.KEY_F5
        screen.mode = "browse"
        row = screen.rows[screen.selected]
        screen.status = "Writing the tailor prompt…" if dry_run else f"Tailoring {row.id}…"
        config_path = _run(screen, config_path, lambda: perform_tailor(screen, dry_run=dry_run))
        return config_path, False
    if 32 <= key <= 126:
        screen.job += chr(key)
    return config_path, False


def run(window: curses.window, config_path: Path | None) -> int:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    window.keypad(True)
    curses.noecho()
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(4, curses.COLOR_RED, -1)
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)
            curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_GREEN)
    except curses.error:
        pass
    screen = load_screen(config_path)
    while True:
        screen.status = ""
        _paint(window, screen)
        window.refresh()
        key = window.getch()
        if key == curses.KEY_RESIZE:
            continue
        if screen.mode == "help":
            if key in (27, curses.KEY_F1, ord("?")):
                screen.mode = "browse"
            elif key in (curses.KEY_F10, ord("q")):
                return 0
            continue
        if screen.mode == "job":
            config_path, quit_now = _on_job(screen, key, config_path)
        else:
            # Paint the working status before a command that may take a while.
            if key in (curses.KEY_F2, curses.KEY_F5, ord("b"), ord("B"), curses.KEY_F6, ord("v"), ord("V"), 10, 13, curses.KEY_ENTER):
                screen.status = "Working…"
                _paint(window, screen)
                window.refresh()
            config_path, quit_now = _on_browse(screen, key, config_path)
        if quit_now:
            return 0


def launch(config_path: Path | None = None) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("The interactive screen needs a terminal. Run cvgen --help for the commands.", file=sys.stderr)
        return 2
    try:
        return curses.wrapper(lambda window: run(window, config_path))
    except curses.error as exc:
        print(f"Could not open the interactive screen: {exc}", file=sys.stderr)
        return 2
