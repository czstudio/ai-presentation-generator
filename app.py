import streamlit as st
import fitz
import traceback
import time
import re
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from abc import ABC, abstractmethod
from io import BytesIO

# 需要安装的依赖包
# pip install streamlit PyMuPDF python-pptx openai anthropic google-generativeai

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.enum.text import PP_ALIGN
    from pptx.dml.color import RGBColor
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# --- 配置区域 ---
@dataclass
class APIConfig:
    """API配置类"""
    openai_key: str = ""
    anthropic_key: str = ""
    gemini_key: str = ""

# 默认配置 - 用户可以在这里预设API Keys
DEFAULT_CONFIG = APIConfig(
    gemini_key="",      # 在这里填入你的Gemini API Key
    openai_key="",      # 在这里填入你的OpenAI API Key
    anthropic_key=""    # 在这里填入你的Claude API Key
)

# --- AI厂商抽象接口 ---
class AIProvider(ABC):
    """AI厂商统一接口"""
    
    @abstractmethod
    def call_api(self, prompt: str, model: str, api_key: str, stream_callback=None) -> Optional[str]:
        """调用AI API"""
        pass
    
    @abstractmethod
    def get_models(self) -> List[str]:
        """获取可用模型列表"""
        pass
    
    @abstractmethod
    def validate_key(self, api_key: str) -> bool:
        """验证API Key"""
        pass

class GeminiProvider(AIProvider):
    """Google Gemini Provider"""
    
    def get_models(self) -> List[str]:
        return ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
    
    def validate_key(self, api_key: str) -> bool:
        if not GEMINI_AVAILABLE or not api_key:
            return False
        try:
            genai.configure(api_key=api_key)
            list(genai.list_models())
            return True
        except:
            return False
    
    def call_api(self, prompt: str, model: str, api_key: str, stream_callback=None) -> Optional[str]:
        try:
            genai.configure(api_key=api_key)
            ai_model = genai.GenerativeModel(model)
            
            if stream_callback:
                response_stream = ai_model.generate_content(prompt, stream=True)
                collected_chunks = []
                for chunk in response_stream:
                    if hasattr(chunk, 'text'):
                        text_part = chunk.text
                        collected_chunks.append(text_part)
                        stream_callback(text_part)
                return "".join(collected_chunks)
            else:
                response = ai_model.generate_content(prompt)
                return response.text if hasattr(response, 'text') else None
        except Exception as e:
            st.error(f"Gemini API调用失败: {e}")
            return None

class OpenAIProvider(AIProvider):
    """OpenAI Provider"""
    
    def get_models(self) -> List[str]:
        return ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo']
    
    def validate_key(self, api_key: str) -> bool:
        if not OPENAI_AVAILABLE or not api_key:
            return False
        try:
            client = openai.OpenAI(api_key=api_key)
            client.models.list()
            return True
        except:
            return False
    
    def call_api(self, prompt: str, model: str, api_key: str, stream_callback=None) -> Optional[str]:
        try:
            client = openai.OpenAI(api_key=api_key)
            
            if stream_callback:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True
                )
                collected_chunks = []
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        text_part = chunk.choices[0].delta.content
                        collected_chunks.append(text_part)
                        stream_callback(text_part)
                return "".join(collected_chunks)
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content
        except Exception as e:
            st.error(f"OpenAI API调用失败: {e}")
            return None

class AnthropicProvider(AIProvider):
    """Anthropic Claude Provider"""
    
    def get_models(self) -> List[str]:
        return ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229']
    
    def validate_key(self, api_key: str) -> bool:
        if not ANTHROPIC_AVAILABLE or not api_key:
            return False
        try:
            client = anthropic.Anthropic(api_key=api_key)
            # 简单验证，发送一个很短的消息
            client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return True
        except:
            return False
    
    def call_api(self, prompt: str, model: str, api_key: str, stream_callback=None) -> Optional[str]:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            
            if stream_callback:
                response = client.messages.create(
                    model=model,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True
                )
                collected_chunks = []
                for chunk in response:
                    if chunk.type == "content_block_delta":
                        text_part = chunk.delta.text
                        collected_chunks.append(text_part)
                        stream_callback(text_part)
                return "".join(collected_chunks)
            else:
                response = client.messages.create(
                    model=model,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text
        except Exception as e:
            st.error(f"Claude API调用失败: {e}")
            return None

class UniversalProvider(AIProvider):
    """通用HTTP API Provider (适用于Kimi, Doubao, 通义千问等)"""
    
    def __init__(self, provider_name: str, base_url: str, models: List[str]):
        self.provider_name = provider_name
        self.base_url = base_url
        self.models = models
    
    def get_models(self) -> List[str]:
        return self.models
    
    def validate_key(self, api_key: str) -> bool:
        if not api_key:
            return False
        try:
            # 简单的验证请求
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            # 大多数API都有models端点
            response = requests.get(f"{self.base_url}/models", headers=headers, timeout=10)
            return response.status_code == 200
        except:
            return False
    
    def call_api(self, prompt: str, model: str, api_key: str, stream_callback=None) -> Optional[str]:
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": bool(stream_callback)
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                stream=bool(stream_callback),
                timeout=300
            )
            
            if stream_callback:
                collected_chunks = []
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            try:
                                json_data = json.loads(line[6:])
                                if 'choices' in json_data and json_data['choices']:
                                    delta = json_data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        text_part = delta['content']
                                        collected_chunks.append(text_part)
                                        stream_callback(text_part)
                            except:
                                continue
                return "".join(collected_chunks)
            else:
                result = response.json()
                return result['choices'][0]['message']['content']
                
        except Exception as e:
            st.error(f"{self.provider_name} API调用失败: {e}")
            return None

# 初始化所有AI厂商
PROVIDERS = {
    "Gemini": GeminiProvider(),
    "OpenAI": OpenAIProvider(),
    "Claude": AnthropicProvider(),
    "Kimi": UniversalProvider("Kimi", "https://api.moonshot.cn/v1", ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]),
    "Doubao": UniversalProvider("Doubao", "https://ark.cn-beijing.volces.com/api/v3", ["ep-20241022-******"]),  # 需要用户填入实际endpoint
    "通义千问": UniversalProvider("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", ["qwen-turbo", "qwen-plus", "qwen-max"]),
    "智谱AI": UniversalProvider("智谱AI", "https://open.bigmodel.cn/api/paas/v4", ["glm-4", "glm-4-plus", "glm-4-0520"]),
    "DeepSeek": UniversalProvider("DeepSeek", "https://api.deepseek.com/v1", ["deepseek-chat", "deepseek-coder"]),
    "硅基流动": UniversalProvider("硅基流动", "https://api.siliconflow.cn/v1", ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V2.5"])
}

# --- 提示词模板 (保持不变) ---
OUTLINE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位顶级的学术汇报设计师和内容策略师，同时具备出色的**"无图化设计" (Graphic-less Design)** 思维。你精通将复杂的学术论文转化为结构化、视觉化的演示文稿（PPT），并且擅长使用CSS样式、布局和文本符号来创造清晰、优雅的视觉效果，以最大限度地减少对外部图片或复杂SVG的依赖。

核心任务 (Core Task):
分析用户上传的学术文档，并生成一个结构化的、逐页的演示文稿大纲。这个大纲需要直接映射到一个预设的HTML汇报模板中。你需要决定将文档内容划分成多少页PPT是合适的（通常在10-15页之间），并为每一页设计内容和可通过简单代码实现的视觉元素。

关键原则 (Guiding Principles):
一页一核心: 每张幻灯片只传达一个核心观点。
化繁为简: 将长句转化为精炼的要点、短语或关键词。
逻辑流畅: 遵循标准的学术汇报逻辑（引言 -> 方法 -> 结果 -> 结论）。
提取关键: 直接从原文中提取关键术语、数据、结果和引用。
CSS优先，无图为主 (CSS First, Image-Free): 这是最重要的原则。 你必须优先考虑那些可以通过纯CSS、Emoji或基本HTML结构实现的视觉元素。绝对禁止建议使用外部图片链接。 仅在极其必要且形状极其简单（如圆形、箭头）的情况下，才建议使用SVG路径。

输出格式 (Required Output Format):
你必须严格按照以下Markdown格式为每一页幻灯片生成内容。使用 --- 分隔每一页。

---
**Slide:** [幻灯片页码，从1开始]
**Title:** [幻灯片标题]
**Purpose:** [幻灯片目的/类型，从以下选项中选择: Title, Overview, Background, Methodology, Data, Results, Analysis, Discussion, Conclusion, Future_Work, Acknowledgements]
**Content:**
- [要点1：简洁的短句或短语]
- [要点2：**加粗**关键术语]
- [要点3：直接引用原文的一句核心观点]
**Visual:**
  - **Type:** [从以下视觉类型中选择: `Symbol`, `Process`, `Chart`, `Table`, `Quote`, `Comparison`, `List`, `Text_Only`]
  - **Data:** [根据选择的Type提供结构化数据。这是最关键的部分，格式见下方说明。]
---

Visual.Data 格式说明 (已优化):
Type: Symbol
Data:
symbol: [一个Unicode Emoji表情符号]
text: [符号旁边的简短说明文字]
color_hint: [一个CSS颜色提示]

Type: Process
Data:
steps: [一个JSON数组]
style: [numbered-list, chevron-arrow]

Type: Chart
Data:
chart_type: [bar, line, pie]
title: [图表标题]
data_summary: [对图表核心数据的文字描述]

Type: Table
Data:
caption: [表格标题]
headers: [一个JSON数组]
rows: [一个包含多行数据的JSON数组]

Type: Quote
Data:
text: [引用的核心文本]
source: [引用来源]

Type: Comparison
Data:
item1_title: [对比项1的标题]
item1_points: [一个JSON数组]
item2_title: [对比项2的标题]
item2_points: [一个JSON数组]

Type: List 或 Type: Text_Only
Data: null

指令 (Instruction):
现在，请分析用户上传的这份学术文档。严格遵循以上所有规则和**"无图化设计"原则，为其生成一份完整的、逻辑清晰的、强调使用简单符号和CSS**进行视觉呈现的学术演示文稿大纲。请开始。
"""

CODE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位精通HTML、CSS和JavaScript的前端开发专家，拥有像素级的代码保真能力。你的核心任务是将结构化的Markdown大纲，无损地、精确地与一个预定义的HTML模板相结合，动态生成最终的、可直接运行的、高度专业的HTML文件。你对细节有极高的要求，尤其是在处理图像资源和数据可视化占位方面。

核心任务 (Core Task):
你将收到两份输入：
1. **PPT大纲 (PPT Outline):** 一份由AI预先生成的、结构化的Markdown文件。
2. **HTML模板 (HTML Template):** 一个完整的HTML文件，包含了所有必须的样式、脚本和关键资源（如Base64编码的校徽）。

你的任务是：
1. **解析大纲:** 逐页解析PPT大纲中的所有字段（Slide、Title、Purpose、Content、Visual等）。
2. **动态生成幻灯片:** 根据解析出的数据，为每一页幻灯片生成对应的HTML `<section>` 元素，并应用正确的CSS类。
3. **智能渲染视觉元素:**
   - **对于图表 (Visual.Type: Chart):** 绝不在页面上显示"占位符"字样。你应该在图表区域内，使用优雅的排版，将大纲中提供的 `Visual.Data.data_summary` (数据摘要文字) 直接展示出来。这为演讲者提供了一个讨论数据的起点，而不是一个空洞的占位符。
   - **对于符号 (Visual.Type: Symbol):** 将大纲中指定的Emoji符号 (`Visual.Data.symbol`) 直接作为文本插入到HTML中，并可选择性地使用 `Visual.Data.color_hint` 作为内联样式的颜色。
   - **对于其他类型:** 根据Visual.Type和Visual.Data智能生成相应的HTML结构。
4. **【最高优先级 - 铁律】保护关键资源:** 在整合代码时，必须完整、无误地保留HTML模板中所有的：
   - 整个`<head>`标签，包含所有的`<link>`和`<style>`
   - 整个`<script>`标签及其内部所有的JavaScript代码
   - 所有导航控件、页码指示器等非幻灯片内容
   - **特别重要:** 所有`<img>`标签及其`src`属性，尤其是那些包含 `data:image/svg+xml;base64,...` 的长字符串。绝不允许对这些资源链接进行任何形式的修改、缩短或删除。
5. **无缝整合:** 确保动态生成的幻灯片数量与底部的缩略图导航和演讲者备注的条目数量完全一致。
6. **代码整洁:** 生成的HTML代码必须有良好的缩进和可读性。

**【绝对禁止 - 输出要求】:**
- 你的最终输出 **绝对不能** 包含任何解释性文字或Markdown代码块标记
- 不要使用```html或```等Markdown代码块标记
- 不要在HTML前后添加任何解释性内容
- 输出必须是一个纯粹的HTML文本，直接以 `<!DOCTYPE html>` 开头，并以 `</html>` 结尾

指令 (Instruction):
以下是用户提供的 **PPT大纲 (PPT Outline)** 和 **HTML模板 (HTML Template)**。请你立即开始工作，严格遵循以上所有规则，特别是保护校徽等关键资源和优雅处理图表占位的指令，将大纲内容与模板代码结合，生成最终的、完整的、专业级的HTML文件。不要提供任何解释或评论，直接输出完整的HTML代码。
"""

# --- PPT生成器 ---
class PPTGenerator:
    """PPT生成器类"""
    
    def __init__(self):
        self.presentation = None
    
    def create_presentation(self, outline_data: str, template_path: str = None) -> BytesIO:
        """根据大纲创建PPT"""
        if not PPTX_AVAILABLE:
            raise ImportError("python-pptx库未安装，无法生成PPT文件")
        
        # 创建演示文稿
        if template_path:
            self.presentation = Presentation(template_path)
        else:
            self.presentation = Presentation()
            
        # 解析大纲
        slides_data = self._parse_outline(outline_data)
        
        # 生成幻灯片
        for slide_data in slides_data:
            self._create_slide(slide_data)
        
        # 保存到BytesIO
        ppt_buffer = BytesIO()
        self.presentation.save(ppt_buffer)
        ppt_buffer.seek(0)
        
        return ppt_buffer
    
    def _parse_outline(self, outline_text: str) -> List[Dict]:
        """解析大纲文本"""
        slides = []
        current_slide = {}
        
        lines = outline_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line == '---':
                if current_slide:
                    slides.append(current_slide)
                    current_slide = {}
                continue
            
            if line.startswith('**Slide:**'):
                current_slide['slide_num'] = line.split('**Slide:**')[1].strip()
            elif line.startswith('**Title:**'):
                current_slide['title'] = line.split('**Title:**')[1].strip()
            elif line.startswith('**Purpose:**'):
                current_slide['purpose'] = line.split('**Purpose:**')[1].strip()
            elif line.startswith('**Content:**'):
                current_slide['content'] = []
            elif line.startswith('- ') and 'content' in current_slide:
                current_slide['content'].append(line[2:].strip())
            elif line.startswith('**Visual:**'):
                current_slide['visual'] = {}
            elif line.startswith('  - **Type:**') and 'visual' in current_slide:
                current_slide['visual']['type'] = line.split('**Type:**')[1].strip()
        
        if current_slide:
            slides.append(current_slide)
            
        return slides
    
    def _create_slide(self, slide_data: Dict):
        """创建单个幻灯片"""
        # 根据purpose选择布局
        purpose = slide_data.get('purpose', 'Content')
        
        if purpose == 'Title':
            layout = self.presentation.slide_layouts[0]  # 标题布局
        else:
            layout = self.presentation.slide_layouts[1]  # 内容布局
            
        slide = self.presentation.slides.add_slide(layout)
        
        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = slide_data.get('title', '')
        
        # 设置内容
        content = slide_data.get('content', [])
        if content and len(slide.placeholders) > 1:
            body_shape = slide.placeholders[1]
            tf = body_shape.text_frame
            tf.clear()
            
            for i, item in enumerate(content):
                if i == 0:
                    tf.text = item
                else:
                    p = tf.add_paragraph()
                    p.text = item
                    p.level = 0

# --- 核心处理函数 ---
def parse_pdf(uploaded_file, debug_log_container):
    """解析PDF文件"""
    try:
        file_bytes = uploaded_file.getvalue()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = "".join(page.get_text() + "\n" for page in doc)
        debug_log_container.write(f"✅ PDF解析成功。总计 {len(full_text):,} 个字符。")
        return full_text
    except Exception:
        debug_log_container.error(f"PDF解析时出现异常: {traceback.format_exc()}")
        return None

def call_ai_api(provider_name: str, model: str, api_key: str, prompt: str, stream_callback=None, debug_log_container=None) -> Optional[str]:
    """统一AI API调用接口"""
    if provider_name not in PROVIDERS:
        if debug_log_container:
            debug_log_container.error(f"不支持的AI厂商: {provider_name}")
        return None
    
    provider = PROVIDERS[provider_name]
    
    if debug_log_container:
        debug_log_container.write(f"正在调用 {provider_name} - {model}...")
        debug_log_container.write(f"Prompt长度: {len(prompt):,} 字符")
    
    try:
        result = provider.call_api(prompt, model, api_key, stream_callback)
        if debug_log_container:
            debug_log_container.write(f"✅ {provider_name} API调用成功")
        return result
    except Exception as e:
        if debug_log_container:
            debug_log_container.error(f"❌ {provider_name} API调用失败: {e}")
        return None

def extract_clean_outline(raw_output, debug_log_container):
    """提取清洁的大纲"""
    try:
        match = re.search(r"\*\*\s*Slide\s*:\s*\*\*", raw_output)
        if not match:
            debug_log_container.error("❌ 在AI响应中未能找到任何`**Slide:**`标记。")
            return None
        first_slide_pos = match.start()
        last_divider_pos = raw_output.rfind("---", 0, first_slide_pos)
        cleaned_outline = raw_output[last_divider_pos:] if last_divider_pos != -1 else raw_output[first_slide_pos:]
        cleaned_outline = cleaned_outline.strip()
        if cleaned_outline.count("**Title:**") < 3:
            debug_log_container.warning("⚠️ 提取出的大纲结构不完整。")
        debug_log_container.success(f"✅ 已智能识别并提取出大纲内容。")
        return cleaned_outline
    except Exception:
        debug_log_container.error(f"提取大纲时发生意外错误: {traceback.format_exc()}")
        return None

def final_cleanup(raw_html, debug_log_container):
    """最终HTML清理"""
    try:
        debug_log_container.write(f"开始清理HTML，原始长度: {len(raw_html):,} 字符")
        
        html_start_pos = raw_html.find("<!DOCTYPE html>")
        if html_start_pos == -1:
            debug_log_container.warning("⚠️ 未找到`<!DOCTYPE html>`，尝试寻找`<html`标签")
            html_start_pos = raw_html.find("<html")
            if html_start_pos == -1:
                debug_log_container.error("❌ 未找到HTML起始标签")
                return None
        
        html_end_pos = raw_html.rfind("</html>")
        if html_end_pos == -1:
            debug_log_container.error("❌ 未找到HTML结束标签")
            return None
        
        html_content = raw_html[html_start_pos:html_end_pos + 7]
        html_content = html_content.strip()
        
        if not (html_content.startswith("<!DOCTYPE html>") or html_content.startswith("<html")):
            debug_log_container.error("❌ 清理后的HTML格式不正确")
            return None
            
        if not html_content.endswith("</html>"):
            debug_log_container.error("❌ 清理后的HTML结尾不正确")
            return None
        
        debug_log_container.success(f"✅ HTML清理完成！最终长度: {len(html_content):,} 字符")
        return html_content
        
    except Exception as e:
        debug_log_container.error(f"最终清理时出错: {traceback.format_exc()}")
        return None

# --- Streamlit UI ---
st.set_page_config(page_title="三大厂商AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 三大厂商AI学术汇报生成器 (精简版)")

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ AI厂商配置")
    
    # 选择AI厂商
    available_providers = list(PROVIDERS.keys())
    selected_provider = st.selectbox("选择AI厂商", available_providers, index=0)
    
    # 获取该厂商的可用模型
    models = PROVIDERS[selected_provider].get_models()
    selected_model = st.selectbox("选择模型", models, index=0)
    
    # API Key输入
    api_key_mapping = {
        "OpenAI": DEFAULT_CONFIG.openai_key,
        "Gemini": DEFAULT_CONFIG.gemini_key,
        "Claude": DEFAULT_CONFIG.anthropic_key
    }
    
    default_key = api_key_mapping.get(selected_provider, "")
    api_key = st.text_input(
        f"请输入{selected_provider} API Key", 
        value=default_key,
        type="password",
        help="💡 可以在代码中预设默认API Key"
    )
    
    # 验证API Key
    if api_key:
        if PROVIDERS[selected_provider].validate_key(api_key):
            st.success(f"✅ {selected_provider} API Key验证通过")
        else:
            st.error(f"❌ {selected_provider} API Key验证失败")
    
    st.divider()
    st.header("📄 输出格式")
    
    # 输出格式选择
    output_formats = st.multiselect(
        "选择输出格式",
        ["HTML演示文稿", "PPT文件"],
        default=["HTML演示文稿"]
    )

# 主界面
col1, col2 = st.columns(2)
with col1:
    pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])
with col2:
    html_template = st.file_uploader("2. 上传您的HTML模板 (可选)", type=['html'])

# 存储生成的结果
if 'results' not in st.session_state:
    st.session_state.results = {}

# 生成按钮
if st.button("🚀 开始生成汇报", use_container_width=True, 
             disabled=(not api_key or not pdf_file or not output_formats)):
    
    st.session_state.results = {}
    
    progress_container = st.container()
    progress_text = progress_container.empty()
    progress_bar = progress_container.progress(0)
    
    with st.expander("🐞 **调试日志**", expanded=False):
        debug_log_container = st.container()
    
    # 解析PDF
    paper_text = parse_pdf(pdf_file, debug_log_container)
    if not paper_text:
        st.error("PDF解析失败")
        st.stop()
    
    progress_bar.progress(10)
    
    # 生成大纲
    progress_text.text("步骤 1/3: 正在生成演示文稿大纲...")
    prompt_for_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
    
    outline_placeholder = st.empty()
    
    def stream_callback(text):
        # 可以在这里处理流式输出
        pass
    
    markdown_outline = call_ai_api(
        selected_provider, 
        selected_model, 
        api_key, 
        prompt_for_outline, 
        stream_callback, 
        debug_log_container
    )
    
    if not markdown_outline:
        st.error("大纲生成失败")
        st.stop()
    
    progress_bar.progress(40)
    outline_placeholder.empty()
    
    # 清理大纲
    progress_text.text("步骤 2/3: 正在处理大纲...")
    cleaned_outline = extract_clean_outline(markdown_outline, debug_log_container)
    
    if not cleaned_outline:
        st.error("大纲处理失败")
        st.stop()
    
    progress_bar.progress(50)
    
    # 生成HTML
    if "HTML演示文稿" in output_formats:
        if not html_template:
            st.error("生成HTML需要上传HTML模板")
        else:
            progress_text.text("步骤 3a/3: 正在生成HTML演示文稿...")
            
            template_code = html_template.getvalue().decode("utf-8")
            
            final_prompt = "".join([
                CODE_GENERATION_PROMPT_TEMPLATE,
                "\n\n--- PPT Outline ---\n",
                cleaned_outline,
                "\n\n--- HTML Template ---\n",
                template_code
            ])
            
            with st.spinner("正在生成HTML..."):
                final_html_raw = call_ai_api(
                    selected_provider,
                    selected_model,
                    api_key,
                    final_prompt,
                    None,
                    debug_log_container
                )
            
            if final_html_raw:
                final_html_code = final_cleanup(final_html_raw, debug_log_container)
                if final_html_code:
                    st.session_state.results['html'] = final_html_code
                    debug_log_container.success("✅ HTML生成成功！")
                else:
                    st.error("HTML清理失败")
            else:
                st.error("HTML生成失败")
    
    progress_bar.progress(70)
    
    # 生成PPT
    if "PPT文件" in output_formats:
        if not PPTX_AVAILABLE:
            st.error("PPT生成需要安装python-pptx库: pip install python-pptx")
        else:
            progress_text.text("步骤 3b/3: 正在生成PPT文件...")
            
            try:
                ppt_generator = PPTGenerator()
                ppt_buffer = ppt_generator.create_presentation(cleaned_outline)
                st.session_state.results['ppt'] = ppt_buffer.getvalue()
                debug_log_container.success("✅ PPT生成成功！")
            except Exception as e:
                st.error(f"PPT生成失败: {e}")
                debug_log_container.error(f"PPT生成错误: {traceback.format_exc()}")
    
    progress_bar.progress(100)
    progress_text.text("🎉 生成完成！")

# 下载区域
if st.session_state.results:
    st.header("📥 下载生成的文件")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if 'html' in st.session_state.results:
            st.download_button(
                label="📥 下载HTML演示文稿",
                data=st.session_state.results['html'].encode('utf-8'),
                file_name='presentation.html',
                mime='text/html',
                use_container_width=True
            )
    
    with col2:
        if 'ppt' in st.session_state.results:
            st.download_button(
                label="📥 下载PPT文件",
                data=st.session_state.results['ppt'],
                file_name='presentation.pptx',
                mime='application/vnd.openxmlformats-officedocument.presentationml.presentation',
                use_container_width=True
            )

# 依赖说明
st.sidebar.divider()
st.sidebar.header("📦 依赖库状态")
st.sidebar.write("✅ PyMuPDF")
st.sidebar.write("✅ python-pptx" if PPTX_AVAILABLE else "❌ python-pptx")
st.sidebar.write("✅ google-generativeai" if GEMINI_AVAILABLE else "❌ google-generativeai")
st.sidebar.write("✅ openai" if OPENAI_AVAILABLE else "❌ openai")
st.sidebar.write("✅ anthropic" if ANTHROPIC_AVAILABLE else "❌ anthropic")

if not PPTX_AVAILABLE:
    st.sidebar.info("💡 安装python-pptx以启用PPT生成功能")