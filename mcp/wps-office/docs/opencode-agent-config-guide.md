# OpenCode 智能体模型配置经验文档

> 编制日期: 2026-07-02
> 涉及项目: oh-my-openagent (v4.13.0) + WPS Office 插件
> 工作区: G:\opencode_mcp

---

## 1. 背景

用户拥有以下 AI Provider：
- **dsefcwe** (GLLLLL) — 自定义 API 网关 `https://www.alan.plus/gateway/coding/v1`，提供 `GLM-5.2`
- **opencode** — OpenCode 内置 Provider，含免费模型 `mimo-v2.5-free`
- ~~Agnes AI~~ — 不可用，已移除

## 2. 配置文件体系

### 2.1 文件位置

| 文件 | 路径 | 作用 |
|------|------|------|
| `opencode.jsonc` | `~/.config/opencode/opencode.jsonc` | 主配置（provider、MCP、默认模型） |
| `opencode.json` | `~/.config/opencode/opencode.json` | 旧版配置（合并到 jsonc） |
| `oh-my-openagent.json` | `~/.config/opencode/oh-my-openagent.json` | 插件配置（agent/category 模型） |
| 项目级配置 | `<project>/.opencode/opencode.jsonc` | 遍历合并，closer wins |

### 2.2 模型分配结构

**`opencode.jsonc`** — 定义 provider 和默认模型：
```jsonc
{
  "model": "dsefcwe/GLM-5.2",
  "provider": {
    "dsefcwe": {
      "name": "GLLLLL",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://www.alan.plus/gateway/coding/v1"
      },
      "models": {
        "GLM-5.2": { "name": "GLM-5.2" }
      }
    }
  }
}
```

**`oh-my-openagent.json`** — 定义 agent / category 模型覆盖：
```jsonc
{
  "agents": {
    "hephaestus": { "model": "..." },
    // 每个 agent 可独立设置模型
  },
  "categories": {
    "quick": { "model": "opencode/mimo-v2.5-free" },
    // 8 个 category 独立设置
  }
}
```

### 2.3 模型解析优先级（高→低）

1. UI 选择的模型（仅 primary agent）
2. User config model（opencode.jsonc 的 model 字段）
3. Category default（oh-my-openagent.json 的 categories 配置）
4. Provider fallback（AGENT_MODEL_REQUIREMENTS 内置链）
5. System default

## 3. oh-my-openagent 11 个 Agent（来源: model-core）

| Agent | 角色 | 推荐模型 |
|-------|------|---------|
| **Sisyphus** | 主编排器 | claude-opus-4-7 / kimi-k2.6 / glm-5 |
| **Hephaestus** | 自主深度工作 | gpt-5.5（硬性 OpenAI） |
| **Oracle** | 架构/调试 | gpt-5.5 / claude-opus-4-7 |
| **Prometheus** | 战略规划 | claude-opus-4-7 / gpt-5.5 / glm-5.1 |
| **Metis** | 预规划顾问 | claude-sonnet-4-6 / claude-opus-4-7 |
| **Momus** | 计划评审 | gpt-5.5 xhigh / claude-opus-4-7 |
| **Atlas** | 持续工作 | claude-sonnet-4-6 / kimi-k2.6 |
| **Sisyphus-Junior** | 聚焦执行 | claude-sonnet-4-6 / kimi-k2.6 |
| **Librarian** | 文档/代码搜索 | gpt-5.4-mini-fast / claude-haiku-4-5 |
| **Explore** | 代码搜索 | gpt-5.4-mini-fast / claude-haiku-4-5 |
| **Multimodal-Looker** | 图片/PDF 分析 | gpt-5.5 / kimi-k2.6 |

## 4. 8 个 Category

| Category | 用途 |
|----------|------|
| `visual-engineering` | 前端、UI/UX、设计、动画 |
| `ultrabrain` | 高难度逻辑、架构决策 |
| `deep` | 自主研究+端到端实现 |
| `artistry` | 创造性问题解决 |
| `quick` | 单文件改动、简单修改 |
| `unspecified-low` | 低复杂度杂项 |
| `unspecified-high` | 高复杂度杂项 |
| `writing` | 文档、技术写作 |

## 5. 关键操作记录

### 5.1 移除 Provider

1. 修改 `"model"` 字段指向现有 provider（否则默认模型会指向不存在的 provider）
2. 删除整个 provider 配置块

```jsonc
// 修改前
"model": "agnes/agnes-2.0-flash",
"provider": { "agnes": { ... }, "dsefcwe": { ... } }

// 修改后
"model": "dsefcwe/GLM-5.2",
"provider": { "dsefcwe": { ... } }
```

### 5.2 模型命名格式

完整引用: **`<providerID>/<modelID>`**

示例: `dsefcwe/GLM-5.2`、`opencode/mimo-v2.5-free`、`opencode/gpt-5-nano`

### 5.3 OpenCode 内置 Provider 可用免费模型

通过 `opencode/` provider 可用（无需额外订阅）：
- `opencode/mimo-v2.5-free` ✅ 已验证可用
- `opencode/gpt-5-nano`
- `opencode/big-pickle`

需 OpenCode Zen 订阅的模型：
- `opencode/claude-opus-4-7`、`opencode/gpt-5.5`、`opencode/glm-5` 等

### 5.4 查询实际使用的模型

查看 OpenCode 日志：
```bash
# ~/.local/share/opencode/log/opencode.log
# 搜索 providerID= 和 modelID=
```

内置链定义：
```
packages/model-core/src/agent-model-requirements.ts
packages/model-core/src/category-model-requirements.ts
```

### 5.5 修改配置后必须重启

方式一：Launcher API
```
POST http://127.0.0.1:14097/stop
POST http://127.0.0.1:14097/start
```

方式二：直接进程管理
```powershell
Get-Process opencode | Stop-Process
# 然后重新启动 opencode serve 或 Launcher
```

### 5.6 模型分配建议

- 强推理（Sisyphus、Oracle、Prometheus）→ 用最好的模型（Opus / GLM-5.2 / GPT-5.5）
- 深度工作（Hephaestus）→ 需要 gpt-5.5 或等效
- 轻量搜索（Librarian、Explore）→ 可用免费/快速模型
- 子任务 categories → 根据复杂度分配，快速任务用免费模型

## 6. 本次变更结果

### 变更内容

| 变更项 | 旧值 | 新值 |
|--------|------|------|
| 默认模型 | `agnes/agnes-2.0-flash` | `dsefcwe/GLM-5.2` |
| Provider | agnes + dsefcwe | 仅 dsefcwe |
| Categories (8个) | `opencode/gpt-5-nano` | `opencode/mimo-v2.5-free` |
| Agents (10个) | `opencode/gpt-5-nano` | 不动 |
| WPS/WeChat/Tavily MCP | 存在 | 不变 |

### 验证结果

分类为 `quick` 的子任务成功使用 `opencode/mimo-v2.5-free` 运行 ✅
主 agent 使用 `dsefcwe/GLM-5.2` ✅
