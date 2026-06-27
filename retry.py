"""Retry functionality for Frozbot - media, context, and record persistence."""

import json
import os
import re
import time
from typing import Any, Optional

from PIL import Image

import config


_SAFE_RETRY_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_retry_id(custom_id: str) -> bool:
    return bool(_SAFE_RETRY_ID_RE.fullmatch(custom_id))


def _retry_record_path(custom_id: str) -> Optional[str]:
    if not _is_safe_retry_id(custom_id):
        return None
    return os.path.join(config.RETRY_RECORDS_DIR, f"{custom_id}.json")


def _is_path_under(path: str, directory: str) -> bool:
    try:
        real_path = os.path.realpath(path)
        real_directory = os.path.realpath(directory)
        return os.path.commonpath([real_path, real_directory]) == real_directory
    except Exception:
        return False


def _read_retry_record(custom_id: str) -> Optional[dict[str, Any]]:
    path = _retry_record_path(custom_id)
    if not path or not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as record_file:
            record = json.load(record_file)
    except Exception:
        return None

    return record if isinstance(record, dict) else None


def _delete_retry_record_file(custom_id: str) -> None:
    path = _retry_record_path(custom_id)
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _load_media_paths(paths: Optional[list], delete_files: bool = True) -> Optional[list]:
    if not paths:
        return None

    loaded: list = []
    for path in paths:
        if not isinstance(path, str):
            continue
        if not _is_path_under(path, config.ASK_IMAGES_DIR):
            continue

        try:
            with Image.open(path) as img:
                loaded.append(img.copy())
        except Exception:
            pass

        if delete_files:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except Exception:
                pass

    return loaded if loaded else None


def save_retry_media(custom_id: str, media_parts: Optional[list]) -> list[str]:
    """Persist provided PIL images to disk for later retry and index by custom_id."""
    try:
        if not media_parts or not _is_safe_retry_id(custom_id):
            return []

        os.makedirs(config.ASK_IMAGES_DIR, exist_ok=True)
        saved_paths: list[str] = []

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

        return saved_paths
    except Exception:
        return []


def load_retry_media(custom_id: str) -> Optional[list]:
    """Load images for this custom_id from disk and delete files."""
    try:
        paths = config.RETRY_MEDIA_TEMP.pop(custom_id, None)
        if not paths:
            record = _read_retry_record(custom_id)
            paths = record.get("media_paths") if record else None

        return _load_media_paths(paths)
    except Exception:
        return None


def cleanup_retry_media(custom_id: str) -> None:
    """Delete any persisted media and mapping for this custom_id."""
    try:
        paths = config.RETRY_MEDIA_TEMP.pop(custom_id, None)
        if not paths:
            record = _read_retry_record(custom_id)
            paths = record.get("media_paths") if record else None

        if not paths:
            return

        for path in paths:
            if not isinstance(path, str):
                continue
            if not _is_path_under(path, config.ASK_IMAGES_DIR):
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
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
    """Load and remove context string from the in-memory compatibility cache."""
    try:
        return config.RETRY_CONTEXT_TEMP.pop(custom_id, None)
    except Exception:
        return None


def save_retry_record(
    custom_id: str,
    user_id: int,
    question: str,
    context_string: str,
    tts: bool,
    media_parts: Optional[list],
) -> bool:
    """Persist all data needed to retry a failed ask request."""
    try:
        record_path = _retry_record_path(custom_id)
        if not record_path:
            return False

        os.makedirs(config.RETRY_RECORDS_DIR, exist_ok=True)
        media_paths = save_retry_media(custom_id, media_parts)
        save_retry_context(custom_id, context_string)

        record = {
            "custom_id": custom_id,
            "user_id": user_id,
            "question": question,
            "context_string": context_string,
            "tts": bool(tts),
            "media_paths": media_paths,
            "created_at": int(time.time()),
        }

        temp_path = f"{record_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as record_file:
            json.dump(record, record_file)
        os.replace(temp_path, record_path)
        return True
    except Exception as e:
        print(f"[WARN] Failed to persist retry record {custom_id}: {e}")
        return False


def load_retry_record(custom_id: str) -> Optional[dict[str, Any]]:
    """Load and remove a persisted retry record, including any image media."""
    record = _read_retry_record(custom_id)
    if not record:
        return None

    media_paths = record.get("media_paths")
    if not media_paths:
        media_paths = config.RETRY_MEDIA_TEMP.pop(custom_id, None)
    else:
        config.RETRY_MEDIA_TEMP.pop(custom_id, None)

    record["media_parts"] = _load_media_paths(media_paths)
    config.RETRY_CONTEXT_TEMP.pop(custom_id, None)
    _delete_retry_record_file(custom_id)
    return record


def cleanup_retry_record(custom_id: str) -> None:
    """Delete a retry record, its media files, and compatibility cache entries."""
    cleanup_retry_media(custom_id)
    try:
        config.RETRY_CONTEXT_TEMP.pop(custom_id, None)
    except Exception:
        pass
    _delete_retry_record_file(custom_id)


def cleanup_expired_retry_records(max_age_seconds: int) -> int:
    """Remove persisted retry records older than max_age_seconds."""
    try:
        if not os.path.isdir(config.RETRY_RECORDS_DIR):
            return 0

        now = int(time.time())
        removed = 0

        for filename in os.listdir(config.RETRY_RECORDS_DIR):
            if not filename.endswith(".json"):
                continue

            custom_id = filename[:-5]
            if not _is_safe_retry_id(custom_id):
                continue

            record = _read_retry_record(custom_id)
            created_at = record.get("created_at") if record else None
            if not isinstance(created_at, int):
                parts = custom_id.split("_")
                if len(parts) >= 5:
                    try:
                        created_at = int(parts[4])
                    except ValueError:
                        created_at = None

            if created_at is None or now - created_at >= max_age_seconds:
                cleanup_retry_record(custom_id)
                removed += 1

        return removed
    except Exception:
        return 0
