"""OpenAI chat completions. Requires the cvgen[openai] extra."""

from __future__ import annotations

import os

from cvgen.providers.base import ProviderError, install_hint

try:
    import openai
except ImportError:
    openai = None


def complete(
    *,
    model: str,
    base_url: str | None,
    temperature: float,
    api_key_env: str | None,
    system: str,
    user: str,
) -> str:
    if openai is None:
        raise ProviderError(f"The openai extra is not installed. {install_hint('openai')}")
    env_name = api_key_env or "OPENAI_API_KEY"
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ProviderError(f"{env_name} is not set.")
    kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = openai.OpenAI(**kwargs)
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"OpenAI request failed: {exc}") from exc
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ProviderError("OpenAI returned an empty response.", code=2)
    return content
