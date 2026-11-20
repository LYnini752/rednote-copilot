"""Pure UI-facing workflow helpers. No Gradio import or network at import time."""

import html
import json
import os
import uuid
from pathlib import Path

from copilot import build_publish_checklist, format_tags, normalize_note, parse_tags
from provider import validate_model

DEMO_LABEL = "演示模板（离线，不是 AI）"
REAL_LABEL = "真实模型（OpenAI-compatible）"
MAX_IMPORT_BYTES = 1_000_000


def load_model_config(text, mode):
    """Demo never reads credentials; real configuration is validated explicitly."""
    if mode == DEMO_LABEL:
        return {"name": "Demo mode", "mode": "demo"}
    if mode != REAL_LABEL:
        raise ValueError("请选择有效的模型模式")
    if not isinstance(text, str) or len(text) > 20000:
        raise ValueError("模型配置过长或格式无效")
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型配置 JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列") from None
    if isinstance(spec, dict) and any(
        spec.get(key) in {"demo", "mock", "template"}
        for key in ("mode", "provider")
        if isinstance(spec.get(key), str)
    ):
        raise ValueError("真实模型模式不能使用 demo 配置")
    validate_model(spec)
    return spec


def check_config(text, mode):
    spec = load_model_config(text, mode)
    if mode == DEMO_LABEL:
        return "演示模板已就绪。无需 Key，不连接网络，不进行智能改写。"
    env_name = spec.get("api_key_env")
    if env_name and not os.getenv(env_name):
        raise ValueError("指定的 Key 环境变量尚未设置；请在启动应用的终端配置后重启。")
    return "配置格式与 Key 环境变量检查通过；尚未请求模型，网络和模型权限仍需生成时验证。"


def editor_note(title, body, tags, missing):
    return {
        "title": title or "",
        "body": body or "",
        "tags": parse_tags(tags),
        "missing_info": [line.strip() for line in (missing or "").splitlines() if line.strip()],
    }


def render_preview(title, body, tags, missing):
    """Escape all user/model text; no active HTML, Markdown links or remote images."""
    note = editor_note(title, body, tags, missing)
    safe_title = html.escape(note["title"] or "未命名草稿")
    safe_body = html.escape(note["body"] or "正文待补充")
    safe_tags = html.escape(format_tags(note["tags"]))
    safe_missing = "".join(f"<li>{html.escape(item)}</li>" for item in note["missing_info"])
    missing_block = (
        f"<aside><strong>待补充（不计入复制文案）</strong><ul>{safe_missing}</ul></aside>"
        if safe_missing
        else ""
    )
    return f'<article class="note-preview"><small>笔记预览 · 非平台最终效果</small><h2>{safe_title}</h2><div class="note-body">{safe_body}</div><p class="note-tags">{safe_tags}</p>{missing_block}</article>'


def editor_feedback(title, body, tags, missing):
    note = editor_note(title, body, tags, missing)
    count = (
        f"标题 {len(note['title'])} 字 · 正文 {len(note['body'])} 字 · {len(note['tags'])} 个话题"
    )
    checklist = build_publish_checklist(title, body, tags)
    if note["missing_info"] or "待补充" in (body or ""):
        checklist += "\n\n- **稿件含待补充内容**，导出不代表可以直接发布，请先完成事实核对。"
    checklist += "\n\n> 字数/话题提醒为本项目写作建议，不是已核验的平台硬性限制。"
    return render_preview(title, body, tags, missing), count, checklist


def copy_text(title, body, tags):
    return (title or "").strip() + "\n\n" + (body or "").strip() + "\n\n" + format_tags(tags)


def import_note(path):
    if not path:
        raise ValueError("请先选择导出内容包中的 JSON 草稿")
    source = Path(path)
    if source.suffix.lower() != ".json":
        raise ValueError("仅支持导入 JSON 草稿，不读取 ZIP 或其他文件")
    if source.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("草稿 JSON 不得超过 1 MB")
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("草稿不是有效的 UTF-8 JSON 文件") from None
    if not isinstance(raw, dict) or set(raw) - {"title", "body", "tags", "missing_info"}:
        raise ValueError("只接受草稿字段 title、body、tags、missing_info；不得导入模型配置或凭据")
    return normalize_note(raw)


def export_metrics(report, output_dir):
    if not isinstance(report, dict) or "ranked_notes" not in report:
        raise ValueError("请先分析 CSV，再导出复盘结果")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"metrics-{uuid.uuid4().hex}.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    path.chmod(0o600)
    return str(path)
