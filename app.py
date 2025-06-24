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

Generated markdown
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
你是一位精通HTML的前端开发专家。你的核心任务是根据一份结构化的Markdown大纲，为每一页幻灯片生成对应的HTML `<section>` 元素。

关键指令:
1.  **只生成幻灯片内容:** 你的输出必须 **只包含** `<section>...</section>` 代码块。
2.  **禁止额外代码:** 绝对不要包含 `<html>`, `<body>`, `<head>`, `<!DOCTYPE>`, 或 `<script>` 标签。
3.  **严格遵循大纲:** 确保为Markdown大纲中的每一页都生成一个对应的 `<section>`。
4.  **智能渲染:** 在`<section>`内部，你需要将大纲中的内容和视觉提示（如表格、引用、符号）智能地转化为HTML结构。
5.  **输出纯净:** 你的输出应该直接以 `<section ...>` 开始，并以 `</section>` 结束。不要添加任何解释性文字。

输入:
你将收到一份PPT大纲 (PPT Outline)。

任务:
请立即开始工作，将以下这份大纲转化为一系列连续的HTML `<section>` 代码块。
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
        error_type = type(e).__name__
        error_message = str(e)
        ui_placeholder.error(f"🚨 **AI调用失败!**\n\n**错误类型:** `{error_type}`\n\n**错误信息:**\n\n`{error_message}`")
        debug_log_container.error(f"--- AI调用时发生严重错误 ---\n{traceback.format_exc()}")
        return None

# ## NEW: 这是智能识别大纲的核心函数 ##
def extract_clean_outline(raw_output, debug_log_container):
    """
    智能地从AI的原始输出中提取出纯净的Markdown大纲。
    不再依赖固定的"Generated markdown"标记。
    """
    try:
        debug_log_container.info("正在尝试智能提取大纲...")
        
        # 使用正则表达式寻找第一个幻灯片的标记
        match = re.search(r"\*\*\s*Slide\s*:\s*\*\*", raw_output)
        
        if not match:
            debug_log_container.error("❌ 在AI响应中未能找到任何`**Slide:**`标记。无法识别大纲内容。")
            with st.expander("查看AI返回的原始响应（调试用）"):
                st.text(raw_output)
            return None

        first_slide_pos = match.start()
        
        # 从第一个幻灯片标记处开始，向前回溯寻找最后一个"---"分隔符
        start_anchor = "---"
        last_divider_pos = raw_output.rfind(start_anchor, 0, first_slide_pos)
        
        if last_divider_pos != -1:
            cleaned_outline = raw_output[last_divider_pos:]
        else:
            cleaned_outline = raw_output[first_slide_pos:]
        
        cleaned_outline = cleaned_outline.strip()

        if cleaned_outline.count("**Title:**") < 3:
            debug_log_container.warning("⚠️ 提取出的大纲结构不完整，可能导致后续步骤失败。")
            st.warning("AI生成的大纲结构不完整或无法识别，请检查调试日志或重试。")
        
        debug_log_container.success(f"✅ 已智能识别并提取出大纲内容，长度 {len(cleaned_outline):,} 字符。")
        return cleaned_outline

    except Exception as e:
        debug_log_container.error(f"提取大纲时发生意外错误: {traceback.format_exc()}")
        return None


# --- Streamlit UI ---
st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 AI学术汇报一键生成器 (最终版)")
with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("请输入您的Google Gemini API Key", type="password")
    model_options = [
        'gemini-1.5-flash-latest',  # 推荐
        'gemini-1.5-pro-latest',
        'gemini-2.0-flash',
        'gemini-2.5-flash',
        'gemini-2.5-pro'
    ]
    selected_model = st.selectbox("选择AI模型", model_options, index=0)

col1, col2 = st.columns(2)
with col1: pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])
with col2: html_template = st.file_uploader("2. 上传您的汇报模板 (.html)", type=['html'])

if 'final_html' not in st.session_state: st.session_state.final_html = None

# --- 主流程 (已更新为使用最终的智能识别函数) ---
if st.button("🚀 开始生成汇报", use_container_width=True, disabled=(not api_key or not pdf_file or not html_template)):
    st.session_state.final_html = None
    progress_container = st.container()
    progress_text = progress_container.empty()
    progress_bar = progress_container.progress(0)
    
    with st.expander("🐞 **调试日志 (点击展开查看详细流程)**", expanded=True):
        debug_log_container = st.container()

    total_start_time = time.time()

    progress_text.text("步骤 0/3: 正在验证配置...")
    if not validate_model(api_key, selected_model, debug_log_container): st.stop()
    progress_bar.progress(5)

    progress_text.text("步骤 1/3: 正在解析PDF文件...")
    paper_text = parse_pdf(pdf_file, debug_log_container)
    if paper_text:
        progress_bar.progress(10)
        
        stage_start_time = time.time()
        progress_text.text(f"步骤 2/3: 正在深度分析生成大纲...")
        st.info("ℹ️ AI正在阅读整个文档，这可能需要数分钟，请耐心等待。")
        
        prompt_for_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
        outline_placeholder = st.empty()
        markdown_outline = call_gemini(api_key, prompt_for_outline, outline_placeholder, selected_model, debug_log_container)
        
        if markdown_outline:
            duration = time.time() - stage_start_time
            debug_log_container.success(f"✅ AI响应接收完毕！(耗时: {duration:.2f}秒)")
            progress_bar.progress(70)
            outline_placeholder.empty()

            cleaned_outline = extract_clean_outline(markdown_outline, debug_log_container)

            if cleaned_outline:
                progress_bar.progress(85)
                
                stage_start_time = time.time()
                progress_text.text(f"步骤 3/3: 正在融合内容并生成最终HTML...")
                template_code = html_template.getvalue().decode("utf-8")
                
                final_prompt = "".join([CODE_GENERATION_PROMPT_TEMPLATE, "\n\n--- PPT Outline ---\n", cleaned_outline])
                final_placeholder = st.empty()
                generated_slides_html = call_gemini(api_key, final_prompt, final_placeholder, selected_model, debug_log_container)

                if generated_slides_html and "section" in generated_slides_html.lower():
                    try:
                        final_html_code = re.sub(
                            r'(<main[^>]*>)(.*?)(</main>)', 
                            lambda m: f"{m.group(1)}\n{generated_slides_html}\n{m.group(3)}",
                            template_code, 
                            count=1, 
                            flags=re.DOTALL | re.IGNORECASE
                        )
                        if final_html_code == template_code: raise ValueError("未能找到<main>标签对")

                        duration = time.time() - stage_start_time
                        debug_log_container.success(f"✅ 最终HTML组装成功！(耗时: {duration:.2f}秒)")
                        
                        st.session_state.final_html = final_html_code
                        total_duration = time.time() - total_start_time
                        progress_text.text(f"🎉 全部完成！总耗时: {total_duration:.2f}秒")
                        progress_bar.progress(100)
                        final_placeholder.empty()
                    except Exception as e:
                        st.error(f"智能组装文件时出错: {e}")
                else:
                    st.error("AI未能生成有效的幻灯片HTML内容。")
            else:
                st.error("无法从AI响应中提取出有效的大纲。请检查调试日志或重试。")

if st.session_state.get('final_html'):
    st.download_button(label="📥 下载您的学术汇报", data=st.session_state.final_html.encode('utf-8'), file_name='my_presentation.html', mime='text/html', use_container_width=True)
