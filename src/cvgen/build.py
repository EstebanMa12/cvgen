"""Markdown to DOCX, with optional PDF export and page-limit enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cvgen.config import Config, ConfigError
from cvgen.docx_io import build_document
from cvgen.layout import STYLES, FitResult, fit_style
from cvgen.markdown import parse_markdown_file
from cvgen.pdf import PdfExportError, count_pdf_pages, export_pdf, find_soffice
from cvgen.util import display_path


@dataclass
class BuildJob:
    markdown: Path
    docx: Path
    length: str


def infer_length(path: Path) -> str:
    name = path.name.lower()
    if "short" in name or "corta" in name:
        return "short"
    return "extended"


def build_one(
    job: BuildJob,
    config: Config,
    *,
    make_pdf: bool,
    autofit: bool,
) -> bool:
    """Render one CV. Return False when the page limit is missed or PDF export fails."""
    model = parse_markdown_file(job.markdown)
    if job.length not in STYLES:
        raise ConfigError(f"Unknown length {job.length!r}. Expected 'short' or 'extended'.")
    style = dict(STYLES[job.length])
    limit = config.page_limits[job.length]
    root = config.root

    def measure(current: dict[str, float]) -> int:
        build_document(
            model,
            current,
            job.docx,
            font=config.font,
            locale_es=config.locale_es,
            locale_en=config.locale_en,
        )
        pdf_path = export_pdf(job.docx)
        return count_pdf_pages(pdf_path)

    try:
        if not make_pdf:
            build_document(
                model,
                style,
                job.docx,
                font=config.font,
                locale_es=config.locale_es,
                locale_en=config.locale_en,
            )
            print(f"Generated: {display_path(job.docx, root)}")
            return True
        if autofit:
            result = fit_style(style, job.length, measure, limit=limit)
        else:
            pages = measure(style)
            result = FitResult(style=style, pages=pages, steps=0, ok=pages <= limit)
    except PdfExportError as exc:
        print(f"  PDF ERROR: {exc}")
        return False

    print(f"Generated: {display_path(job.docx, root)}")
    fit_note = ""
    if result.steps:
        fit_note = f" [auto-fit: {result.steps} step(s), body {result.style['body_size']} pt]"
    pdf_display = display_path(job.docx.with_suffix(".pdf"), root)
    if not result.ok:
        print(
            f"  PAGE CHECK FAIL: {pdf_display} has {result.pages} pages "
            f"(max {limit} for {job.length}){fit_note} — trim the Markdown."
        )
        return False
    note = "" if result.pages == limit else f" (under the {limit}-page limit)"
    print(f"  PDF: {pdf_display} — {result.pages} page(s), limit {limit}: OK{note}{fit_note}")
    return True


def resolve_jobs(variants: list[str], explicit_input: Path | None, explicit_output: Path | None, length: str | None, config: Config) -> list[BuildJob]:
    if explicit_input is not None:
        if variants:
            raise ConfigError("Pass variant ids or --input, not both.")
        markdown = explicit_input if explicit_input.is_absolute() else Path.cwd() / explicit_input
        if not markdown.is_file():
            raise ConfigError(f"Input not found: {markdown}")
        if explicit_output is not None:
            docx = explicit_output if explicit_output.is_absolute() else Path.cwd() / explicit_output
        elif config.config_path is None:
            docx = markdown.with_suffix(".docx")
        else:
            docx = config.output_dir / f"{markdown.stem}.docx"
        return [BuildJob(markdown, docx, length or infer_length(markdown))]

    if not config.variants:
        raise ConfigError("No variants in cvgen.toml. Run `cvgen init` or pass --input.")
    known = {variant.id: variant for variant in config.variants}
    selected = variants or list(known)
    jobs: list[BuildJob] = []
    for key in selected:
        if key not in known:
            raise ConfigError(f"Unknown variant {key!r}. Valid options: {', '.join(known)}.")
        variant = known[key]
        if not variant.input_path.is_file():
            raise ConfigError(f"Input not found: {variant.input_path}")
        jobs.append(
            BuildJob(
                variant.input_path,
                config.output_dir / variant.output_name,
                length or variant.length,
            )
        )
    return jobs


def soffice_available() -> bool:
    return find_soffice() is not None
