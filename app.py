import streamlit as st
import google.generativeai as genai
import fitz
import traceback
import time
import re

# --- 提示词模板 ---

# ## 大纲生成器 (保持不变) ##
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

# ## 代码融合器 (终极强化版 - 基于您成功的原始流程) ##
CODE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位精通HTML、CSS和JavaScript的前端开发专家，拥有像素级的代码保真能力。你的核心任务是将一份结构化的Markdown大纲，无损地、精确地与一个预定义的HTML模板相结合，动态生成最终的、可直接运行的HTML文件。

核心任务 (Core Task):
你将收到两份输入：
1.  **PPT大纲 (PPT Outline):** 一份结构化的Markdown文件。
2.  **HTML模板 (HTML Template):** 一个完整的、包含所有CSS和JavaScript的HTML文件。

你的任务是：
1.  **读取并理解模板:** 完整地分析HTML模板的结构，特别是`<main>`标签内的幻灯片占位内容，以及`<head>`中的`<style>`和`<body>`末尾的`<script>`。
2.  **智能替换内容:** 在你的处理逻辑中，你需要移除模板`<main>`标签内部原有的所有`<section class="slide">...</section>`占位幻灯片。然后，根据PPT大纲的内容，生成新的、**应用了正确CSS类**（例如，通过模仿模板中已有的 `.title-slide`, `.research-card` 等样式）的`<section>`幻灯片，并将它们插入到`<main>`标签内。
3.  **【最高优先级 - 铁律】:** 在生成最终的完整HTML文件时，你必须 **逐字逐句、完整无误地保留** HTML模板中 **除了`<main>`内部幻灯片内容之外的所有部分**。这包括但不限于：
    *   整个`<head>`标签，包含所有的`<link>`和`<style>`。
    *   整个`<script>`标签及其内部所有的JavaScript代码。
    *   所有的导航控件、页码指示器等非幻灯片内容。
    *   所有`<img>`标签及其`src`属性，尤其是Base64编码的图片。
4.  **【绝对禁止】:** 你的最终输出 **绝对不能** 包含任何解释性文字或Markdown代码块标记。输出必须是一个纯粹的HTML文本，直接以 `<!DOCTYPE html>` 开头，并以 `</html>` 结尾。

**【重要输出要求】:**
- 直接输出完整的HTML代码，不要添加任何说明文字
- 不要使用```html或```等Markdown代码块标记
- 不要在HTML前后添加任何解释性内容
- 确保输出以<!DOCTYPE html>开始，以</html>结束

指令 (Instruction):
以下是用户提供的 **PPT大纲 (PPT Outline)** 和 **HTML模板 (HTML Template)**。请立即开始工作，严格遵循以上所有规则，特别是保护脚本和样式的铁律，将大纲内容与模板代码完美融合，生成最终的、完整的、专业级的HTML文件。
"""

# --- 所有Agent函数 (保持健壮) ---
def parse_pdf(uploaded_file, debug_log_container):
    try:
        file_bytes = uploaded_file.getvalue()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = "".join(page.get_text() + "\n" for page in doc)
        debug_log_container.write(f"✅ PDF解析成功。总计 {len(full_text):,} 个字符。")
        return full_text
    except Exception:
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
    except Exception:
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

        # 只有在提供了UI占位符时才进行流式写入
        if ui_placeholder:
            response_stream = model.generate_content(prompt_text, stream=True)
            ui_placeholder.write_stream(stream_and_collect(response_stream))
        else:
            # 如果不提供UI占位符，则直接生成，避免在UI上产生不必要的输出
            response = model.generate_content(prompt_text)
            if hasattr(response, 'text'):
                collected_chunks.append(response.text)
        
        full_response_str = "".join(collected_chunks)
        debug_log_container.write(f"✅ AI响应成功完成。收集到 {len(full_response_str):,} 个字符。")
        return full_response_str
    except Exception as e:
        error_message = f"🚨 **AI调用失败!** 请检查调试日志。\n\n**错误详情:** {e}"
        if ui_placeholder:
            ui_placeholder.error(error_message)
        else:
            st.error(error_message)
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
    except Exception:
        debug_log_container.error(f"提取大纲时发生意外错误: {traceback.format_exc()}")
        return None

# ## 安全版最终清理函数 - 保护HTML模板内容 ##
def final_cleanup(raw_html, debug_log_container):
    """
    对最终的HTML进行安全清理，只清理HTML文档外部的多余内容。
    避免破坏HTML模板的原有格式和内容。
    """
    try:
        debug_log_container.write(f"开始清理HTML，原始长度: {len(raw_html):,} 字符")
        
        # 1. 寻找HTML文档的真正起点和终点
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
        
        # 2. 只清理HTML文档前面可能存在的说明文字
        text_before_html = raw_html[:html_start_pos].strip()
        if text_before_html:
            debug_log_container.write(f"发现HTML前的内容: {text_before_html[:200]}...")
            # 只移除明显的Markdown标记和说明文字
            if any(marker in text_before_html.lower() for marker in ['```', '以下是', '这是', '生成的']):
                debug_log_container.write("移除HTML前的说明文字")
        
        # 3. 提取纯净的HTML内容（从<!DOCTYPE html>到</html>）
        html_content = raw_html[html_start_pos:html_end_pos + 7]  # +7 for "</html>"
        
        # 4. 只清理HTML文档末尾可能存在的多余内容
        text_after_html = raw_html[html_end_pos + 7:].strip()
        if text_after_html:
            debug_log_container.write(f"发现HTML后的内容: {text_after_html[:100]}...")
            # 如果HTML后面还有内容，说明可能有多余的说明文字，直接忽略
        
        # 5. 基本格式验证
        html_content = html_content.strip()
        if not (html_content.startswith("<!DOCTYPE html>") or html_content.startswith("<html")):
            debug_log_container.error("❌ 清理后的HTML格式不正确")
            return None
            
        if not html_content.endswith("</html>"):
            debug_log_container.error("❌ 清理后的HTML结尾不正确")
            return None
        
        debug_log_container.success(f"✅ HTML清理完成！最终长度: {len(html_content):,} 字符")
        debug_log_container.write(f"HTML开头: {html_content[:100]}...")
        debug_log_container.write(f"HTML结尾: ...{html_content[-50:]}")
        
        return html_content
        
    except Exception as e:
        debug_log_container.error(f"最终清理时出错: {traceback.format_exc()}")
        return None

# --- Streamlit UI ---
st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")
st.title("🎓 AI学术汇报一键生成器 (最终修复版)")
with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("请输入您的Google Gemini API Key", type="password")
    model_options = ['gemini-2.5-pro', 'gemini-2.0-pro','gemini-2.5-flash','gemini-2.0-flash']
    selected_model = st.selectbox("选择AI模型", model_options, index=0)

col1, col2 = st.columns(2)
with col1: pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])
with col2: html_template = st.file_uploader("2. 上传您的**原始**HTML模板", type=['html'])

if 'final_html' not in st.session_state: st.session_state.final_html = None

# --- 主流程 (回归您成功的原始逻辑) ---
if st.button("🚀 开始生成汇报", use_container_width=True, disabled=(not api_key or not pdf_file or not html_template)):
    st.session_state.final_html = None
    progress_container = st.container()
    progress_text = progress_container.empty()
    progress_bar = progress_container.progress(0)
    
    with st.expander("🐞 **调试日志 (点击展开查看详细流程)**", expanded=True):
        debug_log_container = st.container()

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

            progress_text.text(f"步骤 2/3: 正在智能识别并清洗大纲...")
            cleaned_outline = extract_clean_outline(markdown_outline, debug_log_container)

            if cleaned_outline:
                progress_bar.progress(70)
                
                # ## 这是最终的核心步骤，完全模拟您成功的手动流程 ##
                progress_text.text(f"步骤 3/3: 正在融合大纲与模板生成最终文件...")
                st.info("ℹ️ AI正在执行最终的全文重写，这可能需要一些时间...")
                
                template_code = html_template.getvalue().decode("utf-8")
                
                final_prompt = "".join([
                    CODE_GENERATION_PROMPT_TEMPLATE, 
                    "\n\n--- PPT Outline ---\n", 
                    cleaned_outline, 
                    "\n\n--- HTML Template ---\n", 
                    template_code
                ])
                
                # ## 修改：最终调用不显示在主UI上，避免出现"短横线"等无关内容 ##
                with st.spinner("AI正在生成最终HTML，请稍候..."):
                    final_html_raw = call_gemini(api_key, final_prompt, None, selected_model, debug_log_container)

                if final_html_raw:
                    # ## 使用强化版清理函数彻底解决HTML显示问题 ##
                    final_html_code = final_cleanup(final_html_raw, debug_log_container)

                    if final_html_code and "</html>" in final_html_code.lower():
                        debug_log_container.success(f"✅ 最终HTML生成并清理成功！")
                        st.session_state.final_html = final_html_code
                        progress_text.text(f"🎉 全部完成！")
                        progress_bar.progress(100)
                    else:
                        st.error("AI未能生成有效的最终HTML文件。请检查调试日志。")
                else:
                    st.error("AI未能生成最终HTML内容。")
            else:
                st.error("无法从AI响应中提取出有效的大纲。")

if st.session_state.get('final_html'):
    st.download_button(label="📥 下载您的学术汇报", data=st.session_state.final_html.encode('utf-8'), file_name='my_presentation.html', mime='text/html', use_container_width=True)