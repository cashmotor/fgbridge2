import json
from typing import Dict, Any

class CardBuilder:
    """
    负责构建飞书互动卡片 (JSON)
    """
    @staticmethod
    def build_permission_card(confirm_id: str, action: str, message: str) -> str:
        """构建高危操作确认卡片 (第一步)"""
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
                            "text": {"content": "申请执行", "tag": "plain_text"},
                            "type": "primary",
                            "value": {"decision": "confirm", "confirm_id": confirm_id}
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
    def build_double_confirm_card(confirm_id: str, action: str) -> str:
        """构建二次确认卡片 (第二步)"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange",
                "title": {"content": "🛡️ 二次安全确认", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": f"**确定要执行以下操作吗？**\n\n> {action}", "tag": "lark_md"}
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"content": "确认执行", "tag": "plain_text"},
                            "type": "primary",
                            "value": {"decision": "allow", "confirm_id": confirm_id}
                        },
                        {
                            "tag": "button",
                            "text": {"content": "返回修改/取消", "tag": "plain_text"},
                            "type": "default",
                            "value": {"decision": "back", "confirm_id": confirm_id}
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
    def build_expired_card(action: str) -> str:
        """构建已失效卡片"""
        desc = "此授权请求" if "switch" not in action else "此会话列表"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "grey",
                "title": {"content": f"⌛ {desc}已失效", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": f"**操作**: {action}\n因检测到新消息输入，该交互已自动关闭以防冲突。", "tag": "lark_md"}
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_processing_card(title: str, content: str = "正在处理中，请稍候...") -> str:
        """构建处理中卡片"""
        card = {
            "header": {
                "template": "blue",
                "title": {"content": title, "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": f"⌛ {content}", "tag": "lark_md"}
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_system_status_card(status: str, time_str: str, role: str = "", session_id: str = "") -> str:
        """构建系统启停通知卡片"""
        is_ready = status.lower() == "ready"
        title = "🚀 FGBridge 2.0 已就绪" if is_ready else "🛑 FGBridge 2.0 已停止"
        template = "blue" if is_ready else "grey"
        
        content = f"**时间**: {time_str}"
        if is_ready and role:
            content += f"\n**默认助理**: {role}"
            # content += f"\n**模式**: WebSocket (长连接)"
        
        if session_id:
            content += f"\n**当前会话 ID**: `{session_id}`"
            
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

    @staticmethod
    def build_session_list_card(sessions: list) -> str:
        """构建历史会话列表卡片"""
        elements = []
        from datetime import datetime
        for s in sessions:
            title = s.get("title") or "未命名会话"
            sid = s.get("session_id") or "N/A"
            last_time = s.get("last_active_time", 0)
            time_str = datetime.fromtimestamp(last_time).strftime("%m-%d %H:%M")
            
            # 将 SID 缩短并放在标题括号中，节省空间
            display_title = f"**{title}** ({sid[:8]})"
            
            elements.append({
                "tag": "div",
                "text": {"content": f"{display_title}\n最后活跃: {time_str}", "tag": "lark_md"},
                "extra": {
                    "tag": "button",
                    "text": {"content": "切换", "tag": "plain_text"},
                    "type": "primary" if not s.get("is_active") else "default",
                    "disabled": bool(s.get("is_active")),
                    "value": {
                        "decision": "switch_session",
                        "session_id": s.get("session_id")
                    }
                }
            })
            elements.append({"tag": "hr"})
        
        if not elements:
            elements.append({"tag": "div", "text": {"content": "暂无历史会话记录。", "tag": "plain_text"}})
        else:
            elements.pop() # 移除最后一个 hr

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"content": "📜 历史会话列表", "tag": "plain_text"}
            },
            "elements": elements
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_switch_success_card(title: str, session_id: str = "") -> str:
        """切换成功通知卡片"""
        content = f"已成功切回至：**{title}**"
        if session_id:
            content += f"\n**会话 ID**: `{session_id}`"
            
        card = {
            "header": {
                "template": "green",
                "title": {"content": "🔄 会话切换成功", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": f"{content}\n后续对话将接续此背景。", "tag": "lark_md"}
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_new_session_card(session_id: str = "") -> str:
        """新会话开启卡片"""
        content = "已为您创建全新的 Gemini 会话，上下文已清空。"
        if session_id:
            content += f"\n**新会话 ID**: `{session_id}`"

        card = {
            "header": {
                "template": "blue",
                "title": {"content": "🆕 新会话已开启", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": content, "tag": "lark_md"}
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_simple_text_card(title: str, content: str, template: str = "grey") -> str:
        """通用简单文本卡片"""
        card = {
            "header": {
                "template": template,
                "title": {"content": title, "tag": "plain_text"}
            },
            "elements": [
                {"tag": "div", "text": {"content": content, "tag": "lark_md"}}
            ]
        }
        return json.dumps(card, ensure_ascii=False)

    @staticmethod
    def build_error_card(error_summary: str, detail: str = "") -> str:
        """构建系统异常报警卡片"""
        content = f"**异常摘要**: {error_summary}"
        if detail:
            # 限制详情长度，防止超出卡片限制
            safe_detail = (detail[:500] + "...") if len(detail) > 500 else detail
            content += f"\n\n**上下文**: \n`{safe_detail}`"
            
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red",
                "title": {"content": "🔴 系统运行异常", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": content, "tag": "lark_md"}
                },
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "请检查后台日志或联系管理员排查。"}]
                }
            ]
        }
        return json.dumps(card, ensure_ascii=False)

