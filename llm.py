"""LLM integration module for Frozbot - uses provider system."""

from typing import Optional

from llm_providers import get_provider

# Global provider instance (lazy-loaded)
_LLM_PROVIDER: Optional[object] = None


def _get_provider():
    """Get or initialize the LLM provider."""
    global _LLM_PROVIDER
    if _LLM_PROVIDER is None:
        _LLM_PROVIDER = get_provider()
    return _LLM_PROVIDER


def get_gemini_client():
    """
    Get the Gemini client (for backward compatibility).
    
    Note: This function name is kept for compatibility but now works with any provider.
    Returns None if no provider is configured.
    """
    provider = _get_provider()
    if provider:
        return provider.get_client()
    return None


async def try_gemini_models(
    question: str, context_string: str, media_parts: Optional[list]
) -> Optional[str]:
    """
    Generate a response using the configured LLM provider.
    
    Note: Function name kept for backward compatibility but works with any provider.
    
    Args:
        question: The user's question
        context_string: System context/instructions
        media_parts: Optional list of media (images, etc.)
        
    Returns:
        Response text or None if generation failed
    """
    provider = _get_provider()
    if not provider:
        return None
    
    return await provider.generate_response(question, context_string, media_parts)


async def summarize_messages_with_gemini(serialized_messages: str) -> Optional[str]:
    """
    Summarize a set of messages into 1–2 sentences using the configured LLM provider.
    
    Note: Function name kept for backward compatibility but works with any provider.
    
    Args:
        serialized_messages: Serialized message history
        
    Returns:
        Summary text or None if summarization failed
    """
    provider = _get_provider()
    if not provider:
        return None
    
    return await provider.summarize_messages(serialized_messages)
