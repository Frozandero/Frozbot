"""LLM Provider system for Frozbot."""

import os
from dataclasses import dataclass
from typing import Callable, Optional

from .base import LLMProvider, TokenUsage


@dataclass(frozen=True)
class ProviderRegistration:
    """Configuration needed to instantiate an LLM provider."""

    name: str
    api_key_env: str
    factory: Callable[[str], LLMProvider]


def _create_gemini_provider(api_key: str) -> LLMProvider:
    from .gemini import GeminiProvider

    return GeminiProvider(api_key)


def _create_mistral_provider(api_key: str) -> LLMProvider:
    from .mistral import MistralProvider

    return MistralProvider(api_key)


def _create_xai_provider(api_key: str) -> LLMProvider:
    from .xai import XAIProvider

    return XAIProvider(api_key)


PROVIDER_REGISTRY: dict[str, ProviderRegistration] = {
    "gemini": ProviderRegistration(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        factory=_create_gemini_provider,
    ),
    "mistral": ProviderRegistration(
        name="mistral",
        api_key_env="MISTRAL_API_KEY",
        factory=_create_mistral_provider,
    ),
    "xai": ProviderRegistration(
        name="xai",
        api_key_env="XAI_API_KEY",
        factory=_create_xai_provider,
    ),
}


def available_provider_names() -> tuple[str, ...]:
    """Return configured provider names."""
    return tuple(PROVIDER_REGISTRY)


def get_provider() -> Optional[LLMProvider]:
    """
    Get the configured LLM provider based on environment variables.

    Returns:
        LLMProvider instance or None if no provider is configured.
    """
    provider_name = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    registration = PROVIDER_REGISTRY.get(provider_name)
    if registration is None:
        supported = ", ".join(available_provider_names())
        print(
            f"[ERROR] Unknown LLM provider: {provider_name}. "
            f"Supported providers: {supported}"
        )
        return None

    api_key = os.getenv(registration.api_key_env)
    if not api_key:
        print(
            f"[ERROR] Missing {registration.api_key_env} for "
            f"LLM_PROVIDER={provider_name}"
        )
        return None

    return registration.factory(api_key)
