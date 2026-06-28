"""Mistral AI provider implementation."""

import asyncio
import base64
import concurrent.futures
import io
import os
from typing import Any, Optional, Tuple

from PIL import Image

from .base import LLMProvider, TokenUsage

try:
    from mistralai.client import Mistral as _MistralClient

    MISTRAL_SDK_AVAILABLE = True
except ImportError:
    try:
        from mistralai import Mistral as _MistralClient

        MISTRAL_SDK_AVAILABLE = True
    except ImportError:
        _MistralClient = None
        MISTRAL_SDK_AVAILABLE = False


DEFAULT_MISTRAL_TEXT_MODELS = [
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
]


def _parse_model_list(raw_value: Optional[str], default_models: list[str]) -> list[str]:
    if not raw_value:
        return list(default_models)
    return [model.strip() for model in raw_value.split(",") if model.strip()]


def _get_value(obj: object, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _image_to_mistral_content(image: Image.Image) -> dict[str, str]:
    """Convert a PIL image into a Mistral image_url content block."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": f"data:image/jpeg;base64,{encoded}",
    }


def _build_user_content(question: str, media_parts: Optional[list]) -> object:
    if not media_parts:
        return question

    content_parts: list[object] = [{"type": "text", "text": question}]
    for media_part in media_parts:
        if isinstance(media_part, Image.Image):
            content_parts.append(_image_to_mistral_content(media_part))
        else:
            content_parts.append(media_part)
    return content_parts


def _extract_token_usage(response: object) -> TokenUsage:
    usage = _get_value(response, "usage")
    if usage is None:
        return TokenUsage()

    return TokenUsage(
        input_tokens=(
            _get_value(usage, "prompt_tokens")
            or _get_value(usage, "input_tokens")
            or 0
        ),
        output_tokens=(
            _get_value(usage, "completion_tokens")
            or _get_value(usage, "output_tokens")
            or 0
        ),
    )


def _content_to_text(content: object) -> Optional[str]:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for content_part in content:
            text = _get_value(content_part, "text")
            if text:
                text_parts.append(str(text))
        if text_parts:
            return "\n".join(text_parts)

    return None


def _extract_response_text(response: object) -> Optional[str]:
    choices = _get_value(response, "choices") or []
    if not choices:
        return None

    first_choice = choices[0]
    message = _get_value(first_choice, "message")
    if message is None:
        return None

    return _content_to_text(_get_value(message, "content"))


def _iter_content_chunks(content: object) -> list[object]:
    if content is None:
        return []
    if isinstance(content, list):
        return content
    return [content]


def _extract_image_generation_outputs(response: object) -> tuple[Optional[str], Optional[str]]:
    text_parts: list[str] = []
    file_id: Optional[str] = None

    for output in _get_value(response, "outputs") or []:
        for chunk in _iter_content_chunks(_get_value(output, "content")):
            chunk_text = _get_value(chunk, "text")
            if chunk_text:
                text_parts.append(str(chunk_text))

            chunk_file_id = _get_value(chunk, "file_id")
            if chunk_file_id:
                file_id = str(chunk_file_id)

    text = "\n".join(text_parts).strip() or None
    return text, file_id


def _downloaded_file_to_bytes(downloaded_file: object) -> Optional[bytes]:
    if isinstance(downloaded_file, bytes):
        return downloaded_file
    if isinstance(downloaded_file, bytearray):
        return bytes(downloaded_file)

    read = getattr(downloaded_file, "read", None)
    if callable(read):
        try:
            data = read()
            if isinstance(data, bytes):
                return data
        except Exception:
            pass

    try:
        content = _get_value(downloaded_file, "content")
        if isinstance(content, bytes):
            return content
    except Exception:
        pass

    return None


def _to_png_bytes(image_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception:
        return image_bytes


class MistralProvider(LLMProvider):
    """Mistral AI provider implementation."""

    provider_name = "mistral"

    def __init__(
        self,
        api_key: str,
        text_models: Optional[list[str]] = None,
        vision_models: Optional[list[str]] = None,
        image_agent_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        """
        Initialize Mistral provider.

        Args:
            api_key: Mistral API key.
            text_models: Optional text model fallback list.
            vision_models: Optional vision model fallback list.
            image_agent_id: Optional Mistral agent ID with image_generation enabled.
            timeout_seconds: Optional API timeout per model attempt.
        """
        self.api_key = api_key
        self.text_models = text_models or _parse_model_list(
            os.getenv("MISTRAL_TEXT_MODELS"),
            DEFAULT_MISTRAL_TEXT_MODELS,
        )
        self.vision_models = vision_models or _parse_model_list(
            os.getenv("MISTRAL_VISION_MODELS"),
            self.text_models,
        )
        self.image_agent_id = (
            image_agent_id
            if image_agent_id is not None
            else os.getenv("MISTRAL_IMAGE_AGENT_ID")
        )
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("MISTRAL_TIMEOUT_SECONDS", "60")
        )
        self._client: Optional[object] = None

    def _get_client(self):
        """Get or create Mistral client."""
        if self._client is not None:
            return self._client

        if not MISTRAL_SDK_AVAILABLE or _MistralClient is None:
            raise ImportError(
                "mistralai is not installed. Install it with: pip install mistralai"
            )

        self._client = _MistralClient(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        """Check if Mistral is available."""
        sdk_or_fake_client = MISTRAL_SDK_AVAILABLE or self._client is not None
        return sdk_or_fake_client and self.api_key is not None and len(self.api_key) > 0

    def supports_image_generation(self) -> bool:
        """Return whether Mistral image generation is configured."""
        return self.is_available() and bool(self.image_agent_id)

    def get_client(self):
        """Get the Mistral client."""
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
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Generate a response using Mistral chat completions.

        Args:
            question: The user's question.
            context_string: System context/instructions.
            media_parts: Optional list of PIL Images.

        Returns:
            Tuple of (response_text, token_usage) where response_text may be None if all models failed.
        """
        if not self.is_available():
            return None, TokenUsage()

        client = self._get_client()
        models_to_try = self.vision_models if media_parts else self.text_models

        messages = [
            {"role": "system", "content": context_string},
            {"role": "user", "content": _build_user_content(question, media_parts)},
        ]

        for i, model_name in enumerate(models_to_try):
            try:
                print(
                    f"[INFO] Trying Mistral model: {model_name} "
                    f"(attempt {i+1}/{len(models_to_try)})"
                )

                def call_mistral_api():
                    return client.chat.complete(
                        model=model_name,
                        messages=messages,
                        temperature=0.9,
                    )

                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    response = await asyncio.wait_for(
                        loop.run_in_executor(executor, call_mistral_api),
                        timeout=self.timeout_seconds,
                    )

                token_usage = _extract_token_usage(response)
                print(
                    f"[INFO] Token usage: {token_usage.input_tokens} input, "
                    f"{token_usage.output_tokens} output "
                    f"(total: {token_usage.total_tokens})"
                )

                response_text = _extract_response_text(response)
                if response_text:
                    print(f"[INFO] Success with Mistral model: {model_name}")
                    return response_text, token_usage

                print(
                    f"[WARN] Mistral model {model_name} returned no response text"
                )
                continue

            except asyncio.TimeoutError:
                print(f"[WARN] Timeout for Mistral model {model_name}")
                continue
            except Exception as e:
                status_code = (
                    _get_value(e, "status_code")
                    or _get_value(e, "code")
                    or _get_value(e, "status")
                )
                status_suffix = f" ({status_code})" if status_code else ""
                print(
                    f"[ERROR] Mistral model {model_name} failed"
                    f"{status_suffix}: "
                    f"{str(e)[:200]}..."
                )
                continue

        print("[ERROR] All Mistral models failed")
        return None, TokenUsage()

    async def summarize_messages(
        self, serialized_messages: str
    ) -> Tuple[Optional[str], TokenUsage]:
        """
        Summarize a set of messages into 1-2 sentences using Mistral.

        Args:
            serialized_messages: Serialized message history.

        Returns:
            Tuple of (summary_text, token_usage) where summary_text may be None if summarization failed.
        """
        if not self.is_available():
            return None, TokenUsage()

        context_instr = (
            "You are summarizing a Discord channel's recent conversation for an assistant. "
            "Compress only. Do not speculate. Keep it to 1-2 sentences, focusing on the main topics, decisions, or questions. "
            "Include notable entities or links if critical."
        )
        prompt = (
            "Summarize the following messages in at most 2 sentences."
            "\n\nMessages:\n" + serialized_messages
        )
        try:
            return await self.generate_response(prompt, context_instr, None)
        except Exception as e:
            print(f"Error summarizing messages with Mistral: {e}")
            return None, TokenUsage()

    async def generate_image(
        self, prompt: str, image_parts: Optional[list] = None
    ) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Generate an image through a configured Mistral image-generation agent.

        Args:
            prompt: Prompt text.
            image_parts: Optional reference images. Mistral image-generation agents currently use the text prompt only.

        Returns:
            Tuple of (description_text, image_bytes_png) where either may be None.
        """
        if not self.supports_image_generation():
            print(
                "[WARN] Mistral image generation requires MISTRAL_IMAGE_AGENT_ID "
                "for an agent with the image_generation tool enabled."
            )
            return None, None

        if image_parts:
            print(
                "[WARN] Mistral image generation agent does not use reference images. "
                "Using text prompt only."
            )

        client = self._get_client()

        try:
            def call_mistral_image_api():
                return client.beta.conversations.start(
                    agent_id=self.image_agent_id,
                    inputs=prompt,
                    store=False,
                )

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                response = await asyncio.wait_for(
                    loop.run_in_executor(executor, call_mistral_image_api),
                    timeout=max(self.timeout_seconds, 120.0),
                )

            description, file_id = _extract_image_generation_outputs(response)
            if not file_id:
                print("[WARN] Mistral image generation returned no file_id")
                return description, None

            def download_image_file():
                return client.files.download(file_id=file_id)

            with concurrent.futures.ThreadPoolExecutor() as executor:
                downloaded_file = await asyncio.wait_for(
                    loop.run_in_executor(executor, download_image_file),
                    timeout=self.timeout_seconds,
                )

            image_bytes = _downloaded_file_to_bytes(downloaded_file)
            if not image_bytes:
                print("[WARN] Mistral image file download returned no bytes")
                return description, None

            return description, _to_png_bytes(image_bytes)

        except asyncio.TimeoutError:
            print("[WARN] Mistral image generation timed out")
            return None, None
        except Exception as e:
            print(f"[ERROR] Mistral image generation error: {str(e)[:200]}...")
            return None, None
