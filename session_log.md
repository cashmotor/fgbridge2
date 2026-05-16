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

## [2026-05-17] Session 寻回深度修复与路由模型进化

### Done
- **Session 保持 (Bug 修复)**:
    - 彻底重构了 `ACPProvider` 的记忆管理，废弃了不稳定的手动物理路径管理，回归 **sessionId 驱动的原生寻回** 模式。
    - 修复了 1v1 单聊下数据库寻回缺失导致的记忆丢失问题。
    - 确保了主对话窗口（主时间轴）与子话题讨论（Thread）均能通过 `Identifier` 实现 100% 稳定的记忆恢复。
- **路由模型优化**:
    - 实现了 1v1 和群聊的差异化路由逻辑：1v1 忽略 root_id 干扰，仅看 thread_id；群聊通过 root_id 保持助理对话，通过 thread_id 触发专家任务。
    - 在 TDD 文档中同步了最新的路由分发矩阵。
- ** Say Hi 功能**: 实现了服务启动和停止时的主动消息通知，并使用 `asyncio.shield` 确保停机消息的发送。
- **日志持久化**: 配置了 `loguru` 的文件落盘、ERROR 分流及 50MB 自动滚动。
- **代码审计**: 完成了全模块审计，架构一致性良好，逻辑闭环，准予进入 Alpha 测试阶段。

### Pending
- **二级缓存优化**: 内存热状态保持及停机前批量保存（已记入 Feature Request）。
- **意图指派逻辑**: 尚未接入 AI 自动判定角色（目前默认为 Developer）。
- **数据库优化**: 考虑引入 `aiosqlite` 连接池或单例管理。

### State
- **当前状态**: 核心业务链路（1v1/群聊、多任务并行、记忆保持、高危拦截）已全部打通。
- **数据库**: `data/fgbridge.db` 结构稳定。
- **协议兼容性**: 完全兼容 Gemini CLI 0.38+ ACP 模式。

