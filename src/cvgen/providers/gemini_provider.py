"""Google Gemini. Requires the cvgen[gemini] extra (package google-genai)."""

from __future__ import annotations

import os

from cvgen.providers.base import ProviderError, install_hint

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


def complete(
    *,
    model: str,
    temperature: float,
    api_key_env: str | None,
    system: str,
    user: str,
) -> str:
    if genai is None or types is None:
        raise ProviderError(f"The gemini extra is not installed. {install_hint('gemini')}")
    env_name = api_key_env or "GEMINI_API_KEY"
    api_key = os.environ.get(env_name, "").strip()
    if not api_key and not api_key_env:
        api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
        env_name = "GEMINI_API_KEY or GOOGLE_API_KEY"
    if not api_key:
        raise ProviderError(f"{env_name} is not set.")
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system,
            ),
        )
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Gemini request failed: {exc}") from exc
    text = getattr(response, "text", None)
    if not text or not str(text).strip():
        raise ProviderError("Gemini returned an empty response.", code=2)
    return str(text)
