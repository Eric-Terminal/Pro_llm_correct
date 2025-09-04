import os
import markdown
from config_manager import ConfigManager
from typing import Optional

class MarkdownRenderer:
    """Markdown渲染器，支持将Markdown文本渲染为带样式的HTML文件"""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def render_markdown_to_html_file(self, markdown_text: str, output_path: str) -> Optional[str]:
        """
        将Markdown文本渲染为带样式的HTML文件。

        Args:
            markdown_text: Markdown格式的文本。
            output_path: 输出HTML文件的路径。

        Returns:
            如果成功，返回生成的HTML文件路径；否则返回None。
        """
        # 检查配置中的RenderMarkdown设置，默认开启
        render_enabled = self.config_manager.get("RenderMarkdown")
        if render_enabled is None:
            # 如果配置中没有设置，使用默认值True
            render_enabled = True
        
        if not render_enabled:
            return None

        try:
            # 将Markdown转换为HTML
            html_body = markdown.markdown(markdown_text, extensions=['extra', 'tables'])
            
            # 组装完整的HTML文档，并嵌入CSS样式
            full_html = self._wrap_with_style(html_body)

            # 将HTML内容写入文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(full_html)
            
            return output_path
        except Exception as e:
            print(f"渲染Markdown到HTML文件时出错: {e}")
            return None
    
    def _wrap_with_style(self, html_body: str) -> str:
        """将HTML内容包裹在带有预设CSS样式的完整HTML结构中"""
        css_style = """
        <style>
            body {
                font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                line-height: 1.6;
                color: #333;
                background-color: #fff;
                padding: 20px;
                margin: 0;
            }
            h1, h2, h3, h4, h5, h6 {
                color: #2c3e50;
                margin-top: 1.5em;
                margin-bottom: 0.5em;
            }
            p {
                margin: 0.8em 0;
            }
            ul, ol {
                margin: 0.8em 0;
                padding-left: 2em;
            }
            li {
                margin: 0.3em 0;
            }
            code {
                background-color: #f8f9fa;
                padding: 0.2em 0.4em;
                border-radius: 3px;
                font-family: 'Monaco', 'Consolas', monospace;
            }
            pre {
                background-color: #f8f9fa;
                padding: 1em;
                border-radius: 5px;
                overflow-x: auto;
            }
            pre code {
                background: none;
                padding: 0;
            }
            blockquote {
                border-left: 4px solid #ddd;
                padding-left: 1em;
                margin-left: 0;
                color: #666;
            }
            table {
                border-collapse: collapse;
                width: 100%;
                margin: 1em 0;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 0.5em;
                text-align: left;
            }
            th {
                background-color: #f8f9fa;
                font-weight: bold;
            }
            .score {
                font-weight: bold;
                color: #e74c3c;
            }
            .comment {
                background-color: #fff3cd;
                padding: 10px;
                border-left: 4px solid #ffc107;
                margin: 10px 0;
            }
        </style>
        """
        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>作文批改报告</title>
            {css_style}
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """

# 工具函数
def create_markdown_renderer(config_manager: ConfigManager) -> MarkdownRenderer:
    """创建Markdown渲染器实例"""
    return MarkdownRenderer(config_manager)