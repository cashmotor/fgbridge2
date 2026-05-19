import time
import json
from typing import Dict, Optional
from pathlib import Path
from loguru import logger
from src.provider.acp import ACPProvider
from src.config import config

class ACPDispatcher:
    """
    ACP 进程调度池，管理不同角色的 ACP 进程及其生命周期 (TTL)
    """
    def __init__(self):
        # role -> {provider: ACPProvider, last_active: float}
        self.pool: Dict[str, Dict] = {}
        self._role_prompts: Dict[str, str] = self._load_role_prompts()

    def _load_role_prompts(self) -> Dict[str, str]:
        """从配置文件加载角色提示词"""
        path = Path(config.role_config_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载角色提示词失败: {e}")
        return {}

    def get_acp(self, role: str) -> ACPProvider:
        """获取或唤醒指定角色的 ACP 进程"""
        now = time.time()
        
        # 角色提示词获取逻辑
        role_prompt = self._role_prompts.get(role)
        if not role_prompt:
            fallback_prompt = "You are a helpful assistant."
            logger.warning(f"角色 '{role}' 未在 {config.role_config_path} 中配置提示词，将使用默认值。")
            role_prompt = fallback_prompt

        if role in self.pool:
            item = self.pool[role]
            if item["provider"]._is_running:
                item["last_active"] = now
                return item["provider"]
            else:
                logger.warning(f"检测到角色 {role} 的 ACP 进程已停止，正在重启...")
                item["provider"].start(system_prompt=role_prompt)
                item["last_active"] = now
                return item["provider"]

        # 启动新进程
        logger.info(f"正在唤醒角色 {role} 的 ACP 进程...")
        provider = ACPProvider()
        provider.start(system_prompt=role_prompt)
        self.pool[role] = {"provider": provider, "last_active": now}
        return provider

    def cleanup(self):
        """执行 TTL 检查并清理过期进程"""
        now = time.time()
        to_remove = []
        for role, item in self.pool.items():
            ttl = config.assistant_ttl if role == config.assistant_role else config.expert_ttl
            if now - item["last_active"] > ttl:
                logger.info(f"角色 {role} 的进程已超过 TTL ({ttl}s)，正在执行惰性退出...")
                item["provider"].stop()
                to_remove.append(role)
        
        for role in to_remove:
            del self.pool[role]

    def stop_all(self):
        """关闭所有进程"""
        for item in self.pool.values():
            item["provider"].stop()
        self.pool.clear()
