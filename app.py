import streamlit as st
import google.generativeai as genai
import fitz
import traceback
import time
import re

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

# ## 代码生成器 (终极版 - 只生成<section>块，并强调使用样式) ##
CODE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位精通HTML的前端开发专家，拥有像素级的代码保真能力。你的核心任务是根据一份结构化的Markdown大纲，为每一页幻灯片生成对应的、**带有正确CSS类的** HTML `<section>` 元素。

关键指令:
1.  **应用模板样式:** 在生成代码时，你必须分析大纲内容，并应用HTML模板中可能存在的CSS类，例如 `.slide`, `.title-slide`, `.research-card`, `.citation-block`, `.stat-card-grid`, `.scroll-reveal` 等，以确保最终样式正确。例如，封面页应该使用 `<section class="slide title-slide" ...>`。
2.  **只生成幻灯片内容:** 你的输出必须 **只包含** `<section>...</section>` 代码块的序列。
3.  **禁止额外代码:** 绝对不要包含 `<html>`, `<body>`, `<head>`, `<!DOCTYPE>`, 或 `<script>` 标签。
4.  **输出纯净:** 你的输出应该直接以 `<section ...>` 开始，并以 `</section>` 结束。

输入:
你将收到一份PPT大纲 (PPT Outline)。

任务:
请立即开始工作，将以下这份大纲转化为一系列应用了正确样式的、连续的HTML `<section>` 代码块。
"""


# --- 所有Agent函数 ---
def parse_pdf(uploaded_file, debug_log_container):
    try:
        file_bytes = uploaded_file.getvalue()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = "".join(page.get_text() + "\n" for page in doc)
        debug_log_container.write(f"✅ PDF解析成功。总计 {len(full_text):,} 个字符。")
        return full_text
    except Exception as e:
        st.error(f"PDF解析失败: {e}")
        debug_log_container.error(f"PDF解析时出现异常: {traceback.format_exc()}")
        return None

def validate_model(api_key, model_name, debug_log_container):
    try:
        if not model_name or not model_name.strip(): return False
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if f"models/{model_name}" in available_models:
            debug_log_container.success(f"✅ 模型 `{model_name}` 验证通过！")
            return True
        else:
            st.error(f"**模型验证失败!** `{model_name}` 不存在。")
            return False
    except Exception as e:
        st.error(f"**API Key验证失败!**")
        debug_log_container.error(f"验证API Key时异常: {traceback.format_exc()}")
        return False

def call_gemini(api_key, prompt_text, ui_placeholder, model_name, debug_log_container):
    try:
        debug_log_container.write(f"--- \n准备调用AI: `{model_name}`...")
        debug_log_container.write(f"**发送的Prompt长度:** `{len(prompt_text):,}` 字符")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        collected_chunks = []
        def stream_and_collect(stream):
            for chunk in stream:
                if hasattr(chunk, 'text'):
                    text_part = chunk.text
                    collected_chunks.append(text_part)
                    yield text_part

        response_stream = model.generate_content(prompt_text, stream=True)
        ui_placeholder.write_stream(stream_and_collect(response_stream))
        
        full_response_str = "".join(collected_chunks)
        debug_log_container.write(f"✅ AI流式响应成功完成。收集到 {len(full_response_str):,} 个字符。")
        return full_response_str
    except Exception as e:
        ui_placeholder.error(f"🚨 **AI调用失败!**\n\n`{e}`")
        debug_log_container.error(f"--- AI调用时发生严重错误 ---\n{traceback.format_exc()}")
        return None

def extract_clean_outline(raw_output, debug_log_container):
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
    except Exception as e:
        debug_log_container.error(f"提取大纲时发生意外错误: {traceback.format_exc()}")
        return None

# ## NEW: 清理AI生成的HTML代码块，移除“废话”和代码标记 ##
def clean_generated_html(raw_html, debug_log_container):
    """
    清理AI生成的HTML代码，移除任何前导文本和Markdown代码块标记。
    """
    try:
        # 寻找第一个<section>标签的开始位置
        first_section_pos = raw_html.find("<section")
        if first_section_pos == -1:
            debug_log_container.error("❌ AI生成的代码中不包含任何`<section>`标签。")
            return None
        
        # 从第一个<section>开始，截取所有后续内容
        cleaned_html = raw_html[first_section_pos:]
        
        # 移除可能存在的Markdown代码块标记
        cleaned_html = cleaned_html.replace("```html", "").replace("```", "").strip()
        
        debug_log_container.success("✅ 已清理AI生成的幻灯片HTML内容。")
        return cleaned_html
    except Exception as e:
        debug_log_container.error(f"清理生成的HTML时出错: {traceback.format_exc()}")
        return None


# --- Streamlit UI ---
st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 AI学术汇报一键生成器 (最终版)")
with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("请输入您的Google Gemini API Key", type="password")
    model_options = [
        
        'gemini-2.0-flash',
        'gemini-2.5-flash',
        'gemini-2.5-pro'
    ]
    selected_model = st.selectbox("选择AI模型", model_options, index=0)

col1, col2 = st.columns(2)
with col1: pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])
with col2: html_template = st.file_uploader("2. 上传您的**原始**HTML模板", type=['html'])

if 'final_html' not in st.session_state: st.session_state.final_html = None

# --- 主流程 (采用最终的“智能热替换”逻辑) ---
if st.button("🚀 开始生成汇报", use_container_width=True, disabled=(not api_key or not pdf_file or not html_template)):
    st.session_state.final_html = None
    progress_container = st.container()
    progress_text = progress_container.empty()
    progress_bar = progress_container.progress(0)
    
    with st.expander("🐞 **调试日志 (点击展开查看详细流程)**", expanded=True):
        debug_log_container = st.container()

    total_start_time = time.time()

    if not validate_model(api_key, selected_model, debug_log_container): st.stop()
    progress_bar.progress(5)

    paper_text = parse_pdf(pdf_file, debug_log_container)
    if paper_text:
        progress_bar.progress(10)
        
        progress_text.text(f"步骤 1/3: 正在深度分析生成大纲...")
        prompt_for_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
        outline_placeholder = st.empty()
        markdown_outline = call_gemini(api_key, prompt_for_outline, outline_placeholder, selected_model, debug_log_container)
        
        if markdown_outline:
            progress_bar.progress(60)
            outline_placeholder.empty()

            cleaned_outline = extract_clean_outline(markdown_outline, debug_log_container)
            if cleaned_outline:
                progress_bar.progress(70)
                
                progress_text.text(f"步骤 2/3: 正在生成带有样式的幻灯片内容...")
                prompt_for_sections = "".join([CODE_GENERATION_PROMPT_TEMPLATE, "\n\n--- PPT Outline ---\n", cleaned_outline])
                sections_placeholder = st.empty()
                generated_slides_html_raw = call_gemini(api_key, prompt_for_sections, sections_placeholder, selected_model, debug_log_container)

                if generated_slides_html_raw:
                    progress_bar.progress(85)
                    sections_placeholder.empty()

                    # ## 这是修复所有问题的核心步骤 ##
                    progress_text.text(f"步骤 3/3: 正在清理并智能组装最终文件...")
                    
                    # 1. 清理AI生成的代码，移除“废话”
                    generated_slides_html = clean_generated_html(generated_slides_html_raw, debug_log_container)

                    if generated_slides_html:
                        # 2. 读取原始模板，执行“热替换”
                        template_code = html_template.getvalue().decode("utf-8")
                        try:
                            # 3. 用Python进行100%可靠的替换，保留所有脚本和样式
                            final_html_code = re.sub(
                                r'(<main[^>]*>)(.*?)(</main>)', 
                                lambda m: f"{m.group(1)}\n{generated_slides_html}\n{m.group(3)}",
                                template_code, 
                                count=1, 
                                flags=re.DOTALL | re.IGNORECASE
                            )
                            if final_html_code == template_code: raise ValueError("未能在模板中找到<main>标签对进行替换。")

                            debug_log_container.success(f"✅ 最终HTML组装成功！")
                            st.session_state.final_html = final_html_code
                            progress_text.text(f"🎉 全部完成！")
                            progress_bar.progress(100)
                        except Exception as e:
                            st.error(f"智能组装文件时出错: {e}")
                    else:
                        st.error("清理AI生成的HTML内容后为空，无法继续。")
                else:
                    st.error("AI未能生成有效的幻灯片HTML内容。")
            else:
                st.error("无法从AI响应中提取出有效的大纲。")

if st.session_state.get('final_html'):
    st.download_button(label="📥 下载您的学术汇报", data=st.session_state.final_html.encode('utf-8'), file_name='my_presentation.html', mime='text/html', use_container_width=True)
