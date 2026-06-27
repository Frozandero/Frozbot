import asyncio
import base64
import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(
    importlib.util.find_spec("google.genai") is not None
    and importlib.util.find_spec("PIL") is not None,
    "Gemini provider runtime dependencies are not installed",
)
class GeminiProviderInteractionsTests(unittest.TestCase):
    def test_default_text_image_model_order(self):
        from llm_providers.gemini import GEMINI_TEXT_IMAGE_MODELS

        self.assertEqual(
            [model for model, _ in GEMINI_TEXT_IMAGE_MODELS],
            [
                "gemini-3.5-flash",
                "gemini-3-flash-preview",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash-lite",
            ],
        )

    def test_generate_response_uses_interactions_payload_and_usage(self):
        from llm_providers.gemini import GeminiProvider

        calls = []

        class FakeInteractions:
            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    output_text="hello",
                    usage=SimpleNamespace(
                        total_input_tokens=12,
                        total_output_tokens=5,
                    ),
                )

        provider = GeminiProvider("test-key")
        provider._client = SimpleNamespace(interactions=FakeInteractions())

        text, usage = asyncio.run(
            provider.generate_response("question", "system prompt", None)
        )

        self.assertEqual(text, "hello")
        self.assertEqual(usage.input_tokens, 12)
        self.assertEqual(usage.output_tokens, 5)
        self.assertEqual(calls[0]["model"], "gemini-3.5-flash")
        self.assertEqual(calls[0]["input"], "question")
        self.assertEqual(calls[0]["system_instruction"], "system prompt")
        self.assertEqual(calls[0]["generation_config"]["thinking_level"], "low")
        self.assertEqual(calls[0]["tools"], [{"type": "url_context"}])
        self.assertFalse(calls[0]["store"])

    def test_generate_response_converts_images_to_interaction_blocks(self):
        from PIL import Image

        from llm_providers.gemini import GeminiProvider

        calls = []

        class FakeInteractions:
            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(output_text="saw image", usage=None)

        provider = GeminiProvider("test-key")
        provider._client = SimpleNamespace(interactions=FakeInteractions())
        image = Image.new("RGB", (1, 1), (255, 0, 0))

        text, _ = asyncio.run(
            provider.generate_response("describe it", "system prompt", [image])
        )

        self.assertEqual(text, "saw image")
        input_parts = calls[0]["input"]
        self.assertEqual(input_parts[0]["type"], "image")
        self.assertEqual(input_parts[0]["mime_type"], "image/png")
        self.assertGreater(len(base64.b64decode(input_parts[0]["data"])), 0)
        self.assertEqual(
            input_parts[1],
            {"type": "text", "text": "describe it"},
        )

    def test_generate_image_extracts_output_image(self):
        from llm_providers.gemini import GeminiProvider

        png_bytes = b"image-bytes"
        calls = []

        class FakeInteractions:
            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    output_text="description",
                    output_image=SimpleNamespace(
                        data=base64.b64encode(png_bytes).decode("utf-8")
                    ),
                )

        provider = GeminiProvider("test-key")
        provider._client = SimpleNamespace(interactions=FakeInteractions())

        description, image_bytes = asyncio.run(provider.generate_image("draw this"))

        self.assertEqual(description, "description")
        self.assertEqual(image_bytes, png_bytes)
        self.assertEqual(calls[0]["model"], "gemini-3.1-flash-image")
        self.assertEqual(calls[0]["input"], "draw this")
        self.assertEqual(calls[0]["response_format"][1]["type"], "image")
        self.assertFalse(calls[0]["store"])


if __name__ == "__main__":
    unittest.main()
