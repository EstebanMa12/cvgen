"""Interactive cvgen screen.

The start screen is a centered menu with a prompt, in the spirit of the
Grok Build CLI. The dashboard is a panel layout: variants and page meters,
the latest check, and match scores for tailored CVs.
"""

from __future__ import annotations

import io
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
    Footer,
    Input,
    Label,
    Markdown,
    OptionList,
    RichLog,
    Select,
    Static,
    Switch,
)
from textual.widgets.option_list import Option

from cvgen import __version__
from cvgen.config import ConfigError
from cvgen.onboard import (
    Wizard,
    create,
    folder_error,
    handle,
    name_error,
    screen_lines,
)
from cvgen.providers.base import ProviderName
from cvgen.tui import (
    bar,
    busiest,
    collect_rows,
    load_screen,
    meter_line,
    perform_build,
    perform_verify,
)
from cvgen.tailor import run_tailor
from cvgen.ui.commands import (
    MENU,
    MenuItem,
    PromptAction,
    matching_commands,
    parse_prompt,
    parse_report,
    shortcut_for,
    tailored_reports,
    ui_key_overrides,
)
from cvgen.ui.logo import LOGO

_PROVIDERS = [(name, name) for name in get_args(ProviderName)]


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
    """Pick a posting and options, then show progress and the match report."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, preset: str = "") -> None:
        super().__init__()
        self.preset = preset

    def compose(self) -> ComposeResult:
        app: CvgenApp = self.app
        root = app.model.root
        jobs = []
        directory = root / "jobs"
        if directory.is_dir():
            jobs = sorted(path for path in directory.iterdir() if path.is_file())
        self._jobs = jobs
        with Vertical(id="dialog"):
            yield Label("Tailor to a job", id="dialog-title")
            yield OptionList(id="jobs")
            yield Input(value=self.preset, placeholder="job file or URL", id="job-path")
            yield Select((("Spanish", "es"), ("English", "en")), value="es", id="lang", allow_blank=False)
            yield Select(
                (("Short, 1 page", "short"), ("Extended, 2 pages", "extended")),
                value="short",
                id="length",
                allow_blank=False,
            )
            yield Select(_PROVIDERS, value="openai", id="provider", allow_blank=False)
            yield Input(placeholder="model, empty uses the provider default", id="model")
            with Horizontal(classes="row"):
                yield Switch(value=True, id="dry")
                yield Label("Dry-run, write the prompt only")
            with Horizontal():
                yield Button("Run", id="run", variant="primary")
                yield Button("Close", id="close")
            yield RichLog(id="log", highlight=False, markup=False, classes="hidden")
            yield Markdown("", id="report")

    def on_mount(self) -> None:
        listing = self.query_one("#jobs", OptionList)
        for path in self._jobs:
            listing.add_option(Option(path.name, id=path.name))
        self.query_one("#report", Markdown).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "run":
            self._start()

    def _job_text(self) -> str:
        typed = self.query_one("#job-path", Input).value.strip()
        if typed:
            return typed
        listing = self.query_one("#jobs", OptionList)
        if listing.highlighted is None or not self._jobs:
            return ""
        return self._jobs[listing.highlighted].name

    def _start(self) -> None:
        job = self._job_text()
        if not job:
            self.app.notify("Choose a job file or type a path", severity="warning")
            return
        self.query_one("#run", Button).disabled = True
        self._log = self.query_one(RichLog)
        self._log.display = True
        self._log.write("Working…")
        self._args = {
            "job": job,
            "lang": str(self.query_one("#lang", Select).value),
            "length": str(self.query_one("#length", Select).value),
            "provider": str(self.query_one("#provider", Select).value),
            "model": self.query_one("#model", Input).value.strip(),
            "dry": bool(self.query_one("#dry", Switch).value),
        }
        self.run_worker(self._go, thread=True, exclusive=True)

    def _go(self) -> int:
        args = self._args
        app: CvgenApp = self.app

        def push(line: str) -> None:
            self.app.call_from_thread(self._log.write, line)

        try:
            stream = _LineStream(push)
            with _redirect(stream):
                code = run_tailor(
                    app.model.config,
                    job=args["job"],
                    lang=args["lang"],
                    length=args["length"],
                    provider_flag=args["provider"],
                    model_flag=args["model"] or None,
                    slug=None,
                    base_url_flag=None,
                    dry_run=args["dry"],
                    generate=not args["dry"],
                    source_path=None,
                    template_path=None,
                )
        except Exception as exc:
            push(str(exc))
            code = 1
        self.app.call_from_thread(self._show_report, code)
        return code

    def _show_report(self, code: int) -> None:
        app: CvgenApp = self.app
        app.reload()
        reports = tailored_reports(app.model.config)
        if reports and not self._args["dry"]:
            name, met, partial, missing = reports[-1]
            path = app.model.config.tailored_dir / f"{name}.md"
            if path.is_file():
                body = path.read_text(encoding="utf-8")
                view = self.query_one("#report", Markdown)
                view.display = True
                view.update(body)
            self.query_one(RichLog).write(f"Match  met {met}   partial {partial}   missing {missing}")
        severity = "information" if code == 0 else "error"
        self.app.notify("Tailor finished" if code == 0 else "Tailor failed", severity=severity)


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
            yield Label("Commands", id="dialog-title")
            yield Static(
                "\n".join(
                    [
                        "The prompt accepts the same actions as the menu.",
                        "",
                        "  /build                 render every variant",
                        "  /verify                fact-check every variant",
                        "  /tailor jobs/role.txt  open tailor for that file",
                        "  /dashboard             variants, checks, matches",
                        "  /new                   create the folders",
                        "  /quit",
                        "",
                        "ctrl+p opens the command palette.",
                        "Shell commands are unchanged: cvgen build, cvgen verify, cvgen tailor.",
                    ]
                )
            )
            yield Label("esc close", id="dialog-hint")


class Dashboard(Screen[None]):
    """Variants, the latest check, and tailor match scores."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("enter", "build_one", "Build"),
        Binding("b", "build_one", "Build"),
        Binding("v", "verify_one", "Verify"),
        Binding("t", "tailor", "Tailor"),
        Binding("r", "reload_view", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.index = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="insight")
        with Grid(id="dash"):
            with Vertical(id="variants", classes="panel"):
                yield Static("variants", classes="panel-title")
                yield Static("", id="variants-body", classes="panel-body")
            with Vertical(id="verify", classes="panel"):
                yield Static("latest check", classes="panel-title")
                yield Static("Not checked yet. Press v.", id="verify-body", classes="panel-body")
            with Vertical(id="matches", classes="panel"):
                yield Static("tailored", classes="panel-title")
                yield Static("", id="matches-body", classes="panel-body")
        yield Footer()

    def on_mount(self) -> None:
        self.reload()

    def on_screen_resume(self) -> None:
        self.reload()

    def reload(self) -> None:
        app: CvgenApp = self.app
        rows = app.model.rows
        if rows:
            self.index = max(0, min(self.index, len(rows) - 1))
        lines = [meter_line(row, i == self.index) for i, row in enumerate(rows)]
        if not rows:
            lines = ["No variants yet."]
        self.query_one("#variants-body", Static).update("\n".join(lines))
        ratio, label = busiest(rows)
        reports = tailored_reports(app.model.config)
        self.query_one("#insight", Static).update(
            f"{len(rows)} variants    pages {bar(ratio, 12)}  {label}    tailored {len(reports)}"
        )
        if reports:
            body = "\n".join(
                f"{name}    met {met}  partial {partial}  missing {missing}"
                for name, met, partial, missing in reports
            )
        else:
            body = "No tailored CVs yet. Press t."
        self.query_one("#matches-body", Static).update(body)
        note = app.last_verify or "Not checked yet. Press v."
        self.query_one("#verify-body", Static).update(note)

    def action_cursor_down(self) -> None:
        self.index += 1
        self.reload()

    def action_cursor_up(self) -> None:
        self.index -= 1
        self.reload()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_reload_view(self) -> None:
        self.app.reload()
        self.reload()

    def action_build_one(self) -> None:
        app: CvgenApp = self.app
        if not app.model.rows:
            return
        index = max(0, min(self.index, len(app.model.rows) - 1))
        row = app.model.rows[index]
        app.push_screen(
            ResultModal(
                f"Build {row.id}",
                lambda: perform_build(app.model.config, app.model.rows, [index], make_pdf=app.make_pdf),
            ),
            lambda _code: self.reload(),
        )

    def action_verify_one(self) -> None:
        app: CvgenApp = self.app
        if not app.model.rows:
            return
        index = max(0, min(self.index, len(app.model.rows) - 1))

        def finish(ok: bool | None) -> None:
            app.remember_verify(0 if ok else 1)
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
        self.menu_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="stage"):
            yield Static(LOGO, id="logo")
            yield Static("", id="who")
            yield Static("", id="menu")
        yield OptionList(id="suggestions")
        with Horizontal(id="prompt-wrap"):
            yield Label(">", id="chevron")
            yield Input(placeholder="/tailor jobs/posting.txt", id="prompt")
            yield Label("cvgen", id="brand")
        yield Label("", id="version")

    def on_mount(self) -> None:
        self._apply_key_overrides()
        self._paint_home()
        self.query_one("#prompt", Input).focus()
        if self.model.config.config_path is None:
            self.push_screen(OnboardModal())

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
            lines.append(f" {marker} {item.title:<22}{key:>12}")
        return "\n".join(lines)

    def reload(self) -> None:
        root = self.model.root
        self.model = load_screen(self.config_path, root)
        self.model.rows = collect_rows(self.model.config)
        self._paint_home()

    def remember_verify(self, code: int) -> None:
        rows = self.model.rows
        if not rows:
            self.last_verify = "No variants."
            return
        self.last_verify = "All checks passed." if code == 0 else "Some checks failed. See the log."

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
        self.push_screen(OnboardModal())
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
            self.remember_verify(0 if ok else 1)
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
        self.push_screen(OnboardModal())

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
        if action.kind == "selected":
            self.dispatch(MENU[self.menu_index].action)
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
        import sys

        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = self._stream
        sys.stderr = self._stream
        return self._stream

    def __exit__(self, *exc):
        import sys

        self._stream.flush()
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        return False


def run_app(config_path: Path | None = None, cwd: Path | None = None) -> int:
    app = CvgenApp(config_path=config_path, cwd=cwd)
    result = app.run()
    return int(result or 0)
