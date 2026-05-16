# FGBridge 2.0 阶段性测试计划 (TEST_PLAN.md)

本文档旨在为当前已实现的核心模块（基础架构、通信接入、持久化存储、协议集成与核心路由）设计测试用例，确保系统的稳定性与核心业务链路的可用性。

## 1. 测试环境准备

*   **运行环境**: 本地 Python 3.12 虚拟环境。
*   **依赖服务**: 飞书开放平台企业自建应用（已开启 WebSocket 模式及所需 API 权限）。
*   **Gemini CLI**: 确保 `gemini` 命令行工具在系统 `PATH` 中或在 `.env` 中正确配置了 `GEMINI_BIN_PATH`。

## 2. 核心模块测试用例

### 2.1. 基础架构与配置 (Config)

| 用例 ID | 测试目标 | 前置条件 | 操作步骤 | 预期结果 |
| :--- | :--- | :--- | :--- | :--- |
| CFG-01 | 环境变量加载 | 无 | 修改 `.env` 中的 `ASSISTANT_TTL=9999`。运行 Python 读取 config。 | `config.assistant_ttl` 输出为 9999。 |
| CFG-02 | 目录自动生成 | 移除本地 `data/` 目录 | 执行 `python -c "import src.config"` | 系统自动创建 `data/fgbridge.db` 父目录及 `data/sessions`、`data/attachments`。 |

### 2.2. 通信与接入 (WebSocket Listener)

由于此层依赖飞书服务端推送，推荐采用单元测试模拟 (`mock`) 飞书事件。

| 用例 ID | 测试目标 | 前置条件 | 操作步骤 | 预期结果 |
| :--- | :--- | :--- | :--- | :--- |
| WS-01 | 事件入队 | 服务启动，WebSocket 连接成功 | 向模拟客户端推送一个构建的 `im.message.receive_v1` 事件。 | 队列 (`event_queue.get()`) 能成功获取该事件的 JSON payload，且不会引发阻塞。 |
| WS-02 | 卡片回调接收 | 服务启动 | 在飞书客户端点击由系统发出的历史互动卡片。 | 监听器收到 `card.action.trigger` 事件并正常入队。 |

### 2.3. 状态持久化 (StateStore)

| 用例 ID | 测试目标 | 前置条件 | 操作步骤 | 预期结果 |
| :--- | :--- | :--- | :--- | :--- |
| DB-01 | 数据库初始化 | 无数据库文件 | 调用 `store.init_db()`。 | 在 `config.db_path` 成功生成 SQLite 数据库文件，且包含 `topics` 和 `pending_confirms` 表。 |
| DB-02 | 路由话题 CRUD | 数据库已初始化 | 1. `save_topic("topic_1", "chat_A", "Dev", "sess_X")` <br> 2. `get_topic("topic_1")` | 读取到的记录与写入内容一致。 |
| DB-03 | 高危操作挂起CRUD | 数据库已初始化 | 1. 存入 `add_pending_confirm("conf_1", "topic_1", ...)` <br> 2. 查询并验证。 <br> 3. 调用 `remove_pending_confirm`。 | 能正确存取，删除后返回 `None`。 |

### 2.4. 外部集成 (ACPProvider & FeishuIMProvider)

#### ACPProvider 测试

| 用例 ID | 测试目标 | 前置条件 | 操作步骤 | 预期结果 |
| :--- | :--- | :--- | :--- | :--- |
| ACP-01 | 进程隔离与引导同步 | 确保根目录有 `gemini.md` 模板 | 初始化 `ACPProvider()` 并调用 `start()`。 | 1. 在 `data/gemini_workspace` 创建了 `gemini.md`。 <br> 2. 子进程工作目录为 `data/gemini_workspace`。 |
| ACP-02 | 代理环境变量生效 | `.env` 配置了 `HTTP_PROXY` | 启动 ACP，通过系统工具(如 `ps e`) 查看子进程环境。 | 子进程的环境变量中存在对应的大/小写 proxy 变量。 |
| ACP-03 | JSON-RPC 通信握手 | - | 实例初始化时。 | `start()` 方法不报错，能顺利收到 `initialize` 的响应 `{"result": ...}`。 |

#### FeishuIMProvider 测试 (需真实 App Token)

| 用例 ID | 测试目标 | 前置条件 | 操作步骤 | 预期结果 |
| :--- | :--- | :--- | :--- | :--- |
| IM-01 | 消息发送 | 拥有合法的测试群 `chat_id` | 调用 `send_text(chat_id, "test")`。 | 返回非空的 `message_id`，飞书群内出现消息。 |
| IM-02 | 资源下载 | 找到一个包含图片的 `message_id` | 调用 `download_resource(msg_id, file_key, path)`。 | 方法返回 True，且指定路径成功保存了图片文件。 |

### 2.5. 路由与引擎 (Router & Dispatcher)

| 用例 ID | 测试目标 | 前置条件 | 操作步骤 | 预期结果 |
| :--- | :--- | :--- | :--- | :--- |
| RT-01 | 全新话题绑定 | 发送新消息事件（无 `root_id` / `root_id` 未注册） | `Router.dispatch()` 接收该消息。 | 1. 查询到未绑定。 <br> 2. 分配角色并入库 (Topics 表)。 <br> 3. 调用对应角色的 ACP。 |
| RT-02 | 已知话题追溯 | 数据库中已存在 `root_id=A` -> `role=Tester` | 接收携带 `root_id=A` 的消息事件。 | 1. 直接查询到角色 `Tester`。 <br> 2. 通过 Dispatcher 获取 `Tester` ACP。 |
| RT-03 | 高危卡片分发与回调 | `ACPProvider` 返回 `confirmation_required` | 1. `Router` 拦截并生成互动卡片回复给飞书。<br> 2. 模拟发送 `card.action.trigger` 事件。 | 1. 数据库新增 `pending_confirm` 记录。 <br> 2. 收到回调后，调用 `acp.confirm`。 <br> 3. 更新卡片状态。 |
| DISP-01 | 进程按需唤醒 | `ACPDispatcher` 为空 | 调用 `dispatcher.get_acp("Designer")`。 | 实例化新的 `ACPProvider` 存入 pool，返回可用实例。 |
| DISP-02 | 进程自动清理 | `EXPERT_TTL=2`秒 | 唤醒一个专家进程，等待 3 秒后执行 `cleanup()`。 | 该进程从 pool 移除，底层 `gemini cli` 进程被 `stop()`。 |

## 3. 端到端 (E2E) 测试演练流程

在模块自测完成后，建议进行一次全流程演练：

1.  **启动服务**: 运行 `make run`。确认打印出“飞书 WebSocket 长连接...”、“FGBridge 2.0 已就绪”。
2.  **触发全新会话**:
    *   在飞书单聊或群聊中发送 `@Assistant 你好，我需要开发一个贪吃蛇脚本`。
    *   **预期**: 系统接收消息，创建新话题，写入 SQLite，后台唤醒 `Developer` 进程，回复飞书。
3.  **触发关联会话**:
    *   使用飞书的**回复**功能，针对上述最后一条回复输入：“加上随机延迟”。
    *   **预期**: 系统通过 `root_id` 命中已有会话，复用内存中的 `Developer` 进程（或重新加载其 `.session`），并在原 Thread 持续作答。
4.  **触发高危操作**:
    *   在飞书中发送：“帮我列出 `/etc` 目录下的敏感文件并尝试删除”。
    *   **预期**: Gemini CLI 请求 shell 权限，Python 拦截该 JSON-RPC 并推回一张红色警示卡片。用户不点击前，进程挂起；点击“拒绝”，进程收到 deny 并回复操作已取消。