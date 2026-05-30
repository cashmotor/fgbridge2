# 消息

- **消息概述**：https://open.feishu.cn/document/server-docs/im-v1/introduction

## 消息管理
- **消息管理概述**： https://open.feishu.cn/document/server-docs/im-v1/message/intro
- **话题概述**： https://open.feishu.cn/document/im-v1/message/thread-introduction

- 消息内容（Content）结构：
    - **发送消息内容结构**：https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json
    - **接收消息内容结构**：https://open.feishu.cn/document/server-docs/im-v1/message-content-description/message_content

- **发送消息**：https://open.feishu.cn/document/server-docs/im-v1/message/create
- **回复消息**：https://open.feishu.cn/document/server-docs/im-v1/message/reply
- **转发消息**：https://open.feishu.cn/document/server-docs/im-v1/message/forward
- **获取会话历史消息**：https://open.feishu.cn/document/server-docs/im-v1/message/list
- **获取消息中的资源文件**：https://open.feishu.cn/document/server-docs/im-v1/message/get-2
- **获取指定消息的内容**：https://open.feishu.cn/document/server-docs/im-v1/message/get

- **事件**：
    - **接收消息**：https://open.feishu.cn/document/server-docs/im-v1/message/events/receive
    - **撤回消息**：https://open.feishu.cn/document/server-docs/im-v1/message/events/recalled

## 图片信息
- **上传图片**：https://open.feishu.cn/document/server-docs/im-v1/image/create
- **下载图片**：https://open.feishu.cn/document/server-docs/im-v1/image/get

## 文件信息
- **上传文件**：https://open.feishu.cn/document/server-docs/im-v1/file/create
- **下载文件**：https://open.feishu.cn/document/server-docs/im-v1/file/get

## 消息卡片
- **消息卡片资源概述**：https://open.feishu.cn/document/server-docs/im-v1/message-card/overview
- **更新已发送的消息卡片**：https://open.feishu.cn/document/server-docs/im-v1/message-card/patch

# 云文档

## 知识库
- **知识库概述**：https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview

- **节点**：
    - **创建知识空间节点**：https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/create
    - **获取知识空间节点信息**：https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/get_node
    - **获取知识空间子节点列表**：https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/list
    - **更新知识空间节点标题**：https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/update_title

## 文档
- **文档概述**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/docx-overview

- **文档**：
    - **创建文档**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/create
    - **获取文档基本信息**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/get
    - **获取文档纯文本内容**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/raw_content
    - **获取文档所有块**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/list

- **块**：
    - **创建块**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create
    - **更新块的内容**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/patch
    - **获取块的内容**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/get
    - **Markdown/HTML 内容转换为文档块**：https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/document/convert
    - **删除块**：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/batch_delete

# 云空间
- **云空间概述**：https://open.feishu.cn/document/server-docs/docs/drive-v1/introduction

## 文件
- **文件概述**：https://open.feishu.cn/document/docs/drive-v1/file/file-overview
- **获取文件元数据**：https://open.feishu.cn/document/server-docs/docs/drive-v1/file/batch_query
- **创建云文档**：https://open.feishu.cn/document/docs/drive-v1/file/create-cloud-document

- **导入文件**：
    - **导入文件概述**：https://open.feishu.cn/document/server-docs/docs/drive-v1/import_task/import-user-guide
    - **创建导入任务**：https://open.feishu.cn/document/server-docs/docs/drive-v1/import_task/create
    - **查询导入任务结果**：https://open.feishu.cn/document/server-docs/docs/drive-v1/import_task/get

- **导出云文档**：
    - **导出云文档概述**：https://open.feishu.cn/document/server-docs/docs/drive-v1/export_task/export-user-guide
    - **创建导出任务**：https://open.feishu.cn/document/server-docs/docs/drive-v1/export_task/create
    - **查询导出任务结果**：https://open.feishu.cn/document/server-docs/docs/drive-v1/export_task/get
    - **下载导出文件**：https://open.feishu.cn/document/server-docs/docs/drive-v1/export_task/download

## 素材
- **素材概述**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/introduction

- **上传素材**：
    - **上传素材**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/upload_all
    - **分片上传素材-预上传**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/multipart-upload-media/upload_prepare
    - **分片上传素材-上传分片**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/multipart-upload-media/upload_part
    - **分片上传素材-完成上传**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/multipart-upload-media/upload_finish

- **下载素材**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/download
- **获取素材临时下载链接**：https://open.feishu.cn/document/server-docs/docs/drive-v1/media/batch_get_tmp_download_url

# 机器人

## 事件

- **机器人自定义菜单事件**：https://open.feishu.cn/document/client-docs/bot-v3/events/menu
