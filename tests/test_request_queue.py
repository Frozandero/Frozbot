import asyncio
import datetime
import importlib.util
import itertools
import unittest
import uuid
from unittest.mock import patch


@unittest.skipUnless(
    all(
        importlib.util.find_spec(module) is not None
        for module in (
            "better_profanity",
            "discord",
            "dotenv",
            "elevenlabs",
            "markdown_it",
            "mdit_plain",
            "PIL",
        )
    ),
    "request queue runtime dependencies are not installed",
)
class RequestQueuePriorityTests(unittest.TestCase):
    def setUp(self):
        import config
        import request_queue

        self.config = config
        self.request_queue = request_queue
        self._old_sequence = config.REQUEST_QUEUE_SEQUENCE
        self._old_queue = config.REQUEST_QUEUE
        self._old_max_concurrent = config.MAX_CONCURRENT_REQUESTS
        config.REQUEST_QUEUE_SEQUENCE = itertools.count()
        config.REQUEST_QUEUE = asyncio.PriorityQueue()
        config.MAX_CONCURRENT_REQUESTS = 1
        request_queue._PENDING_REQUESTS.clear()
        request_queue._ACTIVE_REQUESTS.clear()
        request_queue._CANCELLED_REQUESTS.clear()

    def tearDown(self):
        self.config.REQUEST_QUEUE_SEQUENCE = self._old_sequence
        self.config.REQUEST_QUEUE = self._old_queue
        self.config.MAX_CONCURRENT_REQUESTS = self._old_max_concurrent
        self.request_queue._PENDING_REQUESTS.clear()
        self.request_queue._ACTIVE_REQUESTS.clear()
        self.request_queue._CANCELLED_REQUESTS.clear()

    def test_higher_priority_request_is_processed_first(self):
        from request_queue import (
            QueuedRequest,
            RequestType,
            _build_queue_item,
            _unpack_queue_item,
        )

        low_priority = QueuedRequest(
            request_id="low",
            request_type=RequestType.ASK,
            interaction=None,
            question="low",
            context_string="",
            user_id=1,
            timestamp=datetime.datetime.now(),
            priority=0,
        )
        high_priority = QueuedRequest(
            request_id="high",
            request_type=RequestType.ASK,
            interaction=None,
            question="high",
            context_string="",
            user_id=2,
            timestamp=datetime.datetime.now(),
            priority=2,
        )

        async def get_ordered_ids():
            queue = asyncio.PriorityQueue()
            await queue.put(_build_queue_item(low_priority))
            await queue.put(_build_queue_item(high_priority))
            first = _unpack_queue_item(await queue.get())
            second = _unpack_queue_item(await queue.get())
            return first.request_id, second.request_id

        self.assertEqual(asyncio.run(get_ordered_ids()), ("high", "low"))

    def test_add_request_uses_uuid_request_id(self):
        from request_queue import RequestType, add_request_to_queue

        async def add_request():
            with patch("request_queue.ensure_queue_workers", lambda: None):
                return await add_request_to_queue(
                    RequestType.ASK,
                    None,
                    "question",
                    "context",
                    user_id=123,
                )

        request_id = asyncio.run(add_request())

        self.assertEqual(str(uuid.UUID(request_id)), request_id)

    def test_cancel_queued_request_marks_pending_request_cancelled(self):
        from request_queue import (
            RequestType,
            add_request_to_queue,
            cancel_queued_request,
            get_request_status,
        )

        async def add_request():
            with patch("request_queue.ensure_queue_workers", lambda: None):
                return await add_request_to_queue(
                    RequestType.ASK,
                    None,
                    "question",
                    "context",
                    user_id=123,
                )

        request_id = asyncio.run(add_request())
        result = cancel_queued_request(request_id, user_id=123)

        self.assertTrue(result.cancelled)
        self.assertEqual(get_request_status(request_id)["state"], "cancelled")

    def test_cancel_queued_request_accepts_unambiguous_prefix(self):
        from request_queue import RequestType, add_request_to_queue, cancel_queued_request

        async def add_request():
            with patch("request_queue.ensure_queue_workers", lambda: None):
                return await add_request_to_queue(
                    RequestType.ASK,
                    None,
                    "question",
                    "context",
                    user_id=123,
                )

        request_id = asyncio.run(add_request())
        result = cancel_queued_request(request_id[:8], user_id=123)

        self.assertTrue(result.cancelled)
        self.assertEqual(result.request_id, request_id)


if __name__ == "__main__":
    unittest.main()
