@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM   WeChat OpenCode Bridge - 一键启动所有服务
REM ============================================================
REM   此脚本按顺序启动:
REM     1. wechat-mcp daemon
REM     2. wechat-mcp-server.py (网关)
REM     3. wechat-mcp serve (agent)
REM ============================================================

cd /d "%~dp0"

set GATEWAY_PORT=4100
set WECHAT_MODEL_ID=DeepSeek-V4-Pro
set WECHAT_PROVIDER_ID=aedfewfwegfergertge

echo ============================================================
echo   WeChat OpenCode Bridge - Start All Services
echo ============================================================
echo.

REM ---- Step 1: 检查并清理旧进程 ----
echo [1/5] 清理旧进程...
call :stop_service wechat-mcp-server.py
call :stop_service wechat-mcp-daemon
echo.

REM ---- Step 2: 启动 wechat-mcp daemon ----
echo [2/5] 启动 wechat-mcp daemon...
where wechat-mcp >nul 2>&1
if %errorlevel% neq 0 (
    echo   错误: 找不到 wechat-mcp 命令，请先安装 wechat-mcp
    pause
    exit /b 1
)
start "WeChat-MCP-Daemon" cmd /c wechat-mcp daemon
echo    daemon 已启动 (后台窗口)
call :wait_min 2
echo.

REM ---- Step 3: 启动 wechat-mcp-server.py (网关) ----
echo [3/5] 启动 HTTP 网关...
start "WeChat-MCP-Gateway" cmd /c python wechat-mcp-server.py
echo    网关已启动 (端口 %GATEWAY_PORT%)
call :wait_min 3
echo.

REM ---- Step 4: 启动 wechat-mcp serve (agent) ----
echo [4/5] 启动 wechat-mcp agent...
start "WeChat-MCP-Agent" cmd /c wechat-mcp serve --agent opencode --mode gateway --gateway-url http://localhost:4100 --gateway-type claw
echo    agent 已启动 (后台窗口)
call :wait_min 2
echo.

REM ---- Step 5: 验证 ----
echo [5/5] 验证服务状态...
echo.

echo ============================================================
echo   启动完成!
echo   - wechat-mcp daemon:  后台运行
echo   - 网关 (gateway):     端口 %GATEWAY_PORT%
echo   - agent (serve):      后台运行
echo ============================================================
echo.
echo   按任意键关闭此窗口 (服务将继续在后台运行)
pause >nul
exit /b 0

REM ============================================================
REM   辅助函数
REM ============================================================

:stop_service
set _name=%~1
tasklist /fi "WINDOWTITLE eq %_name%*" 2>nul | find /i "%_name%" >nul
if %errorlevel% equ 0 (
    echo   正在停止 %_name% ...
    taskkill /fi "WINDOWTITLE eq %_name%*" /f >nul 2>&1
)
for /f "tokens=2" %%p in ('tasklist /fi "IMAGENAME eq python.exe" /fo csv /nh 2^>nul ^| findstr /i "%_name%"') do (
    echo   正在停止 PID %%p (%_name%) ...
    taskkill /pid %%p /f >nul 2>&1
)
exit /b 0

:wait_min
set _secs=%1
timeout /t %_secs% /nobreak >nul
exit /b 0
