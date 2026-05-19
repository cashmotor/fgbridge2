# 技术设计文档 (TDD) v0.2：性能优化与交互增强

## 1. 文档概述
### 1.1 目的
本文档旨在对 FGBridge 2.0 核心架构进行增量设计方案说明，重点解决响应内容冗余、授权时效性安全风险、会话管理 IO 性能瓶颈以及 UI 交互体感增强（气泡与卡片化通知）。

---

## 2. 核心功能设计方案

### 2.1 响应内容精准裁剪：原生回合模式 (Native Turn-based Mode)
**背景**：Gemini ACP 0.38+ 协议在本质上是回合制（Turn-based）的。通过深入分析发现，手动在客户端侧执行文本差分（Trimming）容易受到换行符差异、时间戳标签变动等格式微差的干扰，导致“雪球效应”式的冗余叠加。

**方案实现细节**：
- **核心逻辑**：完全信任 Gemini CLI 的内部 Session History 管理机制。通过 `session_id` 的持久化与寻回，让 CLI 引擎自动处理上下文关联。
- **增量获取策略**：
  1. **流式块优先 (Streaming Delta)**：强制依赖 `agent_message_chunk` 级通知。该级别由 CLI 实时发送，天然仅包含当前回合的“增量增量”。
  2. **弃用手动合成**：废弃 `last_full_content` 的文本合成逻辑，不再在 `ACPProvider` 中手动拼接历史与新回复。
- **状态追踪 (Turn Tracking)**：
  - 在数据库 `topics` 表中引入 `turn_count` 字段。
  - 虽然 CLI 不提供官方的 `turn_id`，但 FGB 通过应用层自增记录对话回合，用于审计和状态校验。
- **重启恢复流**：
  - **Restore**：重启后，`Router` 仅通过 `session_load(session_id)` 激活 CLI 内部状态。
  - **Silent Flush (历史冲刷)**：针对 ACP 协议在冷启动后首次提问会强制带出所有历史的问题，引入“牺牲回合”机制。在发送用户正式消息前，先静默发送一个配置化的 Prompt（默认 "Hi"），引出并消耗掉历史回显包。
  - **Execute**：历史冲刷完成后，再发送用户的正式消息，此时 CLI 已处于纯净的增量模式。

- **收益**：
  - **极致简化**：删除了复杂的归一化对比与正则截断算法，大幅降低代码维护成本。
  - **100% 格式对齐**：彻底解决了由于人工介入拼接导致的换行符、空格不一致问题。
  - **自愈与防漏**：通过物理级的“牺牲回合”实现了对历史泄露的深度防御。

### 2.2 授权卡片自动失效机制
**背景**：防止用户忽略旧授权卡片直接提问，导致后续误触历史高危按钮。
**方案**：
- **逻辑位置**：`src/engine/router.py` 的 `_handle_message` 入口。
- **流程**：
  1. 接收到新消息时，根据 `topic_id` 查询 `pending_confirms` 表。
  2. 若存在挂起的确认：
     - 调用 `FeishuIMProvider.client.im.v1.message.apatch` 更新该卡片 UI 为“已失效/超时”。
     - 从 `StateStore` 中物理删除该 `confirm_id`。
     - 记录日志并继续处理当前新消息。

### 2.3 双级会话管理机制 (Memory First + Auto-Save)
**背景**：减少不必要的 `session/load` 和 `session/save` 调用，降低 IO 和响应延迟。
**方案**：
- **内存命中优先 (ACPProvider)**：
  - 在 `ACPProvider` 中维护一个 `_active_session_id` 成员变量。
  - `session_load(session_id)` 逻辑：若传入的 ID 等于当前活跃 ID，则直接返回 `True`（跳过 RPC 调用）。
- **自动持久化 (Dispatcher)**：
  - 修改 `ACPDispatcher.cleanup`：在 `stop()` 进程前，循环遍历该实例下的活跃 Session 执行 `session_save()`。
  - 修改 `main.py` 的停机逻辑：在 `dispatcher.stop_all()` 内部触发全局保存。
  - 移除 `Router` 中每轮对话后的强制 `save`。

### 2.4 交互体感增强：Say Hi 卡片与 Get 气泡
**方案 A：Say Hi 卡片化**：
- 修改 `src/utils/card_builder.py`，增加 `build_system_status_card` 方法。
- 使用飞书卡片的“成功”和“警告”模板展示服务启停状态。

**方案 B：消息 Follow-up 气泡**：
- 在 `src/listener/websocket.py` 或 `Router` 接收消息的第一时间，调用飞书 `POST /im/v1/messages/:message_id/push_follow_up`。
- 添加 `get` 状态，给予用户及时的后台受理反馈。

---

## 3. 模块变更清单

| 模块 | 变更点 | 优先级 |
| :--- | :--- | :--- |
| `src/provider/acp.py` | 增量内容收集逻辑、内存 Session 状态保持、Load 优化 | @high |
| `src/engine/router.py` | 增加授权卡片清理逻辑、调用 Follow-up 接口 | @high |
| `src/engine/dispatcher.py` | 在回收进程前触发 Session 保存 | @med |
| `src/utils/card_builder.py` | 增加系统状态卡片、失效卡片模板 | @med |
| `src/storage/state_store.py` | 增加按 Topic 查询 Pending Confirm 的接口 | @med |

---

## 4. 后续开发计划
1. **[第一阶段]**：实施 ACP 响应裁剪与内存 Session 优化，提升核心体验。
2. **[第二阶段]**：实现“Get”气泡与系统状态卡片，优化 UI 交互。
3. **[第三阶段]**：完善高危卡片失效逻辑，提升安全闭环。
