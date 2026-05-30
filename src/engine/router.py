import json
import base64
import mimetypes
import os
import re
import asyncio
import time
import traceback
from typing import Optional, List, Dict, Any
from loguru import logger
import lark_oapi as lark
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
        
        try:
            if event_type == "im.message.receive_v1":
                await self._handle_message(event.get("event", {}))
            elif event_type == "card.action.trigger":
                await self._handle_card_action(event.get("event", {}))
            elif event_type == "im.message.reaction.receive_v1":
                await self._handle_reaction(event.get("event", {}))
            elif event_type == "application.bot.menu_v6":
                await self._handle_menu_event(event.get("event", {}))
        except Exception as e:
            logger.exception(f"调度事件发生致命错误: {e}")
            # 尝试给管理员发一张报错卡片
            await self._report_system_error(f"事件分发失败: {event_type}", e)

    def _check_operator_permission(self, operator_data: dict) -> bool:
        """校验操作人权限"""
        open_id = operator_data.get("operator_id", {}).get("open_id")
        if not open_id:
            return False
        if not config.feishu_user_ids:
            return True # 未配置白名单则默认允许
        return open_id in config.feishu_user_ids

    async def _report_system_error(self, summary: str, error: Exception, chat_id: str = None):
        """统一向用户/群组上报异常卡片"""
        # 1. 构造卡片
        error_detail = traceback.format_exc()
        card = CardBuilder.build_error_card(summary, str(error))
        
        # 2. 决定发送目标：如果有具体的 chat_id，发给当前上下文；否则发给管理员白名单首位
        target_id = chat_id
        if not target_id and config.feishu_user_ids:
            target_id = config.feishu_user_ids[0]
            
        if target_id:
            logger.info(f"正在向上报目标 {target_id} 发送异常卡片...")
            await self.feishu.send_text(target_id, card, receive_id_type="open_id" if "ou_" in target_id else "chat_id")

    async def _handle_message(self, event_data: dict):
        message = event_data.get("message", {})
        chat_id = message.get("chat_id")
        chat_type = message.get("chat_type")
        message_id = message.get("message_id")
        msg_type = message.get("message_type") or message.get("msg_type")
        
        logger.debug(f"[_handle_message] 开始处理消息: ID={message_id}, 类型={msg_type}")
        
        if config.reaction_get:
            asyncio.create_task(self.feishu.add_reaction(message_id, config.reaction_get))

        thread_id = message.get("thread_id") or ""
        root_id = message.get("root_id") or ""
        
        content_str = message.get("content", "{}")
        try:
            content_json = json.loads(content_str)
        except Exception as e:
            logger.error(f"[_handle_message] 解析消息内容 JSON 失败: {e}")
            content_json = {}

        text = ""
        extracted_image_keys = []
        if msg_type == "text":
            text = content_json.get("text", "")
        elif msg_type == "post":
            for block_list in content_json.get("content", []):
                for element in block_list:
                    if element.get("tag") == "text":
                        text += element.get("text", "")
                    elif element.get("tag") == "img":
                        extracted_image_keys.append(element.get("image_key"))
        elif msg_type == "image":
            if "image_key" in content_json:
                extracted_image_keys.append(content_json["image_key"])

        text = text.strip()
        if extracted_image_keys:
            existing_keys = message.get("image_keys") or []
            message["image_keys"] = list(set(existing_keys + extracted_image_keys))
        
        try:
            extra_text, attachments = await self._process_attachments(message, text)
            if extra_text:
                text += extra_text

            if not text and not attachments:
                if config.reaction_invalid:
                    await self.feishu.add_reaction(message_id, config.reaction_invalid)
                return

            topic_id = ""
            target_role = ""
            is_subtask = False
            open_id = event_data.get("sender", {}).get("sender_id", {}).get("open_id")

            if chat_type == "p2p":
                topic_id = thread_id if thread_id else chat_id
                target_role = config.assistant_role
                is_subtask = bool(thread_id)
                
                if open_id and chat_id:
                    await self.store.save_user_chat(open_id, chat_id)
                if open_id and not is_subtask:
                    if await self.store.get_topic(open_id):
                        await self.store.migrate_topic_and_sessions(open_id, chat_id)
            else:
                if thread_id:
                    topic_id, is_subtask = thread_id, True
                elif root_id:
                    topic_id, target_role = root_id, config.assistant_role
                else:
                    topic_id, target_role = chat_id, config.assistant_role

            await self._auto_expire_pending_confirms(topic_id)
            topic = await self.store.get_topic(topic_id)
            
            if is_subtask and not topic:
                await self._bind_topic_and_route(chat_id, topic_id, message_id, text, attachments)
            else:
                role = topic["role"] if topic else target_role
                await self._route_to_role(role, chat_id, message_id, text, attachments, topic, topic_id, message_id)
        except Exception as e:
            logger.exception(f"处理消息过程中发生异常: {e}")
            await self._report_system_error("消息解析与路由失败", e, chat_id)

    async def _handle_reaction(self, event_data: dict):
        """处理表情授权逻辑"""
        if config.acp_card_mode_enabled: return
        
        operator_type = event_data.get("operator_type")
        if operator_type != "user": return

        emoji_type = event_data.get("reaction_type", {}).get("emoji_type", "").upper()
        message_id = event_data.get("message_id")
        
        try:
            pending = await self.store.get_pending_confirm_by_msg_id(message_id)
            if not pending: return

            confirm_id, step = pending["confirm_id"], pending["confirm_step"]
            is_yes = emoji_type in [e.upper() for e in config.reaction_yes]
            is_no = emoji_type in [e.upper() for e in config.reaction_no]

            if not is_yes and not is_no: return

            if is_yes:
                if step == 1:
                    confirm_msg = "⚠️ [二次确认] 确定要执行上述授权操作吗？\n请再次点赞(YES/OK)确认，或点踩(NO)取消。"
                    new_id = await self.feishu.reply(message_id, confirm_msg)
                    if new_id: await self.store.update_pending_confirm_step(confirm_id, step=2, msg_id=new_id)
                else:
                    await self._execute_confirm_decision(pending, "allow", message_id)
            elif is_no:
                if step == 2:
                    prompt = f"🛑 操作已取消。如果需要重新授权，请在此前消息下回复表情：\n{pending['message']}\n\n👉 点 YES 同意，点 NO 拒绝。"
                    new_id = await self.feishu.reply(message_id, prompt)
                    if new_id: await self.store.update_pending_confirm_step(confirm_id, step=1, msg_id=new_id)
                else:
                    await self._execute_confirm_decision(pending, "deny", message_id)
        except Exception as e:
            logger.exception(f"处理表情事件失败: {e}")
            # 表情事件通常是静默报错，不一定需要打扰用户，但在 DEBUG 期间可以上报
            # await self._report_system_error("表情授权执行失败", e)

    async def _handle_menu_event(self, event_data: dict):
        """处理机器人自定义菜单事件 (UX 优化版)"""
        operator = event_data.get("operator", {})
        event_key = event_data.get("event_key")
        open_id = operator.get("operator_id", {}).get("open_id")
        
        if not self._check_operator_permission(operator):
            logger.warning(f"非法菜单操作: {open_id}")
            if open_id:
                card = CardBuilder.build_simple_text_card("🚫 无权操作", "抱歉，您不在授权名单中，无法使用此菜单。")
                await self.feishu.send_text(open_id, card, receive_id_type="open_id")
            return

        chat_id = await self.store.get_chat_id_by_open_id(open_id)
        topic_id = chat_id if chat_id else open_id

        try:
            if event_key == "FGB_NEW_SESSION":
                p_card = CardBuilder.build_processing_card("🆕 正在开启新会话", "系统正在初始化全新的 Gemini 上下文...")
                card_id = await self.feishu.send_text(open_id, p_card, receive_id_type="open_id")
                
                acp = await asyncio.to_thread(self.dispatcher.get_acp, config.assistant_role)
                session_id = await asyncio.to_thread(acp.session_new)
                await self.store.save_topic(topic_id, chat_id or open_id, role=config.assistant_role, session_id=session_id, turn_count=0)
                
                if card_id:
                    await self.feishu.client.im.v1.message.apatch(
                        lark.im.v1.PatchMessageRequest.builder()
                        .message_id(card_id)
                        .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(CardBuilder.build_new_session_card(session_id)).build())
                        .build()
                    )
                    
            elif event_key == "FGB_LIST_HISTORY":
                sessions = await self.store.get_recent_sessions(topic_id)
                card = CardBuilder.build_session_list_card(sessions)
                card_id = await self.feishu.send_text(open_id, card, receive_id_type="open_id")
                if card_id:
                    await self.store.add_pending_confirm(
                        f"list_{card_id[:8]}", topic_id, "N/A", "switch_session", "📜 历史会话列表", msg_id=card_id
                    )
        except Exception as e:
            logger.exception(f"处理菜单事件失败: {e}")
            await self._report_system_error("菜单操作执行失败", e, open_id)

    async def _handle_card_action(self, event_data: dict):
        logger.debug(f"[_handle_card_action] 接收到卡片数据: {json.dumps(event_data, ensure_ascii=False)[:500]}")
        action_value = event_data.get("action", {}).get("value", {})
        decision = action_value.get("decision")
        message_id = event_data.get("context", {}).get("open_message_id")
        
        # 核心修复：兼容多种飞书标识路径
        context = event_data.get("context", {})
        operator = event_data.get("operator", {})
        open_id = context.get("open_id") or \
                  operator.get("open_id") or \
                  operator.get("operator_id", {}).get("open_id")
                  
        logger.debug(f"[_handle_card_action] 提取结果: decision={decision}, message_id={message_id}, open_id={open_id}")
        
        if not message_id: return

        try:
            if decision == "switch_session":
                if not open_id: return
                logger.debug(f"[_handle_card_action] 开始处理 switch_session: {action_value.get('session_id')}")
                if config.reaction_get: 
                    logger.debug(f"[_handle_card_action] 准备异步发送受理表情")
                    asyncio.create_task(self.feishu.add_reaction(message_id, config.reaction_get))
                try:
                    await self._switch_to_session(open_id, action_value.get("session_id"), message_id)
                    if config.reaction_done: asyncio.create_task(self.feishu.add_reaction(message_id, config.reaction_done))
                finally:
                    if config.reaction_get: asyncio.create_task(self.feishu.delete_bot_reaction_by_type(message_id, config.reaction_get))
                return

            confirm_id = action_value.get("confirm_id")
            if not confirm_id: return
            
            if config.reaction_get: asyncio.create_task(self.feishu.add_reaction(message_id, config.reaction_get))

            try:
                pending = await self.store.get_pending_confirm(confirm_id)
                if not pending: return
                
                new_card = None
                if decision == "confirm":
                    if pending["confirm_step"] != 1: return
                    new_card = CardBuilder.build_double_confirm_card(confirm_id, pending["action_type"])
                    await self.store.update_pending_confirm_step(confirm_id, step=2, msg_id=message_id)
                elif decision == "back":
                    if pending["confirm_step"] != 2: return
                    new_card = CardBuilder.build_permission_card(confirm_id, pending["action_type"], pending["message"])
                    await self.store.update_pending_confirm_step(confirm_id, step=1, msg_id=message_id)
                elif decision in ["allow", "deny"]:
                    await self._execute_confirm_decision(pending, decision, message_id)
                    new_card = CardBuilder.build_result_card(pending["action_type"], decision)

                if new_card:
                    await self.feishu.client.im.v1.message.apatch(
                        lark.im.v1.PatchMessageRequest.builder()
                        .message_id(message_id)
                        .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(new_card).build())
                        .build()
                    )
            finally:
                if config.reaction_get: await self.feishu.delete_bot_reaction_by_type(message_id, config.reaction_get)
        except Exception as e:
            logger.exception(f"处理卡片回调失败: {e}")
            await self._report_system_error("卡片交互执行失败", e, open_id)

    async def _switch_to_session(self, open_id: str, session_id: str, card_msg_id: str):
        """执行会话切换并更新卡片"""
        chat_id = await self.store.get_chat_id_by_open_id(open_id)
        topic_id = chat_id if chat_id else open_id
        
        logger.debug(f"[_switch_to_session] 标识推导结果: open_id={open_id} -> chat_id={chat_id} -> topic_id={topic_id}")
        
        topic = await self.store.get_topic(topic_id)
        if not topic:
            logger.error(f"[_switch_to_session] 无法找到话题 {topic_id}，无法切换")
            return
            
        role = topic["role"]
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        
        logger.info(f"[_switch_to_session] 准备从 {acp._active_session_id} 切换至 {session_id}")

        if not await asyncio.to_thread(acp.session_load, session_id):
            logger.warning(f"[_switch_to_session] 本地缓存丢失，启动深度重建: {session_id}")
            await self._reconstruct_session(acp, session_id)
        else:
            # 热加载成功后，执行静默冲刷以消耗可能的历史回显包 (TDD v0.2)
            if config.acp_silent_flush_enabled:
                logger.info(f"[_switch_to_session] 正在对会话 {session_id} 执行静默冲刷...")
                await asyncio.to_thread(acp.send, session_id, config.acp_silent_flush_prompt)
        
        acp._active_session_id = session_id
        await self.store.save_topic(topic_id, chat_id or open_id, role=role, session_id=session_id)
        
        sessions = await self.store.get_recent_sessions(topic_id, limit=50)
        target_title = "未知会话"
        for s in sessions:
            if s["session_id"] == session_id:
                target_title = s.get("title") or "未命名会话"
                break

        pendings = await self.store.get_pending_confirms_by_topic(topic_id)
        for p in pendings:
            if p["action_type"] == "switch_session":
                await self.store.remove_pending_confirm(p["confirm_id"])

        await self.feishu.client.im.v1.message.apatch(
            lark.im.v1.PatchMessageRequest.builder()
            .message_id(card_msg_id)
            .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(CardBuilder.build_switch_success_card(target_title, session_id)).build())
            .build()
        )
        logger.success(f"[_switch_to_session] 会话切换完成: {session_id}")

    async def _reconstruct_session(self, acp, session_id: str):
        """深度重建 Session 状态并确保内存对齐"""
        messages = await self.store.get_messages(session_id)
        await asyncio.to_thread(acp.session_new)
        for msg in messages:
            await asyncio.to_thread(acp.send, acp._active_session_id, msg["content"])
        await asyncio.to_thread(acp.session_save, session_id)
        acp._active_session_id = session_id
        logger.success(f"Session 重建完成并已对齐: {session_id}")

    async def _route_to_role(self, role: str, chat_id: str, message_id: str, text: str, attachments: list, topic: dict, topic_id: str, origin_msg_id: str):
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        session_id = None
        turn_count = (topic.get("turn_count") or 0) if topic else 0
        is_cold_start = False

        if topic and topic.get("session_id"):
            session_id = topic["session_id"]
            logger.debug(f"[_route_to_role] 数据库 SessionID: {session_id}, ACP 内存 SessionID: {acp._active_session_id}")
            if acp._active_session_id != session_id:
                logger.info(f"[_route_to_role] 检测到 SessionID 不对齐，尝试执行 session/load: {session_id}")
                if not await asyncio.to_thread(acp.session_load, session_id):
                    logger.warning(f"[_route_to_role] 会话 {session_id} 磁盘缓存丢失，尝试重建...")
                    await self._reconstruct_session(acp, session_id)
                is_cold_start = True
        else:
            session_id = await asyncio.to_thread(acp.session_new)
            turn_count = 0
            logger.info(f"[_route_to_role] 开启全新会话: {session_id}")
        
        if not session_id:
             session_id = acp._active_session_id
             logger.warning(f"[_route_to_role] session_id 变量丢失，回退至 ACP 内存标识: {session_id}")

        turn_count += 1
        if turn_count == 1:
            title = text[:15] + ("..." if len(text) > 15 else "")
            await self.store.update_session_title(session_id, title)

        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id, turn_count=turn_count)
        if (is_cold_start or turn_count == 1) and config.acp_silent_flush_enabled:
            await asyncio.to_thread(acp.send, session_id, self.dispatcher.get_role_prompt(role))

        await self.store.add_message(session_id, "user", text)
        resp = await asyncio.to_thread(acp.send, session_id, text, attachments)
        await asyncio.to_thread(acp.session_save, session_id)
        await self._handle_acp_response(resp, chat_id, origin_msg_id, session_id, topic_id)
        await self._finalize_reaction(origin_msg_id)

    async def _handle_acp_response(self, resp: dict, chat_id: str, message_id: str, session_id: str, topic_id: str) -> Optional[str]:
        result = resp.get("result", {})
        if result.get("type") == "confirmation_required":
            confirm_id, action, message = result.get("confirmationId"), result.get("action"), result.get("message")
            if config.acp_card_mode_enabled:
                card = CardBuilder.build_permission_card(confirm_id, action, message)
                sent_id = await self.feishu.reply(message_id, card, msg_type="interactive")
            else:
                prompt = f"🔐 [安全拦截] 进程申请执行高危操作：\n\n**{action}**\n\n{message}\n\n👉 **授权方式**：\n请在此消息下回复表情：点赞(YES/OK)同意，点踩(NO)拒绝。"
                sent_id = await self.feishu.reply(message_id, prompt)
            if sent_id: await self.store.add_pending_confirm(confirm_id, topic_id, session_id, action, message, msg_id=sent_id, confirm_step=1)
            return sent_id
        else:
            content = result.get("content", str(result))
            await self.store.add_message(session_id, "assistant", content)
            return await self.feishu.reply(message_id, content)

    async def _auto_expire_pending_confirms(self, topic_id: str):
        pendings = await self.store.get_pending_confirms_by_topic(topic_id)
        for p in pendings:
            msg_id = p.get("msg_id")
            if msg_id:
                if config.acp_card_mode_enabled or p["action_type"] == "switch_session":
                    await self.feishu.client.im.v1.message.apatch(lark.im.v1.PatchMessageRequest.builder().message_id(msg_id).request_body(lark.im.v1.PatchMessageRequestBody.builder().content(CardBuilder.build_expired_card(p["action_type"])).build()).build())
                    if config.reaction_invalid: await self.feishu.add_reaction(msg_id, config.reaction_invalid)
                else:
                    await self.feishu.reply(msg_id, "⌛ 此授权请求已因新消息输入而自动失效。")
                    if config.reaction_invalid: await self.feishu.add_reaction(msg_id, config.reaction_invalid)
            await self.store.remove_pending_confirm(p["confirm_id"])

    async def _execute_confirm_decision(self, pending: dict, decision: str, current_msg_id: str):
        confirm_id = pending["confirm_id"]
        if await self.store.remove_pending_confirm(confirm_id) == 0: return
        topic_id, session_id = pending["topic_id"], pending["session_id"]
        topic = await self.store.get_topic(topic_id)
        role = topic["role"] if topic else config.assistant_role
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        resp = await asyncio.to_thread(acp.confirm, session_id, confirm_id, decision)
        await asyncio.to_thread(acp.session_save, session_id)
        if not config.acp_card_mode_enabled:
            status_text = "✅ 授权已通过，正在继续执行..." if decision == "allow" else "❌ 授权已拒绝。"
            await self.feishu.reply(current_msg_id, status_text)
        await self._handle_acp_response(resp, "", current_msg_id, session_id, topic_id)

    async def _process_attachments(self, message: dict, text: str) -> tuple[str, list]:
        extra_text, attachments = "", []
        message_id = message.get("message_id")
        bundled_images = message.get("bundled_images") or []
        bundled_files = message.get("bundled_files") or []
        if not bundled_images:
            for key in (message.get("image_keys") or []): bundled_images.append({"key": key, "msg_id": message_id})
        if not bundled_files:
            for key in (message.get("file_keys") or []): bundled_files.append({"key": key, "msg_id": message_id})
        base_dir = config.gemini_cwd or os.getcwd()
        abs_attachment_dir = os.path.join(base_dir, config.attachment_dir)
        os.makedirs(abs_attachment_dir, exist_ok=True)
        for i, item in enumerate(bundled_images):
            key, origin_id = item["key"], item["msg_id"]
            save_path = os.path.join(abs_attachment_dir, f"{origin_id}_{i}_{key[:8]}.png")
            if await self.feishu.download_image(key, save_path, message_id=origin_id):
                with open(save_path, "rb") as f: data_base64 = base64.b64encode(f.read()).decode("utf-8")
                attachments.append({"type": "image", "data": data_base64, "mimeType": "image/png"})
        for item in bundled_files:
            key, origin_id = item["key"], item["msg_id"]
            save_path = os.path.join(abs_attachment_dir, f"{origin_id}_{key[:8]}")
            if await self.feishu.download_resource(origin_id, key, save_path, resource_type="file"):
                attachments.append({"type": "resource_link", "name": key[:8], "uri": f"file://{os.path.abspath(save_path)}"})
        urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
        for url in urls:
            if "feishu.cn" not in url: continue
            doc_info = self.feishu.resolver.parse(url)
            if doc_info:
                token, obj_type = doc_info["token"], doc_info["type"]
                export_ext = (config.feishu_export_type or "").strip().lower()
                content = await self.feishu.aexport_document(token, obj_type, export_ext) if export_ext else None
                if content:
                    filename = f"exported_{token[:8]}.{export_ext}"
                    save_path = os.path.join(abs_attachment_dir, f"{message_id}_{filename}")
                    with open(save_path, "wb") as f: f.write(content)
                    attachments.append({"type": "resource_link", "name": filename, "uri": f"file://{os.path.abspath(save_path)}" })
                else:
                    actual_token, actual_type = token, obj_type
                    if obj_type == "wiki": 
                        try: actual_token, actual_type = await self.feishu.resolver.a_resolve_wiki_node(token)
                        except: pass
                    if actual_type == "docx":
                        doc_md = await self.feishu.aget_docx_markdown(actual_token)
                        if doc_md: extra_text += f"\n\n--- 附件文档内容 [{actual_token}] ---\n{doc_md}\n"
        return extra_text, attachments

    async def _bind_topic_and_route(self, chat_id: str, topic_id: str, message_id: str, text: str, attachments: list):
        role = "Developer"
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        session_id = await asyncio.to_thread(acp.session_new)
        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id)
        topic = await self.store.get_topic(topic_id)
        await self._route_to_role(role, chat_id, message_id, text, attachments, topic, topic_id, message_id)

    async def _finalize_reaction(self, message_id: str):
        if config.reaction_done: await self.feishu.add_reaction(message_id, config.reaction_done)
        if config.reaction_get: await self.feishu.delete_bot_reaction_by_type(message_id, config.reaction_get)
