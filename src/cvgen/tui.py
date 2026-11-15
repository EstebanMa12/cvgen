"""Workspace actions shared by the interactive screen and the shell commands."""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from cvgen.build import BuildJob, build_one, soffice_available
from cvgen.config import Config, ConfigError, load_workspace
from cvgen.onboard import Wizard
from cvgen.pdf import count_pdf_pages
from cvgen.providers.base import DEFAULT_MODELS, ProviderError, canonicalize
from cvgen.scaffold import init_workspace
from cvgen.tailor import run_tailor
from cvgen.verify import verify_paths


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
    wizard: Wizard = field(default_factory=Wizard)
    help_from: str = "browse"

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
        screen.mode = "onboard"
        screen.log = ["Enter walks through the folders. F10 quits."]
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


def meter_line(row: VariantRow, selected: bool) -> str:
    """Shorter row for the dashboard panel."""
    marker = ">" if selected else " "
    meter = bar(page_ratio(row.pages, row.limit), 8)
    pages = format_pages(row.pages, row.limit)
    return f"{marker} {row.id:<16} {row.lang:<3} {meter} {pages:>4}"


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



def launch(config_path: Path | None = None) -> int:
    """Open the interactive screen, or explain why it cannot start."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "The interactive screen needs a terminal. Run cvgen --help for the commands.",
            file=sys.stderr,
        )
        return 2
    try:
        from cvgen.ui.app import run_app
    except ImportError:
        print(
            "The interactive screen needs Textual. Install it with: pip install 'cvgen[ui]'",
            file=sys.stderr,
        )
        return 2
    return run_app(config_path)
