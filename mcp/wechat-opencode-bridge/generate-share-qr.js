#!/usr/bin/env node
/**
 * 生成 WeChat bot 分享 QR 码
 *
 * 使用方法:
 *   node generate-share-qr.js
 *
 * QR 码约 90 秒内有效，生成后请尽快让朋友用微信扫描。
 * 过期后重新运行本脚本即可生成新的 QR 码。
 */

const fs = require("fs");
const path = require("path");
const http = require("https");

const CRED_FILE = path.join(process.env.HOME, ".wechat-mcp", "credentials.json");
const BASE = "https://ilinkai.weixin.qq.com";
const BOT_TYPE = "3";
const OUT_FILE = path.join(process.env.HOME, "wechat-bot-share.png");

async function main() {
  if (!fs.existsSync(CRED_FILE)) {
    console.error("错误：未找到凭据文件，请先运行 wechat-mcp setup");
    process.exit(1);
  }

  const cred = JSON.parse(fs.readFileSync(CRED_FILE, "utf8"));
  const auth = `Bearer ${cred.accountId}:${cred.token}`;

  console.log("正在生成分享 QR 码...");

  const url = `${cred.baseUrl || BASE}/ilink/bot/get_bot_qrcode?bot_type=${BOT_TYPE}`;
  const resp = await fetch(url, { headers: { Authorization: auth } });
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);

  const data = await resp.json();
  const qrUrl = data.qrcode_img_content;

  // 生成 PNG QR 码
  try {
    const QRCode = require("qrcode");
    await QRCode.toFile(OUT_FILE, qrUrl, {
      type: "png",
      width: 400,
      margin: 2,
      color: { dark: "#000", light: "#fff" },
    });
    console.log(`\nQR 码已保存: ${OUT_FILE}`);
  } catch (e) {
    console.log("(提示: npm install -g qrcode 可生成 PNG)");
  }

  // 终端 ASCII QR 码
  try {
    const qrterm = require("qrcode-terminal");
    console.log("\n=== 用微信扫描此 QR 码（90 秒内有效）===");
    qrterm.generate(qrUrl, { small: true });
  } catch (e) {
    /* ignore */
  }

  console.log(`\nURL: ${qrUrl}`);
  console.log("\n注意: QR 码约 90 秒后过期，请尽快扫描");
  console.log("      过期后重新运行本脚本即可生成新的 QR 码");
}

main().catch((err) => {
  console.error(`失败: ${err.message}`);
  process.exit(1);
});
