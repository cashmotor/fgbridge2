from typing import Optional, Union, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 飞书应用配置
    feishu_app_id: str
    feishu_app_secret: str
    feishu_bot_name: str = "Assistant"
    feishu_user_id: str = ""  # 管理员 OpenID
    
    # Gemini CLI 配置
    gemini_bin_path: str = "gemini"
    gemini_cwd: str = str(Path.cwd() / "data" / "gemini_workspace")
    gemini_md_template_path: str = "gemini.md" # 模板文件路径
    gemini_use_sandbox: bool = True
    gemini_use_yolo: bool = False
    acp_silent_flush_enabled: bool = True
    acp_silent_flush_prompt: str = "Hi"
    acp_card_mode_enabled: bool = False  # 默认使用表情授权，而非卡片回调
    
    # 存储配置
    db_path: str = "data/fgbridge.db"
    role_config_path: str = "data/roles.json"
    session_dir: str = "data/sessions"
    attachment_dir: str = "data/attachments"
    log_dir: str = "logs"
    log_rotation: str = "50 MB"
    
    # 业务策略
    assistant_role: str = "ProjectManager"
    assistant_ttl: int = 3600  # 助理常驻时间 (秒)
    expert_ttl: int = 600      # 专家进程 TTL (秒)
    long_response_threshold: int = 150  # 触发文档化的字数阈值
    
    # 这里使用 Any 以避免 pydantic-settings 强制执行 JSON 解析失败
    reaction_get: Any = ["Get"]
    reaction_done: Any = ["Done"]
    reaction_invalid: Any = ["CrossMark"]
    feishu_export_type: str = "pdf" # 飞书文档导出格式，留空则尝试提取文本

    @field_validator("reaction_get", "reaction_done", "reaction_invalid", mode="before")
    @classmethod
    def validate_reaction_list(cls, v: Any) -> list:
        if isinstance(v, str):
            # 处理逗号分隔字符串或单字符串
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list):
            return v
        return [str(v)]

    # 授权表情包 (飞书表情 Type - 注意区分大小写)
    # https://open.feishu.cn/document/server-docs/im-v1/message-reaction/emojis-introduce
    # 同意：OK, YES, CHECK_MARK
    # 拒绝：NO, CROSS_MARK
    reaction_yes: list = ["OK", "Yes", "CheckMark", "THUMBSUP"]
    reaction_no: list = ["No", "CrossMark", "ThumbsDown"]

    # 消息打包配置
    bundling_enabled: bool = True
    bundling_wait_time: float = 3.0  # 连续输入等待间隔 (秒)
    bundling_max_messages: int = 20  # 单次打包最大消息数

    # 网络配置
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None

    def ensure_dirs(self):
        """确保必要的目录存在"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.session_dir).mkdir(parents=True, exist_ok=True)
        Path(self.attachment_dir).mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

config = Settings()
config.ensure_dirs()
