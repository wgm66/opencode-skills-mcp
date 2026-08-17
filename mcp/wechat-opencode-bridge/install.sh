#!/usr/bin/env bash
set -euo pipefail

echo "=== WeChat ↔ OpenCode Bridge 安装脚本 ==="
echo ""

# 1. 安装 wechat-mcp
echo "[1/5] 安装 @paean-ai/wechat-mcp..."
npm install -g @paean-ai/wechat-mcp

# 2. 安装 Python 依赖
echo "[2/5] 安装 Python 依赖..."
pip3 install aiohttp fastmcp mcp --break-system-packages -q 2>/dev/null || \
pip3 install aiohttp fastmcp mcp -q

# 3. 复制项目文件
echo "[3/5] 复制项目文件..."
REPO_DIR="/opt/wechat-opencode-bridge"
if [ ! -d "$REPO_DIR" ]; then
    sudo mkdir -p "$REPO_DIR"
    sudo cp wechat-mcp-server.py generate-share-qr.js "$REPO_DIR/"
    sudo cp -r systemd "$REPO_DIR/"
    sudo cp opencode-config.json "$REPO_DIR/"
fi

# 替换占位符 YOUR_USER
CURRENT_USER=$(whoami)
for f in "$REPO_DIR"/systemd/*.service; do
    sudo sed -i "s/YOUR_USER/$CURRENT_USER/g" "$f"
done

# 4. 配置 systemd 服务
echo "[4/5] 配置 systemd 服务..."
mkdir -p ~/.config/systemd/user/
cp "$REPO_DIR"/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload

echo ""
echo "[5/5] 微信扫码登录"
echo "运行以下命令完成微信绑定:"
echo "  wechat-mcp setup"
echo ""
echo "安装完成！启动服务:"
echo "  systemctl --user enable --now wechat-mcp-daemon.service"
echo "  systemctl --user enable --now wechat-opencode-adapter.service"
echo "  systemctl --user enable --now wechat-mcp-agent.service"
echo "  sudo loginctl enable-linger $(whoami)"
