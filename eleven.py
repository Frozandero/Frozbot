import os
import re

from elevenlabs import ElevenLabs
from markdown_it import MarkdownIt
from mdit_plain.renderer import RendererPlain

import soundfile as sf
import numpy as np

ELEVEN_CLIENT = None
VOICE_ID = None


def get_eleven_client():
    global ELEVEN_CLIENT
    if not ELEVEN_CLIENT:
        ELEVEN_CLIENT = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    return ELEVEN_CLIENT


def get_voice_id() -> str:
    global VOICE_ID
    if not VOICE_ID:
        if os.getenv("ELEVENLABS_VOICE_ID"):
            VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

    return VOICE_ID if VOICE_ID else "JBFqnCBsd6RMkjVDRZzb"


def generate_tts(text: str) -> bytes:
    try:
        client = get_eleven_client()

        tts_bytes = client.text_to_speech.convert(
            text=cleanup_text_for_tts(text),
            voice_id=get_voice_id(),
            model_id="eleven_flash_v2_5",
            output_format="pcm_16000",
        )

        return convert_pcm_to_ogg(b"".join(tts_bytes))

    except Exception as e:
        print(f"Error generating TTS: {e}")
        return b""


def cleanup_text_for_tts(text: str) -> str:
    """Cleans up text from Discord emotes and markdown formatting."""
    # Remove Discord emotes
    # Replace Discord emotes with just their name (e.g., <a:wave:1234> -> wave)
    text = re.sub(r"<a?:([a-zA-Z0-9_]+):[0-9]+>", r"\1", text)
    # Remove markdown formatting
    parser = MarkdownIt(renderer_cls=RendererPlain)  # type: ignore
    text = parser.render(text)
    return text


def convert_pcm_to_ogg(pcm_bytes: bytes) -> bytes:

    # Convert raw PCM bytes to NumPy array
    pcm_array = np.frombuffer(pcm_bytes, dtype=np.int16)

    # Save directly to a memory buffer in OGG Vorbis format
    import io

    buffer = io.BytesIO()
    sf.write(buffer, pcm_array, samplerate=16000, format="OGG", subtype="VORBIS")
    return buffer.getvalue()
