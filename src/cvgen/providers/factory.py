"""Dispatch a completion request to the selected provider."""

from __future__ import annotations

from pathlib import Path
from typing import assert_never

from cvgen.providers.anthropic_provider import complete as anthropic_complete
from cvgen.providers.base import DEFAULT_BASE_URLS, ProviderName
from cvgen.providers.compatible_provider import complete as compatible_complete
from cvgen.providers.cursor_provider import complete as cursor_complete
from cvgen.providers.gemini_provider import complete as gemini_complete
from cvgen.providers.openai_provider import complete as openai_complete


def run_completion(
    provider: ProviderName,
    *,
    model: str,
    base_url: str | None,
    temperature: float,
    api_key_env: str | None,
    system: str,
    user: str,
    cwd: Path,
) -> str:
    match provider:
        case "openai":
            return openai_complete(
                model=model,
                base_url=base_url,
                temperature=temperature,
                api_key_env=api_key_env,
                system=system,
                user=user,
            )
        case "anthropic":
            return anthropic_complete(
                model=model,
                temperature=temperature,
                api_key_env=api_key_env,
                system=system,
                user=user,
            )
        case "gemini":
            return gemini_complete(
                model=model,
                temperature=temperature,
                api_key_env=api_key_env,
                system=system,
                user=user,
            )
        case "cursor":
            return cursor_complete(
                model=model,
                api_key_env=api_key_env,
                system=system,
                user=user,
                cwd=cwd,
            )
        case "ollama":
            return compatible_complete(
                model=model,
                base_url=base_url or DEFAULT_BASE_URLS["ollama"],
                temperature=temperature,
                api_key_env=api_key_env,
                system=system,
                user=user,
            )
        case "openai-compatible":
            return compatible_complete(
                model=model,
                base_url=base_url or "",
                temperature=temperature,
                api_key_env=api_key_env,
                system=system,
                user=user,
            )
        case _:
            assert_never(provider)
