import asyncio
import base64
import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(
    importlib.util.find_spec("PIL") is not None,
    "Pillow is required for Mistral provider image tests",
)
class MistralProviderTests(unittest.TestCase):
    def test_generate_response_uses_chat_payload_and_usage(self):
        from llm_providers.mistral import MistralProvider

        calls = []

        class FakeChat:
            def complete(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="hello from mistral")
                        )
                    ],
                    usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
                )

        provider = MistralProvider("test-key", text_models=["mistral-test"])
        provider._client = SimpleNamespace(chat=FakeChat())

        text, usage = asyncio.run(
            provider.generate_response("question", "system prompt", None)
        )

        self.assertEqual(text, "hello from mistral")
        self.assertEqual(usage.input_tokens, 11)
        self.assertEqual(usage.output_tokens, 7)
        self.assertEqual(calls[0]["model"], "mistral-test")
        self.assertEqual(
            calls[0]["messages"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "question"},
            ],
        )
        self.assertEqual(calls[0]["temperature"], 0.9)

    def test_generate_response_converts_images_to_vision_content(self):
        from PIL import Image

        from llm_providers.mistral import MistralProvider

        calls = []

        class FakeChat:
            def complete(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content="saw image"))
                    ],
                    usage=None,
                )

        provider = MistralProvider(
            "test-key",
            text_models=["mistral-text"],
            vision_models=["mistral-vision"],
        )
        provider._client = SimpleNamespace(chat=FakeChat())
        image = Image.new("RGB", (1, 1), (255, 0, 0))

        text, _ = asyncio.run(
            provider.generate_response("describe it", "system prompt", [image])
        )

        self.assertEqual(text, "saw image")
        self.assertEqual(calls[0]["model"], "mistral-vision")
        user_content = calls[0]["messages"][1]["content"]
        self.assertEqual(user_content[0], {"type": "text", "text": "describe it"})
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertTrue(user_content[1]["image_url"].startswith("data:image/jpeg;base64,"))
        encoded_image = user_content[1]["image_url"].split(",", 1)[1]
        self.assertGreater(len(base64.b64decode(encoded_image)), 0)

    def test_generate_image_uses_configured_agent_and_downloads_file(self):
        from llm_providers.mistral import MistralProvider

        calls = []
        downloaded = []
        downloaded_response = None

        class FakeStreamingDownload:
            def __init__(self, data):
                self.data = data
                self.read_called = False

            @property
            def content(self):
                if not self.read_called:
                    raise RuntimeError(
                        "Attempted to access streaming response content, "
                        "without having called `read()`."
                    )
                return self.data

            def read(self):
                self.read_called = True
                return self.data

        class FakeConversations:
            def start(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    outputs=[
                        SimpleNamespace(
                            content=[
                                SimpleNamespace(type="text", text="generated image"),
                                SimpleNamespace(type="tool_file", file_id="file-123"),
                            ]
                        )
                    ]
                )

        class FakeFiles:
            def download(self, file_id):
                nonlocal downloaded_response
                downloaded.append(file_id)
                downloaded_response = FakeStreamingDownload(b"image-bytes")
                return downloaded_response

        provider = MistralProvider("test-key", image_agent_id="agent-123")
        provider._client = SimpleNamespace(
            beta=SimpleNamespace(conversations=FakeConversations()),
            files=FakeFiles(),
        )

        description, image_bytes = asyncio.run(provider.generate_image("draw this"))

        self.assertEqual(description, "generated image")
        self.assertEqual(image_bytes, b"image-bytes")
        self.assertEqual(
            calls[0],
            {"agent_id": "agent-123", "inputs": "draw this", "store": False},
        )
        self.assertEqual(downloaded, ["file-123"])
        self.assertTrue(downloaded_response.read_called)

    def test_generate_image_requires_agent_id(self):
        from llm_providers.mistral import MistralProvider

        provider = MistralProvider("test-key", image_agent_id="")
        provider._client = SimpleNamespace()

        self.assertFalse(provider.supports_image_generation())


if __name__ == "__main__":
    unittest.main()
