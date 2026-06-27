import asyncio
import datetime
import importlib.util
import itertools
import unittest


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

        self.config = config
        self._old_sequence = config.REQUEST_QUEUE_SEQUENCE
        config.REQUEST_QUEUE_SEQUENCE = itertools.count()

    def tearDown(self):
        self.config.REQUEST_QUEUE_SEQUENCE = self._old_sequence

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


if __name__ == "__main__":
    unittest.main()
