import asyncio
import json
from src.engine.bundler import MessageBundler
from src.config import config

def test_message_bundling_text():
    """测试多条纯文本消息打包"""
    received_events = []
    
    async def run():
        async def mock_dispatch(event):
            received_events.append(event)
            
        bundler = MessageBundler(mock_dispatch)
        config.bundling_wait_time = 0.2
        config.bundling_enabled = True

        # 模拟发送 3 条消息
        for i in range(3):
            event = {
                "header": {"event_type": "im.message.receive_v1", "event_id": f"id_{i}"},
                "event": {
                    "message": {
                        "chat_id": "chat_1",
                        "message_id": f"msg_{i}",
                        "message_type": "text",
                        "content": json.dumps({"text": f"hello {i}"})
                    }
                }
            }
            await bundler.add(event)
            await asyncio.sleep(0.05)

        # 等待打包触发
        await asyncio.sleep(0.3)
        
        assert len(received_events) == 1
        synthetic_event = received_events[0]
        content = json.loads(synthetic_event["event"]["message"]["content"])
        assert content["text"] == "hello 0\nhello 1\nhello 2"
        assert synthetic_event["event"]["message"]["message_id"] == "msg_2"

    asyncio.run(run())

def test_message_bundling_max_messages():
    """测试达到最大消息数限制立即触发"""
    received_events = []
    
    async def run():
        async def mock_dispatch(event):
            received_events.append(event)
            
        bundler = MessageBundler(mock_dispatch)
        config.bundling_wait_time = 5.0
        config.bundling_max_messages = 3
        config.bundling_enabled = True

        # 发送 3 条消息
        for i in range(3):
            event = {
                "header": {"event_type": "im.message.receive_v1", "event_id": f"id_{i}"},
                "event": {
                    "message": {
                        "chat_id": "chat_1",
                        "message_id": f"msg_{i}",
                        "message_type": "text",
                        "content": json.dumps({"text": f"msg {i}"})
                    }
                }
            }
            await bundler.add(event)

        # 稍微等待一下协程调度
        await asyncio.sleep(0.1)
        
        assert len(received_events) == 1
        content = json.loads(received_events[0]["event"]["message"]["content"])
        assert content["text"] == "msg 0\nmsg 1\nmsg 2"

    asyncio.run(run())

def test_message_bundling_attachments():
    """测试附件 Key 合并"""
    received_events = []
    
    async def run():
        async def mock_dispatch(event):
            received_events.append(event)
            
        bundler = MessageBundler(mock_dispatch)
        config.bundling_wait_time = 0.1
        
        events = [
            {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {
                        "chat_id": "chat_1",
                        "message_id": "m1",
                        "message_type": "image",
                        "content": json.dumps({"image_key": "img_1"})
                    }
                }
            },
            {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {
                        "chat_id": "chat_1",
                        "message_id": "m2",
                        "message_type": "text",
                        "content": json.dumps({"text": "and this file"}),
                        "file_keys": ["file_1"]
                    }
                }
            }
        ]

        for e in events:
            await bundler.add(e)
        
        await asyncio.sleep(0.2)
        
        assert len(received_events) == 1
        msg = received_events[0]["event"]["message"]
        
        # Bundler 现在的逻辑是将附件放入 bundled_images 和 bundled_files
        bundled_images = [item["key"] for item in msg.get("bundled_images", [])]
        bundled_files = [item["key"] for item in msg.get("bundled_files", [])]
        
        assert "img_1" in bundled_images
        assert "file_1" in bundled_files

    asyncio.run(run())
