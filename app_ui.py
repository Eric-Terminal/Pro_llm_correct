import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import os
from typing import List
import concurrent.futures
from config_manager import ConfigManager
from api_services import ApiService, DEFAULT_LLM_PROMPT_TEMPLATE

class AboutDialog(tk.Toplevel):
    """“关于”对话框，展示应用信息，支持滚动查看。"""
    def __init__(self, parent):
        super().__init__(parent)
        self.transient(parent)
        self.title("关于 AI 作文批改助手")
        # 设置一个适合滚动的默认窗口尺寸
        self.geometry("450x400")

        # 主框架，用于容纳文本和滚动条
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # 使用Text控件以支持长文本和滚动条
        text_widget = tk.Text(main_frame, wrap="word", relief="flat", spacing1=5, spacing3=5)
        text_widget.grid(row=0, column=0, sticky="nsew")

        # 创建并关联垂直滚动条
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=text_widget.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text_widget.config(yscrollcommand=scrollbar.set)

        about_text = """
欢迎使用 AI 作文批改助手！这是一款专为教育者和学生设计的智能工具，旨在利用前沿的人工智能技术，提供高效、精准、个性化的英文作文批改体验。

核心亮点:
- **双核AI引擎:** 采用先进的两步式处理流程。首先由专用的视觉语言模型(VLM)对作文图片进行高精度手写识别(OCR)与专业的书写质量评估；随后，强大的大语言模型(LLM)会结合识别出的文本、作文题目以及书写评分，进行深度、全面的分析与批改。

- **极致的灵活性与可配置性:**
  * **服务分离:** 您可以为VLM和LLM设置完全独立的API服务地址、密钥和模型名称，轻松适配不同的AI提供商（需要兼容OpenAI格式）或自建服务。
  * **逻辑定制:** 书写评分的“敏感度因子”可在设置中调整，以适应不同年级或要求的评分标准。
  * **模板开放:** 核心的LLM批改指令模板（Prompt）完全开放给用户。您可以在设置中自由修改，调整评分维度、总分、反馈风格等，实现高度个性化的批改要求。

- **闪电般的并发处理:** 内置高效的多线程并发引擎，无论您选择一张还是上百张图片，程序都能同时处理，大幅缩短批量批改的等待时间。最大并发任务数亦可在设置中自由调整。

- **企业级的安全保障:** 我们深知API密钥的敏感性。所有密钥信息在保存到本地配置文件时，均经过强大的加密算法处理，有效防止明文泄露，保障您的账户安全。

- **人性化的评分策略:** 卷面书写分采用更符合教学直觉的“向上取整至0.5分”规则，确保评分结果既精确又公平。

使用说明:
1. **初次配置:** 点击“设置”，分别填入您的VLM和LLM服务提供商的URL、API密钥和模型名称。
2. **输入题目:** 在主界面上方的文本框中，输入本次批改的“作文题目”。
3. **选择文件:** 点击“选择图片”，一次性选择所有需要批改的学生作文图片。
4. **开始批改:** 点击“开始批改”，程序将自动在后台进行并发处理，您可以在日志区看到实时进度。
5. **获取报告:** 任务完成后，每一张图片对应的Markdown格式详细批改报告，都会自动生成在原图片所在的目录下。

作者: Eric_Terminal
https://github.com/Eric-Terminal
版本: 2.4
"""
        
        text_widget.insert("1.0", about_text)
        # 将文本设置为只读，防止用户修改
        text_widget.config(state="disabled")

        # 放置“关闭”按钮的框架
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        close_button = ttk.Button(btn_frame, text="关闭", command=self.destroy)
        close_button.pack()

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_window(self)


class SettingsDialog(tk.Toplevel):
    """“设置”对话框，允许用户配置VLM、LLM服务及其他应用参数。"""
    def __init__(self, parent, current_config: dict):
        super().__init__(parent)
        self.transient(parent)
        self.title("设置")
        self.result = None

        # 为VLM和LLM服务分别创建Tkinter字符串变量
        self.vlm_url = tk.StringVar(value=current_config.get("VlmUrl", ""))
        self.vlm_api_key = tk.StringVar(value=current_config.get("VlmApiKey", ""))
        self.vlm_model = tk.StringVar(value=current_config.get("VlmModel", "gemini-2.5-pro"))
        self.llm_url = tk.StringVar(value=current_config.get("LlmUrl", ""))
        self.llm_api_key = tk.StringVar(value=current_config.get("LlmApiKey", ""))
        self.llm_model = tk.StringVar(value=current_config.get("LlmModel", "gemini-2.5-pro"))
        self.sensitivity_factor = tk.StringVar(value=current_config.get("SensitivityFactor", "1.5"))
        self.max_workers = tk.StringVar(value=current_config.get("MaxWorkers", "4"))
        
        # 智能加载Prompt模板：优先使用用户自定义模板，否则使用默认模板
        user_template = current_config.get("LlmPromptTemplate")
        self.llm_prompt_template_str = user_template if user_template else DEFAULT_LLM_PROMPT_TEMPLATE


        frame = ttk.Frame(self, padding="10")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        frame.grid_columnconfigure(0, weight=1)

        # VLM服务设置区域
        vlm_frame = ttk.LabelFrame(frame, text="VLM (视觉模型) 设置", padding="10")
        vlm_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        vlm_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(vlm_frame, text="VLM URL:").grid(column=0, row=0, sticky=tk.W, pady=2)
        ttk.Entry(vlm_frame, textvariable=self.vlm_url, width=40).grid(column=1, row=0, sticky=(tk.W, tk.E))
        ttk.Label(vlm_frame, text="VLM API Key:").grid(column=0, row=1, sticky=tk.W, pady=2)
        ttk.Entry(vlm_frame, textvariable=self.vlm_api_key, width=40).grid(column=1, row=1, sticky=(tk.W, tk.E))
        ttk.Label(vlm_frame, text="VLM 模型:").grid(column=0, row=2, sticky=tk.W, pady=2)
        ttk.Entry(vlm_frame, textvariable=self.vlm_model, width=40).grid(column=1, row=2, sticky=(tk.W, tk.E))

        # LLM服务设置区域
        llm_frame = ttk.LabelFrame(frame, text="LLM (语言模型) 设置", padding="10")
        llm_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        llm_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(llm_frame, text="LLM URL:").grid(column=0, row=0, sticky=tk.W, pady=2)
        ttk.Entry(llm_frame, textvariable=self.llm_url, width=40).grid(column=1, row=0, sticky=(tk.W, tk.E))
        ttk.Label(llm_frame, text="LLM API Key:").grid(column=0, row=1, sticky=tk.W, pady=2)
        ttk.Entry(llm_frame, textvariable=self.llm_api_key, width=40).grid(column=1, row=1, sticky=(tk.W, tk.E))
        ttk.Label(llm_frame, text="LLM 模型:").grid(column=0, row=2, sticky=tk.W, pady=2)
        ttk.Entry(llm_frame, textvariable=self.llm_model, width=40).grid(column=1, row=2, sticky=(tk.W, tk.E))

        # 其他应用参数设置区域
        other_frame = ttk.LabelFrame(frame, text="其他设置", padding="10")
        other_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        other_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(other_frame, text="手写打分敏感度:").grid(column=0, row=0, sticky=tk.W, pady=2)
        ttk.Entry(other_frame, textvariable=self.sensitivity_factor, width=40).grid(column=1, row=0, sticky=(tk.W, tk.E))
        ttk.Label(other_frame, text="最大并发数:").grid(column=0, row=1, sticky=tk.W, pady=2)
        ttk.Entry(other_frame, textvariable=self.max_workers, width=40).grid(column=1, row=1, sticky=(tk.W, tk.E))
        
        # LLM Prompt模板编辑区域
        prompt_frame = ttk.LabelFrame(frame, text="LLM Prompt 模板 (可在此修改，请勿修改{}占位符内容导致程序参数无法正常传递，通常情况下修改总分即可)", padding="10")
        prompt_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=5)
        prompt_frame.grid_columnconfigure(0, weight=1)
        prompt_frame.grid_rowconfigure(0, weight=1)
        
        self.llm_prompt_text = tk.Text(prompt_frame, height=10, wrap="word")
        self.llm_prompt_text.grid(row=0, column=0, sticky="nsew")
        prompt_scrollbar = ttk.Scrollbar(prompt_frame, orient="vertical", command=self.llm_prompt_text.yview)
        prompt_scrollbar.grid(row=0, column=1, sticky="ns")
        self.llm_prompt_text.config(yscrollcommand=prompt_scrollbar.set)
        self.llm_prompt_text.insert("1.0", self.llm_prompt_template_str)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, sticky=tk.E, pady=10)
        ttk.Button(btn_frame, text="确定", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="关闭", command=self.on_close).pack(side=tk.LEFT)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        self.result = {
            "VlmUrl": self.vlm_url.get(),
            "VlmApiKey": self.vlm_api_key.get(),
            "VlmModel": self.vlm_model.get(),
            "LlmUrl": self.llm_url.get(),
            "LlmApiKey": self.llm_api_key.get(),
            "LlmModel": self.llm_model.get(),
            "SensitivityFactor": self.sensitivity_factor.get(),
            "MaxWorkers": self.max_workers.get(),
            "LlmPromptTemplate": self.llm_prompt_text.get("1.0", "end-1c") # 从Text控件获取用户修改后的Prompt模板
        }
        self.destroy()

    def on_close(self):
        self.result = None
        self.destroy()


class MainApp:
    """应用主窗口类，负责构建UI界面、处理用户交互和协调后台服务。"""
    def __init__(self, root: tk.Tk, config_manager: ConfigManager, api_service: ApiService):
        self.root = root
        self.config_manager = config_manager
        self.api_service = api_service
        
        self.file_paths: List[str] = []
        self.is_file_selected = False
        self.ui_queue = queue.Queue()
        self.topic_input = None
        self.processed_count = 0
        self.lock = threading.Lock()

        self._setup_ui()
        self._initialize_config()
        self.root.after(100, self._process_ui_queue)

    def _setup_ui(self):
        """初始化和布局主窗口的所有UI组件。"""
        self.root.title("AI 作文批改助手")
        self.root.geometry("550x450")
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # 顶部进度条
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        top_frame.grid_columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(top_frame, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E))

        # 左侧控制按钮
        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=1, column=0, sticky=(tk.N, tk.W), padx=(0, 10))
        ttk.Button(left_frame, text="选择图片", command=self._open_file_dialog).pack(fill=tk.X, pady=5)
        ttk.Button(left_frame, text="开始批改", command=self._start_processing).pack(fill=tk.X, pady=5)
        ttk.Button(left_frame, text="设置", command=self._open_settings_dialog).pack(fill=tk.X, pady=5)
        ttk.Button(left_frame, text="关于", command=self._open_about_dialog).pack(fill=tk.X, pady=5)

        # 右侧输入和日志区域
        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # 配置右侧框架的网格权重，使组件能自适应缩放
        right_frame.grid_rowconfigure(0, weight=7)  # 作文题目框占7份
        right_frame.grid_rowconfigure(1, weight=3)  # 日志框占3份
        right_frame.grid_columnconfigure(0, weight=1)

        # 作文题目输入框
        self.topic_input = tk.Text(right_frame, wrap="word")
        self.topic_input.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        
        self.topic_input.insert("1.0", "（在此输入作文题目）")
        self.topic_input.config(fg="grey")

        # 实现输入框的占位符（placeholder）效果
        def on_focus_in(event):
            if self.topic_input.get("1.0", "end-1c").strip() == "（在此输入作文题目）":
                self.topic_input.delete("1.0", tk.END)
                self.topic_input.config(fg="black")

        def on_focus_out(event):
            if not self.topic_input.get("1.0", "end-1c").strip():
                self.topic_input.insert("1.0", "（在此输入作文题目）")
                self.topic_input.config(fg="grey")

        self.topic_input.bind("<FocusIn>", on_focus_in)
        self.topic_input.bind("<FocusOut>", on_focus_out)

        # 日志输出框（带滚动条）
        listbox_frame = ttk.Frame(right_frame)
        listbox_frame.grid(row=1, column=0, sticky="nsew")
        listbox_frame.grid_rowconfigure(0, weight=1)
        listbox_frame.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(listbox_frame)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.listbox.config(yscrollcommand=scrollbar.set)

    def _log(self, message: str):
        """将消息添加到日志列表框并滚动到底部。"""
        self.listbox.insert(tk.END, message)
        self.listbox.see(tk.END)

    def _initialize_config(self):
        """应用启动时检查配置完整性，如果配置不完整则强制用户设置。"""
        is_ok, _ = self.config_manager.check_settings()
        if not is_ok:
            self._show_config_dialog_until_valid()

    def _show_config_dialog_until_valid(self):
        """循环显示设置对话框，直到所有必需配置项都已填写。"""
        while True:
            self._open_settings_dialog()
            is_ok, missing_item = self.config_manager.check_settings()
            if is_ok:
                return
            if messagebox.askretrycancel("配置未完成", f"请配置: {missing_item}") == "cancel":
                self.root.quit()
                return

    def _open_settings_dialog(self):
        """打开设置对话框，并根据返回结果更新和保存配置。"""
        dialog = SettingsDialog(self.root, self.config_manager.config)
        if dialog.result:
            # 清理旧的、统一的AI配置和OCR配置，以兼容新版分离的配置
            self.config_manager.config.pop("AiUrl", None)
            self.config_manager.config.pop("AiApiKey", None)
            self.config_manager.config.pop("OcrApiKey", None)
            self.config_manager.config.pop("OcrSecretKey", None)
            for key, value in dialog.result.items():
                self.config_manager.set(key, value)
            self.config_manager.save()

    def _open_about_dialog(self):
        """创建并显示“关于”对话框。"""
        AboutDialog(self.root)

    def _open_file_dialog(self):
        """打开文件选择对话框，让用户选择一个或多个图片文件。"""
        paths = filedialog.askopenfilenames(title="选择作文图片", filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp")])
        if paths:
            self.file_paths = paths
            self.is_file_selected = True
            self._log(f"已选择 {len(paths)} 个文件")
        else:
            self._log("取消选择")

    def _start_processing(self):
        """启动作文批改流程。"""
        if not self.is_file_selected:
            messagebox.showerror("操作错误", "请先选择文件")
            return
        
        topic = self.topic_input.get("1.0", tk.END).strip()
        if not topic or topic == "（在此输入作文题目）":
            messagebox.showerror("操作错误", "请输入作文题目")
            return

        # 重置进度条和计数器
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(self.file_paths)
        self.processed_count = 0
        
        # 在后台线程中启动并发处理
        thread = threading.Thread(target=self._concurrent_worker_manager, args=(self.file_paths, topic), daemon=True)
        thread.start()

    def _process_ui_queue(self):
        """定期检查UI更新队列，并执行相应的UI操作（如记日志、更新进度条）。"""
        try:
            while True:
                task, data = self.ui_queue.get_nowait()
                if task == "log": 
                    self._log(data)
                elif task == "progress":
                    with self.lock:
                        self.processed_count += 1
                        self.progress_bar['value'] = self.processed_count
                elif task == "finish":
                    messagebox.showinfo("完成", "所有文件处理完成")
                    self.progress_bar['value'] = 0
                    self.is_file_selected = False
        except queue.Empty:
            pass
        finally:
            # 持续轮询队列
            self.root.after(100, self._process_ui_queue)

    def _concurrent_worker_manager(self, file_paths: List[str], topic: str):
        """使用线程池并发处理所有选定的文件。"""
        try:
            max_workers = int(self.config_manager.get("MaxWorkers", "4"))
        except (ValueError, TypeError):
            max_workers = 4

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for file_path in file_paths:
                executor.submit(self._process_single_file, file_path, topic)
        
        # 所有任务完成后，向UI队列发送完成信号
        self.ui_queue.put(("finish", None))

    def _process_single_file(self, file_path: str, topic: str):
        """处理单个图片文件的完整流程：调用API、保存报告、更新UI队列。"""
        base_name = os.path.basename(file_path)
        self.ui_queue.put(("log", f"开始处理: {base_name}"))
        try:
            final_report = self.api_service.process_essay_image(file_path, topic)
            
            report_filename = os.path.splitext(file_path)[0] + "_report.md"
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write(final_report)
            
            self.ui_queue.put(("log", f"完成批改: {base_name} -> {os.path.basename(report_filename)}"))

        except Exception as e:
            self.ui_queue.put(("log", f"文件: {base_name} 失败: {e}"))
        
        # 无论成功或失败，都更新进度
        self.ui_queue.put(("progress", 1))
