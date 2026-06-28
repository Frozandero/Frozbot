"""xAI (Grok) LLM Provider implementation."""

import asyncio
import io
import base64
import logging
from typing import Optional, Tuple, TYPE_CHECKING

from PIL import Image

try:
    from xai_sdk import Client
    from xai_sdk.chat import user, system, image as xai_image
    from xai_sdk.tools import web_search

    XAI_SDK_AVAILABLE = True
except ImportError:
    XAI_SDK_AVAILABLE = False

from .base import LLMProvider, TokenUsage
from .execution import run_blocking_provider_call
from logging_utils import context_log_fields, text_log_fields, token_usage_log_fields

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from xai_sdk import Client as XAIClient
else:
    XAIClient = object


class XAIProvider(LLMProvider):
    """xAI (Grok) provider implementation."""

    provider_name = "xai"

    def __init__(self, api_key: str):
        """
        Initialize xAI provider.

        Args:
            api_key: xAI API key
        """
        self.api_key = api_key
        self._client: Optional[XAIClient] = None

    def _get_client(self) -> XAIClient:
        """Get or create xAI client."""
        if not XAI_SDK_AVAILABLE:
            raise ImportError(
                "xai_sdk is not installed. Install it with: pip install xai-sdk"
            )

        if not self._client:
            self._client = Client(
                api_key=self.api_key,
                timeout=3600,  # Longer timeout for reasoning models
            )
        return self._client

    def is_available(self) -> bool:
        """Check if xAI is available."""
        if not XAI_SDK_AVAILABLE:
            return False
        return self.api_key is not None and len(self.api_key) > 0

    def supports_image_generation(self) -> bool:
        """Return whether xAI image generation is available."""
        return self.is_available()

    def get_client(self):
        """Get the xAI client (for compatibility)."""
        if not self.is_available():
            return None
        try:
            return self._get_client()
        except Exception:
            return None

    async def generate_response(
        self,
        question: str,
        context_string: str,
        media_parts: Optional[list] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Generate a response using xAI Grok with reasoning.

        Args:
            question: The user's question
            context_string: System context/instructions
            media_parts: Optional list of PIL Images

        Returns:
            Tuple of (response_text, token_usage) where response_text may be None if generation failed
        """
        if not self.is_available():
            return None, TokenUsage()

        client = self._get_client()
        model_name = "grok-4-1-fast-reasoning"

        try:
            logger.info(
                "provider_model_attempt",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": model_name,
                    "operation": "generate_response",
                    "media_parts": len(media_parts or []),
                    **text_log_fields("question", question),
                    **context_log_fields(context_string),
                },
            )

            # Run the xAI API call in a thread to avoid blocking the event loop
            def call_xai_api():
                # Create chat with store_messages=False for image understanding (as per docs)
                # But for regular text, we can use store_messages=True for stateful interaction
                chat = client.chat.create(
                    model=model_name, store_messages=False, tools=[web_search()]
                )

                # Add system instruction
                chat.append(system(context_string))

                # Add user message with optional images
                if media_parts:
                    # For images, we need to convert PIL Images to base64 data URLs
                    content_parts = []
                    for pil_img in media_parts:
                        # Convert PIL Image to base64
                        img_buffer = io.BytesIO()
                        pil_img.convert("RGB").save(img_buffer, format="JPEG")
                        img_buffer.seek(0)
                        img_base64 = base64.b64encode(img_buffer.read()).decode("utf-8")
                        data_url = f"data:image/jpeg;base64,{img_base64}"

                        # Add image using xai_sdk's image helper
                        content_parts.append(
                            xai_image(image_url=data_url, detail="high")
                        )

                    # Add text question
                    content_parts.append(question)
                    chat.append(user(*content_parts))
                else:
                    chat.append(user(question))

                # Sample the response
                response = chat.sample()
                return response

            response = await run_blocking_provider_call(
                call_xai_api,
                provider=self.provider_name,
                model=model_name,
                operation="generate_response",
                timeout=60.0,
                request_id=request_id,
                retries=1,
            )

            # Extract token usage from response
            token_usage = TokenUsage()
            if hasattr(response, "usage"):
                usage = response.usage
                if hasattr(usage, "prompt_tokens") or hasattr(usage, "input_tokens"):
                    token_usage.input_tokens = getattr(
                        usage, "prompt_tokens", None
                    ) or getattr(usage, "input_tokens", 0)
                if hasattr(usage, "completion_tokens") or hasattr(
                    usage, "output_tokens"
                ):
                    token_usage.output_tokens = getattr(
                        usage, "completion_tokens", None
                    ) or getattr(usage, "output_tokens", 0)
                # Handle reasoning tokens if present
                if hasattr(usage, "reasoning_tokens"):
                    reasoning_tokens = getattr(usage, "reasoning_tokens", 0)
                    # Reasoning tokens are typically counted separately, add to input
                    token_usage.input_tokens += reasoning_tokens

                logger.info(
                    "provider_model_token_usage",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        **token_usage_log_fields(token_usage),
                    },
                )

            # Extract response text
            if hasattr(response, "content") and response.content:
                logger.info(
                    "provider_model_succeeded",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
                return response.content, token_usage
            elif hasattr(response, "text") and response.text:
                logger.info(
                    "provider_model_succeeded",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
                return response.text, token_usage
            else:
                logger.warning(
                    "provider_model_missing_response_text",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
                return None, token_usage

        except asyncio.TimeoutError:
            logger.warning(
                "provider_model_timeout",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": model_name,
                },
            )
            return None, TokenUsage()
        except Exception as e:
            logger.exception(
                "provider_model_failed",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": model_name,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200],
                },
            )
            return None, TokenUsage()

    async def summarize_messages(
        self, serialized_messages: str, request_id: Optional[str] = None
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Summarize a set of messages into 1–2 sentences using xAI Grok.

        Args:
            serialized_messages: Serialized message history

        Returns:
            Tuple of (summary_text, token_usage) where summary_text may be None if summarization failed
        """
        if not self.is_available():
            return None, TokenUsage()

        context_instr = (
            "You are summarizing a Discord channel's recent conversation for an assistant. "
            "Compress only. Do not speculate. Keep it to 1–2 sentences, focusing on the main topics, decisions, or questions. "
            "Include notable entities or links if critical."
        )
        prompt = (
            "Summarize the following messages in at most 2 sentences."
            "\n\nMessages:\n" + serialized_messages
        )
        try:
            return await self.generate_response(
                prompt, context_instr, None, request_id=request_id
            )
        except Exception as e:
            logger.exception(
                "provider_summarize_messages_failed",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "error_type": type(e).__name__,
                },
            )
            return None, TokenUsage()

    async def generate_image(
        self,
        prompt: str,
        image_parts: Optional[list] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Generate an image (and optional descriptive text) using xAI Grok image generation.

        Args:
            prompt: Prompt text
            image_parts: Optional list of PIL Images as references
                Note: xAI image generation API currently only supports text prompts,
                so reference images are not directly supported.

        Returns:
            Tuple of (description_text, image_bytes_png) where either may be None
        """
        if not self.is_available():
            return None, None

        client = self._get_client()
        model_name = "grok-2-image"

        # Note: xAI image generation API doesn't support reference images directly
        # If image_parts are provided, we could potentially describe them in the prompt
        # but for now we'll just use the text prompt
        enhanced_prompt = prompt
        if image_parts:
            logger.warning(
                "provider_image_reference_ignored",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": model_name,
                    "media_parts": len(image_parts),
                },
            )

        def call_xai_image_api():
            # Use the image generation endpoint (not chat endpoint)
            response = client.image.sample(
                model=model_name,
                prompt=enhanced_prompt,
                image_format="base64",  # Get base64 encoded image bytes
            )
            return response

        try:
            response = await run_blocking_provider_call(
                call_xai_image_api,
                provider=self.provider_name,
                model=model_name,
                operation="generate_image",
                timeout=120.0,
                request_id=request_id,
                retries=1,
            )

            # Extract revised prompt (description) and image bytes
            description: str = ""
            image_bytes: Optional[bytes] = None

            # Get revised prompt if available
            if hasattr(response, "prompt") and response.prompt:
                description = response.prompt

            # Get image bytes
            if hasattr(response, "image") and response.image:
                image_bytes = response.image
                if isinstance(image_bytes, str):
                    # If it's a base64 string, decode it
                    if image_bytes.startswith("data:image"):
                        # Handle data URL format
                        header, data = image_bytes.split(",", 1)
                        image_bytes = base64.b64decode(data)
                    else:
                        # Assume it's raw base64
                        image_bytes = base64.b64decode(image_bytes)
                elif isinstance(image_bytes, bytes):
                    # Already bytes, use as-is
                    pass
                else:
                    logger.warning(
                        "provider_image_unexpected_format",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "image_type": type(image_bytes).__name__,
                        },
                    )
                    image_bytes = None

            # Convert JPG to PNG if we got image bytes
            if image_bytes:
                try:
                    img = Image.open(io.BytesIO(image_bytes))
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="PNG")
                    buf.seek(0)
                    return description.strip() or None, buf.getvalue()
                except Exception as e:
                    logger.exception(
                        "provider_image_png_conversion_failed",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "error_type": type(e).__name__,
                        },
                    )
                    # Return raw bytes if conversion fails
                    return description.strip() or None, image_bytes

            return description.strip() or None, None

        except asyncio.TimeoutError:
            logger.warning(
                "provider_image_timeout",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": model_name,
                },
            )
            return None, None
        except Exception as e:
            logger.exception(
                "provider_image_failed",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": model_name,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200],
                },
            )
            return None, None
