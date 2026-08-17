@echo off
set GATEWAY_PORT=4100
set WECHAT_MODEL_ID=DeepSeek-V4-Pro
set WECHAT_PROVIDER_ID=aedfewfwegfergertge
D:\python\python.exe "E:\opencode_mcp\wechat-opencode-bridge-main\wechat-mcp-server.py" --gateway-only 2>&1
