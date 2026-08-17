# OpenCode Skills & MCP

自建的 OpenCode 多模态能力扩展：一个多模态委托 skill + 两个自建 MCP 服务器。

## 目录结构

```
opencode-skills-mcp/
├── skills/
│   └── multimodal-delegation/          # 多模态任务委托 skill
│       ├── SKILL.md                     # 技能定义（委托协议 + 使用流程）
│       └── scripts/
│           └── pdf_to_images.py         # PDF → PNG 栅格化脚本
└── mcp/
    ├── wps-office/                      # WPS Office MCP（Word/Excel/PPT 操控）
    └── wechat-opencode-bridge/          # 微信 OpenCode 桥接 MCP
```

## skills/multimodal-delegation

当任务涉及图片、视频、PDF 等多模态内容时，通过主 agent 的 `look_at` 工具委托给 `multimodal-looker` 子智能体（`cloud-ai/qwen-3.7-plus` 视觉模型）处理。

**支持能力（实测）：**

| 格式 | 方式 | 状态 |
|------|------|------|
| 图片（png/jpg/webp/gif/bmp/tiff） | 直接 `look_at` | ✅ 可用 |
| PDF | 先转 PNG 再 `look_at` | ✅ 可用（见下） |
| 视频 | 需 ffmpeg 抽帧 | ⚠️ 后端不支持直接输入 |
| 音频 | 需转写工具 | ⚠️ 后端不支持直接输入 |

**PDF 处理流程：** `look_at` 直接传 `.pdf` 会失败（OpenAI-compatible 后端不接受 `application/pdf` file part），必须先栅格化成图片：

```bash
python skills/multimodal-delegation/scripts/pdf_to_images.py <input.pdf> --outdir <输出目录> --dpi 144
```

然后对每页 PNG 调用 `look_at(file_path="...page_1.png", goal="...")`。

## mcp/wps-office

WPS Office MCP 服务器，通过自然语言操控 Word/Excel/PPT（公式、数据清洗、图表、排版、母版等）。

- 依赖：`node`、WPS Office 客户端
- 入口：`dist/index.js`（`node_modules` 需 `npm install`）

## mcp/wechat-opencode-bridge

微信 OpenCode 桥接 MCP，将 OpenCode 接入微信消息通道。

- 依赖：`D:\python\python.exe`（Python 3）
- 入口：`wechat-mcp-server.py`（配合 `run-gateway.bat` / `start-all.bat`）

## License

各子模块遵循其原始许可证（见各自目录内 LICENSE 文件）。
