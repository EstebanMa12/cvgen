"""Job URL, paste, and jobs/ path resolution."""

from pathlib import Path

from cvgen.cli import main
from cvgen.config import load_config
from cvgen.jobs import (
    chosen_job,
    classify_job_input,
    fetch_posting,
    fetch_urls,
    plain_job_error,
    resolve_saved_job,
)
from cvgen.tailor import load_job
from cvgen.ui.commands import list_tailored


def test_bare_filename_resolves_under_jobs(tmp_path: Path, monkeypatch):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    target = tmp_path / "jobs" / "harbor-role.txt"
    target.write_text("Harbor & Co. needs Python and FastAPI for the lantern API.\n")
    monkeypatch.chdir(tmp_path / "out")
    found = resolve_saved_job("harbor-role.txt", tmp_path)
    assert found == target.resolve()
    picked = chosen_job("", target)
    assert picked.endswith("jobs/harbor-role.txt")
    assert Path(picked).parent.name == "jobs"
    assert "FastAPI" in load_job("harbor-role.txt", root=tmp_path)
    assert "FastAPI" in load_job(picked, root=tmp_path)


def test_url_is_saved_and_pasted_text_is_saved(tmp_path: Path, monkeypatch):
    page = "<article>" + ("Harbor & Co. wants Python and FastAPI engineers. " * 6) + "</article>"

    def opener(url: str) -> str:
        assert url == "https://jobs.example.com/harbor-backend"
        return page

    monkeypatch.setattr("cvgen.jobs.default_opener", opener)
    text = load_job("https://jobs.example.com/harbor-backend", root=tmp_path)
    assert "FastAPI" in text
    saved = list((tmp_path / "jobs").glob("*.txt"))
    assert len(saved) == 1
    assert "FastAPI" in saved[0].read_text(encoding="utf-8")

    pasted = "Northwind Labs is hiring a backend engineer who writes Python services every day."
    assert classify_job_input(pasted) == "pasted"
    assert "Northwind" in load_job(pasted, root=tmp_path)
    assert list((tmp_path / "jobs").glob("pasted-*.txt"))


def test_linkedin_guest_url_is_tried_first(monkeypatch):
    public = "https://www.linkedin.com/jobs/view/1000000001/"
    urls = fetch_urls(public)
    assert urls[0].endswith("/jobs-guest/jobs/api/jobPosting/1000000001")
    seen: list[str] = []

    def opener(url: str) -> str:
        seen.append(url)
        if "jobs-guest" in url:
            return "<article>" + ("Build Python services for Harbor and Co. " * 8) + "</article>"
        raise AssertionError(url)

    monkeypatch.setattr("cvgen.jobs.default_opener", opener)
    text = fetch_posting(public)
    assert seen == [urls[0]]
    assert "Python" in text


def test_blocked_page_explains_the_paste_fallback(monkeypatch):
    def opener(url: str) -> str:
        return "<html>login</html>"

    monkeypatch.setattr("cvgen.jobs.default_opener", opener)
    try:
        fetch_posting("https://jobs.example.com/private")
    except Exception as exc:
        message = plain_job_error(str(exc))
    else:
        raise AssertionError("expected a fetch error")
    assert "paste" in message.lower()
    assert "login" in message.lower() or "page" in message.lower()


def test_missing_file_message_says_where_to_look():
    message = plain_job_error("Job file not found: harbor-role.txt")
    assert "jobs folder" in message
    assert "paste" in message.lower()


def test_tailored_list_uses_the_report_title(tmp_path: Path):
    assert main(["init", "--dir", str(tmp_path)]) == 0
    report = tmp_path / "out" / "tailored" / "harbor-role-en-short-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "\n".join(
            [
                "# Match report — Harbor backend",
                "## Requirements met",
                "- Python",
                "- FastAPI",
                "## Partially met",
                "- Docker",
                "## Missing",
                "- Kubernetes",
            ]
        ),
        encoding="utf-8",
    )
    items = list_tailored(load_config(tmp_path / "cvgen.toml"))
    assert items[0].title == "Harbor backend"
    assert items[0].met == 2
    assert items[0].partial == 1
    assert items[0].missing == 1
    assert items[0].percent == 50
    assert items[0].report == report.resolve()
    assert str(items[0].pdf).endswith("harbor-role-en-short.pdf")
