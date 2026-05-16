import os
import json
import httpx
from typing import Optional, List, Any
from loguru import logger
import lark_oapi as lark
from src.config import config

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

    async def send_text(self, receive_id: str, content: str, receive_id_type: str = "chat_id") -> Optional[str]:
        """发送普通文本消息"""
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(json.dumps({"text": content}))
                .build()
            )
            .build()
        )
        response = await self.client.im.v1.message.acreate(request)
        if response.success():
            return response.data.message_id
        logger.error(f"发送文本消息失败: {response.msg}")
        return None

    async def reply(self, message_id: str, content: str, msg_type: str = "text") -> Optional[str]:
        """回复指定消息"""
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

    async def download_resource(self, message_id: str, file_key: str, save_path: str) -> bool:
        """下载消息中的资源文件 (图片/文件)"""
        # 飞书 SDK 的 aget_resource 可能返回 bytes
        request = (
            lark.im.v1.GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .build()
        )
        response = await self.client.im.v1.message_resource.aget(request)
        
        if response.success():
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.file.read())
            return True
        logger.error(f"下载资源失败: {response.msg}")
        return False

    async def get_message_content(self, message_id: str) -> Optional[str]:
        """获取指定消息的文本内容"""
        request = (
            lark.im.v1.GetMessageRequest.builder()
            .message_id(message_id)
            .build()
        )
        response = await self.client.im.v1.message.aget(request)
        if response.success():
            content_str = response.data.items[0].body.content
            try:
                content_json = json.loads(content_str)
                return content_json.get("text", "")
            except:
                return content_str
        return None
