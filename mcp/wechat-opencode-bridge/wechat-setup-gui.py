#!/usr/bin/env python3
"""
WeChat Setup GUI — Windows 二维码图片登录窗口

替代 `wechat-mcp setup`，在 Windows 下弹出原生窗口显示二维码图片，
大幅提升手机扫描成功率。凭证保存位置与 wechat-mcp 完全兼容。

模式:
  py wechat-setup-gui.py              交互模式（终端输入 + GUI 弹窗）
  py wechat-setup-gui.py --json-output JSON 模式（供子进程调用，输出 JSON）

依赖: pip install qrcode Pillow
"""

import sys
import json
import time
import urllib.parse
from pathlib import Path
from datetime import datetime

import qrcode
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

import urllib.request
import urllib.error

# ── 常量 (与 @paean-ai/wechat-mcp 一致) ──
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
BOT_TYPE = "3"
QR_LOGIN_TIMEOUT_MS = 480_000  # 8 分钟
QR_POLL_TIMEOUT_MS = 35_000    # 35 秒/次
CONFIG_DIR = Path.home() / ".wechat-mcp"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
SETUP_RESULT_FILE = CONFIG_DIR / "setup-result.json"


class SetupGUI:
    def __init__(self, force: bool = False, json_output: bool = False):
        self.force = force
        self.json_output = json_output
        self.qrcode_value = ""
        self.running = True
        self.scanned = False

    # ── API 调用 ──

    def _api_get(self, url: str, headers: dict | None = None, timeout: float = 35) -> dict:
        req = urllib.request.Request(url, headers=headers or {})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))

    def fetch_qr(self) -> dict:
        url = f"{DEFAULT_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"
        return self._api_get(url)

    def poll_status(self, qrcode: str) -> dict:
        encoded = urllib.parse.quote(qrcode, safe="")
        url = f"{DEFAULT_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={encoded}"
        headers = {"iLink-App-ClientVersion": "1"}
        return self._api_get(url, headers=headers, timeout=QR_POLL_TIMEOUT_MS / 1000)

    # ── 凭证管理 ──

    def load_credentials(self) -> dict | None:
        if CREDENTIALS_FILE.exists():
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def save_credentials(self, account: dict):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(account, f, indent=2, ensure_ascii=False)

    # ── 二维码生成 ──

    def make_qr_pil_image(self, content: str) -> Image.Image:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img.resize((350, 350), Image.LANCZOS)

    # ── 交互模式 ──

    def ask_reauth(self) -> bool:
        existing = self.load_credentials()
        if existing and not self.force:
            print(f"Existing WeChat account: {existing.get('accountId', 'unknown')}")
            print(f"Saved at: {existing.get('savedAt', 'unknown')}")
            print()
            try:
                answer = input("Re-authenticate? (y/N) ")
                return answer.strip().lower() == "y"
            except (EOFError, KeyboardInterrupt):
                print()
                return False
        return True

    def run(self):
        if not self.ask_reauth():
            print("Keeping existing credentials.")
            return

        print("Fetching WeChat login QR code...")

        qr_resp = self.fetch_qr()
        self.qrcode_value = qr_resp["qrcode"]
        qr_content = qr_resp["qrcode_img_content"]

        qr_pil_image = self.make_qr_pil_image(qr_content)
        self._build_window(qr_pil_image)

        self.window.after(500, self._poll_loop)
        self.window.mainloop()

    def _build_window(self, qr_pil_image: Image.Image):
        self.window = tk.Tk()
        self.window.title("微信扫码登录")
        self.window.resizable(False, False)

        self.window.update_idletasks()
        w, h = 400, 480
        x = (self.window.winfo_screenwidth() - w) // 2
        y = (self.window.winfo_screenheight() - h) // 2
        self.window.geometry(f"{w}x{h}+{x}+{y}")

        qr_photo = ImageTk.PhotoImage(qr_pil_image)
        qr_label = tk.Label(self.window, image=qr_photo)
        qr_label.image = qr_photo
        qr_label.pack(pady=(15, 5))

        self.status_label = tk.Label(
            self.window,
            text="请用微信扫一扫",
            font=("Microsoft YaHei", 12),
            fg="#333333",
        )
        self.status_label.pack(pady=(5, 10))

        self.progress_label = tk.Label(
            self.window,
            text="等待扫码...",
            font=("Microsoft YaHei", 9),
            fg="#888888",
        )
        self.progress_label.pack(pady=(0, 5))

    def _poll_loop(self):
        if not self.running:
            return

        try:
            status = self.poll_status(self.qrcode_value)
            s = status.get("status", "wait")

            if s == "wait":
                print(".", end="", flush=True)
                self.progress_label.config(text="等待扫码...")
                self.window.after(1000, self._poll_loop)

            elif s == "scaned":
                if not self.scanned:
                    self.scanned = True
                    print("\nScanned! Please confirm on your phone...")
                    self.status_label.config(text="已扫描", fg="#e67e22")
                    self.progress_label.config(text="请在手机上确认登录...")
                self.window.after(1000, self._poll_loop)

            elif s == "expired":
                print("\nQR code expired. Please run setup again.")
                self.running = False
                self.progress_label.config(text="二维码已过期，请重新运行", fg="#e74c3c")
                messagebox.showerror("登录失败", "二维码已过期，请重新运行 wechat-setup-gui.py")
                self.window.after(500, self.window.destroy)

            elif s == "confirmed":
                if not status.get("ilink_bot_id") or not status.get("bot_token"):
                    print("\nLogin failed: server did not return complete info.")
                    self.running = False
                    messagebox.showerror("登录失败", "登录失败：服务器未返回完整信息")
                    self.window.after(500, self.window.destroy)
                    return

                account = {
                    "token": status["bot_token"],
                    "baseUrl": status.get("baseurl", DEFAULT_BASE_URL),
                    "accountId": status["ilink_bot_id"],
                    "userId": status.get("ilink_user_id"),
                    "savedAt": datetime.now().isoformat(),
                }
                self.save_credentials(account)

                print("\n\nWeChat connected successfully!")
                print(f"  Account ID: {account['accountId']}")
                print(f"  User ID:    {account.get('userId', 'N/A')}")

                self.running = False
                self.status_label.config(text="登录成功！", fg="#27ae60")
                self.progress_label.config(text="凭证已保存至 " + str(CREDENTIALS_FILE))
                self.window.after(1500, self.window.destroy)

        except Exception as e:
            print(f"\n[poll error] {e}")
            self.progress_label.config(text=f"网络错误: {e}", fg="#e74c3c")
            self.window.after(2000, self._poll_loop)

    # ── JSON 输出模式（供 MCP 子进程调用） ──

    def run_json_mode(self):
        """静默模式：所有结果以 JSON 输出到 stdout，不输出任何其他内容。"""
        existing = self.load_credentials()
        if existing and not self.force:
            print(json.dumps({
                "success": True,
                "skipped": True,
                "message": "已有有效凭证，无需重新登录",
                "accountId": existing.get("accountId"),
                "userId": existing.get("userId"),
            }))
            return

        qr_resp = self.fetch_qr()
        self.qrcode_value = qr_resp["qrcode"]
        qr_content = qr_resp["qrcode_img_content"]

        qr_pil_image = self.make_qr_pil_image(qr_content)
        self._build_window(qr_pil_image)

        result = self._poll_loop_json()

        self.window.destroy()

        if result is None:
            result = {"success": False, "error": "unknown_error"}
        self._write_result_file(result)
        if "error" in result:
            print(json.dumps(result))
            sys.exit(1)
        else:
            print(json.dumps(result))

    def _write_result_file(self, result: dict):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(SETUP_RESULT_FILE, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception:
            pass

    def _poll_loop_json(self) -> dict | None:
        """同步轮询扫码状态，返回结果 dict 或 None。期间保持 tkinter GUI 响应。"""
        deadline = time.time() + QR_LOGIN_TIMEOUT_MS / 1000

        while time.time() < deadline:
            self.window.update()

            try:
                status = self.poll_status(self.qrcode_value)
            except Exception:
                time.sleep(1)
                continue

            s = status.get("status", "wait")

            if s == "wait":
                self.progress_label.config(text="等待扫码...")

            elif s == "scaned":
                self.status_label.config(text="已扫描", fg="#e67e22")
                self.progress_label.config(text="请在手机上确认登录...")

            elif s == "expired":
                return {
                    "success": False,
                    "error": "qr_expired",
                    "message": "二维码已过期，请重新运行",
                }

            elif s == "confirmed":
                if not status.get("ilink_bot_id") or not status.get("bot_token"):
                    return {
                        "success": False,
                        "error": "incomplete_response",
                        "message": "服务器未返回完整登录信息",
                    }

                account = {
                    "token": status["bot_token"],
                    "baseUrl": status.get("baseurl", DEFAULT_BASE_URL),
                    "accountId": status["ilink_bot_id"],
                    "userId": status.get("ilink_user_id"),
                    "savedAt": datetime.now().isoformat(),
                }
                self.save_credentials(account)

                self.status_label.config(text="登录成功！", fg="#27ae60")
                self.progress_label.config(
                    text="凭证已保存至 " + str(CREDENTIALS_FILE)
                )
                self.window.update()
                time.sleep(1.5)

                return {
                    "success": True,
                    "accountId": account["accountId"],
                    "userId": account.get("userId"),
                    "message": "微信登录成功",
                }

            time.sleep(1)

        return {
            "success": False,
            "error": "timeout",
            "message": "登录超时，请重新运行",
        }


def main():
    # 检查依赖
    try:
        import qrcode  # noqa: F811
        import PIL.Image  # noqa: F811
    except ImportError as e:
        print(f"缺少依赖: {e}")
        print("请运行: pip install qrcode Pillow")
        sys.exit(1)

    force = "--force" in sys.argv or "-f" in sys.argv
    json_output = "--json-output" in sys.argv

    gui = SetupGUI(force=force, json_output=json_output)

    try:
        if json_output:
            gui.run_json_mode()
        else:
            gui.run()
    except KeyboardInterrupt:
        if json_output:
            print(json.dumps({"success": False, "error": "cancelled", "message": "用户取消"}))
        else:
            print("\n已取消。")
        gui.running = False
        if hasattr(gui, "window"):
            gui.window.destroy()
    except Exception as e:
        if json_output:
            print(json.dumps({"success": False, "error": str(e)}))
            sys.exit(1)
        else:
            print(f"\n错误: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
