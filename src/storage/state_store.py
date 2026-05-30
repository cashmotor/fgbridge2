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
            
            # 2. 会话详情表 (New v0.5)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL,
                    title TEXT,
                    created_at INTEGER,
                    last_active_time INTEGER,
                    is_active INTEGER DEFAULT 0
                )
            """)

            # 3. 消息历史表 (New v0.5)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp INTEGER
                )
            """)

            # 4. 挂起的确认请求表 (增强型)
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

            # 5. 用户与 P2P 聊天映射表 (New v0.5 修复 Menu 关联问题)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_chats (
                    open_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL
                )
            """)

            # --- 自动升级与数据迁移 (Compatibility) ---
            async with db.execute("PRAGMA table_info(topics)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if "last_full_content" not in columns:
                    await db.execute("ALTER TABLE topics ADD COLUMN last_full_content TEXT")
                if "turn_count" not in columns:
                    await db.execute("ALTER TABLE topics ADD COLUMN turn_count INTEGER DEFAULT 0")
            
            # --- 自动升级 Pending Confirms ---
            async with db.execute("PRAGMA table_info(pending_confirms)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if "reaction_id" not in columns:
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN reaction_id TEXT")
                if "confirm_step" not in columns:
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN confirm_step INTEGER DEFAULT 1")
                if "msg_id" not in columns:
                    await db.execute("ALTER TABLE pending_confirms ADD COLUMN msg_id TEXT")
            
            # 将旧版 topics 中的 session_id 迁移到 sessions 表 (如果不存在)
            async with db.execute("SELECT topic_id, session_id, last_active_time FROM topics WHERE session_id IS NOT NULL") as cursor:
                old_topics = await cursor.fetchall()
                for t_id, s_id, last_active in old_topics:
                    await db.execute("""
                        INSERT OR IGNORE INTO sessions (session_id, topic_id, title, created_at, last_active_time, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """, (s_id, t_id, "历史会话", last_active or int(time.time()), last_active or int(time.time())))

            await db.commit()
            logger.info(f"SQLite 数据库初始化与迁移完成: {self.db_path}")

    # --- Topics 管理 ---
    async def get_topic(self, topic_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_topic(self, topic_id: str, scope_id: str, role: str = None, session_id: str = None, last_full_content: str = None, turn_count: int = None):
        async with aiosqlite.connect(self.db_path) as db:
            now = int(time.time())
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
            """, (topic_id, scope_id, role, session_id, last_full_content, turn_count, now))
            
            # 同步更新 sessions 表的激活状态 (New v0.5)
            if session_id:
                await db.execute("UPDATE sessions SET is_active = 0 WHERE topic_id = ?", (topic_id,))
                await db.execute("""
                    INSERT INTO sessions (session_id, topic_id, title, created_at, last_active_time, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(session_id) DO UPDATE SET
                        is_active = 1,
                        last_active_time = excluded.last_active_time
                """, (session_id, topic_id, "当前会话", now, now))
            
            await db.commit()

    # --- Sessions & Messages 管理 (New v0.5) ---
    async def get_recent_sessions(self, topic_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM sessions 
                WHERE topic_id = ? 
                ORDER BY last_active_time DESC 
                LIMIT ?
            """, (topic_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def add_message(self, session_id: str, role: str, content: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO messages (session_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
            """, (session_id, role, content, int(time.time())))
            await db.commit()

    async def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_session_title(self, session_id: str, title: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE sessions SET title = ? WHERE session_id = ?", (title, session_id))
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

    async def remove_pending_confirm(self, confirm_id: str) -> int:
        """删除挂起的确认请求，返回受影响的行数"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("DELETE FROM pending_confirms WHERE confirm_id = ?", (confirm_id,)) as cursor:
                count = cursor.rowcount
                await db.commit()
                return count

    # --- 用户与 P2P 映射及迁移管理 ---
    async def save_user_chat(self, open_id: str, chat_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_chats (open_id, chat_id)
                VALUES (?, ?)
            """, (open_id, chat_id))
            await db.commit()

    async def get_chat_id_by_open_id(self, open_id: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT chat_id FROM user_chats WHERE open_id = ?", (open_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def migrate_topic_and_sessions(self, from_topic_id: str, to_topic_id: str):
        """将 from_topic_id 的所有数据迁移到 to_topic_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM topics WHERE topic_id = ?", (from_topic_id,)) as cursor:
                from_topic = await cursor.fetchone()
                
            if from_topic:
                now = int(time.time())
                await db.execute("""
                    INSERT INTO topics (topic_id, scope_id, role, session_id, last_full_content, turn_count, last_active_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(topic_id) DO UPDATE SET
                        role=excluded.role,
                        session_id=excluded.session_id,
                        turn_count=excluded.turn_count,
                        last_active_time=excluded.last_active_time
                """, (to_topic_id, to_topic_id, from_topic["role"], from_topic["session_id"], from_topic["last_full_content"], from_topic["turn_count"], now))
                
                await db.execute("UPDATE sessions SET topic_id = ? WHERE topic_id = ?", (to_topic_id, from_topic_id))
                await db.execute("UPDATE pending_confirms SET topic_id = ? WHERE topic_id = ?", (to_topic_id, from_topic_id))
                await db.execute("DELETE FROM topics WHERE topic_id = ?", (from_topic_id,))
                await db.commit()

