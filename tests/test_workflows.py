import json
import zipfile

import pytest

import copilot
from copilot import draft, normalize_note, parse_tags
from workflows import (
    DEMO_LABEL,
    REAL_LABEL,
    check_config,
    copy_text,
    editor_feedback,
    export_metrics,
    import_note,
    load_model_config,
    render_preview,
)

NOTE = {
    "title": "用户手改标题",
    "body": "这是用户自己补充的事实。",
    "tags": ["运营"],
    "missing_info": [],
}
SPEC = {"name": "test", "model": "test", "base_url": "http://127.0.0.1:8080/v1"}


def test_real_draft_uses_manual_editor_as_authoritative_context(monkeypatch):
    captured = []

    def fake_chat(spec, messages):
        captured.extend(messages)
        return {"text": json.dumps(NOTE), "model": "mock-model", "seconds": 0.01}

    monkeypatch.setattr(copilot, "chat", fake_chat)
    history = [{"role": "user", "content": "旧要求"}, {"role": "assistant", "content": "旧稿"}]
    before = list(history)
    result, updated, meta = draft("缩短正文", history, SPEC, current_note=NOTE)
    assert captured[0]["role"] == "system"
    assert "用户手改标题" in captured[-2]["content"]
    assert captured[-1]["content"] == "缩短正文"
    assert history == before
    assert result == NOTE
    assert meta["provider"] == "openai-compatible"
    assert updated[-1]["role"] == "assistant"


def test_history_is_bounded_and_not_mutated():
    history = [
        {"role": role, "content": "旧素材"} for _ in range(40) for role in ("user", "assistant")
    ]
    _, updated, _ = draft("新的素材", history, {"mode": "demo"})
    assert len(updated) == 16
    assert len(history) == 80


def test_demo_revision_preserves_manual_editor_not_fake_ai():
    note, _, meta = draft("缩短正文", [], {"mode": "demo"}, current_note=NOTE)
    assert note["title"] == NOTE["title"]
    assert note["body"] == NOTE["body"]
    assert "演示模板" in note["missing_info"][0]
    assert meta["provider"] == "demo"


@pytest.mark.parametrize("bad_tags", [None, "标签", [None], [42], {"x": "y"}])
def test_invalid_model_tag_schema_rejected(bad_tags):
    with pytest.raises(ValueError):
        normalize_note({**NOTE, "tags": bad_tags})


@pytest.mark.parametrize("message", ["", "   ", "a" * 20001])
def test_bad_materials_rejected(message):
    with pytest.raises(ValueError):
        draft(message, [], {"mode": "demo"})


def test_preview_escapes_every_field_and_has_no_active_links():
    preview = render_preview(
        '<img src=x onerror="alert(1)">',
        "<script>alert(1)</script>\n![remote](https://example.com/track)",
        "#<iframe>",
        '<a href="https://example.com">x</a>',
    )
    assert "<script>" not in preview
    assert "<img" not in preview
    assert "<iframe" not in preview
    assert "<a href=" not in preview
    assert "&lt;script&gt;" in preview
    assert "https://example.com/track" in preview  # text, not an active URL/image


def test_copy_omits_missing_info():
    assert copy_text(" 标题 ", " 正文 ", "#a #a,b") == "标题\n\n正文\n\n#a #b"


def test_tag_parse_does_not_silently_drop_eleventh_tag():
    assert len(parse_tags(" ".join(f"tag{i}" for i in range(12)))) == 12


def test_feedback_warns_missing_info():
    _, count, checklist = editor_feedback("标题", "正文待补充", "话题", "补事实")
    assert "标题 2 字" in count
    assert "待补充内容" in checklist
    assert "不是已核验" in checklist


def test_config_demo_does_not_parse_real_credentials():
    assert load_model_config("not json", DEMO_LABEL)["mode"] == "demo"
    assert "无需 Key" in check_config("not json", DEMO_LABEL)


@pytest.mark.parametrize("text", ["not json", "[]", '{"mode":"demo"}', '{"api_key":"nope"}'])
def test_bad_real_config_rejected(text):
    with pytest.raises(ValueError):
        load_model_config(text, REAL_LABEL)


def test_config_check_never_echoes_key(monkeypatch):
    monkeypatch.setenv("COPILOT_TEST_KEY", "secret-local-fixture")
    text = json.dumps({**SPEC, "api_key_env": "COPILOT_TEST_KEY"})
    assert "secret-local-fixture" not in check_config(text, REAL_LABEL)
    assert "尚未请求模型" in check_config(text, REAL_LABEL)
    monkeypatch.delenv("COPILOT_TEST_KEY")
    with pytest.raises(ValueError, match="尚未设置"):
        check_config(text, REAL_LABEL)


def test_export_restore_roundtrip(tmp_path):
    path = copilot.build_note_bundle(**{**NOTE, "missing_info": ""}, output_dir=tmp_path)
    with zipfile.ZipFile(path) as archive:
        data = next(archive.read(name) for name in archive.namelist() if name.endswith(".json"))
    restored = tmp_path / "draft.json"
    restored.write_bytes(data)
    assert import_note(restored) == NOTE
    assert len(list(tmp_path.glob("*.zip"))) == 1
    assert not any(item.is_dir() for item in tmp_path.iterdir())


@pytest.mark.parametrize(
    "data", [[], {**NOTE, "api_key": "fixture"}, {**NOTE, "tags": "bad"}, {**NOTE, "title": ""}]
)
def test_import_rejects_non_note_or_bad_fields(tmp_path, data):
    path = tmp_path / "note.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        import_note(path)


def test_import_handles_bom_and_invalid_encoding(tmp_path):
    path = tmp_path / "note.json"
    path.write_text(json.dumps(NOTE), encoding="utf-8-sig")
    assert import_note(path) == NOTE
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="UTF-8"):
        import_note(path)


def test_metrics_export_requires_analysis(tmp_path):
    with pytest.raises(ValueError):
        export_metrics(None, tmp_path)
    report = copilot.analyze_csv("note_id,title,views,likes,saves,comments\na,x,0,0,0,0\n")
    path = export_metrics(report, tmp_path)
    assert json.loads(open(path, encoding="utf-8").read())["interactions_per_view"] is None
