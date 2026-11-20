"""Local-only Gradio alpha UI. No account login, automatic publishing or scraping."""

import os
from pathlib import Path

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr

from copilot import (
    analyze_csv,
    build_metrics_summary,
    build_note_bundle,
    draft,
    format_assistant_reply,
    format_status,
    format_tags,
    ranked_note_rows,
)
from provider import ProviderError
from workflows import (
    DEMO_LABEL,
    REAL_LABEL,
    check_config,
    copy_text,
    editor_feedback,
    editor_note,
    export_metrics,
    import_note,
    load_model_config,
)

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / ".local" / "exports"
RANK_HEADERS = ["note_id", "标题", "阅读", "互动", "互动次数 / 阅读次数"]
CSS = """
.gradio-container { max-width: 1320px !important; }
.note-preview { border: 1px solid #edd7dc; border-radius: 20px; padding: 24px;
  background: var(--block-background-fill); overflow-wrap: anywhere; }
.note-preview small { opacity: .65; }
.note-preview h2 { font-size: 22px; line-height: 1.5; margin: 16px 0; }
.note-body { white-space: pre-wrap; line-height: 1.85; }
.note-tags { color: #ba334f; white-space: pre-wrap; }
.note-preview aside { border-top: 1px solid #edd7dc; margin-top: 20px; padding-top: 16px; }

@media (max-width: 720px) {
  .gradio-container { padding: 8px !important; }
  .note-preview { padding: 16px; border-radius: 16px; }
  .note-preview h2 { font-size: 18px; }
}
"""
# Gradio renders labels as siblings, so the inner textarea/input has no accessible
# name. Attach one from the component wrapper, and re-apply after re-renders.
JS = """
() => {
  const labels = {
    "rn-message": "真实素材 / 修改要求",
    "rn-title": "标题",
    "rn-body": "正文",
    "rn-tags": "话题（空格 / 逗号分隔，自动去重）",
    "rn-missing": "待补充信息（不会进入可复制文案）",
    "rn-copy": "标题 + 正文 + 话题",
  };
  let pending = null;
  const apply = () => {
    pending = null;
    for (const [id, label] of Object.entries(labels)) {
      const wrapper = document.getElementById(id);
      const control = wrapper && wrapper.querySelector("textarea, input");
      if (!control) continue;
      if (!control.id) control.id = id + "-input";
      if (control.getAttribute("aria-label") !== label) {
        control.setAttribute("aria-label", label);
      }
    }
  };
  const schedule = () => {
    if (pending === null) pending = setTimeout(apply, 50);
  };
  apply();
  new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true});
}
"""


def _raise_ui_error(exc):
    if isinstance(exc, (ValueError, ProviderError)):
        raise gr.Error(str(exc)) from None
    if isinstance(exc, UnicodeError):
        raise gr.Error("文件编码错误，请使用 UTF-8 导出后重试") from None
    if isinstance(exc, OSError):
        raise gr.Error("无法读取或写入本地文件，请检查文件和目录权限") from None
    raise gr.Error("操作失败；当前稿件未改动。请检查配置或开始新稿后重试。") from None


WRITING_CONTROL_COUNT = 11


def set_writing_interactive(enabled):
    return [gr.update(interactive=enabled) for _ in range(WRITING_CONTROL_COUNT)]


def lock_writing(writing_locked):
    if writing_locked:
        raise gr.Error("正在生成中，请等待本轮完成。")
    return (True, *set_writing_interactive(False))


def unlock_writing():
    return (False, *set_writing_interactive(True))


def export_bundle_guarded(writing_locked, title, body, tags, missing):
    if writing_locked:
        raise gr.Error("正在生成中，导出已锁定。")
    return export_bundle(title, body, tags, missing)


def restore_note_guarded(writing_locked, file):
    if writing_locked:
        raise gr.Error("正在生成中，恢复已锁定。")
    return restore_note(file)


def clear_session_guarded(writing_locked):
    if writing_locked:
        raise gr.Error("正在生成中，新稿已锁定。")
    return clear_session()


def load_sample_draft(writing_locked):
    return restore_note_guarded(writing_locked, str(ROOT / "examples" / "draft.synthetic.json"))


def analyze_sample():
    return analyze(str(ROOT / "example-metrics.csv"))


def validate_config_ui(config_text, mode):
    try:
        return check_config(config_text, mode)
    except Exception as exc:
        _raise_ui_error(exc)


def sync_preview(title, body, tags, missing):
    preview, count, checklist = editor_feedback(title, body, tags, missing)
    return preview, count, checklist, copy_text(title, body, tags), None


def generate(message, model_history, config_text, mode, title="", body="", tags="", missing=""):
    """Atomic: failed requests do not replace the current editor or append history."""
    try:
        spec = load_model_config(config_text, mode)
        note, updated_history, meta = draft(
            message, model_history, spec, current_note=editor_note(title, body, tags, missing)
        )
        title, body = note["title"], note["body"]
        tags, missing = format_tags(note["tags"]), "\n".join(note["missing_info"])
        preview, count, checklist = editor_feedback(title, body, tags, missing)
        dialogue = []
        for turn in updated_history:
            if turn["role"] == "user":
                dialogue.append({"role": "user", "content": turn["content"]})
            else:
                dialogue.append({"role": "assistant", "content": "草稿已更新，请查看右侧编辑区。"})
        dialogue[-1]["content"] = format_assistant_reply(note, meta)
        return (
            updated_history,
            dialogue,
            title,
            body,
            tags,
            missing,
            preview,
            count,
            checklist,
            copy_text(title, body, tags),
            format_status(meta),
            None,
        )
    except Exception as exc:
        _raise_ui_error(exc)


def export_bundle(title, body, tags, missing):
    try:
        bundle = build_note_bundle(title, body, tags, missing, EXPORT_DIR)
        suffix = " 注意：仍有待补充信息，请勿直接发布。" if missing.strip() else ""
        return (
            bundle,
            "已导出当前编辑稿（TXT / Markdown / JSON / 发布清单），未发布到小红书。" + suffix,
        )
    except Exception as exc:
        _raise_ui_error(exc)


def restore_note(file):
    try:
        note = import_note(file)
        title, body = note["title"], note["body"]
        tags, missing = format_tags(note["tags"]), "\n".join(note["missing_info"])
        preview, count, checklist = editor_feedback(title, body, tags, missing)
        return (
            [],
            [],
            title,
            body,
            tags,
            missing,
            preview,
            count,
            checklist,
            copy_text(title, body, tags),
            "已恢复 JSON 草稿并清空旧对话；继续改稿以当前稿件为准。",
            None,
        )
    except Exception as exc:
        _raise_ui_error(exc)


def clear_session():
    preview, count, checklist = editor_feedback("", "", "", "")
    return (
        [],
        [],
        "",
        "",
        "",
        "",
        preview,
        count,
        checklist,
        "",
        "已开始新稿；先前导出文件仍保存在本机。",
        None,
        "",
        None,
    )


def analyze(file):
    if not file:
        raise gr.Error("请选择 CSV")
    try:
        path = Path(file)
        if path.suffix.lower() != ".csv":
            raise ValueError("仅支持 CSV 文件")
        if path.stat().st_size > 5_000_000:
            raise ValueError("CSV 超过 5 MB")
        report = analyze_csv(path.read_text(encoding="utf-8-sig"))
        return report, build_metrics_summary(report), report, ranked_note_rows(report), None
    except Exception as exc:
        _raise_ui_error(exc)


def export_metrics_ui(report):
    try:
        return export_metrics(report, EXPORT_DIR)
    except Exception as exc:
        _raise_ui_error(exc)


def build_app():
    empty_preview, empty_count, empty_checklist = editor_feedback("", "", "", "")
    with gr.Blocks(
        title="Rednote Copilot · alpha",
        theme=gr.themes.Soft(primary_hue="rose"),
        css=CSS,
        js=JS,
        analytics_enabled=False,
    ) as demo:
        gr.Markdown(
            "# Rednote Copilot\n### 写下来，改到满意，再复盘。\n本地小红书创作助手 · alpha · 无自动登录 / 发帖 / 后台读取"
        )
        model_history = gr.State([])
        writing_locked = gr.State(False)
        report_state = gr.State(None)
        with gr.Tab("✍ 创作工作台"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5, min_width=280):
                    mode = gr.Radio([DEMO_LABEL, REAL_LABEL], value=DEMO_LABEL, label="写作模式")
                    gr.Markdown(
                        "**离线演示不是 AI**：仅整理素材；再次改稿保留当前文案并记录要求。真实智能改写需配置自己的模型。"
                    )
                    with gr.Accordion("真实模型配置（Key 只从环境变量读取）", open=False):
                        config = gr.Code(
                            (ROOT / "config.real.example.json").read_text(encoding="utf-8"),
                            language="json",
                            label="OpenAI-compatible 配置",
                            lines=9,
                        )
                        config_check = gr.Button("检查配置（不请求模型）")
                        config_status = gr.Textbox(label="配置检查结果", interactive=False)
                        gr.Markdown(
                            "素材和当前稿件会发送给所选模型服务；不要输入 Cookie、Key 或不应外发的数据。"
                        )
                    dialogue = gr.Chatbot(
                        type="messages",
                        label="创作对话（最近 8 轮）",
                        height=280,
                        render_markdown=False,
                        sanitize_html=True,
                        allow_tags=False,
                    )
                    message = gr.Textbox(
                        label="真实素材 / 修改要求",
                        lines=4,
                        placeholder="描述你的主题、目标读者、亲身经历或事实依据。修改时以右侧手动编辑的当前稿件为准。",
                        max_length=20000,
                        elem_id="rn-message",
                    )
                    gr.Examples(
                        examples=[
                            [
                                "合成演示素材：给运营同学介绍一个 AI 复盘工具。可以导入 CSV 计算加权互动率。语气克制，不声称用过或提升流量。"
                            ],
                            ["保留我手动写的开头，把正文缩短，结尾只提一个问题。"],
                        ],
                        inputs=message,
                    )
                    with gr.Row():
                        button = gr.Button("生成 / 基于当前稿修改", variant="primary")
                        clear = gr.Button("开始新稿（清空）")
                    sample_draft = gr.Button("载入示例草稿（替换当前稿）")
                    status = gr.Textbox(
                        value="离线演示就绪。未调用真实模型，未发布。",
                        label="操作状态",
                        interactive=False,
                    )
                    with gr.Accordion("恢复上次导出的草稿", open=False):
                        restore_file = gr.File(
                            label="内容包里的 JSON 草稿", file_types=[".json"], type="filepath"
                        )
                        restore_button = gr.Button("恢复草稿（替换当前稿并清空对话）")
                with gr.Column(scale=6, min_width=280):
                    gr.Markdown(
                        "## 当前编辑稿\n手动修改自动更新预览；下一轮生成以这里为准。刷新页面不会保留未导出的草稿。"
                    )
                    title = gr.Textbox(label="标题", max_length=500, elem_id="rn-title")
                    body = gr.Textbox(label="正文", lines=10, max_length=20000, elem_id="rn-body")
                    tags = gr.Textbox(label="话题（空格 / 逗号分隔，自动去重）", elem_id="rn-tags")
                    missing = gr.Textbox(
                        label="待补充信息（不会进入可复制文案）", lines=3, elem_id="rn-missing"
                    )
                    count = gr.Textbox(value=empty_count, label="字数参考", interactive=False)
                    preview = gr.HTML(empty_preview, label="安全文本预览")
                    with gr.Accordion("可复制文案", open=True):
                        copy = gr.Textbox(
                            label="标题 + 正文 + 话题",
                            lines=6,
                            interactive=False,
                            show_copy_button=True,
                            elem_id="rn-copy",
                        )
                    with gr.Accordion("发布准备与提醒", open=False):
                        checklist = gr.Markdown(empty_checklist)
                        gr.Markdown(
                            "导出后由你在小红书创作者页面粘贴文案、添加图片/封面并确认发布。本应用没有发布按钮。"
                        )
                    export = gr.Button("导出当前编辑稿内容包", variant="primary")
                    bundle = gr.File(
                        label="ZIP：TXT / Markdown / JSON / 发布检查清单", interactive=False
                    )
        with gr.Tab("📊 数据复盘"):
            gr.Markdown(
                "## 导入后看结果\n每篇笔记一行**最新累计值**，而不是多天累计快照。字段：`note_id,title,views,likes,saves,comments`。全程本地统计，不发送给模型。"
            )
            with gr.Row():
                csv_file = gr.File(
                    file_types=[".csv"],
                    type="filepath",
                    label="运营 CSV（UTF-8，最大 5 MB，最多 10000 篇）",
                )
                gr.File(
                    value=str(ROOT / "example-metrics.csv"),
                    label="下载字段示例（合成数据）",
                    interactive=False,
                )
            analyze_button = gr.Button("分析 CSV", variant="primary")
            sample_metrics = gr.Button("查看示例复盘（合成数据）")
            summary = gr.Markdown()
            ranked = gr.Dataframe(
                headers=RANK_HEADERS,
                datatype=["str", "str", "number", "number", "str"],
                interactive=False,
                label="按互动次数 / 阅读次数排序",
            )
            with gr.Accordion("结构化结果与导出", open=False):
                result = gr.JSON(label="统计口径与全部笔记")
                metrics_export = gr.Button("导出复盘 JSON")
                metrics_file = gr.File(label="复盘结果", interactive=False)
            csv_file.change(
                lambda: (None, "", None, [], None),
                outputs=[report_state, summary, result, ranked, metrics_file],
                queue=False,
                api_name=False,
            )
        gr.Markdown(
            "**数据边界**：无账号连接、无 Cookie。下载文件保存在 `.local/exports/`；新稿不删除导出文件，敏感草稿使用后请自行清理。"
        )
        editor = [title, body, tags, missing]
        write_outputs = [
            model_history,
            dialogue,
            *editor,
            preview,
            count,
            checklist,
            copy,
            status,
            bundle,
        ]
        write_options = {"concurrency_id": "writing", "concurrency_limit": 4}
        protected_controls = [
            message,
            *editor,
            button,
            clear,
            export,
            restore_button,
            mode,
            sample_draft,
        ]
        protected_outputs = [writing_locked, *protected_controls]
        start_generation = button.click(
            lock_writing,
            inputs=writing_locked,
            outputs=protected_outputs,
            queue=False,
            api_name=False,
        )
        # A rejected duplicate click must not start another generation or unlock
        # the first request. Only continue after acquiring this session's lock.
        generate_event = start_generation.success(
            generate,
            [message, model_history, config, mode, *editor],
            write_outputs,
            api_name="generate",
            **write_options,
        )
        generate_event.success(
            unlock_writing,
            outputs=protected_outputs,
            queue=False,
            api_name=False,
        )
        generate_event.failure(
            unlock_writing,
            outputs=protected_outputs,
            queue=False,
            api_name=False,
        )
        config_check.click(
            validate_config_ui, [config, mode], config_status, api_name="check_config"
        )
        export.click(
            export_bundle_guarded,
            [writing_locked, *editor],
            [bundle, status],
            api_name="export_bundle",
            **write_options,
        )
        sample_draft.click(
            load_sample_draft,
            writing_locked,
            write_outputs,
            api_name="load_sample_draft",
            **write_options,
        )
        sample_metrics.click(
            analyze_sample,
            outputs=[report_state, summary, result, ranked, metrics_file],
            api_name="analyze_sample",
            concurrency_id="metrics",
            concurrency_limit=1,
        )
        restore_button.click(
            restore_note_guarded,
            [writing_locked, restore_file],
            write_outputs,
            api_name="restore_note",
            **write_options,
        )
        clear.click(
            clear_session_guarded,
            writing_locked,
            outputs=[*write_outputs, message, restore_file],
            api_name="new_note",
            **write_options,
        )
        for component in editor:
            component.input(
                sync_preview,
                editor,
                [preview, count, checklist, copy, bundle],
                queue=False,
                api_name=False,
            )
        analyze_button.click(
            analyze,
            csv_file,
            [report_state, summary, result, ranked, metrics_file],
            api_name="analyze_csv",
            concurrency_id="metrics",
            concurrency_limit=1,
        )
        metrics_export.click(
            export_metrics_ui,
            report_state,
            metrics_file,
            api_name="export_metrics",
            concurrency_id="metrics",
            concurrency_limit=1,
        )
    return demo


def main():
    try:
        port = int(os.getenv("PORT", "7863"))
    except ValueError:
        raise ValueError("PORT 必须是 1-65535 的整数端口") from None
    if not 1 <= port <= 65535:
        raise ValueError("PORT 必须是 1-65535 的端口")
    build_app().queue(max_size=20).launch(
        server_name="127.0.0.1",
        server_port=port,
        share=False,
        show_error=False,
        max_file_size="5mb",
    )


if __name__ == "__main__":
    main()
