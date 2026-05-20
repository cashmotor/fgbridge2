import aiosqlite
import time
import json
from typing import Optional, List, Dict, Any
from loguru import logger
from src.config import config

class StateStore:
    """
    异步 SQLite 状态持久化存储层
    """
    def __init__(self, db_path: str = config.db_path):
        self.db_path = db_path

    async def init_db(self):
        """初始化数据库表结构并执行自动升级"""
        async with aiosqlite.connect(self.db_path) as db:
            # 1. 话题路由表 (Scope-Topic 映射)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    topic_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    role TEXT,
                    session_id TEXT,
                    last_full_content TEXT,
                    turn_count INTEGER DEFAULT 0,
                    last_active_time INTEGER
                )
            """)
            
            # --- 自动升级 Topics ---
            async with db.execute("PRAGMA table_info(topics)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if "last_full_content" not in columns:
                    await db.execute("ALTER TABLE topics ADD COLUMN last_full_content TEXT")
                if "turn_count" not in columns:
                    await db.execute("ALTER TABLE topics ADD COLUMN turn_count INTEGER DEFAULT 0")
            
            # 2. 挂起的确认请求表 (增强型)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_confirms (
                    confirm_id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL,
                    session_id TEXT,
                    action_type TEXT,
                    message TEXT,
                    reaction_id TEXT,
                    confirm_step INTEGER DEFAULT 1,
                    msg_id TEXT,
                    created_at INTEGER
                )
            """)

            # --- 自动升级 Pending Confirms ---
            async with db.execute("PRAGMA table_info(pending_confirms)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if "reaction_id" not in columns:
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN reaction_id TEXT")
                if "confirm_step" not in columns:
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN confirm_step INTEGER DEFAULT 1")
                if "msg_id" not in columns:
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN msg_id TEXT")
            
            await db.commit()
            logger.info(f"SQLite 数据库初始化完成: {self.db_path}")

    # --- Topics 管理 ---
    async def get_topic(self, topic_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_topic(self, topic_id: str, scope_id: str, role: str = None, session_id: str = None, last_full_content: str = None, turn_count: int = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO topics (topic_id, scope_id, role, session_id, last_full_content, turn_count, last_active_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                    scope_id=excluded.scope_id,
                    role=COALESCE(excluded.role, topics.role),
                    session_id=COALESCE(excluded.session_id, topics.session_id),
                    last_full_content=COALESCE(excluded.last_full_content, topics.last_full_content),
                    turn_count=COALESCE(excluded.turn_count, topics.turn_count),
                    last_active_time=excluded.last_active_time
            """, (topic_id, scope_id, role, session_id, last_full_content, turn_count, int(time.time())))
            await db.commit()

    # --- Pending Confirms 管理 ---
    async def add_pending_confirm(self, confirm_id: str, topic_id: str, session_id: str, action_type: str, message: str, reaction_id: str = None, confirm_step: int = 1, msg_id: str = None):
        """添加挂起的确认请求"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO pending_confirms (confirm_id, topic_id, session_id, action_type, message, reaction_id, confirm_step, msg_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (confirm_id, topic_id, session_id, action_type, message, reaction_id, confirm_step, msg_id, int(time.time())))
            await db.commit()

    async def update_pending_confirm_step(self, confirm_id: str, step: int, msg_id: str = None):
        """更新授权步骤和关联消息 ID"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE pending_confirms SET confirm_step = ?, msg_id = ? WHERE confirm_id = ?", (step, msg_id, confirm_id))
            await db.commit()

    async def get_pending_confirm(self, confirm_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pending_confirms WHERE confirm_id = ?", (confirm_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_pending_confirm_by_msg_id(self, msg_id: str) -> Optional[Dict[str, Any]]:
        """通过消息 ID 查找授权请求 (用于 Reaction 匹配)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pending_confirms WHERE msg_id = ?", (msg_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_pending_confirms_by_topic(self, topic_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pending_confirms WHERE topic_id = ?", (topic_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def remove_pending_confirm(self, confirm_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_confirms WHERE confirm_id = ?", (confirm_id,))
            await db.commit()
