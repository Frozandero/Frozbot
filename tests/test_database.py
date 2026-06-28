import os
import tempfile
import unittest


class DatabaseChannelScopeTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

        import database

        self.database = database
        self.database.init_db()

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmpdir.cleanup()

    def test_memory_counts_are_channel_scoped(self):
        self.database.add_memory("alice", "channel one", 1)
        self.database.add_memory("alice", "channel two", 2)
        self.database.add_memory("*", "generic channel one", 1)

        self.assertEqual(self.database.count_memories_by_user("alice", 1), 1)
        self.assertEqual(self.database.count_memories_by_user("alice", 2), 1)
        self.assertEqual(self.database.count_memories(1), 2)
        self.assertEqual(self.database.count_memories(2), 1)

    def test_delete_memory_is_channel_scoped(self):
        self.database.add_memory("alice", "channel one", 1)
        self.database.add_memory("alice", "channel two", 2)

        channel_two_memory_id = self.database.get_memories_by_user(
            "alice", 2, limit=-1
        )[0][0]

        self.assertFalse(self.database.delete_memory(channel_two_memory_id, 1))
        self.assertEqual(self.database.count_memories_by_user("alice", 2), 1)

        self.assertTrue(self.database.delete_memory(channel_two_memory_id, 2))
        self.assertEqual(self.database.count_memories_by_user("alice", 2), 0)

    def test_empty_multi_user_memory_lookup_returns_empty_dict(self):
        self.assertEqual(self.database.get_memories_for_users([], 1), {})

    def test_memory_lookup_uses_stable_user_id(self):
        self.database.add_memory(
            "alice",
            "likes tea",
            1,
            user_id=123,
            display_name="Alice Display",
        )

        self.assertEqual(
            self.database.count_memories_by_user("renamed_alice", 1, user_id=123),
            1,
        )
        memories = self.database.get_memories_by_user(
            "renamed_alice", 1, user_id=123
        )
        self.assertEqual(memories[0][1], "Alice Display")
        self.assertEqual(memories[0][2], "likes tea")

    def test_legacy_memory_is_backfilled_when_user_id_is_known(self):
        self.database.add_memory("alice", "legacy memory", 1)

        memories = self.database.get_memories_for_user_refs(
            [
                {
                    "key": "id:456",
                    "user_id": 456,
                    "username": "alice",
                    "display_name": "Alice New",
                }
            ],
            1,
        )

        self.assertEqual(memories["id:456"][0][2], "legacy memory")
        self.assertEqual(
            self.database.count_memories_by_user("new_alice", 1, user_id=456),
            1,
        )

    def test_duplicate_ban_is_ignored(self):
        self.database.add_banned_user(123)
        self.database.add_banned_user(123)

        self.assertEqual(self.database.get_banned_users(), [123])


if __name__ == "__main__":
    unittest.main()
