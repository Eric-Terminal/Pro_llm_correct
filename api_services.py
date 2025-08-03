import base64
from typing import Dict, Any
from config_manager import ConfigManager
import os
import mimetypes
import re
from openai import OpenAI

# 定义默认的LLM Prompt模板。使用`.format()`方法进行后续的动态填充。
DEFAULT_LLM_PROMPT_TEMPLATE = """# ESSAY TOPIC
{topic}

# INSTRUCTIONS FOR AI (Process in English)
## 1. ROLE & GOAL
You are a highly experienced senior high school English teacher. Your task is to provide a detailed, constructive, and encouraging evaluation of a student's essay.
## 2. INPUT DATA
You will receive a quantitative `<wscore>` and the full `<text>` of the essay. The essay is based on the topic provided above.
## 3. GRADING LOGIC (Total Score: 15 points)
- **Content & Language (12 points):** Evaluate this based on grammar, vocabulary, sentence structure, etc., in relation to the essay topic.
- **Handwriting & Presentation (3 points):** Calculate the score by first getting a raw score (`Raw Score = wscore * 3`), and then rounding the `Raw Score` **up** to the nearest half-point (0.5).
    - *Rounding Logic Example:* A raw score of 2.49 becomes 2.5. A raw score of 2.51 becomes 3.0. A raw score of 2.50 remains 2.5. A score of 0 remains 0.
## 4. FINAL TASK
Analyze the text, calculate scores, and present your feedback in **Simplified Chinese** using the precise Markdown format specified below.
#--- End of English Instructions ---
# OUTPUT SPECIFICATION (MUST BE IN SIMPLIFIED CHINESE)
# 请严格使用以下Markdown格式，并用简体中文填充所有内容，优点可以两个到三个，问题建议要把全部问题找出来并且解析，都要遵循类似格式。


###【作文内容】
*   **作文文本:** [在此处粘贴完整的作文文本。]
### 【综合评价】
(在此处用一两句鼓励性的话，对本次作文进行总体概述。)
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
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager

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

    def process_essay_image(self, file_path: str, topic: str) -> str:
        """
        执行完整的两步式作文批改流程：
        1. VLM调用：分析作文图片，提取手写文本和书写质量分数。
        2. LLM调用：基于VLM的输出和作文题目，生成详细的批改报告。
        """
        # --- 步骤 1: 调用VLM进行图像分析 ---
        vlm_client = OpenAI(
            api_key=self.config.get("VlmApiKey"),
            base_url=self.config.get("VlmUrl")
        )
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
        
        vlm_model = self.config.get("VlmModel", "gemini-2.5-pro")
        vlm_response = vlm_client.chat.completions.create(model=vlm_model, messages=vlm_messages, max_tokens=4096, temperature=1)
        vlm_output = vlm_response.choices[0].message.content or ""
        
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
        llm_client = OpenAI(
            api_key=self.config.get("LlmApiKey"),
            base_url=self.config.get("LlmUrl")
        )
        
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

        llm_model = self.config.get("LlmModel", "gemini-2.5-pro")
        llm_response = llm_client.chat.completions.create(model=llm_model, messages=llm_messages, temperature=1, max_tokens=16384)
        final_report = llm_response.choices[0].message.content or "错误：AI未能生成报告。"

        return final_report