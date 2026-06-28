"""Provider-neutral LLM integration module for Frozbot."""

from typing import Optional, Tuple

from llm_providers import get_provider
from llm_providers.base import TokenUsage

# Global provider instance (lazy-loaded)
_LLM_PROVIDER: Optional[object] = None


def _get_provider():
    """Get or initialize the LLM provider."""
    global _LLM_PROVIDER
    if _LLM_PROVIDER is None:
        _LLM_PROVIDER = get_provider()
    return _LLM_PROVIDER


def get_llm_client():
    """Get the configured provider client, or None when no provider is configured."""
    provider = _get_provider()
    if provider:
        return provider.get_client()
    return None


def get_llm_provider():
    """Return the underlying LLM provider (or None)."""
    return _get_provider()


def provider_supports_image_generation() -> bool:
    """Return whether the configured provider can generate images."""
    provider = _get_provider()
    return bool(provider and provider.supports_image_generation())


async def generate_response_with_llm(
    question: str, context_string: str, media_parts: Optional[list]
) -> Tuple[Optional[str], TokenUsage]:
    """
    Generate a response using the configured LLM provider.

    Args:
        question: The user's question
        context_string: System context/instructions
        media_parts: Optional list of media (images, etc.)

    Returns:
        Tuple of (response_text, token_usage) where response_text may be None if generation failed
    """
    provider = _get_provider()
    if not provider:
        return None, TokenUsage()

    return await provider.generate_response(question, context_string, media_parts)


async def summarize_messages_with_llm(
    serialized_messages: str,
) -> Tuple[Optional[str], TokenUsage]:
    """
    Summarize a set of messages into 1–2 sentences using the configured LLM provider.

    Args:
        serialized_messages: Serialized message history

    Returns:
        Tuple of (summary_text, token_usage) where summary_text may be None if summarization failed
    """
    provider = _get_provider()
    if not provider:
        return None, TokenUsage()

    return await provider.summarize_messages(serialized_messages)


async def generate_image_with_llm(
    prompt: str, image_parts: Optional[list] = None
) -> Tuple[Optional[str], Optional[bytes]]:
    """
    Generate an image using the configured LLM provider (if supported).

    Args:
        prompt: Prompt text
        image_parts: Optional list of PIL Images as references

    Returns:
        (description_text, image_bytes_png) where either may be None on failure
    """
    provider = _get_provider()
    if not provider or not provider.supports_image_generation():
        return None, None

    return await provider.generate_image(prompt, image_parts)
