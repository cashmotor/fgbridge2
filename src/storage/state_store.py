import aiosqlite
import time
from loguru import logger
from src.config import config

class StateStore:
    """
    异步 SQLite 状态持久化存储层
    """
    def __init__(self, db_path: str = config.db_path):
        self.db_path = db_path

    async def init_db(self):
        """初始化数据库表结构"""
        async with aiosqlite.connect(self.db_path) as db:
            # 1. 话题路由表 (Scope-Topic 映射)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    topic_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    role TEXT,
                    session_id TEXT,
                    last_active_time INTEGER
                )
            """)
            
            # 2. 挂起的确认请求表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_confirms (
                    confirm_id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL,
                    session_id TEXT,
                    action_type TEXT,
                    message TEXT,
                    created_at INTEGER
                )
            """)
            await db.commit()
            logger.info(f"SQLite 数据库初始化完成: {self.db_path}")

    # --- Topics 管理 ---
    async def get_topic(self, topic_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "topic_id": row[0],
                        "scope_id": row[1],
                        "role": row[2],
                        "session_id": row[3],
                        "last_active_time": row[4]
                    }
                return None

    async def save_topic(self, topic_id: str, scope_id: str, role: str = None, session_id: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO topics (topic_id, scope_id, role, session_id, last_active_time)
                VALUES (?, ?, ?, ?, ?)
            """, (topic_id, scope_id, role, session_id, int(time.time())))
            await db.commit()

    # --- Pending Confirms 管理 ---
    async def add_pending_confirm(self, confirm_id: str, topic_id: str, session_id: str, action_type: str, message: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO pending_confirms (confirm_id, topic_id, session_id, action_type, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (confirm_id, topic_id, session_id, action_type, message, int(time.time())))
            await db.commit()

    async def get_pending_confirm(self, confirm_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM pending_confirms WHERE confirm_id = ?", (confirm_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "confirm_id": row[0],
                        "topic_id": row[1],
                        "session_id": row[2],
                        "action_type": row[3],
                        "message": row[4],
                        "created_at": row[5]
                    }
                return None

    async def remove_pending_confirm(self, confirm_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_confirms WHERE confirm_id = ?", (confirm_id,))
            await db.commit()
