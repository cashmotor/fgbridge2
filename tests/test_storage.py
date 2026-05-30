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

    async def test_session_and_messages(self):
        """测试 Session 切换与消息持久化 (New v0.5)"""
        topic_id = "test_topic"
        # 1. 自动迁移/保存逻辑
        await self.store.save_topic(topic_id, "chat_1", "Developer", "sess_1")
        sessions = await self.store.get_recent_sessions(topic_id)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "sess_1")
        self.assertEqual(sessions[0]["is_active"], 1)

        # 2. 开启新会话 (增加延时确保时间戳递增)
        await asyncio.sleep(1.1)
        await self.store.save_topic(topic_id, "chat_1", "Developer", "sess_2")
        sessions = await self.store.get_recent_sessions(topic_id)
        self.assertEqual(len(sessions), 2)
        # sess_2 应该是 active 且排在第一位
        self.assertEqual(sessions[0]["session_id"], "sess_2")
        self.assertEqual(sessions[0]["is_active"], 1)
        # sess_1 应该不再 active
        sess1 = next(s for s in sessions if s["session_id"] == "sess_1")
        self.assertEqual(sess1["is_active"], 0)

        # 3. 消息记录
        await self.store.add_message("sess_2", "user", "hello")
        await self.store.add_message("sess_2", "assistant", "world")
        msgs = await self.store.get_messages("sess_2")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["content"], "hello")
        self.assertEqual(msgs[1]["role"], "assistant")

        # 4. 更新标题
        await self.store.update_session_title("sess_2", "New Title")
        sessions = await self.store.get_recent_sessions(topic_id)
        self.assertEqual(sessions[0]["title"], "New Title")

if __name__ == "__main__":
    unittest.main()
