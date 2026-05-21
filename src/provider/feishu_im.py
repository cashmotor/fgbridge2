import os
import json
import httpx
import re
import asyncio
from typing import Optional, List, Any, Dict
from urllib.parse import urlparse
from loguru import logger
import lark_oapi as lark
from src.config import config

class FeishuUrlResolver:
    """
    飞书 URL 解析器
    支持解析各种飞书文档 URL (Sheet, Docx, Wiki, Bitable)
    """

    PATTERNS = {
        "sheet": re.compile(r"/sheets/([a-zA-Z0-9]+)"),
        "wiki": re.compile(r"/wiki/([a-zA-Z0-9]+)"),
        "docx": re.compile(r"/docx/([a-zA-Z0-9]+)"),
        "bitable": re.compile(r"/base/([a-zA-Z0-9]+)"),
    }

    def __init__(self, client: lark.Client):
        self.client = client

    def parse(self, url: str) -> Optional[Dict[str, str]]:
        """
        解析 URL 并返回基础信息 {token, type}
        """
        parsed = urlparse(url)
        path = parsed.path

        for type_name, pattern in self.PATTERNS.items():
            match = pattern.search(path)
            if match:
                return {"token": match.group(1), "type": type_name}
        return None

    async def a_resolve_wiki_node(self, wiki_token: str) -> tuple[str, str]:
        """
        异步调用 Wiki API 获取 Wiki 节点对应的实际对象 Token 和类型
        返回: (obj_token, obj_type)
        """
        try:
            logger.debug(f"正在解析 Wiki 节点: {wiki_token}")
            request = (
                lark.wiki.v2.GetNodeSpaceRequest.builder().token(wiki_token).build()
            )
            response = await self.client.wiki.v2.space.aget_node(request)

            if response.success():
                node = response.data.node
                return node.obj_token, node.obj_type
            
            logger.warning(f"Wiki 节点解析失败: {response.msg} (code: {response.code})，尝试 Drive 搜索...")
            
            # 备选方案：Drive API 搜索 (兼容某些特殊情况)
            req = (
                lark.BaseRequest.builder()
                .http_method(lark.HttpMethod.GET)
                .uri("/open-apis/drive/v1/files")
                .token_types({lark.AccessTokenType.TENANT})
                .queries([("folder_token", wiki_token)])
                .build()
            )
            resp = await self.client.arequest(req)
            if resp.success():
                data = json.loads(str(resp.raw.content, lark.UTF_8))
                files = data.get("data", {}).get("files", [])
                if files:
                    return files[0].get("token"), files[0].get("type")

            raise Exception(f"无法解析 Wiki 节点 [{wiki_token}]")
        except Exception as e:
            logger.error(f"Wiki 解析异常: {e}")
            raise

class FeishuIMProvider:
    """
    飞书 IM API 封装，负责消息发送、回复及资源处理
    """
    def __init__(self):
        self.client = (
            lark.Client.builder()
            .app_id(config.feishu_app_id)
            .app_secret(config.feishu_app_secret)
            .log_level(lark.LogLevel.ERROR)
            .build()
        )
        self.resolver = FeishuUrlResolver(self.client)

    async def send_text(self, receive_id: str, content: str, receive_id_type: str = "chat_id") -> Optional[str]:
        """发送文本或互动卡片消息 (自动识别内容格式)"""
        msg_type = "text"
        processed_content = json.dumps({"text": content})
        
        try:
            card_data = json.loads(content)
            if isinstance(card_data, dict) and ("elements" in card_data or "header" in card_data):
                msg_type = "interactive"
                processed_content = content
                logger.debug(f"准备发送互动卡片: {content}")
        except:
            pass

        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type(msg_type)
                .content(processed_content)
                .build()
            )
            .build()
        )
        response = await self.client.im.v1.message.acreate(request)
        if response.success():
            return response.data.message_id
        logger.error(f"发送消息失败: {response.msg}")
        return None

    async def reply(self, message_id: str, content: str, msg_type: str = "text") -> Optional[str]:
        """回复指定消息"""
        if msg_type == "interactive":
            logger.debug(f"准备回复互动卡片: {content}")
            
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .msg_type(msg_type)
                .content(content if msg_type != "text" else json.dumps({"text": content}))
                .build()
            )
            .build()
        )
        response = await self.client.im.v1.message.areply(request)
        if response.success():
            return response.data.message_id
        logger.error(f"回复消息失败: {response.msg}")
        return None

    async def download_resource(self, message_id: str, file_key: str, save_path: str, resource_type: str = "image") -> bool:
        """下载消息中的资源文件"""
        request = (
            lark.im.v1.GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(resource_type)
            .build()
        )
        response = await self.client.im.v1.message_resource.aget(request)
        if response.success():
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.file.read())
            return True
        
        logger.error(f"[download_resource] 失败: {response.msg} (code: {response.code}, type: {resource_type}, key: {file_key})")
        return False

    async def download_image(self, image_key: str, save_path: str, message_id: Optional[str] = None) -> bool:
        """
        下载图片逻辑：优先尝试消息资源接口（支持权限穿透），失败则尝试专用图片接口
        """
        clean_key = str(image_key).strip().replace("\"", "").replace("'", "")
        try:
            # 策略 A: 优先使用消息资源接口 (GetMessageResource)
            if message_id:
                logger.debug(f"[download_image] 尝试通过消息资源接口下载: {clean_key}")
                if await self.download_resource(message_id, clean_key, save_path, resource_type="image"):
                    return True

            # 策略 B: 兜底使用专用图片接口 (GetImage)
            logger.warning(f"[download_image] 消息资源接口不可用或失败，尝试专用图片接口: {clean_key}")
            request = lark.im.v1.GetImageRequest.builder().image_key(clean_key).build()
            response = await asyncio.to_thread(self.client.im.v1.image.get, request)
            
            if response.success():
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(response.file.read())
                logger.success(f"[download_image] 专用图片接口下载成功: {clean_key}")
                return True
            
            # 记录最终失败详情
            log_id = response.get_log_id()
            error_msg = f"All image download strategies failed. Last attempt (GetImage) code: {response.code}, msg: {response.msg}, log_id: {log_id}"
            logger.error(error_msg)
            return False

        except Exception as e:
            logger.exception(f"[download_image] 发生异常: {e}, key: {clean_key}")
            return False

    async def add_reaction(self, message_id: str, emoji_type: str) -> Optional[str]:
        """为消息添加表情回复"""
        request = (
            lark.im.v1.CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                lark.im.v1.CreateMessageReactionRequestBody.builder()
                .reaction_type(lark.im.v1.Emoji.builder().emoji_type(emoji_type).build())
                .build()
            )
            .build()
        )
        response = await self.client.im.v1.message_reaction.acreate(request)
        if response.success():
            return response.data.reaction_id
        
        logger.error(f"[add_reaction] 失败: {response.msg} (code: {response.code}, emoji: {emoji_type}, msg_id: {message_id})")
        return None

    async def delete_bot_reaction_by_type(self, message_id: str, emoji_type: str) -> bool:
        """通过即时查询并匹配，删除机器人自己添加的特定类型表情"""
        try:
            # 1. 查询该消息下的所有表情
            list_req = (
                lark.im.v1.ListMessageReactionRequest.builder()
                .message_id(message_id)
                .build()
            )
            list_resp = await self.client.im.v1.message_reaction.alist(list_req)
            
            if not list_resp.success():
                return False
            
            # 2. 遍历并匹配 (找到自己发的且类型一致的)
            items = list_resp.data.items or []
            for item in items:
                # 检查表情类型是否匹配
                if item.reaction_type.emoji_type.upper() == emoji_type.upper():
                    # 关键：检查操作者是否为当前 App (即机器人自己)
                    if item.operator.operator_type == "app":
                        # 3. 执行精准删除
                        del_req = (
                            lark.im.v1.DeleteMessageReactionRequest.builder()
                            .message_id(message_id)
                            .reaction_id(item.reaction_id)
                            .build()
                        )
                        await self.client.im.v1.message_reaction.adelete(del_req)
                        logger.debug(f"成功清理机器人表情: {emoji_type} (ID: {item.reaction_id[:10]}...)")
                        return True
            return False
        except Exception as e:
            logger.error(f"清理机器人表情异常: {e}")
            return False

    async def get_message_content(self, message_id: str) -> Optional[str]:
        request = (lark.im.v1.GetMessageRequest.builder().message_id(message_id).build())
        response = await self.client.im.v1.message.aget(request)
        if response.success():
            content_str = response.data.items[0].body.content
            try:
                content_json = json.loads(content_str)
                return content_json.get("text", "")
            except:
                return content_str
        return None

    async def aexport_document(self, token: str, obj_type: str, file_extension: str = "pdf") -> Optional[bytes]:
        """
        导出飞书文档为指定格式 (异步)
        :param token: 文档 token 或 wiki token
        :param obj_type: "docx", "sheet", "bitable", "doc", "wiki"
        :param file_extension: "pdf", "docx", "xlsx" 等
        """
        try:
            # 0. 如果是 Wiki 节点，先解析出实际的对象 Token 和 类型
            if obj_type == "wiki":
                logger.debug(f"检测到 Wiki 导出请求，正在解析实际节点信息: {token}")
                token, obj_type = await self.resolver.a_resolve_wiki_node(token)
                logger.debug(f"Wiki 节点解析结果: token={token}, type={obj_type}")

            # 1. 创建导出任务
            request = (
                lark.drive.v1.CreateExportTaskRequest.builder()
                .request_body(
                    lark.drive.v1.ExportTask.builder()
                    .file_extension(file_extension)
                    .token(token)
                    .type(obj_type)
                    .build()
                )
                .build()
            )
            response = await self.client.drive.v1.export_task.acreate(request)
            if not response.success():
                logger.error(f"创建导出任务失败: {response.msg} (token={token}, type={obj_type})")
                return None
            
            ticket = response.data.ticket
            
            # 2. 轮询任务状态
            max_retries = 30
            for i in range(max_retries):
                await asyncio.sleep(2)  # 等待 2 秒
                get_req = (
                    lark.drive.v1.GetExportTaskRequest.builder()
                    .ticket(ticket)
                    .token(token)
                    .build()
                )
                get_resp = await self.client.drive.v1.export_task.aget(get_req)
                if not get_resp.success():
                    logger.warning(f"获取导出任务状态失败 ({i+1}): {get_resp.msg}")
                    continue
                
                result = get_resp.data.result
                status = result.job_status
                if status == 0:  # 成功
                    file_token = result.file_token
                    return await self._adownload_export_file(file_token)
                elif status in [1, 2]: # 初始化 or 处理中
                    logger.debug(f"导出任务处理中 ({i+1})...")
                    continue
                else:
                    logger.error(f"导出任务失败, status: {status}, msg: {result.job_error_msg}")
                    return None
            
            logger.error("导出任务超时")
            return None
        except Exception as e:
            logger.error(f"导出文档异常: {e}")
            return None

    async def _adownload_export_file(self, file_token: str) -> Optional[bytes]:
        """下载导出后的文件 (异步)"""
        try:
            request = (
                lark.drive.v1.DownloadExportTaskRequest.builder()
                .file_token(file_token)
                .build()
            )
            response = await self.client.drive.v1.export_task.adownload(request)
            if response.success():
                return response.raw.content
            else:
                logger.error(f"下载导出文件失败: {response.msg}")
                return None
        except Exception as e:
            logger.error(f"下载导出文件异常: {e}")
            return None

    async def aget_docx_markdown(self, docx_token: str) -> str:
        """获取飞书文档 (Docx) 内容并转换为 Markdown (异步)"""
        try:
            # 1. 获取文档所有 Block IDs
            request = (
                lark.docx.v1.ListDocumentBlockRequest.builder()
                .document_id(docx_token)
                .build()
            )
            response = await self.client.docx.v1.document_block.alist(request)
            
            if not response.success():
                logger.error(f"获取文档 Block 列表失败: {response.msg}")
                return f"[读取文档失败: {response.msg}]"

            blocks = response.data.items
            block_map = {b.block_id: b for b in blocks}
            
            # 文档根节点通常是第一个 block
            root_id = blocks[0].block_id if blocks else ""
            if not root_id:
                return ""

            # 递归解析 Blocks
            return self._parse_docx_blocks(docx_token, root_id, block_map)
        except Exception as e:
            logger.error(f"解析飞书文档异常: {e}")
            return f"[解析文档异常: {e}]"

    def _parse_docx_blocks(self, docx_token: str, block_id: str, block_map: Dict[str, Any]) -> str:
        """递归解析 Docx Block 树并生成 Markdown"""
        block = block_map.get(block_id)
        if not block:
            return ""

        md_parts = []
        b_type = block.block_type
        
        # 处理不同类型的 Block
        if b_type == 2: # Text
            text_run = block.text
            if text_run and text_run.elements:
                for el in text_run.elements:
                    if el.text_run:
                        md_parts.append(el.text_run.content)
            md_parts.append("\n")
        elif 3 <= b_type <= 11: # Headings
            level = b_type - 2
            prefix = "#" * level + " "
            md_parts.append(prefix)
            text_run = getattr(block, f"heading{level}", None)
            if text_run and text_run.elements:
                for el in text_run.elements:
                    if el.text_run:
                        md_parts.append(el.text_run.content)
            md_parts.append("\n\n")
        elif b_type == 14: # Code
            code = block.code
            lang = code.style.language if code.style else "text"
            md_parts.append(f"```{lang}\n")
            if code.elements:
                for el in code.elements:
                    if el.text_run:
                        md_parts.append(el.text_run.content)
            md_parts.append("\n```\n\n")
        elif b_type == 31: # Table
            md_parts.append("\n[表格内容已忽略，暂不支持复杂表格提取]\n\n")

        # 递归处理子节点
        if block.children:
            for child_id in block.children:
                md_parts.append(self._parse_docx_blocks(docx_token, child_id, block_map))

        return "".join(md_parts)
