import json
import re
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from copilot import build_note_bundle


def bundle_contents(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(not entry.is_dir() for entry in archive.infolist())
        return {name: archive.read(name) for name in names}


def test_build_note_bundle_exports_multiple_formats(tmp_path):
    bundle = build_note_bundle(
        title="AI 复盘模板",
        body="第一段\n第二段",
        tags="#AI工具 #运营干货",
        missing_info="补充真实数据",
        output_dir=tmp_path,
    )
    assert isinstance(bundle, str)
    assert Path(bundle).parent == tmp_path
    files = bundle_contents(bundle)
    assert set(files) == {
        "AI-复盘模板.md",
        "AI-复盘模板.txt",
        "AI-复盘模板.json",
        "publish-checklist.md",
    }
    payload = json.loads(files["AI-复盘模板.json"])
    assert payload == {
        "title": "AI 复盘模板",
        "body": "第一段\n第二段",
        "tags": ["AI工具", "运营干货"],
        "missing_info": ["补充真实数据"],
    }
    assert (
        files["AI-复盘模板.txt"].decode("utf-8")
        == "AI 复盘模板\n\n第一段\n第二段\n\n#AI工具 #运营干货\n"
    )
    markdown = files["AI-复盘模板.md"].decode("utf-8")
    assert markdown.startswith("# AI 复盘模板\n")
    assert "第一段\n第二段" in markdown and "补充真实数据" in markdown
    checklist = files["publish-checklist.md"].decode("utf-8")
    assert "不会自动登录" in checklist and "手动" in checklist
    assert all(data.endswith(b"\n") for data in files.values())


@pytest.mark.parametrize(
    "title",
    [
        "../../escape",
        "/absolute/path",
        r"..\..\escape",
        "C:\\temp\\escape",
        "../.hidden",
        "a\x00b",
        "a\n../../b",
        "../🧪🚀",
        "🧪🚀",
        "x" * 200,
        "中文/安全:标题?*",
        "...",
        "CON",
        'a|b<>"c',
    ],
)
def test_untrusted_title_cannot_escape_output_directory(tmp_path, title):
    output_dir = tmp_path / "exports"
    bundle = Path(build_note_bundle(title, "有效正文", [], "", output_dir))
    assert bundle.resolve().parent == output_dir.resolve()
    assert re.fullmatch(
        r"[0-9A-Za-z\u4e00-\u9fff_-]{1,40}-(?:[0-9a-f]{8}|[0-9a-f]{32})\.zip", bundle.name
    )
    files = bundle_contents(bundle)
    assert len(files) == 4
    for name in files:
        path = PurePosixPath(name)
        assert not path.is_absolute() and len(path.parts) == 1 and ".." not in path.parts
        assert "\\" not in name and "\x00" not in name
        assert re.fullmatch(r"[0-9A-Za-z\u4e00-\u9fff_-]{1,40}\.(md|txt|json)", name)
    payload = json.loads(next(data for name, data in files.items() if name.endswith(".json")))
    assert payload["title"] == title.strip()
    assert not (tmp_path / "escape").exists()


def test_bundle_content_is_deterministic_and_repeated_exports_do_not_overwrite(tmp_path):
    args = ("重复导出", "正文\n第二段", ["AI", "AI", "运营"], "问题一\n\n问题二", tmp_path)
    first = build_note_bundle(*args)
    before = bundle_contents(first)
    second = build_note_bundle(*args)
    assert first != second
    assert bundle_contents(first) == before == bundle_contents(second)
    assert json.loads(before["重复导出.json"])["tags"] == ["AI", "运营"]
    # Content equality is required; UUID paths and ZIP timestamps are not compared.


@pytest.mark.parametrize("field", ["title", "body"])
@pytest.mark.parametrize("invalid", ["", " \n\t", None, 42, [], {}])
def test_export_rejects_empty_or_non_string_required_data(tmp_path, field, invalid):
    args = dict(title="标题", body="正文", tags=[], missing_info="", output_dir=tmp_path)
    args[field] = invalid
    with pytest.raises(ValueError):
        build_note_bundle(**args)
    assert not list(tmp_path.iterdir())


def test_export_accepts_empty_optional_data_and_nested_output_dir(tmp_path):
    bundle = build_note_bundle(" 标题 ", " 正文 ", "", "", str(tmp_path / "nested" / "exports"))
    files = bundle_contents(bundle)
    payload = json.loads(files["标题.json"])
    assert payload == {"title": "标题", "body": "正文", "tags": [], "missing_info": []}
    assert "正文为空" not in files["publish-checklist.md"].decode("utf-8")


def test_checklist_filename_collision_does_not_drop_note_markdown(tmp_path):
    files = bundle_contents(build_note_bundle("publish-checklist", "独特正文", [], "", tmp_path))
    assert len(files) == 4, (
        "导出标题与固定 checklist 文件名冲突，笔记 Markdown 被覆盖；由 main 修复"
    )
    note_markdown = [
        data
        for name, data in files.items()
        if name.endswith(".md") and name != "publish-checklist.md"
    ]
    assert len(note_markdown) == 1
    assert "独特正文" in note_markdown[0].decode("utf-8")


@pytest.mark.parametrize("title", ["CON", "nul", "AUX", "PrN", "COM1", "LPT9"])
def test_export_members_are_not_windows_reserved_names(tmp_path, title):
    with zipfile.ZipFile(build_note_bundle(title, "正文", "话题", "", tmp_path)) as archive:
        names = archive.namelist()
    assert "note-" + title + ".txt" in names


@pytest.mark.parametrize("missing", [None, [], "", ["补充经历"], "补充经历\n补充数据"])
def test_missing_info_roundtrips_optional_forms(tmp_path, missing):
    path = build_note_bundle("标题", "正文", "运营", missing, tmp_path)
    with zipfile.ZipFile(path) as archive:
        payload = json.loads(
            next(archive.read(name) for name in archive.namelist() if name.endswith(".json"))
        )
    expected = missing.splitlines() if isinstance(missing, str) else (missing or [])
    assert payload["missing_info"] == expected
