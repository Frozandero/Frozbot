"""Retry functionality for Frozbot - media and context persistence."""

import os
from typing import Optional

from PIL import Image

import config


def save_retry_media(custom_id: str, media_parts: Optional[list]) -> None:
    """Persist provided PIL images to disk for later retry and index by custom_id."""
    try:
        if not media_parts:
            return
        os.makedirs(config.ASK_IMAGES_DIR, exist_ok=True)
        saved_paths: list = []
        for idx, part in enumerate(media_parts):
            try:
                if isinstance(part, Image.Image):
                    path = os.path.join(config.ASK_IMAGES_DIR, f"{custom_id}_{idx}.png")
                    part.convert("RGB").save(path, format="PNG")
                    saved_paths.append(path)
            except Exception:
                continue
        if saved_paths:
            config.RETRY_MEDIA_TEMP[custom_id] = saved_paths
    except Exception:
        pass


def load_retry_media(custom_id: str) -> Optional[list]:
    """Load images for this custom_id from disk and delete files; return PIL images list or None."""
    try:
        paths = config.RETRY_MEDIA_TEMP.pop(custom_id, None)
        if not paths:
            return None
        loaded: list = []
        for path in paths:
            try:
                with Image.open(path) as img:
                    loaded.append(img.copy())
            except Exception:
                pass
            try:
                os.remove(path)
            except Exception:
                pass
        return loaded if loaded else None
    except Exception:
        return None


def cleanup_retry_media(custom_id: str) -> None:
    """Delete any persisted media and mapping for this custom_id (used on expiry)."""
    try:
        paths = config.RETRY_MEDIA_TEMP.pop(custom_id, None)
        if not paths:
            return
        for path in paths:
            try:
                os.remove(path)
            except Exception:
                pass
    except Exception:
        pass


def save_retry_context(custom_id: str, context_string: Optional[str]) -> None:
    """Save context string for retry."""
    try:
        if context_string:
            config.RETRY_CONTEXT_TEMP[custom_id] = context_string
    except Exception:
        pass


def load_retry_context(custom_id: str) -> Optional[str]:
    """Load and remove context string for retry."""
    try:
        return config.RETRY_CONTEXT_TEMP.pop(custom_id, None)
    except Exception:
        return None
