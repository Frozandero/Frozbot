"""Defensive image attachment validation."""

import io
import logging
import warnings
from typing import Optional

from PIL import Image

import config

logger = logging.getLogger(__name__)


class ImageValidationError(ValueError):
    """Raised when an image input is unsafe or unsupported."""


def _allowed_formats() -> set[str]:
    return {
        fmt.strip().upper()
        for fmt in config.ALLOWED_IMAGE_FORMATS.split(",")
        if fmt.strip()
    }


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
