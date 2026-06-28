import asyncio
import importlib.util
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("discord") is not None,
    "discord.py is not installed",
)
class EmojiReplacementTests(unittest.TestCase):
    def test_replaces_plain_custom_emoji_names(self):
        from emoji import replace_guild_emojis_in_text

        guild = FakeGuild(
            cached_emojis=[
                FakeEmoji("GrankDespair", "<:GrankDespair:111>"),
                FakeEmoji("GrankL", "<a:GrankL:222>"),
            ]
        )

        result = asyncio.run(
            replace_guild_emojis_in_text(
                ':GrankDespair: *sigh* relationship. :GrankL:',
                guild,
            )
        )

        self.assertEqual(
            result,
            '<:GrankDespair:111> *sigh* relationship. <a:GrankL:222>',
        )
        self.assertFalse(guild.fetch_called)

    def test_replaces_escaped_custom_emoji_names(self):
        from emoji import replace_guild_emojis_in_text

        guild = FakeGuild(
            cached_emojis=[
                FakeEmoji("GrankDespair", "<:GrankDespair:111>"),
                FakeEmoji("GrankL", "<a:GrankL:222>"),
            ]
        )

        result = asyncio.run(
            replace_guild_emojis_in_text(
                r'\:GrankDespair\: *sigh* relationship. \:GrankL\:',
                guild,
            )
        )

        self.assertEqual(
            result,
            '<:GrankDespair:111> *sigh* relationship. <a:GrankL:222>',
        )

    def test_fetches_missing_custom_emoji_names(self):
        from emoji import replace_guild_emojis_in_text

        guild = FakeGuild(
            cached_emojis=[FakeEmoji("GrankHi", "<a:GrankHi:333>")],
            fetched_emojis=[FakeEmoji("GrankDespair", "<:GrankDespair:111>")],
        )

        result = asyncio.run(
            replace_guild_emojis_in_text(":GrankDespair: hello", guild)
        )

        self.assertEqual(result, "<:GrankDespair:111> hello")
        self.assertTrue(guild.fetch_called)

    def test_does_not_rewrite_existing_discord_emoji_mentions(self):
        from emoji import replace_guild_emojis_in_text

        guild = FakeGuild(
            cached_emojis=[FakeEmoji("GrankHi", "<a:GrankHi:333>")]
        )

        result = asyncio.run(
            replace_guild_emojis_in_text("<a:GrankHi:333> :GrankHi:", guild)
        )

        self.assertEqual(result, "<a:GrankHi:333> <a:GrankHi:333>")


class FakeEmoji:
    def __init__(self, name, text):
        self.name = name
        self.text = text

    def __str__(self):
        return self.text


class FakeGuild:
    def __init__(self, cached_emojis=None, fetched_emojis=None):
        self.id = 123
        self.emojis = cached_emojis or []
        self.fetched_emojis = fetched_emojis or []
        self.fetch_called = False

    async def fetch_emojis(self):
        self.fetch_called = True
        return self.fetched_emojis


if __name__ == "__main__":
    unittest.main()
