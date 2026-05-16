# FGBridge 2.0 开发会话日志

## [2026-05-16] 初始化与核心框架搭建

### Done
- **基础架构**: 初始化了 `src` 目录结构，编写了 `config.py` (Pydantic Settings), `Makefile`, 并更新了 `.env.example`。
- **通信接入**: 实现了 `FeishuWebSocketListener` (WebSocket 长连接模式)，并在 `main.py` 中通过 `asyncio.Queue` 建立了异步事件分发流水线，确保 3 秒 ACK 响应。
- **状态持久化**: 建立了 SQLite 数据库 (`src/storage/state_store.py`)，支持 Scope-Topic 路由表及高危操作挂起状态。
- **外部集成**: 移植了 `ACPProvider` (Gemini CLI 协议)，实现了 `FeishuIMProvider` (飞书消息发送与资源下载)。
- **引擎与 UX**: 
    - 实现了 `ACPDispatcher` 进程池管理，支持角色级进程唤醒与 TTL 清理。
    - 实现了 `Router` 路由大脑，支持 `Scope-Topic` 映射。
    - 实现了 `CardBuilder` 互动卡片构造器，支持高危操作拦截。

### Pending
- **意图识别**: 话题首次绑定的 AI 识别逻辑尚为占位符 (Mocked as "Developer")。
- **多模态流水线**: 尚未实现飞书消息附件（图片/文件）的自动下载并转发给 ACP。
- **文档化**: Markdown 转飞书文档的功能尚未实现。
- **TTL 自动清理**: Dispatcher 的 `cleanup` 逻辑已编写，但尚未在 `main.py` 的循环中调用。

### State
- **当前架构**: 异步事件驱动架构。
- **关键信号**: WebSocket 模式下 card 回调已打通逻辑。
- **数据库**: 使用 `aiosqlite` 操作 `data/fgbridge.db`。
