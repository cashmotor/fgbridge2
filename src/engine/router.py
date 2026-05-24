import json
import base64
import mimetypes
import os
import re
import asyncio
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
        # 兼容 message_type 或 msg_type
        msg_type = message.get("message_type") or message.get("msg_type")
        
        logger.debug(f"[_handle_message] 开始处理消息: ID={message_id}, 类型={msg_type}")
        
        # 0. 立即回复 GET 表情，告知用户已收到消息 (非阻塞)
        if config.reaction_get:
            logger.debug(f"[_handle_message] 异步提交 GET 表情: {message_id}")
            asyncio.create_task(self.feishu.add_reaction(message_id, config.reaction_get))

        thread_id = message.get("thread_id") or ""
        root_id = message.get("root_id") or ""
        
        logger.debug(f"[_handle_message] 提取内容字段...")
        content_str = message.get("content", "{}")
        try:
            content_json = json.loads(content_str)
        except Exception as e:
            logger.error(f"[_handle_message] 解析消息内容 JSON 失败: {e}, 内容: {content_str}")
            content_json = {}

        text = ""
        extracted_image_keys = []
        if msg_type == "text":
            text = content_json.get("text", "")
        elif msg_type == "post":
            # 解析富文本消息
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
        
        # 将解析到的 image_keys 存入 message 供 _process_attachments 使用
        if extracted_image_keys:
            existing_keys = message.get("image_keys") or []
            message["image_keys"] = list(set(existing_keys + extracted_image_keys))
        
        logger.debug(f"[_handle_message] 准备提取附件: text_len={len(text)}")
        extra_text, attachments = await self._process_attachments(message, text)
        
        if extra_text:
            logger.debug(f"[_handle_message] 提取到额外文本: {len(extra_text)} chars")
            text += extra_text

        logger.debug(f"[_handle_message] 最终处理内容: text_len={len(text)}, attachments_count={len(attachments)}")

        if not text and not attachments:
            logger.warning(f"[_handle_message] 消息内容和附件均为空，跳过处理 (ID={message_id})")
            # 标记为跳过/无效
            if config.reaction_invalid:
                await self.feishu.add_reaction(message_id, config.reaction_invalid)
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

        logger.debug(f"[_handle_message] 路由决策: topic_id={topic_id}, role={target_role}, is_subtask={is_subtask}")

        # 1. 核心增强：检测到新消息，自动失效挂起的授权
        await self._auto_expire_pending_confirms(topic_id)

        topic = await self.store.get_topic(topic_id)
        logger.debug(f"[_handle_message] 获取 Topic 状态: {'found' if topic else 'not found'}")
        
        if is_subtask:
            if not topic:
                logger.debug(f"[_handle_message] 分发至 _bind_topic_and_route")
                await self._bind_topic_and_route(chat_id, topic_id, message_id, text, attachments)
            else:
                logger.debug(f"[_handle_message] 分发至 _route_to_role (subtask)")
                await self._route_to_role(topic["role"], chat_id, message_id, text, attachments, topic, topic_id, message_id)
        else:
            logger.debug(f"[_handle_message] 分发至 _route_to_role (main)")
            await self._route_to_role(target_role, chat_id, message_id, text, attachments, topic, topic_id, message_id)

    async def _handle_reaction(self, event_data: dict):
        """处理表情授权逻辑"""
        # 1. 交互分割：如果已开启卡片模式，则忽略表情授权，确保用户仅通过卡片交互
        if config.acp_card_mode_enabled:
            return

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
        """执行最终授权决策并反馈 (异步化)"""
        confirm_id = pending["confirm_id"]
        
        # 幂等性保护：尝试从数据库移除，如果移除失败说明已被其他任务处理
        if await self.store.remove_pending_confirm(confirm_id) == 0:
            logger.warning(f"授权请求 {confirm_id} 已处理或正在处理中，跳过重复执行")
            return

        topic_id = pending["topic_id"]
        session_id = pending["session_id"]
        
        topic = await self.store.get_topic(topic_id)
        role = topic["role"] if topic else config.assistant_role
        
        # 异步获取 ACP
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        logger.info(f"正在执行授权决策: {confirm_id} -> {decision}")
        
        # 异步执行确认并保存
        resp = await asyncio.to_thread(acp.confirm, session_id, confirm_id, decision)
        await asyncio.to_thread(acp.session_save, session_id)
        
        # 仅在非卡片模式下回复状态消息，卡片模式通过 Patch 卡片展示状态
        if not config.acp_card_mode_enabled:
            status_text = "✅ 授权已通过，正在继续执行..." if decision == "allow" else "❌ 授权已拒绝。"
            await self.feishu.reply(current_msg_id, status_text)
        
        await self._handle_acp_response(resp, "", current_msg_id, session_id, topic_id)

    async def _auto_expire_pending_confirms(self, topic_id: str):
        """自动失效指定话题下的所有挂起授权"""
        pendings = await self.store.get_pending_confirms_by_topic(topic_id)
        for p in pendings:
            logger.info(f"检测到新消息，自动失效旧授权: {p['confirm_id']}")
            msg_id = p.get("msg_id")
            if msg_id:
                if config.acp_card_mode_enabled:
                    # 卡片模式：更新原卡片为失效状态
                    expired_card = CardBuilder.build_expired_card(p["action_type"])
                    await self.feishu.client.im.v1.message.apatch(
                        lark.im.v1.PatchMessageRequest.builder()
                        .message_id(msg_id)
                        .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(expired_card).build())
                        .build()
                    )
                else:
                    # 表情模式：回复失效消息并加表情
                    await self.feishu.reply(msg_id, "⌛ 此授权请求已因新消息输入而自动失效。")
                    if config.reaction_invalid:
                        await self.feishu.add_reaction(msg_id, config.reaction_invalid)
            
            await self.store.remove_pending_confirm(p["confirm_id"])

    async def _process_attachments(self, message: dict, text: str) -> tuple[str, list]:
        extra_text = ""
        attachments = []
        message_id = message.get("message_id")
        
        # 1. 优先获取打包后的带上下文附件
        bundled_images = message.get("bundled_images") or []
        bundled_files = message.get("bundled_files") or []
        
        # 2. 如果没有打包数据，则尝试从普通消息结构中提取 (兼容非打包模式)
        if not bundled_images:
            image_keys = message.get("image_keys") or []
            for key in image_keys:
                bundled_images.append({"key": key, "msg_id": message_id})
        
        if not bundled_files:
            file_keys = message.get("file_keys") or []
            for key in file_keys:
                bundled_files.append({"key": key, "msg_id": message_id})

        logger.debug(f"[_process_attachments] 准备处理附件: images={len(bundled_images)}, files={len(bundled_files)}")
        
        # 确保附件目录在 acp 进程工作目录下
        base_dir = config.gemini_cwd if config.gemini_cwd else os.getcwd()
        abs_attachment_dir = os.path.join(base_dir, config.attachment_dir)
        os.makedirs(abs_attachment_dir, exist_ok=True)

        # 3. 处理图片
        for i, item in enumerate(bundled_images):
            key = item["key"]
            origin_msg_id = item["msg_id"]
            clean_key = key.strip().replace("\"", "").replace("'", "")
            # 文件名加入 origin_msg_id 以防冲突
            save_path = os.path.join(abs_attachment_dir, f"{origin_msg_id}_{i}_{clean_key[:8]}.png")
            
            logger.debug(f"[_process_attachments] 正在下载图片: {clean_key} (来自消息 {origin_msg_id})")
            if await self.feishu.download_image(clean_key, save_path, message_id=origin_msg_id):
                with open(save_path, "rb") as f:
                    data_base64 = base64.b64encode(f.read()).decode("utf-8")
                attachments.append({"type": "image", "data": data_base64, "mimeType": "image/png"})
                logger.success(f"[_process_attachments] 图片下载成功: {clean_key}")
            else:
                logger.error(f"[_process_attachments] 图片下载失败: {clean_key}")

        # 4. 处理文件
        for item in bundled_files:
            key = item["key"]
            origin_msg_id = item["msg_id"]
            save_path = os.path.join(abs_attachment_dir, f"{origin_msg_id}_{key[:8]}")
            
            logger.debug(f"[_process_attachments] 正在下载文件: {key} (来自消息 {origin_msg_id})")
            if await self.feishu.download_resource(origin_msg_id, key, save_path, resource_type="file"):
                attachments.append({"type": "resource_link", "name": key[:8], "uri": f"file://{os.path.abspath(save_path)}"})
                logger.success(f"[_process_attachments] 文件下载成功: {key}")
            else:
                logger.error(f"[_process_attachments] 文件下载失败: {key}")

        # 5. 解析文本中的飞书链接
        urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
        for url in urls:
            if "feishu.cn" not in url:
                continue
            
            doc_info = self.feishu.resolver.parse(url)
            if doc_info:
                token = doc_info["token"]
                obj_type = doc_info["type"]
                logger.info(f"检测到飞书文档链接: {token} (type: {obj_type})")
                
                export_ext = (config.feishu_export_type or "").strip().lower()
                content = None
                
                # 尝试导出
                if export_ext:
                    logger.info(f"正在尝试导出文档为 {export_ext}...")
                    content = await self.feishu.aexport_document(token, obj_type, export_ext)
                    if content:
                        filename = f"exported_{token[:8]}.{export_ext}"
                        save_path = os.path.join(abs_attachment_dir, f"{message_id}_{filename}")
                        
                        with open(save_path, "wb") as f:
                            f.write(content)
                        
                        attachments.append({
                            "type": "resource_link",
                            "name": filename,
                            "uri": f"file://{os.path.abspath(save_path)}"
                        })
                        logger.success(f"飞书文档导出成功: {filename}")
                
                # 如果未指定导出格式或导出失败，尝试提取 Markdown (仅限 docx)
                if not content:
                    actual_token, actual_type = token, obj_type
                    if obj_type == "wiki":
                        try:
                            actual_token, actual_type = await self.feishu.resolver.a_resolve_wiki_node(token)
                        except:
                            actual_type = "unknown"

                    if actual_type == "docx":
                        logger.info("提取 Docx Markdown 文本...")
                        doc_md = await self.feishu.aget_docx_markdown(actual_token)
                        if doc_md:
                            extra_text += f"\n\n--- 附件文档内容 [{actual_token}] ---\n{doc_md}\n"
        
        return extra_text, attachments

    async def _bind_topic_and_route(self, chat_id: str, topic_id: str, message_id: str, text: str, attachments: list):
        role = "Developer" 
        # 异步唤醒
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        session_id = await asyncio.to_thread(acp.session_new)
        
        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id)
        topic = await self.store.get_topic(topic_id)
        await self._route_to_role(role, chat_id, message_id, text, attachments, topic, topic_id, message_id)

    async def _route_to_role(self, role: str, chat_id: str, message_id: str, text: str, attachments: list, topic: dict, topic_id: str, origin_msg_id: str):
        # 异步获取或唤醒 ACP
        acp = await asyncio.to_thread(self.dispatcher.get_acp, role)
        
        session_id = None
        turn_count = (topic.get("turn_count") or 0) if topic else 0
        is_cold_start = False

        if topic and topic.get("session_id"):
            session_id = topic["session_id"]
            if acp._active_session_id != session_id:
                # 异步加载 Session
                if not await asyncio.to_thread(acp.session_load, session_id):
                    session_id = await asyncio.to_thread(acp.session_new)
                    turn_count = 0
                else:
                    is_cold_start = True
        else:
            session_id = await asyncio.to_thread(acp.session_new)
            turn_count = 0
        
        turn_count += 1
        await self.store.save_topic(topic_id, chat_id, role=role, session_id=session_id, turn_count=turn_count)
        
        needs_role_init = is_cold_start or (turn_count == 1)
        if needs_role_init and config.acp_silent_flush_enabled:
            role_prompt = self.dispatcher.get_role_prompt(role)
            try:
                # 异步注入角色
                await asyncio.to_thread(acp.send, session_id, role_prompt)
            except Exception as e:
                logger.error(f"角色注入执行异常: {e}")

        # 异步发送 Prompt 核心调用
        logger.debug(f"[_route_to_role] 正在发送 Prompt 至 ACP...")
        resp = await asyncio.to_thread(acp.send, session_id, text, attachments)
        
        # 异步保存状态
        await asyncio.to_thread(acp.session_save, session_id)
        
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
                card_content = CardBuilder.build_permission_card(confirm_id, action, message)
                sent_msg_id = await self.feishu.reply(message_id, card_content, msg_type="interactive")
                if sent_msg_id:
                    await self.store.add_pending_confirm(confirm_id, topic_id, session_id, action, message, msg_id=sent_msg_id, confirm_step=1)
                return sent_msg_id
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
        
        # 飞书卡片回调上下文中的消息 ID 字段为 open_message_id
        message_id = event_data.get("context", {}).get("open_message_id")
        if not message_id:
            logger.error(f"卡片回调事件中缺少 open_message_id: {event_data}")
            return

        # 1. 立即反馈：添加 GET 表情告知受理 (非阻塞)
        if config.reaction_get:
            asyncio.create_task(self.feishu.add_reaction(message_id, config.reaction_get))

        try:
            pending = await self.store.get_pending_confirm(confirm_id)
            if not pending: 
                logger.debug(f"卡片操作 {confirm_id} 已失效或不存在")
                return
            
            # 2. 逻辑分发与幂等保护
            new_card = None
            if decision == "confirm":
                if pending["confirm_step"] != 1: return # 幂等保护
                new_card = CardBuilder.build_double_confirm_card(confirm_id, pending["action_type"])
                await self.store.update_pending_confirm_step(confirm_id, step=2, msg_id=message_id)
            
            elif decision == "back":
                if pending["confirm_step"] != 2: return # 幂等保护
                new_card = CardBuilder.build_permission_card(confirm_id, pending["action_type"], pending["message"])
                await self.store.update_pending_confirm_step(confirm_id, step=1, msg_id=message_id)
                
            elif decision in ["allow", "deny"]:
                # 最终决策由 _execute_confirm_decision 内部进行 remove 原子化保护
                await self._execute_confirm_decision(pending, decision, message_id)
                new_card = CardBuilder.build_result_card(pending["action_type"], decision)
            else:
                logger.warning(f"未知卡片决策: {decision}")
                return

            # 3. 更新原卡片内容 (Patch)
            if new_card:
                await self.feishu.client.im.v1.message.apatch(
                    lark.im.v1.PatchMessageRequest.builder()
                    .message_id(message_id)
                    .request_body(lark.im.v1.PatchMessageRequestBody.builder().content(new_card).build())
                    .build()
                )
        finally:
            # 4. 无论成功失败，清理受理表情
            if config.reaction_get:
                await self.feishu.delete_bot_reaction_by_type(message_id, config.reaction_get)
