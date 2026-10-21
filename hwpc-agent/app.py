"""Gradio 入口(C,B 在 2026-10-21 加了界面填凭证)。

提供Web界面用于输入任务、展示结果和导出。

凭证处理:公开部署时由使用者在界面自行填写,按会话隔离保存在 gr.State 里,
不写进全局变量、不写 os.environ、不落盘、不进日志。未填写时回退到环境变量,
方便本地开发。
"""
import os
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from agent import pipeline
from agent.contracts import TaskInput
from agent.export import export_markdown, export_report_only, export_text
from agent.llm import LLMConfig, LLMError
from agent.retriever.ima import ImaRetriever
from agent.retriever.ima_api import ImaCredentials, ImaError
from agent.retriever.local import LocalRetriever

# 加载环境变量
load_dotenv()

# 本地副本:仅开发期可用,云端没有这批文件(手册禁止上传知识库)
KB_ROOT = os.getenv("LOCAL_KB_ROOT", "../华为PC全板块深度知识库_v7")
LOCAL_KB_AVAILABLE = Path(KB_ROOT).exists()


def _blank_session() -> dict:
    """一个访客的会话状态。凭证只存在这里,随会话销毁。"""
    return {"retriever": None, "llm": None, "source": ""}


def init_local_session() -> dict:
    """开发期:直接用本地副本,免填 ima 凭证。"""
    if not LOCAL_KB_AVAILABLE:
        return _blank_session()
    return {"retriever": LocalRetriever(KB_ROOT), "llm": None, "source": "本地副本"}


def format_scene_profile(scene):
    """格式化场景判断。"""
    lines = []
    lines.append(f"**人群**：{scene.audience}")
    lines.append(f"**场景**：{scene.usage_scene}")
    lines.append(f"**购买阶段**：{scene.purchase_stage}")
    lines.append(f"**主要问题**：{scene.main_problem}")
    lines.append(f"**内容目标**：{scene.content_goal}")
    if scene.missing_info:
        lines.append(f"\n⚠️ **缺失信息**：{', '.join(scene.missing_info)}")
    return "\n".join(lines)


def format_knowledge_base(facts, model):
    """格式化知识库依据。"""
    lines = []
    lines.append(f"**型号**：{model}\n")
    lines.append(f"**事实点数量**：{len(facts)}\n")

    # 显示部分关键事实
    if facts:
        lines.append("**关键事实**：")
        for fact in facts[:5]:  # 只显示前5个
            lines.append(f"- {fact.field}: {fact.value}")
            if fact.qualifier:
                lines.append(f"  （{fact.qualifier}）")
            lines.append(f"  来源：{fact.source_title}")
        if len(facts) > 5:
            lines.append(f"...（共{len(facts)}条事实）")

    return "\n".join(lines)


def format_draft(draft):
    """格式化软文内容。"""
    lines = []
    lines.append(f"## {draft.title}\n")

    if draft.lead:
        lines.append(f"**{draft.lead}**\n")

    lines.append(draft.body)
    lines.append("")

    if draft.call_to_action:
        lines.append(f"**行动引导**：{draft.call_to_action}\n")

    if draft.image_plan:
        lines.append("**配图方案**：")
        for i, img in enumerate(draft.image_plan, 1):
            lines.append(f"{i}. {img.filename} - {img.caption}")
            lines.append(f"   来源：{img.source} | 位置：{img.suggested_position}")

    if draft.tags:
        lines.append(f"\n**标签**：{' '.join(f'#{tag}' for tag in draft.tags)}")

    return "\n".join(lines)


def format_verification(report):
    """格式化核验结果。"""
    lines = []

    # 总体状态
    if report.blocked:
        lines.append(f"### 🚫 状态：已阻断\n")
        lines.append(f"**原因**：{report.block_reason}\n")
    else:
        lines.append("### ✅ 状态：通过\n")

    # 事实核验
    lines.append("**事实核验**：")
    if report.fact_check:
        passed = sum(1 for item in report.fact_check if item.get("status") == "passed")
        failed = sum(1 for item in report.fact_check if item.get("status") == "failed")
        warning = sum(1 for item in report.fact_check if item.get("status") == "warning")
        lines.append(f"通过 {passed} | 失败 {failed} | 警告 {warning}")

        for item in report.fact_check:
            if item.get("status") != "passed":
                lines.append(f"- ⚠️ {item.get('issue', '')}")
    else:
        lines.append("无事实核验记录")

    # 图片核验
    lines.append("\n**图片型号核验**：")
    if report.image_check:
        passed = sum(1 for item in report.image_check if item.get("status") == "passed")
        failed = sum(1 for item in report.image_check if item.get("status") == "failed")
        lines.append(f"通过 {passed} | 失败 {failed}")

        for item in report.image_check:
            if item.get("status") == "failed":
                lines.append(f"- ❌ {item.get('issue', '')}")
    else:
        lines.append("无图片核验记录")

    # 合规检查
    lines.append("\n**合规检查**：")
    if report.compliance:
        blocking = sum(1 for item in report.compliance if item.get("blocking"))
        warning = len(report.compliance) - blocking
        lines.append(f"阻断项 {blocking} | 警告项 {warning}")

        for item in report.compliance[:5]:  # 只显示前5项
            emoji = "🚫" if item.get("blocking") else "⚠️"
            category = item.get("category", item.get("type", ''))
            lines.append(f"- {emoji} {category}: {item.get('issue', '')}")

        if len(report.compliance) > 5:
            lines.append(f"...（共{len(report.compliance)}项，详见完整报告）")
    else:
        lines.append("✅ 无合规问题")

    # 待确认信息
    if report.to_confirm:
        lines.append("\n**待确认信息**：")
        for item in report.to_confirm[:3]:
            lines.append(f"- {item}")
        if len(report.to_confirm) > 3:
            lines.append(f"...（共{len(report.to_confirm)}项）")

    return "\n".join(lines)


def connect_knowledge_base(client_id, api_key, kb_name, session):
    """用界面填的 ima 凭证连接知识库。凭证只进会话状态,不写环境变量。"""
    session = dict(session or _blank_session())
    cid, key = (client_id or "").strip(), (api_key or "").strip()
    if not cid or not key:
        missing = "、".join(n for n, v in (("Client ID", cid), ("API Key", key)) if not v)
        return f"⚠️ 请先填写 {missing}", session
    try:
        retr = ImaRetriever(
            creds=ImaCredentials(client_id=cid, api_key=key),
            kb_name=(kb_name or "").strip() or None,
        )
        name = retr.check_connection()
    except ImaError as exc:
        # ImaError 的 message 已脱敏,可直接展示
        return f"❌ 连接失败：{exc}", session
    except Exception as exc:  # noqa: BLE001  不展示未知异常的原文,避免带出凭证
        return f"❌ 连接失败：{type(exc).__name__}", session
    session["retriever"] = retr
    session["source"] = f"ima 知识库「{name}」"
    return f"✅ 已连接 {session['source']}", session


def use_local_knowledge_base(session):
    """开发期回退:用本地副本,不需要 ima 凭证。"""
    session = dict(session or _blank_session())
    if not LOCAL_KB_AVAILABLE:
        return f"❌ 本地副本不可用（LOCAL_KB_ROOT={KB_ROOT}）", session
    session["retriever"] = LocalRetriever(KB_ROOT)
    session["source"] = "本地副本"
    return "✅ 已连接本地副本（仅开发期可用）", session


def save_llm_config(base_url, api_key, model, session):
    """保存大模型配置到会话。不做真实调用,避免消耗额度。"""
    session = dict(session or _blank_session())
    try:
        cfg = LLMConfig(
            base_url=(base_url or "").strip(),
            api_key=(api_key or "").strip(),
            model=(model or "").strip(),
        ).require()
    except LLMError as exc:
        return f"⚠️ {exc}", session
    session["llm"] = cfg
    return f"✅ 已保存大模型配置（模型：{cfg.model}）。生成时才会真正调用。", session


def current_status(session) -> str:
    """顶部状态条。只显示知识库名和模型名,不显示任何凭证。"""
    session = session or _blank_session()
    kb = session.get("source") or "未连接"
    cfg = session.get("llm")
    if cfg:
        llm_txt = f"已配置（{cfg.model}）"
    elif LLMConfig.from_env().api_key:
        llm_txt = "用环境变量"
    else:
        llm_txt = "未配置"
    return f"**知识库**：{kb} ｜ **大模型**：{llm_txt}"


def run_pipeline(product, audience, scene, platform, extra_requirements, session):
    """运行完整流程。"""
    session = session or _blank_session()
    retriever = session.get("retriever")
    if not retriever:
        return "❌ 请先在上方「① 连接知识库」里连接 ima 或本地副本", "", "", "", "", ""

    if not product:
        return "❌ 错误：请输入产品型号", "", "", "", "", ""

    # 构建任务输入
    task = TaskInput(
        product=product,
        audience=audience,
        scene=scene,
        platform=platform,
        extra_requirements=extra_requirements
    )

    try:
        # 运行pipeline。llm_config 为界面填写的配置,None 时回退到环境变量
        steps = pipeline.real_steps(retriever, llm_config=session.get("llm"))
        result = pipeline.run(task, retriever, steps)

        # 根据状态返回结果
        if result.status == "need_info":
            questions = "\n".join(f"- {q}" for q in result.questions)
            return f"ℹ️ 需要补充信息：\n{questions}", "", "", "", "", ""

        if result.status == "blocked":
            reason = result.report.block_reason if result.report else "未知原因"
            return f"🚫 流程已阻断：{reason}", "", "", "", "", ""

        if result.status != "ok":
            return f"❌ 流程异常：{result.status}", "", "", "", "", ""

        # 成功：格式化各部分输出
        scene_text = format_scene_profile(result.scene) if result.scene else ""
        kb_text = format_knowledge_base(result.facts or [], result.task.model)
        draft_text = format_draft(result.draft) if result.draft else ""
        verify_text = format_verification(result.report) if result.report else ""

        # 生成导出内容
        markdown_export = export_markdown(result.draft, result.report) if result.draft else ""
        text_export = export_text(result.draft, result.report) if result.draft else ""

        return scene_text, kb_text, draft_text, verify_text, markdown_export, text_export

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return f"❌ 执行出错：{str(e)}\n\n{error_detail}", "", "", "", "", ""


def create_ui():
    """创建Gradio界面。"""

    # Gradio 6:theme 已从 Blocks 移到 launch()
    with gr.Blocks(title="华为PC营销软文智能体") as demo:
        gr.Markdown(
            """
            # 华为PC营销软文智能体

            自研Agent闭环：场景解析 → 平台策略 → 知识库检索 → 事实点提取 → 图文编排 →
            软文生成 → 事实与图片核验 → 合规检查 → 导出

            ---
            """
        )

        # 每个访客一份会话状态,凭证只存这里,互不可见
        session = gr.State(init_local_session)

        status_bar = gr.Markdown(current_status(init_local_session()))

        with gr.Accordion("⚙️ 连接配置（凭证只保存在当前会话，不上传、不记录）", open=not LOCAL_KB_AVAILABLE):
            gr.Markdown(
                "凭证仅用于本次浏览器会话，关闭页面即失效。"
                "本站不保存、不记录、不会显示在任何输出里。"
                "ima 凭证在 ima 客户端的「开放平台」里获取。"
            )
            with gr.Row():
                with gr.Column():
                    gr.Markdown("#### ① 连接知识库（ima）")
                    ima_cid = gr.Textbox(
                        label="ima Client ID",
                        type="password",
                        placeholder="IMA_OPENAPI_CLIENTID",
                    )
                    ima_key = gr.Textbox(
                        label="ima API Key",
                        type="password",
                        placeholder="IMA_OPENAPI_APIKEY",
                    )
                    ima_kb = gr.Textbox(
                        label="知识库名称",
                        placeholder="留空则用默认名称",
                        info="需与 ima 里的知识库名称完全一致",
                    )
                    with gr.Row():
                        connect_btn = gr.Button("连接 ima 知识库", variant="primary")
                        local_btn = gr.Button("用本地副本（开发期）")
                    ima_status = gr.Markdown()

                with gr.Column():
                    gr.Markdown("#### ② 配置大模型（OpenAI 兼容接口）")
                    llm_base = gr.Textbox(
                        label="Base URL",
                        placeholder="https://api.deepseek.com/v1",
                        info="任何 OpenAI 兼容接口，如 DeepSeek、通义",
                    )
                    llm_key = gr.Textbox(label="API Key", type="password", placeholder="sk-...")
                    llm_model = gr.Textbox(label="模型名", placeholder="deepseek-chat")
                    save_llm_btn = gr.Button("保存大模型配置", variant="primary")
                    llm_status = gr.Markdown()

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("## 📝 输入任务")

                product_input = gr.Textbox(
                    label="产品/型号",
                    placeholder="例如：MateBook 14、D 16、Pro",
                    info="输入产品名称或型号"
                )

                audience_input = gr.Textbox(
                    label="目标人群",
                    placeholder="例如：大学新生、商务人士、内容创作者",
                    info="可选，系统会根据场景推断"
                )

                scene_input = gr.Textbox(
                    label="使用场景",
                    placeholder="例如：宿舍写论文、出差办公、视频剪辑",
                    info="可选，描述主要使用场景"
                )

                platform_input = gr.Dropdown(
                    label="发布平台",
                    choices=["公众号", "小红书", "朋友圈", "海报"],
                    value="小红书",
                    info="选择目标发布平台"
                )

                extra_input = gr.Textbox(
                    label="临时要求",
                    placeholder="例如：强调续航、突出设计、面向学生预算",
                    lines=2,
                    info="可选，额外的创作要求"
                )

                generate_btn = gr.Button("🚀 生成软文", variant="primary", size="lg")

            with gr.Column(scale=2):
                gr.Markdown("## 📊 输出结果")

                with gr.Tabs():
                    with gr.Tab("一、场景判断"):
                        scene_output = gr.Markdown()

                    with gr.Tab("二、知识库依据"):
                        kb_output = gr.Markdown()

                    with gr.Tab("三、图文软文"):
                        draft_output = gr.Markdown()

                    with gr.Tab("四、核验结果"):
                        verify_output = gr.Markdown()

                    with gr.Tab("📥 导出（Markdown）"):
                        markdown_output = gr.Textbox(
                            lines=20,
                            buttons=["copy"],  # Gradio 6 用 buttons 代替 show_copy_button
                            label="Markdown格式"
                        )

                    with gr.Tab("📥 导出（纯文本）"):
                        text_output = gr.Textbox(
                            lines=20,
                            buttons=["copy"],  # Gradio 6 用 buttons 代替 show_copy_button
                            label="纯文本格式"
                        )

        # 绑定事件。每个配置动作结束后刷新顶部状态条
        connect_btn.click(
            fn=connect_knowledge_base,
            inputs=[ima_cid, ima_key, ima_kb, session],
            outputs=[ima_status, session],
        ).then(fn=current_status, inputs=session, outputs=status_bar)

        local_btn.click(
            fn=use_local_knowledge_base,
            inputs=session,
            outputs=[ima_status, session],
        ).then(fn=current_status, inputs=session, outputs=status_bar)

        save_llm_btn.click(
            fn=save_llm_config,
            inputs=[llm_base, llm_key, llm_model, session],
            outputs=[llm_status, session],
        ).then(fn=current_status, inputs=session, outputs=status_bar)

        generate_btn.click(
            fn=run_pipeline,
            inputs=[product_input, audience_input, scene_input, platform_input, extra_input, session],
            outputs=[scene_output, kb_output, draft_output, verify_output, markdown_output, text_output]
        )

        gr.Markdown(
            """
            ---

            ### 📌 使用说明

            1. **必填项**：产品/型号
            2. **可选项**：目标人群、使用场景、临时要求
            3. **信息不足时**：系统会提示需要补充的信息
            4. **核验阻断**：如果事实或合规检查未通过，会明确标注
            5. **导出**：可复制Markdown或纯文本格式，用于后续编辑

            ### ⚠️ 注意事项

            - 图片必须来自知识库且型号一致
            - 价格必须有依据且带类型和日期
            - 禁止虚构体验、评价、销量、奖项
            - 凭证只保存在当前会话，不落盘、不进日志、不会显示在界面或导出内容里
            - ima 取原文有每日次数上限，用尽后需次日恢复
            """
        )

    return demo


def main():
    """主入口。

    默认只监听本机,调试时不对局域网开放。部署到魔搭创空间时用
    GRADIO_SERVER_NAME=0.0.0.0 覆盖(平台侧自带访问控制)。
    """
    demo = create_ui()
    demo.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        share=False,
        show_error=True,
        theme=gr.themes.Soft(),  # Gradio 6:theme 在 launch() 里传
    )


if __name__ == "__main__":
    main()
