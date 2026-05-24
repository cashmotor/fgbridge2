# 技术设计文档 (TDD) v0.4：多消息打包处理与并发异步化架构

## 1. 文档概述
### 1.1 目的
针对用户在 IM 场景下习惯发送碎片化消息、以及 ACP 同步阻塞导致系统假死的性能瓶颈，本文档定义了消息打包（Bundling）机制及基于线程池的 ACP 异步化交互架构。

---

## 2. 核心设计方案

### 2.1 消息打包器 (MessageBundler)
**背景**：用户连续发送多条短消息时，若每条都触发 ACP 回合，会导致回复支离破碎且消耗大量 Token。
**设计要点**：
- **去抖机制 (Debounce)**：引入 `bundling_wait_time`（默认 2-3s）。接收到新消息时重置计时器。
- **上限控制 (Limit)**：引入 `bundling_max_messages`（默认 10条）。达到上限立即触发冲刷。
- **合成事件**：
    - **文本拼接**：将包内所有文本按顺序以换行符 `\n` 拼接。
    - **附件汇总**：提取每条原始消息的 `image_keys` 和 `file_keys`。
    - **元数据保留**：合成事件保留**最后一条消息**的 `message_id` 和 `chat_id`，确保表情回复落在最后一条消息上。

### 2.2 附件权限穿透 (Attachment Context)
**挑战**：飞书 API 下载附件需提供 `message_id` 进行权限校验。
**解决方案**：
- `MessageBundler` 在打包时不再只传递 Key 列表，而是传递 `(key, origin_msg_id)` 映射。
- `Router` 下载图片/文件时，精准使用其归属消息的 ID，确保跨消息打包时的下载成功率。

### 2.3 ACP 并发异步化 (Thread-based Async Isolation)
**背景**：`ACPProvider` 的 `send` 和 `start` 均为同步阻塞调用，会导致异步事件循环卡死。
**解决方案**：
- **线程池隔离**：在 `Router` 中使用 `asyncio.to_thread` 封装所有对 `ACPProvider` 和 `ACPDispatcher` 的调用。
- **解耦分发**：`MessageBundler` 在冲刷消息时使用 `asyncio.create_task` 启动 `Router` 协程，确保打包器能立即返回处理下一个会话。

---

## 3. 配置项扩充 (config.py)

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `bundling_enabled` | bool | True | 是否启用多消息打包功能 |
| `bundling_wait_time` | float | 2.0 | 连续输入停止后的等待间隔（秒） |
| `bundling_max_messages` | int | 10 | 单个包内最大消息条目数 |

---

## 4. 流程图 (Sequence)

1.  **用户** -> 发送消息 A -> **Bundler** (开启计时)
2.  **用户** -> 发送消息 B -> **Bundler** (重置计时)
3.  **Bundler** -> 计时结束 -> 构造**合成事件** -> **Router** (异步 Task)
4.  **Router** -> **Feishu** (回复 GET 表情)
5.  **Router** -> **ThreadPool** -> **ACP** (唤醒或发送)
6.  **ACP** -> 返回结果 -> **Router** -> **Feishu** (回复内容 + Done 表情)

---

## 5. 健壮性与 UX 优化

### 5.1 表情回复可靠性
- **超时保护**：`add_reaction` 增加 10s 超时，应对冷启动 Token 刷新。
- **自动重试**：失败后自动尝试第二次，增加容错。
- **非阻塞调用**：在 `Router` 中对某些非关键表情操作（如 `Done` 的清理）使用 `create_task`，进一步降低延迟。

---

## 6. 模块变更清单

| 模块 | 变更点 | 优先级 |
| :--- | :--- | :--- |
| `src/engine/bundler.py` | (新增) 实现消息打包、附件汇总、计时管理逻辑 | @high |
| `src/main.py` | 在 Worker 逻辑中接入 `MessageBundler` | @high |
| `src/engine/router.py` | 适配 `bundled_images` 结构；ACP 调用全链路 `to_thread` 异步化 | @high |
| `src/provider/feishu_im.py` | `add_reaction` 增加超时、重试及 LogID 日志记录 | @med |
| `tests/test_bundler.py` | (新增) 覆盖打包、上限、附件合并等测试场景 | @high |
