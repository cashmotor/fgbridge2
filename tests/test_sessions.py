import unittest
import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock
from src.engine.router import Router
from src.storage.state_store import StateStore
from src.config import config

class TestSessionManagement(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_db = "data/test_sessions.db"
        self.store = StateStore(db_path=self.test_db)
        await self.store.init_db()
        
        self.mock_dispatcher = MagicMock()
        self.mock_feishu = AsyncMock()
        self.router = Router(self.store, self.mock_dispatcher, self.mock_feishu)
        
        # 默认白名单包含 test_user
        config.feishu_user_ids = ["test_user"]

    async def asyncTearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    async def test_menu_permission_denied(self):
        """测试非白名单用户被拦截 (SES-01)"""
        event_data = {
            "operator": {"operator_id": {"open_id": "evil_user"}},
            "event_key": "FGB_NEW_SESSION"
        }
        await self.router._handle_menu_event(event_data)
        
        # 验证是否发送了无权提示
        self.mock_feishu.send_text.assert_called_once()
        args = self.mock_feishu.send_text.call_args[0]
        self.assertIn("无权操作", str(args))

    async def test_new_session_event(self):
        """测试开启新会话菜单事件 (SES-01)"""
        mock_acp = MagicMock()
        mock_acp.session_new = MagicMock(return_value="new_sess_123")
        self.mock_dispatcher.get_acp.return_value = mock_acp
        
        await self.store.save_user_chat("test_user", "chat_123")
        
        event_data = {
            "operator": {"operator_id": {"open_id": "test_user"}},
            "event_key": "FGB_NEW_SESSION"
        }
        await self.router._handle_menu_event(event_data)
        
        # 验证数据库状态
        topic = await self.store.get_topic("chat_123")
        self.assertEqual(topic["session_id"], "new_sess_123")
        self.mock_feishu.send_text.assert_called_once()
        self.assertIn("🆕 新会话已开启", self.mock_feishu.send_text.call_args[0][1])

    async def test_session_reconstruction(self):
        """测试深度重建逻辑 (SES-03)"""
        session_id = "lost_sess"
        await self.store.add_message(session_id, "user", "msg1")
        await self.store.add_message(session_id, "assistant", "reply1")
        
        mock_acp = MagicMock()
        mock_acp._active_session_id = "temp_sess"
        # 模拟 load 失败
        mock_acp.session_load.return_value = False
        self.mock_dispatcher.get_acp.return_value = mock_acp
        
        # 触发重建
        await self.router._reconstruct_session(mock_acp, session_id)
        
        # 验证 acp.send 是否被调用了两次（回放历史）
        self.assertEqual(mock_acp.send.call_count, 2)
        # 验证最后保存为原始 ID
        mock_acp.session_save.assert_called_with(session_id)

    async def test_switch_session_action(self):
        """测试通过卡片切换会话"""
        await self.store.save_topic("chat_1", "chat_1", "Developer", "sess_old")
        await self.store.save_user_chat("test_user", "chat_1")
        
        mock_acp = MagicMock()
        mock_acp.session_load.return_value = True
        self.mock_dispatcher.get_acp.return_value = mock_acp
        
        event_data = {
            "context": {"open_id": "test_user", "open_message_id": "card_msg_1"},
            "action": {"value": {"decision": "switch_session", "session_id": "sess_target"}}
        }
        await self.router._handle_card_action(event_data)
        
        # 验证数据库更新
        topic = await self.store.get_topic("chat_1")
        self.assertEqual(topic["session_id"], "sess_target")
        # 验证卡片 Patch
        self.mock_feishu.client.im.v1.message.apatch.assert_called_once()

if __name__ == "__main__":
    unittest.main()
