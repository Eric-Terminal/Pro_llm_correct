import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import os
from typing import List
import concurrent.futures
import logging
from config_manager import ConfigManager
from api_services import ApiService, DEFAULT_LLM_PROMPT_TEMPLATE

# 配置日志记录器
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AboutDialog(tk.Toplevel):
    """“关于”对话框，展示应用信息，支持滚动查看。"""
    def __init__(self, parent, config_manager: ConfigManager):
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

        vlm_in = config_manager.get('UsageVlmInput', 0)
        vlm_out = config_manager.get('UsageVlmOutput', 0)
        llm_in = config_manager.get('UsageLlmInput', 0)
        llm_out = config_manager.get('UsageLlmOutput', 0)

        about_text = f"""
欢迎使用 AI 作文批改助手！这是一款专为教育工作者和学生设计的智能工具，利用前沿的人工智能技术，提供高效、精准、个性化的英文作文批改体验。

✨ 核心特色:

- **双AI引擎架构:** 采用创新的两步式处理流程。首先由专业的视觉语言模型(VLM)进行高精度手写文字识别(OCR)和专业的书写质量评估；然后由强大的大语言模型(LLM)结合识别文本、作文题目和书写评分，进行深度内容分析和专业批改。

- **极致灵活性:**
  * **服务独立配置:** VLM和LLM支持完全独立的API服务地址、密钥和模型名称，轻松适配各种AI服务提供商（兼容OpenAI格式）
  * **智能评分调节:** 书写质量"敏感度因子"可自由调整，适应不同年级和评分标准要求
  * **Prompt完全开放:** 核心批改指令模板完全可自定义，支持调整评分标准、总分设置和反馈风格

- **高效并发处理:** 内置多线程并发引擎，支持批量处理任意数量的图片，大幅提升批改效率，最大并发数可配置

- **企业级安全保障:** 所有API密钥均采用军事级加密算法存储，确保您的账户信息安全

- **专业评分体系:** 针对高考英语作文场景设计，支持应用文(15分制)和读后续写(25分制)两种评分标准

📋 使用指南:
1. **首次设置:** 点击"设置"，配置VLM和LLM服务的URL、API密钥和模型
2. **输入题目:** 在主界面文本框中输入本次批改的作文题目
3. **选择图片:** 点击"选择图片"，可多选需要批改的作文图片
4. **开始批改:** 点击"开始批改"，程序自动进行并发处理
5. **查看报告:** 处理完成后，Markdown和HTML格式的详细批改报告将保存在原图片目录

🎯 输出格式:
- Markdown源文件（可编辑）
- HTML可视化报告（美观易读）
- 详细的语法错误分析
- 专业的写作建议
- 精准的分数评估

作者: Eric_Terminal
项目地址: https://github.com/Eric-Terminal/Pro_llm_correct
版本: 3.1

---
历史Token使用统计:
- VLM 输入Token: {vlm_in:,}
- VLM 输出Token: {vlm_out:,}
- LLM 输入Token: {llm_in:,}
- LLM 输出Token: {llm_out:,}
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
    """"设置"对话框，允许用户配置VLM、LLM服务及其他应用参数。"""
    def __init__(self, parent, config_manager: ConfigManager):
        super().__init__(parent)
        self.transient(parent)
        self.title("设置")
        self.result = None
        self.config_manager = config_manager

        # 为VLM和LLM服务分别创建Tkinter字符串变量
        # 使用config_manager.get()方法获取解密后的值用于显示
        self.vlm_url = tk.StringVar(value=config_manager.get("VlmUrl", "https://api.siliconflow.cn/v1"))
        self.vlm_api_key = tk.StringVar(value=config_manager.get("VlmApiKey", ""))
        self.vlm_model = tk.StringVar(value=config_manager.get("VlmModel", "Pro/THUDM/GLM-4.1V-9B-Thinking"))
        self.llm_url = tk.StringVar(value=config_manager.get("LlmUrl", "https://api.siliconflow.cn/v1"))
        self.llm_api_key = tk.StringVar(value=config_manager.get("LlmApiKey", ""))
        self.llm_model = tk.StringVar(value=config_manager.get("LlmModel", "moonshotai/Kimi-K2-Instruct"))
        self.sensitivity_factor = tk.StringVar(value=config_manager.get("SensitivityFactor", "1.5"))
        self.max_workers = tk.StringVar(value=config_manager.get("MaxWorkers", "4"))
        self.max_retries = tk.StringVar(value=config_manager.get("MaxRetries", "3"))
        self.retry_delay = tk.StringVar(value=config_manager.get("RetryDelay", "5"))
        self.save_markdown = tk.BooleanVar(value=config_manager.get("SaveMarkdown", True))
        self.render_markdown = tk.BooleanVar(value=config_manager.get("RenderMarkdown", True))
        
        # 智能加载Prompt模板：优先使用用户自定义模板，否则使用默认模板
        user_template = config_manager.get("LlmPromptTemplate")
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
        ttk.Label(other_frame, text="最大重试次数:").grid(column=0, row=2, sticky=tk.W, pady=2)
        ttk.Entry(other_frame, textvariable=self.max_retries, width=40).grid(column=1, row=2, sticky=(tk.W, tk.E))
        ttk.Label(other_frame, text="重试延迟(秒):").grid(column=0, row=3, sticky=tk.W, pady=2)
        ttk.Entry(other_frame, textvariable=self.retry_delay, width=40).grid(column=1, row=3, sticky=(tk.W, tk.E))
        ttk.Label(other_frame, text="保存Markdown文件:").grid(column=0, row=4, sticky=tk.W, pady=2)
        ttk.Checkbutton(other_frame, variable=self.save_markdown).grid(column=1, row=4, sticky=tk.W)
        ttk.Label(other_frame, text="渲染HTML报告:").grid(column=0, row=5, sticky=tk.W, pady=2)
        ttk.Checkbutton(other_frame, variable=self.render_markdown).grid(column=1, row=5, sticky=tk.W)
        
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
            "MaxRetries": self.max_retries.get(),
            "RetryDelay": self.retry_delay.get(),
            "SaveMarkdown": self.save_markdown.get(),
            "RenderMarkdown": self.render_markdown.get(),
            "LlmPromptTemplate": self.llm_prompt_text.get("1.0", "end-1c")
        }

        # 如果用户修改后的模板与默认模板内容一致，则不写入配置文件，以使用默认值
        if self.result["LlmPromptTemplate"].strip() == DEFAULT_LLM_PROMPT_TEMPLATE.strip():
            self.result["LlmPromptTemplate"] = None  # 使用 None 作为信号，表示应移除此配置项

        self.destroy()

    def on_close(self):
        self.result = None
        self.destroy()


class MainApp:
    """应用主窗口类，负责构建UI界面、处理用户交互和协调后台服务。"""
    def __init__(self, root: tk.Tk, config_manager: ConfigManager):
        self.root = root
        self.config_manager = config_manager
        self.ui_queue = queue.Queue()
        self.api_service = ApiService(config_manager, self.ui_queue)
        
        self.file_paths: List[str] = []
        self.is_file_selected = False
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
        dialog = SettingsDialog(self.root, self.config_manager)
        if dialog.result:
            # 清理旧的、统一的AI配置和OCR配置，以兼容新版分离的配置
            self.config_manager.config.pop("AiUrl", None)
            self.config_manager.config.pop("AiApiKey", None)
            self.config_manager.config.pop("OcrApiKey", None)
            self.config_manager.config.pop("OcrSecretKey", None)
            for key, value in dialog.result.items():
                if key == "LlmPromptTemplate":
                    if value is None:
                        # 如果值为None，表示用户希望恢复默认模板，因此从配置中移除该键
                        self.config_manager.config.pop(key, None)
                    else:
                        self.config_manager.set(key, value)
                else:
                    self.config_manager.set(key, value)
            self.config_manager.save()

    def _open_about_dialog(self):
        """创建并显示“关于”对话框。"""
        AboutDialog(self.root, self.config_manager)

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
            # 强制将从配置中读取的值转换为整数，提供默认值以防万一
            max_workers = int(self.config_manager.get("MaxWorkers", 4))
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
            final_report, vlm_usage, llm_usage, html_path = self.api_service.process_essay_image(file_path, topic)
            
            # 检查是否保存Markdown文件
            save_markdown = self.config_manager.get("SaveMarkdown", True)
            report_filename_md = os.path.splitext(file_path)[0] + "_report.md"
            
            # 保存Markdown源文件（如果配置开启）
            if save_markdown:
                with open(report_filename_md, 'w', encoding='utf-8') as f:
                    f.write(final_report)
            
            vlm_in = vlm_usage.get("prompt_tokens", 0)
            vlm_out = vlm_usage.get("completion_tokens", 0)
            llm_in = llm_usage.get("prompt_tokens", 0)
            llm_out = llm_usage.get("completion_tokens", 0)

            usage_log = f"Token用量: VLM(in:{vlm_in}, out:{vlm_out}), LLM(in:{llm_in}, out:{llm_out})"
            
            # 记录所有生成的文件
            output_files = []
            if save_markdown:
                output_files.append(os.path.basename(report_filename_md))
            
            # 检查是否只勾选了HTML，如果是则删除Markdown文件
            render_html = self.config_manager.get("RenderMarkdown", True)
            if html_path and os.path.exists(html_path):
                output_files.append(os.path.basename(html_path))
                self.ui_queue.put(("log", f"已生成HTML报告: {os.path.basename(html_path)}"))
                
                # 如果只勾选HTML，不勾选Markdown，则删除Markdown文件
                if not save_markdown and render_html and os.path.exists(report_filename_md):
                    os.remove(report_filename_md)
                    self.ui_queue.put(("log", f"已删除Markdown文件（仅保留HTML）"))

            self.ui_queue.put(("log", f"完成批改: {base_name} -> {', '.join(output_files)}"))
            self.ui_queue.put(("log", usage_log))

            # 加锁以保证线程安全地更新和保存配置
            with self.lock:
                self.config_manager.update_token_usage(vlm_in, vlm_out, llm_in, llm_out)
                self.config_manager.save()

        except Exception as e:
            self.ui_queue.put(("log", f"文件: {base_name} 失败: {e}"))
        
        # 无论成功或失败，都更新进度
        self.ui_queue.put(("progress", 1))
