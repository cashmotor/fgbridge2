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
                    last_active_time INTEGER
                )
            """)
            
            # --- 自动升级：为 topics 表添加 last_full_content 字段 ---
            async with db.execute("PRAGMA table_info(topics)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if "last_full_content" not in columns:
                    logger.info("数据库升级: 为 topics 表添加 last_full_content 字段")
                    await db.execute("ALTER TABLE topics ADD COLUMN last_full_content TEXT")
            
            # 2. 挂起的确认请求表 (基础结构)
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

            # --- 自动升级：检查并添加 reaction_id 字段 ---
            async with db.execute("PRAGMA table_info(pending_confirms)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if "reaction_id" not in columns:
                    logger.info("数据库升级: 为 pending_confirms 表添加 reaction_id 字段")
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN reaction_id TEXT")
            
            await db.commit()
            logger.info(f"SQLite 数据库初始化完成: {self.db_path}")

    # --- Topics 管理 ---
    async def get_topic(self, topic_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    content = row[4]
                    # 防御性逻辑：如果数据库里是空数字或空值，强制转为 None
                    if not content or content == 0 or content == "0":
                        content = None
                        
                    return {
                        "topic_id": row[0],
                        "scope_id": row[1],
                        "role": row[2],
                        "session_id": row[3],
                        "last_full_content": content,
                        "last_active_time": row[5]
                    }
                return None

    async def save_topic(self, topic_id: str, scope_id: str, role: str = None, session_id: str = None, last_full_content: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            if last_full_content is not None:
                await db.execute("""
                    INSERT OR REPLACE INTO topics (topic_id, scope_id, role, session_id, last_full_content, last_active_time)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (topic_id, scope_id, role, session_id, last_full_content, int(time.time())))
            else:
                # 兼容不更新内容的情况
                await db.execute("""
                    INSERT INTO topics (topic_id, scope_id, role, session_id, last_active_time)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(topic_id) DO UPDATE SET
                        scope_id=excluded.scope_id,
                        role=COALESCE(excluded.role, topics.role),
                        session_id=COALESCE(excluded.session_id, topics.session_id),
                        last_active_time=excluded.last_active_time
                """, (topic_id, scope_id, role, session_id, int(time.time())))
            await db.commit()

    # --- Pending Confirms 管理 ---
    async def add_pending_confirm(self, confirm_id: str, topic_id: str, session_id: str, action_type: str, message: str, reaction_id: str = None):
        """添加挂起的确认请求 (非阻塞友好)"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO pending_confirms (confirm_id, topic_id, session_id, action_type, message, reaction_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (confirm_id, topic_id, session_id, action_type, message, reaction_id, int(time.time())))
                await db.commit()
        except Exception as e:
            logger.error(f"保存待确认状态失败: {e}")

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
                        "reaction_id": row[5],
                        "created_at": row[6]
                    }
                return None

    async def get_pending_confirms_by_topic(self, topic_id: str):
        """获取指定话题下所有挂起的请求"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM pending_confirms WHERE topic_id = ?", (topic_id,)) as cursor:
                rows = await cursor.fetchall()
                return [{
                    "confirm_id": row[0],
                    "topic_id": row[1],
                    "session_id": row[2],
                    "action_type": row[3],
                    "message": row[4],
                    "reaction_id": row[5],
                    "created_at": row[6]
                } for row in rows]

    async def save_reaction(self, message_id: str, reaction_id: str):
        """临时记录 Reaction ID (非阻塞设计)"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO pending_confirms (confirm_id, topic_id, reaction_id, created_at)
                    VALUES (?, ?, ?, ?)
                """, (f"react_{message_id}", message_id, reaction_id, int(time.time())))
                await db.commit()
        except Exception as e:
            logger.error(f"保存 Reaction 状态失败 (非阻塞): {e}")

    async def remove_pending_confirm(self, confirm_id: str):
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM pending_confirms WHERE confirm_id = ?", (confirm_id,))
                await db.commit()
        except Exception as e:
            logger.error(f"移除 Pending 状态失败: {e}")
