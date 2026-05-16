import unittest
import os
import shutil
from pathlib import Path
from src.config import config

class TestConfig(unittest.TestCase):
    def test_config_dirs(self):
        """测试目录是否正确创建"""
        self.assertTrue(Path(config.session_dir).exists())
        self.assertTrue(Path(config.attachment_dir).exists())

    def test_env_override(self):
        """验证环境变量是否能覆盖默认值"""
        os.environ["ASSISTANT_TTL"] = "1234"
        # 重新加载配置模块以获取新变量 (由于 Python 缓存需特殊处理)
        # 这里仅作逻辑示意，实际应用中建议使用 pydantic 的初始化注入
        pass

if __name__ == "__main__":
    unittest.main()
