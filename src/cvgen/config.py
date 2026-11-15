"""Workspace configuration. API keys are never read from this file."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cvgen.layout import PAGE_LIMITS

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
}
_KEY_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_\-]{12,}|sk-ant-[A-Za-z0-9_\-]{12,}"
    r"|cursor_[A-Za-z0-9_\-]{12,}|AIza[0-9A-Za-z_\-]{12,})"
)
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ConfigError(Exception):
    pass


@dataclass
class Variant:
    id: str
    input_path: Path
    output_name: str
    length: str
    lang: str


@dataclass
class Config:
    root: Path
    config_path: Path | None
    person_name: str
    source_path: Path | None
    output_dir: Path
    tailored_dir: Path
    font: str = "Times New Roman"
    locale_es: str = "es"
    locale_en: str = "en-US"
    page_limits: dict[str, int] = field(default_factory=lambda: dict(PAGE_LIMITS))
    variants: list[Variant] = field(default_factory=list)
    provider: str = "openai"
    model: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    api_key_env: str | None = None
    forbidden: list[str] = field(default_factory=lambda: ["TODO", "lorem", "placeholder"])
    required_by_variant: dict[str, list[str]] = field(default_factory=dict)
    extra_known_tech: list[str] = field(default_factory=list)


def default_config(root: Path | None = None) -> Config:
    base = (root or Path.cwd()).resolve()
    return Config(
        root=base,
        config_path=None,
        person_name="",
        source_path=None,
        output_dir=base / "out",
        tailored_dir=base / "out" / "tailored",
    )


def find_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in [current, *current.parents]:
        candidate = directory / "cvgen.toml"
        if candidate.is_file():
            return candidate
    return None


def _reject_secrets(value: object, where: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEYS:
                raise ConfigError(
                    f"Refusing to read {where}{key} from the config file. "
                    "Set an environment variable instead."
                )
            _reject_secrets(item, f"{where}{key}.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{where}[{index}].")
        return
    if isinstance(value, str) and _KEY_VALUE.search(value):
        raise ConfigError(
            "Refusing to load a config file that contains an API key. "
            "Use an environment variable instead."
        )


def _as_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a path.")
    path = Path(value)
    return path if path.is_absolute() else root / path


def _string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{label} must be a list of strings.")
    return list(value)


def load_config(path: Path) -> Config:
    path = path.resolve()
    if not path.is_file():
        raise ConfigError(f"Config not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a TOML table.")
    _reject_secrets(data)

    root = path.parent
    person = data.get("person") or {}
    paths = data.get("paths") or {}
    build = data.get("build") or {}
    verify = data.get("verify") or {}
    tailor = data.get("tailor") or {}
    if not all(isinstance(table, dict) for table in (person, paths, build, verify, tailor)):
        raise ConfigError("person, paths, build, verify and tailor must be tables.")

    page_limits = dict(PAGE_LIMITS)
    for length, key in (("short", "short_max_pages"), ("extended", "extended_max_pages")):
        if key in build:
            raw = build[key]
            if not isinstance(raw, int) or raw < 1:
                raise ConfigError(f"build.{key} must be an integer of 1 or more.")
            page_limits[length] = raw

    temperature = tailor.get("temperature", 0.2)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ConfigError("tailor.temperature must be a number.")
    if not 0 <= float(temperature) <= 2:
        raise ConfigError("tailor.temperature must be between 0 and 2.")

    api_key_env = tailor.get("api_key_env")
    if api_key_env is not None:
        if not isinstance(api_key_env, str) or not _ENV_NAME.fullmatch(api_key_env):
            raise ConfigError(
                "tailor.api_key_env must be the name of an environment variable, not the key itself."
            )
        if _KEY_VALUE.search(api_key_env):
            raise ConfigError("tailor.api_key_env looks like an API key. Put the variable name there.")

    required_raw = verify.get("required") or {}
    if not isinstance(required_raw, dict):
        raise ConfigError("verify.required must be a table of variant id to keyword list.")
    required: dict[str, list[str]] = {}
    for key, value in required_raw.items():
        required[str(key)] = _string_list(value, f"verify.required.{key}")

    source = paths.get("source")
    config = Config(
        root=root,
        config_path=path,
        person_name=str(person.get("name") or "").strip(),
        source_path=_as_path(root, source, "paths.source") if source else None,
        output_dir=_as_path(root, paths.get("output_dir", "out"), "paths.output_dir"),
        tailored_dir=_as_path(root, paths.get("tailored_dir", "out/tailored"), "paths.tailored_dir"),
        font=str(build.get("font") or "Times New Roman"),
        locale_es=str(build.get("locale_es") or "es"),
        locale_en=str(build.get("locale_en") or "en-US"),
        page_limits=page_limits,
        provider=str(tailor.get("provider") or "openai"),
        model=str(tailor["model"]) if tailor.get("model") else None,
        base_url=str(tailor["base_url"]) if tailor.get("base_url") else None,
        temperature=float(temperature),
        api_key_env=api_key_env,
        forbidden=_string_list(verify.get("forbidden", ["TODO", "lorem", "placeholder"]), "verify.forbidden"),
        required_by_variant=required,
        extra_known_tech=_string_list(verify.get("extra_known_tech", []), "verify.extra_known_tech"),
    )

    seen: set[str] = set()
    for raw in data.get("variants") or []:
        if not isinstance(raw, dict):
            raise ConfigError("Each [[variants]] entry must be a table.")
        variant_id = str(raw.get("id") or "").strip()
        if not variant_id:
            raise ConfigError("A variant is missing id.")
        if variant_id in seen:
            raise ConfigError(f"Duplicate variant id {variant_id!r}.")
        seen.add(variant_id)
        length = str(raw.get("length") or "")
        lang = str(raw.get("lang") or "")
        if length not in PAGE_LIMITS:
            raise ConfigError(f"Variant {variant_id!r} length must be 'short' or 'extended'.")
        if lang not in {"es", "en"}:
            raise ConfigError(f"Variant {variant_id!r} lang must be 'es' or 'en'.")
        output_name = str(raw.get("output") or f"{variant_id}.docx")
        if not output_name.endswith(".docx"):
            output_name += ".docx"
        config.variants.append(
            Variant(
                id=variant_id,
                input_path=_as_path(root, raw.get("input"), f"variants.{variant_id}.input"),
                output_name=output_name,
                length=length,
                lang=lang,
            )
        )
    return config


def load_workspace(explicit: Path | None = None, *, cwd: Path | None = None) -> Config:
    """Load --config, else the nearest cvgen.toml, else defaults for this directory."""
    if explicit is not None:
        return load_config(explicit)
    found = find_config(cwd or Path.cwd())
    if found is not None:
        return load_config(found)
    return default_config(cwd or Path.cwd())
