"""Cursor provider.

The Cursor SDK is TypeScript, so this runs the bundled Node script
``vendor/cursor_agent.mjs`` against a user-installed ``@cursor/sdk``.
The API key is passed on stdin and is not written to the workspace.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from cvgen.providers.base import ProviderError

_PACKAGE = Path(__file__).resolve().parents[1]
_SCRIPT = _PACKAGE / "vendor" / "cursor_agent.mjs"
_PACKAGE_JSON = _PACKAGE / "vendor" / "package.json"


def cursor_home() -> Path:
    override = os.environ.get("CVGEN_CURSOR_HOME")
    home = Path(override) if override else Path.home() / ".cache" / "cvgen" / "cursor-sdk"
    home.mkdir(parents=True, exist_ok=True)
    (home / "cursor_agent.mjs").write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    sdk = home / "node_modules" / "@cursor" / "sdk"
    if not sdk.exists():
        (home / "package.json").write_text(_PACKAGE_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    return home


def complete(
    *,
    model: str,
    api_key_env: str | None,
    system: str,
    user: str,
    cwd: Path,
) -> str:
    env_name = api_key_env or "CURSOR_API_KEY"
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ProviderError(
            f"{env_name} is not set. Create a key in the Cursor dashboard and export it. "
            "It is never stored in cvgen.toml."
        )
    node = os.environ.get("CVGEN_NODE") or shutil.which("node")
    if not node:
        raise ProviderError("Node.js 22 or newer is required for the Cursor provider, and node was not found on PATH.")
    home = cursor_home()
    if not (home / "node_modules" / "@cursor" / "sdk").exists():
        raise ProviderError(
            "The Cursor TypeScript SDK is not installed for cvgen. From a shell, run:\n"
            f"  npm install --prefix {home}\n"
            "That installs @cursor/sdk next to the bundled runner. Then retry."
        )
    payload = {
        "apiKey": api_key,
        "model": model,
        "cwd": str(cwd.resolve()),
        "prompt": f"{system}\n\n{user}",
    }
    try:
        completed = subprocess.run(
            [node, str(home / "cursor_agent.mjs")],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=600,
            cwd=str(cwd.resolve()),
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError("The Cursor agent timed out.", code=2) from exc
    if completed.returncode == 0 and completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        code = 2 if completed.returncode == 2 else 1
        raise ProviderError(f"Cursor agent failed: {detail}", code=code)
    if not completed.stdout.strip():
        raise ProviderError("Cursor agent returned an empty response.", code=2)
    return completed.stdout
