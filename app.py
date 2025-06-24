import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import traceback

# --- 提示词模板 ---

# ## 用户原始提示词1: 大纲生成器 (完全按照您的要求) ##
OUTLINE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位顶级的学术汇报设计师和内容策略师，同时具备出色的**“无图化设计” (Graphic-less Design)** 思维。你精通将复杂的学术论文转化为结构化、视觉化的演示文稿（PPT），并且擅长使用CSS样式、布局和文本符号来创造清晰、优雅的视觉效果，以最大限度地减少对外部图片或复杂SVG的依赖。

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
现在，请分析用户上传的这份学术文档。严格遵循以上所有规则和**“无图化设计”原则，为其生成一份完整的、逻辑清晰的、强调使用简单符号和CSS**进行视觉呈现的学术演示文稿大纲。请开始。
"""

# ## 用户原始提示词2: 代码融合器 (保持不变) ##
CODE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位精通HTML、CSS和JavaScript的前端开发专家...
""" # (为简洁省略，请确保在您的文件中此部分是完整的)


# --- 所有Agent函数 (均包含健壮的错误处理和调试信息) ---
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
        if not model_name or not model_name.strip():
            st.error("**模型名称不能为空!**")
            return False
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if f"models/{model_name}" in available_models:
            debug_log_container.success(f"✅ 模型 `{model_name}` 验证通过！")
            return True
        else:
            st.error(f"**模型验证失败!** `{model_name}` 不存在或您的API Key无权访问。")
            debug_log_container.error(f"模型 `models/{model_name}` 不在可用列表 `{available_models}` 中。")
            return False
    except Exception as e:
        st.error(f"**API Key验证或模型列表获取失败!**")
        debug_log_container.error(f"验证API Key时出现异常: {traceback.format_exc()}")
        return False

def call_gemini(api_key, prompt_text, ui_placeholder, model_name, debug_log_container):
    try:
        debug_log_container.write(f"--- \n准备调用AI: `{model_name}`...")
        debug_log_container.write(f"**发送的Prompt长度:** `{len(prompt_text):,}` 字符")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response_stream = model.generate_content(prompt_text, stream=True)
        full_response = ui_placeholder.write_stream(response_stream)
        debug_log_container.write("✅ AI流式响应成功完成。")
        return full_response
    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        ui_placeholder.error(f"🚨 **AI调用失败!**\n\n**错误类型:** `{error_type}`\n\n**错误信息:**\n\n`{error_message}`")
        debug_log_container.error(f"--- AI调用时发生严重错误 ---\n{traceback.format_exc()}")
        return None

# --- Streamlit UI ---
st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 AI学术汇报一键生成器")
st.markdown("本应用将直接使用您的提示词对论文全文进行深度分析，请耐心等待。")

with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("请输入您的Google Gemini API Key", type="password")
    model_options = ['gemini-2.5-pro', 'gemini-1.5-pro-latest', 'gemini-1.5-flash-latest']
    selected_model = st.selectbox("选择AI模型", model_options, index=0, help="处理长文档建议使用Gemini 1.5 Pro。")
    if not api_key: st.warning("请输入API Key以开始。")

col1, col2 = st.columns(2)
with col1: pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])
with col2: html_template = st.file_uploader("2. 上传您的汇报模板 (.html)", type=['html'])

if 'final_html' not in st.session_state: st.session_state.final_html = None

if st.button("🚀 开始生成汇报", use_container_width=True, disabled=(not api_key or not pdf_file or not html_template)):
    st.session_state.final_html = None
    progress_container = st.container()
    
    with st.expander("🐞 **调试日志 (点击展开查看详细流程)**", expanded=True):
        debug_log_container = st.container()

    # 步骤 0: 验证
    debug_log_container.info("步骤 0/3: 正在验证API Key和模型名称...")
    if not validate_model(api_key, selected_model, debug_log_container):
        st.stop()

    # 步骤 1: 解析PDF
    progress_container.info("步骤 1/3: 正在解析PDF文件...")
    paper_text = parse_pdf(pdf_file, debug_log_container)

    if paper_text:
        progress_container.success("✅ PDF文件解析完成！")
        
        # 步骤 2: 生成大纲 (直接使用全文)
        # ## 这是核心修改：明确告知用户此步骤耗时很长 ##
        progress_container.warning(f"步骤 2/3: 正在使用 `{selected_model}` 对全文进行深度分析以生成大纲...")
        st.info("ℹ️ **请注意: 这是最耗时的一步。** AI需要阅读和理解整个文档，可能需要数分钟时间，请耐心等待，不要关闭页面。")
        
        # ## 这是核心修改：将全文和您的原始提示词组合 ##
        prompt_for_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
        outline_placeholder = progress_container.empty()
        markdown_outline = call_gemini(api_key, prompt_for_outline, outline_placeholder, selected_model, debug_log_container)
        
        if markdown_outline:
            progress_container.success("✅ 汇报大纲生成成功！")
            
            # 步骤 3: 融合代码
            progress_container.info(f"步骤 3/3: 正在使用 `{selected_model}` 融合内容与模板...")
            template_code = html_template.getvalue().decode("utf-8")
            final_prompt = "".join([CODE_GENERATION_PROMPT_TEMPLATE, "\n\n--- PPT Outline ---\n", markdown_outline, "\n\n--- HTML Template ---\n", template_code])
            final_placeholder = progress_container.empty()
            with st.spinner("正在生成最终HTML代码..."):
                final_html_code = call_gemini(api_key, final_prompt, final_placeholder, selected_model, debug_log_container)

            if final_html_code:
                st.session_state.final_html = final_html_code
                progress_container.success("🎉 恭喜！您的学术汇报已准备就绪！")
            else:
                progress_container.error("最终HTML生成失败，请检查调试日志。")

if st.session_state.get('final_html'):
    st.download_button(label="📥 下载您的学术汇报", data=st.session_state.final_html.encode('utf-8'), file_name='my_presentation.html', mime='text/html', use_container_width=True)
