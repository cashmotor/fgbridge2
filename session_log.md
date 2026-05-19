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
- **响应内容精准裁剪 (终极版)**:
    - 实现了 **“正则归一化 + 20 字符锚点”** 融合算法。
    - 解决了 Gemini CLI 动态数字标签导致的硬前缀匹配失效问题。
    - 引入了 **“智能全量合成”**，确保数据库持久化的基准 100% 权威。
    - 实现了跨进程、跨重启的 100% 增量回复保障。
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

## [2026-05-19] 调试增强：响应裁剪链路透明化

### Done
- **链路日志增强**: 
    - 为 `ACPProvider` 的 `_read_until` 方法注入了详尽的裁剪逻辑日志，区分流式捕获、归一化全匹配、锚点匹配等策略。
    - 修复了 `Router` 在请求前调用 `save_topic` 时因默认值处理不当导致数据库历史基准被覆盖的 Bug。
- **调度引擎优化**:
    - 修复了 `Dispatcher` 中 TTL 清理逻辑对常驻角色的硬编码 Bug：现在会正确根据 `config.assistant_role` 动态匹配常驻助理的 TTL。

- **持久化层架构对齐**:
    - 修复了 `StateStore` 中由于数据库字段升级导致的**索引偏移 Bug**（误将 `last_active_time` 当作 `last_full_content` 读取）。
    - 引入了 `aiosqlite.Row` 具名列读取机制，提升了存储层的健壮性。
    - 明确了“全量基准存储”逻辑：数据库始终保存未裁剪的完整上下文，以确保重启后能通过 `rsplit` 精准切出增量回复。

## [2026-05-19] 架构跃迁：全面转向“原生回合模式”

### Done
- **架构重构**:
    - 废弃了基于文本差分的裁剪引擎，转向由 `session_id` 驱动的 **原生回合模式 (Native Turn-based Mode)**。
    - 删除了 `ACPProvider` 中所有关于 `last_full_content` 的手动合成与还原逻辑，彻底消除格式微差导致的裁剪失效风险。
    - 确立了以 `agent_message_chunk` (流式增量) 为核心的响应获取策略。
- **状态追踪升级**:
    - 在数据库 `topics` 表中引入了 `turn_count` 字段，实现对话回合的显式追踪与持久化。
    - 简化了 `Router` 逻辑：重启后仅需通过 `session_load` 唤醒记忆，Gemini CLI 内部机制将自动确保响应的增量纯净性。
- **历史回显深度防御**:
    - 实现了 **“静默刷 (Silent Flush)”** 机制：针对 ACP 模式在冷启动后首次 `prompt` 强制回显历史的问题，通过预先发送一个配置化的静默消息（如 "Hi"）来物理级消耗掉历史缓冲区。
    - 在 `config.py` 中增加了 `acp_silent_flush_enabled` 和 `acp_silent_flush_prompt` 配置项，增强了系统的灵活性。




