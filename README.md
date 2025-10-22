# AI 作文批改助手 ✨

(＾▽＾)ﾉﾞ 欢迎使用 AI 作文批改助手！这是一款专为教育工作者和学生设计的本地 Web 应用，能够像经验丰富的英语老师一样，自动批改手写英文作文图片，并生成专业详细的批改报告。

## ✨ 核心特色功能

### 🤖 双AI引擎智能处理
- **视觉语言模型(VLM)**: 专业的手写文字识别(OCR)和书写质量评估，给出精准的卷面分数
- **大语言模型(LLM)**: 深度内容分析，提供专业的语法纠错和写作建议
- **智能作文类型识别**: 自动识别应用文(15分制)和读后续写(25分制)两种高考作文类型

### ⚙️ 极致灵活配置
- **服务独立配置**: VLM和LLM支持完全独立的API服务、密钥和模型配置
- **评分标准可调**: 书写质量"敏感度因子"自由调节，适应不同评分要求
- **Prompt模板开放**: 核心批改指令完全可自定义，打造个性化批改风格

### 🚀 高效并发处理
- 多线程并发引擎，支持批量处理任意数量的作文图片
- 智能任务调度，大幅提升批改效率，节省宝贵时间
- 实时进度显示和详细日志输出，随时掌握处理状态

### 🔒 企业级安全保障
- 军事级加密算法保护API密钥，防止敏感信息泄露
- 本地配置文件加密存储，确保账户安全无忧
- 透明的Token使用统计，方便成本控制

### 📊 专业输出格式
- **Markdown源文件**: 完整的批改报告，支持进一步编辑和定制
- **HTML可视化报告**: 美观易读的网页格式，方便分享和查看
- **详细错误分析**: 语法错误、表达问题、修改建议一应俱全
- **精准分数评估**: 专业的评分体系，符合高考评分标准

---

##  使用指南

### 快速开始
1. **下载程序**: 前往 [Releases页面](https://github.com/Eric-Terminal/Pro_llm_correct/releases) 下载最新版本
2. **启动 Web UI**:
   - 在终端运行 `python3 main.py`
   - 程序会从 4567 端口起寻找可用端口，并自动打开浏览器访问 Web 界面
3. **配置服务**:
   - 通过顶部导航切换到“服务设置”页，填写 VLM/LLM 的 URL、API Key、模型名称等参数
   - 可自定义 Prompt 模板、并发数量、重试策略与输出目录
   - 密钥字段不会回显；若提示“已保存”，留空即可沿用原值，输入新值即可覆盖
   - 点击“保存设置”即可持久化到本地 `config.json`（密钥自动加密）
4. **上传批改**:
   - Web 首页默认停留在“批改作文”页，在表单中输入作文题目或场景说明
   - 上传需要批改的作文照片（支持多选）
   - 点击“开始批改”，浏览器会实时显示每个文件的处理状态与日志
5. **查看报告**:
   - 所有输出默认保存在 `output_reports/<时间戳>/` 目录
   - 结果卡片中提供 Markdown/HTML 链接，可直接在浏览器查看或下载

### 输出文件说明
- 默认保存在 `output_reports/<时间戳>/` 目录
- `原文件名_report.md`: Markdown 格式详细批改报告
- `原文件名_report.html`: HTML 可视化批改报告
- 包含: 作文内容、综合评价、亮点优点、问题建议、分数评估

---

## 🛠️ 开发者指南

### 环境搭建
```bash
# 1. 克隆仓库
git clone https://github.com/Eric-Terminal/Pro_llm_correct.git
cd Pro_llm_correct

# 2. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt
# 需要确保系统已安装 curl（macOS/Linux 默认自带，Windows 可安装 Git Bash 或使用 WSL）

# 4. 运行程序
python3 main.py
```

### 项目打包
```bash
# 打包为独立可执行文件
pyinstaller --noconsole --onefile main.py

# 打包好的程序在 dist/ 目录
```

### 技术架构
- **前端**: Flask Web 服务 + 原生 HTML/CSS（玻璃拟态苹果风界面）
- **核心**: 双AI引擎架构 (VLM + LLM)
- **安全**: cryptography 加密存储配置
- **并发**: threading + concurrent.futures.ThreadPoolExecutor
- **输出**: Markdown/HTML 报告（内置样式渲染器）

---

## 📝 配置说明

### 必需配置项
- `VlmUrl`: VLM服务地址
- `VlmApiKey`: VLM服务密钥（自动加密）
- `VlmModel`: VLM模型名称
- `LlmUrl`: LLM服务地址  
- `LlmApiKey`: LLM服务密钥（自动加密）
- `LlmModel`: LLM模型名称

### 可选配置项
- `SensitivityFactor`: 书写评分敏感度因子（默认1.5）
- `MaxWorkers`: 最大并发数（默认4）
- `MaxRetries`: 最大重试次数（默认3）
- `RetryDelay`: 重试延迟秒数（默认5）
- `RequestTimeout`: 单次 API 请求超时时长（秒，默认120）
- `SaveMarkdown`: 是否保存Markdown文件（默认True）
- `RenderMarkdown`: 是否渲染HTML报告（默认True）

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。您可以自由地使用、修改和分发本软件，只需保留原始的版权声明即可。

---

## 🤝 贡献与支持

如果您在使用过程中遇到问题或有改进建议，欢迎：
- 提交 [Issue](https://github.com/Eric-Terminal/Pro_llm_correct/issues)
- 发起 [Pull Request](https://github.com/Eric-Terminal/Pro_llm_correct/pulls)
- 给项目点个 ⭐ Star 支持一下！

---

*由 Eric-Terminal 精心开发。希望这个工具能够帮助更多的教育工作者和学生！(｡･ω･｡)ﾉ♡*
