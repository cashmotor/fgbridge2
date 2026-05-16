import unittest
import os
import asyncio
from src.storage.state_store import StateStore

class TestStateStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_db = "data/test_fgbridge.db"
        self.store = StateStore(db_path=self.test_db)
        await self.store.init_db()

    async def asyncTearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    async def test_topic_operations(self):
        """测试话题的存取"""
        await self.store.save_topic("topic_1", "chat_A", "Developer", "sess_X")
        topic = await self.store.get_topic("topic_1")
        self.assertIsNotNone(topic)
        self.assertEqual(topic["role"], "Developer")
        self.assertEqual(topic["scope_id"], "chat_A")

    async def test_pending_confirms(self):
        """测试挂起确认的存取"""
        await self.store.add_pending_confirm("conf_1", "topic_1", "sess_X", "shell", "rm -rf")
        confirm = await self.store.get_pending_confirm("conf_1")
        self.assertIsNotNone(confirm)
        self.assertEqual(confirm["action_type"], "shell")
        
        await self.store.remove_pending_confirm("conf_1")
        confirm_after = await self.store.get_pending_confirm("conf_1")
        self.assertIsNone(confirm_after)

if __name__ == "__main__":
    unittest.main()
