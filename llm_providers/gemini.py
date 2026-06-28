"""Gemini LLM Provider implementation."""

import asyncio
import base64
import io
import logging
import os
from typing import Optional, Tuple

from PIL import Image

from google.genai import errors
from google import genai

from .base import LLMProvider, TokenUsage
from .execution import run_blocking_provider_call
from logging_utils import context_log_fields, text_log_fields, token_usage_log_fields

URL_CONTEXT_TOOL = {"type": "url_context"}
logger = logging.getLogger(__name__)

DEFAULT_TEXT_IMAGE_MODEL_SPECS = [
    "gemini-3.5-flash:low",
    "gemini-3-flash-preview:low",
    "gemini-2.5-pro:low",
    "gemini-2.5-flash:low",
    "gemini-3.1-flash-lite:minimal",
    "gemini-2.5-flash-lite:minimal",
]


def _parse_text_model_specs(raw_value: Optional[str]) -> list[tuple[str, str]]:
    specs = raw_value.split(",") if raw_value else DEFAULT_TEXT_IMAGE_MODEL_SPECS
    models = []
    for spec in specs:
        parts = spec.strip().split(":", 1)
        if not parts[0]:
            continue
        thinking_level = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "low"
        models.append((parts[0].strip(), thinking_level))
    return models


GEMINI_TEXT_IMAGE_MODELS = _parse_text_model_specs(os.getenv("GEMINI_TEXT_IMAGE_MODELS"))

GEMINI_IMAGE_MODELS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_IMAGE_MODELS",
        "gemini-3.1-flash-image,gemini-2.5-flash-image",
    ).split(",")
    if model.strip()
]


def _image_to_interaction_block(image: Image.Image) -> dict:
    """Convert a PIL image into an Interactions API image content block."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return {
        "type": "image",
        "data": base64.b64encode(buffer.getvalue()).decode("utf-8"),
        "mime_type": "image/png",
    }


def _build_interaction_input(prompt: str, media_parts: Optional[list]) -> object:
    if not media_parts:
        return prompt

    input_parts = []
    for media_part in media_parts:
        if isinstance(media_part, Image.Image):
            input_parts.append(_image_to_interaction_block(media_part))
        else:
            input_parts.append(media_part)
    input_parts.append({"type": "text", "text": prompt})
    return input_parts


def _extract_token_usage(interaction) -> TokenUsage:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return TokenUsage()

    return TokenUsage(
        input_tokens=(
            getattr(usage, "total_input_tokens", None)
            or getattr(usage, "input_tokens", None)
            or 0
        ),
        output_tokens=(
            getattr(usage, "total_output_tokens", None)
            or getattr(usage, "output_tokens", None)
            or 0
        ),
    )


def _extract_interaction_image_bytes(interaction) -> Optional[bytes]:
    output_image = getattr(interaction, "output_image", None)
    if output_image is not None and getattr(output_image, "data", None):
        return base64.b64decode(output_image.data)

    for step in getattr(interaction, "steps", []) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for content_block in getattr(step, "content", []) or []:
            if getattr(content_block, "type", None) == "image":
                data = getattr(content_block, "data", None)
                if data:
                    return base64.b64decode(data)
    return None


def _is_retryable_gemini_error(exc: BaseException) -> bool:
    return isinstance(exc, errors.APIError) and getattr(exc, "code", None) in {
        500,
        502,
        503,
        504,
    }


class GeminiProvider(LLMProvider):
    """Gemini AI provider implementation."""

    provider_name = "gemini"

    def __init__(self, api_key: str):
        """
        Initialize Gemini provider.

        Args:
            api_key: Gemini API key
        """
        self.api_key = api_key
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        """Get or create Gemini client."""
        if not self._client:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        """Check if Gemini is available."""
        return self.api_key is not None and len(self.api_key) > 0

    def supports_image_generation(self) -> bool:
        """Return whether Gemini image generation is configured."""
        return bool(GEMINI_IMAGE_MODELS)

    def get_client(self):
        """Get the Gemini client (for compatibility)."""
        if not self.is_available():
            return None
        return self._get_client()

    async def generate_response(
        self,
        question: str,
        context_string: str,
        media_parts: Optional[list] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Generate a response using Gemini with model fallback.

        Args:
            question: The user's question
            context_string: System context/instructions
            media_parts: Optional list of PIL Images

        Returns:
            Tuple of (response_text, token_usage) where response_text may be None if all models failed
        """
        if not self.is_available():
            return None, TokenUsage()

        models_to_try = GEMINI_TEXT_IMAGE_MODELS

        client = self._get_client()

        for i, (model_name, thinking_level) in enumerate(models_to_try):
            try:
                logger.info(
                    "provider_model_attempt",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        "operation": "generate_response",
                        "model_attempt": i + 1,
                        "model_count": len(models_to_try),
                        "media_parts": len(media_parts or []),
                        **text_log_fields("question", question),
                        **context_log_fields(context_string),
                    },
                )

                def call_gemini_api():
                    return client.interactions.create(
                        model=model_name,
                        input=_build_interaction_input(question, media_parts),
                        system_instruction=context_string,
                        generation_config={
                            "thinking_level": thinking_level,
                            "temperature": 0.9,
                        },
                        tools=[URL_CONTEXT_TOOL],
                        store=False,
                    )

                interaction = await run_blocking_provider_call(
                    call_gemini_api,
                    provider=self.provider_name,
                    model=model_name,
                    operation="generate_response",
                    timeout=30.0,
                    request_id=request_id,
                    retries=1,
                    is_retryable=_is_retryable_gemini_error,
                )

                token_usage = _extract_token_usage(interaction)
                logger.info(
                    "provider_model_succeeded",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        **token_usage_log_fields(token_usage),
                    },
                )

                if getattr(interaction, "output_text", None):
                    return interaction.output_text, token_usage
                else:
                    logger.warning(
                        "provider_model_missing_output_text",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "interaction_type": type(interaction).__name__,
                        },
                    )
                    continue

            except asyncio.TimeoutError:
                logger.warning(
                    "provider_model_timeout",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
                continue
            except errors.APIError as e:
                if e.code == 429:
                    logger.warning(
                        "provider_model_quota_exceeded",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "status_code": e.code,
                        },
                    )
                    continue
                else:
                    error_msg = e.message if e.message else str(e)
                    logger.error(
                        "provider_model_api_error",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "status_code": e.code,
                            "error_message": error_msg[:200],
                        },
                    )
                    continue
            except Exception as e:
                logger.exception(
                    "provider_model_unexpected_error",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        "error_type": type(e).__name__,
                    },
                )
                continue

        # All models failed
        logger.error(
            "provider_all_models_failed",
            extra={
                "request_id": request_id,
                "provider": self.provider_name,
                "model_count": len(models_to_try),
                "client_initialized": client is not None,
                "client_type": type(client).__name__ if client else None,
                **text_log_fields("question", question),
            },
        )

        return None, TokenUsage()

    async def summarize_messages(
        self, serialized_messages: str, request_id: Optional[str] = None
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Summarize a set of messages into 1–2 sentences using Gemini.

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
        Generate an image (and optional descriptive text) using Gemini.

        Args:
            prompt: Prompt text
            image_parts: Optional list of PIL Images as references

        Returns:
            Tuple of (description_text, image_bytes_png) where either may be None
        """
        if not self.is_available():
            return None, None

        client = self._get_client()
        for model_name in GEMINI_IMAGE_MODELS:
            try:
                def call_gemini_image_api():
                    return client.interactions.create(
                        model=model_name,
                        input=_build_interaction_input(prompt, image_parts),
                        response_format=[
                            {"type": "text"},
                            {"type": "image", "mime_type": "image/png"},
                        ],
                        store=False,
                    )

                interaction = await run_blocking_provider_call(
                    call_gemini_image_api,
                    provider=self.provider_name,
                    model=model_name,
                    operation="generate_image",
                    timeout=60.0,
                    request_id=request_id,
                    retries=1,
                    is_retryable=_is_retryable_gemini_error,
                )

                image_bytes = _extract_interaction_image_bytes(interaction)
                if image_bytes:
                    return getattr(interaction, "output_text", None), image_bytes

                logger.warning(
                    "provider_image_missing_output",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
                continue

            except asyncio.TimeoutError:
                logger.warning(
                    "provider_image_timeout",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
                continue
            except errors.APIError as e:
                if e.code == 429:
                    logger.warning(
                        "provider_image_quota_exceeded",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "status_code": e.code,
                        },
                    )
                    continue
                logger.error(
                    "provider_image_api_error",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        "status_code": e.code,
                        "error_message": str(e)[:200],
                    },
                )
                continue
            except Exception as e:
                logger.exception(
                    "provider_image_unexpected_error",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        "error_type": type(e).__name__,
                    },
                )
                continue

        return None, None
