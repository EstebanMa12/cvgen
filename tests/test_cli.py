from pathlib import Path

import pytest

from cvgen.cli import main
from cvgen.config import ConfigError, load_config


def test_init_build_and_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert main(["init"]) == 1
    assert main(["build", "--no-pdf"]) == 0
    for name in (
        "avery-quinn-short-en.docx",
        "avery-quinn-short-es.docx",
        "avery-quinn-extended-en.docx",
        "avery-quinn-extended-es.docx",
    ):
        assert (tmp_path / "out" / name).is_file()
    assert main(["verify"]) == 0
    verify_out = capsys.readouterr().out
    assert "All checks passed." in verify_out
    assert main(["verify", "out/avery-quinn-short-en.docx"]) == 0


def test_verify_fails_on_an_invented_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    original = (tmp_path / "cv" / "avery-quinn-short-en.md").read_text(encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text(
        original.replace(
            "## EXPERIENCE\n",
            "## EXPERIENCE\n"
            "**Initech** | Port Meridian\n"
            "*Chief Astronaut | April 1999 – Present*\n"
            "*Technologies: Oracle*\n"
            "- Led 99 launches.\n",
        ),
        encoding="utf-8",
    )
    assert main(["verify", str(bad)]) == 1
    markdown_report = capsys.readouterr().out
    assert "Initech" in markdown_report
    assert "Oracle" in markdown_report
    assert "99" in markdown_report
    docx = tmp_path / "bad.docx"
    assert main(["build", "--input", str(bad), "--output", str(docx), "--length", "short", "--no-pdf"]) == 0
    assert main(["verify", str(docx)]) == 1
    docx_report = capsys.readouterr().out
    assert "Initech" in docx_report
    assert "Oracle" in docx_report


def test_dry_run_writes_the_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0

    def boom(*_args, **_kwargs):
        raise AssertionError("provider should not be called")

    monkeypatch.setattr("cvgen.tailor.run_completion", boom)
    code = main(
        ["tailor", "--job", "jobs/lumenfield-backend.txt", "--lang", "es", "--length", "short", "--dry-run"]
    )
    assert code == 0
    prompts = list((tmp_path / "out" / "tailored").glob("*.prompt.md"))
    assert len(prompts) == 1
    text = prompts[0].read_text(encoding="utf-8")
    assert "NEVER invent" in text
    assert "Lumenfield" in text
    assert "Northwind Labs" in text
    assert "Avery Quinn" in text


def test_config_rejects_api_keys(tmp_path: Path):
    path = tmp_path / "cvgen.toml"
    path.write_text('[tailor]\napi_key = "sk-abcdefghijklmnopqrstuvwxyz"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="environment variable"):
        load_config(path)


def test_version():
    assert main(["--version"]) == 0


def test_variant_add_writes_a_base_cv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    code = main(["variant", "add", "--name", "Brief English", "--lang", "en", "--length", "short", "--blank"])
    assert code == 0
    created = tmp_path / "cv" / "brief-english.md"
    assert created.is_file()
    text = (tmp_path / "cvgen.toml").read_text(encoding="utf-8")
    assert 'id = "brief-english"' in text
    assert 'lang = "en"' in text
    config = load_config(tmp_path / "cvgen.toml")
    added = next(variant for variant in config.variants if variant.id == "brief-english")
    assert added.length == "short"
    assert added.lang == "en"
    code = main(
        ["variant", "add", "--name", "One pager", "--lang", "es", "--length", "one-pager", "--max-pages", "1", "--blank"]
    )
    assert code == 0
    custom = load_config(tmp_path / "cvgen.toml")
    one = next(variant for variant in custom.variants if variant.id == "one-pager")
    assert one.max_pages == 1
    assert one.lang == "es"
