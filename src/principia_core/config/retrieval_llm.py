"""
Helpers for configuring retrieval-specific LLM clients.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from principia_core.config.llm_profiles import infer_provider, resolve_main_llm_config


def resolve_retrieval_llm_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    active_profile: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Resolve LLM settings for retrieval tools.

    Retrieval tools first use explicit arguments, then retrieval-specific
    environment variables, then RETRIEVAL_LLM_ACTIVE_PROFILE if configured, and
    finally fall back to the agent-wide LLM config.
    """
    retrieval_profile_name = active_profile if active_profile is not None else os.getenv("RETRIEVAL_LLM_ACTIVE_PROFILE")
    retrieval_profile = (
        resolve_main_llm_config(active_profile=retrieval_profile_name) if retrieval_profile_name else None
    )
    main_config = resolve_main_llm_config()

    resolved_api_key = (
        api_key
        or os.getenv("RETRIEVAL_LLM_API_KEY")
        or (retrieval_profile.api_key if retrieval_profile else None)
        or main_config.api_key
    )
    resolved_base_url = (
        base_url
        or os.getenv("RETRIEVAL_LLM_API_BASE_URL")
        or (retrieval_profile.base_url if retrieval_profile else None)
        or main_config.base_url
    )
    resolved_model = (
        model
        or os.getenv("RETRIEVAL_LLM_MODEL")
        or (retrieval_profile.model if retrieval_profile else None)
        or main_config.model
        or "gpt-4"
    )
    explicit_provider = (
        provider
        or os.getenv("RETRIEVAL_LLM_PROVIDER")
        or (retrieval_profile.provider if retrieval_profile else None)
        or main_config.provider
    )
    resolved_provider = infer_provider(resolved_base_url, resolved_model, explicit_provider)

    return {
        "api_key": resolved_api_key,
        "base_url": resolved_base_url,
        "model": resolved_model,
        "provider": resolved_provider,
        "active_profile": retrieval_profile_name or main_config.active_profile,
    }
