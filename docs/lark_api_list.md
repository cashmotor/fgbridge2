# FGBridge 2.0 飞书 API 权限清单

为了确保本产品的功能正常运行，您需要在飞书开放平台后台为应用开启以下权限及配置。

## 1. 通信模式配置
- **事件订阅方式**：WebSocket (长连接)
- **事件订阅范围**：接收机器人消息、卡片交互回调

## 2. 核心权限点 (Scopes)

### IM 即时通讯 (消息处理)
- `im:message` : **接收消息** (必须，用于获取用户指令)
- `im:message.p2p_msg:readonly` : **读取单聊消息** (必须，用于 1v1 场景)
- `im:message.group_msg:readonly` : **读取群聊消息** (必须，用于群聊场景)
- `im:message:send_as_bot` : **以机器人身份发送消息** (必须，用于回复用户)
- `im:resource:readonly` : **获取消息资源文件** (必须，用于下载图片/附件)
- `im:chat:readonly` : **获取群组信息** (必须，用于 Scope 识别)

### 互动卡片 (高危拦截)
- 不需要额外 Scope，但需确保在“机器人”功能页开启了卡片能力。

### 飞书文档 (长回复文档化)
- `docx:document:create` : **创建和管理文档** (必须，用于 FR-3.3)
- `wiki:space` : **管理知识库节点** (可选，若需将文档存入特定知识库)
- `drive:file` : **管理云空间文件** (必须，用于创建和导出文档)

---

## 3. 具体调用的 API 列表

| 模块 | 功能 | 调用接口 | 对应权限点 |
| :--- | :--- | :--- | :--- |
| **接入** | 建立 WebSocket | `ws.start()` (Lark SDK) | 无 (需 AppID/Secret) |
| **路由** | 获取根消息内容 | `GET /im/v1/messages/:message_id` | `im:message` |
| **回复** | 发送文本/卡片 | `POST /im/v1/messages/:message_id/reply` | `im:message:send_as_bot` |
| **资源** | 下载图片/文件 | `GET /im/v1/messages/:message_id/resources/:file_key` | `im:resource:readonly` |
| **文档** | 创建新文档 | `POST /docx/v1/documents` | `docx:document` |
| **文档** | 转换 Markdown | `POST /docx/v1/documents/:document_id/blocks` | `docx:document` |
| **卡片** | 更新卡片状态 | `PATCH /im/v1/messages/:message_id` | `im:message:send_as_bot` |

## 4. 注意事项
- 权限修改后，必须**发布应用版本**并经企业管理员审核通过后方可生效。
- WebSocket 模式下，不需要配置“消息卡片请求网址”或“事件订阅请求网址”。
