import json
import os
import base64
import hashlib
from typing import Dict, Optional, Tuple, Any
from cryptography.fernet import Fernet, InvalidToken

class ConfigManager:
    """
    管理应用的配置（`config.json`），包括加载、保存以及对敏感信息的自动加解密。
    """
    # 定义需要进行加密处理的配置项
    SENSITIVE_KEYS = ["VlmApiKey", "LlmApiKey"]
    # 用于生成加密密钥的密码和盐。注意：修改这些值将导致旧的配置文件无法解密。
    _ENCRYPTION_PASSWORD = b"a-strong-but-not-public-password-for-this-app"
    _SALT = b'salt_for_llm_app_config'

    def __init__(self, file_path: str = "config.json"):
        self.file_path = file_path
        self.config: Dict[str, Any] = {}
        self._fernet: Optional[Fernet] = None
        self._initialize_encryption()
        self.load()
        # 确保默认渲染设置存在
        self._ensure_default_render_settings()

    def _initialize_encryption(self):
        """使用预设的密码和盐生成加密密钥，并初始化Fernet加密/解密实例。"""
        kdf = hashlib.pbkdf2_hmac('sha256', self._ENCRYPTION_PASSWORD, self._SALT, 100000)
        key = base64.urlsafe_b64encode(kdf)
        self._fernet = Fernet(key)

    def _encrypt(self, value: str) -> str:
        """使用初始化的Fernet实例加密字符串。"""
        if not value or not self._fernet:
            return ""
        return self._fernet.encrypt(value.encode('utf-8')).decode('utf-8')

    def _ensure_default_render_settings(self):
        """确保渲染相关的默认设置存在"""
        if self.get("SaveMarkdown") is None:
            self.set("SaveMarkdown", True)  # 默认保存Markdown文件
        if self.get("RenderMarkdown") is None:
            self.set("RenderMarkdown", True)  # 默认开启HTML渲染功能

    def _decrypt(self, encrypted_value: str) -> str:
        """
        使用初始化的Fernet实例解密字符串。
        如果解密失败（例如，值是旧的明文或已损坏），则返回空字符串以避免程序崩溃。
        """
        if not encrypted_value or not self._fernet:
            return ""
        try:
            return self._fernet.decrypt(encrypted_value.encode('utf-8')).decode('utf-8')
        except InvalidToken:
            # 如果解密失败，返回空字符串
            return ""

    def load(self) -> bool:
        """从JSON文件加载配置。如果文件不存在，则创建一个空的配置文件。"""
        if not os.path.exists(self.file_path):
            # 如果配置文件不存在，则创建一个空的配置字典并保存
            self.config = {}
            self.save()
            return True
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            return True
        except (json.JSONDecodeError, IOError):
            self.config = {}
            return False

    def save(self):
        """将当前配置保存到JSON文件。敏感信息的加密在`set`方法中处理。"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"保存配置失败: {e}")

    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        """获取指定键的配置值。如果键属于敏感信息，则自动解密后返回。"""
        value = self.config.get(key)
        if value is None:
            return default
        
        if key in self.SENSITIVE_KEYS:
            return self._decrypt(str(value))
        return value

    def set(self, key: str, value: Any):
        """设置指定键的配置值。如果键属于敏感信息，则自动加密后存储。"""
        if key in self.SENSITIVE_KEYS:
            self.config[key] = self._encrypt(str(value))
        else:
            self.config[key] = value

    def update_token_usage(self, vlm_input: int, vlm_output: int, llm_input: int, llm_output: int):
        """累加本次API调用的token使用量到配置中。"""
        self.config['UsageVlmInput'] = self.get('UsageVlmInput', 0) + vlm_input
        self.config['UsageVlmOutput'] = self.get('UsageVlmOutput', 0) + vlm_output
        self.config['UsageLlmInput'] = self.get('UsageLlmInput', 0) + llm_input
        self.config['UsageLlmOutput'] = self.get('UsageLlmOutput', 0) + llm_output

    def check_settings(self) -> Tuple[bool, Optional[str]]:
        """
        检查所有必需的配置项是否都已设置。
        返回一个元组，包含检查结果（布尔值）和第一个缺失的配置项名称（字符串）。
        """
        required_settings = {
            "VlmUrl": "VLM服务地址",
            "VlmApiKey": "VLM服务密钥",
            "VlmModel": "VLM模型名称",
            "LlmUrl": "LLM服务地址",
            "LlmApiKey": "LLM服务密钥",
            "LlmModel": "LLM模型名称",
            "MaxRetries": "最大重试次数",
            "RetryDelay": "重试延迟时间(秒)",
        }
        for key, name in required_settings.items():
            # 使用self.get()来确保我们检查的是解密后的值
            if not self.get(key):
                return False, name
        return True, None
