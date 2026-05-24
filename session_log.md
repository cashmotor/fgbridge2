# FGBridge 2.0 开发会话日志

...
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

## [2026-05-20] 附件流水线：图片下载与飞书文档自动导出

### Done
- **飞书资源增强 (Provider)**:
    - 引入了 `FeishuUrlResolver` 模块，支持对飞书文档 (Docx, Sheet)、知识库 (Wiki) 及多维表格 (Bitable) URL 的自动识别与 Token 提取。
    - 实现了 `aexport_document` 异步方法：支持将飞书文档导出为 PDF/Docx/Xlsx 格式，包含自动轮询导出任务状态及下载逻辑。
    - 实现了 `aget_docx_markdown` 异步方法：支持递归解析 Docx Block 树并生成 Markdown 文本，作为导出失败或未配置导出时的降级方案。
    - 增强了 Wiki 节点解析逻辑，增加了基于 Drive API 的备选搜索方案，提高了解析成功率。
- **Router 附件处理逻辑升级**:
    - 重构了 `_process_attachments` 方法：现在支持从 IM 消息正文中通过正则自动提取飞书链接。
    - 建立了“下载-处理-关联”流水线：图片自动下载为 Base64 或资源链接；飞书文档根据配置自动导出为本地附件或转换为 Markdown 注入 prompt。
    - 实现了附件名与消息 ID 的唯一性绑定，确保多并发场景下文件不冲突。
    - **修复 (Path)**: 确保附件下载路径始终相对于 `gemini_cwd` (ACP 工作目录)，解决文件无法被 ACP 识别的问题。
    - **修复 (UX)**: 将 `Get` 表情回复逻辑提前至消息处理的最开始，确保在耗时的文档导出过程中用户能立即收到受理反馈。
    - **优化 (UX)**: 为跳过处理的消息及因新消息输入而自动失效的授权请求添加了 `CROSSMARK` 表情回复，提供明确的负面状态视觉反馈，且不覆盖已有的 `Get` 表情。
    - **修复 (Image)**: 
        1. 修复了飞书 `post` (富文本) 消息内容无法被正确解析的问题，现在支持遍历 block 并提取图文混排中的所有 `text` 和 `image_key`。
        2. 实现了**双策略图片下载流水线**：优先尝试专用图片接口 (`GetImage`)，若遇参数错误则自动降级至消息资源接口 (`GetMessageResource`)，利用 `message_id` 解决即时消息图片的权限穿透问题。
        3. 增加了严格的 `image_key` 数据清洗，去除了 JSON 转义导致的非法字符。
    - **修复 (UX/Emoji)**: 
        1. 修正了飞书表情符号的大小写敏感问题（如 `Get` 而非 `GET`）。
        2. 引入了 `reaction_invalid` 配置项，使用飞书标准符号（如 `Error`）提供跳过处理和授权失效的视觉反馈。
    - **增强 (Debug)**: 在 `Router` 中增加了全链路调试日志，并开启了飞书 SDK 的底层 DEBUG 日志，支持追踪实际请求 URL。
- **配置与验证**:
    - 在 `config.py` 中新增 `feishu_export_type` 配置项，允许用户自定义导出格式。
    - 编写并运行了 `pytest` 测试用例，验证了 URL 解析引擎和 Router 附件处理链条的正确性。

### State
- **多模态能力**: 系统现已具备处理图片附件及飞书内部文档链接的能力，极大增强了 Gemini 的信息获取边界。
- **导出策略**: 优先执行二进制导出（PDF等），若导出失败或非文档类型则尝试 Markdown 提取。

### Done
- **角色注入引擎优化**:
    - 解决了 `systemInstruction` 被 `gemini.md` 覆盖的问题：废弃了初始化时的 RPC 指令发送，改为在“静默刷”回合直接注入角色提示词（Role Prompt）。
    - 确保了新会话（Turn 1）和冷启动会话均能通过第一条消息锁定角色身份。
- **表情授权流 (Reaction-based Auth)**:
    - 针对飞书卡片回调限制，实现了全新的基于消息表情的授权方案。
    - 引入了 **双重确认 (Double Confirm)** 机制：用户需在原始消息和确认消息下各回复一次 `YES` 类型表情（如 OK/Yes）方可触发执行。
    - 增加了防误触回退逻辑：若在二次确认阶段回复 `NO`，系统将自动重置状态并允许用户重新授权。
- **持久化层平滑升级**:
    - 升级了 `pending_confirms` 表结构，增加了 `confirm_step` 和 `msg_id` 字段。
    - 实现了鲁棒的数据库自动迁移逻辑，兼容旧版本数据。
- **监听器与 SDK 修复**:
    - 修复了 `lark-oapi` 1.5.5 在 WebSocket 模式下的事件导入错误。
    - 适配了飞书 2.0 表情事件的数据结构，实现了精准的用户操作过滤。
- **文档化**:
    - 发布了 `docs/TDD_v0.3.md`，详细定义了表情授权流的技术实现。

### State
- **授权模型**: 现支持“卡片回调”与“表情授权”双模切换（默认表情模式）。
- **初始化流**: 实现了“角色定义 + 历史冲刷”的一体化冷启动方案。

## [2026-05-24] UX 增强：多条连续输入打包处理

### Done
- **消息打包器 (MessageBundler)**:
    - 实现了基于会话 ID (`bundle_id`) 的异步消息打包引擎。
    - 支持基于时间间隔的 **去抖触发 (Debounce)**：在 `bundling_wait_time` 内有新消息进入则重置计时器。
    - 支持基于数量的 **上限触发 (Limit)**：当 Bundle 内消息数达到 `bundling_max_messages` 时立即冲刷。
    - **内容合成策略**: 将多条消息的文本按顺序用换行符拼接，并将所有 `image_keys` 和 `file_keys` 汇总去重。
- **流程集成**:
    - 在 `main.py` 的 Worker 循环中接入 `MessageBundler`，确保所有进入系统的消息在分发给 `Router` 前完成打包。
    - 完美兼容现有表情反馈逻辑：由于合成事件携带最后一条消息的 `message_id`，`Get` 和 `Done` 表情会自动回复在被打包的最后一条消息上。
- **配置化**:
    - 在 `config.py` 中增加了打包相关的三项配置，支持按需调整。
- **质量保障**:
    - 编写了 `tests/test_bundler.py` 覆盖文本拼接、上限触发及附件合并等核心场景，测试全部通过。

### State
- **输入体验**: 用户现在可以连续发送多条短消息（或图文混排），系统会将其视为一个完整的 Prompt 处理，大幅减少了碎片化的回复和 ACP 消耗。
- **视觉反馈**: 回复表情仅出现在最后一条消息上，保持了 IM 会话的整洁。

## [2026-05-24] UX 优化：表情回复多样化

### Done
- **多表情随机采用**:
    - 在 `config.py` 中将 `reaction_get`, `reaction_done`, `reaction_invalid` 升级为列表类型。
    - 实现了 `validate_reaction_list` 校验器，兼容旧版单字符串及逗号分隔字符串配置。
    - 修改 `FeishuIMProvider.add_reaction`，使用 `random.choice` 从配置列表中随机挑选表情。
    - 增强了 `delete_bot_reaction_by_type`，支持传入列表并清理掉列表中所有匹配的机器人表情。

### State
- **交互趣味性**: 机器人现在会随机选用不同的表情（如 `Eyes`, `SMILE`, `RAINBOW` 等）来反馈受理和完成状态，提升了产品的亲和力。

## [2026-05-24] 修复：卡片模式授权回调异常

### Done
- **Router 核心修复**:
    - **修复 (NameError)**: 在 `src/engine/router.py` 中增加了缺失的 `import lark_oapi as lark`，解决了卡片回调处理时 `name 'lark' is not defined` 的崩溃问题。
    - **修复 (Message ID)**: 修正了 `_handle_card_action` 中获取消息 ID 的逻辑，将 `event_data.get("context", {}).get("message_id")` 更新为飞书标准字段 `open_message_id`。
    - **全链路打通**: 修复后，卡片模式下的“允许”和“拒绝”操作均能正确获取上下文消息 ID，并成功调用 `reply` 进行状态反馈及 `apatch` 更新卡片展示内容。
- **卡片模式双重确认机制**:
    - 在 `src/utils/card_builder.py` 中增加了 `build_double_confirm_card` 方法，并重构了 `build_permission_card`，将第一步按钮改为“申请执行”。
    - 在 `Router._handle_card_action` 中实现了状态机：
        - `confirm`: 第一步申请 -> 更新为二次确认卡片，数据库 `confirm_step` 更新为 2。
        - `back`: 从二次确认卡片返回 -> 恢复为初始申请卡片，数据库 `confirm_step` 回退为 1。
        - `allow`: 第二步最终确认 -> 执行 ACP 决策并展示结果。
    - 统一了卡片模式与表情模式的“双重确认”安全标准。
- **交互逻辑解耦 (Interaction Separation)**:
    - 实现了卡片模式与非卡片（表情）模式的完全隔离：
        - **卡片模式**: 移除所有授权相关的文本消息回复，转而通过 `apatch` 实时更新卡片展示状态（包括“已授权”、“已拒绝”及“已失效”）。
        - **非卡片模式**: 保留原有的文本回复（“✅ 授权已通过...”）和表情反馈（`Error`）机制。
    - 在 `CardBuilder` 中新增了 `build_expired_card` 样式，用于处理用户直接输入新消息导致旧卡片自动失效的场景。
- **交互冲突规避与逻辑分割 (Conflict Resolution)**:
    - 在 `_handle_reaction` 中增加了 `acp_card_mode_enabled` 校验：当卡片模式开启时，系统会显式忽略所有表情授权事件。
    - **设计意图**: 实现了“卡片模式全通过卡片交互、非卡片模式全通过消息和表情回复交互”的物理隔离，避免了在卡片消息上点赞触发文本二次确认的混淆场景。
- **并发与幂等性优化 (Idempotency & Feedback)**:
    - **即时反馈**: 在 `_handle_card_action` 启动时立即异步添加 `REACTION_GET` 表情，处理完成后通过 `finally` 块确保清理，增强了卡片点击后的即时视觉反馈。
    - **原子化决策**: 重构了 `_execute_confirm_decision`，将 `remove_pending_confirm` 移动至函数开头，利用数据库 `rowcount` 实现了原子的“检查并删除”逻辑，防止高并发下的重复授权执行。
    - **状态机幂等**: 在卡片多步跳转中增加了 `confirm_step` 校验，确保同一卡片状态无法被重复触发。

### State
- **授权稳定性**: 修复了卡片模式授权的核心路径缺陷，确保在开启 `acp_card_mode_enabled` 时系统依然健壮。
