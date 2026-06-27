import importlib.util
import unittest
from datetime import datetime, timezone


class FakeUser:
    def __init__(self, user_id=123, name="tester"):
        self.id = user_id
        self.name = name
        self.discriminator = "0"
        self.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)


@unittest.skipUnless(
    importlib.util.find_spec("discord") is not None,
    "discord.py is not installed",
)
class IQTests(unittest.TestCase):
    def test_iq_is_deterministic_for_same_user(self):
        from iq import compute_deterministic_iq

        user = FakeUser()

        first = compute_deterministic_iq(user)
        second = compute_deterministic_iq(user)

        self.assertEqual(first, second)

    def test_iq_changes_with_stable_identifier(self):
        from iq import compute_deterministic_iq

        first_user = FakeUser(user_id=123)
        second_user = FakeUser(user_id=456)

        self.assertNotEqual(
            compute_deterministic_iq(first_user),
            compute_deterministic_iq(second_user),
        )


if __name__ == "__main__":
    unittest.main()
