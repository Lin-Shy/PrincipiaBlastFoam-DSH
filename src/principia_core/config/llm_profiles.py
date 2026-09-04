"""
Provider capability profiles for OpenAI-compatible chat models.

Many providers expose an OpenAI-like API but differ on thinking controls,
structured output modes, and tool-call message contracts. This module keeps
those differences out of agent logic and makes the runtime behavior explicit.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from principia_core.config.model_profiles import (
    get_model_profile,
    normalize_profile_id,
    resolve_profile_api_key,
)


STRUCTURED_OUTPUT_MODES = {"json_schema", "json_object", "prompt_only", "disabled"}
THINKING_MODES = {"auto", "enabled", "disabled", "passthrough"}


@dataclass(frozen=True)
class LLMProfile:
    provider: str
    model: str | None = None
    base_url: str | None = None
    structured_output: str = "prompt_only"
    thinking: str = "passthrough"
    thinking_disabled_extra_body: dict[str, Any] = field(default_factory=dict)
    thinking_enabled_extra_body: dict[str, Any] = field(default_factory=dict)
    reasoning_roundtrip: bool = False

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LLMRuntimeConfig:
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    provider: str | None = None
    model_provider: str | None = None
    active_profile: str | None = None
    profile_id: str | None = None
    profile_label: str | None = None
    api_key_env: str | None = None
    profile_metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "legacy"


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_profile_name(value: str | None) -> str:
    return (value or "").strip()


def _profile_env_prefix(profile_name: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in profile_name.strip().upper())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"LLM_PROFILE_{normalized}" if normalized else ""


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _config_from_active_profile(active_profile: str | None = None) -> LLMRuntimeConfig:
    profile_name = _normalize_profile_name(
        active_profile
        if active_profile is not None
        else os.getenv("PRINCIPIA_MODEL_PROFILE") or os.getenv("LLM_ACTIVE_PROFILE")
    )
    if not profile_name:
        return LLMRuntimeConfig()

    model_profile = get_model_profile(profile_name)
    if model_profile is not None:
        api_key, api_key_env = resolve_profile_api_key(model_profile)
        return LLMRuntimeConfig(
            api_key=api_key,
            model=model_profile.model,
            base_url=model_profile.base_url,
            provider=model_profile.provider,
            model_provider=model_profile.model_provider,
            active_profile=model_profile.id,
            profile_id=model_profile.id,
            profile_label=model_profile.display_name,
            api_key_env=api_key_env,
            profile_metadata=model_profile.public_metadata(selected_api_key_env=api_key_env),
            source="model_profile",
        )

    prefix = _profile_env_prefix(profile_name)
    if not prefix:
        return LLMRuntimeConfig(active_profile=profile_name)

    return LLMRuntimeConfig(
        api_key=_env_first(f"{prefix}_API_KEY"),
        model=_env_first(f"{prefix}_MODEL"),
        base_url=_env_first(f"{prefix}_API_BASE_URL", f"{prefix}_BASE_URL"),
        provider=_env_first(f"{prefix}_PROVIDER"),
        model_provider=_env_first(f"{prefix}_MODEL_PROVIDER") or "openai",
        active_profile=profile_name,
        profile_id=normalize_profile_id(profile_name),
        profile_label=profile_name,
        api_key_env=f"{prefix}_API_KEY",
        source="profile",
    )


def _model_provider_for(provider: str | None, explicit_model_provider: str | None = None) -> str | None:
    model_provider = _normalize(explicit_model_provider or os.getenv("PRINCIPIA_MODEL_PROVIDER") or os.getenv("LLM_MODEL_PROVIDER"))
    if model_provider:
        return model_provider
    normalized_provider = _normalize(provider)
    if normalized_provider in {"deepseek", "qwen", "glm", "minimax", "moonshot", "generic"}:
        return "openai"
    return normalized_provider or None


def resolve_main_llm_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    active_profile: str | None = None,
) -> LLMRuntimeConfig:
    """
    Resolve the main workflow LLM settings.

    Priority:
    1. Explicit function arguments, usually CLI arguments.
    2. The selected PRINCIPIA_MODEL_PROFILE registry entry.
    3. Legacy LLM_ACTIVE_PROFILE / LLM_PROFILE_* variables.
    4. Legacy LLM_* variables.

    The legacy active profile block uses variables such as
    LLM_PROFILE_DEEPSEEK_V4_FLASH_MODEL. Profile names are normalized to
    uppercase and non-alphanumeric characters become underscores.
    """
    profile_config = _config_from_active_profile(active_profile)

    resolved_api_key = api_key or profile_config.api_key or os.getenv("LLM_API_KEY")
    resolved_base_url = base_url or profile_config.base_url or os.getenv("LLM_API_BASE_URL")
    resolved_model = model or profile_config.model or os.getenv("LLM_MODEL")
    explicit_provider = provider or profile_config.provider or os.getenv("LLM_PROVIDER")
    resolved_provider = infer_provider(resolved_base_url, resolved_model, explicit_provider)
    resolved_model_provider = _model_provider_for(resolved_provider, profile_config.model_provider)
    source = profile_config.source if profile_config.active_profile else "legacy"

    return LLMRuntimeConfig(
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        provider=resolved_provider,
        model_provider=resolved_model_provider,
        active_profile=profile_config.active_profile,
        profile_id=profile_config.profile_id,
        profile_label=profile_config.profile_label,
        api_key_env=profile_config.api_key_env,
        profile_metadata=profile_config.profile_metadata,
        source=source,
    )


def _deep_merge(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(dict(left))
    for key, value in right.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _env_choice(name: str, allowed: set[str], default: str) -> str:
    value = _normalize(os.getenv(name))
    if not value:
        return default
    aliases = {
        "off": "disabled",
        "false": "disabled",
        "no": "disabled",
        "on": "enabled",
        "true": "enabled",
        "yes": "enabled",
        "schema": "json_schema",
        "json_schema": "json_schema",
        "json_object": "json_object",
        "json": "json_object",
        "prompt": "prompt_only",
        "prompt_only": "prompt_only",
        "none": "disabled",
    }
    value = aliases.get(value, value)
    if value not in allowed:
        print(f"LLM profile: ignoring unsupported {name}={value!r}; using {default!r}.")
        return default
    return value


def infer_provider(base_url: str | None, model: str | None, explicit_provider: str | None = None) -> str:
    provider = _normalize(explicit_provider or os.getenv("LLM_PROVIDER"))
    if provider:
        return provider

    source = f"{base_url or ''} {model or ''}".lower()
    if "deepseek" in source:
        return "deepseek"
    if "dashscope" in source or "aliyuncs" in source or "qwen" in source:
        return "qwen"
    if "bigmodel" in source or "z.ai" in source or "zhipu" in source or "glm" in source:
        return "glm"
    if "minimax" in source or "minimaxi" in source:
        return "minimax"
    if "moonshot" in source or "kimi" in source:
        return "moonshot"
    if "openai" in source or "api.openai.com" in source:
        return "openai"
    return "generic"


def _base_profile(provider: str, base_url: str | None, model: str | None) -> LLMProfile:
    if provider == "openai":
        return LLMProfile(provider=provider, model=model, base_url=base_url, structured_output="json_schema")
    if provider == "deepseek":
        return LLMProfile(
            provider=provider,
            model=model,
            base_url=base_url,
            structured_output="json_object",
            thinking="disabled",
            thinking_disabled_extra_body={"thinking": {"type": "disabled"}},
            thinking_enabled_extra_body={"thinking": {"type": "enabled"}},
        )
    if provider == "qwen":
        return LLMProfile(
            provider=provider,
            model=model,
            base_url=base_url,
            structured_output="json_object",
            thinking="disabled",
            thinking_disabled_extra_body={"enable_thinking": False},
            thinking_enabled_extra_body={"enable_thinking": True},
        )
    if provider == "glm":
        return LLMProfile(
            provider=provider,
            model=model,
            base_url=base_url,
            structured_output="json_object",
            thinking="disabled",
            thinking_disabled_extra_body={"thinking": {"type": "disabled"}},
            thinking_enabled_extra_body={"thinking": {"type": "enabled"}},
        )
    if provider == "minimax":
        return LLMProfile(
            provider=provider,
            model=model,
            base_url=base_url,
            structured_output="prompt_only",
            thinking="enabled",
            thinking_enabled_extra_body={"reasoning_split": True},
        )
    if provider == "moonshot":
        return LLMProfile(
            provider=provider,
            model=model,
            base_url=base_url,
            structured_output="json_object",
            thinking="disabled",
            thinking_disabled_extra_body={"thinking": {"type": "disabled"}},
            thinking_enabled_extra_body={"thinking": {"type": "enabled"}},
        )
    return LLMProfile(provider=provider, model=model, base_url=base_url, structured_output="prompt_only")


def resolve_llm_profile(base_url: str | None, model: str | None, provider: str | None = None) -> LLMProfile:
    provider = infer_provider(base_url, model, provider)
    profile = _base_profile(provider, base_url, model)

    thinking_override = _env_choice("LLM_THINKING", THINKING_MODES, "auto")
    structured_override = _env_choice("LLM_STRUCTURED_OUTPUT", STRUCTURED_OUTPUT_MODES | {"auto"}, "auto")

    thinking = profile.thinking if thinking_override == "auto" else thinking_override
    structured_output = profile.structured_output if structured_override == "auto" else structured_override

    roundtrip_env = _normalize(os.getenv("LLM_REASONING_ROUNDTRIP"))
    if roundtrip_env in {"1", "true", "yes", "on"}:
        reasoning_roundtrip = True
    elif roundtrip_env in {"0", "false", "no", "off"}:
        reasoning_roundtrip = False
    else:
        reasoning_roundtrip = profile.reasoning_roundtrip

    return LLMProfile(
        provider=profile.provider,
        model=model,
        base_url=base_url,
        structured_output=structured_output,
        thinking=thinking,
        thinking_disabled_extra_body=profile.thinking_disabled_extra_body,
        thinking_enabled_extra_body=profile.thinking_enabled_extra_body,
        reasoning_roundtrip=reasoning_roundtrip,
    )


def extra_body_for_profile(profile: LLMProfile) -> dict[str, Any]:
    if profile.thinking == "disabled":
        return copy.deepcopy(profile.thinking_disabled_extra_body)
    if profile.thinking == "enabled":
        return copy.deepcopy(profile.thinking_enabled_extra_body)
    return {}


def _parse_extra_body_env() -> dict[str, Any]:
    raw = os.getenv("LLM_EXTRA_BODY")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"LLM profile: ignoring invalid LLM_EXTRA_BODY JSON: {exc}")
        return {}
    if not isinstance(parsed, dict):
        print("LLM profile: ignoring LLM_EXTRA_BODY because it is not a JSON object.")
        return {}
    return parsed


def chat_openai_kwargs(
    *,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    provider: str | None = None,
    temperature: float | None = 0.1,
) -> dict[str, Any]:
    profile = resolve_llm_profile(base_url, model, provider)
    extra_body = _deep_merge(extra_body_for_profile(profile), _parse_extra_body_env())
    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "metadata": {"principia_llm_profile": profile.to_metadata()},
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    return kwargs


def profile_from_llm(llm: Any) -> LLMProfile:
    metadata = getattr(llm, "metadata", None)
    if isinstance(metadata, Mapping):
        raw_profile = metadata.get("principia_llm_profile")
        if isinstance(raw_profile, Mapping):
            return LLMProfile(
                provider=str(raw_profile.get("provider") or "generic"),
                model=raw_profile.get("model"),
                base_url=raw_profile.get("base_url"),
                structured_output=str(raw_profile.get("structured_output") or "prompt_only"),
                thinking=str(raw_profile.get("thinking") or "passthrough"),
                thinking_disabled_extra_body=dict(raw_profile.get("thinking_disabled_extra_body") or {}),
                thinking_enabled_extra_body=dict(raw_profile.get("thinking_enabled_extra_body") or {}),
                reasoning_roundtrip=bool(raw_profile.get("reasoning_roundtrip", False)),
            )

    model = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    return resolve_llm_profile(str(base_url) if base_url else None, str(model) if model else None)


def structured_output_mode(llm: Any) -> str:
    mode = _env_choice("LLM_STRUCTURED_OUTPUT", STRUCTURED_OUTPUT_MODES | {"auto"}, "auto")
    if mode != "auto":
        return mode
    profile = profile_from_llm(llm)
    if profile.structured_output in STRUCTURED_OUTPUT_MODES:
        return profile.structured_output
    return "prompt_only"
