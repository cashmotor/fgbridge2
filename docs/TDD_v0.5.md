# 技术设计文档 (TDD) v0.5：机器人菜单与 Session 深度管理

## 1. 业务背景
为解决 Session 上下文过长导致的问题，通过飞书机器人自定义菜单提供 Session 切换与新建能力。引入操作人权限校验确保安全，并实现 Session 本地缓存失效后的“深度重建”机制。同时针对飞书 P2P 标识不一致问题（Menu 使用 open_id，Message 使用 chat_id）引入身份映射与自动迁移逻辑。

---

## 2. 核心定义

### 2.1 菜单事件 ID (Event Keys)
在飞书后台配置以下菜单项及对应的 `event_key`:
*   `FGB_NEW_SESSION`: 开启新会话。
*   `FGB_LIST_HISTORY`: 查看并切换历史会话。

### 2.2 数据模型变更 (SQLite)
#### 2.2.1 `sessions` 表
记录每个 Topic 下的所有会话。
```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    title TEXT,
    created_at INTEGER,
    last_active_time INTEGER,
    is_active INTEGER DEFAULT 0  -- 1 表示当前激活
);
```

#### 2.2.2 `messages` 表
存储对话原始文本，用于重建 Session。
```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL, -- 'user' | 'assistant'
    content TEXT NOT NULL,
    timestamp INTEGER
);
```

#### 2.2.3 `user_chats` 表 (P2P 身份映射)
用于解决飞书菜单事件不携带 `chat_id` 的寻址问题。
```sql
CREATE TABLE IF NOT EXISTS user_chats (
    open_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL
);
```

---

## 3. 流程设计

### 3.1 菜单事件处理 (Menu Event Flow)
1.  **事件接收**: `FeishuWebSocketListener` 注册 `register_p2_application_bot_menu_v6`。
2.  **权限校验**: 提取 `operator.operator_id.open_id`，校验是否存在于 `config.feishu_user_ids`。
3.  **标识对齐**: 
    *   通过 `user_chats` 表查询当前操作人的 `chat_id`。
    *   若存在映射，以 `chat_id` 作为 `topic_id`；否则以 `open_id` 作为临时 `topic_id`。
4.  **响应式体验 (Reactive Feedback)**: 
    *   接收到点击后，无论底层需耗时多久，立即向用户下发一张“处理中”状态卡片，建立即时的视觉确定感。
5.  **路由决策与状态闭环**:
    *   `FGB_NEW_SESSION`: 调用 `acp.session_new`。成功后，使用 `apatch` 更新上述卡片为最终成功状态（并展示 Session ID）。
    *   `FGB_LIST_HISTORY`: 下发历史列表卡片。同时启用“输入即失效”逻辑：若用户未点击卡片而直接输入新消息，该历史列表卡片会自动置灰过期，防范脏状态。

### 3.2 Session 重建机制 (Deep Reconstruction)
当 `acp.session_load(session_id)` 失败（本地 `.session` 丢失）时，进入深度灾备恢复：
1.  调用 `acp.session_new` 获取临时 `new_id` 开启全新空间。
2.  从 `messages` 表按 `timestamp` 顺序读取该 `session_id` 的所有历史记录。
3.  遍历消息，逐条调用 `acp.send(new_id, content)`（静默模式，不产生飞书回复）。
4.  **物理落盘**: 重建完成后，调用 `acp.session_save(session_id)` 强行覆盖为原始文件名。
5.  **原子对齐 (Atomic Alignment)**: 重建成功后，在底层强制将 `acp._active_session_id` 对齐至原始 `session_id`。
    *   *设计权衡*: 摒弃在 Router 顶层盲目赋值的做法。内存标识的更新被严格下放至 `session_load` 和 `_reconstruct_session` 内部。只有在确认底层 RPC 执行成功后，内存状态才允许改变，从而彻底消除“虚假切换”引发的上下文错位风险。

### 3.3 自动身份迁移逻辑 (Identity Migration)
针对 P2P 场景下的标识冲突提供无感修复：
1.  **采集映射**: 每次 `_handle_message` 到达时，强制更新 `user_chats` 映射表。
2.  **触发迁移**: 若检测到当前消息携带 `chat_id` 且为非子任务（Main Chat），但数据库中该用户的 Session 仍挂在 `open_id` 名下。
3.  **执行迁移**: 调用 `migrate_topic_and_sessions` 将 `open_id` 及其关联的 `sessions` / `messages` 全部原子化迁移至 `chat_id`。
4.  **隔离保护**: 该逻辑严格跳过基于 `thread_id` 的子任务 Session，确保专家话题不受干扰。

---

## 4. 关键接口定义

### 4.1 Router 扩展
*   `_handle_menu_event(event_data)`: 处理菜单点击。
*   `_check_operator_permission(open_id)`: 权限校验逻辑。
*   `_switch_to_session(open_id, session_id, card_id)`: 执行会话热切换。
*   `_reconstruct_session(acp, session_id)`: 物理级历史重放。

### 4.2 StateStore 扩展
*   `get_recent_sessions(topic_id, limit=5)`: 获取历史列表。
*   `add_message(session_id, role, content)`: 记录对话。
*   `save_user_chat(open_id, chat_id)`: 维护 ID 映射关系。
*   `migrate_topic_and_sessions(from, to)`: 跨标识数据安全迁移。

---

## 5. 验收要点
*   [x] 配置非法用户点击菜单，系统记录 Warning 并拒绝。
*   [x] 点击“开启新会话”后，P2P 消息能正确路由至新 Session，不再残留旧记忆。
*   [x] 删除本地 `.session` 后点击“切换”，系统能通过重放历史恢复记忆。
*   [x] 验证主轴迁移逻辑不干扰话题子任务的 Session。
