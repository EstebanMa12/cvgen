"""Fact-check a CV against a consolidated source of truth.

Every technology, employer, institution, role title, date and number in the
CV must occur in the source. A miss is reported as a FACT error. Keyword
rules (required and forbidden phrases) are configured per workspace.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from cvgen.config import Config, Variant
from cvgen.docx_io import load_docx
from cvgen.markdown import (
    CvModel,
    detect_language,
    model_text,
    parse_markdown_file,
    strip_comments,
)
from cvgen.pdf import count_pdf_pages
from cvgen.util import display_path

EXPERIENCE_HEADINGS = ("EXPERIENCE", "EXPERIENCIA", "WORK")
EDUCATION_HEADINGS = ("EDUCATION", "FORMACIÓN ACADÉMICA", "EDUCACIÓN")
PROJECT_HEADINGS = ("PROJECT", "PROYECTO")
SKILL_HEADINGS = ("SKILLS", "HABILIDADES")
CERT_HEADINGS = ("CERTIF", "EXTENDED EDUCATION", "FORMACIÓN COMPLEMENTARIA")

# Technologies a model might add because a job posting mentioned them.
# Any of these in a CV but not in the source is a FACT error. Word boundaries
# are used, and short tokens (Go, S3, JPA) stay case-sensitive.
KNOWN_TECH = [
    "JHipster", "Oracle", "PL/SQL", "PLSQL", "Angular", "AngularJS", "Kotlin", "Scala", "Rust",
    "Golang", "C#", ".NET", "ASP.NET", "PHP", "Laravel", "Symfony", "Ruby", "Rails", "Go",
    "Swift", "Objective-C", "Flutter", "Dart", "React Native", "Ionic", "Xamarin", "GraphQL",
    "gRPC", "Kafka", "RabbitMQ", "Redis", "MySQL", "MariaDB", "SQL Server", "T-SQL", "DynamoDB",
    "Cassandra", "Elasticsearch", "Firebase", "Supabase", "Terraform", "Ansible", "Jenkins",
    "GitHub Actions", "GitLab", "CircleCI", "Helm", "OpenShift", "AWS Lambda", "EC2", "ECS",
    "EKS", "CloudFormation", "Azure", "GCP", "Google Cloud", "Hibernate", "Maven", "Gradle",
    "Quarkus", "Micronaut", "Spring Cloud", "Spring Security", "Spring Batch", "Struts", "JSF",
    "JUnit", "Mockito", "Selenium", "Cypress", "Jest", "Playwright", "Vitest", "Svelte", "Nuxt",
    "Tailwind", "jQuery", "Redux", "Unity", "Unreal", "C++", "TensorFlow", "PyTorch", "Pandas",
    "FastAPI", "Flask", "Spark", "Hadoop", "Airflow", "Power BI", "Tableau", "SAP", "Salesforce",
    "Scrum", "Jira", "Linux", "Bash", "Vue", "React", "Java", "Python", "TypeScript",
    "JavaScript", "HTML", "CSS", "SQL", "PostgreSQL", "MongoDB", "SQLite", "Docker",
    "Kubernetes", "Nginx", "Django", "Express", "Node.js", "Next.js", "Storybook", "Turborepo",
    "Spring Boot", "JPA", "Servlets", "Bootstrap", "Bitnami", "MQTT", "AWS", "Cognito", "S3",
]

MONTHS = (
    "january february march april may june july august september october november "
    "december enero febrero marzo abril mayo junio julio agosto septiembre octubre "
    "noviembre diciembre"
).split()


def norm(text: str) -> str:
    """Casefold, unify dashes and drop markdown emphasis."""
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ")
    text = re.sub(r"[‐‑‒–—−]", "–", text)
    text = text.replace("’", "'").replace("*", "")
    text = re.sub(r"\s*–\s*", " – ", text)
    text = re.sub(r"\s+", " ", text)
    return text.casefold().strip()


def norm_number(token: str) -> str:
    token = re.sub(r"[‐‑‒—−-]", "–", token)
    return re.sub(r"[\s~+]", "", token)


def contains_term(text: str, term: str) -> bool:
    """Word-boundary match. Short acronyms stay case-sensitive."""
    flags = 0 if len(term) <= 3 else re.IGNORECASE
    pattern = r"(?<![\w.+#/-])" + re.escape(term) + r"(?![\w+#]|\.[A-Za-z])"
    return re.search(pattern, text, flags) is not None


def split_items(text: str) -> list[str]:
    text = re.sub(r"^\*\*[^*]+\*\*\s*", "", text)
    return [part.strip().strip(".") for part in text.split(",") if part.strip()]


def load_cv(path: Path) -> CvModel:
    if path.suffix.lower() == ".docx":
        return load_docx(path)
    return parse_markdown_file(path)


def fact_check(model: CvModel, source_raw: str, *, extra_tech: list[str] | None = None) -> list[str]:
    """Return FACT messages for claims that the source does not contain."""
    src = norm(strip_comments(source_raw))
    src_numbers = {norm_number(n) for n in re.findall(r"\d+(?:\s*[–—-]\s*\d+)?", src)}
    src_numbers |= {part for token in list(src_numbers) for part in token.split("–")}
    errors: list[str] = []

    def need(kind: str, value: str) -> None:
        if value and norm(value) not in src:
            errors.append(f"{kind} not in source: {value!r}")

    full = model_text(model)
    body = "\n".join(line for line in full.splitlines() if line not in model["contact"])
    need("Name", model["name"])

    for section in model["sections"]:
        title = section["title"].upper()
        is_exp = title.startswith(EXPERIENCE_HEADINGS)
        is_edu = title.startswith(EDUCATION_HEADINGS)
        is_proj = title.startswith(PROJECT_HEADINGS)
        is_skill = title.startswith(SKILL_HEADINGS)
        is_cert = any(heading in title for heading in CERT_HEADINGS)
        for item in section["items"]:
            kind = item[0]
            if kind == "entry" and (is_exp or is_edu):
                need("Employer/institution", item[1])
                need("Location", item[2])
            elif kind == "entry" and is_proj:
                need("Project", item[1])
                need("Project dates", item[2])
            elif kind == "subentry":
                need("Title", item[1])
                need("Dates", item[2])
            elif kind == "tech":
                for tech in split_items(re.sub(r"^[^:]*:\s*", "", item[1])):
                    need("Technology", tech)
            elif kind == "bullet" and is_skill:
                for tech in split_items(item[1]):
                    need("Skill", tech)
            elif kind == "bullet" and is_cert:
                need("Certification", re.split(r"\s+[—|]\s+", item[1])[0])

    source_plain = strip_comments(source_raw)
    vocabulary = list(KNOWN_TECH) + list(extra_tech or [])
    for term in vocabulary:
        if contains_term(body, term) and not contains_term(source_plain, term):
            errors.append(f"Technology not in source: {term!r}")

    for month, year in re.findall(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", body, re.IGNORECASE):
        need("Date", f"{month} {year}")

    src_compact = re.sub(r"\s+", "", src)
    for token in re.findall(r"[~+]?\d+(?:[.,]\d+)?(?:\s*[–—-]\s*\d+)?[+%]?", body):
        number = norm_number(token)
        decorated = token.strip()
        if decorated[:1] == "~" or decorated[-1:] in "+%":
            if norm(decorated).replace(" ", "") not in src_compact:
                errors.append(f"Number not in source: {decorated!r}")
        elif number and number not in src_numbers:
            errors.append(f"Number not in source: {decorated!r}")

    return sorted(set(errors))


def keyword_check(
    text: str,
    *,
    required: list[str],
    forbidden: list[str],
) -> list[str]:
    problems: list[str] = []
    missing = [term for term in required if term and term not in text]
    present = [term for term in forbidden if term and contains_term(text, term)]
    if missing:
        problems.append(f"MISSING keywords: {missing}")
    if present:
        problems.append(f"FORBIDDEN present: {present}")
    return problems


def match_variant(path: Path, config: Config) -> Variant | None:
    resolved = path.resolve()
    for variant in config.variants:
        output = (config.output_dir / variant.output_name).resolve()
        if resolved == variant.input_path.resolve() or resolved == output:
            return variant
    return None


def _length_from_name(path: Path) -> str | None:
    name = path.name.lower()
    if "short" in name or "corta" in name:
        return "short"
    if "extended" in name or "extendid" in name:
        return "extended"
    return None


def pdf_for(path: Path, config: Config) -> Path | None:
    """PDF sitting next to path, or the variant's built PDF in the output dir."""
    sibling = path.with_suffix(".pdf")
    if sibling.exists():
        return sibling
    variant = match_variant(path, config)
    if variant is None:
        return None
    built = (config.output_dir / variant.output_name).with_suffix(".pdf")
    if built.exists():
        return built
    return None


def sibling_pdf_pages(path: Path, config: Config) -> int | None:
    pdf = pdf_for(path, config)
    if pdf is None:
        return None
    try:
        return count_pdf_pages(pdf)
    except OSError:
        return None


@dataclass
class VerifyResult:
    path: Path
    ok: bool
    facts: list[str]
    keywords: list[str]
    warnings: list[str]
    words: int
    pages: int | None
    label: str


def verify_one(
    path: Path,
    source_raw: str,
    config: Config,
    *,
    extra_required: list[str] | None = None,
) -> VerifyResult:
    model = load_cv(path)
    text = model_text(model)
    variant = match_variant(path, config)
    lang = variant.lang if variant else detect_language(model)
    length = variant.length if variant else _length_from_name(path)
    canonical = variant is not None

    facts = fact_check(model, source_raw, extra_tech=config.extra_known_tech)
    required = list(extra_required or [])
    if config.person_name:
        required.append(config.person_name)
    if variant is not None:
        required.extend(config.required_by_variant.get(variant.id, []))
    keywords = keyword_check(text, required=required, forbidden=config.forbidden)

    warnings: list[str] = []
    if path.suffix.lower() == ".md":
        comments = re.findall(r"<!--(.*?)-->", path.read_text(encoding="utf-8"), re.DOTALL)
        warnings.extend(f"comment (not rendered): {comment.strip()}" for comment in comments)

    pages = sibling_pdf_pages(path, config)
    if pages is not None and length and pages > config.page_limits[length]:
        keywords.append(f"PDF has {pages} pages (max {config.page_limits[length]})")

    label = f"{length or '?'}-{lang}" + (" canonical" if canonical else "")
    return VerifyResult(
        path=path,
        ok=not facts and not keywords,
        facts=facts,
        keywords=keywords,
        warnings=warnings,
        words=len(text.split()),
        pages=pages,
        label=label,
    )


def format_result(result: VerifyResult, *, root: Path | None = None) -> list[str]:
    status = "OK" if result.ok else "FAIL"
    page_info = f" | pdf pages={result.pages}" if result.pages is not None else ""
    lines = [f"{display_path(result.path, root)}: {status} [{result.label}] | words={result.words}{page_info}"]
    lines.extend(f"  FACT: {fact}" for fact in result.facts)
    lines.extend(f"  {problem}" for problem in result.keywords)
    lines.extend(f"  WARN: {warning}" for warning in result.warnings)
    return lines


def verify_paths(
    paths: list[Path],
    source_raw: str,
    config: Config,
    *,
    extra_required: list[str] | None = None,
) -> tuple[bool, str]:
    lines: list[str] = []
    ok = True
    for path in paths:
        if not path.exists():
            lines.append(f"{path}: FAIL | file not found")
            ok = False
            continue
        result = verify_one(path, source_raw, config, extra_required=extra_required)
        lines.extend(format_result(result, root=config.root))
        ok = ok and result.ok
    lines.append("")
    lines.append("All checks passed." if ok else "Some checks FAILED.")
    return ok, "\n".join(lines)
