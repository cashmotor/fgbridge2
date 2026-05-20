import json
import base64
import mimetypes
import os
from typing import Optional, List, Dict, Any
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
        logger.debug(f"Router 接收到事件: {event_type}")
        
        if event_type == "im.message.receive_v1":
            await self._handle_message(event.get("event", {}))
        elif event_type == "card.action.trigger":
            await self._handle_card_action(event.get("event", {}))
        elif event_type == "im.message.reaction.receive_v1":
            await self._handle_reaction(event.get("event", {}))

    async def _handle_message(self, event_data: dict):
        message = event_data.get("message", {})
        chat_id = message.get("chat_id")
        chat_type = message.get("chat_type")
        message_id = message.get("message_id")
        
        thread_id = message.get("thread_id") or ""
        root_id = message.get("root_id") or ""
        
        attachments = await self._process_attachments(message)
        content_json = json.loads(message.get("content", "{}"))
        text = content_json.get("text", "").strip()

        if not text and not attachments:
            return

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

        # 1. 核心增强：检测到新消息，自动失效挂起的授权
        await self._auto_expire_pending_confirms(topic_id)

        if config.reaction_get:
            await self.feishu.add_reaction(message_id, config.reaction_get)

        topic = await self.store.get_topic(topic_id)
        
        if is_subtask:
            if not topic:
                await self._bind_topic_and_route(chat_id, topic_id, message_id, text, attachments)
            else:
                await self._route_to_role(topic["role"], chat_id, message_id, text, attachments, topic, topic_id, message_id)
        else:
            await self._route_to_role(target_role, chat_id, message_id, text, attachments, topic, topic_id, message_id)

    async def _handle_reaction(self, event_data: dict):
        """处理表情授权逻辑"""
        # 修正：直接从 event_data 获取 operator_type (飞书 2.0 格式)
        operator_type = event_data.get("operator_type")
        if operator_type != "user":
            logger.debug(f"忽略非用户表情事件 (Operator: {operator_type})")
            return

        emoji_type = event_data.get("reaction_type", {}).get("emoji_type", "").upper()
        message_id = event_data.get("message_id")
        
        # 1. 查找该消息关联的授权请求
        pending = await self.store.get_pending_confirm_by_msg_id(message_id)
        if not pending:
            logger.debug(f"消息 {message_id} 未关联任何挂起的授权请求")
            return

        confirm_id = pending["confirm_id"]
        step = pending["confirm_step"]
        
        logger.info(f"Router 识别到授权表情: {emoji_type} (ConfirmID: {confirm_id}, Step: {step})")

        # 2. 匹配表情类型
        is_yes = emoji_type in [e.upper() for e in config.reaction_yes]
        is_no = emoji_type in [e.upper() for e in config.reaction_no]

        if not is_yes and not is_no:
            logger.debug(f"表情 {emoji_type} 不在 YES/NO 映射表中，忽略")
            return

        # 3. 执行逻辑分发
        if is_yes:
            if step == 1:
                confirm_msg = "⚠️ [二次确认] 确定要执行上述授权操作吗？\n请再次点赞(YES/OK)确认，或点踩(NO)取消。"
                new_msg_id = await self.feishu.reply(message_id, confirm_msg)
                if new_msg_id:
                    await self.store.update_pending_confirm_step(confirm_id, step=2, msg_id=new_msg_id)
                    logger.info(f"授权 {confirm_id} 进入二次确认阶段 (NewMsg: {new_msg_id})")
            else:
                await self._execute_confirm_decision(pending, "allow", message_id)
        
        elif is_no:
            if step == 2:
                logger.info(f"授权 {confirm_id} 在二次确认阶段被拒绝，正在回退...")
                prompt = f"🛑 操作已取消。如果需要重新授权，请在此前消息下回复表情：\n{pending['message']}\n\n👉 点 YES 同意，点 NO 拒绝。"
                new_msg_id = await self.feishu.reply(message_id, prompt)
                if new_msg_id:
                    await self.store.update_pending_confirm_step(confirm_id, step=1, msg_id=new_msg_id)
            else:
                await self._execute_confirm_decision(pending, "deny", message_id)

    async def _execute_confirm_decision(self, pending: dict, decision: str, current_msg_id: str):
        """执行最终授权决策并反馈"""
        confirm_id = pending["confirm_id"]
        topic_id = pending["topic_id"]
        session_id = pending["session_id"]
        
        topic = await self.store.get_topic(topic_id)
        role = topic["role"] if topic else config.assistant_role
        
        acp = self.dispatcher.get_acp(role)
        logger.info(f"正在执行授权决策: {confirm_id} -> {decision}")
        
        resp = acp.confirm(session_id, confirm_id, decision)
        acp.session_save(session_id)
        
        await self.store.remove_pending_confirm(confirm_id)
        
        status_text = "✅ 授权已通过，正在继续执行..." if decision == "allow" else "❌ 授权已拒绝。"
        await self.feishu.reply(current_msg_id, status_text)
        
        await self._handle_acp_response(resp, "", current_msg_id, session_id, topic_id)

    async def _auto_expire_pending_confirms(self, topic_id: str):
        """自动失效指定话题下的所有挂起授权"""
        pendings = await self.store.get_pending_confirms_by_topic(topic_id)
        for p in pendings:
            logger.info(f"检测到新消息，自动失效旧授权: {p['confirm_id']}")
            if p.get("msg_id"):
                await self.feishu.reply(p["msg_id"], "⌛ 此授权请求已因新消息输入而自动失效。")
            await self.store.remove_pending_confirm(p["confirm_id"])

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
                attachments.append({"type": "image", "data": data_base64, "mimeType": "image/png"})

        for key in file_keys:
            save_path = f"{config.attachment_dir}/{message_id}_{key[:8]}"
            if await self.feishu.download_resource(message_id, key, save_path):
                attachments.append({"type": "resource_link", "uri": f"file://{os.path.abspath(save_path)}"})
        return attachments

    async def _bind_topic_and_route(self, chat_id: str, topic_id: str, message_id: str, text: str, attachments: list):
        role = "Developer" 
        acp = self.dispatcher.get_acp(role)
        session_id = acp.session_new()
        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id)
        topic = await self.store.get_topic(topic_id)
        await self._route_to_role(role, chat_id, message_id, text, attachments, topic, topic_id, message_id)

    async def _route_to_role(self, role: str, chat_id: str, message_id: str, text: str, attachments: list, topic: dict, topic_id: str, origin_msg_id: str):
        acp = self.dispatcher.get_acp(role)
        session_id = None
        turn_count = (topic.get("turn_count") or 0) if topic else 0
        is_cold_start = False

        if topic and topic.get("session_id"):
            session_id = topic["session_id"]
            if acp._active_session_id != session_id:
                if not acp.session_load(session_id):
                    session_id = acp.session_new()
                    turn_count = 0
                else:
                    is_cold_start = True
        else:
            session_id = acp.session_new()
            turn_count = 0
        
        turn_count += 1
        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id, turn_count=turn_count)
        
        needs_role_init = is_cold_start or (turn_count == 1)
        if needs_role_init and config.acp_silent_flush_enabled:
            role_prompt = self.dispatcher.get_role_prompt(role)
            try:
                acp.send(session_id, role_prompt)
            except Exception as e:
                logger.error(f"角色注入执行异常: {e}")

        resp = acp.send(session_id, text, attachments)
        acp.session_save(session_id)
        await self._handle_acp_response(resp, chat_id, origin_msg_id, session_id, topic_id)
        await self._finalize_reaction(origin_msg_id)

    async def _finalize_reaction(self, message_id: str):
        if config.reaction_done:
            await self.feishu.add_reaction(message_id, config.reaction_done)
        if config.reaction_get:
            await self.feishu.delete_bot_reaction_by_type(message_id, config.reaction_get)

    async def _handle_acp_response(self, resp: dict, chat_id: str, message_id: str, session_id: str, topic_id: str) -> Optional[str]:
        result = resp.get("result", {})
        if result.get("type") == "confirmation_required":
            confirm_id = result.get("confirmationId")
            action = result.get("action")
            message = result.get("message")
            
            if config.acp_card_mode_enabled:
                await self.store.add_pending_confirm(confirm_id, topic_id, session_id, action, message)
                card_content = CardBuilder.build_permission_card(confirm_id, action, message)
                return await self.feishu.reply(message_id, card_content, msg_type="interactive")
            else:
                prompt = f"🔐 [安全拦截] 进程申请执行高危操作：\n\n**{action}**\n\n{message}\n\n👉 **授权方式**：\n请在此消息下回复表情：点赞(YES/OK)同意，点踩(NO)拒绝。"
                sent_msg_id = await self.feishu.reply(message_id, prompt)
                if sent_msg_id:
                    await self.store.add_pending_confirm(confirm_id, topic_id, session_id, action, message, msg_id=sent_msg_id, confirm_step=1)
                    logger.info(f"已发送授权请求消息: {sent_msg_id}")
                return sent_msg_id
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
        
        await self._execute_confirm_decision(pending, decision, event_data.get("context", {}).get("message_id"))
        
        new_card = CardBuilder.build_result_card(pending["action_type"], decision)
        await self.feishu.client.im.v1.message.apatch(
            lark.im.v1.PatchMessageRequest.builder()
            .message_id(event_data.get("context", {}).get("message_id"))
            .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(new_card).build())
            .build()
        )
