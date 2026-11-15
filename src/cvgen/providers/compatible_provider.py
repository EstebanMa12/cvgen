"""OpenAI-compatible HTTP APIs, including Ollama. Uses the standard library only."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from cvgen.providers.base import ProviderError


def _chat_url(base_url: str) -> str:
    """Accept a host, a /v1 root, or a full chat-completions URL."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    path = urllib.parse.urlparse(trimmed).path
    if path in {"", "/"}:
        trimmed += "/v1"
    return trimmed + "/chat/completions"


def complete(
    *,
    model: str,
    base_url: str,
    temperature: float,
    api_key_env: str | None,
    system: str,
    user: str,
    timeout: float = 300,
) -> str:
    if not base_url:
        raise ProviderError("This provider needs a base URL. Set tailor.base_url in cvgen.toml or pass --base-url.")
    url = _chat_url(base_url)
    body = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    env_name = api_key_env or ""
    api_key = os.environ.get(env_name, "").strip() if env_name else ""
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"Request to {url} failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"Request to {url} failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Request to {url} returned invalid JSON.") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"Unexpected response from {url}.", code=2) from exc
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("The model returned an empty response.", code=2)
    return content
