import importlib.util
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    all(importlib.util.find_spec(module) is not None for module in ("discord", "dotenv")),
    "config runtime dependencies are not installed",
)
class ConfigCooldownTests(unittest.TestCase):
    def test_seconds_value_wins_over_deprecated_minutes(self):
        import config

        config.CONFIG_DEPRECATION_WARNINGS.clear()
        with patch.dict(
            os.environ,
            {
                "ASK_COMMAND_COOLDOWN_SECONDS": "45",
                "ASK_COMMAND_COOLDOWN_MINUTES": "30",
            },
        ):
            value = config._read_cooldown_seconds(
                "ASK_COMMAND_COOLDOWN_SECONDS",
                "ASK_COMMAND_COOLDOWN_MINUTES",
                1800,
            )

        self.assertEqual(value, 45)
        self.assertIn("deprecated and ignored", config.CONFIG_DEPRECATION_WARNINGS[0])

    def test_deprecated_minutes_are_converted_to_seconds(self):
        import config

        config.CONFIG_DEPRECATION_WARNINGS.clear()
        with patch.dict(
            os.environ,
            {"IMAGINE_COMMAND_COOLDOWN_MINUTES": "2"},
            clear=True,
        ):
            value = config._read_cooldown_seconds(
                "IMAGINE_COMMAND_COOLDOWN_SECONDS",
                "IMAGINE_COMMAND_COOLDOWN_MINUTES",
                900,
            )

        self.assertEqual(value, 120)
        self.assertIn(
            "Converted 2 minute(s) to 120 seconds",
            config.CONFIG_DEPRECATION_WARNINGS[0],
        )


if __name__ == "__main__":
    unittest.main()
