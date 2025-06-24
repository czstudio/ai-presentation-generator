import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import traceback
import time
import re

# -------------------------------------------------------------
# Prompt Templates
# -------------------------------------------------------------

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

(后续视觉数据格式说明略)
"""

CODE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位精通HTML、CSS和JavaScript的前端开发专家，拥有像素级的代码保真能力。你的核心任务是将一份结构化的Markdown大纲，无损地、精确地与一个预定义的HTML模板相结合，动态生成最终的、可直接运行的、高度专业的HTML文件。

核心任务 (Core Task):
你将收到两份输入：
1.  **PPT大纲 (PPT Outline):** 一份结构化的Markdown文件。
2.  **HTML模板 (HTML Template):** 一个完整的、包含所有CSS和JavaScript的HTML文件。

你的任务是：
1.  **读取并理解模板:** 完整地分析HTML模板的结构，特别是`<main>`标签内的幻灯片占位内容，以及`<head>`中的`<style>`和`<body>`末尾的`<script>`。
2.  **清空并替换内容:** 在你的处理逻辑中，你需要移除模板`<main>`标签内部原有的所有`<section class="slide">...</section>`占位幻灯片。然后，根据PPT大纲的内容，生成新的、应用了正确CSS类（如 `slide`, `research-card`, `scroll-reveal`等）的`<section>`幻灯片，并将它们插入到`<main>`标签内。
3.  **【最高优先级】保护关键代码:** 在生成最终的完整HTML文件时，必须 **逐字逐句、完整无误地保留** HTML模板中 **除了`<main>`内部幻灯片内容之外的所有部分**。特别是：
    *   整个`<head>`标签，包括所有的`<link>`和`<style>`。
    *   整个`<script>`标签及其内部所有的JavaScript代码。
    *   所有的导航控件、页码指示器等非幻灯片内容。
    *   所有`<img>`标签及其`src`属性，尤其是Base64编码的图片。
4.  **输出完整文件:** 你的最终输出必须是一个单一的、完整的、可以直接另存为`.html`并运行的HTML代码字符串。它应该以`<!DOCTYPE html>`开头，并以`</html>`结尾。

指令 (Instruction):
以下是用户提供的 **PPT大纲 (PPT Outline)** 和 **HTML模板 (HTML Template)**。请立即开始工作，严格遵循以上所有规则，特别是保护脚本和样式的指令，将大纲内容与模板代码完美融合，生成最终的、完整的、专业级的HTML文件。
"""

# -------------------------------------------------------------
# Validation Utilities
# -------------------------------------------------------------

def validate_outline(outline_text: str, debug_log_container) -> bool:
    """验证生成的大纲格式是否正确（忽略大小写、允许多空格）。"""
    try:
        # 1️⃣ 标记检测：忽略大小写，允许 'generated   markdown' 这类空格
        marker_regex = r"generated\s+markdown"
        if not re.search(marker_regex, outline_text, re.IGNORECASE):
            debug_log_container.error("❌ 大纲缺少 'Generated markdown' 标记（不区分大小写）")
            return False

        # 2️⃣ 提取大纲正文（用正则切分而不是 str.split，兼容大小写 & 变体）
        cleaned_outline_parts = re.split(marker_regex, outline_text, flags=re.IGNORECASE, maxsplit=1)
        if len(cleaned_outline_parts) < 2:
            debug_log_container.error("❌ 无法在大纲中找到 'Generated markdown' 标记后续内容")
            return False
        cleaned_outline = cleaned_outline_parts[1].strip()

        # 3️⃣ 判断幻灯片分隔符数量
        slide_sections = [s.strip() for s in cleaned_outline.split("---") if s.strip()]
        if len(slide_sections) < 5:
            debug_log_container.error(f"❌ 大纲包含的幻灯片数量过少: {len(slide_sections)} 页 (< 5)")
            return False

        # 4️⃣ 基本结构检查
        valid_slides = 0
        for i, section in enumerate(slide_sections, start=1):
            if re.search(r"\*\*Slide:\*\*", section) and re.search(r"\*\*Title:\*\*", section):
                valid_slides += 1
            else:
                debug_log_container.warning(f"⚠️ 第 {i} 页幻灯片格式可能不完整")

        debug_log_container.success(f"✅ 大纲验证通过: 共 {len(slide_sections)} 页，{valid_slides} 页基本格式正确")
        return True

    except Exception as e:
        debug_log_container.error(f"❌ 大纲验证出错: {e}")
        return False


def validate_html_template(template_content: str, debug_log_container) -> bool:
    """验证HTML模板中是否包含关键结构元素。"""
    try:
        key_elements = [
            ("<section", "幻灯片区域"),
            ("<script", "JavaScript代码"),
            ("class=", "CSS类"),
            ("<div", "DIV容器"),
        ]

        missing = [desc for tag, desc in key_elements if tag not in template_content]
        if missing:
            debug_log_container.error(f"❌ HTML模板缺少关键元素: {', '.join(missing)}")
            return False

        debug_log_container.success("✅ HTML模板结构验证通过")
        return True

    except Exception as e:
        debug_log_container.error(f"❌ HTML模板验证出错: {e}")
        return False


def validate_final_html(html_content: str, debug_log_container) -> bool:
    """验证生成的 HTML 文件是否包含实际幻灯片内容，而不仅仅是加载提示。"""
    try:
        indicators = ["<section", "<h1", "<h2", "<h3", "<li>", "<p>"]
        content_found = sum(1 for i in indicators if i in html_content)
        if content_found < 3:
            debug_log_container.error("❌ 生成的HTML缺少实际内容")
            return False
        if "正在加载" in html_content and content_found < 5:
            debug_log_container.error("❌ 生成的HTML可能只是加载页面")
            return False

        debug_log_container.success(f"✅ 最终HTML验证通过: 检测到 {content_found} 个内容标识符")
        return True

    except Exception as e:
        debug_log_container.error(f"❌ 最终HTML验证出错: {e}")
        return False

# -------------------------------------------------------------
# PDF Parsing & Gemini Calls (unchanged logic unless noted)
# -------------------------------------------------------------

def parse_pdf(uploaded_file, debug_log_container):
    try:
        file_bytes = uploaded_file.getvalue()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = "".join(page.get_text() + "\n" for page in doc)

        # Truncate long documents (50k chars) to avoid token overflow
        if len(full_text) > 50000:
            full_text = full_text[:50000] + "\n[文档已截断以避免API限制]"
            debug_log_container.warning("⚠️ 文档过长，已自动截断")

        debug_log_container.write(f"✅ PDF解析成功，总计 {len(full_text):,} 个字符")
        return full_text
    except Exception:
        st.error("PDF解析失败")
        debug_log_container.error(f"PDF解析时出现异常:\n{traceback.format_exc()}")
        return None


def validate_model(api_key: str, model_name: str, debug_log_container) -> bool:
    try:
        if not model_name.strip():
            st.error("**模型名称不能为空!**")
            return False
        genai.configure(api_key=api_key)
        available = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
        if f"models/{model_name}" in available:
            debug_log_container.success(f"✅ 模型 `{model_name}` 验证通过！")
            return True
        st.error(f"**模型验证失败!** `{model_name}` 不存在或无权访问")
        debug_log_container.error(f"模型 `models/{model_name}` 不在可用列表中。")
        return False
    except Exception:
        st.error("**API Key验证或模型列表获取失败!**")
        debug_log_container.error(f"验证API Key时出现异常:\n{traceback.format_exc()}")
        return False


def call_gemini(api_key: str, prompt_text: str, ui_placeholder, model_name: str, debug_log_container):
    """调用 Gemini API（带指数退避重试）并流式输出。"""
    retries = 3
    for attempt in range(retries):
        try:
            debug_log_container.write(f"--- 调用AI: `{model_name}` (第 {attempt+1}/{retries} 次)")
            debug_log_container.write(f"Prompt 长度: {len(prompt_text):,} 字符")
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)

            # Rate‑limit backoff
            if attempt:
                wait = min(30, 5 * 2 ** attempt)
                debug_log_container.info(f"⏳ 等待 {wait}s 后重试…")
                time.sleep(wait)

            collected = []
            def collector(stream):
                for chunk in stream:
                    if hasattr(chunk, "text"):
                        collected.append(chunk.text)
                        yield chunk.text
            stream_resp = model.generate_content(prompt_text, stream=True)
            ui_placeholder.write_stream(collector(stream_resp))
            full = "".join(collected)
            debug_log_container.success(f"✅ AI 流式响应完成 ({len(full):,} 字符)")
            return full
        except Exception as e:
            if "429" in str(e) or "ResourceExhausted" in type(e).__name__:
                debug_log_container.warning(f"⚠️ 第 {attempt+1} 次尝试触发配额限制")
                if attempt < retries - 1:
                    continue
                ui_placeholder.error("🚨 API配额限制超出! 请稍后重试或升级计划。")
                return None
            debug_log_container.error(f"调用失败: {e}")
            if attempt < retries - 1:
                continue
            ui_placeholder.error(f"🚨 AI调用失败: {e}")
            return None
    return None

# -------------------------------------------------------------
# Streamlit UI (unchanged except minor text tweaks)
# -------------------------------------------------------------

st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 AI学术汇报一键生成器 (调试增强版)")
st.markdown("本应用将分析您的论文并生成完整的HTML演示文稿，包含详细的调试信息。")

with st.expander("🔧 常见问题排查指南", expanded=False):
    st.markdown("""
    **若生成的HTML只显示\"正在加载\"：**
    1. 检查调试日志中的验证步骤
    2. 确认大纲格式是否正确 (需含 *Generated markdown* 标记)
    3. 检查HTML模板是否包含必要结构
    4. 重试生成过程
    """)

with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("请输入Google Gemini API Key", type="password")
    model_opts = [
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro-latest",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
    selected_model = st.selectbox("选择AI模型", model_opts, index=0)
    if not api_key:
        st.warning("请输入 API Key 以开始。")

col1, col2 = st.columns(2)
pdf_file = col1.file_uploader("1. 上传学术论文 (.pdf)", type=["pdf"])
html_template = col2.file_uploader("2. 上传汇报模板 (.html)", type=["html"])

if "final_html" not in st.session_state:
    st.session_state.final_html = None

if st.button("🚀 开始生成汇报", use_container_width=True, disabled=not (api_key and pdf_file and html_template)):
    st.session_state.final_html = None

    progress = st.container()
    progress_text = progress.empty()
    bar = progress.progress(0)

    with st.expander("🐞 详细调试日志", expanded=True):
        debug = st.container()

    # 0️⃣ 验证配置
    progress_text.text("步骤 0/6: 验证配置…")
    if not validate_model(api_key, selected_model, debug):
        st.stop()
    bar.progress(5)

    # 1️⃣ 解析 PDF
    progress_text.text("步骤 1/6: 解析 PDF…")
    paper_text = parse_pdf(pdf_file, debug)
    if not paper_text:
        st.error("PDF解析失败，终止")
        st.stop()
    bar.progress(15)

    # 2️⃣ 验证 HTML 模板
    progress_text.text("步骤 2/6: 验证 HTML 模板…")
    tpl_code = html_template.getvalue().decode("utf-8")
    if not validate_html_template(tpl_code, debug):
        st.warning("HTML模板可能存在问题，但继续处理…")
    bar.progress(25)

    # 3️⃣ 生成大纲
    progress_text.text("步骤 3/6: 生成演示大纲…")
    st.info("AI 正在分析文档内容，可能耗时数分钟…")
    prompt_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
    outline_placeholder = st.empty()
    markdown_outline = call_gemini(api_key, prompt_outline, outline_placeholder, selected_model, debug)
    outline_placeholder.empty()
    if not markdown_outline:
        st.error("大纲生成失败")
        st.stop()
    bar.progress(60)

    # 4️⃣ 验证大纲
    progress_text.text("步骤 4/6: 验证大纲…")
    if not validate_outline(markdown_outline, debug):
        st.error("大纲格式错误，请检查日志并重试")
        with st.expander("生成的大纲内容 (调试)"):
            st.text(markdown_outline[:2000] + ("..." if len(markdown_outline) > 2000 else ""))
        st.stop()

    cleaned_outline = re.split(r"generated\s+markdown", markdown_outline, flags=re.IGNORECASE, maxsplit=1)[1].strip()
    bar.progress(70)

    # 5️⃣ 生成最终 HTML
    progress_text.text("步骤 5/6: 融合内容与模板…")
    final_prompt = CODE_GENERATION_PROMPT_TEMPLATE + "\n\n--- PPT Outline ---\n" + cleaned_outline + "\n\n--- HTML Template ---\n" + tpl_code
    html_placeholder = st.empty()
    final_html = call_gemini(api_key, final_prompt, html_placeholder, selected_model, debug)
    html_placeholder.empty()
    if not final_html:
        st.error("最终HTML生成失败")
        st.stop()
    bar.progress(90)

    # 6️⃣ 验证最终 HTML
    progress_text.text("步骤 6/6: 验证最终HTML…")
    if not validate_final_html(final_html, debug):
        st.warning("⚠️ 最终 HTML 可能存在问题，但仍提供下载")
        with st.expander("HTML 片段 (调试)"):
            st.code(final_html[:1000] + ("..." if len(final_html) > 1000 else ""), language="html")

    st.session_state.final_html = final_html
    bar.progress(100)
    progress_text.text("🎉 全部完成！")

# -------------------------------------------------------------
# 下载 & 预览
# -------------------------------------------------------------

if st.session_state.get("final_html"):
    left, right = st.columns([2, 1])
    left.download_button(
        "📥 下载完整学术汇报 HTML",
        data=st.session_state.final_html.encode("utf-8"),
        file_name="academic_presentation.html",
        mime="text/html",
        use_container_width=True,
    )

    if right.button("🔍 预览 HTML"):
        with st.expander("HTML 内容预览", expanded=True):
            preview = st.session_state.final_html
            st.code(preview[:2000] + ("..." if len(preview) > 2000 else ""), language="html")

st.sidebar.markdown("---")
st.sidebar.info("💡 若遇问题，请查看调试日志，或重新上传文件重试。")
