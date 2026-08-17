# 架构文档

## 系统架构

```
                    ┌─────────────────────────────────────────┐
                    │           微信 (WeChat)                  │
                    │  ┌─────────────┐  ┌──────────────────┐  │
                    │  │ 个人微信     │  │ ClawBot liteapp  │  │
                    │  │ (bot owner)  │  │ (非 owner 用户)  │  │
                    │  └──────┬──────┘  └────────┬─────────┘  │
                    └─────────┼──────────────────┼────────────┘
                              │         (不支持)
                    ┌─────────▼──────────────────┘
                    │      iLink API (ilinkai.weixin.qq.com)
                    │      ┌─────────────────────────────┐
                    │      │  /ilink/bot/getupdates       │
                    │      │  /ilink/bot/sendmessage      │
                    │      │  /ilink/bot/get_bot_qrcode   │
                    │      └────────────┬────────────────┘
                    └──────────────────┼────────────────────┘
                                       │
              ┌────────────────────────┴────────────────────────┐
              │              wechat-mcp daemon                   │
              │  - 长轮询 getupdates (~35s)                      │
              │  - 消息路由 (按 @mention)                        │
              │  - Gateway bridge (POST → agent HTTP endpoint)  │
              │  - 回复发送 (sendmessage)                        │
              └────────────────────────┬────────────────────────┘
                                       │ HTTP IPC (127.0.0.1:动态端口)
                                       │ claw SSE 协议
              ┌────────────────────────┴────────────────────────┐
              │          wechat-mcp-server.py (本组件)            │
              │                                                  │
               │  ┌─────────────────┐  ┌──────────────────────┐   │
               │  │ HTTP Gateway    │  │ MCP stdio Server     │   │
               │  │ port 4100       │  │ (FastMCP)            │   │
               │  │                 │  │                      │   │
               │  │ POST /api/chat  │  │ wechat_send          │   │
               │  │ GET /health     │  │ wechat_conversations │   │
               │  │ GET /share-qr   │  │ wechat_history       │   │
               │  │                 │  │ wechat_setup         │   │
               │  └────────┬────────┘  └──────────────────────┘   │
               │           │                                      │
               │  ┌────────┴────────┐                             │
               │  │  预处理管道      │                             │
               │  │  - 敏感信息脱敏  │                             │
               │  │  - 快捷指令拦截  │                             │
               │  │  - 模式前缀注入  │                             │
               │  └────────┬────────┘                             │
               └───────────┼──────────────────────────────────────┘
                           │ OpenCode REST API (动态端口)
               ┌───────────▼──────────────────────────────────────┐
               │              OpenCode                             │
               │  - REST API: /session, /prompt_async, /message   │
               │  - MCP 客户端: 加载 wechat MCP 工具              │
              └──────────────────────────────────────────────────┘
```

## 消息流程

### 入站（微信 → OpenCode）

```
1. 用户在微信中发送消息给 bot
2. iLink API 接收消息，排队等待轮询
3. wechat-mcp daemon getUpdates 轮询拉取到消息
4. daemon 解析消息，提取文本和 senderId
5. daemon 保存联系人信息到 contacts.json
6. daemon 根据 @mention 路由到对应 agent
7. agent 模式为 gateway → 调用 bridgeToGateway()
8. bridgeToGateway POST 到 http://localhost:4100/api/chat
9. wechat-mcp-server.py 解析 claw SSE 请求
10. **预处理管道**: 快捷指令拦截 → 敏感信息脱敏 → 模式前缀注入
11. 自动发现 OpenCode REST API 端口和凭据
12. 自动查找当前活跃 session（有有效 workspace 的）
13. 复用活跃 session，调用 POST /session/{id}/prompt_async
14. 轮询等待 AI 回复完成
14. 读取 OpenCode 回复消息
15. 以 SSE 格式返回给 daemon (start→content→done)
16. daemon 收到完整回复后调用 sendTextMessage()
17. iLink API 将消息发送回微信用户
```

### 出站（OpenCode → 微信）

```
1. OpenCode 中调用 MCP 工具 wechat_send(conv_id, text)
2. wechat-mcp-server.py 调用 OpenCode REST API 处理消息
3. 获取回复后调用 daemon 的 HTTP API 发送
4. daemon 调用 iLink sendmessage API
5. 微信用户收到消息
```

## 自动发现机制

### OpenCode REST API 端口

`wechat-mcp-server.py` 在启动时自动执行以下步骤：

1. **命令行参数** — 检查 `--opencode-url` 参数
2. **环境变量** — 检查 `OPENCODE_URL` 环境变量
3. **自动发现** — 通过 `netstat` 查找 OpenCode 进程监听的 127.0.0.1 端口
4. **默认值** — 使用 `http://localhost:4096`

```python
# 自动发现逻辑（_find_opencode_port 函数）
# Windows: 通过 Get-Process + netstat 查找
# Linux: 通过 ss -tlnp 查找
```

### OpenCode API 凭据

1. **命令行参数** — 检查 `--opencode-user` 和 `--opencode-pass`
2. **环境变量** — 检查 `OPENCODE_SERVER_USERNAME` 和 `OPENCODE_SERVER_PASSWORD`
3. **默认值** — 用户名 `opencode`，密码为空

### 活跃 Session 复用

`wechat-mcp-server.py` 不会创建新 session，而是**复用** OpenCode 前端当前活跃的 session：

1. 遍历所有 session，找第一个 `directory` 有效的
2. 排除 `C:\Users\<用户名>` 和 `Users/` 开头的无效路径
3. 获取该 session 的 `agent` 类型（plan/build/explore）
4. 所有微信消息都发送到该 session

## 关键数据结构

### contacts.json
```json
[{
  "userId": "o9cq806j8t4...@im.wechat",
  "contextToken": "AARzJWAFAAABAAAAAAA...",
  "lastSeen": "2026-05-13T12:28:46.488Z",
  "displayName": "user_nickname"
}]
```

### adapter-sessions.json
```json
{
  "629fc298": "ses_1dec2ab94ffeHmOJRc6G7Fuaps"
}
```

### credentials.json
```json
{
  "accountId": "232fef6283ce@im.bot",
  "token": "0600009e27375c87fd4f6c8dfc52fd141af06a",
  "baseUrl": "https://ilinkai.weixin.qq.com",
  "savedAt": "2026-05-13T11:51:13.537Z"
}
```

## 可配置参数

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `OPENCODE_URL` | 自动发现 | OpenCode REST API 地址 |
| `GATEWAY_PORT` | `4100` | HTTP 网关监听端口 |
| `WECHAT_MODEL_ID` | `DeepSeek-V4-Pro` | AI 模型 ID |
| `WECHAT_PROVIDER_ID` | `aedfewfwegfergertge` | AI Provider ID |
| `OPENCODE_SERVER_USERNAME` | 自动获取 | API 用户名 |
| `OPENCODE_SERVER_PASSWORD` | 自动获取 | API 密码 |

### 配置文件 config.json

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `agent.preferred` | `"plan"` | 优先 Agent 模式：`plan`(对话优先) 或 `build`(执行优先) |
| `session.ttl_hours` | `24` | 会话超时清理时间 |
| `sensitive_filter.enabled` | `true` | 是否启用敏感信息脱敏 |
| `commands.enabled` | `true` | 是否启用微信快捷指令 |

详细配置见 [README 配置文件章节](README.md#配置文件-wechat-mcpconfigjson)。

### 命令行参数

```bash
python wechat-mcp-server.py [选项]

选项:
  --gateway-only          仅 HTTP 网关模式
  --opencode-url URL      手动指定 API 地址
  --opencode-user USER    手动指定用户名
  --opencode-pass PASS    手动指定密码
```

### 代码级配置

编辑 `wechat-mcp-server.py` 中的以下常量：

```python
# Agent 模式（约第 138 行）
_active_session_agent: str = "plan"  # 改为 "build" 使用 build 模式

# AI 模型（约第 108 行）
WECHAT_MODEL = {
    "modelID": "DeepSeek-V4-Pro",
    "providerID": "aedfewfwegfergertge",
}

# DEBUG 模式（约第 47 行，需自行添加）
DEBUG = True  # 开启详细日志
```

## 已知限制

| 限制 | 原因 |
|------|------|
| 仅 bot owner 可用 | iLink ClawBot 协议设计 |
| 群聊不支持 | daemon 仅处理 MSG_TYPE_USER (1) |
| QR 码 90 秒过期 | iLink 安全设计 |
| 仅文本消息 | 基础实现，可扩展 weixin-mcp 支持多媒体 |
| 会话操作串行化 | 已用 conversation_locks + session_locks 双层锁解决并发 |
| Bot session 有过期时间 | 需定期重新扫码登录 |
| prompt_async 需 agent 匹配 | session 的 agent 必须与 prompt_async 参数一致 |
| 敏感信息脱敏无状态 | 替换标签不还原，AI 回复中可能包含标签 |

## 并发控制

`wechat-mcp-server.py` 使用两级锁保证数据一致性：

1. **conversation_locks** — 按微信 conversation ID 隔离，同一会话串行处理
2. **session_locks** — 按 OpenCode session ID 隔离，防止同一 session 的并发 prompt_async
3. **save_history_lock** — 保护消息历史文件的并发写入
4. **递归检测** — `wechat_send` 检测到 conversation 锁被持有时返回错误，防止循环调用

## 技术栈

| 组件 | 技术 | 端口 |
|------|------|------|
| wechat-mcp daemon | Node.js | 动态 |
| HTTP Gateway | Python aiohttp | 4100 |
| MCP Server | Python FastMCP | stdio |
| OpenCode API | Go | 动态 |
