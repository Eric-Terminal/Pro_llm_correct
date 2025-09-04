import base64
from typing import Dict, Any, Tuple, Optional
from config_manager import ConfigManager
from markdown_renderer import create_markdown_renderer
import os
import mimetypes
import re
from openai import OpenAI
import time
import logging

# 定义默认的LLM Prompt模板。使用`.format()`方法进行后续的动态填充。
DEFAULT_LLM_PROMPT_TEMPLATE = """# ESSAY TOPIC
{topic}

# INSTRUCTIONS FOR AI (Process in English)
## 1. ROLE & GOAL
You are a highly experienced senior high school English teacher specializing in the Chinese National College Entrance Examination (Gaokao). Your goal is to provide a detailed, constructive, and encouraging evaluation of a student's essay, correctly identifying the essay type and applying the appropriate scoring standard.

## 2. INPUT DATA
You will receive three pieces of data:
- `<topic>`: For "Application Writing", this is the essay prompt. For "Read and Continue Writing", this is the initial story provided to the student.
- `<wscore>`: A quantitative handwriting quality score from 0.0 to 1.0.
- `<text>`: The full text of the student's handwritten essay.

## 3. STEP 1: IDENTIFY ESSAY TYPE
First, you MUST determine which of the two following Gaokao essay types this is. This decision will change the total score.
*   **TYPE A: Application Writing (应用文)**
    *   **Clues:** The total word count of the student's `<text>` is shorter, typically around 80-100 words. The `<topic>` is a straightforward instruction (e.g., "Write a letter to...").
    *   **Total Score:** 15 points.
*   **TYPE B: Read and Continue Writing (读后续写)**
    *   **Clues:** The total word count of the student's `<text>` is longer, typically around 150 words. The `<topic>` contains a substantial story. The student's `<text>` will consist of two distinct paragraphs, and the beginning of each paragraph will match the starting sentences provided in the original exam prompt.
    *   **Total Score:** 25 points.

## 4. STEP 2: APPLY SCORING LOGIC
Based on the identified essay type, apply the corresponding grading logic. The Handwriting score calculation is the same for both.
*   **Handwriting & Presentation Score (通用卷面分计算):**
    *   This sub-score is always out of **3 points**.
    *   **Calculation:** Get a raw score (`Raw Score = wscore * 3`). Then, round the `Raw Score` **up** to the nearest half-point (0.5).
    *   **Rounding Example:** A raw score of 2.49 becomes 2.5. A raw score of 2.51 becomes 3.0. A score of 2.50 remains 2.5.

*   **GRADING FOR TYPE A: Application Writing (Total 15)**
    *   **Content & Language (12 points):** Evaluate grammar, vocabulary, sentence structure, and relevance to the topic.
    *   **Handwriting & Presentation (3 points):** Use the calculation described above.
    *   **Final Score:** (Content & Language Score) + (Handwriting Score) out of 15.

*   **GRADING FOR TYPE B: Read and Continue Writing (Total 25)**
    *   **Content & Language (22 points):** Evaluate the quality of the continuation. Key criteria include: coherence with the original story, logical plot development, character consistency, richness of detail, and advanced use of grammar, vocabulary, and sentence structures.
    *   **Handwriting & Presentation (3 points):** Use the calculation described above.
    *   **Final Score:** (Content & Language Score) + (Handwriting Score) out of 25.

## 5. FINAL TASK
Analyze the text, identify the essay type, calculate the scores, and present your complete feedback in **Simplified Chinese** using the precise Markdown format specified in the "OUTPUT SPECIFICATION" section. Ensure the final score correctly reflects the total points possible (15 or 25).
#--- End of English Instructions ---
# OUTPUT SPECIFICATION (MUST BE IN SIMPLIFIED CHINESE)
#你应该综合考量书写和内容的评分，内容是主要的，字体是次要的，例如对于写的内容和作文毫无关系但是字很好看的，不应该给3分而是直接给0分
# 请使用以下Markdown格式，并用简体中文填充所有内容，优点找不到不要硬找，问题建议要把全部问题找出来并且解析，都要遵循类似格式。对于分数的总分则必须由你选择是15分还是25分(不一定是下面的15分)。


###【作文内容】
*   **作文文本:** [在此处粘贴完整的作文文本。]
### 【综合评价】
(在此处用一两句鼓励性的话，对本次作文进行总体概述。如果写的太烂了也可以骂人)
### 【亮点与优点】
*   **(优点1):** [具体描述作文内容或语言上的一个亮点。]
*   **(优点2):** [具体描述另一个优点。]
*   **(优点3):（以此类推，不限制数量，但建议控制在3个以内。）
### 【问题与修改建议】
*   **[问题1 - 语法/拼写错误]:**
    *   **原文句子:** "[引用出现错误的原文句子]"
    *   **问题分析:** [简要说明错误类型。]
    *   **修改建议:** "[写出修改后的正确句子]"
*   **[问题2 - 表达/逻辑]:**
    *   **原文句子:** "[引用表达欠佳的原文句子]"
    *   **问题分析:** [说明问题所在。]
    *   **修改建议:** "[提供一个更好的表达方式。]
*   **[问题3 - （以此类推，不限制数量，但建议控制在3个以内。）]:**
    *   **原文句子:** "[说明问题所在。]"
    *   **问题分析:** [说明问题所在。]
### 【分数评估】
*   **内容与语言分 (Content & Language):** [分数] / 12
*   **卷面与书写分 (Handwriting & Presentation):** [分数] / 3
*   ---
*   **最终得分 (Final Score):** **[总分] / 15**

# INPUT DATA FOR THIS TASK

<wscore>{wscore}</wscore>
<text>
{essay_text}
</text>
"""

class ApiService:
    """封装了与外部API（VLM和LLM）交互的所有逻辑。"""
    def __init__(self, config_manager: ConfigManager, ui_queue: Optional[Any] = None):
        self.config = config_manager
        self.ui_queue = ui_queue
        self.markdown_renderer = create_markdown_renderer(config_manager)

    def _log(self, message: str):
        """将日志消息放入UI队列。"""
        if self.ui_queue:
            self.ui_queue.put(("log", message))

    def _encode_image_to_base64_url(self, image_path: str) -> str:
        """将本地图片文件编码为Base64数据URL。"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found at: {image_path}")
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith('image'):
            raise ValueError(f"File is not a recognizable image type: {mime_type}")
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        return f"data:{mime_type};base64,{encoded_string}"

    def process_essay_image(self, file_path: str, topic: str) -> Tuple[str, Dict[str, int], Dict[str, int]]:
        """
        执行完整的两步式作文批改流程：
        1. VLM调用：分析作文图片，提取手写文本和书写质量分数。
        2. LLM调用：基于VLM的输出和作文题目，生成详细的批改报告。
        返回: (批改报告, VLM token使用情况, LLM token使用情况)
        """
        # --- 步骤 1: 调用VLM进行图像分析 ---
        try:
            max_retries = int(self.config.get("MaxRetries", 3))
            retry_delay = int(self.config.get("RetryDelay", 5))
        except (ValueError, TypeError):
            max_retries = 3
            retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                vlm_client = OpenAI(
                    api_key=self.config.get("VlmApiKey"),
                    base_url=self.config.get("VlmUrl")
                )
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                self._log(f"VLM客户端创建失败，{retry_delay}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
        base64_image_url = self._encode_image_to_base64_url(file_path)

        vlm_prompt = """# ROLE
You are a high-precision OCR (Optical Character Recognition) and handwriting analysis engine. Your only job is to analyze the provided image and output structured data. Do not add any conversational text or explanations.
# TASK
Analyze the handwriting quality and extract all text from the image.
## 1. Handwriting Quality Analysis:
- Critically evaluate the handwriting on a continuous scale from 0.0 to 1.0.
- The scoring must be stringent. A score of 1.0 is reserved for flawless, machine-printed-like perfection, which is virtually unattainable.
- **Score Tiers:**
    - **0.90-0.99:** Near-perfect, professional calligrapher level. Extremely rare.
    - **0.80-0.89:** Excellent, clear, consistent, and aesthetically pleasing. The best a top student can achieve.
    - **0.70-0.79:** Good and very legible, but with minor inconsistencies in size or spacing.
    - **0.60-0.69:** Clear and legible, but with noticeable inconsistencies.
    - **Below 0.60:** Legibility is impacted.
- Output this score enclosed in a single <wscore> XML tag.
## 2. Full Text Extraction:
- Perform a high-accuracy OCR on the entire image.
- Preserve the original line breaks and paragraph structure as best as possible.
- Output the full extracted text enclosed in a single <text> XML tag.
# OUTPUT FORMAT
Strictly adhere to the following format. Do not output anything else.
<wscore>[Your calculated score, e.g., 0.85]</wscore>
<text>
[The full extracted text from the image goes here.]
</text>"""
        vlm_messages = [{"role": "user", "content": [{"type": "text", "text": vlm_prompt}, {"type": "image_url", "image_url": {"url": base64_image_url}}]}]
        
        vlm_model = self.config.get("VlmModel", "Pro/THUDM/GLM-4.1V-9B-Thinking")
        for attempt in range(max_retries):
            try:
                vlm_response = vlm_client.chat.completions.create(model=vlm_model, messages=vlm_messages, max_tokens=4096, temperature=1)
                vlm_output = vlm_response.choices[0].message.content or ""
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                self._log(f"VLM调用失败，{retry_delay}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
        
        vlm_usage = {
            "prompt_tokens": vlm_response.usage.prompt_tokens if vlm_response.usage else 0,
            "completion_tokens": vlm_response.usage.completion_tokens if vlm_response.usage else 0,
        }
        
        # 解析VLM返回的XML格式输出，提取分数和文本
        wscore_match = re.search(r'<wscore>(.*?)</wscore>', vlm_output, re.DOTALL)
        text_match = re.search(r'<text>(.*?)</text>', vlm_output, re.DOTALL)
        original_wscore = float(wscore_match.group(1).strip()) if wscore_match else 0.0
        essay_text = text_match.group(1).strip() if text_match else "错误：无法从图片中提取文本。"
        
        try:
            sensitivity_factor = float(self.config.get("SensitivityFactor", "1.0"))
        except (ValueError, TypeError):
            # 如果配置的敏感度因子无效，则使用默认值1.0
            sensitivity_factor = 1.0 
            
        wscore = original_wscore ** sensitivity_factor

        if not text_match:
            raise ValueError(f"VLM未能按预期格式返回，无法解析文本。模型返回：\n{vlm_output}")

        # --- 步骤 2: 调用LLM生成批改报告 ---
        for attempt in range(max_retries):
            try:
                llm_client = OpenAI(
                    api_key=self.config.get("LlmApiKey"),
                    base_url=self.config.get("LlmUrl")
                )
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                self._log(f"LLM客户端创建失败，{retry_delay}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
        
        # 从配置加载Prompt模板，若用户未定义则使用默认模板
        prompt_template = self.config.get("LlmPromptTemplate")
        if not prompt_template:
            prompt_template = DEFAULT_LLM_PROMPT_TEMPLATE
        
        # 使用作文题目、书写分数和识别出的文本填充Prompt模板
        final_llm_prompt = prompt_template.format(
            topic=topic,
            wscore=wscore,
            essay_text=essay_text
        )
        
        llm_messages = [{"role": "user", "content": final_llm_prompt}]

        llm_model = self.config.get("LlmModel", "moonshotai/Kimi-K2-Instruct")
        for attempt in range(max_retries):
            try:
                llm_response = llm_client.chat.completions.create(model=llm_model, messages=llm_messages, temperature=1, max_tokens=16384)
                final_report = llm_response.choices[0].message.content or "错误：AI未能生成报告。"
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    final_report = f"错误：AI生成报告失败（达到最大重试次数 {max_retries} 次）"
                else:
                    self._log(f"LLM调用失败，{retry_delay}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)

        llm_usage = {
            "prompt_tokens": llm_response.usage.prompt_tokens if llm_response.usage else 0,
            "completion_tokens": llm_response.usage.completion_tokens if llm_response.usage else 0,
        }

        # 渲染Markdown为HTML（如果配置开启）
        html_path = None
        if self.markdown_renderer:
            # 定义HTML报告的文件名
            report_base_name = os.path.splitext(file_path)[0]
            html_output_path = f"{report_base_name}_report.html"
            
            html_path = self.markdown_renderer.render_markdown_to_html_file(final_report, html_output_path)
            if html_path:
                self._log(f"已生成HTML报告: {os.path.basename(html_path)}")
        
        return final_report, vlm_usage, llm_usage, html_path