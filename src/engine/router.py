import json
import base64
import mimetypes
import os
from typing import Optional
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
        chat_type = message.get("chat_type") # "p2p" or "group"
        message_id = message.get("message_id")
        
        # 1. 立即推送 Get 气泡反馈 (通过一条临时的回复消息)
        ack_msg_id = None
        if config.follow_up_get:
            ack_msg_id = await self.feishu.reply(message_id, "⌛")
            if ack_msg_id:
                await self.feishu.push_follow_up(ack_msg_id, config.follow_up_get)

        thread_id = message.get("thread_id") or ""
...
        root_id = message.get("root_id") or ""
        
        # 处理多模态附件
        attachments = await self._process_attachments(message)
        
        content_json = json.loads(message.get("content", "{}"))
        text = content_json.get("text", "").strip()

        if not text and not attachments:
            return

        # --- 精准差异化路由逻辑 ---
        topic_id = ""
        target_role = ""
        is_subtask = False

        if chat_type == "p2p":
            if thread_id:
                topic_id = thread_id
                is_subtask = True
            else:
                topic_id = chat_id
                target_role = config.assistant_role
        else:
            if thread_id:
                topic_id = thread_id
                is_subtask = True
            elif root_id:
                topic_id = root_id
                target_role = config.assistant_role
            else:
                topic_id = chat_id
                target_role = config.assistant_role

        # --- 统一执行数据库寻回 ---
        topic = await self.store.get_topic(topic_id)
        
        if is_subtask:
            if not topic:
                await self._bind_topic_and_route(chat_id, topic_id, message_id, text, attachments)
            else:
                await self._route_to_role(topic["role"], chat_id, message_id, text, attachments, topic, topic_id)
        else:
            await self._route_to_role(target_role, chat_id, message_id, text, attachments, topic, topic_id)

    async def _process_attachments(self, message: dict) -> list:
        attachments = []
        message_id = message.get("message_id")
        image_keys = message.get("image_keys", [])
        file_keys = message.get("file_keys", [])
        
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

        for key in file_keys:
            save_path = f"{config.attachment_dir}/{message_id}_{key[:8]}"
            if await self.feishu.download_resource(message_id, key, save_path):
                attachments.append({
                    "type": "resource_link",
                    "uri": f"file://{os.path.abspath(save_path)}"
                })

        return attachments

    async def _bind_topic_and_route(self, chat_id: str, root_id: str, message_id: str, text: str, attachments: list):
        role = "Developer" 
        acp = self.dispatcher.get_acp(role)
        session_id = acp.session_new()
        await self.store.save_topic(root_id, chat_id, role=role, session_id=session_id)
        topic = await self.store.get_topic(root_id)
        await self._route_to_role(role, chat_id, message_id, text, attachments, topic, root_id)

    async def _route_to_role(self, role: str, chat_id: str, message_id: str, text: str, attachments: list, topic: dict, topic_id: str):
        acp = self.dispatcher.get_acp(role)
        session_id = None

        if topic and topic.get("session_id"):
            session_id = topic["session_id"]
            logger.info(f"检测到历史会话，尝试寻回内存/磁盘记忆: {session_id} (Role: {role})")
            if not acp.session_load(session_id):
                logger.warning(f"记忆寻回失败 (可能已被 CLI 清理)，将作为新会话处理")
                session_id = acp.session_new()
        else:
            session_id = acp.session_new()
        
        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id)
        resp = acp.send(session_id, text, attachments)
        acp.session_save(session_id)
        
        # 5. 发送正式回答并追加 Done 气泡
        resp_msg_id = await self._handle_acp_response(resp, chat_id, message_id, session_id, topic_id)
        if resp_msg_id and config.follow_up_done:
            await self.feishu.push_follow_up(resp_msg_id, config.follow_up_done)

    async def _handle_acp_response(self, resp: dict, chat_id: str, message_id: str, session_id: str, topic_id: str) -> Optional[str]:
        result = resp.get("result", {})
        if result.get("type") == "confirmation_required":
            confirm_id = result.get("confirmationId")
            action = result.get("action")
            message = result.get("message")
            await self.store.add_pending_confirm(confirm_id, topic_id, session_id, action, message)
            card_content = CardBuilder.build_permission_card(confirm_id, action, message)
            return await self.feishu.reply(message_id, card_content, msg_type="interactive")
        else:
            content = result.get("content", str(result))
            return await self.feishu.reply(message_id, content)

    async def _handle_card_action(self, event_data: dict):
        action_value = event_data.get("action", {}).get("value", {})
        confirm_id = action_value.get("confirm_id")
        decision = action_value.get("decision")
        if not confirm_id: return
        pending = await self.store.get_pending_confirm(confirm_id)
        if not pending: return
        topic = await self.store.get_topic(pending["topic_id"])
        role = topic["role"] if topic else config.assistant_role
        acp = self.dispatcher.get_acp(role)
        resp = acp.confirm(pending["session_id"], confirm_id, decision)
        acp.session_save(pending["session_id"])
        await self.store.remove_pending_confirm(confirm_id)
        new_card = CardBuilder.build_result_card(pending["action_type"], decision)
        await self.feishu.client.im.v1.message.apatch(
            lark.im.v1.PatchMessageRequest.builder()
            .message_id(event_data.get("context", {}).get("message_id"))
            .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(new_card).build())
            .build()
        )
        await self._handle_acp_response(resp, "", "", pending["session_id"], pending["topic_id"])
