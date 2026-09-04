from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_PROFILES_PATH = PROJECT_ROOT / "config" / "model_profiles.json"


@dataclass(frozen=True)
class ModelProfile:
    id: str
    provider: str
    model: str
    model_provider: str = "openai"
    base_url: str | None = None
    api_key_env: str | None = None
    legacy_api_key_env: str | None = None
    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def public_metadata(self, *, selected_api_key_env: str | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("legacy_api_key_env", None)
        payload["selected_api_key_env"] = selected_api_key_env or self.api_key_env
        return payload


def normalize_profile_id(value: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", (value or "").strip().lower())
    return "_".join(part for part in normalized.split("_") if part)


def model_profiles_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    env_path = os.getenv("PRINCIPIA_MODEL_PROFILES")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_MODEL_PROFILES_PATH


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def load_model_profiles(path: str | os.PathLike[str] | None = None) -> dict[str, ModelProfile]:
    profile_path = model_profiles_path(path)
    if not profile_path.exists():
        return {}
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    raw_profiles = raw.get("profiles", {})
    if not isinstance(raw_profiles, Mapping):
        raise ValueError(f"model profile registry has no profiles object: {profile_path}")

    profiles: dict[str, ModelProfile] = {}
    for raw_id, payload in raw_profiles.items():
        if not isinstance(payload, Mapping):
            raise ValueError(f"model profile {raw_id!r} must be an object")
        profile_id = normalize_profile_id(str(raw_id))
        provider = str(payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not profile_id or not provider or not model:
            raise ValueError(f"model profile {raw_id!r} must define provider and model")
        profiles[profile_id] = ModelProfile(
            id=profile_id,
            provider=provider,
            model=model,
            model_provider=str(payload.get("model_provider") or "openai").strip(),
            base_url=str(payload.get("base_url") or "").strip() or None,
            api_key_env=str(payload.get("api_key_env") or "").strip() or None,
            legacy_api_key_env=str(payload.get("legacy_api_key_env") or "").strip() or None,
            display_name=str(payload.get("display_name") or "").strip() or None,
            aliases=_as_tuple(payload.get("aliases")),
            metadata=dict(payload.get("metadata") or {}),
        )
    return profiles


def default_model_profile_id(path: str | os.PathLike[str] | None = None) -> str | None:
    profile_path = model_profiles_path(path)
    if not profile_path.exists():
        return None
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    default = raw.get("default_profile")
    return normalize_profile_id(str(default)) if default else None


def get_model_profile(
    profile_id: str | None,
    *,
    path: str | os.PathLike[str] | None = None,
) -> ModelProfile | None:
    normalized = normalize_profile_id(profile_id)
    if not normalized:
        return None
    profiles = load_model_profiles(path)
    if normalized in profiles:
        return profiles[normalized]
    for profile in profiles.values():
        aliases = {normalize_profile_id(alias) for alias in profile.aliases}
        aliases.add(normalize_profile_id(profile.display_name))
        aliases.add(normalize_profile_id(profile.model))
        if normalized in aliases:
            return profile
    return None


def resolve_profile_api_key(profile: ModelProfile) -> tuple[str | None, str | None]:
    for env_name in (profile.api_key_env, profile.legacy_api_key_env):
        if env_name and os.getenv(env_name):
            return os.getenv(env_name), env_name
    return None, profile.api_key_env or profile.legacy_api_key_env
