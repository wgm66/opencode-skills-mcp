@echo off
REM ============================================================
REM   WeChat OpenCode Bridge - 网关启动脚本
REM ============================================================
REM   此脚本启动 HTTP 网关（wechat-mcp-server.py）
REM   网关将自动发现 OpenCode REST API 的端口和凭据
REM   如需自定义配置，修改下方的环境变量
REM ============================================================

REM ---- 基本配置 ----
REM HTTP 网关监听端口（默认 4100，一般无需修改）
set GATEWAY_PORT=4100

REM ---- AI 模型配置 ----
REM 模型 ID：DeepSeek-V4-Pro, agnes-2.0-flash, gpt-5.5, glm-5.1 等
set WECHAT_MODEL_ID=DeepSeek-V4-Pro

REM Provider ID：aedfewfwegfergertge, agnes, anthropic 等
set WECHAT_PROVIDER_ID=aedfewfwegfergertge

REM ---- 手动覆盖（通常无需设置，留空即可） ----
REM OpenCode REST API 地址（留空 = 自动发现）
REM set OPENCODE_URL=http://localhost:4096

REM API 用户名（留空 = 自动从环境变量获取）
REM set OPENCODE_SERVER_USERNAME=opencode

REM API 密码（留空 = 自动从环境变量获取）
REM set OPENCODE_SERVER_PASSWORD=

REM ---- 启动网关 ----
echo.
echo ============================================================
echo   WeChat OpenCode Bridge - HTTP Gateway
echo ============================================================
echo   端口: %GATEWAY_PORT%
echo   模型: %WECHAT_MODEL_ID% / %WECHAT_PROVIDER_ID%
echo   日志输出到 stderr（可在终端查看）
echo ============================================================
echo.

cd /d "%~dp0"
python wechat-mcp-server.py
