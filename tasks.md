# FGBridge 2.0 开发任务看板

## [基础架构]
- [x] 初始化项目骨架（src 目录结构、Makefile、.env） @high (2026-05-16)
- [x] 编写 Pydantic 配置解析模型 (config.py) @high (2026-05-16)
- [x] 完善 requirements.txt 依赖清单 (lark-oapi, pydantic-settings, aiosqlite 等) @high (2026-05-16)
- [x] 实现 ACP 进程工作目录隔离及 gemini.md 自动引导功能 @high (2026-05-16)

## [通信与接入]
- [x] 实现飞书 WebSocket 长连接监听器 (src/listener/websocket.py) @high (2026-05-16)
- [x] 建立异步事件分发队列 (asyncio.Queue) 及 Worker 机制 @high (2026-05-16)
- [x] 实现 3 秒快速 ACK 响应逻辑 @high (2026-05-16)
- [x] 整理所需调用的 lark API 清单，更新 docs/lark_api_list.md @high (2026-05-16)
- [x] 捕获 im.message.reaction.created_v1 事件以支持表情授权 @high (2026-05-19)
- [x] 支持多条连续输入的用户消息打包处理 @high (2026-05-24)

## [Session 管理与多话题切换]
- [x] **数据库架构演进**:
    - [x] `sessions` 表: 记录 `session_id`, `topic_id`, `title`, `last_active_time`, `is_active` 等 @high (2026-05-27)
    - [x] `messages` 表: 实现历史消息持久化（用于本地缓存清理后的 Session 重建） @high (2026-05-27)
    - [x] `user_chats` 表: 解决 open_id 与 chat_id 映射问题 @high (2026-05-27)
- [x] **飞书菜单集成**:
    - [x] 注册 `application.bot.menu_v6` 事件监听并分发至 Router @high (2026-05-27)
    - [ ] 实现操作人身份校验逻辑（基于 `feishu_user_ids` 白名单）；（未实测） @high (2026-05-27)
    - [x] 实现 `_handle_menu_event` 逻辑，处理“开启新会话”和“历史会话列表”触发器 @high (2026-05-27)
- [x] **Session 核心能力实现**:
    - [x] **New Session**: 生成新 session，清理当前 topic 下的 active 标志，持久化新 session @high (2026-05-27)
    - [x] **List History**: 构建互动卡片，列出最近 n (默认 5) 个 session，提供“切换”按钮 @high (2026-05-27)
    - [x] **Switch Action**: 实现卡片点击热切换，并引入 Silent Flush 消除历史回显 @high (2026-05-30)
- [x] **深度重建逻辑 (Deep Reconstruction)**:
    - [ ] 实现从 `messages` 表读取历史消息并顺序 replay 的原子操作；（未实测） @high (2026-05-30)
- [x] **配置与打磨**:
    - [x] 增加 `history_session_limit` 配置项，默认 5 @low (2026-05-27)
    - [x] 实现基于首条消息的 Session 自动重命名逻辑 @med (2026-05-27)
    - [x] 引入全局异常报警卡片，提升系统透明度 @med (2026-05-30)
- [ ] 机器人菜单操作幂等性保护 @med

## [状态持久化]
- [x] 建立 SQLite 数据库模型 (src/storage/state_store.py) @high (2026-05-16)
- [x] 实现 Topics (Scope-Topic 映射) 存储逻辑 @high (2026-05-16)
- [x] 实现 Sessions 状态管理逻辑 @med (2026-05-16)
- [x] 数据库表结构升级，支持多步授权状态追踪 (confirm_step, msg_id) @high (2026-05-19)
- [ ] 通过飞书机器人菜单重启后端 Python 服务的能力 @low

## [外部集成]
- [x] 移植并适配 ACP 协议组件 (src/provider/acp.py) @high (2026-05-16)
- [x] 开发飞书 IM 消息发送与资源下载组件 (src/provider/feishu_im.py) @high (2026-05-16)
- [ ] 实现长回复 Markdown 转飞书文档块逻辑 (src/utils/docx_builder.py) @med

## [路由与引擎]
- [x] 实现基于 Scope-Topic 的智能路由分发器 (src/engine/router.py) @high (2026-05-16)
- [ ] 实现常驻助理的意图识别与角色指派逻辑 @high
- [x] 编写 ACP 进程调度池 (dispatcher.py)，支持按需唤醒 @med (2026-05-16)
- [x] 实现基于“静默刷”回合的角色注入引擎，解决指令覆盖问题 @high (2026-05-19)

## [UX 与安全]
- [x] 编写飞书互动卡片构造器 (src/utils/card_builder.py) @med (2026-05-16)
- [x] 实现基于表情回复（Reaction）的授权流与双重确认机制 @high (2026-05-19)
- [x] 多模态附件（图片/文件）的流水线处理逻辑 @med (2026-05-21)
- [x] Say Hi消息改为卡片模式 @med (2026-05-17)
- [x] 接收和回复用户消息时，在对应用户消息上添加‘get’和‘done’表情回复 @med (2026-05-17)

## [优化与打磨]
- [x] 专家进程的惰性退出 TTL 机制实现 @med (2026-05-17)
- [ ] Gemini Context Caching 性能优化支持 @low
- [ ] 结构化日志记录与错误追溯系统 @med
- [x] acp回复给lark的消息会携带session历史，需要trim只回复最新添加的内容 @high (2026-05-17)
- [x] 修复 fgb 重启后历史基准丢失及裁剪算法失效的问题 @high (2026-05-19)
- [x] 用静默刷机制重构历史上下文裁剪，验证重启后的第一条消息是否已成功裁剪历史上下文 @high (2026-05-19)
- [x] 解决 systemInstruction 效果被 gemini.md 覆盖的问题 @high (2026-05-19)
- [x] acp的同类型回复设置多种可用表情，随机采用，优化体验 @med (2026-05-24)
- [x] 修复卡片模式下授权回调的 `NameError: lark` 及 `None` 消息 ID 异常 @high (2026-05-24)
- [x] 实现卡片模式下的双重确认（Double Confirm）流 @high (2026-05-24)
- [x] 优化交互体验：实现卡片模式与非卡片模式的反馈逻辑解耦 @med (2026-05-24)
- [x] 强化授权幂等性保护并增加卡片点击后的即时表情反馈 @high (2026-05-24)
