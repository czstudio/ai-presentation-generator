import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import traceback
import time
import re

# --- 提示词模板 ---

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
你是一位精通HTML、CSS和JavaScript的前端开发专家，拥有像素级的代码保真能力。你的核心任务是将结构化的Markdown大纲，无损地、精确地与一个预定义的HTML模板相结合，动态生成最终的、可直接运行的、高度专业的HTML文件。

【重要说明】: 你必须确保生成的HTML文件包含完整的幻灯片内容，而不仅仅是一个加载页面。

核心任务 (Core Task):
你将收到两份输入：
1. PPT大纲 (PPT Outline): 一份结构化的Markdown文件
2. HTML模板 (HTML Template): 一个完整的HTML文件

你的任务是：
1. **解析大纲**: 逐页解析PPT大纲中的所有字段
2. **动态生成幻灯片**: 为每一页生成完整的HTML <section> 元素
3. **确保内容显示**: 生成的HTML必须包含实际的幻灯片内容，不能只是加载页面
4. **保护关键资源**: 保留所有 <img> 标签和Base64资源
5. **匹配导航**: 确保幻灯片数量与导航元素一致

【关键要求】:
- 生成的HTML文件必须立即显示幻灯片内容
- 不能只显示"正在加载"字样
- 每个 <section> 必须包含完整的标题和内容
- 确保所有JavaScript变量正确初始化

指令 (Instruction):
请严格按照上述要求，将大纲内容完整地插入到HTML模板中，生成可以立即使用的完整HTML文件。不要只返回模板，而要返回包含所有幻灯片内容的完整HTML代码。
"""

# --- 修改: 大纲验证函数 ---

def validate_outline(outline_text, debug_log_container):
    """验证生成的大纲格式是否正确 (大小写不敏感，去除多余空白)"""
    try:
        # 使用正则表达式进行大小写不敏感匹配，容忍前后空白和冒号
        if not re.search(r"\bGenerated\s+markdown\b", outline_text, re.IGNORECASE):
            debug_log_container.error("❌ 大纲缺少 'Generated markdown' 标记 (不区分大小写)")
            return False

        # 提取大纲内容，使用正则以防不同大小写
        match = re.split(r"(?i)Generated\s+markdown", outline_text, maxsplit=1)
        cleaned_outline = match[1].strip() if len(match) > 1 else ""

        # 检查是否包含幻灯片分隔符
        slide_sections = [s.strip() for s in cleaned_outline.split("---") if s.strip()]

        if len(slide_sections) < 5:
            debug_log_container.error(f"❌ 大纲包含的幻灯片数量过少: {len(slide_sections)}页 (应≥5页)")
            return False

        # 验证每个幻灯片的基本结构
        valid_slides = 0
        for i, section in enumerate(slide_sections):
            if re.search(r"\*\*Slide:\*\*", section) and re.search(r"\*\*Title:\*\*", section):
                valid_slides += 1
            else:
                debug_log_container.warning(f"⚠️ 第{i+1}页幻灯片格式可能不完整")

        debug_log_container.success(f"✅ 大纲验证通过: 共{len(slide_sections)}页，{valid_slides}页格式正确")
        return True

    except Exception as e:
        debug_log_container.error(f"❌ 大纲验证出错: {e}")
        return False

# --- HTML验证函数 ---

def validate_html_template(template_content, debug_log_container):
    """验证HTML模板的关键结构"""
    try:
        # 检查关键标签
        key_elements = [
            ('<section', '幻灯片区域'),
            ('<script', 'JavaScript代码'),
            ('class=', 'CSS类'),
            ('<div', 'DIV容器')
        ]

        missing_elements = []
        for element, description in key_elements:
            if element not in template_content:
                missing_elements.append(description)

        if missing_elements:
            debug_log_container.error(f"❌ HTML模板缺少关键元素: {', '.join(missing_elements)}")
            return False

        debug_log_container.success("✅ HTML模板结构验证通过")
        return True

    except Exception as e:
        debug_log_container.error(f"❌ HTML模板验证出错: {e}")
        return False

# --- 结果验证函数 ---

def validate_final_html(html_content, debug_log_container):
    """验证最终生成的HTML是否包含实际内容"""
    try:
        # 检查是否包含实际的幻灯片内容
        content_indicators = [
            '<section',
            '<h1',
            '<h2',
            '<h3',
            '<li>',
            '<p>'
        ]

        content_found = sum(1 for indicator in content_indicators if indicator in html_content)

        if content_found < 3:
            debug_log_container.error("❌ 生成的HTML缺少实际内容")
            return False

        # 检查是否只是加载页面
        if re.search(r"正在加载", html_content, re.IGNORECASE) and content_found < 5:
            debug_log_container.error("❌ 生成的HTML可能只是加载页面")
            return False

        debug_log_container.success(f"✅ 最终HTML验证通过: 包含{content_found}个内容元素")
        return True

    except Exception as e:
        debug_log_container.error(f"❌ 最终HTML验证出错: {e}")
        return False

# --- 原有函数保持不变 ---

def parse_pdf(uploaded_file, debug_log_container):
    try:
        file_bytes = uploaded_file.getvalue()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = "".join(page.get_text() + "\n" for page in doc)

        # 限制文本长度以避免token超限
        if len(full_text) > 50000:
            full_text = full_text[:50000] + "\n[文档已截断以避免API限制]"
            debug_log_container.warning("⚠️ 文档过长，已自动截断")

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
            debug_log_container.error(f"模型 `models/{model_name}` 不在可用列表中。")
            return False
    except Exception as e:
        st.error(f"**API Key验证或模型列表获取失败!**")
        debug_log_container.error(f"验证API Key时出现异常: {traceback.format_exc()}")
        return False


def call_gemini(api_key, prompt_text, ui_placeholder, model_name, debug_log_container):
    """调用Google Gemini API，带重试机制"""
    max_retries = 3

    for attempt in range(max_retries):
        try:
            debug_log_container.write(f"--- \n准备调用AI: `{model_name}` (尝试 {attempt + 1}/{max_retries})")
            debug_log_container.write(f"**发送的Prompt长度:** `{len(prompt_text):,}` 字符")

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)

            # 添加延迟避免速率限制
            if attempt > 0:
                wait_time = min(30, 5 * (2 ** attempt))
                debug_log_container.write(f"⏳ 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)

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

            if "429" in error_message or "ResourceExhausted" in error_type:
                debug_log_container.warning(f"⚠️ 尝试 {attempt + 1} 失败: API配额限制")
                if attempt < max_retries - 1:
                    continue
                else:
                    ui_placeholder.error("🚨 **API配额限制超出!** 请等待一段时间后重试，或升级到付费计划。")
                    return None
            else:
                debug_log_container.error(f"尝试 {attempt + 1} 失败: {error_type}: {error_message}")
                if attempt < max_retries - 1:
                    continue
                else:
                    ui_placeholder.error(f"🚨 **AI调用失败!** {error_type}: {error_message}")
                    return None

    return None

# --- Streamlit UI ---

st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 AI学术汇报一键生成器 (调试增强版)")
st.markdown("本应用将分析您的论文并生成完整的HTML演示文稿，包含详细的调试信息。")

# 添加问题排查指南
with st.expander("🔧 常见问题排查指南", expanded=False):
    st.markdown("""
    **如果生成的HTML只显示"正在加载":**
    1. 检查调试日志中的验证步骤
    2. 确认大纲格式是否正确
    3. 检查HTML模板是否包含必要结构
    4. 重试生成过程

    **API配额问题:**
    - 使用 `gemini-1.5-flash-latest` 模型（消耗更少）
    - 等待配额重置后重试
    - 考虑升级到付费计划
    """)

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
    selected_model = st.selectbox("选择AI模型", model_options, index=0, 
                                 help="推荐使用 flash 版本，速度快且消耗配额少")
    if not api_key: st.warning("请输入API Key以开始。")

col1, col2 = st.columns(2)
with col1:
    pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])
with col2:
    html_template = st.file_uploader("2. 上传您的汇报模板 (.html)", type=['html'])

if 'final_html' not in st.session_state:
    st.session_state.final_html = None

if st.button("🚀 开始生成汇报", use_container_width=True, disabled=(not api_key or not pdf_file or not html_template)):
    st.session_state.final_html = None

    progress_container = st.container()
    progress_text = progress_container.empty()
    progress_bar = progress_container.progress(0)

    # 调试日志默认展开以便观察问题
    with st.expander("🐞 **详细调试日志**", expanded=True):
        debug_log_container = st.container()

    total_start_time = time.time()

    # 步骤 0: 验证配置
    progress_text.text("步骤 0/6: 正在验证配置...")
    debug_log_container.info("步骤 0/6: 正在验证API Key和模型名称...")
    if not validate_model(api_key, selected_model, debug_log_container):
        st.stop()
    progress_bar.progress(5)

    # 步骤 1: 解析PDF
    progress_text.text("步骤 1/6: 正在解析PDF文件...")
    paper_text = parse_pdf(pdf_file, debug_log_container)
    if not paper_text:
        st.error("PDF解析失败，无法继续")
        st.stop()
    progress_bar.progress(15)

    # 步骤 2: 验证HTML模板
    progress_text.text("步骤 2/6: 正在验证HTML模板...")
    template_code = html_template.getvalue().decode("utf-8")
    if not validate_html_template(template_code, debug_log_container):
        st.warning("HTML模板可能存在问题，但继续尝试处理...")
    progress_bar.progress(25)

    # 步骤 3: 生成大纲
    progress_text.text("步骤 3/6: 正在生成演示大纲...")
    st.info("ℹ️ AI正在分析文档内容，可能需要几分钟时间...")

    prompt_for_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
    outline_placeholder = st.empty()
    markdown_outline = call_gemini(api_key, prompt_for_outline, outline_placeholder, selected_model, debug_log_container)

    if not markdown_outline:
        st.error("大纲生成失败，请检查API配额或重试")
        st.stop()

    outline_placeholder.empty()
    progress_bar.progress(60)

    # 步骤 4: 验证大纲
    progress_text.text("步骤 4/6: 正在验证生成的大纲...")
    if not validate_outline(markdown_outline, debug_log_container):
        st.error("生成的大纲格式不正确，请重试")
        # 显示大纲内容供调试
        with st.expander("查看生成的大纲内容（调试用）"):
            st.text(markdown_outline[:2000] + "..." if len(markdown_outline) > 2000 else markdown_outline)
        st.stop()

    # 提取清洁的大纲 (使用大小写不敏感分割)
    cleaned_outline = re.split(r"(?i)Generated\s+markdown", markdown_outline, maxsplit=1)[1].strip()
    debug_log_container.success("✅ 大纲验证通过，正在提取内容...")
    progress_bar.progress(70)

    # 步骤 5: 生成最终HTML
    progress_text.text("步骤 5/6: 正在融合内容与模板...")

    final_prompt = "".join([
        CODE_GENERATION_PROMPT_TEMPLATE,
        "\n\n--- PPT Outline ---\n",
        cleaned_outline,
        "\n\n--- HTML Template ---\n",
        template_code
    ])

    final_placeholder = st.empty()
    final_html_code = call_gemini(api_key, final_prompt, final_placeholder, selected_model, debug_log_container)

    if not final_html_code:
        st.error("最终HTML生成失败")
        st.stop()

    final_placeholder.empty()
    progress_bar.progress(90)

    # 步骤 6: 验证最终结果
    progress_text.text("步骤 6/6: 正在验证最终结果...")
    if not validate_final_html(final_html_code, debug_log_container):
        st.warning("⚠️ 生成的HTML可能存在问题，但仍提供下载")
        # 显示部分HTML内容供调试
        with st.expander("查看生成的HTML片段（调试用）"):
            st.code(final_html_code[:1000] + "..." if len(final_html_code) > 1000 else final_html_code)

    st.session_state.final_html = final_html_code
    total_duration = time.time() - total_start_time
    progress_text.text(f"🎉 全部完成！总耗时: {total_duration:.2f}秒")
    progress_bar.progress(100)

# 下载按钮和预览
if st.session_state.get('final_html'):
    col1, col2 = st.columns([2, 1])

    with col1:
        st.download_button(
            label="📥 下载完整的学术汇报HTML",
            data=st.session_state.final_html.encode('utf-8'),
            file_name='academic_presentation.html',
            mime='text/html',
            use_container_width=True
        )

    with col2:
        if st.button("🔍 预览HTML内容"):
            with st.expander("HTML内容预览", expanded=True):
                # 显示HTML的前2000个字符
                preview_text = st.session_state.final_html[:2000]
                st.code(preview_text, language='html')
                if len(st.session_state.final_html) > 2000:
                    st.text(f"... (还有 {len(st.session_state.final_html) - 2000} 个字符)")

st.sidebar.markdown("---")
st.sidebar.info("💡 如遇问题，请查看调试日志中的详细信息，或重新上传文件重试。")
