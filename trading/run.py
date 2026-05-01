"""
OKX 交易助手 - 启动脚本
"""
import sys
import os
import time
import webbrowser
import threading

from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.api.app import run


def open_browser(port: int, delay: float = 1.5):
    """延迟打开浏览器 (等服务启动完成)"""
    time.sleep(delay)
    webbrowser.open(f"http://localhost:{port}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else 8888
    no_browser = "--no-browser" in sys.argv

    print("=" * 45)
    print("  OKX 交易助手 v1.0")
    print("=" * 45)
    print(f"  地址: http://localhost:{port}")
    print(f"  按 Ctrl+C 停止")
    print("=" * 45)

    if not no_browser:
        # 后台延迟打开浏览器
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    run(port=port)
