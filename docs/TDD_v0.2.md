# 技术设计文档 (TDD) v0.2：性能优化与交互增强

## 1. 文档概述
### 1.1 目的
本文档旨在对 FGBridge 2.0 核心架构进行增量设计方案说明，重点解决响应内容冗余、授权时效性安全风险、会话管理 IO 性能瓶颈以及 UI 交互体感增强（气泡与卡片化通知）。

---

## 2. 核心功能设计方案

### 2.1 响应内容精准裁剪 (Response Trimming)
**背景**：Gemini ACP 0.38+ 模式通常采用回合制（Turn-based）响应。虽然协议倾向于只返回当前回合的增量内容，但在执行 `session/load` 后或特定环境下，仍可能回显部分甚至全部历史上下文。为确保飞书前端体验，必须具备鲁棒的差分裁剪能力。

**方案实现细节**：
- **逻辑位置**：`src/provider/acp.py` 中的 `_read_until` 处理逻辑。
- **混合动力裁剪引擎**：
  系统通过以下三个维度自动识别响应模式，防止历史内容泄露或数据库记录重复叠加：
  1. **流式增量模式 (Streaming Delta)**：
     - **识别**：若在最终响应前收到了 `agent_message_chunk` 块，则优先信任该流式内容为“纯增量”。
     - **处理**：直接提取流式块内容作为回复。
     - **持久化**：将 `旧全量基准 + 当前流式增量` 合成新的全量快照存入数据库。
  2. **全量回显模式 (Full Echo)**：
     - **识别**：若未收到流式块，但最终回复（`raw_content`）中包含经过归一化处理后的旧历史基准。
     - **处理**：使用 `rsplit` 结合归一化锚点，从全量内容中精准截断旧历史，提取后缀增量。
     - **持久化**：直接将收到的 `raw_content` 作为新的全量快照存入数据库。
  3. **独立回复模式 (Independent Turn)**：
     - **识别**：既无流式块，且 `raw_content` 与旧基准无重合。
     - **处理**：视 `raw_content` 本身为增量。
     - **持久化**：合成 `旧全量基准 + raw_content` 存入数据库。

- **关键技术点**：
  - **正则归一化 (Normalization)**：引入更鲁棒的正则 `\d+[:\s]+` 和 `\d+\n`，剔除 ACP 协议中动态生成的数字时间戳/标签。这解决了“内容相同但标签不同”导致的匹配失败问题。
  - **具名列持久化**：`StateStore` 采用具名列（`aiosqlite.Row`）访问模式，彻底解决因数据库 `ALTER TABLE` 升级导致的索引偏移（误将时间戳当做基准）问题。
  - **基准寻回**：在 `Router` 唤醒 Session 时，强制执行 `last_full_content` 的内存注入。若数据库记录为空，则记录警告日志并以当前回复为新基准。

- **收益**：
  - **防雪球效应**：避免了由于错误拼接导致的数据库历史记录呈指数级重复增长。
  - **跨重启一致性**：确保服务重启后，第一条消息能根据持久化基准实现 100% 成功裁剪。
  - **透明调试**：通过详尽的 `[Trim]` 前缀日志展示匹配策略，实现问题的快速溯源。

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
