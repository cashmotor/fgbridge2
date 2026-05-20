import asyncio
import json
from loguru import logger
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1, P2ImMessageReactionCreatedV1
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
from src.config import config

class FeishuWebSocketListener:
    """
    飞书 WebSocket 长连接监听器
    使用 EventDispatcherHandler 注册事件，确保类型安全
    """
    def __init__(self, event_queue: asyncio.Queue):
        self.event_queue = event_queue
        
        # 1. 创建事件分发器
        # WebSocket 模式下无需 verification_token 和 encrypt_key
        self.event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_received)
            .register_p2_card_action_trigger(self._on_card_action_triggered)
            .register_p2_im_message_reaction_created_v1(self._on_reaction_received)
            .build()
        )

        # 2. 创建 WebSocket 客户端
        # 直接通过构造函数初始化
        self.cli = lark.ws.Client(
            app_id=config.feishu_app_id,
            app_secret=config.feishu_app_secret,
            log_level=lark.LogLevel.INFO,
            event_handler=self.event_handler
        )

    def _on_message_received(self, data: P2ImMessageReceiveV1) -> None:
        """接收到消息事件"""
        logger.info(f"收到消息事件: {data.event.message.message_id}")
        payload = {
            "header": {
                "event_type": "im.message.receive_v1",
                "event_id": data.header.event_id
            },
            "event": json.loads(lark.JSON.marshal(data.event))
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.event_queue.put(payload), loop)
        except Exception as e:
            logger.error(f"投递消息事件失败: {e}")

    def _on_card_action_triggered(self, data: P2CardActionTrigger) -> None:
        """接收到卡片交互事件"""
        logger.info(f"收到卡片回调事件: {data.header.event_id}")
        payload = {
            "header": {
                "event_type": "card.action.trigger",
                "event_id": data.header.event_id
            },
            "event": json.loads(lark.JSON.marshal(data.event))
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.event_queue.put(payload), loop)
        except Exception as e:
            logger.error(f"投递卡片事件失败: {e}")

    def _on_reaction_received(self, data: P2ImMessageReactionCreatedV1) -> None:
        """接收到表情回复事件 (Created)"""
        raw_event_json = lark.JSON.marshal(data.event)
        logger.debug(f"RAW REACTION EVENT: {raw_event_json}")
        
        emoji_type = data.event.reaction_type.emoji_type
        message_id = data.event.message_id
        
        logger.info(f"捕获到表情回复: {emoji_type} (Message: {message_id})")
        
        # 修正：只将 event 部分放入 payload["event"]，保持与 dispatch 逻辑一致
        payload = {
            "header": {
                "event_type": "im.message.reaction.receive_v1",
                "event_id": data.header.event_id
            },
            "event": json.loads(raw_event_json)
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.event_queue.put(payload), loop)
            else:
                logger.warning("事件循环未在运行，无法投递表情事件")
        except Exception as e:
            logger.error(f"投递表情事件失败: {e}")

    def start(self):
        """启动监听器 (阻塞)"""
        logger.info("正在建立飞书 WebSocket 长连接...")
        self.cli.start()
