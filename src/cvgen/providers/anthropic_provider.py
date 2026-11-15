"""Anthropic messages. Requires the cvgen[anthropic] extra."""

from __future__ import annotations

import os

from cvgen.providers.base import ProviderError, install_hint

try:
    import anthropic
except ImportError:
    anthropic = None


def complete(
    *,
    model: str,
    temperature: float,
    api_key_env: str | None,
    system: str,
    user: str,
) -> str:
    if anthropic is None:
        raise ProviderError(f"The anthropic extra is not installed. {install_hint('anthropic')}")
    env_name = api_key_env or "ANTHROPIC_API_KEY"
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ProviderError(f"{env_name} is not set.")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=16000,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Anthropic request failed: {exc}") from exc
    parts = [block.text for block in message.content if getattr(block, "text", None)]
    if not parts:
        raise ProviderError("Anthropic returned an empty response.", code=2)
    return "".join(parts)
