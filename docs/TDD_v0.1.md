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
        I[开发专家 Process]
        J[其他专家 Process]
    end

    A <== "WebSocket (TLS)" ==> B
    B -- "3s 内 ACK" --> A
    B -- "投递事件" --> C
    C --> D
    D <--> F
    D -- "唤醒/分发" --> G
    G <--> H
    G <--> I
    G <--> J
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
│   │   └── websocket.py      # [新建] 飞书 WebSocket 长连接监听器
│   ├── engine/               # 核心业务引擎
│   │   ├── router.py         # IM 消息路由与分发 (Scope-Topic 逻辑)
│   │   └── dispatcher.py     # 异步任务调度与进程池管理
│   ├── provider/             # 外部依赖交互
│   │   ├── acp.py            # [复用] Gemini CLI ACP 协议通信
│   │   └── feishu_im.py      # [改造] 飞书 API 封装 (消息发送、资源下载)
│   ├── storage/              # 数据持久化
│   │   └── state_store.py    # [改造] SQLite 路由与状态存储
│   ├── utils/
│   │   ├── card_builder.py   # [新建] 飞书互动卡片构造器
│   │   └── docx_builder.py   # [新建] Markdown 转文档块逻辑
│   ├── config.py             # 配置管理
│   └── main.py               # 服务启动入口 (启动 WebSocket 线程)
├── .env                      # 环境变量
└── requirements.txt          # 依赖清单
```

---

## 4. 模块设计与代码复用策略

### 4.1 接入层：WebSocket Listener (全新开发)
**实现方案**：
- 使用 `lark-oapi` 官方 SDK 的 `ws.Client` 实现。
- **并发处理**：SDK 接收到消息后，业务逻辑必须在独立线程或协程中执行，确保主监听回路能立即返回（响应飞书服务器），避免 3 秒超时重推。

### 4.2 核心协议层：ACPProvider (100% 复用)
**来源**：`demo/provider/acp.py`
**设计说明**：
- 保持不变。ACP 的 JSON-RPC 机制与 WebSocket 的异步推送天然契合。

### 4.3 状态持久化：StateStore (80% 复用)
**调整设计**：
- 确认使用 **SQLite**。
- 路由表记录 `topic_id` (即消息 `root_id`) 与 `session_id` 的绑定。

---

## 5. 关键交互流程设计 (WebSocket 专项)

### 5.1 互动卡片拦截 (针对 WebSocket)
**流程**：
1. `ACPProvider` 触发权限请求。
2. 后端构造卡片，通过 `feishu_im.py` (HTTP API) 发送。
3. 用户点击卡片按钮。
4. **飞书通过现有的 WebSocket 连接**将 `card.action.trigger` 事件推送到 `listener/websocket.py`。
5. 监听器识别事件类型，提取 `value` (包含 `confirm_id`)，通过队列交给 `router.py`。
6. `router.py` 调用 `acp.confirm` 解锁 ACP 进程。

### 5.2 资源下载
**流程**：
- 收到包含资源的文件消息后，立即 ACK。
- 异步 Worker 调用 `feishu_im.py`，使用 `message-resource` 接口下载资源。

---

## 6. 设计可行性确认
- **事件全覆盖**：WebSocket 模式支持 `im.message.receive_v1` 和 `card.action.trigger`，满足所有交互需求。
- **免公网配置**：完全符合内网安全部署要求。
- **3秒响应**：通过 `asyncio.Queue` 完美规避处理耗时限制。
