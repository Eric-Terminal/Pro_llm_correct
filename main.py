import tkinter as tk
from app_ui import MainApp
from config_manager import ConfigManager
from api_services import ApiService
import sys
import os

def resource_path(relative_path):
    """
    获取资源的绝对路径，以支持PyInstaller打包后的单文件应用。

    在开发环境中，返回基于当前工作目录的相对路径。
    在PyInstaller打包的应用中，返回临时文件夹`_MEIPASS`中的路径。
    """
    try:
        # 尝试获取PyInstaller在运行时创建的临时路径
        base_path = sys._MEIPASS
    except Exception:
        # 如果`_MEIPASS`属性不存在，说明是在开发环境，使用当前目录
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    # 1. 初始化核心服务
    # 使用 resource_path 确保在打包后也能正确找到配置文件
    config_manager = ConfigManager(resource_path("config.json"))

    # 2. 创建Tkinter主窗口
    root = tk.Tk()
    
    # 3. 实例化主应用，服务将在MainApp内部创建
    app = MainApp(root, config_manager)

    # 4. 启动Tkinter事件循环
    root.mainloop()