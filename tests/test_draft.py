from copilot import draft, format_tags, generate_demo_note, render_note_markdown


def test_demo_draft_returns_editable_note():
    note, history, meta = draft(
        "给运营同学写一篇 AI 复盘工具体验，语气真诚一点。",
        [],
        {"name": "Demo", "mode": "demo"},
    )
    assert note["title"]
    assert note["body"]
    assert history[-1]["role"] == "assistant"
    assert meta["provider"] == "demo"


def test_demo_note_infers_tags_and_missing_info():
    note = generate_demo_note("想写一篇职场效率工具推荐，目标读者是运营。")
    assert any(tag in note["tags"] for tag in ["职场成长", "效率工具", "运营干货"])
    assert note["missing_info"]


def test_render_note_markdown_formats_sections():
    markdown = render_note_markdown(
        "标题", "第一段\n第二段", format_tags(["AI工具", "运营干货"]), "补充真实案例"
    )
    assert markdown.startswith("# 标题")
    assert "#AI工具" in markdown
    assert "补充真实案例" in markdown
