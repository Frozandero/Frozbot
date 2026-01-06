"""LLM Provider system for Frozbot."""

import os
from typing import Optional

from .base import LLMProvider
from .gemini import GeminiProvider


def get_provider() -> Optional[LLMProvider]:
    """
    Get the configured LLM provider based on environment variables.
    
    Returns:
        LLMProvider instance or None if no provider is configured.
    """
    provider_name = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        return GeminiProvider(api_key)
    
    # Future providers can be added here:
    # elif provider_name == "openai":
    #     api_key = os.getenv("OPENAI_API_KEY")
    #     if not api_key:
    #         return None
    #     return OpenAIProvider(api_key)
    
    print(f"[ERROR] Unknown LLM provider: {provider_name}")
    return None

