"""Fail if seed personal names or employers appear anywhere in the working tree."""

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "out",
    ".mypy_cache",
}
# Encoded so the plaintext terms are not stored in this file.
_ENCODED = (
    "ZXN0ZWJhbg==",
    "cG9ydGlsbG8=",
    "YW50aW9xdWlh",
    "ZWFmaXQ=",
    "YXZhbnphdGVjaA==",
    "YXRlbmVh",
    "Y29wbmlh",
    "aWNlc2k=",
)


def _banned() -> list[str]:
    return [base64.b64decode(item).decode("utf-8") for item in _ENCODED]


def test_repository_has_no_seed_personal_data():
    banned = _banned()
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        folded = text.casefold()
        for term in banned:
            if term in folded:
                hits.append(f"{path.relative_to(ROOT)} contains a disallowed seed term")
                break
    assert hits == []
