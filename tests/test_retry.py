import importlib.util
import os
import tempfile
import unittest


@unittest.skipUnless(
    (
        importlib.util.find_spec("PIL") is not None
        and importlib.util.find_spec("discord") is not None
        and importlib.util.find_spec("dotenv") is not None
    ),
    "Pillow, discord.py, and python-dotenv are required",
)
class RetryPersistenceTests(unittest.TestCase):
    def setUp(self):
        import config

        self.config = config
        self._old_temp_media_dir = config.TEMP_MEDIA_DIR
        self._old_ask_images_dir = config.ASK_IMAGES_DIR
        self._old_retry_records_dir = config.RETRY_RECORDS_DIR

        self._tmpdir = tempfile.TemporaryDirectory()
        config.TEMP_MEDIA_DIR = self._tmpdir.name
        config.ASK_IMAGES_DIR = os.path.join(self._tmpdir.name, "ask_images")
        config.RETRY_RECORDS_DIR = os.path.join(self._tmpdir.name, "retry_records")
        config.RETRY_MEDIA_TEMP.clear()
        config.RETRY_CONTEXT_TEMP.clear()

    def tearDown(self):
        self.config.TEMP_MEDIA_DIR = self._old_temp_media_dir
        self.config.ASK_IMAGES_DIR = self._old_ask_images_dir
        self.config.RETRY_RECORDS_DIR = self._old_retry_records_dir
        self.config.RETRY_MEDIA_TEMP.clear()
        self.config.RETRY_CONTEXT_TEMP.clear()
        self._tmpdir.cleanup()

    def test_retry_record_survives_empty_memory_cache(self):
        from PIL import Image
        from retry import load_retry_record, save_retry_record

        custom_id = "retry_123_abcdef_token_1000"
        image = Image.new("RGB", (2, 2), color=(255, 0, 0))

        saved = save_retry_record(
            custom_id=custom_id,
            user_id=123,
            question="try again?",
            context_string="server context",
            tts=True,
            media_parts=[image],
        )
        self.assertTrue(saved)

        self.config.RETRY_MEDIA_TEMP.clear()
        self.config.RETRY_CONTEXT_TEMP.clear()

        record = load_retry_record(custom_id)

        self.assertIsNotNone(record)
        self.assertEqual(record["user_id"], 123)
        self.assertEqual(record["question"], "try again?")
        self.assertEqual(record["context_string"], "server context")
        self.assertTrue(record["tts"])
        self.assertEqual(len(record["media_parts"]), 1)
        self.assertIsNone(load_retry_record(custom_id))


if __name__ == "__main__":
    unittest.main()
