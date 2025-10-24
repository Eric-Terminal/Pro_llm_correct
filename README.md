# AI 作文批改助手 ✨

> 上传手写英文作文 → 自动识别文本 → 按高考标准打分 → 输出详尽反馈报告，全流程在本地浏览器完成。

![Web UI 批改页面](photo/1.png)
![Web UI 设置页面](photo/2.png)
![Web UI 关于页面](photo/3.png)

## 全面重构亮点
- **现代化 Web UI**：基于 Flask 构建的单页应用，所有功能集中在浏览器端完成，配置与状态实时同步。
- **任务可追溯**：每次批改都会创建独立 run id，原图、Markdown、HTML 报告集中存放，便于回看和分享。
- **并发调度升级**：多线程线程池 + 独立任务状态机，批量图片互不阻塞，失败文件单独记录。
- **Prompt / 评分可插拔**：默认内置高考英语评分模板，可在 UI 动态替换；书写敏感度、模型温度均可调整。
- **安全与透明**：API Key 以设备指纹派生的密钥加密存储，支持一键清除；Token 用量实时累积并在 UI 展示。
- **自动更新提示**：后台检查 GitHub Releases 获取最新版本信息，可一键触发或关闭。

## 工作原理概览
1. **图片接入**：兼容摄像头拍照、扫描件或批量上传，自动清洗文件名防止覆盖。
2. **VLM 解析**：将图片转为 base64，通过兼容 OpenAI 的视觉模型 OCR + 计算书写分。
3. **LLM 批改**：根据作文题目、识别文本、书写分构建 Prompt，生成结构化中文反馈。
4. **报告生成**：按配置保存 Markdown，并可渲染为带主题的 HTML 文件输出。
5. **状态同步**：Web UI 实时播报进度、日志、Token 消耗。

## 快速开始

### 环境准备
- Python 3.9 及以上
- macOS / Windows / Linux 均可
- 任意兼容 OpenAI API 协议的 VLM/LLM 服务（OpenAI、Azure OpenAI、通义、DeepSeek 等）

### 安装依赖
```bash
git clone https://github.com/Eric-Terminal/Pro_llm_correct.git
cd Pro_llm_correct
python3 -m venv venv
source venv/bin/activate        # Windows 使用 venv\Scripts\activate
pip install -r requirements.txt
```

### 启动 Web 版
```bash
python3 main.py
```
- 应用将尝试从 4567–4667 中选择空闲端口，并自动打开默认浏览器。
- 首次运行会生成 `config.json`、`output_reports/` 等目录。

## 使用流程
1. 在「批改作文」页填入题目或场景说明。
2. 上传一张或多张作文图片并提交。
3. 查看实时处理状态：成功会显示 Markdown / HTML 下载链接，失败会给出详细错误。
4. 结果保存在 `output_reports/<run_id>/` 中，run id 由时间戳生成，保证唯一。

```
output_reports/
└── <run_id>/               # 例如 20240101-120000
    ├── essay-1.png         # 原始上传文件
    ├── essay-1_report.md   # Markdown 报告（若启用 SaveMarkdown）
    └── essay-1_report.html # HTML 报告（若启用 RenderMarkdown）
```
- `OutputDirectory` 可改为绝对路径以迁移到 NAS / 外部硬盘。
- 若只启用 HTML，程序会在渲染完成后自动删除对应 Markdown 文件。

## 关键配置参考
| 分类 | 键名 | 说明 |
| --- | --- | --- |
| 服务连接 | `VlmUrl` / `VlmModel` / `VlmApiKey`<br>`LlmUrl` / `LlmModel` / `LlmApiKey` | 与 OpenAI SDK 参数保持一致；密钥输入后即被本地加密，输入框留空表示沿用已有值。 |
| 性能与容错 | `MaxWorkers` / `MaxRetries` / `RetryDelay` / `RequestTimeout` | 控制并发线程数、失败重试次数与间隔、单次请求超时（秒）。 |
| 评分策略 | `SensitivityFactor` | 对 VLM 输出的书写分进行幂次强化/弱化（默认 1.0）。 |
|  | `VlmTemperature` / `LlmTemperature` | 约束模型随机性，范围 0–2。 |
| Prompt 定制 | `LlmPromptTemplate` | 使用 Python `str.format` 语法，支持 `{topic}`、`{wscore}`、`{essay_text}` 占位符，留空回退到内置模板。 |
| 输出控制 | `OutputDirectory` / `SaveMarkdown` / `RenderMarkdown` | 自定义输出目录及报告格式，布尔选项可在 UI 勾选。 |
| 版本与统计 | `AutoUpdateCheck` / `UsageVlmInput` 等 | 自动更新开关及历史 Token 统计，展示于 UI「关于」面板。 |

配置文件位于仓库根目录 `config.json`，敏感字段均以设备指纹派生密钥加密存储，迁移到新设备后需重新输入 API Key。

## Web API（用于自动化集成）
- `GET /api/config`：读取当前配置、版本信息、Token 统计。
- `POST /api/config`：提交 JSON 更新配置；支持 `ClearVlmApiKey` / `ClearLlmApiKey` 清除敏感字段。
- `POST /api/process`：multipart/form-data，包含 `topic` 与 `files[]`，返回 run id。
- `GET /api/run-status/<run_id>`：轮询任务状态、日志、Token 用量以及生成的文件路径。
- `GET /outputs/<path>`：访问生成的原图或批改报告。

## 日志与故障排查
- 控制台会输出端口探测、API 请求摘要和异常信息。
- Web UI：结果卡片实时显示每个文件的日志及错误信息。
- 常见问题排查：
  - **配置缺失**：缺少必填项时，后端会在任务开始前返回具体提示。
  - **网络或权限错误**：请确认模型名称、Key 是否正确，服务是否支持图像输入，并适当调整 `RequestTimeout` / `RetryDelay`。

## 开发者指南
- 核心依赖：Flask（Web 服务）、cryptography（配置加密）、openai SDK（兼容多家服务）、markdown（报告渲染）。
- 调试技巧：
  ```bash
  python3 web_app.py   # 直接运行 Flask 应用
  python3 main.py      # 启动正式入口，包含日志与端口选择
  ```
- 如需打包为单文件可执行程序：
  ```bash
  pyinstaller --noconsole --onefile main.py
  ```
  生成的可执行文件位于 `dist/`。

## 贡献与许可
- 欢迎通过 Issue / Pull Request 分享想法与改进。
- 如果这个项目对你有帮助，别忘了点个 ⭐️。
- 本项目遵循 [MIT License](LICENSE)。
