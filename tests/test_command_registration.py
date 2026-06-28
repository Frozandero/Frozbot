import importlib.util
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
    "command registration runtime dependencies are not installed",
)
class CommandRegistrationTests(unittest.TestCase):
    def setUp(self):
        import config

        self.config = config
        self.old_ask_enable = config.ASK_ENABLE
        self.old_imagine_enable = config.IMAGINE_ENABLE
        self.old_elevenlabs_api_key = config.ELEVENLABS_API_KEY

    def tearDown(self):
        self.config.ASK_ENABLE = self.old_ask_enable
        self.config.IMAGINE_ENABLE = self.old_imagine_enable
        self.config.ELEVENLABS_API_KEY = self.old_elevenlabs_api_key

    def _build_tree(self):
        import discord
        from discord import app_commands

        client = discord.Client(intents=discord.Intents.default())
        return client, app_commands.CommandTree(client)

    def test_imagine_command_is_not_registered_when_disabled(self):
        from commands import setup_all_commands

        self.config.ASK_ENABLE = True
        self.config.IMAGINE_ENABLE = False
        self.config.ELEVENLABS_API_KEY = None

        client, tree = self._build_tree()
        setup_all_commands(tree, client)

        self.assertIsNone(tree.get_command("imagine"))
        self.assertIsNotNone(tree.get_command("ask"))

    def test_tts_options_are_hidden_when_tts_is_not_configured(self):
        from commands import setup_all_commands

        self.config.ASK_ENABLE = True
        self.config.IMAGINE_ENABLE = False
        self.config.ELEVENLABS_API_KEY = None

        client, tree = self._build_tree()
        setup_all_commands(tree, client)

        ask_command = tree.get_command("ask")
        say_command = tree.get_command("say")
        summarize_command = tree.get_command("summarize")

        self.assertNotIn("tts", [param.name for param in ask_command.parameters])
        self.assertNotIn("tts", [param.name for param in say_command.parameters])
        self.assertIsNotNone(summarize_command)

    def test_public_queue_commands_are_not_registered(self):
        from commands import setup_all_commands

        self.config.ASK_ENABLE = True
        self.config.IMAGINE_ENABLE = False
        self.config.ELEVENLABS_API_KEY = None

        client, tree = self._build_tree()
        setup_all_commands(tree, client)

        self.assertIsNone(tree.get_command("queue"))
        self.assertIsNone(tree.get_command("cancelrequest"))
        self.assertIsNotNone(tree.get_command("queuestatus"))
        self.assertIsNotNone(tree.get_command("clearqueue"))


if __name__ == "__main__":
    unittest.main()
