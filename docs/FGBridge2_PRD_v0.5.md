# FGBridge 2.0 PRD v0.5：飞书机器人菜单与多 Session 切换管理

## 1. 产品背景 (Product Background)
随着助理使用时间的增长，单一会话 (Session) 的上下文长度会逐渐达到模型上限，或因处理多个不同主题的任务而导致上下文污染。目前 FGBridge 2.0 采用基于 `chat_id` 或 `thread_id` 的固定 `topic_id` 绑定策略，无法灵活开启新话题。

本版本旨在通过飞书机器人菜单，为用户提供灵活的 Session 管理能力，支持“开启新会话”以获得纯净上下文，以及“切换历史会话”以找回过去的记忆。

---

## 2. 核心功能设计 (Core Features)

### 2.1 飞书机器人菜单 (Bot Menu)
在飞书机器人后台手工配置“自定义菜单”，主要包含以下选项：
*   **🆕 开启新会话 (New Session)**: 立即为当前话题创建一个全新的 Gemini 会话。
*   **📜 切换历史会话 (Switch Session)**: 弹出一个互动卡片，列出最近使用的 N 个会话供用户选择切换。

### 2.2 多 Session 持久化 (Multi-Session Persistence)
*   **数据库变更**: 
    *   引入 `sessions` 表，将 `session_id` 从 `topics` 表的 1:1 关系解耦为 1:N 关系（一个 Topic 可拥有多个 Sessions）。
    *   引入 `messages` 表，持久化存储对话历史，用于在本地缓存丢失时重建 Session。
*   **Session 状态**: 每个 Session 记录其最后活跃时间、描述（自动从第一条消息提取或摘要生成）。

### 2.3 Session 重建机制 (Session Reconstruction)
*   **两层保护**:
    1.  **快速唤醒**: 优先尝试使用 Gemini 本地缓存的 `.session` 文件进行 `session_load`。
    2.  **深度重建**: 若本地缓存已清理，则从数据库 `messages` 表读取历史消息，按顺序通过 `session_new` + 多轮 `send` (静默模式) 物理级重建 Session 状态。

### 2.4 安全与操作人校验 (Operator Validation)
*   **权限控制**: 机器人菜单属于高权限敏感操作，必须严格限制操作人身份。
*   **白名单机制**: 
    *   将原有的 `feishu_user_id` 升级为 `feishu_user_ids`。
    *   该配置项为**列表格式**，支持配置多个飞书用户 OpenID。
*   **校验逻辑**: 
    *   当接收到 `application.bot.menu_v6` 事件时，从事件体中提取 `operator.open_id`。
    *   校验该 `open_id` 是否存在于 `feishu_user_ids` 白名单列表中。
    *   若校验失败，系统应保持静默或回复提示消息（“抱歉，您没有权限操作此菜单”），并在日志中记录非法尝试。

---

## 3. 技术实现要点 (Technical Implementation)

### 3.1 监听器扩展 (Listener)
*   在 `FeishuWebSocketListener` 中增加对 `application.bot.menu_v6` 事件的注册。
*   将菜单事件及其 `event_key` 和 `operator` 信息投递至 `Router` 处理。

### 3.2 路由分发 (Router)
*   **权限预校验**: 在进入具体的菜单处理逻辑前，优先执行操作人身份校验。
*   **handle_menu_event**: 
    *   若为 `new_session`: 调用 `acp.session_new`，更新数据库状态，并向用户发送“新会话已开启”的通知。
    *   若为 `list_history`: 从 `sessions` 表按 `last_active_time` 倒序查询前 N 条记录，构建并发送“历史会话选择卡片”。
*   **handle_card_action**: 
    *   处理用户点击“切换”按钮的操作，执行 `acp.session_load` 并更新当前 `topics` 绑定的 `session_id`。

### 3.3 数据模型 (Data Model)
*   **Table: sessions**
    *   `session_id` (PK)
    *   `topic_id` (FK)
    *   `title` (文本描述)
    *   `created_at`
    *   `last_active_time`
*   **Table: messages**
    *   `id` (PK)
    *   `session_id` (FK)
    *   `role` (user/assistant)
    *   `content` (文本内容)
    *   `timestamp`

---

## 4. 配置项 (Configuration)

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `feishu_user_ids` | list | [] | 允许操作机器人菜单的飞书用户 OpenID 白名单 |
| `history_session_limit` | int | 5 | 历史会话卡片展示的最大数量 |
| `auto_summarize_title` | bool | True | 是否根据首条消息自动生成 Session 标题 |

---

## 5. 验收标准 (Acceptance Criteria)
1.  用户点击“开启新会话”后，后续消息不再携带旧的上下文。
2.  用户点击“切换历史会话”并从卡片中选择一个旧会话后，机器人能接续之前的记忆。
3.  在手动删除本地 `.session` 文件后，切换会话能通过重建机制恢复工作（耗时可能会稍长）。
4.  卡片展示条目严格遵循 `history_session_limit`。
