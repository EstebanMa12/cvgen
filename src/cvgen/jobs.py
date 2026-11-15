"""Turn a job URL, a file path, or pasted text into a posting saved under jobs/."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from cvgen.config import ConfigError
from cvgen.tailor import default_slug, html_to_text, slugify

MIN_POSTING_CHARS = 80
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_LINKEDIN_ID = re.compile(
    r"linkedin\.com/(?:jobs/view|jobs-guest/jobs/api/jobPosting)/(\d+)",
    re.IGNORECASE,
)


class JobFetchError(ConfigError):
    """The posting URL could not be read. The UI can offer a paste box."""

    def __init__(self, message: str, *, url: str = "") -> None:
        super().__init__(message)
        self.url = url


def classify_job_input(text: str) -> str:
    """Return url, pasted, path, or empty."""
    raw = text.strip()
    if not raw:
        return "empty"
    first = raw.splitlines()[0].strip()
    if _URL.fullmatch(first) and "\n" not in raw:
        return "url"
    if "\n" in raw or len(raw) >= 120 or raw.count(" ") >= 6:
        return "pasted"
    return "path"


def linkedin_job_id(url: str) -> str | None:
    match = _LINKEDIN_ID.search(url)
    return match.group(1) if match else None


def fetch_urls(url: str) -> list[str]:
    """Guest LinkedIn endpoint first, then the public job page."""
    job_id = linkedin_job_id(url)
    if not job_id:
        return [url]
    guest = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    public = f"https://www.linkedin.com/jobs/view/{job_id}/"
    ordered: list[str] = []
    for candidate in (guest, public, url):
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _description_from_jsonld(data: object) -> str:
    nodes: list[object]
    if isinstance(data, list):
        nodes = list(data)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        nodes = list(graph) if isinstance(graph, list) else [data]
    else:
        return ""
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" not in kinds and "description" not in node:
            continue
        description = node.get("description")
        if isinstance(description, str) and description.strip():
            return html_to_text(description)
    return ""


def extract_readable_text(html: str) -> str:
    """Prefer a job description, then the main article, then the whole page."""
    for blob in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        text = _description_from_jsonld(data)
        if len(text) >= MIN_POSTING_CHARS:
            return text
    markup = re.search(
        r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if markup:
        text = html_to_text(markup.group(1))
        if len(text) >= MIN_POSTING_CHARS:
            return text
    for tag in ("main", "article"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            text = html_to_text(match.group(1))
            if len(text) >= MIN_POSTING_CHARS:
                return text
    return html_to_text(html)


def default_opener(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise JobFetchError(f"HTTP {exc.code}", url=url) from exc
    except urllib.error.URLError as exc:
        raise JobFetchError(str(exc.reason), url=url) from exc


def fetch_posting(url: str, opener: Callable[[str], str] | None = None) -> str:
    """Download a posting. Raises JobFetchError when every attempt is blocked or empty."""
    read = opener or default_opener
    errors: list[str] = []
    for candidate in fetch_urls(url):
        try:
            html = read(candidate)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            continue
        text = extract_readable_text(html)
        if len(text) >= MIN_POSTING_CHARS:
            return f"Source URL: {url}\n\n{text[:20000]}"
        errors.append(f"{candidate}: too little readable text ({len(text)} characters)")
    detail = errors[-1] if errors else "no response"
    raise JobFetchError(
        "Could not read that job page. The site may require a login or may be blocking "
        f"automated requests. Paste the posting text instead. Last attempt: {detail}",
        url=url,
    )


def chosen_job(typed: str, highlighted: Path | None) -> str:
    """The job the form should open. A picked file is its path, not its bare name."""
    if typed.strip():
        return typed.strip()
    if highlighted is not None:
        return str(highlighted.resolve())
    return ""


def resolve_saved_job(reference: str, root: Path) -> Path | None:
    """Find a posting file in the workspace, including a bare name under jobs/."""
    raw = reference.strip()
    if classify_job_input(raw) != "path":
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    direct = (root / candidate).resolve()
    if direct.is_file():
        return direct
    portable = raw.replace("\\", "/")
    bare_name = "/" not in portable
    if bare_name or portable.startswith("jobs/"):
        in_jobs = (root / "jobs" / candidate.name).resolve()
        if in_jobs.is_file():
            return in_jobs
    return None


def save_posting(jobs_dir: Path, slug: str, text: str) -> Path:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    safe = slugify(slug) or "job"
    destination = jobs_dir / f"{safe}.txt"
    body = text if text.endswith("\n") else text + "\n"
    destination.write_text(body, encoding="utf-8")
    return destination


def plain_job_error(message: str) -> str:
    """Turn a tailor failure into one sentence plus what to do next."""
    text = message.strip()
    lowered = text.lower()
    if "job file not found" in lowered or "no job was given" in lowered:
        return (
            "That posting is not in the jobs folder. "
            "Pick a saved job, paste a public URL, or paste the posting text."
        )
    if "could not read that job page" in lowered or "could not fetch" in lowered:
        return (
            "The page could not be read. It may be behind a login or blocking downloads. "
            "Copy the posting text, paste it in the job box, and press Generate CV again."
        )
    if "api key" in lowered or "environment variable" in lowered:
        return (
            "The AI provider has no key in the environment. "
            "Export that key, or open Advanced and turn on preview only."
        )
    if not text:
        return "The tailor step failed. Read the log under the message and try again."
    first = text.splitlines()[-1].strip()
    return first or text


def posting_slug(text: str) -> str:
    if classify_job_input(text) == "url":
        job_id = linkedin_job_id(text.strip())
        if job_id:
            return f"linkedin-{job_id}"
        return default_slug(text.strip())
    first = text.strip().splitlines()[0] if text.strip() else "pasted-posting"
    return f"pasted-{slugify(first)[:40] or 'posting'}"
