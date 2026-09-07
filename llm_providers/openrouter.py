"""OpenRouter LLM provider implementation."""

import asyncio
import base64
import io
import logging
import os
from typing import Any, Optional, Tuple

from PIL import Image

try:
    from openrouter import OpenRouter as _OpenRouterClient

    OPENROUTER_SDK_AVAILABLE = True
except ImportError:
    _OpenRouterClient = None
    OPENROUTER_SDK_AVAILABLE = False

from .base import BinaryMediaPart, LLMProvider, TokenUsage
from logging_utils import context_log_fields, text_log_fields, token_usage_log_fields

logger = logging.getLogger(__name__)


DEFAULT_OPENROUTER_TEXT_MODELS = ["minimax/minimax-m3:free"]
DEFAULT_OPENROUTER_MULTIMODAL_MODELS = ["minimax/minimax-m3:free"]
DEFAULT_OPENROUTER_AUDIO_MODELS: list[str] = []
OPENROUTER_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}

_AUDIO_FORMATS = {
    "audio/aac": "aac",
    "audio/aiff": "aiff",
    "audio/flac": "flac",
    "audio/m4a": "m4a",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-aiff": "aiff",
    "audio/x-flac": "flac",
    "audio/x-m4a": "m4a",
    "audio/x-wav": "wav",
}


def _parse_model_list(raw_value: Optional[str], default_models: list[str]) -> list[str]:
    if raw_value is None:
        return list(default_models)
    return [model.strip() for model in raw_value.split(",") if model.strip()]


def _parse_reasoning_effort(raw_value: Optional[str]) -> Optional[str]:
    if raw_value is None or not raw_value.strip():
        return None

    reasoning_effort = raw_value.strip().lower()
    if reasoning_effort not in OPENROUTER_REASONING_EFFORTS:
        allowed = ", ".join(sorted(OPENROUTER_REASONING_EFFORTS))
        raise ValueError(
            f"Invalid OPENROUTER_REASONING_EFFORT {raw_value!r}; allowed: {allowed}."
        )
    return reasoning_effort


def _get_value(obj: object, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_token_usage(response: object) -> TokenUsage:
    usage = _get_value(response, "usage")
    if usage is None:
        return TokenUsage()

    return TokenUsage(
        input_tokens=int(_get_value(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(_get_value(usage, "completion_tokens", 0) or 0),
    )


def _content_to_text(content: object) -> Optional[str]:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for part in content:
            text = _get_value(part, "text")
            if text:
                text_parts.append(str(text))
        return "\n".join(text_parts) or None

    return None


def _extract_response_text(response: object) -> Optional[str]:
    choices = _get_value(response, "choices") or []
    if not choices:
        return None

    message = _get_value(choices[0], "message")
    if message is None:
        return None
    return _content_to_text(_get_value(message, "content"))


def _image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _binary_media_to_content(part: BinaryMediaPart) -> dict[str, object]:
    encoded = base64.b64encode(part.data).decode("ascii")
    mime_type = part.mime_type.lower()

    if mime_type.startswith("image/"):
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{encoded}",
                "detail": "high",
            },
        }

    if mime_type.startswith("audio/"):
        audio_format = _AUDIO_FORMATS.get(mime_type)
        if not audio_format:
            raise ValueError(f"Unsupported OpenRouter audio MIME type: {mime_type}")
        return {
            "type": "input_audio",
            "input_audio": {
                "data": encoded,
                "format_": audio_format,
            },
        }

    if mime_type.startswith("video/"):
        return {
            "type": "video_url",
            "video_url": {"url": f"data:{mime_type};base64,{encoded}"},
        }

    raise ValueError(f"Unsupported OpenRouter media MIME type: {mime_type}")


def _build_user_content(question: str, media_parts: Optional[list]) -> object:
    if not media_parts:
        return question

    content: list[object] = [{"type": "text", "text": question}]
    for part in media_parts:
        if isinstance(part, Image.Image):
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_to_data_url(part),
                        "detail": "high",
                    },
                }
            )
        elif isinstance(part, BinaryMediaPart):
            content.append(_binary_media_to_content(part))
        elif isinstance(part, dict):
            content.append(part)
        else:
            raise TypeError(
                f"Unsupported OpenRouter media part type: {type(part).__name__}"
            )
    return content


def _model_request_args(models: list[str]) -> dict[str, object]:
    if len(models) == 1:
        return {"model": models[0]}
    return {"models": models}


def _to_png_bytes(image_bytes: bytes) -> Optional[bytes]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            buffer = io.BytesIO()
            if image.mode in {"RGBA", "LA"}:
                image.convert("RGBA").save(buffer, format="PNG")
            else:
                image.convert("RGB").save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception:
        return None


class OpenRouterProvider(LLMProvider):
    """OpenRouter provider with text, image, audio, and video input support."""

    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        text_models: Optional[list[str]] = None,
        multimodal_models: Optional[list[str]] = None,
        audio_models: Optional[list[str]] = None,
        image_models: Optional[list[str]] = None,
        timeout_seconds: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
    ):
        self.api_key = api_key
        self.text_models = (
            text_models
            if text_models is not None
            else _parse_model_list(
                os.getenv("OPENROUTER_TEXT_MODELS"),
                DEFAULT_OPENROUTER_TEXT_MODELS,
            )
        )
        self.multimodal_models = (
            multimodal_models
            if multimodal_models is not None
            else _parse_model_list(
                os.getenv("OPENROUTER_MULTIMODAL_MODELS"),
                DEFAULT_OPENROUTER_MULTIMODAL_MODELS,
            )
        )
        self.audio_models = (
            audio_models
            if audio_models is not None
            else _parse_model_list(
                os.getenv("OPENROUTER_AUDIO_MODELS"),
                DEFAULT_OPENROUTER_AUDIO_MODELS,
            )
        )
        self.image_models = (
            image_models
            if image_models is not None
            else _parse_model_list(os.getenv("OPENROUTER_IMAGE_MODELS"), [])
        )
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("OPENROUTER_TIMEOUT_SECONDS", "55")
        )
        self.reasoning_effort = _parse_reasoning_effort(
            reasoning_effort
            if reasoning_effort is not None
            else os.getenv("OPENROUTER_REASONING_EFFORT")
        )
        self.http_referer = os.getenv("OPENROUTER_HTTP_REFERER") or None
        self.app_title = os.getenv("OPENROUTER_APP_TITLE", "Frozbot") or None
        self.provider_preferences = self._load_provider_preferences()
        self._client: Optional[object] = None

    @staticmethod
    def _load_provider_preferences() -> Optional[dict[str, object]]:
        preferences: dict[str, object] = {}

        data_collection = os.getenv("OPENROUTER_DATA_COLLECTION", "").strip().lower()
        if data_collection in {"allow", "deny"}:
            preferences["data_collection"] = data_collection
        elif data_collection:
            logger.warning(
                "openrouter_data_collection_invalid",
                extra={"value": data_collection},
            )

        zdr_value = os.getenv("OPENROUTER_ZDR")
        if zdr_value is not None and zdr_value.strip():
            preferences["zdr"] = zdr_value.strip().lower() == "true"

        return preferences or None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not OPENROUTER_SDK_AVAILABLE or _OpenRouterClient is None:
            raise ImportError(
                "openrouter is not installed. Install it with: pip install openrouter"
            )

        self._client = _OpenRouterClient(
            api_key=self.api_key,
            http_referer=self.http_referer,
            x_open_router_title=self.app_title,
            timeout_ms=max(1, int(self.timeout_seconds * 1000)),
        )
        return self._client

    def is_available(self) -> bool:
        sdk_or_fake_client = OPENROUTER_SDK_AVAILABLE or self._client is not None
        return sdk_or_fake_client and bool(self.api_key)

    def supports_image_generation(self) -> bool:
        return self.is_available() and bool(self.image_models)

    def supports_media_type(self, mime_type: str) -> bool:
        normalized_type = mime_type.lower()
        if normalized_type.startswith("audio/"):
            return bool(self.audio_models)
        if normalized_type.startswith(("image/", "video/")):
            return bool(self.multimodal_models)
        return False

    def get_client(self):
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
        if not self.is_available():
            return None, TokenUsage()

        has_audio = any(
            isinstance(part, BinaryMediaPart)
            and part.mime_type.lower().startswith("audio/")
            for part in media_parts or []
        )
        if has_audio:
            models = self.audio_models
        elif media_parts:
            models = self.multimodal_models
        else:
            models = self.text_models
        if not models:
            logger.error(
                "provider_models_missing",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "operation": "generate_response",
                    "media_parts": len(media_parts or []),
                },
            )
            return None, TokenUsage()

        try:
            messages = [
                {"role": "system", "content": context_string},
                {
                    "role": "user",
                    "content": _build_user_content(question, media_parts),
                },
            ]
            request_args: dict[str, object] = {
                **_model_request_args(models),
                "messages": messages,
                "stream": False,
                "temperature": 0.9,
                "timeout_ms": max(1, int(self.timeout_seconds * 1000)),
            }
            if self.provider_preferences:
                request_args["provider"] = self.provider_preferences
            if self.reasoning_effort:
                request_args["reasoning"] = {"effort": self.reasoning_effort}

            logger.info(
                "provider_model_attempt",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "models": models,
                    "operation": "generate_response",
                    "media_parts": len(media_parts or []),
                    **text_log_fields("question", question),
                    **context_log_fields(context_string),
                },
            )

            response = await self._get_client().chat.send_async(**request_args)
            token_usage = _extract_token_usage(response)
            actual_model = _get_value(response, "model")
            usage = _get_value(response, "usage")
            cost = _get_value(usage, "cost") if usage is not None else None
            usage_fields: dict[str, object] = token_usage_log_fields(token_usage)
            if isinstance(cost, (int, float)):
                usage_fields["cost_usd"] = cost

            response_text = _extract_response_text(response)
            if response_text:
                logger.info(
                    "provider_model_succeeded",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": actual_model,
                        **usage_fields,
                    },
                )
                return response_text, token_usage

            logger.warning(
                "provider_model_missing_response_text",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "model": actual_model,
                },
            )
            return None, token_usage

        except asyncio.TimeoutError:
            logger.warning(
                "provider_model_timeout",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "models": models,
                },
            )
            return None, TokenUsage()
        except Exception as exc:
            logger.exception(
                "provider_model_failed",
                extra={
                    "request_id": request_id,
                    "provider": self.provider_name,
                    "models": models,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:200],
                },
            )
            return None, TokenUsage()

    async def summarize_messages(
        self, serialized_messages: str, request_id: Optional[str] = None
    ) -> Tuple[Optional[str], TokenUsage]:
        context_instruction = (
            "You are summarizing a Discord channel's recent conversation for an assistant. "
            "Compress only. Do not speculate. Keep it to 1–2 sentences, focusing on the "
            "main topics, decisions, or questions. Include notable entities or links if critical."
        )
        prompt = (
            "Summarize the following messages in at most 2 sentences."
            "\n\nMessages:\n" + serialized_messages
        )
        return await self.generate_response(
            prompt,
            context_instruction,
            None,
            request_id=request_id,
        )

    async def generate_image(
        self,
        prompt: str,
        image_parts: Optional[list] = None,
        request_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[bytes]]:
        if not self.supports_image_generation():
            return None, None

        input_references = []
        for part in image_parts or []:
            if isinstance(part, Image.Image):
                image_url = _image_to_data_url(part)
            elif isinstance(part, BinaryMediaPart) and part.mime_type.startswith("image/"):
                encoded = base64.b64encode(part.data).decode("ascii")
                image_url = f"data:{part.mime_type};base64,{encoded}"
            else:
                logger.warning(
                    "provider_image_reference_ignored",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "media_type": type(part).__name__,
                    },
                )
                continue
            input_references.append(
                {"type": "image_url", "image_url": {"url": image_url}}
            )

        client = self._get_client()
        for model_name in self.image_models:
            try:
                request_args: dict[str, object] = {
                    "model": model_name,
                    "prompt": prompt,
                    "n": 1,
                    "output_format": "png",
                    "stream": False,
                    "timeout_ms": max(120_000, int(self.timeout_seconds * 1000)),
                }
                if input_references:
                    request_args["input_references"] = input_references

                logger.info(
                    "provider_model_attempt",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        "operation": "generate_image",
                        "media_parts": len(input_references),
                        **text_log_fields("prompt", prompt),
                    },
                )

                response = await client.images.generate_async(**request_args)
                response_data = _get_value(response, "data") or []
                if not response_data:
                    continue

                encoded_image = _get_value(response_data[0], "b64_json")
                if not encoded_image:
                    continue

                image_bytes = base64.b64decode(encoded_image)
                png_bytes = _to_png_bytes(image_bytes)
                if png_bytes:
                    logger.info(
                        "provider_model_succeeded",
                        extra={
                            "request_id": request_id,
                            "provider": self.provider_name,
                            "model": model_name,
                            "operation": "generate_image",
                        },
                    )
                    return None, png_bytes

                logger.warning(
                    "provider_image_invalid_output",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "provider_image_timeout",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                    },
                )
            except Exception as exc:
                logger.exception(
                    "provider_image_failed",
                    extra={
                        "request_id": request_id,
                        "provider": self.provider_name,
                        "model": model_name,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:200],
                    },
                )

        return None, None
