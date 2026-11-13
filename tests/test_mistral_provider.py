import asyncio
import base64
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


@unittest.skipUnless(
    importlib.util.find_spec("PIL") is not None,
    "Pillow is required for Mistral provider image tests",
)
class MistralProviderTests(unittest.TestCase):
    def _run_with_sdk(self, question="question", media=None, search=False, fail_search=False, answer="verified answer"):
        from mistralai import agents
        from llm_providers.mistral import MistralProvider
        import os

        captured = {}
        completed = agents.Completed(
            session_id="session", turn_id="turn", cursor="cursor", text=answer,
            output=answer,
        )
        session = SimpleNamespace(cancel=AsyncMock())

        async def run(content):
            captured["content"] = content
            await captured["hooks"][0].post_llm_call(None, SimpleNamespace(
                usage=SimpleNamespace(input_tokens=11, output_tokens=7)))
            if search:
                result = await captured["tools"][0](query="game release official announcement")
                captured["evidence"] = result
            return completed

        session.run = run
        real_agent = agents.Agent

        def make_agent(**kwargs):
            # Validate the actual pinned SDK constructor without making a network call.
            real_agent(**kwargs)
            captured.update(kwargs)
            return SimpleNamespace(start_session=AsyncMock(return_value=session))

        response = SimpleNamespace(outputs=[SimpleNamespace(
            type="message.output", role="assistant", content=[
                {"type": "text", "text": "Official announcement: a new release date."},
                {"type": "tool_reference", "url": "https://example.com/announcement"},
            ])], usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3))
        search_api = AsyncMock(return_value=response)
        if fail_search:
            search_api.side_effect = RuntimeError("unavailable")
        with patch.dict(os.environ, {"MISTRAL_WEB_SEARCH_ENABLE": "true"}):
            provider = MistralProvider("test-key", text_models=["mistral-test"], vision_models=["vision-test"])
        provider._client = SimpleNamespace(beta=SimpleNamespace(conversations=SimpleNamespace(start_async=search_api)))
        with patch.object(agents, "Agent", side_effect=make_agent):
            result = asyncio.run(provider.generate_response(question, "persona and memories", media))
        return result, captured, session, search_api

    def test_agent_search_keeps_evidence_internal_and_aggregates_usage(self):
        (text, usage), captured, session, search_api = self._run_with_sdk(search=True)
        self.assertEqual(text, "verified answer")
        self.assertIn("https://example.com/announcement", captured["evidence"])
        self.assertIn("unless the user explicitly asks", captured["instructions"])
        self.assertNotIn("Cite supporting source URLs in your answer", captured["instructions"])
        self.assertIn("Official announcement", captured["evidence"])
        self.assertIn("persona and memories", captured["instructions"])
        self.assertIn("release dates", captured["instructions"])
        self.assertEqual((usage.input_tokens, usage.output_tokens), (16, 10))
        self.assertFalse(search_api.call_args.kwargs["store"])
        self.assertEqual(search_api.call_args.kwargs["tools"], [{"type": "web_search"}])
        session.cancel.assert_awaited_once()

    def test_explicit_source_request_keeps_selected_model_citation(self):
        answer = "November 19. [Official announcement](https://example.com/announcement)"
        (text, _), captured, _, _ = self._run_with_sdk(
            question="When is it released? Include a source link.", search=True, answer=answer,
        )
        self.assertEqual(text, answer)
        self.assertIn("one or two supporting links", captured["instructions"])

    def test_casual_chat_does_not_force_search(self):
        (text, usage), captured, session, search_api = self._run_with_sdk()
        self.assertEqual(text, "verified answer")
        self.assertEqual(captured["content"], "question")
        self.assertEqual(usage.input_tokens, 11)
        search_api.assert_not_awaited()

    def test_search_failure_returns_explicit_uncertainty_to_agent(self):
        _, captured, _, _ = self._run_with_sdk(search=True, fail_search=True)
        self.assertIn("could not be verified", captured["evidence"])
        self.assertIn("do not guess", captured["evidence"])

    def test_agent_converts_validated_image_for_sdk(self):
        from PIL import Image
        _, captured, _, _ = self._run_with_sdk(media=[Image.new("RGB", (1, 1))])
        self.assertEqual(captured["model"], "vision-test")
        self.assertEqual(captured["content"][1]["type"], "image")
        self.assertTrue(captured["content"][1]["uri"].startswith("data:image/jpeg;base64,"))

    def test_real_sdk_harness_executes_request_scoped_search_without_network(self):
        from mistralai import agents
        from llm_providers.mistral import MistralProvider
        from llm_providers.mistral_tools import search_callback
        model = agents.testing.ScriptedModel([
            agents.testing.call("web_search", query="official game release date"),
            agents.testing.reply("Confirmed by the official announcement."),
        ])
        real_agent = agents.Agent
        def scripted_agent(**kwargs):
            return real_agent(**kwargs).override(model=model)
        search_api = AsyncMock(return_value=SimpleNamespace(outputs=[{
            "type": "message.output", "content": [
                {"type": "text", "text": "Official release date announcement"},
                {"type": "tool_reference", "url": "https://example.com/official"},
            ],
        }]))
        provider = MistralProvider("key", text_models=["test"])
        provider._client = SimpleNamespace(beta=SimpleNamespace(conversations=SimpleNamespace(start_async=search_api)))
        with patch.object(agents, "Agent", side_effect=scripted_agent), patch(
            "httpx.AsyncClient.send", new=AsyncMock(side_effect=RuntimeError("network disabled in tests"))
        ):
            text, _ = asyncio.run(provider.generate_response("When is the game out?", "persona"))
        self.assertNotIn("https://example.com/official", text)
        self.assertNotIn("Sources:", text)
        model.assert_consumed()
        search_api.assert_awaited_once()
        self.assertIsNone(search_callback.get())

    def test_http_rate_limit_after_search_retries_without_repeating_search(self):
        import json
        import os
        import httpx
        from llm_providers.mistral import MistralProvider
        from llm_providers.mistral_tools import search_callback, usage_callback

        completion_payloads = []
        search_api = AsyncMock(return_value=SimpleNamespace(outputs=[{
            "type": "message.output", "content": [
                {"type": "text", "text": "Official announcement says the date is November 19."},
                {"type": "tool_reference", "url": "https://example.com/official"},
            ],
        }]))

        async def send(request, **kwargs):
            if request.url.path == "/v1/chat/completions":
                completion_payloads.append(json.loads(request.content))
                if len(completion_payloads) == 2:
                    return httpx.Response(429, request=request, json={
                        "object": "error", "message": "Rate limit exceeded",
                        "type": "rate_limited", "code": "1300",
                    })
                if len(completion_payloads) == 1:
                    delta = {"tool_calls": [{"index": 0, "id": "search-call", "type": "function",
                        "function": {"name": "web_search", "arguments": json.dumps({"query": "official release date"})}}]}
                    finish = "tool_calls"
                else:
                    delta = {"content": "The officially announced date is November 19."}
                    finish = "stop"
                chunk = {"id": "test-completion", "object": "chat.completion.chunk", "created": 1,
                    "model": "mistral-small-latest", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
                return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"},
                    content="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")
            if request.method == "GET" and request.url.path.startswith("/v1/models"):
                return httpx.Response(200, request=request, json={
                    "id": "mistral-small-latest", "max_context_length": 32768,
                    "capabilities": {"completion_chat": True, "vision": True},
                })
            if request.url.path == "/v1/datalake/events":
                return httpx.Response(201, request=request, json={})
            raise AssertionError("Unexpected network request in offline test: " + str(request.url))

        with patch.dict(os.environ, {"MISTRAL_API_KEY": "offline-key", "MISTRAL_WEB_SEARCH_ENABLE": "true"}), patch(
            "httpx.AsyncClient.send", new=AsyncMock(side_effect=send)
        ), patch("mistralai.vibe.harness.runtime.completion.providers.utils._BACKOFF_WAIT", return_value=0), patch(
            "mistralai.vibe.harness.runtime.completion.providers.utils._JITTER_WAIT", return_value=0
        ):
            provider = MistralProvider("offline-key", text_models=["mistral-small-latest"])
            provider._client = SimpleNamespace(beta=SimpleNamespace(conversations=SimpleNamespace(start_async=search_api)))
            text, usage = asyncio.run(provider.generate_response("When is it released?", "Keep it concise."))
        self.assertIn("November 19", text)
        self.assertNotIn("https://example.com/official", text)
        self.assertNotIn("Sources:", text)
        self.assertEqual(len(completion_payloads), 3)
        self.assertEqual(completion_payloads[1], completion_payloads[2])
        search_api.assert_awaited_once()
        self.assertEqual((usage.input_tokens, usage.output_tokens), (20, 10))
        self.assertIsNone(search_callback.get())
        self.assertIsNone(usage_callback.get())

    def test_failed_sdk_turn_logs_error_and_falls_back(self):
        from mistralai import agents
        from llm_providers.mistral import MistralProvider

        failure = agents.Failed(
            session_id="s", turn_id="t", cursor="c", text=None,
            error=agents.ProtocolError(message="Rate limit exceeded", code="completion_rate_limited", retryable=True),
        )
        success = agents.Completed(session_id="s2", turn_id="t2", cursor="c2", text="fallback answer", output="fallback answer")
        sessions = []
        def make_agent(**kwargs):
            session = SimpleNamespace(run=AsyncMock(return_value=failure if not sessions else success), cancel=AsyncMock())
            sessions.append(session)
            return SimpleNamespace(start_session=AsyncMock(return_value=session))
        provider = MistralProvider("key", text_models=["first", "second"])
        provider._client = SimpleNamespace()
        with patch.object(agents, "Agent", side_effect=make_agent), self.assertLogs("llm_providers.mistral", level="ERROR") as logs:
            text, _ = asyncio.run(provider.generate_response("q", "ctx"))
        self.assertEqual(text, "fallback answer")
        record = next(record for record in logs.records if record.msg == "provider_model_failed")
        self.assertEqual(record.error_code, "completion_rate_limited")
        self.assertTrue(record.retryable)
        for session in sessions:
            session.cancel.assert_awaited_once()

    def test_fallback_and_timeout_cancel_session(self):
        from mistralai import agents
        from llm_providers.mistral import MistralProvider
        provider = MistralProvider("key", text_models=["first", "second"], timeout_seconds=0.02)
        provider._client = SimpleNamespace()
        sessions = []

        async def slow_run(content):
            await asyncio.sleep(1)

        def make_agent(**kwargs):
            session = SimpleNamespace(run=slow_run, cancel=AsyncMock())
            sessions.append(session)
            return SimpleNamespace(start_session=AsyncMock(return_value=session))

        with patch.object(agents, "Agent", side_effect=make_agent):
            text, _ = asyncio.run(provider.generate_response("q", "ctx"))
        self.assertIsNone(text)
        self.assertEqual(len(sessions), 2)
        for session in sessions:
            session.cancel.assert_awaited_once()

    def test_summaries_disable_search(self):
        from llm_providers.mistral import MistralProvider
        from llm_providers.base import TokenUsage
        provider = MistralProvider("key")
        provider._client = SimpleNamespace()
        provider.generate_response = AsyncMock(return_value=("summary", TokenUsage()))
        asyncio.run(provider.summarize_messages("messages"))
        self.assertFalse(provider.generate_response.call_args.kwargs["allow_search"])

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
