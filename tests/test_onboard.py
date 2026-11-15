from pathlib import Path

from cvgen.config import load_config
from cvgen.onboard import Wizard, destination, folder_error, handle, screen_lines
from cvgen.scaffold import init_blank
from cvgen.theme import palette
from cvgen.tui import load_screen
from cvgen.verify import verify_paths


def test_dracula_palette_is_purple():
    colors = palette(256)
    assert colors["purple"] == 141
    assert colors["pink"] == 212
    assert colors["bg"] == 236
    assert colors["cyan"] == 117


def test_welcome_names_the_folders():
    lines = "\n".join(text for _role, text in screen_lines(Wizard(), Path("/tmp")))
    for folder in ("source/", "cv/", "jobs/", "out/"):
        assert folder in lines


def test_wizard_reaches_review_for_the_example():
    wizard = Wizard()
    assert handle(wizard, "next") == "stay"
    assert wizard.step == "folder"
    assert handle(wizard, "next") == "stay"
    assert wizard.step == "kind"
    assert handle(wizard, "next") == "stay"
    assert wizard.step == "review"
    assert handle(wizard, "next") == "create"


def test_blank_path_asks_for_a_name_and_rejects_a_parent_directory():
    wizard = Wizard()
    handle(wizard, "next")
    handle(wizard, "next")
    handle(wizard, "down")
    assert wizard.kind == "blank"
    handle(wizard, "next")
    assert wizard.step == "name"
    assert handle(wizard, "next") == "stay"
    assert wizard.step == "name"
    handle(wizard, "type:C")
    handle(wizard, "type:a")
    handle(wizard, "type:s")
    handle(wizard, "type:e")
    handle(wizard, "type:y")
    assert handle(wizard, "next") == "stay"
    assert wizard.step == "review"
    assert folder_error("../outside") is not None
    assert destination(Path("/tmp/work"), "my-cv") == Path("/tmp/work/my-cv").resolve()


def test_blank_workspace_verifies(tmp_path: Path):
    written = init_blank(tmp_path, "Casey Rivera")
    assert (tmp_path / "source").is_dir()
    assert (tmp_path / "cv").is_dir()
    assert (tmp_path / "jobs").is_dir()
    assert (tmp_path / "out" / "tailored").is_dir()
    config = load_config(tmp_path / "cvgen.toml")
    assert config.person_name == "Casey Rivera"
    source = (tmp_path / "source" / "consolidated.md").read_text(encoding="utf-8")
    cvs = [item for item in written if item.parent.name == "cv"]
    ok, report = verify_paths(cvs, source, config)
    assert ok, report


def test_empty_directory_opens_the_folder_wizard(tmp_path: Path):
    screen = load_screen(None, tmp_path)
    assert screen.mode == "onboard"
    assert screen.wizard.step == "welcome"
