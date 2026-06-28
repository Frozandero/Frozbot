"""Gemini LLM Provider implementation."""

import asyncio
import base64
import concurrent.futures
import io
import os
from typing import Optional, Tuple

from PIL import Image

from google.genai import errors
from google import genai

from .base import LLMProvider, TokenUsage

URL_CONTEXT_TOOL = {"type": "url_context"}

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
                print(
                    f"[INFO] Trying model: {model_name} (attempt {i+1}/{len(models_to_try)})"
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

                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    interaction = await asyncio.wait_for(
                        loop.run_in_executor(executor, call_gemini_api),
                        timeout=30.0,  # 30 second timeout
                    )

                print(f"[INFO] Success with model: {model_name}")

                token_usage = _extract_token_usage(interaction)
                print(
                    f"[INFO] Token usage: {token_usage.input_tokens} input, {token_usage.output_tokens} output (total: {token_usage.total_tokens})"
                )

                if getattr(interaction, "output_text", None):
                    return interaction.output_text, token_usage
                else:
                    print(
                        f"[WARN] {model_name} returned interaction without output_text"
                    )
                    print(f"Interaction object type: {type(interaction)}")
                    continue

            except asyncio.TimeoutError:
                print(f"[WARN] Timeout for {model_name}, trying next model...")
                continue
            except errors.APIError as e:
                if e.code == 429:
                    print(f"[WARN] Quota exceeded for {model_name}, trying next model...")
                    continue
                elif e.code in [
                    500,
                    502,
                    503,
                    504,
                ]:  # Server errors that might be temporary
                    print(f"[INFO] Server error ({e.code}) for {model_name}, retrying...")
                    # For server errors, try the same model again once
                    try:
                        print(f"[INFO] Retrying {model_name} after server error...")
                        # Add a small delay before retry to avoid overwhelming the service
                        await asyncio.sleep(1)

                        def retry_gemini_api():
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

                        loop = asyncio.get_event_loop()
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            interaction = await asyncio.wait_for(
                                loop.run_in_executor(executor, retry_gemini_api),
                                timeout=30.0,
                            )
                        print(f"[INFO] Success with {model_name} on retry")

                        token_usage = _extract_token_usage(interaction)
                        print(
                            f"[INFO] Token usage: {token_usage.input_tokens} input, {token_usage.output_tokens} output (total: {token_usage.total_tokens})"
                        )

                        if getattr(interaction, "output_text", None):
                            return interaction.output_text, token_usage
                        else:
                            print(
                                f"[WARN] Warning: {model_name} retry returned interaction without output_text"
                            )
                            print(f"Interaction object type: {type(interaction)}")
                            print(f"Interaction object attributes: {dir(interaction)}")
                            continue
                    except Exception as retry_error:
                        print(
                            f"[ERROR] Retry failed for {model_name}: {str(retry_error)[:100]}..."
                        )
                        continue
                else:
                    # Non-quota, non-server error, log and try next model
                    error_msg = e.message if e.message else str(e)
                    print(
                        f"[ERROR] Non-quota error with {model_name}: {error_msg[:100]}... (code: {e.code})"
                    )
                    continue
            except Exception as e:
                print(f"[ERROR] Unexpected error with {model_name}: {str(e)[:100]}...")
                # Log the full error for debugging
                import traceback

                print(f"Full error details for {model_name}:")
                traceback.print_exc()
                continue

        # All models failed
        print("[ERROR] All models failed")
        print(f"Failed to get response for question: {question[:100]}...")

        # Log additional debugging information
        print("[INFO] Debugging info:")
        print(f"  - Total models attempted: {len(models_to_try)}")
        print(f"  - Client initialized: {client is not None}")
        if client:
            print(f"  - Client type: {type(client)}")

        return None, TokenUsage()

    async def summarize_messages(
        self, serialized_messages: str
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
            return await self.generate_response(prompt, context_instr, None)
        except Exception as e:
            print(f"Error summarizing messages: {e}")
            return None, TokenUsage()

    async def generate_image(
        self, prompt: str, image_parts: Optional[list] = None
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

                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    interaction = await asyncio.wait_for(
                        loop.run_in_executor(executor, call_gemini_image_api),
                        timeout=60.0,
                    )

                image_bytes = _extract_interaction_image_bytes(interaction)
                if image_bytes:
                    return getattr(interaction, "output_text", None), image_bytes

                print(
                    f"[WARN] Image generation with {model_name} returned no output image."
                )
                continue

            except asyncio.TimeoutError:
                print(f"[WARN] Image generation timed out for {model_name}.")
                continue
            except errors.APIError as e:
                if e.code == 429:
                    print(f"[WARN] Quota exceeded for {model_name}, trying next model...")
                    continue
                print(
                    f"[ERROR] Image generation API error with {model_name} ({e.code}): {str(e)[:200]}..."
                )
                continue
            except Exception as e:
                print(
                    f"[ERROR] Unexpected image generation error with {model_name}: {str(e)[:200]}..."
                )
                continue

        return None, None
