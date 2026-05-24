import asyncio
import json
import time
from typing import Dict, List, Any, Callable, Optional
from loguru import logger
from src.config import config

class MessageBundler:
    """
    消息打包器：支持多条连续输入的用户消息打包处理。
    如果时间间隔内用户又输入新的消息，则重置计时器。
    达到上限或超时后，将消息拼接成一个合成事件分发给回调函数。
    """
    def __init__(self, dispatch_callback: Callable):
        self.dispatch_callback = dispatch_callback
        self.bundles: Dict[str, Dict[str, Any]] = {}  # bundle_id -> {messages, timer_task, lock}
        self.lock = asyncio.Lock()

    def _get_bundle_id(self, event: dict) -> str:
        """根据消息上下文计算打包 ID (类似于 Router 的 topic_id)"""
        data = event.get("event", {})
        message = data.get("message", {})
        chat_id = message.get("chat_id", "unknown")
        chat_type = message.get("chat_type", "")
        thread_id = message.get("thread_id") or ""
        root_id = message.get("root_id") or ""

        # 逻辑与 Router 保持一致，确保同一个会话的消息被打到一个包里
        if chat_type == "p2p":
            return thread_id if thread_id else chat_id
        else:
            if thread_id:
                return thread_id
            elif root_id:
                return root_id
            else:
                return chat_id

    def _extract_content(self, event: dict) -> Dict[str, Any]:
        """从单个事件中提取文本和附件 Key，并关联 message_id"""
        data = event.get("event", {})
        message = data.get("message", {})
        message_id = message.get("message_id")
        msg_type = message.get("message_type") or message.get("msg_type")
        content_str = message.get("content", "{}")
        
        try:
            content_json = json.loads(content_str)
        except:
            content_json = {}

        text = ""
        image_attachments = []
        file_attachments = []
        
        if msg_type == "text":
            text = content_json.get("text", "")
        elif msg_type == "post":
            for block_list in content_json.get("content", []):
                for element in block_list:
                    if element.get("tag") == "text":
                        text += element.get("text", "")
                    elif element.get("tag") == "img":
                        image_attachments.append({"key": element.get("image_key"), "msg_id": message_id})
        elif msg_type == "image":
            if "image_key" in content_json:
                image_attachments.append({"key": content_json["image_key"], "msg_id": message_id})

        # 处理 message 对象中可能已有的 file_keys
        for fkey in (message.get("file_keys") or []):
            file_attachments.append({"key": fkey, "msg_id": message_id})

        return {
            "text": text.strip(),
            "image_attachments": image_attachments,
            "file_attachments": file_attachments
        }

    async def add(self, event: dict):
        """添加一个事件到打包器"""
        event_type = event.get("header", {}).get("event_type")
        
        # 仅打包消息接收事件（im.message.receive_v1），卡片交互和表情授权需立即响应
        if event_type != "im.message.receive_v1" or not config.bundling_enabled:
            await self.dispatch_callback(event)
            return

        bundle_id = self._get_bundle_id(event)
        
        async with self.lock:
            if bundle_id not in self.bundles:
                self.bundles[bundle_id] = {
                    "events": [],
                    "timer_task": None
                }
            
            bundle = self.bundles[bundle_id]
            bundle["events"].append(event)
            
            # 如果已有计时器，取消它（实现 Debounce 效果）
            if bundle["timer_task"]:
                bundle["timer_task"].cancel()
            
            # 检查是否达到上限
            if len(bundle["events"]) >= config.bundling_max_messages:
                logger.info(f"[Bundler] Bundle {bundle_id} 达到上限 ({config.bundling_max_messages})，立即触发处理")
                # 这里不直接调用 flush，而是通过创建一个立即执行的任务，避免在 lock 内部等待
                asyncio.create_task(self.flush(bundle_id))
            else:
                # 启动新计时器
                bundle["timer_task"] = asyncio.create_task(self._wait_and_flush(bundle_id))

    async def _wait_and_flush(self, bundle_id: str):
        """等待指定时间后触发冲刷"""
        try:
            await asyncio.sleep(config.bundling_wait_time)
            await self.flush(bundle_id)
        except asyncio.CancelledError:
            # 被取消是正常的（收到了新消息）
            pass

    async def flush(self, bundle_id: str):
        """冲刷并分发打包的消息"""
        async with self.lock:
            bundle = self.bundles.pop(bundle_id, None)
            if not bundle or not bundle["events"]:
                return

            events = bundle["events"]
            if bundle["timer_task"]:
                bundle["timer_task"].cancel()

        # 提取并拼接内容
        combined_texts = []
        all_images = [] # List of {"key", "msg_id"}
        all_files = []  # List of {"key", "msg_id"}
        
        for e in events:
            extracted = self._extract_content(e)
            if extracted["text"]:
                combined_texts.append(extracted["text"])
            all_images.extend(extracted.get("image_attachments", []))
            all_files.extend(extracted.get("file_attachments", []))

        # 以最后一条消息作为基准构造合成事件
        last_event = events[-1]
        
        # 构造合成消息：类型设为 text，内容设为拼接后的文本
        synthetic_text = "\n".join(combined_texts)
        
        # 深度拷贝并修改
        synthetic_event = json.loads(json.dumps(last_event))
        synthetic_message = synthetic_event["event"]["message"]
        synthetic_message["message_type"] = "text"
        synthetic_message["content"] = json.dumps({"text": synthetic_text})
        
        # 将带上下文的附件列表存入扩展字段
        synthetic_message["bundled_images"] = all_images
        synthetic_message["bundled_files"] = all_files
        
        logger.info(f"[Bundler] Bundle {bundle_id} 已冲刷: 拼接了 {len(events)} 条消息, 图片={len(all_images)}, 文件={len(all_files)}")
        
        # 异步分发，不阻塞 Bundler 继续处理新消息
        async def safe_dispatch():
            try:
                await self.dispatch_callback(synthetic_event)
            except Exception as e:
                logger.error(f"[Bundler] 分发合成事件失败: {e}")
        
        asyncio.create_task(safe_dispatch())
