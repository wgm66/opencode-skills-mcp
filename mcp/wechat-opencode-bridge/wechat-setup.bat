@echo off
REM ============================================================
REM   WeChat OpenCode Bridge - 微信扫码登录
REM ============================================================
REM   此脚本弹出微信扫码登录窗口
REM   支持参数: --force（强制重新登录）
REM ============================================================

setlocal
cd /d "%~dp0"

REM 自动查找 Python（优先使用 PATH 中的 python，其次使用指定路径）
where python >nul 2>&1
if %errorlevel% equ 0 (
    python wechat-setup-gui.py %*
) else (
    if exist "D:\python\python.exe" (
        D:\python\python.exe wechat-setup-gui.py %*
    ) else (
        echo 错误: 找不到 Python 解释器
        echo 请安装 Python 3.10+ 或修改本脚本中的 Python 路径
        pause
        exit /b 1
    )
)

endlocal
