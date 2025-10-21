import json
import os
import base64
import hashlib
import platform
import subprocess
from typing import Dict, Optional, Tuple, Any
from cryptography.fernet import Fernet, InvalidToken


class ConfigManager:
    """
    管理应用的配置（`config.json`），包含加载、保存和敏感字段的加解密逻辑。
    """

    SENSITIVE_KEYS = ["VlmApiKey", "LlmApiKey"]
    _ENCRYPTION_PASSWORD = b"a-strong-but-not-public-password-for-this-app"
    _SALT = b"salt_for_llm_app_config"
    _FALLBACK_DEVICE_IDS = {
        "default-device-id-for-encryption",
        "unknown-device-for-security",
        "",
        None,
    }

    def __init__(self, file_path: str = "config.json"):
        self.file_path = file_path
        self.config: Dict[str, Any] = {}
        self._fernet: Optional[Fernet] = None
        self._needs_save = False
        self._device_locked = False

        self.load()
        self._initialize_encryption()
        self._ensure_default_render_settings()

        if self._needs_save:
            self.save()

    def _get_device_identifier(self) -> str:
        """
        获取设备的唯一标识符（如序列号），用于加密。
        这使得配置文件在另一台机器上无法解密。
        """
        system = platform.system()
        try:
            if system == "Windows":
                return (
                    subprocess.check_output(
                        "wmic bios get serialnumber", shell=True
                    )
                    .decode()
                    .split("\n")[1]
                    .strip()
                )
            if system == "Darwin":
                return (
                    subprocess.check_output(
                        "ioreg -l | grep IOPlatformSerialNumber", shell=True
                    )
                    .decode()
                    .split('"')[-2]
                )
            if system == "Linux":
                try:
                    return (
                        subprocess.check_output(
                            "sudo dmidecode -s system-serial-number", shell=True
                        )
                        .decode()
                        .strip()
                    )
                except Exception:
                    with open("/etc/machine-id", "r", encoding="utf-8") as f:
                        return f.read().strip()
        except Exception as exc:
            print(f"无法获取设备ID: {exc}，将使用默认值。")
            return "default-device-id-for-encryption"
        return "unknown-device-for-security"

    def _initialize_encryption(self):
        """使用预设密码和设备信息生成Fernet密钥，同时确保跨运行稳定。"""
        device_id = self._get_device_identifier()
        current_source = (
            "fallback" if device_id in self._FALLBACK_DEVICE_IDS else "hardware"
        )
        device_id = device_id or "default-device-id-for-encryption"

        stored_salt = self.config.get("__device_salt__")
        if isinstance(stored_salt, str):
            try:
                device_specific_salt = base64.urlsafe_b64decode(
                    stored_salt.encode("utf-8")
                )
            except (ValueError, TypeError):
                device_specific_salt = self._derive_salt_from_device(device_id)
                self.config["__device_salt__"] = base64.urlsafe_b64encode(
                    device_specific_salt
                ).decode("utf-8")
                self._needs_save = True
        else:
            device_specific_salt = self._derive_salt_from_device(device_id)
            self.config["__device_salt__"] = base64.urlsafe_b64encode(
                device_specific_salt
            ).decode("utf-8")
            self._needs_save = True

        key = self._build_key(device_specific_salt)
        self._fernet = Fernet(key)

        current_fingerprint = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
        stored_fingerprint = self.config.get("__device_fingerprint__")
        stored_source = self.config.get("__device_fingerprint_source__", "hardware")

        if stored_fingerprint:
            if stored_fingerprint != current_fingerprint:
                if stored_source == "fallback" and current_source == "hardware":
                    self._migrate_encryption(device_id, current_fingerprint, current_source)
                else:
                    print("警告：检测到配置来自其他设备，敏感信息已锁定，请重新输入。")
                    self._fernet = None
                    self._device_locked = True
                    return
        else:
            self.config["__device_fingerprint__"] = current_fingerprint
            self.config["__device_fingerprint_source__"] = current_source
            self._needs_save = True

        if not self._device_locked:
            if stored_fingerprint != current_fingerprint:
                self.config["__device_fingerprint__"] = current_fingerprint
                self.config["__device_fingerprint_source__"] = current_source
                self._needs_save = True

    def _derive_salt_from_device(self, device_id: str) -> bytes:
        """将设备ID与固定盐组合为最终的盐值。"""
        return self._SALT + device_id.encode("utf-8")

    def _build_key(self, device_specific_salt: bytes) -> bytes:
        """基于设备盐构造Fernet密钥。"""
        kdf = hashlib.pbkdf2_hmac(
            "sha256", self._ENCRYPTION_PASSWORD, device_specific_salt, 100000
        )
        return base64.urlsafe_b64encode(kdf)

    @staticmethod
    def _is_probably_encrypted(value: Any) -> bool:
        """
        粗略判断一个值是否像Fernet密文。
        Fernet密文通常以'gAAAAA'开头，这里用作启发式判断。
        """
        return isinstance(value, str) and value.startswith("gAAAAA")

    def _encrypt(self, value: str) -> str:
        """使用Fernet实例加密字符串。"""
        if not value or not self._fernet:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _ensure_default_render_settings(self):
        """确保渲染相关默认配置存在。"""
        if self.get("SaveMarkdown") is None:
            self.set("SaveMarkdown", True)
        if self.get("RenderMarkdown") is None:
            self.set("RenderMarkdown", True)

    def _decrypt(self, encrypted_value: str) -> str:
        """
        使用Fernet实例解密字符串。
        如果解密失败但内容不像新版本密文，则视为旧版本明文返回。
        """
        if not encrypted_value or not self._fernet or self._device_locked:
            return ""
        try:
            return self._fernet.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            if not self._is_probably_encrypted(encrypted_value):
                return encrypted_value
            print("警告：检测到敏感字段无法解密，请重新输入并保存。")
            return ""

    def _migrate_encryption(self, new_device_id: str, new_fingerprint: str, new_source: str):
        """
        将旧密钥加密的数据迁移到新设备指纹对应的密钥。
        仅在从回退指纹迁移到真实硬件指纹时使用。
        """
        if not self._fernet:
            return

        plaintext_cache: Dict[str, str] = {}
        for key in self.SENSITIVE_KEYS:
            raw_value = self.config.get(key)
            if raw_value:
                decrypted = self._decrypt(str(raw_value))
                if decrypted:
                    plaintext_cache[key] = decrypted

        new_salt = self._derive_salt_from_device(new_device_id)
        new_key = self._build_key(new_salt)
        new_fernet = Fernet(new_key)

        for key, value in plaintext_cache.items():
            self.config[key] = new_fernet.encrypt(value.encode("utf-8")).decode("utf-8")

        self.config["__device_salt__"] = base64.urlsafe_b64encode(new_salt).decode("utf-8")
        self.config["__device_fingerprint__"] = new_fingerprint
        self.config["__device_fingerprint_source__"] = new_source

        self._fernet = new_fernet
        self._needs_save = True

    def load(self) -> bool:
        """从JSON文件加载配置，如不存在则初始化为空配置。"""
        if not os.path.exists(self.file_path):
            self.config = {}
            self._needs_save = True
            return True
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                self.config = json.load(file)
            return True
        except (json.JSONDecodeError, IOError):
            self.config = {}
            return False

    def save(self):
        """将当前配置写入JSON文件。"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as file:
                json.dump(self.config, file, indent=4)
            self._needs_save = False
        except IOError as exc:
            print(f"保存配置失败: {exc}")

    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        """读取指定配置项，对敏感字段自动解密。"""
        value = self.config.get(key)
        if value is None:
            return default

        if key in self.SENSITIVE_KEYS:
            decrypted = self._decrypt(str(value))
            if decrypted and decrypted == str(value) and not self._is_probably_encrypted(value):
                self.set(key, decrypted)
                self.save()
            return decrypted if decrypted else default
        return value

    def set(self, key: str, value: Any):
        """写入指定配置项，对敏感字段自动加密。"""
        if key in self.SENSITIVE_KEYS:
            self.config[key] = self._encrypt(str(value))
        else:
            self.config[key] = value
        self._needs_save = True

    def update_token_usage(self, vlm_input: int, vlm_output: int, llm_input: int, llm_output: int):
        """累加本次调用的token用量统计。"""
        self.config["UsageVlmInput"] = self.get("UsageVlmInput", 0) + vlm_input
        self.config["UsageVlmOutput"] = self.get("UsageVlmOutput", 0) + vlm_output
        self.config["UsageLlmInput"] = self.get("UsageLlmInput", 0) + llm_input
        self.config["UsageLlmOutput"] = self.get("UsageLlmOutput", 0) + llm_output
        self._needs_save = True

    def check_settings(self) -> Tuple[bool, Optional[str]]:
        """
        检查所有必需配置项是否已设置。
        返回 (是否完整, 第一个缺失项的友好名称)。
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
            if not self.get(key):
                return False, name
        return True, None

