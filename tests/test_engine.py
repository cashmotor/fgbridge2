import unittest
import time
from unittest.mock import MagicMock, patch
from src.engine.dispatcher import ACPDispatcher

class TestDispatcher(unittest.TestCase):
    def setUp(self):
        # 模拟 ACPProvider 以避免启动真实进程
        self.patcher = patch('src.engine.dispatcher.ACPProvider')
        self.mock_acp_class = self.patcher.start()
        self.dispatcher = ACPDispatcher()

    def tearDown(self):
        self.patcher.stop()

    def test_get_acp_initialization(self):
        """测试按需唤醒新角色"""
        acp = self.dispatcher.get_acp("Designer")
        self.assertIn("Designer", self.dispatcher.pool)
        self.mock_acp_class.assert_called_once()
        self.assertEqual(acp, self.pool_item("Designer")["provider"])

    def test_get_acp_reuse(self):
        """测试复用已有活跃角色"""
        self.dispatcher.get_acp("Developer")
        self.dispatcher.get_acp("Developer")
        # 仅在第一次时调用构造函数
        self.assertEqual(self.mock_acp_class.call_count, 1)

    def test_cleanup_ttl(self):
        """测试超时自动清理"""
        # 设置一个极短的 TTL 用于测试
        with patch('src.config.config.expert_ttl', 0.1):
            acp = self.dispatcher.get_acp("Tester")
            mock_provider = self.dispatcher.pool["Tester"]["provider"]
            
            time.sleep(0.2)
            self.dispatcher.cleanup()
            
            self.assertNotIn("Tester", self.dispatcher.pool)
            mock_provider.stop.assert_called_once()

    def pool_item(self, role):
        return self.dispatcher.pool.get(role)

if __name__ == "__main__":
    unittest.main()
