"""Command line interface for cvgen."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cvgen import __version__
from cvgen.build import build_one, resolve_jobs, soffice_available
from cvgen.config import ConfigError, load_workspace
from cvgen.providers.base import ProviderError
from cvgen.scaffold import init_workspace
from cvgen.tailor import run_tailor
from cvgen.tui import launch
from cvgen.util import display_path
from cvgen.verify import verify_paths


def _pull_config(argv: list[str]) -> tuple[Path | None, list[str]]:
    kept: list[str] = []
    value: str | None = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--config":
            if index + 1 >= len(argv):
                raise ConfigError("--config needs a path.")
            value = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            value = arg.split("=", 1)[1]
            index += 1
            continue
        kept.append(arg)
        index += 1
    return (Path(value) if value else None), kept


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cvgen",
        description="Build, verify and tailor CVs from Markdown. Facts come from a source file you control.",
        epilog=(
            "cvgen.toml is discovered from the current directory upward.\n"
            "Pass --config PATH before or after the subcommand to use another file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ui", help="open the interactive screen (also the default in a terminal)")

    init = sub.add_parser("init", help="create a workspace with a fictional example")
    init.add_argument("--dir", type=Path, default=Path("."), help="directory to create (default: .)")
    init.add_argument("--force", action="store_true", help="overwrite scaffold files that already exist")

    build = sub.add_parser("build", help="render Markdown to DOCX and, when LibreOffice is installed, PDF")
    build.add_argument("variants", nargs="*", help="variant ids from cvgen.toml (default: all)")
    build.add_argument("--input", "-i", type=Path, help="one Markdown CV instead of the configured variants")
    build.add_argument("--output", "-o", type=Path, help="DOCX path used with --input")
    build.add_argument("--length", choices=("short", "extended"), help="page profile (default: from the variant or the file name)")
    build.add_argument("--no-pdf", action="store_true", help="write the DOCX only")
    build.add_argument("--require-pdf", action="store_true", help="fail if LibreOffice is not installed")
    build.add_argument("--no-autofit", action="store_true", help="do not shrink fonts to meet the page limit")

    verify = sub.add_parser("verify", help="fact-check CVs against the consolidated source")
    verify.add_argument("files", nargs="*", type=Path, help="Markdown or DOCX files (default: the configured variants)")
    verify.add_argument("--source", type=Path, help="consolidated source of truth")
    verify.add_argument("--require", action="append", default=[], help="extra required phrase (repeatable)")

    tailor = sub.add_parser("tailor", help="rewrite a CV for a job using only facts from the source")
    tailor.add_argument("--job", required=True, help="job posting text file, or an http(s) URL")
    tailor.add_argument("--lang", choices=("es", "en"), default="es")
    tailor.add_argument("--length", choices=("short", "extended"), default="short")
    tailor.add_argument("--provider", help="openai, anthropic, gemini, cursor, ollama, or openai-compatible")
    tailor.add_argument("--model", help="model id for the selected provider")
    tailor.add_argument("--slug", help="file name stem for the tailored CV")
    tailor.add_argument("--base-url", help="base URL for ollama or an OpenAI-compatible server")
    tailor.add_argument("--dry-run", action="store_true", help="write the prompt and do not call a provider")
    tailor.add_argument("--no-generate", action="store_true", help="write Markdown and the match report, then stop")
    tailor.add_argument("--source", type=Path, help="consolidated source (default: paths.source)")
    tailor.add_argument("--template", type=Path, help="base CV to adapt (default: the matching variant)")
    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    written = init_workspace(args.dir, force=args.force)
    print(f"Initialized a cvgen workspace in {args.dir.resolve()}")
    for path in written:
        print(f"  {display_path(path, args.dir.resolve())}")
    print("\nNext:")
    print("  cvgen build")
    print("  cvgen verify")
    print("  cvgen tailor --job jobs/lumenfield-backend.txt --lang en --length short --dry-run")
    return 0


def _cmd_build(args: argparse.Namespace, config_path: Path | None) -> int:
    if args.no_pdf and args.require_pdf:
        raise ConfigError("Pass either --no-pdf or --require-pdf, not both.")
    config = load_workspace(config_path)
    jobs = resolve_jobs(args.variants, args.input, args.output, args.length, config)
    make_pdf = not args.no_pdf
    if make_pdf and not soffice_available():
        print(
            "WARNING: LibreOffice (soffice) was not found. "
            "DOCX files will still be written. Install libreoffice-writer to export PDF."
        )
        if args.require_pdf:
            return 3
        make_pdf = False
    ok = True
    for job in jobs:
        ok = build_one(job, config, make_pdf=make_pdf, autofit=not args.no_autofit) and ok
    if not ok:
        print("\nSome page or PDF checks FAILED.")
        return 1
    suffix = " Page checks passed." if make_pdf else ""
    print(f"\nAll documents generated.{suffix}")
    return 0


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _cmd_verify(args: argparse.Namespace, config_path: Path | None) -> int:
    config = load_workspace(config_path)
    source = _resolve(args.source) if args.source else config.source_path
    if source is None:
        raise ConfigError("Pass --source or set paths.source in cvgen.toml.")
    if not source.is_file():
        raise ConfigError(f"Source not found: {source}")
    if args.files:
        paths = [_resolve(path) for path in args.files]
    elif config.variants:
        paths = [variant.input_path for variant in config.variants]
    else:
        raise ConfigError("Pass CV files to verify, or define variants in cvgen.toml.")
    ok, report = verify_paths(paths, source.read_text(encoding="utf-8"), config, extra_required=args.require)
    print(report)
    return 0 if ok else 1


def _cmd_tailor(args: argparse.Namespace, config_path: Path | None) -> int:
    config = load_workspace(config_path)
    return run_tailor(
        config,
        job=args.job,
        lang=args.lang,
        length=args.length,
        provider_flag=args.provider,
        model_flag=args.model,
        slug=args.slug,
        base_url_flag=args.base_url,
        dry_run=args.dry_run,
        generate=not args.no_generate,
        source_path=args.source,
        template_path=args.template,
    )


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--version" in raw:
        print(f"cvgen {__version__}")
        return 0
    try:
        config_path, raw = _pull_config(raw)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(raw)
    if args.version:
        print(f"cvgen {__version__}")
        return 0
    if args.command == "ui" or (not args.command and _terminal()):
        return launch(config_path)
    if not args.command:
        parser.print_help()
        return 2
    try:
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "build":
            return _cmd_build(args, config_path)
        if args.command == "verify":
            return _cmd_verify(args, config_path)
        if args.command == "tailor":
            return _cmd_tailor(args, config_path)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ProviderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.code
    print(f"ERROR: unknown command {args.command!r}", file=sys.stderr)
    return 2


def _terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def app() -> None:
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
