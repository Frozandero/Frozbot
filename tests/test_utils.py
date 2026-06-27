import importlib.util
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("better_profanity") is not None,
    "better_profanity is not installed",
)
class UtilsTests(unittest.TestCase):
    def test_sanitize_system_prompt_removes_extreme_term_pattern(self):
        from utils import sanitize_system_prompt

        sanitized = sanitize_system_prompt("Do not repeat t3rr0rist variants.")

        self.assertIn("[removed]", sanitized)
        self.assertNotIn("t3rr0rist", sanitized)

    def test_truncate_text_preserves_short_text(self):
        from utils import truncate_text

        self.assertEqual(truncate_text("hello", max_length=10), "hello")

    def test_truncate_text_adds_ellipsis(self):
        from utils import truncate_text

        self.assertEqual(truncate_text("abcdefghij", max_length=6), "abc...")


if __name__ == "__main__":
    unittest.main()
