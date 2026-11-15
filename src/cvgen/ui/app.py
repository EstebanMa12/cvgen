"""Interactive cvgen screen.

The start screen is a centered menu with a prompt. The dashboard lists base
CVs with absolute paths, and tailor is a short labeled form.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from typing import get_args

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Provider
from textual.containers import Grid, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Label,
    LoadingIndicator,
    Markdown,
    OptionList,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
    Switch,
)
from textual.widgets.option_list import Option

from cvgen import __version__
from cvgen.config import ConfigError
from cvgen.jobs import chosen_job, plain_job_error
from cvgen.onboard import (
    Wizard,
    create,
    folder_error,
    handle,
    name_error,
    screen_lines,
)
from cvgen.providers.base import ProviderName
from cvgen.tailor import run_tailor
from cvgen.util import CYAN, GREEN, ORANGE, PINK, YELLOW, friendly_path, tint
from cvgen.tui import (
    base_cv_details,
    base_cv_lines,
    collect_rows,
    load_screen,
    perform_build,
    perform_verify,
)
from cvgen.ui.commands import (
    MENU,
    MenuItem,
    TailoredItem,
    format_tailored,
    list_tailored,
    matching_commands,
    parse_prompt,
    shortcut_for,
    ui_key_overrides,
)
from cvgen.ui.logo import LOGO
from cvgen.variants import add_base_cv

_PROVIDERS = [(name, name) for name in get_args(ProviderName)]
_PROGRESS = ("Reading job", "Asking AI", "Verifying facts", "Building PDF")
_STAGE_INDEX = {
    "Reading the job": 0,
    "Asking the model": 1,
    "Writing the prompt": 1,
    "Checking the facts": 2,
    "Building the document": 3,
}


def progress_text(stage: str, *, preview: bool) -> str:
    """Labeled tailor steps. The current step is marked with >."""
    index = _STAGE_INDEX.get(stage, 0)
    if preview:
        labels = ("Reading job", "Writing the prompt")
        index = min(index, 1)
    else:
        labels = _PROGRESS
    lines: list[str] = []
    for position, label in enumerate(labels):
        if position < index:
            lines.append(f"  {label}  done")
        elif position == index:
            lines.append(f"> {label}")
        else:
            lines.append(f"  {label}")
    return "\n".join(lines)


def open_path(path: Path) -> str | None:
    """Open a file with the desktop handler. Returns an error string, or None."""
    if not path.is_file():
        return f"Not created yet: {path}"
    try:
        subprocess.Popen(
            ["xdg-open", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return f"Could not open {path}: {exc}"
    return None


class CvgenCommands(Provider):
    """Slash-command palette opened with ctrl+p."""

    async def discover(self):
        for item in MENU:
            yield DiscoveryHit(item.title, self._run(item), help=item.help, text=item.title)

    async def search(self, query: str):
        matcher = self.matcher(query)
        for item in MENU:
            score = matcher.match(item.title)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(item.title),
                    self._run(item),
                    help=item.help,
                    text=item.title,
                )

    def _run(self, item: MenuItem):
        def command() -> None:
            self.app.dispatch(item.action)

        return command


class ResultModal(ModalScreen[int]):
    """Scrollable log for build and verify. Lines arrive while the work runs."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, title: str, work) -> None:
        super().__init__()
        self.heading = title
        self.work = work

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.heading, id="dialog-title")
            yield RichLog(id="log", highlight=False, markup=False)
            yield Label("esc close", id="dialog-hint")

    def on_mount(self) -> None:
        self._log = self.query_one(RichLog)
        self._log.write("Working…")
        self._lines: list[str] = []
        self.run_worker(self._go, thread=True, exclusive=True)

    def _go(self) -> int:
        def push(line: str) -> None:
            self._lines.append(line)
            self.app.call_from_thread(self._log.write, line)

        try:
            stream = _LineStream(push)
            with _redirect(stream):
                code = int(self.work())
        except Exception as exc:
            push(str(exc))
            code = 1
        self.app.call_from_thread(self._done, code)
        return code

    def _done(self, code: int) -> None:
        self.app.last_output = "\n".join(self._lines)
        self.dismiss(code == 0)
        severity = "information" if code == 0 else "error"
        self.app.notify(self.heading if code == 0 else f"{self.heading} failed", severity=severity)


class TailorModal(ModalScreen[None]):
    """Labeled form: which job, language, length, then Generate CV."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, preset: str = "") -> None:
        super().__init__()
        self.preset = preset
        self._jobs: list[Path] = []
        self._args: dict[str, str | bool] = {}
        self._lines: list[str] = []
        self._item: TailoredItem | None = None
        self._prompt_path: Path | None = None
        self._copy_target: Path | None = None

    def compose(self) -> ComposeResult:
        app: CvgenApp = self.app
        directory = app.model.root / "jobs"
        if directory.is_dir():
            self._jobs = sorted(
                path for path in directory.iterdir() if path.is_file() and not path.name.startswith(".")
            )
        with Vertical(id="dialog", classes="tailor-dialog"):
            with Vertical(id="form"):
                with Vertical(id="fields"):
                    yield Label("Tailor to a job", id="dialog-title")
                    yield Label("1. Which job?", classes="step-label")
                    yield Static(
                        "Pick a saved posting, or paste a URL or the posting text.",
                        id="job-help",
                    )
                    yield OptionList(id="jobs")
                    yield Static("Pick a saved job, or paste a URL or the posting text.", id="using")
                    yield Input(
                        value=self.preset,
                        placeholder="Paste a URL or the posting text",
                        id="job-path",
                    )
                    yield Label("2. Language", classes="step-label")
                    with RadioSet(id="lang"):
                        yield RadioButton("Spanish", id="lang-es", value=True)
                        yield RadioButton("English", id="lang-en")
                    yield Label("Length", classes="step-label")
                    with RadioSet(id="length"):
                        yield RadioButton("Short (1 page)", id="len-short", value=True)
                        yield RadioButton("Extended (2 pages)", id="len-extended")
                    with Collapsible(title="Advanced", collapsed=True, id="advanced"):
                        yield Label("Provider")
                        yield Select(_PROVIDERS, value="openai", id="provider", allow_blank=False)
                        yield Input(placeholder="Model (empty uses the provider default)", id="model")
                        with Horizontal(classes="row"):
                            yield Switch(value=False, id="preview")
                            yield Label("Preview prompt only (don't call AI)")
                with Horizontal(id="actions"):
                    yield Button("Generate CV", id="generate", variant="primary")
                    yield Button("Cancel", id="cancel")
            with Vertical(id="progress", classes="hidden"):
                yield LoadingIndicator(id="spinner")
                yield Static(progress_text("Reading the job", preview=False), id="stage-list")
            with Vertical(id="result", classes="hidden"):
                yield Label("Tailored CV", id="result-title")
                yield Static("", id="summary")
                with Horizontal():
                    yield Button("Open PDF", id="open-pdf", variant="primary")
                    yield Button("Open report", id="open-report")
                    yield Button("Copy path", id="copy-path")
                    yield Button("Close", id="close-result")
            with Vertical(id="error-box", classes="hidden"):
                yield Label("Could not tailor the CV", id="error-title")
                yield Static("", id="error-text")
                yield RichLog(id="log", highlight=False, markup=False, wrap=True)
                yield Button("Close", id="close-error")

    def on_mount(self) -> None:
        listing = self.query_one("#jobs", OptionList)
        for path in self._jobs:
            listing.add_option(Option(path.name, id=str(path.resolve())))
        self._refresh_using()
        if self.preset.strip():
            self.notify("Check language and length, then press Generate CV.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button in {"cancel", "close-result", "close-error"}:
            self.dismiss(None)
        elif button == "generate":
            self._start()
        elif button == "open-pdf":
            self._open(self._item.pdf if self._item else None)
        elif button == "open-report":
            target = self._item.report if self._item else self._prompt_path
            self._open(target)
        elif button == "copy-path":
            self._copy()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "job-path":
            self._refresh_using()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "job-path":
            event.stop()
            self._start()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "jobs":
            return
        if event.option_index >= len(self._jobs):
            return
        path = self._jobs[event.option_index]
        self.query_one("#job-path", Input).value = f"jobs/{path.name}"
        self._refresh_using()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "jobs":
            self._refresh_using()

    def _highlighted_path(self) -> Path | None:
        listing = self.query_one("#jobs", OptionList)
        if listing.highlighted is None or not self._jobs:
            return None
        if listing.highlighted >= len(self._jobs):
            return None
        return self._jobs[listing.highlighted]

    def _job_text(self) -> str:
        typed = self.query_one("#job-path", Input).value
        return chosen_job(typed, self._highlighted_path())

    def _refresh_using(self) -> None:
        typed = self.query_one("#job-path", Input).value.strip()
        label = self.query_one("#using", Static)
        if typed:
            shown = typed if len(typed) < 72 else typed[:69] + "..."
            label.update(f"Using what you typed: {shown}")
            return
        path = self._highlighted_path()
        if path is None:
            label.update("Pick a saved job, or paste a URL or the posting text.")
            return
        label.update(f"Using jobs/{path.name}")

    def _lang(self) -> str:
        button = self.query_one("#lang", RadioSet).pressed_button
        if button is not None and button.id == "lang-en":
            return "en"
        return "es"

    def _length(self) -> str:
        button = self.query_one("#length", RadioSet).pressed_button
        if button is not None and button.id == "len-extended":
            return "extended"
        return "short"

    def _start(self) -> None:
        job = self._job_text()
        if not job:
            self.app.notify("Pick a saved job, or paste a URL or the posting text.", severity="warning")
            return
        preview = bool(self.query_one("#preview", Switch).value)
        self._args = {
            "job": job,
            "lang": self._lang(),
            "length": self._length(),
            "provider": str(self.query_one("#provider", Select).value),
            "model": self.query_one("#model", Input).value.strip(),
            "preview": preview,
        }
        self.query_one("#form").add_class("hidden")
        self.query_one("#result").add_class("hidden")
        self.query_one("#error-box").add_class("hidden")
        stage = self.query_one("#stage-list", Static)
        stage.update(progress_text("Reading the job", preview=preview))
        self.query_one("#progress").remove_class("hidden")
        self._lines = []
        self.run_worker(self._go, thread=True, exclusive=True)

    def _go(self) -> int:
        args = self._args
        app: CvgenApp = self.app

        def push(line: str) -> None:
            self._lines.append(line)

        def stage(message: str) -> None:
            preview = bool(args["preview"])
            self.app.call_from_thread(self._set_stage, message, preview)

        try:
            stream = _LineStream(push)
            with _redirect(stream):
                code = run_tailor(
                    app.model.config,
                    job=str(args["job"]),
                    lang=str(args["lang"]),
                    length=str(args["length"]),
                    provider_flag=str(args["provider"]),
                    model_flag=str(args["model"]) or None,
                    slug=None,
                    base_url_flag=None,
                    dry_run=bool(args["preview"]),
                    generate=not bool(args["preview"]),
                    source_path=None,
                    template_path=None,
                    on_stage=stage,
                )
        except Exception as exc:
            push(str(exc))
            code = 1
        self.app.call_from_thread(self._finish, code)
        return code

    def _set_stage(self, message: str, preview: bool) -> None:
        self.query_one("#stage-list", Static).update(progress_text(message, preview=preview))

    def _finish(self, code: int) -> None:
        app: CvgenApp = self.app
        app.reload()
        self.query_one("#progress").add_class("hidden")
        if code != 0:
            self._show_error()
            return
        self._show_success()

    def _show_error(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        for line in self._lines:
            log.write(line)
        raw = "\n".join(self._lines)
        self.query_one("#error-text", Static).update(plain_job_error(raw))
        self.query_one("#error-box").remove_class("hidden")
        self.app.notify("Tailor failed", severity="error")

    def _show_success(self) -> None:
        app: CvgenApp = self.app
        items = list_tailored(app.model.config)
        self._item = items[-1] if items and not self._args["preview"] else None
        prompts = sorted(app.model.config.tailored_dir.glob("*.prompt.md"), key=lambda path: path.stat().st_mtime)
        self._prompt_path = prompts[-1].resolve() if prompts else None
        if self._args["preview"]:
            where = self._prompt_path or app.model.config.tailored_dir
            self._copy_target = self._prompt_path
            shown = friendly_path(where) if isinstance(where, Path) else str(where)
            summary = (
                "Preview only. No AI was called.\n\n"
                f"Prompt\n{shown}\n\n"
                "The file is under out/tailored/. "
                "Turn off preview under Advanced, then press Generate CV to call the model."
            )
        elif self._item is not None:
            self._copy_target = self._item.pdf
            percent = self._item.percent
            if percent >= 70:
                score_color = GREEN
            elif percent >= 40:
                score_color = YELLOW
            else:
                score_color = ORANGE
            summary = (
                f"{tint(f'{percent}% match', score_color)}\n"
                f"{tint(f'Met {self._item.met}', GREEN)}    "
                f"{tint(f'Partial {self._item.partial}', YELLOW)}    "
                f"{tint(f'Missing {self._item.missing}', PINK)}\n\n"
                f"PDF\n{friendly_path(self._item.pdf)}\n\n"
                f"DOCX\n{friendly_path(self._item.docx)}\n\n"
                f"Report\n{friendly_path(self._item.report)}\n\n"
                "Saved under out/tailored/."
            )
        else:
            self._copy_target = None
            summary = "The tailor step finished, but no match report was written."
        self.query_one("#summary", Static).update(summary)
        self.query_one("#result").remove_class("hidden")
        self.app.notify("Tailored CV is ready", severity="information")

    def _open(self, path: Path | None) -> None:
        if path is None:
            self.app.notify("That file was not written.", severity="warning")
            return
        problem = open_path(path)
        if problem:
            self.app.notify(problem, severity="warning")

    def _copy(self) -> None:
        if self._copy_target is None:
            self.app.notify("Nothing to copy yet.", severity="warning")
            return
        text = str(self._copy_target)
        self.app.copy_to_clipboard(text)
        self.app.notify(f"Copied {text}")


class OnboardModal(ModalScreen[bool]):
    """Modal steps that create source/, cv/, jobs/, and out/."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self.wizard = Wizard()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("", id="body")
            yield Input(id="field")
            yield Static("", id="error")
            with Horizontal():
                yield Button("Example", id="example")
                yield Button("Blank", id="blank")
                yield Button("Back", id="back")
                yield Button("Next", id="next", variant="primary")

    def on_mount(self) -> None:
        self._show_step()

    def _show_step(self) -> None:
        app: CvgenApp = self.app
        lines = [text for _role, text in screen_lines(self.wizard, app.model.root)]
        self.query_one("#body", Static).update("\n".join(lines))
        field = self.query_one("#field", Input)
        kind_buttons = self.wizard.step == "kind"
        self.query_one("#example", Button).display = kind_buttons
        self.query_one("#blank", Button).display = kind_buttons
        if self.wizard.step == "folder":
            field.display = True
            field.value = self.wizard.folder
            field.placeholder = "folder name, or empty for this directory"
            field.focus()
        elif self.wizard.step == "name":
            field.display = True
            field.value = self.wizard.name
            field.placeholder = "Name on the CV"
            field.focus()
        else:
            field.display = False
            self.query_one("#next", Button).focus()
        label = "Create" if self.wizard.step == "review" else "Next"
        self.query_one("#next", Button).label = label

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.action_back()
        elif event.button.id == "next":
            self.action_next()
        elif event.button.id == "example":
            self.wizard.kind = "example"
            self.action_next()
        elif event.button.id == "blank":
            self.wizard.kind = "blank"
            self.action_next()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_next()

    def action_back(self) -> None:
        if self.wizard.step == "welcome":
            self.dismiss(False)
            return
        handle(self.wizard, "back")
        self._show_step()

    def action_next(self) -> None:
        field = self.query_one("#field", Input)
        if self.wizard.step == "folder":
            self.wizard.folder = field.value
            problem = folder_error(self.wizard.folder)
            if problem:
                self.query_one("#error", Static).update(problem)
                return
        if self.wizard.step == "name":
            self.wizard.name = field.value
            problem = name_error(self.wizard.name)
            if problem:
                self.query_one("#error", Static).update(problem)
                return
        self.query_one("#error", Static).update("")
        outcome = handle(self.wizard, "next")
        if outcome != "create":
            self._show_step()
            return
        app: CvgenApp = self.app
        try:
            root = create(app.model.root, self.wizard)
        except (ConfigError, ValueError) as exc:
            self.query_one("#error", Static).update(str(exc))
            return
        app.config_path = root / "cvgen.toml"
        app.reload()
        self.dismiss(True)


class HelpModal(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("How to start", id="dialog-title")
            yield Static(
                "\n".join(
                    [
                        "Paste a job URL, a file path, or the posting text, then press Enter.",
                        "Pick Spanish or English, and Short (1 page) or Extended (2 pages).",
                        "Generate CV writes the PDF, DOCX, and match report under out/tailored/.",
                        "",
                        "  /build                 render every base CV",
                        "  /verify                fact-check every base CV",
                        "  /tailor jobs/role.txt  open tailor for that file",
                        "  /dashboard             base CVs, checks, matches",
                        "  /new                   create the folders",
                        "  /quit",
                        "",
                        "A base CV is one Markdown file, in one language and one length.",
                        "ctrl+p opens the command palette.",
                        "Shell: cvgen build, cvgen verify, cvgen tailor, cvgen variant add.",
                    ]
                )
            )
            yield Label("esc close", id="dialog-hint")


class WelcomeModal(ModalScreen[None]):
    """Shown once per workspace so the first screen is not a blank prompt."""

    BINDINGS = [Binding("escape", "close_intro", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Start here", id="dialog-title")
            yield Static(
                "\n".join(
                    [
                        "Paste a job link or the posting text in the prompt, then press Enter.",
                        "Choose Spanish or English, and Short (1 page) or Extended (2 pages).",
                        "Generate CV saves the PDF under out/tailored/ and shows the path.",
                        "",
                        "Base CVs are the Markdown files you start from, one language and one length.",
                        "The dashboard lists them, with the absolute path of each file.",
                    ]
                )
            )
            yield Button("Got it", id="got-it", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "got-it":
            self.action_close_intro()

    def action_close_intro(self) -> None:
        app: CvgenApp = self.app
        marker = app.model.root / "out" / ".cvgen-intro"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("seen\n", encoding="utf-8")
        self.dismiss(None)


class AddCvModal(ModalScreen[bool]):
    """Create one base CV: a Markdown file plus a cvgen.toml entry."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        app: CvgenApp = self.app
        options = [("Blank", "")]
        options.extend((row.id, row.id) for row in app.model.rows)
        with Vertical(id="dialog"):
            yield Label("New base CV", id="dialog-title")
            yield Static("A base CV is one Markdown file, in one language and one length.")
            yield Input(placeholder="Name, such as Short English", id="cv-name")
            yield Label("Language", classes="step-label")
            with RadioSet(id="cv-lang"):
                yield RadioButton("Spanish", id="cv-es", value=True)
                yield RadioButton("English", id="cv-en")
            yield Label("Length", classes="step-label")
            with RadioSet(id="cv-length"):
                yield RadioButton("Short (1 page)", id="cv-short", value=True)
                yield RadioButton("Extended (2 pages)", id="cv-extended")
            yield Label("Start from")
            yield Select(options, value="", id="cv-from", allow_blank=False)
            yield Static("", id="cv-error")
            with Horizontal():
                yield Button("Create", id="cv-create", variant="primary")
                yield Button("Cancel", id="cv-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cv-cancel":
            self.dismiss(False)
        elif event.button.id == "cv-create":
            self._create()

    def _create(self) -> None:
        app: CvgenApp = self.app
        name = self.query_one("#cv-name", Input).value.strip()
        lang_button = self.query_one("#cv-lang", RadioSet).pressed_button
        length_button = self.query_one("#cv-length", RadioSet).pressed_button
        lang = "en" if lang_button is not None and lang_button.id == "cv-en" else "es"
        length = "extended" if length_button is not None and length_button.id == "cv-extended" else "short"
        source = str(self.query_one("#cv-from", Select).value)
        try:
            add_base_cv(
                app.model.config,
                name=name,
                lang=lang,
                length=length,
                copy_from=source or None,
                blank=not source,
            )
        except (ConfigError, ValueError) as exc:
            self.query_one("#cv-error", Static).update(str(exc))
            return
        app.reload()
        self.dismiss(True)


class FileModal(ModalScreen[None]):
    """Show a tailored CV's match summary and the absolute paths."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, item: TailoredItem) -> None:
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        item = self.item
        body = "\n".join(
            [
                f"{item.percent}% match",
                f"Met {item.met}    Partial {item.partial}    Missing {item.missing}",
                "",
                "PDF",
                friendly_path(item.pdf),
                "DOCX",
                friendly_path(item.docx),
                "Report",
                friendly_path(item.report),
            ]
        )
        with Vertical(id="dialog"):
            yield Label(item.title, id="dialog-title")
            yield Static(body, id="file-body")
            with Horizontal():
                yield Button("Open PDF", id="file-pdf", variant="primary")
                yield Button("Open report", id="file-report")
                yield Button("Copy path", id="file-copy")
                yield Button("Close", id="file-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "file-close":
            self.dismiss(None)
        elif button == "file-pdf":
            self._open(self.item.pdf)
        elif button == "file-report":
            self._open(self.item.report)
        elif button == "file-copy":
            self.app.copy_to_clipboard(str(self.item.pdf))
            self.app.notify(f"Copied {self.item.pdf}")

    def _open(self, path: Path) -> None:
        problem = open_path(path)
        if problem:
            self.app.notify(problem, severity="warning")


class Dashboard(Screen[None]):
    """Base CVs, the file paths, and tailored match scores."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("tab", "switch_panel", "Switch", show=False),
        Binding("enter", "open_selected", "Open", show=False),
        Binding("b", "build_one", "Build", show=False),
        Binding("v", "verify_one", "Verify", show=False),
        Binding("t", "tailor", "Tailor", show=False),
        Binding("n", "new_cv", "New base CV", show=False),
        Binding("p", "open_pdf", "Open PDF", show=False),
        Binding("c", "copy_path", "Copy path", show=False),
        Binding("r", "reload_view", "Refresh", show=False),
        Binding("q", "app.quit", "Quit", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.index = 0
        self.tailor_index = 0
        self.focus_panel = "base"
        self._tailored: list[TailoredItem] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="insight")
        with Grid(id="dash"):
            with Vertical(id="variants", classes="panel"):
                yield Static("Base CVs", classes="panel-title")
                yield Static("", id="variants-body", classes="panel-body")
            with Vertical(id="verify", classes="panel"):
                yield Static("This base CV", classes="panel-title")
                yield Static("", id="verify-body", classes="panel-body")
            with Vertical(id="matches", classes="panel"):
                yield Static("Tailored CVs", classes="panel-title")
                yield Static("", id="matches-body", classes="panel-body")
        yield Static("", id="dash-help")

    def on_mount(self) -> None:
        self.reload()

    def on_screen_resume(self) -> None:
        self.reload()

    def reload(self) -> None:
        app: CvgenApp = self.app
        rows = app.model.rows
        if rows:
            self.index = max(0, min(self.index, len(rows) - 1))
        self._tailored = list_tailored(app.model.config)
        if self._tailored:
            self.tailor_index = max(0, min(self.tailor_index, len(self._tailored) - 1))
        self.query_one("#variants-body", Static).update(base_cv_lines(rows, self.index, app.checks))
        if rows:
            row = rows[self.index]
            check = app.checks.get(row.id, app.last_verify or "not checked")
            self.query_one("#verify-body", Static).update(base_cv_details(row, check))
        else:
            self.query_one("#verify-body", Static).update("No base CVs yet. Press n to add one.")
        self.query_one("#matches-body", Static).update(format_tailored(self._tailored, self.tailor_index))
        count = len(rows)
        noun = "base CV" if count == 1 else "base CVs"
        self.query_one("#insight", Static).update(
            f"{count} {noun}. Each is a Markdown file in one language and one length."
        )
        if self.focus_panel == "tailored":
            hint = "Tailored CVs    j/k move    enter report    p open PDF    c copy path    tab base CVs    esc back"
        else:
            hint = "Base CVs    j/k move    b build    v check    n new    p open PDF    c copy path    tab tailored    t tailor    esc back"
        self.query_one("#dash-help", Static).update(hint)

    def action_switch_panel(self) -> None:
        self.focus_panel = "tailored" if self.focus_panel == "base" else "base"
        self.reload()

    def action_cursor_down(self) -> None:
        if self.focus_panel == "tailored":
            self.tailor_index += 1
        else:
            self.index += 1
        self.reload()

    def action_cursor_up(self) -> None:
        if self.focus_panel == "tailored":
            self.tailor_index -= 1
        else:
            self.index -= 1
        self.reload()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_reload_view(self) -> None:
        self.app.reload()
        self.reload()

    def _selected_row(self):
        app: CvgenApp = self.app
        if not app.model.rows:
            return None
        index = max(0, min(self.index, len(app.model.rows) - 1))
        return app.model.rows[index]

    def action_open_selected(self) -> None:
        if self.focus_panel == "tailored":
            if not self._tailored:
                return
            item = self._tailored[max(0, min(self.tailor_index, len(self._tailored) - 1))]
            self.app.push_screen(FileModal(item), lambda _result: self.reload())
            return
        self.action_build_one()

    def action_open_pdf(self) -> None:
        if self.focus_panel == "tailored" and self._tailored:
            item = self._tailored[max(0, min(self.tailor_index, len(self._tailored) - 1))]
            problem = open_path(item.pdf)
            if problem:
                self.app.notify(problem, severity="warning")
            return
        row = self._selected_row()
        if row is None:
            return
        problem = open_path(row.pdf)
        if problem:
            self.app.notify(problem, severity="warning")

    def action_copy_path(self) -> None:
        if self.focus_panel == "tailored" and self._tailored:
            item = self._tailored[max(0, min(self.tailor_index, len(self._tailored) - 1))]
            text = str(item.pdf)
        else:
            row = self._selected_row()
            if row is None:
                return
            text = str(row.markdown.resolve())
        self.app.copy_to_clipboard(text)
        self.app.notify(f"Copied {text}")

    def action_new_cv(self) -> None:
        self.app.push_screen(AddCvModal(), lambda created: self.reload() if created else None)

    def action_build_one(self) -> None:
        app: CvgenApp = self.app
        row = self._selected_row()
        if row is None:
            return
        index = app.model.rows.index(row)
        app.push_screen(
            ResultModal(
                f"Build {row.id}",
                lambda: perform_build(app.model.config, app.model.rows, [index], make_pdf=app.make_pdf),
            ),
            lambda _code: self.reload(),
        )

    def action_verify_one(self) -> None:
        app: CvgenApp = self.app
        row = self._selected_row()
        if row is None:
            return
        index = app.model.rows.index(row)
        variant_id = row.id

        def finish(ok: bool | None) -> None:
            passed = bool(ok)
            app.checks[variant_id] = "passed" if passed else "failed"
            app.remember_verify(0 if passed else 1)
            self.reload()

        app.push_screen(
            ResultModal(
                "Verify",
                lambda: perform_verify(app.model.config, app.model.rows, [index]),
            ),
            finish,
        )

    def action_tailor(self) -> None:
        self.app.push_screen(TailorModal(), lambda _result: self.reload())


class CvgenApp(App[int]):
    """Start screen, dashboard, and the modals around them."""

    CSS_PATH = "cvgen.tcss"
    TITLE = "cvgen"
    COMMANDS = {CvgenCommands}
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True, show=False),
        Binding("ctrl+b", "build_all", "Build", priority=True, show=False),
        Binding("ctrl+y", "verify_all", "Verify", priority=True, show=False),
        Binding("ctrl+t", "tailor", "Tailor", priority=True, show=False),
        Binding("ctrl+d", "dashboard", "Dashboard", priority=True, show=False),
        Binding("ctrl+n", "new_workspace", "New", priority=True, show=False),
        Binding("ctrl+p", "command_palette", "Commands", priority=True, show=False),
    ]

    def __init__(
        self,
        config_path: Path | None = None,
        cwd: Path | None = None,
        make_pdf: bool | None = None,
    ) -> None:
        super().__init__()
        self.cwd = (cwd or Path.cwd()).resolve()
        self.config_path = config_path
        self.make_pdf = make_pdf
        self.model = load_screen(config_path, self.cwd)
        self.last_verify = ""
        self.checks: dict[str, str] = {}
        self.menu_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="stage"):
            yield Static(LOGO, id="logo")
            yield Static("", id="who")
            yield Static("", id="menu")
        yield OptionList(id="suggestions")
        with Horizontal(id="prompt-wrap"):
            yield Label(">", id="chevron")
            yield Input(placeholder="Paste a job URL, a file path, or type / for commands", id="prompt")
            yield Label("cvgen", id="brand")
        yield Label("Paste a job link to tailor a CV. Type / for commands.", id="hint")
        yield Label("", id="version")

    def on_mount(self) -> None:
        self._apply_key_overrides()
        self._paint_home()
        self.query_one("#prompt", Input).focus()
        if self.model.config.config_path is None:
            self.push_screen(OnboardModal(), self._after_onboard)
            return
        marker = self.model.root / "out" / ".cvgen-intro"
        if not marker.is_file():
            self.push_screen(WelcomeModal())

    def _after_onboard(self, created: bool | None) -> None:
        if created:
            self.push_screen(WelcomeModal())

    def _apply_key_overrides(self) -> None:
        for action, key in ui_key_overrides(self.model.config).items():
            self.bind(key, action, description=action)

    def _paint_home(self) -> None:
        who = self.model.config.person_name or "No workspace yet"
        try:
            self.query_one("#who", Static).update(who)
            self.query_one("#menu", Static).update(self._menu_text())
            self.query_one("#version", Label).update(__version__)
        except NoMatches:
            return

    def _menu_text(self) -> str:
        lines = []
        for index, item in enumerate(MENU):
            key = shortcut_for(item.action, self.model.config)
            marker = ">" if index == self.menu_index else " "
            shown = tint(marker, PINK) if marker == ">" else marker
            lines.append(f" {shown} {item.title:<22}{tint(f'{key:>12}', CYAN)}")
        return "\n".join(lines)

    def reload(self) -> None:
        root = self.model.root
        self.model = load_screen(self.config_path, root)
        self.model.rows = collect_rows(self.model.config)
        self._paint_home()

    def remember_verify(self, code: int) -> None:
        rows = self.model.rows
        if not rows:
            self.last_verify = "No base CVs yet."
            return
        self.last_verify = "passed" if code == 0 else "failed"

    def dispatch(self, action: str, arg: str = "") -> None:
        if action == "build_all":
            self.action_build_all()
        elif action == "verify_all":
            self.action_verify_all()
        elif action == "tailor":
            self.action_tailor(arg)
        elif action == "dashboard":
            self.action_dashboard()
        elif action == "new_workspace":
            self.action_new_workspace()
        elif action == "quit":
            self.exit(0)
        elif action == "help":
            self.push_screen(HelpModal())
        elif action == "palette":
            self.action_command_palette()
        else:
            self.notify(f"Unknown command {arg or action}", severity="warning")

    def _workspace_ready(self) -> bool:
        return self.model.config.config_path is not None

    def _require_workspace(self) -> bool:
        if self._workspace_ready():
            return True
        self.push_screen(OnboardModal(), self._after_onboard)
        return False

    def action_build_all(self) -> None:
        if not self._require_workspace():
            return
        rows = list(self.model.rows)
        config = self.model.config
        self.push_screen(
            ResultModal("Build", lambda: perform_build(config, rows, list(range(len(rows))), make_pdf=self.make_pdf)),
            lambda _code: self.reload(),
        )

    def action_verify_all(self) -> None:
        if not self._require_workspace():
            return
        rows = list(self.model.rows)
        config = self.model.config

        def finish(ok: bool | None) -> None:
            passed = bool(ok)
            for row in rows:
                self.checks[row.id] = "passed" if passed else "failed"
            self.remember_verify(0 if passed else 1)
            self.reload()

        self.push_screen(
            ResultModal("Verify", lambda: perform_verify(config, rows, list(range(len(rows))))),
            finish,
        )

    def action_tailor(self, preset: str = "") -> None:
        if not self._require_workspace():
            return
        self.push_screen(TailorModal(preset))

    def action_dashboard(self) -> None:
        if isinstance(self.screen, Dashboard):
            return
        if not self._require_workspace():
            return
        self.push_screen(Dashboard())

    def action_new_workspace(self) -> None:
        if self._workspace_ready():
            self.notify("This directory already has a workspace", severity="warning")
            return
        self.push_screen(OnboardModal(), self._after_onboard)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        listing = self.query_one("#suggestions", OptionList)
        matches = matching_commands(event.value) if event.value.startswith("/") else []
        listing.clear_options()
        if matches and event.value.startswith("/"):
            listing.add_class("visible")
            for item in matches:
                listing.add_option(Option(f"{item.slash:<14}{item.title}", id=item.action))
        else:
            listing.remove_class("visible")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt":
            return
        action = parse_prompt(event.value)
        event.input.clear()
        self.query_one("#suggestions", OptionList).remove_class("visible")
        if action.kind == "hint":
            self.notify("Paste a job URL or the posting text, or type / for commands.")
            return
        if action.kind == "unknown":
            self.notify(f"Unknown command {action.arg}", severity="warning")
            return
        self.dispatch(action.kind, action.arg)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "suggestions":
            return
        action = str(event.option.id)
        self.query_one("#prompt", Input).clear()
        self.query_one("#suggestions", OptionList).remove_class("visible")
        self.dispatch(action)

    def on_key(self, event) -> None:
        if len(self.screen_stack) != 1:
            return
        if event.key == "up":
            self.menu_index = (self.menu_index - 1) % len(MENU)
            self._paint_home()
        elif event.key == "down":
            self.menu_index = (self.menu_index + 1) % len(MENU)
            self._paint_home()


class _LineStream(io.TextIOBase):
    def __init__(self, push) -> None:
        self._push = push
        self._buf = ""

    def write(self, data: str) -> int:
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._push(line)
        return len(data)

    def flush(self) -> None:
        if self._buf.strip():
            self._push(self._buf)
            self._buf = ""


class _redirect:
    def __init__(self, stream: _LineStream) -> None:
        self._stream = stream
        self._stdout = None
        self._stderr = None

    def __enter__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = self._stream
        sys.stderr = self._stream
        return self._stream

    def __exit__(self, *exc):
        self._stream.flush()
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        return False


def run_app(config_path: Path | None = None, cwd: Path | None = None) -> int:
    app = CvgenApp(config_path=config_path, cwd=cwd)
    result = app.run()
    return int(result or 0)
