import os
import re
import subprocess

from elevenlabs import ElevenLabs
from markdown_it import MarkdownIt
from mdit_plain.renderer import RendererPlain

ELEVEN_CLIENT = None
VOICE_ID = None


def get_eleven_client():
    global ELEVEN_CLIENT
    if not ELEVEN_CLIENT:
        if os.getenv("ELEVENLABS_API_KEY"):
            ELEVEN_CLIENT = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        else:
            raise Exception("ElevenLabs API key not found")
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
            output_format="mp3_22050_32",
        )

        return mp3_bytes_to_ogg(b"".join(tts_bytes))

    except Exception as e:
        print(f"Error generating TTS: {e}")
        return b""


def cleanup_text_for_tts(text: str) -> str:
    """Cleans up text from Discord emotes and markdown formatting."""
    # Remove Discord emotes
    # Replace Discord emotes with just their name (e.g., <a:wave:1234> -> wave)
    formatted_text = re.sub(r"<a?:([a-zA-Z0-9_]+):[0-9]+>", r"\1", text)

    # remove @user's @ (usernames can have punctuation)
    formatted_text = re.sub(r"@([a-zA-Z0-9_]+)", r"\1", formatted_text)

    # Remove markdown formatting
    parser = MarkdownIt(renderer_cls=RendererPlain)  # type: ignore
    formatted_text = parser.render(formatted_text)
    return formatted_text


def mp3_bytes_to_ogg(mp3_bytes: bytes) -> bytes:
    """
    Convert MP3 bytes to OGG Vorbis bytes using ffmpeg (no pydub).
    """
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-i",
            "pipe:0",
            "-ar",
            "48000",  # resample to 48kHz
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "pipe:1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    out_bytes, _ = process.communicate(mp3_bytes)
    return out_bytes
