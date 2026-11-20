"""HTTP/queue integration with the actual Gradio app; no external model calls."""

import json
import socket
import urllib.request
import zipfile
from pathlib import Path

import pytest
from gradio_client import Client, handle_file

import app
from workflows import DEMO_LABEL


@pytest.fixture(scope="module")
def running_app(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ui-http")
    original = app.EXPORT_DIR
    app.EXPORT_DIR = directory / "exports"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    demo = app.build_app().queue(max_size=20)
    try:
        demo.launch(
            server_name="127.0.0.1",
            server_port=port,
            prevent_thread_lock=True,
            quiet=True,
            share=False,
            show_error=False,
        )
        url = f"http://127.0.0.1:{port}"
        yield demo, url, directory
    finally:
        demo.close()
        app.EXPORT_DIR = original


def test_startup_config_and_no_public_share(running_app):
    demo, url, _ = running_app
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
    with urllib.request.urlopen(url + "/config") as response:
        config = json.load(response)
    assert demo.share_url is None
    assert config["analytics_enabled"] is False
    assert any(item.get("props", {}).get("label") == "标题" for item in config["components"])


def test_gradio_full_draft_edit_export_restore_csv_and_clear(running_app):
    _, url, directory = running_app
    client = Client(url, verbose=False)
    result = client.predict(
        "合成素材：运营 CSV 复盘工具，目标读者是运营，语气克制",
        "{}",
        DEMO_LABEL,
        "",
        "",
        "",
        "",
        api_name="/generate",
    )
    assert result[1]
    assert "Demo mode" in result[9]
    assert result[10] is None
    edited_title = "用户手改标题"
    edited_body = "用户手改正文，保留真实事实。\n第二段是已知的 CSV 功能。"
    revised = client.predict(
        "保留这些事实",
        "{}",
        DEMO_LABEL,
        edited_title,
        edited_body,
        "运营",
        "",
        api_name="/generate",
    )
    assert revised[1] == edited_title
    assert revised[2] == edited_body
    assert len(revised[0]) == 4

    bundle, status = client.predict(
        edited_title, edited_body, "运营", "", api_name="/export_bundle"
    )
    assert "未发布" in status
    with zipfile.ZipFile(bundle) as archive:
        assert len(archive.namelist()) == 4
        note_name = next(name for name in archive.namelist() if name.endswith(".json"))
        restored = directory / "restored.json"
        restored.write_bytes(archive.read(note_name))
        assert json.loads(restored.read_text(encoding="utf-8"))["body"] == edited_body
    recovered = client.predict(handle_file(restored), api_name="/restore_note")
    assert recovered[1] == edited_title
    assert recovered[0] == []

    csv = directory / "metrics.csv"
    csv.write_text(
        "note_id,title,views,likes,saves,comments\na,甲,100,10,5,5\nb,乙,0,0,0,0\n",
        encoding="utf-8",
    )
    summary, report, table, artifact = client.predict(handle_file(csv), api_name="/analyze_csv")
    assert report["note_count"] == 2
    assert report["interactions_per_view"] == pytest.approx(0.2)
    assert "复盘摘要" in summary
    assert table["data"][0][0] == "a"
    assert artifact is None
    exported = client.predict(api_name="/export_metrics")
    assert json.loads(Path(exported).read_text(encoding="utf-8"))["totals"]["views"] == 100

    cleared = client.predict(api_name="/new_note")
    assert cleared[0] == []
    assert cleared[1:5] == ("", "", "", "")
    assert cleared[10] is None


def test_http_sessions_do_not_share_history(running_app):
    _, url, _ = running_app
    first = Client(url, verbose=False)
    second = Client(url, verbose=False)
    args = ("新稿素材", "{}", DEMO_LABEL, "", "", "", "")
    first.predict(*args, api_name="/generate")
    first_result = first.predict(*args, api_name="/generate")
    second_result = second.predict(*args, api_name="/generate")
    assert len(first_result[0]) == 4
    assert len(second_result[0]) == 2


def test_callback_clear_output_alignment():
    values = app.clear_session()
    assert len(values) == 14
    assert values[0:6] == ([], [], "", "", "", "")
    assert values[11] is None
    assert values[12] == ""
    assert values[13] is None


@pytest.mark.parametrize("title,body", [("", "正文"), ("标题", ""), (" ", "正文")])
def test_export_validation_errors_are_user_visible_without_outputs(title, body):
    import gradio as gr

    with pytest.raises(gr.Error):
        app.export_bundle(title, body, "", "")


def test_bad_request_does_not_mutate_history():
    import gradio as gr

    from workflows import REAL_LABEL

    history = [{"role": "user", "content": "已有素材"}, {"role": "assistant", "content": "旧稿"}]
    before = json.dumps(history)
    with pytest.raises(gr.Error):
        app.generate("新指令", history, "not json", REAL_LABEL, "标题", "正文", "", "")
    assert json.dumps(history) == before


def test_editor_input_invalidates_old_bundle():
    values = app.sync_preview("修改标题", "修改正文", "运营", "")
    assert values[-1] is None
    assert "修改标题" in values[0]
    assert "修改正文" in values[3]


def test_generation_controls_lock_and_unlock():
    locked = app.set_writing_interactive(False)
    unlocked = app.set_writing_interactive(True)
    assert len(locked) == len(unlocked) == 10
    assert all(value["interactive"] is False for value in locked)
    assert all(value["interactive"] is True for value in unlocked)


def test_no_metrics_available_in_a_new_session(running_app):
    from gradio_client.exceptions import AppError

    _, url, _ = running_app
    client = Client(url, verbose=False)
    with pytest.raises(AppError, match="先分析"):
        client.predict(api_name="/export_metrics")


def test_gradio_real_mode_protocol_with_loopback_stub(running_app):
    """Real-mode protocol, not a real LLM or quality acceptance."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from workflows import REAL_LABEL

    captured = []

    class StubModel(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append(payload)
            note = {
                "title": "协议测试稿",
                "body": "合成协议正文",
                "tags": ["测试"],
                "missing_info": [],
            }
            for turn in payload["messages"]:
                if turn["content"].startswith("以下是用户当前手动编辑的稿件"):
                    current = json.loads(turn["content"].split("\n", 1)[1])
                    note = {**current, "title": current["title"] + "（已改）"}
            result = {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(note, ensure_ascii=False)},
                    }
                ],
                "model": "synthetic-stub",
                "usage": {"total_tokens": 42},
            }
            encoded = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), StubModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, url, _ = running_app
        client = Client(url, verbose=False)
        spec = json.dumps(
            {
                "name": "loopback-stub",
                "model": "stub",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "timeout": 5,
            }
        )
        generated = client.predict(
            "合成素材", spec, REAL_LABEL, "", "", "", "", api_name="/generate"
        )
        assert generated[1] == "协议测试稿"
        assert "synthetic-stub" in generated[9]
        assert "total_tokens=42" in generated[9]
        revised = client.predict(
            "改标题，保留正文",
            spec,
            REAL_LABEL,
            "手工标题",
            "手工事实",
            "测试",
            "",
            api_name="/generate",
        )
        assert revised[1] == "手工标题（已改）"
        assert revised[2] == "手工事实"
        assert captured[-1]["messages"][-1]["content"] == "改标题，保留正文"
        assert len(revised[0]) == 4
        assert captured[-1]["stream"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rejected_generation_lock_does_not_chain_generation():
    import gradio as gr

    with pytest.raises(gr.Error, match="正在生成"):
        app.lock_writing(True)
    demo = app.build_app()
    dependencies = demo.config["dependencies"]
    generation = next(d for d in dependencies if d["api_name"] == "generate")
    # Gradio .then runs even when its predecessor raises. This must be
    # success-only, otherwise a rapid rejected click still calls the model.
    assert generation["trigger_only_on_success"] is True
    assert generation["trigger_after"] is not None


@pytest.mark.parametrize(
    "action,args",
    [
        (app.export_bundle_guarded, ("标题", "手动正文", "", "")),
        (app.restore_note_guarded, (None,)),
        (app.clear_session_guarded, ()),
    ],
)
def test_writing_actions_reject_while_generation_is_locked(action, args):
    import gradio as gr

    with pytest.raises(gr.Error, match="锁定"):
        action(True, *args)
    values = app.unlock_writing()
    assert values[0] is False
    assert all(v["interactive"] for v in values[1:])
