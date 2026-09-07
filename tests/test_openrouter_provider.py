import asyncio
import base64
import io
import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(
    importlib.util.find_spec("PIL") is not None,
    "Pillow is required for OpenRouter provider image tests",
)
class OpenRouterProviderTests(unittest.TestCase):
    def test_default_models_use_minimax_m3_free(self):
        from llm_providers.openrouter import (
            DEFAULT_OPENROUTER_MULTIMODAL_MODELS,
            DEFAULT_OPENROUTER_TEXT_MODELS,
        )

        self.assertEqual(DEFAULT_OPENROUTER_TEXT_MODELS, ["minimax/minimax-m3:free"])
        self.assertEqual(
            DEFAULT_OPENROUTER_MULTIMODAL_MODELS,
            ["minimax/minimax-m3:free"],
        )

    def test_generate_response_uses_async_chat_and_extracts_usage(self):
        from llm_providers.openrouter import OpenRouterProvider

        calls = []

        class FakeChat:
            async def send_async(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    model="minimax/minimax-m3:free",
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="hello from openrouter")
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=13,
                        completion_tokens=6,
                        cost=0,
                    ),
                )

        provider = OpenRouterProvider(
            "test-key",
            text_models=["minimax/minimax-m3:free"],
        )
        provider._client = SimpleNamespace(chat=FakeChat())

        text, usage = asyncio.run(
            provider.generate_response("question", "system prompt", None)
        )

        self.assertEqual(text, "hello from openrouter")
        self.assertEqual(usage.input_tokens, 13)
        self.assertEqual(usage.output_tokens, 6)
        self.assertEqual(calls[0]["model"], "minimax/minimax-m3:free")
        self.assertNotIn("models", calls[0])
        self.assertEqual(
            calls[0]["messages"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "question"},
            ],
        )
        self.assertFalse(calls[0]["stream"])

    def test_generate_response_builds_image_audio_and_video_content(self):
        from PIL import Image

        from llm_providers.base import BinaryMediaPart
        from llm_providers.openrouter import OpenRouterProvider

        calls = []

        class FakeChat:
            async def send_async(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    model="multimodal-test",
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content="media seen"))
                    ],
                    usage=None,
                )

        provider = OpenRouterProvider(
            "test-key",
            text_models=["text-test"],
            multimodal_models=["multimodal-test"],
            audio_models=["multimodal-test"],
        )
        provider._client = SimpleNamespace(chat=FakeChat())
        image = Image.new("RGB", (1, 1), (255, 0, 0))
        audio = BinaryMediaPart(
            data=b"audio-bytes",
            mime_type="audio/mpeg",
            filename="clip.mp3",
        )
        video = BinaryMediaPart(
            data=b"video-bytes",
            mime_type="video/mp4",
            filename="clip.mp4",
        )

        text, _ = asyncio.run(
            provider.generate_response(
                "describe these",
                "system prompt",
                [image, audio, video],
            )
        )

        self.assertEqual(text, "media seen")
        self.assertEqual(calls[0]["model"], "multimodal-test")
        content = calls[0]["messages"][1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "describe these"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(
            content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        )
        self.assertEqual(content[2]["type"], "input_audio")
        self.assertEqual(content[2]["input_audio"]["format_"], "mp3")
        self.assertEqual(
            base64.b64decode(content[2]["input_audio"]["data"]),
            b"audio-bytes",
        )
        self.assertEqual(content[3]["type"], "video_url")
        self.assertTrue(
            content[3]["video_url"]["url"].startswith("data:video/mp4;base64,")
        )

    def test_generate_response_sends_ordered_model_fallbacks(self):
        from llm_providers.openrouter import OpenRouterProvider

        calls = []

        class FakeChat:
            async def send_async(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    model="fallback-model",
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                    usage=None,
                )

        provider = OpenRouterProvider(
            "test-key",
            text_models=["primary-model", "fallback-model"],
        )
        provider._client = SimpleNamespace(chat=FakeChat())

        asyncio.run(provider.generate_response("question", "system prompt"))

        self.assertEqual(calls[0]["models"], ["primary-model", "fallback-model"])
        self.assertNotIn("model", calls[0])

    def test_generate_image_uses_image_api_and_returns_png(self):
        from PIL import Image

        from llm_providers.openrouter import OpenRouterProvider

        calls = []
        source_buffer = io.BytesIO()
        Image.new("RGB", (2, 2), (0, 0, 255)).save(source_buffer, format="JPEG")
        encoded_image = base64.b64encode(source_buffer.getvalue()).decode("ascii")

        class FakeImages:
            async def generate_async(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    data=[SimpleNamespace(b64_json=encoded_image)],
                    usage=None,
                )

        provider = OpenRouterProvider(
            "test-key",
            image_models=["image-model"],
        )
        provider._client = SimpleNamespace(images=FakeImages())
        reference = Image.new("RGB", (1, 1), (255, 0, 0))

        description, image_bytes = asyncio.run(
            provider.generate_image("draw this", [reference])
        )

        self.assertIsNone(description)
        self.assertIsNotNone(image_bytes)
        with Image.open(io.BytesIO(image_bytes)) as generated:
            self.assertEqual(generated.format, "PNG")
        self.assertEqual(calls[0]["model"], "image-model")
        self.assertEqual(calls[0]["output_format"], "png")
        self.assertEqual(calls[0]["n"], 1)
        self.assertEqual(calls[0]["input_references"][0]["type"], "image_url")

    def test_image_generation_requires_configured_model(self):
        from llm_providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider("test-key", image_models=[])
        provider._client = SimpleNamespace()

        self.assertFalse(provider.supports_image_generation())

    def test_minimax_default_does_not_claim_audio_input(self):
        from llm_providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider("test-key")
        provider._client = SimpleNamespace()

        self.assertFalse(provider.supports_media_type("audio/mpeg"))
        self.assertTrue(provider.supports_media_type("image/png"))
        self.assertTrue(provider.supports_media_type("video/mp4"))


if __name__ == "__main__":
    unittest.main()
