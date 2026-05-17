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

    async def download_resource(self, message_id: str, file_key: str, save_path: str) -> bool:
        """下载消息中的资源文件"""
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
