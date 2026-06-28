"""Base LLM Provider interface for Frozbot."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class TokenUsage:
    """Token usage information from an LLM request."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens


class LLMProvider(ABC):
    """Base class for LLM providers."""

    provider_name = "unknown"

    def supports_image_generation(self) -> bool:
        """Return whether this provider can generate images in the current config."""
        return False

    @abstractmethod
    async def generate_response(
        self,
        question: str,
        context_string: str,
        media_parts: Optional[list] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Generate a response from the LLM.

        Args:
            question: The user's question/prompt
            context_string: System context/instructions
            media_parts: Optional list of media (images, etc.)
            request_id: Optional queue/request identifier for logs

        Returns:
            Tuple of (response_text, token_usage) where response_text may be None if generation failed
        """
        pass

    @abstractmethod
    async def summarize_messages(
        self, serialized_messages: str, request_id: Optional[str] = None
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Summarize a set of messages.

        Args:
            serialized_messages: Serialized message history
            request_id: Optional queue/request identifier for logs

        Returns:
            Tuple of (summary_text, token_usage) where summary_text may be None if summarization failed
        """
        pass

    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        image_parts: Optional[list] = None,
        request_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[bytes]]:
        """
        Generate an image (and optional descriptive text).

        Args:
            prompt: Prompt text for image generation
            image_parts: Optional list of PIL Images as references
            request_id: Optional queue/request identifier for logs

        Returns:
            (description_text, image_bytes_png) where either may be None on failure
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is available/configured.

        Returns:
            True if provider is available, False otherwise
        """
        pass

    @abstractmethod
    def get_client(self):
        """
        Get the underlying client object (for compatibility with existing code).

        Returns:
            Provider-specific client object or None
        """
        pass
