from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
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
