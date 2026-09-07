"""Defensive multimodal attachment validation."""

import io
import logging
import mimetypes
import os
import warnings
from typing import Optional

from PIL import Image

import config
from llm_providers.base import BinaryMediaPart

logger = logging.getLogger(__name__)


class MediaValidationError(ValueError):
    """Raised when a multimodal attachment is unsafe or unsupported."""


class ImageValidationError(MediaValidationError):
    """Raised when an image input is unsafe or unsupported."""


_AUDIO_MIME_FORMATS = {
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

_VIDEO_MIME_FORMATS = {
    "video/mov": "mov",
    "video/mp4": "mp4",
    "video/mpeg": "mpeg",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


def _allowed_formats() -> set[str]:
    return {
        fmt.strip().upper()
        for fmt in config.ALLOWED_IMAGE_FORMATS.split(",")
        if fmt.strip()
    }


def _allowed_media_formats(raw_value: str) -> set[str]:
    return {value.strip().lower() for value in raw_value.split(",") if value.strip()}


def _normalized_content_type(content_type: Optional[str]) -> Optional[str]:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower() or None


def _attachment_content_type(attachment: object) -> Optional[str]:
    content_type = _normalized_content_type(getattr(attachment, "content_type", None))
    if content_type and content_type != "application/octet-stream":
        return content_type

    filename = str(getattr(attachment, "filename", "") or "")
    guessed_type, _ = mimetypes.guess_type(filename)
    return _normalized_content_type(guessed_type)


def is_supported_media_attachment(attachment: object) -> bool:
    """Return whether an attachment looks like a supported input modality."""
    content_type = _attachment_content_type(attachment)
    return bool(
        content_type
        and content_type.startswith(("image/", "audio/", "video/"))
    )


def _media_format(
    *,
    content_type: str,
    filename: Optional[str],
    mime_formats: dict[str, str],
) -> Optional[str]:
    media_format = mime_formats.get(content_type)
    if media_format:
        return media_format

    extension = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return extension or None


def validate_binary_media_bytes(
    media_bytes: bytes,
    *,
    source_name: str,
    content_type: str,
    filename: Optional[str] = None,
    request_id: Optional[str] = None,
) -> BinaryMediaPart:
    """Validate audio/video bytes and return a provider-neutral media part."""
    normalized_type = _normalized_content_type(content_type)
    if not normalized_type:
        raise MediaValidationError("Attachment has no recognized media type.")

    if normalized_type.startswith("audio/"):
        media_kind = "audio"
        max_bytes = config.MAX_AUDIO_ATTACHMENT_BYTES
        allowed_formats = _allowed_media_formats(config.ALLOWED_AUDIO_FORMATS)
        mime_formats = _AUDIO_MIME_FORMATS
    elif normalized_type.startswith("video/"):
        media_kind = "video"
        max_bytes = config.MAX_VIDEO_ATTACHMENT_BYTES
        allowed_formats = _allowed_media_formats(config.ALLOWED_VIDEO_FORMATS)
        mime_formats = _VIDEO_MIME_FORMATS
    else:
        raise MediaValidationError("Attachment is not supported audio or video.")

    if not media_bytes:
        raise MediaValidationError(f"{media_kind.title()} attachment is empty.")
    if len(media_bytes) > max_bytes:
        raise MediaValidationError(
            f"{media_kind.title()} is too large ({len(media_bytes)} bytes; max {max_bytes})."
        )

    media_format = _media_format(
        content_type=normalized_type,
        filename=filename,
        mime_formats=mime_formats,
    )
    if not media_format or media_format not in allowed_formats:
        allowed = ", ".join(sorted(allowed_formats))
        raise MediaValidationError(
            f"Unsupported {media_kind} format {media_format or 'unknown'}; allowed: {allowed}."
        )

    logger.info(
        "media_attachment_validated",
        extra={
            "request_id": request_id,
            "source_name": source_name,
            "content_type": normalized_type,
            "media_kind": media_kind,
            "media_format": media_format,
            "media_bytes": len(media_bytes),
        },
    )
    return BinaryMediaPart(
        data=bytes(media_bytes),
        mime_type=normalized_type,
        filename=filename,
    )


def validate_image_bytes(
    image_bytes: bytes,
    *,
    source_name: str,
    content_type: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Image.Image:
    """Validate raw image bytes and return a loaded RGB PIL image."""
    if content_type and not content_type.lower().startswith("image/"):
        raise ImageValidationError("Attachment is not an image.")

    max_bytes = config.MAX_IMAGE_ATTACHMENT_BYTES
    if len(image_bytes) > max_bytes:
        raise ImageValidationError(
            f"Image is too large ({len(image_bytes)} bytes; max {max_bytes})."
        )

    allowed_formats = _allowed_formats()
    max_pixels = config.MAX_IMAGE_PIXELS

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as verify_image:
                image_format = (verify_image.format or "").upper()
                if image_format not in allowed_formats:
                    allowed = ", ".join(sorted(allowed_formats))
                    raise ImageValidationError(
                        f"Unsupported image format {image_format or 'unknown'}; allowed: {allowed}."
                    )

                width, height = verify_image.size
                if width <= 0 or height <= 0:
                    raise ImageValidationError("Image has invalid dimensions.")

                pixel_count = width * height
                if pixel_count > max_pixels:
                    raise ImageValidationError(
                        f"Image has too many pixels ({pixel_count}; max {max_pixels})."
                    )

                verify_image.verify()

            with Image.open(io.BytesIO(image_bytes)) as loaded_image:
                loaded_image.load()
                image = loaded_image.convert("RGB")
    except ImageValidationError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("Image dimensions are unsafe.") from exc
    except Exception as exc:
        raise ImageValidationError("Attachment could not be decoded as a valid image.") from exc

    logger.info(
        "image_attachment_validated",
        extra={
            "request_id": request_id,
            "source_name": source_name,
            "content_type": content_type,
            "image_format": image_format,
            "image_width": image.width,
            "image_height": image.height,
            "image_bytes": len(image_bytes),
        },
    )
    return image


async def read_validated_attachment(
    attachment: object,
    *,
    source_name: str,
    request_id: Optional[str] = None,
) -> Image.Image:
    """Read and validate a Discord attachment as an image."""
    content_type = getattr(attachment, "content_type", None)
    size = getattr(attachment, "size", None)
    if size is not None and int(size) > config.MAX_IMAGE_ATTACHMENT_BYTES:
        raise ImageValidationError(
            f"Image is too large ({size} bytes; max {config.MAX_IMAGE_ATTACHMENT_BYTES})."
        )

    read = getattr(attachment, "read", None)
    if not callable(read):
        raise ImageValidationError("Attachment cannot be read.")

    image_bytes = await read()
    return validate_image_bytes(
        image_bytes,
        source_name=source_name,
        content_type=content_type,
        request_id=request_id,
    )


async def read_validated_media_attachment(
    attachment: object,
    *,
    source_name: str,
    request_id: Optional[str] = None,
) -> object:
    """Read and validate an image, audio, or video Discord attachment."""
    content_type = _attachment_content_type(attachment)
    if not content_type:
        raise MediaValidationError("Attachment has no recognized media type.")

    if content_type.startswith("image/"):
        size = getattr(attachment, "size", None)
        if size is not None and int(size) > config.MAX_IMAGE_ATTACHMENT_BYTES:
            raise ImageValidationError(
                f"Image is too large ({size} bytes; max {config.MAX_IMAGE_ATTACHMENT_BYTES})."
            )
        read = getattr(attachment, "read", None)
        if not callable(read):
            raise ImageValidationError("Attachment cannot be read.")
        image_bytes = await read()
        return validate_image_bytes(
            image_bytes,
            source_name=source_name,
            content_type=content_type,
            request_id=request_id,
        )

    if content_type.startswith("audio/"):
        max_bytes = config.MAX_AUDIO_ATTACHMENT_BYTES
    elif content_type.startswith("video/"):
        max_bytes = config.MAX_VIDEO_ATTACHMENT_BYTES
    else:
        raise MediaValidationError("Only image, audio, and video attachments are supported.")

    size = getattr(attachment, "size", None)
    if size is not None and int(size) > max_bytes:
        media_kind = content_type.split("/", 1)[0]
        raise MediaValidationError(
            f"{media_kind.title()} is too large ({size} bytes; max {max_bytes})."
        )

    read = getattr(attachment, "read", None)
    if not callable(read):
        raise MediaValidationError("Attachment cannot be read.")

    media_bytes = await read()
    return validate_binary_media_bytes(
        media_bytes,
        source_name=source_name,
        content_type=content_type,
        filename=getattr(attachment, "filename", None),
        request_id=request_id,
    )
