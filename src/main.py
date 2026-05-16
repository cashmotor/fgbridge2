import asyncio
import threading
import sys
from loguru import logger

from src.config import config
from src.storage.state_store import StateStore
from src.engine.dispatcher import ACPDispatcher
from src.provider.feishu_im import FeishuIMProvider
from src.engine.router import Router
from src.listener.websocket import FeishuWebSocketListener

def setup_logging():
    """配置日志持久化"""
    from pathlib import Path
    log_path = Path(config.log_dir)
    
    # 移除默认的控制台输出（如果需要自定义格式，否则可以保留）
    # logger.remove() 
    # logger.add(sys.stderr, level="INFO")

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

async def worker(queue: asyncio.Queue, router: Router):
    """异步任务消费者"""
    logger.info("事件处理 Worker 已启动")
    while True:
        event = await queue.get()
        try:
            event_type = event.get('header', {}).get('event_type')
            logger.debug(f"正在处理事件: {event_type}")
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

    # 1. 初始化异步队列
    event_queue = asyncio.Queue()

    # 2. 启动异步任务
    # 将当前事件循环传递给监听器（以便在多线程中进行异步投递）
    loop = asyncio.get_running_loop()
    
    worker_task = asyncio.create_task(worker(event_queue, router))
    ttl_task = asyncio.create_task(cleanup_task(dispatcher))

    # 3. 在独立线程中启动飞书 WebSocket 监听器
    listener = FeishuWebSocketListener(event_queue)
    # 修改 listener 内部逻辑以适应多线程环境已在 websocket.py 完成
    listener_thread = threading.Thread(target=listener.start, daemon=True)
    listener_thread.start()

    logger.success("FGBridge 2.0 服务已全面启动")
    
    # 4. Say Hi (启动通知)
    if config.feishu_user_id:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await feishu.send_text(
            config.feishu_user_id, 
            f"🚀 FGBridge 2.0 已就绪\n启动时间: {now}\n当前助理角色: {config.assistant_role}",
            receive_id_type="open_id"
        )

    try:
        await asyncio.gather(worker_task, ttl_task)
    except asyncio.CancelledError:
        logger.info("服务正在关闭...")
    finally:
        # 5. Say Hi (停止通知)
        if config.feishu_user_id:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info("正在发送停止通知...")
            try:
                # 使用 shield 保护发送动作，防止在取消过程中被打断
                await asyncio.shield(feishu.send_text(
                    config.feishu_user_id, 
                    f"🛑 FGBridge 2.0 已停止服务\n停止时间: {now}",
                    receive_id_type="open_id"
                ))
            except Exception as e:
                logger.error(f"发送停止通知失败: {e}")
        
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
