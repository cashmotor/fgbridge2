import json
import base64
import mimetypes
import os
from loguru import logger
from src.storage.state_store import StateStore
from src.engine.dispatcher import ACPDispatcher
from src.provider.feishu_im import FeishuIMProvider
from src.utils.card_builder import CardBuilder
from src.config import config

class Router:
    """
    事件路由引擎，负责 Scope-Topic 识别、角色委派及消息分发
    """
    def __init__(self, store: StateStore, dispatcher: ACPDispatcher, feishu: FeishuIMProvider):
        self.store = store
        self.dispatcher = dispatcher
        self.feishu = feishu

    async def dispatch(self, event: dict):
        header = event.get("header", {})
        event_type = header.get("event_type")
        
        if event_type == "im.message.receive_v1":
            await self._handle_message(event.get("event", {}))
        elif event_type == "card.action.trigger":
            await self._handle_card_action(event.get("event", {}))

    async def _handle_message(self, event_data: dict):
        message = event_data.get("message", {})
        chat_id = message.get("chat_id")
        message_id = message.get("message_id")
        root_id = message.get("root_id") or ""
        
        # 处理多模态附件
        attachments = await self._process_attachments(message)
        
        content_json = json.loads(message.get("content", "{}"))
        text = content_json.get("text", "").strip()

        if not text and not attachments:
            return

        # 1. 路由识别
        if not root_id:
            await self._route_to_role(config.assistant_role, chat_id, message_id, text, attachments)
        else:
            topic = await self.store.get_topic(root_id)
            if not topic:
                await self._bind_topic_and_route(chat_id, root_id, message_id, text, attachments)
            else:
                await self._route_to_role(topic["role"], chat_id, message_id, text, attachments, topic)

    async def _process_attachments(self, message: dict) -> list:
        """识别并下载消息中的图片/文件"""
        attachments = []
        message_id = message.get("message_id")
        
        # 1. 处理图片
        image_keys = message.get("image_keys", [])
        for key in image_keys:
            save_path = f"{config.attachment_dir}/{message_id}_{key[:8]}.png"
            if await self.feishu.download_resource(message_id, key, save_path):
                with open(save_path, "rb") as f:
                    data_base64 = base64.b64encode(f.read()).decode("utf-8")
                attachments.append({
                    "type": "image",
                    "data": data_base64,
                    "mimeType": "image/png"
                })
                logger.info(f"成功载入图片附件: {key}")

        # 2. 处理文件
        file_keys = message.get("file_keys", [])
        for key in file_keys:
            # 飞书 SDK 返回的文件名逻辑
            save_path = f"{config.attachment_dir}/{message_id}_{key[:8]}"
            if await self.feishu.download_resource(message_id, key, save_path):
                attachments.append({
                    "type": "resource_link",
                    "uri": f"file://{os.path.abspath(save_path)}"
                })
                logger.info(f"成功载入文件附件: {key}")

        return attachments

    async def _bind_topic_and_route(self, chat_id: str, root_id: str, message_id: str, text: str, attachments: list):
        # 1. 调用助理识别意图 (简化版：目前先硬编码 Developer，但通过助理 ACP 逻辑预留)
        # acp_assistant = self.dispatcher.get_acp(config.assistant_role)
        role = "Developer" 
        acp_expert = self.dispatcher.get_acp(role)
        session_id = acp_expert.session_new()
        
        await self.store.save_topic(root_id, chat_id, role=role, session_id=session_id)
        topic = await self.store.get_topic(root_id)
        await self._route_to_role(role, chat_id, message_id, text, attachments, topic)

    async def _route_to_role(self, role: str, chat_id: str, message_id: str, text: str, attachments: list, topic: dict = None):
        acp = self.dispatcher.get_acp(role)
        
        if topic:
            session_id = topic["session_id"]
            # 关键：如果 ACP 进程是新唤醒的（或不包含该会话），尝试从磁盘加载
            # 这里简化逻辑：总是尝试 load，ACP 内部会处理是否存在
            logger.info(f"正在尝试恢复话题记忆 (session_id: {session_id})")
            if not acp.session_load(session_id):
                logger.warning(f"话题 {topic['topic_id']} 记忆恢复失败，将作为新会话处理")
                session_id = acp.session_new()
        else:
            session_id = acp.session_new()
        
        # 更新活跃时间及最新的 session_id (防止新建)
        await self.store.save_topic(topic["topic_id"] if topic else message_id, chat_id, role=role, session_id=session_id)

        # 发送请求
        resp = acp.send(session_id, text, attachments)
        
        # 响应后立即保存记忆 (实现 FR-2.2 的及时性)
        acp.session_save(session_id)
        
        await self._handle_acp_response(resp, chat_id, message_id, session_id, topic["topic_id"] if topic else message_id)

    async def _handle_acp_response(self, resp: dict, chat_id: str, message_id: str, session_id: str, topic_id: str):
        result = resp.get("result", {})
        
        if result.get("type") == "confirmation_required":
            confirm_id = result.get("confirmationId")
            action = result.get("action")
            message = result.get("message")
            
            # 记录挂起状态
            await self.store.add_pending_confirm(confirm_id, topic_id or message_id, session_id, action, message)
            
            # 发送确认卡片
            card_content = CardBuilder.build_permission_card(confirm_id, action, message)
            await self.feishu.reply(message_id, card_content, msg_type="interactive")
        else:
            # 发送最终回答
            content = result.get("content", str(result))
            await self.feishu.reply(message_id, content)

    async def _handle_card_action(self, event_data: dict):
        action_value = event_data.get("action", {}).get("value", {})
        confirm_id = action_value.get("confirm_id")
        decision = action_value.get("decision")
        
        if not confirm_id: return
        
        pending = await self.store.get_pending_confirm(confirm_id)
        if not pending: return
        
        # 找到对应的 ACP 进程并确认
        # 这里需要 Dispatcher 支持通过 session_id 找进程，或者通过 role
        # 简化版：假设专家角色
        acp = self.dispatcher.get_acp("Developer") # TODO: 动态找角色
        resp = acp.confirm(pending["session_id"], confirm_id, decision)
        
        await self.store.remove_pending_confirm(confirm_id)
        
        # 更新卡片状态
        new_card = CardBuilder.build_result_card(pending["action_type"], decision)
        await self.feishu.client.im.v1.message.apatch(
            lark.im.v1.PatchMessageRequest.builder()
            .message_id(event_data.get("context", {}).get("message_id"))
            .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(new_card).build())
            .build()
        )
        
        # 处理确认后的结果
        await self._handle_acp_response(resp, "", "", pending["session_id"], pending["topic_id"])
