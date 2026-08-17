#!/usr/bin/env python3
"""
WeChat ↔ OpenCode MCP Server
- MCP stdio: 暴露 wechat_send / wechat_conversations / wechat_history / wechat_setup 工具给 OpenCode
- HTTP (port 4100): 接收 wechat-mcp daemon 的 claw SSE 请求，调用 OpenCode REST API
"""

import asyncio
import json
import os
import sys
import time
import io
import urllib.parse
import aiohttp
from aiohttp import web
from fastmcp import FastMCP

import argparse
import ctypes
from ctypes import wintypes
import struct
import subprocess
import platform
import re

from sensitive_filter import SensitiveFilter


if platform.system() == "Windows":
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _ntdll = ctypes.WinDLL('ntdll', use_last_error=True)

    class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ExitStatus", wintypes.LONG),
            ("PebBaseAddress", ctypes.c_void_p),
            ("AffinityMask", ctypes.c_ulonglong),
            ("BasePriority", wintypes.LONG),
            ("UniqueProcessId", ctypes.c_ulonglong),
            ("InheritedFromUniqueProcessId", ctypes.c_ulonglong),
        ]

    def _read_process_env(pid: int, var_name: str) -> str | None:
        """从远程进程环境变量中读取指定变量值 (Windows only)"""
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        h_process = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h_process:
            return None
        try:
            pbi = _PROCESS_BASIC_INFORMATION()
            status = _ntdll.NtQueryInformationProcess(h_process, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
            if status != 0:
                return None
            peb_addr = pbi.PebBaseAddress
            pp_offset = 0x20
            buf = ctypes.create_string_buffer(8)
            bytes_read = ctypes.c_size_t()
            if not _kernel32.ReadProcessMemory(h_process, ctypes.c_void_p(peb_addr + pp_offset), buf, 8, ctypes.byref(bytes_read)):
                return None
            proc_params_addr = struct.unpack('<Q', buf.raw)[0]
            env_offset = 0x80
            if not _kernel32.ReadProcessMemory(h_process, ctypes.c_void_p(proc_params_addr + env_offset), buf, 8, ctypes.byref(bytes_read)):
                return None
            env_addr = struct.unpack('<Q', buf.raw)[0]
            env_size = 65536
            env_buf = ctypes.create_string_buffer(env_size)
            if not _kernel32.ReadProcessMemory(h_process, ctypes.c_void_p(env_addr), env_buf, env_size, ctypes.byref(bytes_read)):
                return None
            raw = env_buf.raw[:bytes_read.value]
            text = raw.decode('utf-16-le', errors='replace')
            for line in text.split('\x00'):
                if '=' in line:
                    key, _, value = line.partition('=')
                    if key == var_name:
                        return value
            return None
        finally:
            _kernel32.CloseHandle(h_process)


def _find_opencode_sidecar_pid() -> int | None:
    """找到 OpenCode 桌面版的 sidecar 进程 PID"""
    try:
        system = platform.system()
        if system == "Windows":
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_Process -Filter \"Name='OpenCode.exe'\").ProcessId"],
                capture_output=True, text=True, timeout=15
            )
            opencode_pids = [int(line.strip()) for line in result.stdout.strip().split() if line.strip().isdigit()]
            if not opencode_pids:
                return None
            child_result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_Process).Where({$_.ParentProcessId -in @(" + ",".join(str(p) for p in opencode_pids) + ")}).ProcessId"],
                capture_output=True, text=True, timeout=15
            )
            child_pids = [int(line.strip()) for line in child_result.stdout.strip().split() if line.strip().isdigit()]
            for pid in child_pids:
                try:
                    env_val = _read_process_env(pid, "OPENCODE_SERVER_PASSWORD")
                    if env_val:
                        return pid
                except Exception:
                    continue
        else:
            result = subprocess.run(["pgrep", "-f", "opencode"], capture_output=True, text=True, timeout=10)
            pids = [int(line.strip()) for line in result.stdout.strip().split() if line.strip().isdigit()]
            for pid in pids:
                try:
                    with open(f"/proc/{pid}/environ", "rb") as f:
                        data = f.read().decode("utf-8", errors="replace")
                    if "OPENCODE_SERVER_PASSWORD" in data:
                        return pid
                except Exception:
                    continue
    except Exception as e:
        print(f"[wechat-mcp-server] find sidecar PID failed: {e}", flush=True, file=sys.stderr)
    return None


def _find_opencode_port(sidecar_pid: int | None = None) -> int | None:
    """自动发现 OpenCode sidecar 监听的端口"""
    try:
        system = platform.system()
        if system == "Windows":
            if sidecar_pid is None:
                sidecar_pid = _find_opencode_sidecar_pid()
            if sidecar_pid is None:
                result = subprocess.run(
                    ["powershell", "-Command", "(Get-Process -Name OpenCode -ErrorAction SilentlyContinue).Id"],
                    capture_output=True, text=True, timeout=10
                )
                pids = [int(line.strip()) for line in result.stdout.strip().split() if line.strip().isdigit()]
            else:
                pids = [sidecar_pid]
            if not pids:
                return None
            netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
            for line in netstat.stdout.splitlines():
                if "LISTENING" not in line:
                    continue
                for pid in pids:
                    if line.rstrip().endswith(str(pid)):
                        m = re.search(r"127\.0\.0\.1:(\d+)", line)
                        if m:
                            return int(m.group(1))
        else:
            result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                if "OpenCode" in line or "opencode" in line:
                    m = re.search(r"127\.0\.0\.1:(\d+)", line)
                    if m:
                        return int(m.group(1))
    except Exception as e:
        print(f"[wechat-mcp-server] auto-discover OpenCode port failed: {e}", flush=True, file=sys.stderr)
    return None


def _discover_opencode_password() -> str | None:
    """从 OpenCode sidecar 进程环境变量自动读取密码"""
    system = platform.system()
    if system == "Windows":
        pid = _find_opencode_sidecar_pid()
        if pid:
            return _read_process_env(pid, "OPENCODE_SERVER_PASSWORD")
    else:
        result = subprocess.run(["pgrep", "-f", "opencode"], capture_output=True, text=True, timeout=10)
        pids = [int(line.strip()) for line in result.stdout.strip().split() if line.strip().isdigit()]
        for pid in pids:
            try:
                with open(f"/proc/{pid}/environ", "rb") as f:
                    data = f.read().decode("utf-8", errors="replace")
                for line in data.split('\x00'):
                    if line.startswith("OPENCODE_SERVER_PASSWORD="):
                        return line.split("=", 1)[1]
            except Exception:
                continue
    return None


def _discover_opencode_url() -> str:
    """自动发现或使用已有配置的 OpenCode URL"""
    if args.opencode_url != "http://localhost:4096":
        return args.opencode_url
    env_url = os.environ.get("OPENCODE_URL", "")
    if env_url and env_url != "http://localhost:4096":
        return env_url
    sidecar_pid = _find_opencode_sidecar_pid()
    port = _find_opencode_port(sidecar_pid)
    if port:
        print(f"[wechat-mcp-server] auto-discovered OpenCode port: {port}", flush=True, file=sys.stderr)
        return f"http://localhost:{port}"
    print("[wechat-mcp-server] warning: cannot auto-discover OpenCode port, using default 4096", flush=True, file=sys.stderr)
    return args.opencode_url


def _discover_opencode_auth() -> tuple[str, str]:
    """自动发现 OpenCode 认证凭据（优先从 sidecar 进程环境读取密码）"""
    user = args.opencode_user or os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    password = args.opencode_pass or os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not password:
        discovered = _discover_opencode_password()
        if discovered:
            print("[wechat-mcp-server] auto-discovered OpenCode password from sidecar", flush=True, file=sys.stderr)
            password = discovered
    return user, password

parser = argparse.ArgumentParser(description="WeChat OpenCode MCP Bridge")
parser.add_argument("--gateway-only", action="store_true", help="仅HTTP网关模式")
parser.add_argument("--opencode-url", default=os.environ.get("OPENCODE_URL", "http://localhost:4096"), help="OpenCode REST API URL")
parser.add_argument("--opencode-user", default=os.environ.get("OPENCODE_SERVER_USERNAME", ""), help="OpenCode API用户名")
parser.add_argument("--opencode-pass", default=os.environ.get("OPENCODE_SERVER_PASSWORD", ""), help="OpenCode API密码")
args, _ = parser.parse_known_args()

OPENCODE_URL = _discover_opencode_url()
OPECODE_USER, OPECODE_PASS = _discover_opencode_auth()
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "4100"))
WECHAT_MODEL = {
    "modelID": os.environ.get("WECHAT_MODEL_ID", "DeepSeek-V4-Pro"),
    "providerID": os.environ.get("WECHAT_PROVIDER_ID", "aedfewfwegfergertge"),
}
SESSIONS_FILE = os.path.expanduser("~/.wechat-mcp/adapter-sessions.json")
CREDENTIALS_FILE = os.path.expanduser("~/.wechat-mcp/credentials.json")
HISTORY_FILE = os.path.expanduser("~/.wechat-mcp/message-history.json")
CONFIG_FILE = os.path.expanduser("~/.wechat-mcp/config.json")
MAX_HISTORY_PER_CONV = 500
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETUP_GUI_SCRIPT = os.path.join(SCRIPT_DIR, "wechat-setup-gui.py")

conversation_sessions: dict[str, str] = {}
message_history: dict[str, list] = {}
http_client: aiohttp.ClientSession | None = None
conversation_locks: dict[str, asyncio.Lock] = {}
session_locks: dict[str, asyncio.Lock] = {}
save_history_lock = asyncio.Lock()
filter_instance: SensitiveFilter | None = None
_opencode_base_url: str = OPENCODE_URL
_opencode_auth: tuple[str, str] = (OPECODE_USER, OPECODE_PASS)


def log(msg: str):
    print(f"[wechat-mcp-server] {msg}", flush=True, file=sys.stderr)


MAX_RETRIES = 3

async def _ensure_opencode_connection() -> bool:
    """确保 OpenCode 连接可用。如果失败则重新发现端口和凭据并重建 http_client。"""
    global http_client, _opencode_base_url, _opencode_auth
    if http_client is None:
        return await _rebuild_http_client()
    return True


async def _rebuild_http_client() -> bool:
    """重新发现 OpenCode 端口/凭据并重建 http_client。返回是否成功。"""
    global http_client, _opencode_base_url, _opencode_auth
    import base64

    if http_client is not None:
        try:
            await http_client.close()
        except Exception:
            pass
        http_client = None

    new_port = _find_opencode_port()
    if new_port:
        _opencode_base_url = f"http://localhost:{new_port}"
    else:
        _opencode_base_url = _discover_opencode_url()

    user = args.opencode_user or os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    password = args.opencode_pass or os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    _opencode_auth = (user, password)

    headers = {}
    if user and password:
        auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {auth}"

    http_client = aiohttp.ClientSession(headers=headers)

    try:
        async with http_client.get(f"{_opencode_base_url}/session") as r:
            r.raise_for_status()
        log(f"OpenCode 连接成功: {_opencode_base_url}")
        return True
    except Exception as e:
        log(f"OpenCode 连接失败 ({_opencode_base_url}): {e}")
        return False


async def _opencode_request(method: str, path: str, **kwargs) -> aiohttp.ClientResponse:
    """向 OpenCode API 发送请求，失败时自动重试重新发现连接。"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 2):
        if http_client is None:
            ok = await _rebuild_http_client()
            if not ok:
                last_err = Exception("无法连接到 OpenCode")
                continue
        try:
            url = f"{_opencode_base_url}{path}"
            if method == "GET":
                resp = await http_client.get(url, **kwargs)
            elif method == "POST":
                resp = await http_client.post(url, **kwargs)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")
            resp.raise_for_status()
            return resp
        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, ConnectionRefusedError) as e:
            last_err = e
            log(f"连接失败 (尝试 {attempt}/{MAX_RETRIES + 1}): {e}")
            ok = await _rebuild_http_client()
            if not ok:
                continue
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES + 1:
                await asyncio.sleep(0.5 * attempt)
                continue
            raise
    raise last_err or Exception("OpenCode 请求失败")


def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE) as f:
                conversation_sessions.update(json.load(f))
            log(f"加载 {len(conversation_sessions)} 个历史会话")
        except Exception as e:
            log(f"加载会话失败: {e}")


def save_sessions():
    try:
        os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
        with open(SESSIONS_FILE, "w") as f:
            json.dump(conversation_sessions, f, indent=2)
    except Exception as e:
        log(f"保存会话失败: {e}")


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                data = json.load(f)
            for conv_id, msgs in data.items():
                if conv_id not in message_history:
                    message_history[conv_id] = msgs[-MAX_HISTORY_PER_CONV:]
            log(f"加载 {len(message_history)} 个会话的历史消息")
        except Exception as e:
            log(f"加载历史失败: {e}")


async def save_history():
    async with save_history_lock:
        try:
            os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            truncated = {
                k: v[-MAX_HISTORY_PER_CONV:]
                for k, v in message_history.items()
            }
            with open(HISTORY_FILE, "w") as f:
                json.dump(truncated, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            log(f"保存历史失败: {e}")


_save_history_scheduled = False


async def _schedule_save_history():
    global _save_history_scheduled
    if _save_history_scheduled:
        return
    _save_history_scheduled = True
    await asyncio.sleep(30)
    _save_history_scheduled = False
    await save_history()


last_activity: dict[str, float] = {}
conversation_modes: dict[str, str] = {}


async def cleanup_stale_sessions():
    while True:
        await asyncio.sleep(3600)
        ttl_hours = config.get("session", {}).get("ttl_hours", 24)
        ttl = ttl_hours * 3600
        now = time.time()
        stale = [cid for cid, ts in last_activity.items() if now - ts > ttl]
        for cid in stale:
            conversation_sessions.pop(cid, None)
            conversation_locks.pop(cid, None)
            message_history.pop(cid, None)
            last_activity.pop(cid, None)
            conversation_modes.pop(cid, None)
        if stale:
            save_sessions()
            await save_history()
            log(f"清理 {len(stale)} 个过期会话")


def _build_mode_prefix(conv_id: str) -> str:
    mode = conversation_modes.get(conv_id, "default")
    mode_config = config.get("modes", {}).get(mode, {})
    prompt = mode_config.get("system_prompt", "")
    if prompt:
        return f"[System mode: {mode} — {mode_config.get('description', '')}]\n{prompt}\n\n"
    return ""


DEFAULT_CONFIG = {
    "sensitive_filter": {
        "enabled": True,
        "types": {
            "phone": {"enabled": True, "replacement": "[手机号]"},
            "id_card": {"enabled": True, "replacement": "[身份证号]"},
            "bank_card": {"enabled": True, "replacement": "[银行卡号]"},
            "email": {"enabled": True, "replacement": "[邮箱]"},
            "ip_address": {"enabled": False, "replacement": "[IP地址]"},
            "address": {"enabled": False, "replacement": "[地址]"},
        },
    },
    "session": {"ttl_hours": 24},
    "agent": {"preferred": "build"},
    "commands": {
        "enabled": True,
        "search": {"backend": "", "api_key": "", "timeout_seconds": 10},
    },
    "modes": {
        "default": {"system_prompt": "", "description": "正常模式"},
        "coding": {
            "system_prompt": "你是编程专家。回答简洁，优先提供可运行的代码。使用用户偏好的编程语言。",
            "description": "编程模式",
        },
        "translate": {
            "system_prompt": "你是翻译专家。中文翻译成英文，英文翻译成中文。只输出翻译结果。",
            "description": "翻译模式",
        },
    },
}

config: dict = dict(DEFAULT_CONFIG)


def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                user_config = json.load(f)
            config.update(user_config)
            log(f"已加载配置文件: {CONFIG_FILE}")
        except (json.JSONDecodeError, IOError) as e:
            log(f"配置文件解析失败，使用默认值: {e}")
            config = dict(DEFAULT_CONFIG)
    else:
        config = dict(DEFAULT_CONFIG)


def get_agent_mode() -> str:
    """获取当前配置的 agent 模式，统一入口"""
    return config.get("agent", {}).get("preferred", "build")
    return config


async def _find_active_session() -> tuple[str, str] | None:
    """找到 OpenCode 前端当前活跃的 session，优先选择 preferred agent 模式的 session"""
    try:
        resp = await _opencode_request("GET", "/session")
        sessions = await resp.json()
        valid = []
        for s in sessions:
            directory = s.get("directory", "")
            if directory and directory != "C:\\Users\\8" and not directory.startswith("Users"):
                agent = s.get("agent", "plan")
                if not agent:
                    agent = "plan"
                valid.append((s["id"], agent))
        if not valid:
            return None
        preferred = get_agent_mode()
        for sid, agent in valid:
            if agent == preferred:
                log(f"找到活跃 session: {sid} agent={agent} dir={s.get('directory', '?')} (preferred)")
                return sid, agent
        sid, agent = valid[0]
        log(f"找到活跃 session: {sid} agent={agent} (fallback, 无 {preferred} session)")
        return sid, agent
    except Exception as e:
        log(f"查找活跃 session 失败: {e}")
    return None

_active_session_id: str | None = None
_active_session_agent: str = get_agent_mode()

async def get_or_create_session(conv_id: str) -> str:
    global _active_session_id, _active_session_agent
    await _ensure_opencode_connection()
    if conv_id in conversation_sessions:
        return conversation_sessions[conv_id]

    resp = await _opencode_request(
        "POST", "/session",
        json={"projectID": "global", "agent": get_agent_mode()},
    )
    data = await resp.json()
    session_id = data["id"]
    _active_session_id = session_id
    _active_session_agent = get_agent_mode()
    log(f"新建会话: {conv_id[:8]} -> {session_id} (agent={_active_session_agent})")
    conversation_sessions[conv_id] = session_id
    save_sessions()
    return session_id


async def send_to_opencode(session_id: str, message: str) -> str:
    await _ensure_opencode_connection()

    resp = await _opencode_request(
        "POST", f"/session/{session_id}/prompt_async",
        json={"model": WECHAT_MODEL, "agent": get_agent_mode(), "parts": [{"type": "text", "text": message}]},
    )
    log(f"消息已发送 -> {session_id}")

    await asyncio.sleep(2)

    resp = await _opencode_request("GET", f"/session/{session_id}/message")
    raw = await resp.read()
    msgs_before = json.loads(raw, strict=False)
    ids_before = {m["info"]["id"] for m in msgs_before if m["info"]["role"] != "assistant"}
    log(f"ids_before 快照: {len(ids_before)} 条 (已排除 assistant 消息)")

    deadline = time.time() + 600
    went_missing = False
    consecutive_errors = 0
    status_checks = 0
    while time.time() < deadline:
        await asyncio.sleep(1)
        try:
            resp = await _opencode_request("GET", "/session/status")
            statuses = await resp.json()
            consecutive_errors = 0
            status_checks += 1
            if session_id not in statuses:
                if status_checks < 5:
                    log(f"session 未出现在 status 列表中 (第{status_checks}次)，继续等待...")
                    continue
                log("session 已从 status 消失，等待写入...")
                went_missing = True
                break
            status_type = statuses[session_id].get("type", "")
            if status_type == "idle":
                break
            if status_checks % 30 == 0:
                log(f"等待 AI 回复中... (已等待 {status_checks}s, status={status_type})")
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                log(f"连续 {consecutive_errors} 次轮询出错，放弃等待: {e}")
                break
            log(f"轮询出错 (第{consecutive_errors}次): {e}")
            await asyncio.sleep(2)

    await asyncio.sleep(1.5 if went_missing else 0.5)

    retries = 30
    delay = 0.5
    last_text = ""
    for attempt in range(retries):
        try:
            resp = await _opencode_request("GET", f"/session/{session_id}/message")
            raw = await resp.read()
            msgs_now = json.loads(raw, strict=False)
        except Exception as e:
            log(f"获取消息失败 (第{attempt+1}次): {e}")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 3)
            continue

        new_msgs = [
            m for m in msgs_now
            if m["info"]["id"] not in ids_before and m["info"]["role"] == "assistant"
        ]
        if new_msgs and new_msgs[-1].get("info", {}).get("time", {}).get("completed"):
            text = "\n".join(
                "".join(p.get("text", "") for p in m.get("parts", []) if p.get("type") == "text")
                for m in new_msgs
            ).strip()
            if not text:
                last_parts = new_msgs[-1].get("parts", [])
                part_types = [p.get("type", "?") for p in last_parts]
                log(f"空回复诊断: parts类型={part_types}")
                non_text = []
                for p in last_parts:
                    if p.get("type") == "tool_call":
                        non_text.append(f"[工具调用: {p.get('tool', '?')}]")
                    elif p.get("type") == "tool_result":
                        non_text.append(f"[工具结果]")
                    elif p.get("type") == "reasoning":
                        non_text.append(f"[思考: {str(p.get('text', ''))[:80]}...]")
                if non_text:
                    return "\n".join(non_text) or "(空回复: 非文本回复)"
                return "(空回复)"
            return text

        if not new_msgs:
            pass
        elif new_msgs[-1].get("info", {}).get("time", {}).get("completed") is None:
            current_text = "".join(p.get("text", "") for p in new_msgs[-1].get("parts", []) if p.get("type") == "text")
            if current_text and current_text != last_text:
                last_text = current_text
                log(f"消息仍在生成中... ({len(current_text)} 字符)")
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, 3)

    resp = await _opencode_request("GET", f"/session/{session_id}/message")
    raw = await resp.read()
    msgs_now = json.loads(raw, strict=False)
    new_msgs = [
        m for m in msgs_now
        if m["info"]["id"] not in ids_before and m["info"]["role"] == "assistant"
    ]
    if not new_msgs:
        return "(未收到回复)"
    text = "".join(
        p.get("text", "") for p in new_msgs[-1].get("parts", []) if p.get("type") == "text"
    ).strip()
    if not text:
        last_parts = new_msgs[-1].get("parts", [])
        part_types = [p.get("type", "?") for p in last_parts]
        log(f"超时空回复诊断: parts类型={part_types}")
        return "(空回复)"
    return text


async def _handle_command(conv_id: str, text: str) -> tuple[bool, str]:
    """处理快捷指令。返回 (is_command, result_text)"""
    text = text.strip()
    if not text.startswith("/"):
        return False, ""

    cmd_config = config.get("commands", {})
    if not cmd_config.get("enabled", True):
        return False, ""

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        help_lines = [
            "可用指令:",
            "/help     - 显示此帮助",
            "/status   - 查看系统状态",
            "/reset    - 重置当前会话 (用法: /reset yes)",
            "/model    - 显示当前 AI 模型",
            "/mode     - 切换对话模式 (用法: /mode <模式名>)",
            "/search   - 搜索网络 (用法: /search <查询>)",
            "",
            "提示: 在消息前加空格可绕过指令拦截，如 ' /help'",
        ]
        available_modes = config.get("modes", {})
        if len(available_modes) > 1:
            mode_list = ", ".join(available_modes.keys())
            help_lines.insert(-2, f"可用模式: {mode_list}")
        return True, "\n".join(help_lines)

    if cmd == "/status":
        return True, (
            f"活跃会话: {len(conversation_sessions)}\n"
            f"历史会话: {len(message_history)}\n"
            f"当前模型: {WECHAT_MODEL['modelID']} / {WECHAT_MODEL['providerID']}\n"
            f"Agent 模式: {_active_session_agent}"
        )

    if cmd == "/reset":
        if args.strip().lower() != "yes":
            return True, "确认重置当前会话？请发送 /reset yes 确认。注意：重置后对话历史将被清除。"
        old_sid = conversation_sessions.pop(conv_id, None)
        conversation_locks.pop(conv_id, None)
        message_history.pop(conv_id, None)
        save_sessions()
        asyncio.create_task(save_history())
        log(f"会话已重置: {conv_id[:8]} (原 session: {old_sid})")
        return True, "会话已重置。下一条消息将重新开始对话。"

    if cmd == "/model":
        return True, f"当前模型: {WECHAT_MODEL['modelID']}\nProvider: {WECHAT_MODEL['providerID']}"

    if cmd == "/search":
        query = args.strip()
        if not query:
            return True, "用法: /search <查询内容>"
        return True, await _do_search(query)

    if cmd == "/mode":
        mode_name = args.strip().lower() or "default"
        available = list(config.get("modes", {}).keys())
        if mode_name not in available:
            return True, f"未知模式: {mode_name}\n可用模式: {', '.join(available)}\n用法: /mode <模式名>"
        conversation_modes[conv_id] = mode_name
        return True, f"已切换到 {mode_name} 模式。下一条消息将使用该模式。"

    return False, ""


async def _do_search(query: str) -> str:
    search_config = config.get("commands", {}).get("search", {})
    backend = search_config.get("backend", "")
    api_key = search_config.get("api_key", "")
    timeout = search_config.get("timeout_seconds", 10)

    if backend == "tavily" and api_key:
        try:
            async with aiohttp.ClientSession() as client:
                async with client.post(
                    "https://api.tavily.com/search",
                    json={"query": query, "max_results": 5, "search_depth": "basic"},
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as r:
                    if r.status != 200:
                        return f"搜索失败: API 返回 {r.status}"
                    data = await r.json()
                    results = data.get("results", [])
                    if not results:
                        return "未找到相关结果"
                    lines = [f"搜索: {query}\n"]
                    for i, item in enumerate(results[:5], 1):
                        title = item.get("title", "无标题")
                        snippet = item.get("content", item.get("snippet", ""))[:200]
                        lines.append(f"{i}. {title}\n   {snippet}")
                    result_text = "\n".join(lines)
                    if len(result_text) > 1800:
                        result_text = result_text[:1800] + "\n...(结果过长，已截断)"
                    return result_text
        except asyncio.TimeoutError:
            return "搜索超时，请稍后重试"
        except Exception as e:
            return f"搜索失败: {e}"

    if backend == "custom" and search_config.get("custom_url"):
        try:
            url = search_config["custom_url"].replace("{query}", urllib.parse.quote(query))
            async with aiohttp.ClientSession() as client:
                async with client.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    text = await r.text()
                    if len(text) > 1800:
                        text = text[:1800] + "\n...(结果过长，已截断)"
                    return text
        except Exception as e:
            return f"自定义搜索失败: {e}"

    return (
        "搜索功能未配置。请在 ~/.wechat-mcp/config.json 中设置:\n"
        '  "commands": {"search": {"backend": "tavily", "api_key": "你的密钥"}}\n'
        "支持的 backend: tavily, custom"
    )


async def handle_chat(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    message = body.get("message", "")
    conv_id = body.get("conversationId")
    sender_id = body.get("senderId", "")
    if not conv_id:
        conv_id = sender_id or "__daemon_direct__"
        log(f"警告: 收到无 conversationId 的消息，使用 fallback: {conv_id[:20]}")
    log(f"收到微信消息: conv={conv_id[:8]} msg={message[:60]!r}")

    is_cmd, cmd_result = await _handle_command(conv_id, message)
    if is_cmd:
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        })
        await response.prepare(request)
        await response.write(
            f"data: {json.dumps({'type': 'start', 'conversationId': conv_id})}\n\n".encode()
        )
        for i in range(0, len(cmd_result), 50):
            await response.write(
                f"data: {json.dumps({'type': 'content', 'text': cmd_result[i:i + 50]})}\n\n".encode()
            )
        await response.write(
            f"data: {json.dumps({'type': 'done', 'content': cmd_result})}\n\n".encode()
        )
        await response.write_eof()
        return response

    message_history.setdefault(conv_id, []).append({
        "role": "user", "text": message, "ts": time.time()
    })
    asyncio.create_task(_schedule_save_history())

    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })
    await response.prepare(request)

    async def sse(data: dict):
        await response.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode())

    lock = conversation_locks.setdefault(conv_id, asyncio.Lock())

    async with lock:
        session_id = await get_or_create_session(conv_id)
        await sse({"type": "start", "conversationId": conv_id})

        try:
            safe_message = filter_instance.mask(message) if filter_instance else message
            mode_prefix = _build_mode_prefix(conv_id)
            if mode_prefix:
                safe_message = mode_prefix + safe_message
            last_activity[conv_id] = time.time()
            reply_task = asyncio.create_task(send_to_opencode(session_id, safe_message))
            while not reply_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(reply_task), timeout=5)
                except asyncio.TimeoutError:
                    await response.write(b": heartbeat\n\n")

            content = reply_task.result()

        except Exception as e:
            log(f"处理失败: {e}")
            try:
                await sse({"type": "done", "content": f"错误: {e}"})
            except Exception:
                pass
            await response.write_eof()
            return response

    message_history.setdefault(conv_id, []).append({
        "role": "assistant", "text": content, "ts": time.time()
    })
    asyncio.create_task(_schedule_save_history())

    log(f"回复: {content[:80]!r}")
    for i in range(0, len(content), 50):
        await sse({"type": "content", "text": content[i:i + 50]})
    await sse({"type": "done", "content": content})

    await response.write_eof()

    if sender_id and content and content not in ("(空回复)", "(未收到回复)", "(空回复: 非文本回复)"):
        asyncio.create_task(_send_via_daemon(sender_id, content))

    return response


async def _send_via_daemon(sender_id: str, text: str):
    """通过 daemon 的 /send API 发送回复作为备份"""
    try:
        daemon_file = os.path.expanduser("~/.wechat-mcp/daemon.json")
        if not os.path.exists(daemon_file):
            return
        with open(daemon_file) as f:
            daemon_info = json.load(f)
        daemon_port = daemon_info.get("port")
        if not daemon_port:
            return
        daemon_url = f"http://127.0.0.1:{daemon_port}/send"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                daemon_url,
                json={"to": sender_id, "text": text},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                if result.get("success"):
                    log(f"daemon 备份发送成功: {sender_id[:20]}...")
                else:
                    log(f"daemon 备份发送失败: {result}")
    except Exception as e:
        log(f"daemon 备份发送异常: {e}")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "conversations": len(conversation_sessions),
    })


async def handle_share_qr(request: web.Request) -> web.Response:
    """生成即时有效的 bot 分享 QR 码（~90 秒内有效）"""
    await _ensure_opencode_connection()
    base = "https://ilinkai.weixin.qq.com"
    bot_type = "3"
    auth_token = os.environ.get("WECHAT_MCP_GATEWAY_TOKEN", "")

    cred_file = os.path.expanduser("~/.wechat-mcp/credentials.json")
    if not auth_token and os.path.exists(cred_file):
        try:
            with open(cred_file) as f:
                cred = json.load(f)
            auth_token = f"Bearer {cred.get('accountId', '')}:{cred.get('token', '')}"
        except Exception as e:
            log(f"加载凭据失败: {e}")

    if not auth_token:
        return web.json_response({"error": "未找到凭据"}, status=500)

    try:
        import qrcode
        async with http_client.get(
            f"{base}/ilink/bot/get_bot_qrcode?bot_type={bot_type}",
            headers={"Authorization": auth_token}
        ) as r:
            if r.status != 200:
                return web.json_response({"error": f"API error: {r.status}"}, status=502)
            raw = await r.read()
            data = json.loads(raw)

        qr_url = data.get("qrcode_img_content", "")
        qr_token = data.get("qrcode", "")

        buf = io.BytesIO()
        qr_img = qrcode.make(qr_url)
        qr_img.save(buf, format="PNG")

        return web.Response(
            body=buf.getvalue(),
            content_type="image/png",
            headers={
                "X-QR-URL": qr_url,
                "X-QR-Token": qr_token,
            }
        )
    except Exception as e:
        log(f"生成 QR 失败: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def start_gateway(loop: asyncio.AbstractEventLoop):
    global http_client, filter_instance
    load_config()
    filter_instance = SensitiveFilter(config)
    ok = await _rebuild_http_client()
    if not ok:
        log("警告: 初始 OpenCode 连接失败，将在首次请求时重试")
    load_sessions()
    load_history()

    app = web.Application()
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/share-qr", handle_share_qr)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", GATEWAY_PORT)
    try:
        await site.start()
        log(f"HTTP gateway 已启动 port={GATEWAY_PORT}")
    except OSError as e:
        if e.errno in (48, 98, 10048):
            log(f"port {GATEWAY_PORT} 已被占用以 MCP-only 模式运行（网关将由已有进程提供）")
        else:
            raise


mcp = FastMCP("wechat-opencode", instructions="通过此工具与微信对话交互，支持发送消息、查看会话、管理登录")


@mcp.tool()
async def wechat_send(conversation_id: str, text: str) -> str:
    """
    向指定微信会话发送消息并获取 OpenCode 的回复。
    Args:
        conversation_id: 微信会话 ID（可从 wechat_conversations 获取）
        text: 要发送的消息内容
    """
    await _ensure_opencode_connection()
    setup_msg = _check_setup_result()
    if setup_msg:
        log(f"setup 结果: {setup_msg}")
    try:
        conv_lock = conversation_locks.setdefault(conversation_id, asyncio.Lock())
        if conv_lock.locked():
            return "错误: 该会话正在处理中，请等待当前消息处理完成后再试"

        safe_text = filter_instance.mask(text) if filter_instance else text
        mode_prefix = _build_mode_prefix(conversation_id)
        if mode_prefix:
            safe_text = mode_prefix + safe_text

        async with conv_lock:
            session_id = await get_or_create_session(conversation_id)
            sess_lock = session_locks.setdefault(session_id, asyncio.Lock())
            async with sess_lock:
                reply = await send_to_opencode(session_id, safe_text)
            last_activity[conversation_id] = time.time()
            message_history.setdefault(conversation_id, []).append(
                {"role": "assistant", "text": reply, "ts": time.time()}
            )
            asyncio.create_task(_schedule_save_history())
            return reply
    except Exception as e:
        return f"发送失败: {e}"


SETUP_RESULT_FILE = os.path.expanduser("~/.wechat-mcp/setup-result.json")


def _check_setup_result() -> str | None:
    if os.path.exists(SETUP_RESULT_FILE):
        try:
            with open(SETUP_RESULT_FILE, "r") as f:
                result = json.load(f)
            os.remove(SETUP_RESULT_FILE)
            if result.get("success"):
                return f"微信登录成功 (Account: {result.get('accountId', 'unknown')})"
            else:
                return f"微信登录失败: {result.get('message', result.get('error', 'unknown'))}"
        except Exception:
            pass
    return None


@mcp.tool()
def wechat_conversations() -> list[dict]:
    """列出所有活跃的微信会话。"""
    setup_msg = _check_setup_result()
    if setup_msg:
        log(f"setup 结果: {setup_msg}")
    return [
        {"conversation_id": conv_id, "session_id": sess_id}
        for conv_id, sess_id in conversation_sessions.items()
    ]


@mcp.tool()
def wechat_history(conversation_id: str, limit: int = 20) -> list[dict]:
    """获取指定微信会话的消息历史。"""
    history = message_history.get(conversation_id, [])
    return history[-limit:]


@mcp.tool()
async def wechat_setup(force: bool = False) -> str:
    """
    触发微信扫码登录。在 Windows 上弹出二维码窗口，用户扫码后自动保存凭证。
    调用后立即返回，不会等待扫码完成。扫码完成后请告知 AI。
    Args:
        force: 是否强制重新登录（忽略已有凭证）
    """
    if not force:
        try:
            if os.path.exists(CREDENTIALS_FILE):
                with open(CREDENTIALS_FILE) as f:
                    cred = json.load(f)
                if cred.get("accountId"):
                    return (
                        f"已有有效凭证 (Account: {cred.get('accountId')})，"
                        f"无需重新登录。如需强制重新登录请设置 force=True"
                    )
        except Exception:
            pass

    if not os.path.exists(SETUP_GUI_SCRIPT):
        return "错误: 找不到 wechat-setup-gui.py，请确保文件在同一目录下"

    cmd = [sys.executable, SETUP_GUI_SCRIPT, "--json-output"]
    if force:
        cmd.append("--force")

    log(f"启动微信登录子进程: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return f"错误: 找不到 Python 解释器 ({sys.executable})"
    except Exception as e:
        log(f"wechat_setup 异常: {e}")
        return f"登录过程异常: {e}"

    return (
        "✅ 微信扫码窗口已弹出，请使用手机微信扫描屏幕上的二维码完成登录。\n"
        "⏳ 扫码窗口会自动检测登录状态，登录成功后凭证将自动保存。\n"
        "💡 登录完成后，请告诉我你已经登录成功。"
    )


async def _main():
    gateway_only = args.gateway_only
    await start_gateway(asyncio.get_event_loop())
    asyncio.create_task(cleanup_stale_sessions())
    if gateway_only:
        log("仅 HTTP gateway 模式（systemd service）")
        await asyncio.Event().wait()
    else:
        log("MCP stdio 模式（HTTP gateway + MCP stdio）")
        await mcp.run_async(transport="stdio")


if __name__ == "__main__":
    mode = "gateway-only" if args.gateway_only else "mcp+gateway"
    log(f"启动 WeChat MCP Server（mode={mode} OpenCode API={OPENCODE_URL} auth={'yes' if OPECODE_USER else 'no'}）")
    asyncio.run(_main())
