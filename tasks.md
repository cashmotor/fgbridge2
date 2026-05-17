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

## [状态持久化]
- [x] 建立 SQLite 数据库模型 (src/storage/state_store.py) @high (2026-05-16)
- [x] 实现 Topics (Scope-Topic 映射) 存储逻辑 @high (2026-05-16)
- [x] 实现 Sessions 状态管理逻辑 @med (2026-05-16)

## [外部集成]
- [x] 移植并适配 ACP 协议组件 (src/provider/acp.py) @high (2026-05-16)
- [x] 开发飞书 IM 消息发送与资源下载组件 (src/provider/feishu_im.py) @high (2026-05-16)
- [ ] 实现长回复 Markdown 转飞书文档块逻辑 (src/utils/docx_builder.py) @med

## [路由与引擎]
- [x] 实现基于 Scope-Topic 的智能路由分发器 (src/engine/router.py) @high (2026-05-16)
- [ ] 实现常驻助理的意图识别与角色指派逻辑 @high
- [x] 编写 ACP 进程调度池 (dispatcher.py)，支持按需唤醒 @med (2026-05-16)

## [UX 与安全]
- [x] 编写飞书互动卡片构造器 (src/utils/card_builder.py) @med (2026-05-16)
- [x] 实现高危操作的 WebSocket 回调拦截与处理逻辑 @high (2026-05-16)
- [ ] 多模态附件（图片/文件）的流水线处理逻辑 @med
- [ ] Say Hi消息改为卡片模式 @med
- [ ] 接收到用户消息后，在对应用户消息上添加‘get’气泡（方法参见https://open.feishu.cn/document/im-v1/message/push_follow_up） @med

## [优化与打磨]
- [ ] 专家进程的惰性退出 TTL 机制实现 @med
- [ ] Gemini Context Caching 性能优化支持 @low
- [ ] 结构化日志记录与错误追溯系统 @med
- [ ] acp回复给lark的消息会携带session历史，需要trim只回复最新添加的内容 @high
