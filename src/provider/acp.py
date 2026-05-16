import json
import os
import select
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from loguru import logger
from src.config import config

class ACPError(Exception):
    """ACP 模块基础异常"""
    pass

class ACPProvider:
    """
    Gemini CLI ACP 模式提供者
    负责管理 gemini --acp 子进程，封装 JSON-RPC 2.0 通信逻辑及自动重启机制。
    使用非阻塞二进制流通信以确保在沙箱模式下的稳定性。
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._is_running = False

        # 用于存储 ACP 发送给 CLI 的请求信息
        self._pending_permissions: Dict[str, Dict] = {}
        
        # 用于收集流式输出内容
        self._collected_content = ""
        self._collected_thought = ""
        self._collected_images: List[Dict[str, Any]] = []

    def start(self, system_prompt: str = None) -> None:
        """启动 gemini --acp 子进程并完成初始化握手"""
        try:
            # 1. 准备工作目录隔离
            target_cwd = Path(config.gemini_cwd)
            target_cwd.mkdir(parents=True, exist_ok=True)
            
            # 2. 自动引导 gemini.md
            template_path = Path(config.gemini_md_template_path)
            if template_path.exists():
                target_md = target_cwd / "gemini.md"
                # 如果目标文件不存在，或者模板更新了，则复制
                if not target_md.exists():
                    logger.info(f"正在部署引导文件: {template_path} -> {target_md}")
                    shutil.copy2(template_path, target_md)
            else:
                logger.warning(f"未找到 gemini.md 模板文件: {template_path}")

            args = [config.gemini_bin_path, "--acp"]
            if config.gemini_use_sandbox:
                args.append("--sandbox")
            if config.gemini_use_yolo:
                args.append("--yolo")

            logger.info(f"正在启动 ACP 进程: {' '.join(args)} (cwd: {target_cwd})")

            # 配置环境变量
            env = os.environ.copy()
            for proxy in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
                val = getattr(config, proxy.lower(), None)
                if val:
                    env[proxy] = val

            self._process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                env=env,
                cwd=str(target_cwd),
            )
            self._is_running = True

            if config.gemini_use_sandbox:
                logger.info("等待沙箱环境初始化 (3s)...")
                time.sleep(3)

            # 执行初始化握手
            capabilities = {
                "promptCapabilities": {"image": True, "audio": True},
                "mcpCapabilities": {"http": True}
            }
            params = {"protocolVersion": 1, "capabilities": capabilities}
            if system_prompt:
                params["systemInstruction"] = system_prompt
                logger.info(f"ACP 注入系统提示词 (长度: {len(system_prompt)})")

            resp = self._call(
                "initialize",
                params,
                is_initializing=True
            )
            logger.success(f"ACP 进程初始化成功: {resp.get('result', {})}")

        except Exception as e:
            self._is_running = False
            logger.error(f"ACP 进程启动失败: {e}")
            raise ACPError(f"无法启动 ACP 进程: {e}")

    def _call(
            self,
            method: str,
            params: Dict[str, Any],
            timeout: int = 300,
            is_initializing: bool = False,
    ) -> Dict[str, Any]:
        """发送 JSON-RPC 请求并同步等待响应"""
        if not is_initializing:
            if not self._process or self._process.poll() is not None:
                logger.warning("ACP 进程已退出，尝试重启...")
                self.restart()

        if method == "session/prompt":
            self._collected_content = ""
            self._collected_thought = ""
            self._collected_images = []

        with self._lock:
            self._req_id += 1
            if method == "session/prompt":
                self._last_prompt_req_id = self._req_id

            request = {
                "jsonrpc": "2.0",
                "id": self._req_id,
                "method": method,
                "params": params,
            }

            try:
                payload = (json.dumps(request) + "\n").encode("utf-8")
                logger.debug(f"ACP >>> 发送请求: {json.dumps(request)}")
                if self._process and self._process.stdin:
                    self._process.stdin.write(payload)
                    self._process.stdin.flush()
                else:
                    raise ACPError("ACP 进程标准输入流不可用")

                return self._read_until(self._req_id, method, timeout)

            except Exception as e:
                logger.error(f"ACP 通信异常: {e}")
                raise ACPError(f"ACP 通信失败: {e}")

    def _read_until(self, target_id: int, method: str, timeout: int) -> Dict[str, Any]:
        """流式读取二进制输出直到获得目标 ID 的响应"""
        start_time = time.time()
        stdout_buffer = b""
        max_buffer_size = 1024 * 1024

        for pipe in [self._process.stdout, self._process.stderr]:
            if pipe:
                os.set_blocking(pipe.fileno(), False)

        while time.time() - start_time < timeout:
            if not self._process: raise ACPError("ACP 进程未启动")

            poll_code = self._process.poll()
            pipes = [p for p in [self._process.stdout, self._process.stderr] if p]
            
            if not pipes: raise ACPError("ACP 进程管道不可用")

            readable, _, _ = select.select(pipes, [], [], 0.1)

            for r in readable:
                if r is self._process.stderr:
                    try:
                        err_chunk = r.read()
                        if err_chunk:
                            logger.debug(f"ACP STDERR: {err_chunk.decode('utf-8', errors='replace').strip()}")
                    except Exception: pass

                if r is self._process.stdout:
                    try:
                        chunk = r.read()
                        if not chunk: continue
                        stdout_buffer += chunk
                        
                        while b"\n" in stdout_buffer:
                            line_bytes, stdout_buffer = stdout_buffer.split(b"\n", 1)
                            line = line_bytes.decode("utf-8", errors="replace").strip()
                            
                            if not line or not (line.startswith("{") and line.endswith("}")):
                                continue

                            try:
                                msg = json.loads(line)
                                if msg.get("id") == target_id:
                                    if method == "session/prompt":
                                        res = msg.setdefault("result", {})
                                        if self._collected_content: res["content"] = self._collected_content
                                        if self._collected_thought: res["thought"] = self._collected_thought
                                        if self._collected_images:
                                            res.setdefault("items", []).extend(self._collected_images)
                                    return msg
                                
                                if "method" in msg and "id" not in msg:
                                    self._handle_notification(msg)
                                    continue

                                if "method" in msg and "id" in msg:
                                    if msg["method"] == "session/request_permission":
                                        return self._handle_permission_request(msg)
                            except json.JSONDecodeError: continue
                    except Exception as e:
                        logger.error(f"读取 Stdout 异常: {e}")
                        continue

            if not readable and poll_code is not None:
                raise ACPError(f"ACP 进程异常退出 (code: {poll_code})")

        raise ACPError(f"ACP 等待超时 (target_id: {target_id}, method: {method})")

    def _handle_notification(self, msg: Dict[str, Any]) -> None:
        """处理 ACP 流式通知"""
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "session/update":
            update = params.get("update", {})
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content", {})
                ctype = content.get("type")
                if ctype == "text":
                    self._collected_content += content.get("text", "")
                elif ctype == "thought":
                    self._collected_thought += content.get("thought", "")
                elif ctype in ["image", "file"]:
                    self._collected_images.append(content)
            elif update.get("sessionUpdate") == "call_update":
                chunk = update.get("text", "")
                if chunk:
                    self._collected_thought += f"\n[Plan] {chunk}\n"

    def _handle_permission_request(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """处理权限请求"""
        rpc_id = msg.get("id")
        params = msg.get("params", {})
        session_id = params.get("sessionId")
        tool_call = params.get("toolCall", {})
        options = params.get("options", [])
        confirmation_id = tool_call.get("toolCallId") or f"perm_{int(time.time())}"

        self._pending_permissions[confirmation_id] = {
            "rpc_id": rpc_id,
            "session_id": session_id,
            "options": options
        }

        logger.info(f"收到 ACP 权限请求: {confirmation_id} ({tool_call.get('title')})")

        return {
            "result": {
                "type": "confirmation_required",
                "confirmationId": confirmation_id,
                "action": tool_call.get("title", "未知操作"),
                "message": f"Gemini 请求执行操作: {tool_call.get('title')}\n详情: {json.dumps(tool_call.get('content', {}), ensure_ascii=False)}"
            }
        }

    def _wait_for_prompt_completion(self, session_id: str) -> Dict[str, Any]:
        """等待原 prompt 请求完成"""
        if hasattr(self, "_last_prompt_req_id"):
            with self._lock:
                try:
                    return self._read_until(self._last_prompt_req_id, "session/prompt", 300)
                except Exception as e:
                    logger.error(f"等待 Prompt 完成失败: {e}")
                    return {"error": {"message": str(e)}}
        return {"result": {"content": "已发送决策，但无法追踪状态。"}}

    def session_new(self) -> str:
        """创建新会话"""
        params = {"cwd": config.gemini_cwd, "mcpServers": []}
        resp = self._call("session/new", params)
        return resp.get("result", {}).get("sessionId", "")

    def send(self, session_id: str, text: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """发送提示词"""
        prompt_parts = [{"type": "text", "text": text}]
        if attachments:
            prompt_parts.extend(attachments)
        return self._call("session/prompt", {"sessionId": session_id, "prompt": prompt_parts})

    def confirm(self, session_id: str, confirmation_id: str, decision: str) -> Dict[str, Any]:
        """发送决策"""
        if confirmation_id in self._pending_permissions:
            perm_data = self._pending_permissions.pop(confirmation_id)
            rpc_id, sid = perm_data["rpc_id"], perm_data["session_id"]
            available_options = [opt.get("optionId") for opt in perm_data.get("options", [])]
            
            option_id = "allow" if decision == "allow" else "deny"
            if decision == "allow":
                for cand in ["allow", "proceed_once", "yes"]:
                    if cand in available_options:
                        option_id = cand
                        break
            else:
                for cand in ["deny", "cancel", "no"]:
                    if cand in available_options:
                        option_id = cand
                        break

            response = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"optionId": option_id, "outcome": {"outcome": "selected" if decision == "allow" else "cancelled", "optionId": option_id}}
            }
            
            with self._lock:
                payload = (json.dumps(response) + "\n").encode("utf-8")
                if self._process and self._process.stdin:
                    self._process.stdin.write(payload)
                    self._process.stdin.flush()
            
            return self._wait_for_prompt_completion(sid)
        
        return self._call("confirm", {"sessionId": session_id, "confirmationId": confirmation_id, "decision": decision})

    def session_load(self, session_id: str) -> bool:
        """恢复会话"""
        try:
            # 这里的 session_id 实际上是保存在 data/sessions 下的文件名或标识
            session_path = Path(config.session_dir) / f"{session_id}.session"
            if not session_path.exists():
                logger.warning(f"找不到会话文件: {session_path}")
                return False
                
            params = {
                "sessionId": session_id, 
                "path": str(session_path),
                "cwd": config.gemini_cwd, 
                "mcpServers": []
            }
            return "error" not in self._call("session/load", params)
        except Exception as e:
            logger.error(f"加载会话异常: {e}")
            return False

    def session_save(self, session_id: str) -> bool:
        """保存会话到磁盘"""
        try:
            session_path = Path(config.session_dir) / f"{session_id}.session"
            params = {
                "sessionId": session_id,
                "path": str(session_path)
            }
            return "error" not in self._call("session/save", params)
        except Exception as e:
            logger.error(f"保存会话异常: {e}")
            return False

    def stop(self) -> None:
        """停止 ACP"""
        if self._process:
            try:
                if self._process.stdin: self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception: self._process.kill()
            finally: self._process, self._is_running = None, False

    def restart(self) -> None:
        """重启 ACP"""
        self.stop()
        self.start()
