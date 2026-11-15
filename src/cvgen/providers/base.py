"""Provider names, defaults and errors. Keys come from the environment."""

from __future__ import annotations

from typing import Literal, get_args

from cvgen.config import ConfigError

ProviderName = Literal["openai", "anthropic", "gemini", "cursor", "ollama", "openai-compatible"]

DEFAULT_MODELS: dict[ProviderName, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "gemini": "gemini-2.5-flash",
    "cursor": "composer-2",
    "ollama": "llama3.1",
    "openai-compatible": "llama3.1",
}

DEFAULT_BASE_URLS: dict[str, str] = {
    "ollama": "http://127.0.0.1:11434/v1",
}

ENV_VARS: dict[ProviderName, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "cursor": "CURSOR_API_KEY",
    "ollama": "",
    "openai-compatible": "OPENAI_API_KEY",
}

_ALIASES = {
    "google": "gemini",
    "google-gemini": "gemini",
    "local": "ollama",
}


class ProviderError(Exception):
    def __init__(self, message: str, *, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def canonicalize(name: str) -> ProviderName:
    key = name.strip().lower().replace("_", "-")
    key = _ALIASES.get(key, key)
    allowed = get_args(ProviderName)
    if key not in allowed:
        choices = ", ".join(allowed)
        raise ConfigError(f"Unknown provider {name!r}. Choose from: {choices}.")
    return key  # type: ignore[return-value]


def install_hint(provider: ProviderName) -> str:
    extras = {
        "openai": "openai",
        "anthropic": "anthropic",
        "gemini": "gemini",
    }
    extra = extras.get(provider)
    if extra is None:
        return ""
    return f"Install it with: pip install 'cvgen[{extra}]'  (or pipx install '.[{extra}]' from a checkout)."
