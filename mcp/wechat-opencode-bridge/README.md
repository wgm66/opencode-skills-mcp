# WeChat OpenCode Bridge

将微信与 OpenCode（及任意兼容 HTTP API 的 AI Agent）连接，实现通过微信与 AI 对话。

```
微信消息 → iLink API → wechat-mcp daemon → HTTP Gateway → OpenCode REST API → 回复
                                                                    ←
```

## 工作原理

```
                     WeChat iLink API
                          │
                 ┌────────┴────────┐
                 │  wechat-mcp     │
                 │  daemon         │
                 │  (background)   │
                 └───┬─────────────┘
                     │ HTTP IPC (localhost)
                     ▼
          ┌──────────────────────┐
          │  wechat-mcp-server   │  ← 本项目的核心组件
          │  (Python aiohttp)    │
          │  port 4100           │
          └────┬────────────┬────┘
               │            │
               ▼            ▼
        OpenCode REST   MCP stdio
        (动态端口)      (FastMCP 工具)
```

1. **wechat-mcp daemon** — 维护 WeChat iLink 长连接，轮询收取消息
2. **HTTP Gateway** (`wechat-mcp-server.py`) — 接收 daemon 转发的消息，通过 OpenCode REST API 发送，返回 SSE 流式响应
3. **MCP 工具** — 通过 FastMCP 暴露 `wechat_send`、`wechat_conversations`、`wechat_history` 工具给 OpenCode 内部使用

## 前置要求

- Node.js >= 18
- Python >= 3.10
- OpenCode（或任何提供 REST API 的 AI Agent）
- 微信 iOS/Android/PC/Mac（最新版，支持 ClawBot 插件）

## 快速安装

```bash
# 1. 安装 wechat-mcp
npm install -g @paean-ai/wechat-mcp

# 2. 安装 Python 依赖
pip install aiohttp fastmcp qrcode Pillow

# 3. 微信扫码登录（Windows 弹窗推荐）
py wechat-setup-gui.py
# 替代方案（终端 ASCII 二维码）：
#   wechat-mcp setup
```

## 启动服务

> **重要**：必须先启动服务，再在微信中发送消息。服务启动顺序如下：

### Windows

```bash
# 1. 启动微信守护进程（必须第一步）
start /min wechat-mcp daemon

# 2. 启动 HTTP 网关（必须第二步）
start /min python E:\opencode_mcp\wechat-opencode-bridge-main\wechat-mcp-server.py

# 3. 启动 MCP Agent（必须第三步）
start /min wechat-mcp serve --agent opencode --mode gateway --gateway-url http://localhost:4100 --gateway-type claw
```

### Linux (systemd 开机自启)

```bash
# 复制服务文件
cp systemd/*.service ~/.config/systemd/user/

# 重新加载并启动
systemctl --user daemon-reload
systemctl --user enable --now wechat-mcp-daemon.service
systemctl --user enable --now wechat-opencode-adapter.service
systemctl --user enable --now wechat-mcp-agent.service

# 启用用户 linger（允许无登录会话运行服务）
sudo loginctl enable-linger $(whoami)
```

---

# 配置指南

## 1. OpenCode MCP 配置

在 OpenCode 的配置文件中（`opencode.json` 或项目中的 `opencode-config.json`）添加 wechat MCP server：

```json
{
  "mcp": {
    "wechat": {
      "type": "local",
      "command": [
        "D:\\python\\python.exe",
        "E:/opencode_mcp/wechat-opencode-bridge-main/wechat-mcp-server.py"
      ],
      "enabled": true,
      "timeout": 300000,
      "environment": {
        "GATEWAY_PORT": "4100",
        "WECHAT_MODEL_ID": "DeepSeek-V4-Pro",
        "WECHAT_PROVIDER_ID": "aedfewfwegfergertge"
      }
    }
  }
}
```

**重要说明**：
- 网关会**自动发现** OpenCode 的 REST API 端口，无需手动配置
- 网关会**自动获取** OpenCode 的认证凭据（从环境变量 `OPENCODE_SERVER_USERNAME` / `OPENCODE_SERVER_PASSWORD`）
- 网关会**自动复用**当前 OpenCode 前端活跃的会话（session）

---

## 2. DEBUG 模式：调整日志输出和调试行为

### 方式一：查看实时日志（推荐）

`wechat-mcp-server.py` 的所有日志输出到 **stderr**，可在终端中查看：

**Windows**：
```bash
# 前台运行（日志直接显示在终端）
python E:\opencode_mcp\wechat-opencode-bridge-main\wechat-mcp-server.py 2>&1 | tee gateway.log
```

**Linux**：
```bash
# 前台运行并保存日志
python3 wechat-mcp-server.py 2>&1 | tee gateway.log
```

### 方式二：查看 Daemon 日志

```bash
# 前台运行 daemon（日志直接显示）
wechat-mcp daemon
```

### 方式三：修改日志详细程度

编辑 `wechat-mcp-server.py`，在文件顶部添加 DEBUG 开关：

```python
# 在 wechat-mcp-server.py 文件头部添加（import 之后）
DEBUG = True  # 设置为 False 关闭详细日志

def log(msg: str):
    if DEBUG:
        print(f"[wechat-mcp-server] {msg}", flush=True, file=sys.stderr)
```

### DEBUG 日志包含的信息

- 自动发现的 OpenCode 端口号
- 复用的活跃 session ID 和 agent 类型
- 收到的微信消息内容（前 60 字符）
- 发送到 OpenCode 的消息状态
- 轮询等待回复的状态
- API 调用的异常信息

---

## 3. 工作目录（Workspace）：修改 Session 目录

### 问题背景

OpenCode REST API 创建的 session 默认工作目录是 `C:\Users\<用户名>`，但这**不是有效的 workspace**，导致 `prompt_async` 无法触发 AI 处理。

### 解决方案

`wechat-mcp-server.py` 已内置自动检测机制：会自动查找 OpenCode 前端**当前活跃**的 session（即你有实际 workspace 目录的 session），并复用该 session 来发送消息。

### 自动检测规则

网关会遍历所有 session，选择第一个满足以下条件的：
- `directory` 不为空
- `directory` 不是 `C:\Users\<用户名>`（Windows 默认路径）
- `directory` 不以 `Users/` 开头（非有效 workspace）

```python
# wechat-mcp-server.py 中的自动检测逻辑（_find_active_session 函数）
for s in sessions:
    directory = s.get("directory", "")
    if directory and directory != "C:\\Users\\8" and not directory.startswith("Users"):
        return s["id"], s.get("agent", "plan")
```

### 手动指定工作目录

如果需要强制使用特定 workspace，可通过 OpenCode 前端**先在该目录下打开一个会话**（例如用 OpenCode 打开 `E:\my_project`），然后启动网关。

### 验证当前工作目录

```bash
# 查看 gateway 的 stderr 输出，会显示：
[wechat-mcp-server] 找到活跃 session: ses_xxxx agent=plan dir=E:/my_project
```

也可以直接通过 OpenCode REST API 查看：
```bash
curl -u opencode:密码 http://localhost:<端口>/session
```

---

## 4. Agent 模式：plan 模式 vs build 模式

### 问题背景

OpenCode 有两种主要的 Agent 模式：
- **plan** — 先规划再执行（两阶段），适合复杂任务
- **build** — 直接执行（单阶段），适合简单任务

`prompt_async` API 的 `agent` 参数必须与 session 的当前 agent 类型**一致**，否则 AI 不会生成回复。

### 默认行为

`wechat-mcp-server.py` 通过 `get_agent_mode()` 函数统一获取 agent 模式，所有请求（创建 session、发送 prompt、自动检测 active session）都使用该函数。默认值在 `DEFAULT_CONFIG` 中定义为 **`"build"`**。

`get_agent_mode()` 的返回值优先级从高到低为：
1. `opencode-config.json` 中的 `agent.preferred`
2. 代码中 `DEFAULT_CONFIG` 的默认值（`"build"`）

> **重要**：v2.0 起，微信消息**不再跟随 OpenCode 前端 session 的 agent 模式**。无论前端在 plan 还是 build 模式，微信消息始终使用 `get_agent_mode()` 返回的统一模式。这避免了前端切换模式导致微信回复行为不一致的问题。

### 方式一：修改配置文件（推荐）

编辑 `opencode-config.json`（位于项目根目录），修改 `agent.preferred`：

```json
{
  "agent": {
    "preferred": "build"
  }
}
```

> **配置说明**：`opencode-config.json` 是 `wechat-mcp-server.py` 的本地配置文件，与 OpenCode 的 `opencode.json`（位于 `~/.config/opencode/`）不同。`opencode.json` 控制 OpenCode 的 MCP 服务器注册和环境变量，`opencode-config.json` 控制 bridge 自身的行为。

### 方式二：修改代码默认值（不推荐）

编辑 `wechat-mcp-server.py`，修改 `DEFAULT_CONFIG` 或 `get_agent_mode()` 函数：

```python
# 方式 2a: 修改 DEFAULT_CONFIG（约第 436 行）
"agent": {"preferred": "build"},  # plan=规划模式, build=执行模式

# 方式 2b: 修改 get_agent_mode() 的 fallback 值（约第 474 行）
def get_agent_mode() -> str:
    return config.get("agent", {}).get("preferred", "build")
```

### 方式三：通过环境变量指定

在启动网关时设置环境变量（暂未实现，需自行修改代码添加）：

```bash
# Windows
set WECHAT_AGENT=build && python wechat-mcp-server.py

# Linux
WECHAT_AGENT=build python3 wechat-mcp-server.py
```

### 方式三：通过 OpenCode 前端切换

直接在 OpenCode 前端将当前会话切换为 plan 或 build 模式，网关会自动检测并使用。

### 各模式适用场景

| 模式 | 特点 | 适用场景 |
|------|------|----------|
| `plan` | 先规划再执行，响应更详细 | 复杂任务、需要多步骤操作 |
| `build` | 直接执行，响应更快 | 简单问答、快速查询 |
| `explore` | 代码探索专用 | 代码分析、文件搜索 |

---

## 5. AI 模型及相关参数配置

### 方式一：通过环境变量配置（推荐）

在启动网关时设置环境变量：

**Windows**：
```batch
set WECHAT_MODEL_ID=DeepSeek-V4-Pro
set WECHAT_PROVIDER_ID=aedfewfwegfergertge
python E:\opencode_mcp\wechat-opencode-bridge-main\wechat-mcp-server.py
```

**Linux**：
```bash
export WECHAT_MODEL_ID=DeepSeek-V4-Pro
export WECHAT_PROVIDER_ID=aedfewfwegfergertge
python3 wechat-mcp-server.py
```

### 方式二：修改代码中的默认值

编辑 `wechat-mcp-server.py`，修改 `WECHAT_MODEL` 常量：

```python
# 在 wechat-mcp-server.py 中找到这一段（约第 108 行）
WECHAT_MODEL = {
    "modelID": os.environ.get("WECHAT_MODEL_ID", "DeepSeek-V4-Pro"),
    "providerID": os.environ.get("WECHAT_PROVIDER_ID", "aedfewfwegfergertge"),
}
```

修改 `"DeepSeek-V4-Pro"` 和 `"aedfewfwegfergertge"` 为你需要的模型和 provider。

### 方式三：在 opencode-config.json 中配置

```json
{
  "mcp": {
    "wechat": {
      "environment": {
        "WECHAT_MODEL_ID": "你的模型ID",
        "WECHAT_PROVIDER_ID": "你的Provider ID"
      }
    }
  }
}
```

### 查找可用的模型和 Provider

查看 OpenCode 当前配置中的 provider 列表：

```bash
# 通过 REST API 获取配置
curl -u opencode:密码 http://localhost:<端口>/config
```

返回的 JSON 中 `provider` 字段包含所有可用的 provider 及其模型：

```json
{
  "provider": {
    "aedfewfwegfergertge": {
      "name": "seferwferw4fergfert",
      "models": {
        "Kimi-K2.6": "",
        "glm-5": "",
        "glm-5.1": "",
        "DeepSeek-V4-Pro": ""
      }
    },
    "anthropic": {
      "npm": "@ai-sdk/anthropic",
      "models": {}
    }
  }
}
```

### 当前支持的模型参数

| 参数 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `WECHAT_MODEL_ID` | 模型 ID | `DeepSeek-V4-Pro` | `agnes-2.0-flash`, `gpt-5.5`, `glm-5.1` |
| `WECHAT_PROVIDER_ID` | Provider ID | `aedfewfwegfergertge` | `agnes`, `anthropic` |

### 完整配置参考

以下是所有可配置的环境变量（及其默认值）：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `OPENCODE_URL` | 自动发现 | OpenCode REST API 地址（通常无需手动设置） |
| `GATEWAY_PORT` | `4100` | HTTP 网关监听端口 |
| `WECHAT_MODEL_ID` | `DeepSeek-V4-Pro` | AI 模型 ID |
| `WECHAT_PROVIDER_ID` | `aedfewfwegfergertge` | AI Provider ID |
| `OPENCODE_SERVER_USERNAME` | 自动获取 | OpenCode API 用户名 |
| `OPENCODE_SERVER_PASSWORD` | 自动获取 | OpenCode API 密码 |

---

## 使用方式

### 微信快捷指令

在微信聊天中直接发送以下指令（Gateway 本地处理，不经过 AI）：

| 指令 | 说明 | 示例 |
|------|------|------|
| `/help` | 显示所有可用指令 | `/help` |
| `/status` | 查看系统状态（活跃会话数、当前模型等） | `/status` |
| `/reset` | 重置当前会话（清除对话历史） | `/reset yes` |
| `/model` | 显示当前 AI 模型和 Provider | `/model` |
| `/mode <模式>` | 切换对话模式 | `/mode coding` |
| `/search <关键词>` | 搜索网络（需在 config.json 中配置搜索后端） | `/search Python 教程` |

> **提示**: 如果要发送的字面文本以 `/` 开头，在消息前加空格即可绕过指令拦截（如 ` /help`）。

### 对话模式

通过 `/mode` 指令或配置文件切换对话模式：

| 模式 | 说明 |
|------|------|
| `default` | 正常模式，无特殊指令 |
| `coding` | 编程模式，回复简洁并优先提供可运行代码 |
| `translate` | 翻译模式，中英互译，只输出翻译结果 |

模式切换后，后续消息会自动附加对应的 system prompt 前缀。

### 发送微信消息

在 OpenCode 中使用 MCP 工具：

- `wechat_send(conversation_id, text)` — 向指定会话发送消息
- `wechat_conversations()` — 列出所有活跃会话
- `wechat_history(conversation_id, limit=20)` — 查看消息历史
- `wechat_setup(force=False)` — 触发微信扫码登录（Windows 弹窗）

### 微信中回复

用微信扫描登录时的 QR 码，即可开始与 bot 对话。发送的消息会自动路由到 OpenCode，回复会发回微信。

---

## 命令行参数

`wechat-mcp-server.py` 支持以下命令行参数：

```bash
python wechat-mcp-server.py [选项]

选项:
  --gateway-only          仅 HTTP 网关模式（不启动 MCP stdio）
  --opencode-url URL      手动指定 OpenCode REST API 地址（覆盖自动发现）
  --opencode-user USER    手动指定 API 用户名
  --opencode-pass PASS    手动指定 API 密码
```

示例：
```bash
# 手动指定所有参数
python wechat-mcp-server.py --opencode-url http://localhost:12345 --opencode-user opencode --opencode-pass mypassword
```

---

## 配置文件 `~/.wechat-mcp/config.json`

Gateway 支持通过配置文件自定义行为。配置文件位于 `~/.wechat-mcp/config.json`（Windows: `C:\Users\<用户名>\.wechat-mcp\config.json`）。

**如果文件不存在，Gateway 使用内置默认值运行，无需手动创建。**

### 完整配置示例

```json
{
  "sensitive_filter": {
    "enabled": true,
    "types": {
      "phone":     {"enabled": true, "replacement": "[手机号]"},
      "id_card":   {"enabled": true, "replacement": "[身份证号]"},
      "bank_card": {"enabled": true, "replacement": "[银行卡号]"},
      "email":     {"enabled": true, "replacement": "[邮箱]"},
      "ip_address":{"enabled": false, "replacement": "[IP地址]"},
      "address":   {"enabled": false, "replacement": "[地址]"}
    }
  },
  "session": {
    "ttl_hours": 24
  },
  "commands": {
    "enabled": true,
    "search": {
      "backend": "tavily",
      "api_key": "tvly-你的密钥",
      "timeout_seconds": 10
    }
  },
  "agent": {
    "preferred": "plan"
  },
  "modes": {
    "default":   {"system_prompt": "", "description": "正常模式"},
    "coding":    {"system_prompt": "你是编程专家。回答简洁，优先提供可运行的代码。", "description": "编程模式"},
    "translate": {"system_prompt": "你是翻译专家。中文翻译成英文，英文翻译成中文。只输出翻译结果。", "description": "翻译模式"}
  }
}
```

### 配置项说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `sensitive_filter.enabled` | `true` | 是否启用敏感信息脱敏 |
| `sensitive_filter.types.*.enabled` | 见示例 | 各类型独立开关 |
| `sensitive_filter.types.*.replacement` | 见示例 | 替换标签文本 |
| `session.ttl_hours` | `24` | 会话超时时间（小时），超时后自动清理 |
| `commands.enabled` | `true` | 是否启用快捷指令 |
| `commands.search.backend` | `""` | 搜索后端：`tavily` 或 `custom` |
| `commands.search.api_key` | `""` | Tavily API 密钥 |
| `agent.preferred` | `"plan"` | 优先使用的 Agent 模式：`plan`（对话优先）或 `build`（执行优先） |
| `modes` | 见示例 | 对话模式定义（可自定义添加新模式） |

> **注意**: 配置文件 JSON 格式错误时，Gateway 会使用默认值运行并在 stderr 输出警告。修改配置后需**重启 Gateway** 生效。

---

## 敏感信息脱敏

Gateway 内置正则脱敏引擎，在消息发送给 AI 之前自动替换敏感信息为标签：

| 类型 | 匹配规则 | 默认标签 | 默认状态 |
|------|----------|----------|----------|
| 手机号 | 11位 1[3-9] 开头，支持 `138-1234-5678` 格式 | `[手机号]` | 启用 |
| 身份证号 | 18位（含出生日期校验）+ 15位旧版 | `[身份证号]` | 启用 |
| 银行卡号 | 16-19位，支持 `6222 1234 5678 9012` 格式 | `[银行卡号]` | 启用 |
| 邮箱 | 标准 email 格式 | `[邮箱]` | 启用 |
| IP地址 | IPv4 格式 | `[IP地址]` | 关闭 |
| 地址 | 含2个以上地址关键词的句子 | `[地址]` | 关闭 |

脱敏是无状态的——敏感信息被替换为标签后**不会还原**。AI 回复中的标签会原样返回给微信用户。可通过 `config.json` 自定义替换标签或关闭特定类型。

---

## 架构说明

| 组件 | 技术栈 | 端口 | 说明 |
|------|--------|------|------|
| wechat-mcp daemon | Node.js | 动态 | 维护 iLink 长连接，轮询消息 |
| HTTP Gateway | Python aiohttp | 4100 | 接收 daemon claw 请求，调用 OpenCode API |
| MCP stdio | Python FastMCP | stdio | 暴露 wechat 工具给 OpenCode |
| OpenCode REST API | Go | 动态 | OpenCode 自身 API |

---

## 文件说明

- `wechat-mcp-server.py` — HTTP Gateway + MCP Server（核心组件）
- `sensitive_filter.py` — 敏感信息脱敏引擎（纯正则，无状态）
- `wechat-setup-gui.py` — Windows 图形化扫码登录工具（替代 `wechat-mcp setup`）
- `generate-share-qr.js` — 生成 bot 分享 QR 码的脚本
- `systemd/` — 三个 systemd 服务文件
- `opencode-config.json` — OpenCode MCP 配置示例
- `start-gateway.bat` — Windows 网关启动脚本（含环境变量）
- `wechat-setup.bat` — Windows 扫码登录快速启动脚本

---

## 故障排除

### 1. 消息发送后没有 AI 回复

**原因**：prompt_async 需要正确的 agent 和有效的 workspace。

**解决**：
- 确保 OpenCode 前端**有打开的 session**（在某个项目目录下）
- 检查 agent 模式是否匹配（网关会自动检测）
- 查看 gateway 日志确认是否找到活跃 session

### 2. 连接被拒绝 (Connection Refused)

**原因**：OpenCode REST API 端口变化或未启动。

**解决**：
- 网关已内置自动发现，重启网关即可
- 如果手动指定了端口，确保端口正确

### 3. 401 Unauthorized

**原因**：API 密码已过期或错误。

**解决**：
- 密码是动态的，重启 OpenCode 后会变化
- 网关已内置自动获取，重启网关即可
- 如果手动指定了密码，重新获取并更新

### 4. 消息未到达网关

**原因**：daemon 或 agent 未运行。

**解决**：
- 确保 `wechat-mcp daemon` 和 `wechat-mcp serve --agent opencode --mode gateway` 都在运行
- 检查微信 bot 是否已扫码登录

---

## 已知限制

- **仅支持 bot 创建者本人使用**：iLink ClawBot 协议设计为单人使用，无法分享给其他微信用户
- 群聊不支持
- QR 码会话 token 约 90 秒过期
- 仅文本消息（图片/文件等需要 weixin-mcp 扩展）
- Bot session 有过期时间，需要定期重新扫码登录
- 敏感信息脱敏为无状态替换（不还原），AI 回复中可能包含替换标签
- 会话超时清理默认 24 小时，可通过 `config.json` 修改

## 相关项目

- [@paean-ai/wechat-mcp](https://github.com/paean-ai/wechat-mcp) — 底层 WeChat MCP 中间件
- [weixin-mcp](https://github.com/bkmashiro/weixin-mcp) — 另一个 WeChat MCP 实现（支持图片/文件）
- [cc-wechat](https://github.com/paceaitian/cc-wechat) — Claude Code 微信通道

## License

MIT
