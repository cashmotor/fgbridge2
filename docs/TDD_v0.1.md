# 技术设计文档 (TDD)：个人版 AI Agent 虚拟团队智能网关

## 1. 文档概述
### 1.1 目的
本文档基于《FGBridge2_PRD_v0.1.md》（v0.2修订版），详细阐述 FGBridge 2.0 的技术架构、目录结构、模块设计以及从 FGBridge 1.0 (Demo 表格版) 代码中复用与改造的策略。

### 1.2 背景
FGBridge 2.0 全面转向飞书 IM 即时通讯，**通信机制严格限定为飞书 WebSocket (长连接) 模式**。该模式无需公网域名或 IP，极大地提升了部署的便利性与安全性，同时对高危操作拦截（互动卡片回调）提供原生支持。

---

## 2. 系统架构设计

### 2.1 整体架构图
```mermaid
graph TD
    subgraph 飞书开放平台
        A[飞书消息/事件推送服务]
    end

    subgraph FGBridge 2.0 (Python 后端 - 内网部署)
        B[WebSocket 监听器 (Lark SDK)]
        C[异步事件队列 (asyncio.Queue)]
        D[路由与会话管理器 (Router)]
        E[飞书 API 客户端 (HTTP)]
        F[状态存储 (SQLite)]
        G[ACP 进程调度池]
    end

    subgraph 代理执行层
        H[常驻助理 Process]
        I[专家进程池 Process]
    end

    A <== "WebSocket (TLS)" ==> B
    B -- "3s 内 ACK" --> A
    B -- "投递事件" --> C
    C --> D
    D <--> F
    D -- "唤醒/分发" --> G
    G <--> H
    G <--> I
    G -- "发送消息/卡片 (HTTP API)" --> E
    E -- "回复结果/卡片更新" --> A
```

---

## 3. 项目目录结构

```text
FGBridge2/
├── docs/                     # 文档目录
├── src/                      # 核心源码
│   ├── listener/             # 接入层
│   │   └── websocket.py      # 飞书 WebSocket 长连接监听器
│   ├── engine/               # 核心业务引擎
│   │   ├── router.py         # 消息智能路由分发 (1v1/群聊差异化)
│   │   └── dispatcher.py     # ACP 进程调度与 TTL 生命周期管理
│   ├── provider/             # 外部依赖交互
│   │   ├── acp.py            # Gemini CLI ACP 协议通信 (Identifier 驱动)
│   │   └── feishu_im.py      # 飞书 API 封装 (Say Hi, 消息收发)
│   ├── storage/              # 数据持久化
│   │   └── state_store.py    # SQLite 路由与状态存储
│   ├── utils/
│   │   ├── card_builder.py   # 飞书互动卡片构造器
│   │   └── docx_builder.py   # Markdown 转文档块逻辑
│   ├── config.py             # 配置管理 (Pydantic)
│   └── main.py               # 服务启动入口与全局生命周期管理
├── .env                      # 环境变量
└── Makefile                  # 构建与运行脚本
```

---

## 4. 模块设计与代码复用策略

### 4.1 核心协议层：ACPProvider (100% 改造复用)
**设计说明**：
- **Identifier 驱动**：摒弃不稳定的 UUID 依赖，统一使用 `Topic_ID` 作为标识。
- **绝对路径一致性**：强制使用绝对路径读写 `.session`，解决子进程 CWD 漂移导致的记忆丢失。

### 4.2 状态持久化：StateStore
- 存储 `Topic -> Session` 的持久化绑定，支持服务重启后的秒级恢复。

---

## 5. 关键业务流程设计

### 5.1 消息智能路由 (engine/router.py)
系统通过识别 `chat_type` 实施差异化的记忆隔离与角色委派策略。

**路由分发矩阵**：

| 对话场景 | 触发特征 | 寻回标识 (Topic_ID) | 响应角色 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **1v1 主时间轴** | `thread_id` 为空 | `chat_id` | 常驻助理 | 共享全局上下文记忆。 |
| **1v1 子任务** | `thread_id` 不为空 | `thread_id` | 特定专家 | 只要有话题标识，即视为独立任务。 |
| **群聊 初始/主轴** | `root_id` & `thread_id` 均空 | `chat_id` | 常驻助理 | 群内首发或主时间轴沟通。 |
| **群聊 回复串** | 仅 `root_id` 有值 | `root_id` | 常驻助理 | 针对主轴消息的追加讨论，保持记忆。 |
| **群聊 话题** | `thread_id` 有值 | `thread_id` | 特定专家 | 飞书原生话题模式，完全隔离。 |

---

## 6. 非功能设计

### 6.1 优雅停机与通知
- **Say Hi 机制**：启动发送 `🚀 已就绪`，停止发送 `🛑 已停止`。
- **保护性退出**：使用 `asyncio.shield` 确保停机通知发出的概率，随后显式回收所有 ACP 进程。

### 6.2 日志持久化
- **全量追踪**：`fgb.log` (Rotation 50MB)。
- **错误分流**：`error.log` 专用于监控严重异常。
