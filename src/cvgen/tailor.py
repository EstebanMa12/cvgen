"""Tailor a CV to a job posting without adding facts that the source does not contain."""

from __future__ import annotations

import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cvgen.build import BuildJob, build_one, soffice_available
from cvgen.config import Config, ConfigError
from cvgen.providers.base import DEFAULT_BASE_URLS, DEFAULT_MODELS, ENV_VARS, ProviderName, canonicalize
from cvgen.providers.factory import run_completion
from cvgen.util import display_path
from cvgen.verify import verify_paths

CV_START = "<<<CV_MARKDOWN"
CV_END = "CV_MARKDOWN>>>"
REPORT_START = "<<<REPORT_MARKDOWN"
REPORT_END = "REPORT_MARKDOWN>>>"

SYSTEM_PROMPT = (
    "You tailor a CV using only the facts in the user message. "
    "Never invent employers, institutions, titles, technologies, dates or numbers. "
    "If a requirement is not supported by the consolidated source, put it in the report's "
    "Missing section and leave it off the CV. "
    "Reply using the two requested blocks."
)


def slugify(text: str) -> str:
    folded = unicodedata.normalize("NFD", text)
    ascii_text = "".join(char for char in folded if unicodedata.category(char) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:60]


def html_to_text(html: str) -> str:
    text = re.sub(r"<(script|style|noscript)\b[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>|</(p|div|li|h\d)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&#39;": "'",
        "&apos;": "'",
        "&quot;": '"',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def load_job(job: str) -> str:
    if re.match(r"https?://", job, flags=re.IGNORECASE):
        return _load_job_url(job)
    path = Path(job)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise ConfigError(
            f"Job file not found: {job}. "
            "If the posting is behind a login, save the text to a file and pass that path."
        )
    return path.read_text(encoding="utf-8")


def _load_job_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "cvgen"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ConfigError(
            f"Could not fetch {url}: HTTP {exc.code}. Save the posting to a text file and pass that instead."
        ) from exc
    except urllib.error.URLError as exc:
        raise ConfigError(
            f"Could not fetch {url}: {exc.reason}. Save the posting to a text file and pass that instead."
        ) from exc
    text = html_to_text(raw)
    if len(text) < 200:
        raise ConfigError(
            f"The page at {url} returned too little text. It may require a login. "
            "Save the posting to a text file and pass that instead."
        )
    return f"Source URL: {url}\n\n{text[:20000]}"


def default_slug(job: str) -> str:
    if re.match(r"https?://", job, flags=re.IGNORECASE):
        parsed = urllib.parse.urlparse(job)
        host = parsed.netloc.removeprefix("www.")
        return slugify(f"{host}-{parsed.path}") or "job"
    return slugify(Path(job).stem) or "job"


def markdown_name(template: str) -> str:
    for line in template.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return "the candidate"


def extract_block(text: str, start: str, end: str) -> str | None:
    begin = text.find(start)
    if begin < 0:
        return None
    finish = text.find(end, begin + len(start))
    if finish < 0:
        return None
    body = text[begin + len(start) : finish]
    body = re.sub(r"^\s*```(?:markdown|md)?\s*\n", "", body)
    body = re.sub(r"\n```\s*$", "", body)
    return body.strip() + "\n"


def build_user_prompt(
    *,
    name: str,
    lang: str,
    length: str,
    job_text: str,
    template: str,
    source: str,
    template_label: str,
) -> str:
    language = "Spanish" if lang == "es" else "English"
    pages = "1 page" if length == "short" else "2 pages"
    return f"""You are a senior recruiter tailoring a CV for {name}.

## HARD RULES
1. The ONLY source of facts is the CONSOLIDATED SOURCE below.
2. NEVER invent experience, employers, institutions, tools, technologies, titles, degrees, dates, metrics or numbers. If the posting asks for something the source does not list, put it under Missing in the report. Do not put it in the CV.
3. Do not upgrade seniority or scope. Copy every employer, institution, role title, date and number exactly as written in the source.
4. You may reorder bullets, drop less relevant bullets and rephrase prose. Every remaining fact must still be traceable to the source.
5. Keep the name and the contact lines exactly as in the template. Keep the template's section titles.
6. Do not add confidential figures that are not already in the source. Keep HTML comments from the template as they are.
7. Return the result in the two blocks below.

## WHAT TO WRITE
- Language: {language}. Length: {length}. The rendered CV must fit on {pages}.
- Write one headline line starting with `> `, using only titles and technologies from the source.
- Rewrite the profile toward the posting. In Spanish, write the profile in the first person. In English bullets, use action verbs and do not start a bullet with "I" unless the template already does.
- Reorder bullets, technology lines and skills so matches for the posting come first.
- Use the posting's wording only when it is a true synonym of a fact in the source.

## MARKDOWN GRAMMAR
- First line `# Name`, then a `> Headline` line, then contact lines with ` | ` between items.
- `## SECTION` for sections.
- `**Employer** | Place`, then `*Role | Dates*`.
- `- bullet` lines. Inline `**bold**` is allowed.
- Technology lines are italic and contain no pipe: `*Technologies: a, b, c*` or `*Tecnologías: a, b, c*`.
- Skills use `- **Category:** a, b, c`.
- No tables, images or extra headings.

## OUTPUT FORMAT
{CV_START}
...the tailored CV markdown...
{CV_END}
{REPORT_START}
# Match report — <job title> (<company>)
## Requirements met
- requirement — evidence from the source
## Partially met
- requirement — what the source supports instead
## Missing
- requirement — not in the source. Suggest an honest next step, and do not claim it on the CV.
## ATS keywords used
- comma-separated keywords that actually appear in the CV
## Recruiter notes
- 2 to 4 bullets on positioning, risks and questions to confirm with the candidate
{REPORT_END}

## JOB POSTING
\"\"\"
{job_text.strip()}
\"\"\"

## TEMPLATE ({template_label})
\"\"\"
{template.strip()}
\"\"\"

## CONSOLIDATED SOURCE
\"\"\"
{source.strip()}
\"\"\"
"""


def full_prompt(user: str) -> str:
    return f"{SYSTEM_PROMPT}\n\n{user}"


def select_model(provider: ProviderName, config: Config, model_flag: str | None, provider_flag: str | None) -> str:
    if model_flag:
        return model_flag
    configured = canonicalize(config.provider)
    if provider_flag and provider != configured:
        return DEFAULT_MODELS[provider]
    return config.model or DEFAULT_MODELS[provider]


def key_status(provider: ProviderName, api_key_env: str | None) -> str:
    names: list[str] = []
    if api_key_env:
        names.append(api_key_env)
    else:
        primary = ENV_VARS[provider]
        if primary:
            names.append(primary)
        if provider == "gemini":
            names.append("GOOGLE_API_KEY")
    if not names:
        return "API key: not required"
    for name in names:
        if os.environ.get(name, "").strip():
            return f"{name}: set"
    return f"{names[0]}: NOT set (required for a real run)"


def _pick_template(config: Config, lang: str, length: str, explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else Path.cwd() / explicit
        if not path.is_file():
            raise ConfigError(f"Template not found: {path}")
        return path
    matches = [variant for variant in config.variants if variant.lang == lang and variant.length == length]
    if not matches:
        raise ConfigError(f"No {length}-{lang} variant in the config. Pass --template.")
    if not matches[0].input_path.is_file():
        raise ConfigError(f"Template not found: {matches[0].input_path}")
    return matches[0].input_path


def _read_source(config: Config, explicit: Path | None) -> tuple[Path, str]:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else Path.cwd() / explicit
    elif config.source_path is not None:
        path = config.source_path
    else:
        raise ConfigError("Pass --source or set paths.source in cvgen.toml.")
    if not path.is_file():
        raise ConfigError(f"Source not found: {path}")
    return path, path.read_text(encoding="utf-8")


def _repair_prompt(verify_output: str, rejected: str, source: str) -> str:
    return f"""The fact checker rejected the CV. Fix only the reported problems.
Every employer, institution, title, technology, date and number must match the consolidated source.
Do not add facts. Return the full corrected CV in the {CV_START} block.
A report block is optional.

## PROBLEMS
{verify_output}

## REJECTED CV
{rejected.strip()}

## CONSOLIDATED SOURCE
{source.strip()}
"""


def run_tailor(
    config: Config,
    *,
    job: str,
    lang: str,
    length: str,
    provider_flag: str | None,
    model_flag: str | None,
    slug: str | None,
    base_url_flag: str | None,
    dry_run: bool,
    generate: bool,
    source_path: Path | None,
    template_path: Path | None,
) -> int:
    provider = canonicalize(provider_flag or config.provider)
    model = select_model(provider, config, model_flag, provider_flag)
    base_url = base_url_flag or config.base_url
    if provider == "ollama" and not base_url:
        base_url = DEFAULT_BASE_URLS["ollama"]

    job_text = load_job(job)
    source_file, source = _read_source(config, source_path)
    template_file = _pick_template(config, lang, length, template_path)
    template = template_file.read_text(encoding="utf-8")
    name = markdown_name(template)
    user = build_user_prompt(
        name=name,
        lang=lang,
        length=length,
        job_text=job_text,
        template=template,
        source=source,
        template_label=display_path(template_file, config.root),
    )
    prompt = full_prompt(user)

    chosen_slug = slugify(slug) if slug else default_slug(job)
    if not chosen_slug:
        chosen_slug = "job"
    tailored_dir = config.tailored_dir
    tailored_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{chosen_slug}-{lang}-{length}"
    cv_path = tailored_dir / f"{stem}.md"
    report_path = tailored_dir / f"{stem}-report.md"
    prompt_path = tailored_dir / f"{stem}.prompt.md"

    if dry_run:
        prompt_path.write_text(prompt, encoding="utf-8")
        print("DRY RUN — no API call.")
        print(f"  provider: {provider}")
        print(f"  model: {model}")
        print(f"  source: {display_path(source_file, config.root)}")
        print(f"  prompt: {display_path(prompt_path, config.root)} ({len(prompt)} characters)")
        print(f"  would write: {display_path(cv_path, config.root)}")
        print(f"  would write: {display_path(report_path, config.root)}")
        print(f"  {key_status(provider, config.api_key_env)}")
        return 0

    print(f"Tailoring {stem} with {provider} ({model})...")
    answer = run_completion(
        provider,
        model=model,
        base_url=base_url,
        temperature=config.temperature,
        api_key_env=config.api_key_env,
        system=SYSTEM_PROMPT,
        user=user,
        cwd=config.root,
    )
    cv = extract_block(answer, CV_START, CV_END)
    report = extract_block(answer, REPORT_START, REPORT_END)
    if cv is None or report is None:
        raw_path = tailored_dir / f"{stem}-raw-answer.md"
        raw_path.write_text(answer, encoding="utf-8")
        print(f"ERROR: the model did not return both blocks. Raw answer: {display_path(raw_path, config.root)}")
        return 2
    cv_path.write_text(cv, encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {display_path(cv_path, config.root)}")
    print(f"Wrote {display_path(report_path, config.root)}")
    if not generate:
        return 0

    ok, verify_output = verify_paths([cv_path], source, config)
    print(verify_output)
    if not ok:
        print("Fact check failed — asking the model for one correction...")
        repaired = run_completion(
            provider,
            model=model,
            base_url=base_url,
            temperature=config.temperature,
            api_key_env=config.api_key_env,
            system=SYSTEM_PROMPT,
            user=_repair_prompt(verify_output, cv, source),
            cwd=config.root,
        )
        fixed = extract_block(repaired, CV_START, CV_END)
        if fixed is None:
            raw_path = tailored_dir / f"{stem}-raw-answer.md"
            raw_path.write_text(repaired, encoding="utf-8")
            print(f"ERROR: the correction did not include a CV block. Raw answer: {display_path(raw_path, config.root)}")
            return 2
        cv_path.write_text(fixed, encoding="utf-8")
        revised_report = extract_block(repaired, REPORT_START, REPORT_END)
        if revised_report is not None:
            report_path.write_text(revised_report, encoding="utf-8")
        ok, verify_output = verify_paths([cv_path], source, config)
        print(verify_output)
        if not ok:
            print(f"ERROR: fact check still failing. Review {display_path(cv_path, config.root)}.")
            return 3

    make_pdf = soffice_available()
    if not make_pdf:
        print("WARNING: LibreOffice (soffice) was not found — writing the DOCX and skipping PDF export.")
    built = build_one(
        BuildJob(cv_path, cv_path.with_suffix(".docx"), length),
        config,
        make_pdf=make_pdf,
        autofit=True,
    )
    if not built:
        print("ERROR: rendering the tailored CV failed.")
        return 4
    print(f"\nDone. Read {display_path(report_path, config.root)} before sending the CV.")
    return 0
