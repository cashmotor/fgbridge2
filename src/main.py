import asyncio
import threading
import sys
from loguru import logger

from src.config import config
from src.storage.state_store import StateStore
from src.engine.dispatcher import ACPDispatcher
from src.provider.feishu_im import FeishuIMProvider
from src.engine.router import Router
from src.engine.bundler import MessageBundler
from src.listener.websocket import FeishuWebSocketListener
from src.utils.card_builder import CardBuilder

def setup_logging():
    """配置日志持久化"""
    from pathlib import Path
    log_path = Path(config.log_dir)
    
    # 1. 全量日志 (包括 ERROR)
    logger.add(
        log_path / "fgb.log",
        rotation=config.log_rotation,
        level="DEBUG",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 2. 独立错误日志 (仅记录 ERROR 及以上级别)
    logger.add(
        log_path / "error.log",
        rotation=config.log_rotation,
        level="ERROR",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

async def worker(queue: asyncio.Queue, bundler: MessageBundler, router: Router):
    """异步任务消费者"""
    logger.info("事件处理 Worker 已启动")
    while True:
        event = await queue.get()
        try:
            event_type = event.get('header', {}).get('event_type')
            logger.debug(f"正在处理事件: {event_type}")
            
            # 只有用户发的消息才进 Bundler 等待打包，其余事件（如卡片点击、菜单）直接放行
            if event_type == "im.message.receive_v1":
                await bundler.add(event)
            else:
                await router.dispatch(event)
        except Exception as e:
            logger.error(f"处理事件时发生异常: {e}")
        finally:
            queue.task_done()

async def cleanup_task(dispatcher: ACPDispatcher):
    """周期性清理过期进程"""
    while True:
        await asyncio.sleep(60)
        dispatcher.cleanup()

async def main():
    # 0. 初始化配置与日志
    setup_logging()
    
    # 初始化存储
    store = StateStore()
    await store.init_db()
    
    dispatcher = ACPDispatcher()
    feishu = FeishuIMProvider()
    router = Router(store, dispatcher, feishu)
    bundler = MessageBundler(router.dispatch)

    # 1. 初始化异步队列
    event_queue = asyncio.Queue()

    # 2. 启动异步任务
    worker_task = asyncio.create_task(worker(event_queue, bundler, router))
    ttl_task = asyncio.create_task(cleanup_task(dispatcher))

    # 3. 在独立线程中启动飞书 WebSocket 监听器
    listener = FeishuWebSocketListener(event_queue)
    listener_thread = threading.Thread(target=listener.start, daemon=True)
    listener_thread.start()

    # 3.1 预热常驻助理 (Eager Initialization)
    logger.info(f"正在预热常驻助理角色: {config.assistant_role}...")
    acp = await asyncio.to_thread(dispatcher.get_acp, config.assistant_role)

    logger.success("FGBridge 2.0 服务已全面启动")

    # 4. Say Hi (启动通知卡片)
    if config.feishu_user_ids:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for user_id in config.feishu_user_ids:
            logger.info(f"发送启动通知至: {user_id}")
            # 尝试获取该用户的当前 session
            chat_id = await store.get_chat_id_by_open_id(user_id)
            topic_id = chat_id if chat_id else user_id
            topic = await store.get_topic(topic_id)
            sess_id = topic.get("session_id") if topic else None
            
            card_content = CardBuilder.build_system_status_card("ready", now, config.assistant_role, session_id=sess_id)
            await feishu.send_text(user_id, card_content, receive_id_type="open_id")

    try:
        await asyncio.gather(worker_task, ttl_task)
    except asyncio.CancelledError:
        logger.info("服务正在关闭...")
    finally:
        # 5. Say Hi (停止通知卡片)
        if config.feishu_user_ids:
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            card_content = CardBuilder.build_system_status_card("stopped", now)
            for user_id in config.feishu_user_ids:
                logger.info(f"正在发送停止通知至: {user_id}")
                try:
                    # 使用 shield 保护发送动作，防止在取消过程中被打断
                    await asyncio.shield(feishu.send_text(user_id, card_content, receive_id_type="open_id"))
                except Exception as e:
                    logger.error(f"发送停止通知失败 ({user_id}): {e}")

        logger.info("正在关闭所有 ACP 子进程...")

        dispatcher.stop_all()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户主动停止服务")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"启动失败: {e}")
        sys.exit(1)
