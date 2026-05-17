# 技术设计文档 (TDD) v0.2：性能优化与交互增强

## 1. 文档概述
### 1.1 目的
本文档旨在对 FGBridge 2.0 核心架构进行增量设计方案说明，重点解决响应内容冗余、授权时效性安全风险、会话管理 IO 性能瓶颈以及 UI 交互体感增强（气泡与卡片化通知）。

---

## 2. 核心功能设计方案

### 2.1 响应内容精准裁剪 (Response Trimming)
**背景**：Gemini ACP 模式在 `session/prompt` 响应中可能包含部分历史上下文。为确保飞书前端体验，必须仅转发本次新增的生成内容。
**方案**：
- **逻辑位置**：`src/provider/acp.py` 中的 `_read_until` 或 `send` 方法。
- **实现机制**：利用 ACP 协议中的流式通知 `agent_message_chunk`。
  - 在发送 `prompt` 前清空 `_collected_content` 缓冲区。
  - 仅累加当前请求周期内收到的 `chunk`。
  - 确保返回给 `Router` 的结果仅包含该次增量文本。

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
