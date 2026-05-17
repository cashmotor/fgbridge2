import json
from typing import Dict, Any

class CardBuilder:
    """
    负责构建飞书互动卡片 (JSON)
    """
    @staticmethod
    def build_permission_card(confirm_id: str, action: str, message: str) -> str:
        """构建高危操作确认卡片"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red",
                "title": {"content": "⚠️ 高危操作安全拦截", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": f"**操作类型**: {action}", "tag": "lark_md"}
                },
                {
                    "tag": "div",
                    "text": {"content": f"**详情**: {message}", "tag": "lark_md"}
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"content": "允许执行", "tag": "plain_text"},
                            "type": "primary",
                            "value": {"decision": "allow", "confirm_id": confirm_id}
                        },
                        {
                            "tag": "button",
                            "text": {"content": "拒绝并取消", "tag": "plain_text"},
                            "type": "danger",
                            "value": {"decision": "deny", "confirm_id": confirm_id}
                        }
                    ]
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_result_card(action: str, decision: str) -> str:
        """更新处理后的卡片状态"""
        template = "green" if decision == "allow" else "grey"
        status_text = "✅ 已授权执行" if decision == "allow" else "❌ 已拒绝操作"
        
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"content": status_text, "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": f"**操作**: {action}\n该请求已被处理。", "tag": "lark_md"}
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_system_status_card(status: str, time_str: str, role: str = "") -> str:
        """构建系统启停通知卡片"""
        is_ready = status.lower() == "ready"
        title = "🚀 FGBridge 2.0 已就绪" if is_ready else "🛑 FGBridge 2.0 已停止"
        template = "blue" if is_ready else "grey"
        
        content = f"**时间**: {time_str}"
        if is_ready and role:
            content += f"\n**当前助理角色**: {role}"
            content += f"\n**模式**: WebSocket (长连接)"
            
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"content": title, "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": content, "tag": "lark_md"}
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

