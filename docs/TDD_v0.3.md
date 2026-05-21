# 技术设计文档 (TDD) v0.3：表情授权流与双重确认机制

## 1. 文档概述
### 1.1 目的
针对飞书近期对互动卡片 WebSocket 回调支持的调整，本文档定义了一种基于消息表情（Reaction）的替代授权方案。该方案不仅解决了回调失效问题，还通过“双重确认”逻辑进一步提升了高危操作的安全拦截能力。

---

## 2. 核心设计方案

### 2.1 表情授权模式 (Reaction-based Auth)
**背景**：飞书卡片回调目前在 WebSocket 模式下稳定性受限。采用原生的表情回复作为授权触发器，具有更好的兼容性和更低的交互门槛。

**设计要点**：
- **模式切换**：引入 `acp_card_mode_enabled` 配置项（默认 `False`），用于在“卡片回调模式”与“表情授权模式”之间切换。
- **符号映射**：
    - **同意 (YES)**：映射 `OK`, `YES`, `CHECK_MARK`, `THUMBSUP` 等正面表情。
    - **拒绝 (NO)**：映射 `NO`, `CROSS_MARK`, `THUMBSDOWN` 等负面表情。

### 2.2 双重确认逻辑 (Double Confirm Workflow)
**目的**：防止用户因误触表情而导致高危指令（如 `rm -rf`）执行。

**流程定义**：
1.  **初始申请 (Step 1)**：
    - 机器人发送文本格式的授权请求，末尾提示：“点赞同意，点踩拒绝”。
    - 数据库记录该请求，`confirm_step = 1`，并关联当前消息 ID。
2.  **二次确认 (Step 2)**：
    - 当用户对 Step 1 消息回复“同意”表情时，机器人**回复 (Reply)** 一条二次确认消息：“⚠️ 确定要执行上述操作吗？”。
    - 状态更新为 `confirm_step = 2`，并将追踪 ID 锁定到这条新的确认消息上。
3.  **最终执行**：
    - 用户必须对“二次确认消息”再次回复“同意”表情，操作才会正式提交。
4.  **取消与回退**：
    - 在任何阶段回复“拒绝”表情，操作立即终止。
    - 若在 Step 2 拒绝，系统会发送取消提示并重置回 Step 1，允许用户重新发起。

### 2.3 自动失效与清理机制
- **消息截断**：若用户未进行表情操作直接发送了新消息，`Router` 会检测到该话题下的挂起授权，将其状态标记为失效并删除，防止旧授权被意外激活。
- **Thread 绑定**：所有授权相关的消息均使用飞书 `reply` 接口，确保在同一个消息 Thread 中流转，方便审计。

---

## 3. 数据库结构变更

### 3.1 `pending_confirms` 表扩展
为支持多步确认和表情追踪，表结构进行了以下升级：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `confirm_step` | INTEGER | 当前授权阶段（1: 待初审, 2: 待二次确认） |
| `msg_id` | TEXT | 当前正在监听表情的消息 ID |
| `reaction_id` | TEXT | (保留) 关联的表情 ID |

---

## 4. 模块变更清单

| 模块 | 变更点 | 优先级 |
| :--- | :--- | :--- |
| `src/config.py` | 增加 `acp_card_mode_enabled` 开关及表情配置库 | @high |
| `src/storage/state_store.py` | 增加数据库自动迁移逻辑，支持 `confirm_step` 和 `msg_id` | @high |
| `src/listener/websocket.py` | 注册 `im.message.reaction.created_v1` 事件捕获 | @high |
| `src/engine/router.py` | 实现 `_handle_reaction` 状态机逻辑，重构授权分发逻辑 | @high |

---

## 6. 多模态附件流水线 (Multimodal Attachment Pipeline)

### 6.1 飞书复杂消息解析
**背景**：飞书 IM 消息除基础 `text` 类型外，还包含 `post`（富文本）和 `image` 等类型。
**处理逻辑**：
- **`post` 类型解析**：遍历 `content` 数组中的所有 block。
    - 提取 `tag: "text"` 的内容拼接至主文本。
    - 提取 `tag: "img"` 的 `image_key` 加入待处理附件列表。
- **字段兼容性**：支持飞书事件流中 `message_type` 和 `msg_type` 字段的混用。

### 6.2 资源下载与 API 区分
为确保附件下载成功率，系统严格区分了资源类型及其对应的 API 接口：
- **图片类 (`image_key`)**：采用**双策略降级下载机制**，优先利用消息上下文以获得更高成功率：
    1. **主策略**：优先尝试通用的 `lark.im.v1.GetMessageResourceRequest` API，通过传入 `message_id` 实现权限穿透，特别适用于即时发送的图片。
    2. **降级策略**：若消息资源接口不可用或失败，自动降级使用专用的 `lark.im.v1.GetImageRequest` API（用于下载应用内自有资源）。
    3. **参数清洗**：所有传入的 `image_key` 在请求前均经过严格的字符清洗，杜绝 JSON 解析残留的隐藏引号导致请求失效。

- **文件类 (`file_key`)**：使用通用的 `lark.im.v1.GetMessageResourceRequest` API，且必须显式指定 `type: "file"`。
- **工作目录绑定**：附件下载路径始终相对于 `gemini_cwd` (ACP 进程工作目录)，确保 ACP 内部能通过 `file://` 正确引用。

### 6.3 飞书文档自动处理
针对文本中包含的飞书文档链接（Docx, Sheet, Wiki, Bitable）：
- **自动识别**：基于正则识别飞书文档 Token 和对象类型。
- **导出策略**：
    - **二进制导出**：优先尝试将文档导出为用户配置的格式（如 PDF/Docx/Xlsx）。
    - **Markdown 降级**：若未配置导出或导出失败，对 Docx 文档进行 block 级递归解析，转换为 Markdown 注入 Prompt。
- **Wiki 节点穿透**：针对 Wiki 类型链接，自动解析出其背后关联的实际 `obj_token`，若 Wiki API 失败则调用 Drive API 兜底搜索。

---

## 7. 交互反馈优化 (UX Feedback)

### 7.1 表情反馈逻辑
为提升系统受理任务的实时感，增加了以下表情反馈机制（均遵循飞书标准大小写命名，例如 `Get`、`Done`、`Error`）：
- **受理反馈 (Get)**：在 `_handle_message` 入口处立即回复 `Get` 表情，不等待耗时的导出/下载操作。
- **完成反馈 (Done)**：任务成功回复后，将 `Get` 替换为 `Done`。
- **无效/失效反馈 (Error/配置项)**：
    - 针对因内容/附件均为空而被跳过的消息，回复配置的 `reaction_invalid`（如 `Error` 或 `CrossMark`）。
    - 针对因新消息输入而自动失效的授权请求，在原消息上追加失效表情，提供视觉反馈且不覆盖原有的 `Get`。

---

## 8. 模块变更清单 (续)

| 模块 | 变更点 | 优先级 |
| :--- | :--- | :--- |
| `src/provider/feishu_im.py` | 新增 `FeishuUrlResolver`, `download_image`, `aexport_document` | @high |
| `src/engine/router.py` | 重构 `_handle_message` 解析 `post` 类型；重构附件下载路径逻辑 | @high |
| `src/config.py` | 增加 `feishu_export_type` 导出格式配置 | @med |
