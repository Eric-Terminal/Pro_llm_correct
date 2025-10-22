import os
import socket
import sys
import threading
import time
import webbrowser

from config_manager import ConfigManager
from web_app import create_app


def get_config_path():
    """
    获取配置文件的合适路径。
    在开发环境使用当前目录，在打包环境使用exe所在目录。
    """
    try:
        # 检查是否在PyInstaller打包环境中
        sys._MEIPASS
        # 如果是打包环境，使用exe文件所在目录
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, "config.json")
    except Exception:
        # 开发环境，使用当前目录
        return "config.json"

def find_available_port(start: int = 4567, limit: int = 4667) -> int:
    """Return the first free TCP port within the inclusive range."""
    for port in range(start, limit + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"无法在 {start}-{limit} 范围内找到可用端口")


def open_browser_later(url: str, delay: float = 1.0) -> None:
    """Open the default browser after a small delay."""

    def _opener():
        time.sleep(delay)
        try:
            webbrowser.open_new(url)
        except Exception:
            pass

    threading.Thread(target=_opener, daemon=True).start()


if __name__ == "__main__":
    config_path = get_config_path()
    config_manager = ConfigManager(config_path)
    app = create_app(config_manager)

    port = find_available_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"🚀 Web UI 已启动，访问: {url}")
    open_browser_later(url)

    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
