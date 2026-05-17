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

## [2026-05-17] TDD v0.2 性能优化与交互模型升级

### Done
- **响应内容精准裁剪 (Response Trimming)**:
    - 实现了基于 ACP 流式通知的增量收集机制，彻底解决了飞书前端回复中携带历史上下文的问题。
- **二级会话管理 (Memory First)**:
    - 在 `ACPProvider` 中引入内存热状态追踪，实现了已加载 Session 的秒级跳过逻辑，显著降低 TTFT。
- **表情回复 (Reaction) 反馈循环**:
    - 全面上线基于 Reaction 的状态交互：接收消息挂载 `OK` (GET)，回复完成自动流转为 `DONE`。
    - 扩展了 `StateStore` 和 `FeishuIMProvider` 以支持 Reaction ID 的持久化记录与精准删除。
- **安全增强 (授权自动失效)**:
    - 实现了话题级挂起授权的自动清理逻辑：新消息到达时自动废弃该话题下过时的授权请求，彻底规避历史按钮误触风险。
- **响应内容精准裁剪 (增强版)**:
    - 实现了 **“Cross-Restart Persistence”**：通过在数据库存储 `last_full_content`，解决了 FGB 重启后第一条消息无法裁剪的顽疾。
- **Say Hi 功能升级**:
    - 启停通知全面卡片化，支持蓝色 (Ready) 和灰色 (Stopped) 模板。
    - 优化了 `send_text` 接口，支持自动识别内容格式并智能切换 `interactive` 类型。

### Pending
- **自动持久化 (Auto-Save)**: 优化 `Dispatcher.cleanup` 及停机逻辑，实现在回收进程前自动触发全局保存。
- **意图指派逻辑**: AI 角色自动判定引擎开发（目前默认为 Developer）。
- **Get 气泡方案调整**: 已根据反馈从“跟随气泡”模型切换为更轻量的“表情回复”模型。

### State
- **状态追踪**: `pending_confirms` 表现已支持 Reaction 和 Auth 状态的复合管理。
- **系统稳健性**: 具备了防降级、防误触及响应裁剪的完整闭环。

