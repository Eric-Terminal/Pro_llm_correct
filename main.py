import tkinter as tk
from app_ui import MainApp
from config_manager import ConfigManager
from api_services import ApiService
import sys
import os


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

if __name__ == "__main__":
    # 1. 初始化核心服务
    # 使用合适的配置文件路径
    config_path = get_config_path()
    config_manager = ConfigManager(config_path)

    # 2. 创建Tkinter主窗口
    root = tk.Tk()
    
    # 3. 实例化主应用，服务将在MainApp内部创建
    app = MainApp(root, config_manager)

    # 4. 启动Tkinter事件循环
    root.mainloop()