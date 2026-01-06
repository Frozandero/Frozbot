"""Base LLM Provider interface for Frozbot."""

from abc import ABC, abstractmethod
from typing import Optional


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def generate_response(
        self,
        question: str,
        context_string: str,
        media_parts: Optional[list] = None,
    ) -> Optional[str]:
        """
        Generate a response from the LLM.

        Args:
            question: The user's question/prompt
            context_string: System context/instructions
            media_parts: Optional list of media (images, etc.)

        Returns:
            Response text or None if generation failed
        """
        pass

    @abstractmethod
    async def summarize_messages(self, serialized_messages: str) -> Optional[str]:
        """
        Summarize a set of messages.

        Args:
            serialized_messages: Serialized message history

        Returns:
            Summary text or None if summarization failed
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
