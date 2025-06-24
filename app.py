import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import os

# --- 提示词模板 ---
# 这是 Agent 2 (大纲生成器) 的核心指令
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
Type: Symbol (符号/图标，优先使用Emoji)
Data:
symbol: [一个Unicode Emoji表情符号，例如 🔬, 📈, 💡, 📚, 🎓]。
text: [符号旁边的简短说明文字]。
color_hint: [一个CSS颜色提示，例如 red, blue, green]。

Type: Process (流程图)
Data:
steps: [一个JSON数组，例如 ["文献回顾", "理论构建", "数据分析", "结论撰写"]]。
style: [numbered-list, chevron-arrow]。

Type: Chart (图表，简化数据结构)
Data:
chart_type: [bar, line, pie]。
title: [图表标题]。
data_summary: [对图表核心数据的文字描述，例如 "柱状图显示实验组A (85%) 显著高于对照组B (62%)"]。

Type: Table (表格)
Data:
caption: [表格标题]。
headers: [一个包含表头的JSON数组, 例如 ["指标", "数值", "P值"]]。
rows: [一个包含多行数据的JSON数组，例如 [["效率", "95%", "<0.01"], ["成本", "-20%", "N/A"]]]。

Type: Quote (引用)
Data:
text: [引用的核心文本]。
source: [引用来源]。

Type: Comparison (对比)
Data:
item1_title: [对比项1的标题]。
item1_points: [一个包含对比项1要点的JSON数组]。
item2_title: [对比项2的标题]。
item2_points: [一个包含对比项2要点的JSON数组]。

Type: List 或 Type: Text_Only
Data: null (内容直接在 Content 字段中体现)。

指令 (Instruction):
现在，请分析用户上传的这份学术文档。严格遵循以上所有规则和**“无图化设计”原则，为其生成一份完整的、逻辑清晰的、强调使用简单符号和CSS**进行视觉呈现的学术演示文稿大纲。请开始。
"""

# 这是 Agent 3 (代码生成器) 的核心指令
CODE_GENERATION_PROMPT_TEMPLATE = """
角色 (Role):
你是一位精通HTML、CSS和JavaScript的前端开发专家，拥有像素级的代码保真能力。你的核心任务是将结构化的Markdown大纲，无损地、精确地与一个预定义的HTML模板相结合，动态生成最终的、可直接运行的、高度专业的HTML文件。你对细节有极高的要求，尤其是在处理图像资源和数据可视化占位方面。

核心任务 (Core Task):
你将收到两份输入：
1. PPT大纲 (PPT Outline): 一份由AI预先生成的、结构化的Markdown文件。
2. HTML模板 (HTML Template): 一个完整的HTML文件，包含了所有必须的样式、脚本和关键资源（如Base64编码的校徽）。

你的任务是：
1. **解析大纲**: 逐页解析PPT大纲中的所有字段。
2. **动态生成幻灯片**: 根据解析出的数据，为每一页幻灯片生成对应的HTML <section> 元素。
3. **智能渲染视觉元素**:
   - 对于图表 (Visual.Type: Chart): **绝不在页面上显示“占位符”字样**。你应该在图表区域内，使用优雅的排版，将大纲中提供的 `Visual.Data.data_summary` (数据摘要文字) 直接展示出来。
   - 对于符号 (Visual.Type: Symbol): 将大纲中指定的Emoji符号 (`Visual.Data.symbol`) 直接作为文本插入到HTML中。
4. **【最高优先级】保护关键资源**: 在整合代码时，必须完整、无误地保留HTML模板中所有的 `<img>` 标签及其 `src` 属性，特别是那些包含 `data:image/svg+xml;base64,...` 的长字符串。**绝不允许对这些资源链接进行任何形式的修改、缩短或删除。**
5. **无缝整合**: 确保动态生成的幻灯片数量与模板中的导航元素（如缩略图、JS变量）相匹配。
6. **代码整洁**: 生成的HTML代码必须有良好的缩进和可读性。

指令 (Instruction):
以下是用户提供的 PPT大纲 (PPT Outline) 和 HTML模板 (HTML Template)。
请你立即开始工作，严格遵循以上所有规则，将大纲内容与模板代码结合，生成最终的、完整的、专业级的 index.html 文件。不要提供任何解释或评论，直接输出完整的HTML代码。
"""


# --- Agent 1: PDF解析函数 ---
def parse_pdf(uploaded_file):
    """从上传的PDF文件中提取纯文本。"""
    try:
        file_bytes = uploaded_file.getvalue()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
        return full_text
    except Exception as e:
        return f"PDF解析失败: {e}"

# --- 调用LLM的函数 ---
def call_gemini(api_key, prompt_text, model_name="gemini-1.5-pro-latest"):
    """调用Google Gemini API并返回结果。"""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt_text)
        # 清理返回的文本，移除可能存在的Markdown代码块标记
        cleaned_text = response.text.replace("```html", "").replace("```", "").strip()
        return cleaned_text
    except Exception as e:
        return f"调用AI时出错: {e}"

# --- Streamlit UI ---
st.set_page_config(page_title="AI学术汇报生成器", page_icon="🎓", layout="wide")

st.title("🎓 AI学术汇报一键生成器")
st.markdown("上传您的学术论文PDF和汇报HTML模板，AI将为您自动生成精美的网页版演示文稿。")

# 在侧边栏获取API密钥
with st.sidebar:
    st.header("配置")
    api_key = st.text_input("请输入您的Google Gemini API Key", type="password")
    st.markdown("[如何获取API Key?](https://aistudio.google.com/app/apikey)")

# 主界面文件上传
col1, col2 = st.columns(2)
with col1:
    pdf_file = st.file_uploader("1. 上传您的学术论文 (.pdf)", type=['pdf'])

with col2:
    html_template = st.file_uploader("2. 上传您的汇报模板 (.html)", type=['html'])

# 生成按钮
if st.button("🚀 开始生成汇报", use_container_width=True):
    if not api_key:
        st.error("请输入您的Google Gemini API Key！")
    elif not pdf_file:
        st.error("请上传您的学术论文PDF文件！")
    elif not html_template:
        st.error("请上传您的汇报模板HTML文件！")
    else:
        with st.spinner("AI正在努力工作中，请稍候..."):
            # --- 工作流开始 ---

            # 步骤1: 调用Agent 1解析PDF
            st.info("步骤 1/3: 正在解析PDF文件...")
            paper_text = parse_pdf(pdf_file)
            if paper_text.startswith("PDF解析失败"):
                st.error(paper_text)
            else:
                st.success("✅ PDF文件解析完成！")

                # 步骤2: 调用Agent 2生成大纲
                st.info("步骤 2/3: 正在生成汇报大纲 (调用AI中，可能需要1-2分钟)...")
                prompt_for_outline = OUTLINE_GENERATION_PROMPT_TEMPLATE + "\n\n--- 学术文档全文 ---\n" + paper_text
                markdown_outline = call_gemini(api_key, prompt_for_outline)

                if markdown_outline.startswith("调用AI时出错"):
                    st.error(markdown_outline)
                else:
                    st.success("✅ 汇报大纲生成成功！")
                    with st.expander("点击查看AI生成的Markdown大纲"):
                        st.markdown(markdown_outline)

                    # 步骤3: 调用Agent 3融合代码
                    st.info("步骤 3/3: 正在融合内容与模板 (再次调用AI，这步可能需要更长时间)...")
                    template_code = html_template.getvalue().decode("utf-8")
                    
                    final_prompt_parts = [
                        CODE_GENERATION_PROMPT_TEMPLATE,
                        "\n\n--- PPT Outline ---\n",
                        markdown_outline,
                        "\n\n--- HTML Template ---\n",
                        template_code
                    ]
                    
                    prompt_for_final_html = "".join(final_prompt_parts)
                    
                    final_html = call_gemini(api_key, prompt_for_final_html)

                    if final_html.startswith("调用AI时出错"):
                        st.error(final_html)
                    else:
                        st.success("🎉 恭喜！您的学术汇报已准备就绪！")
                        
                        # 提供下载按钮
                        st.download_button(
                            label="📥 下载您的学术汇报 (my_presentation.html)",
                            data=final_html.encode('utf-8'),
                            file_name='my_presentation.html',
                            mime='text/html',
                            use_container_width=True
                        )

st.sidebar.info("本应用由AI Agent驱动，旨在简化学术交流。")