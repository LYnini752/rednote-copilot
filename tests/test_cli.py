"""Smoke the documented `python app.py` entry point, then terminate it."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_documented_app_entrypoint_starts_loopback_only():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(
        os.environ,
        PORT=str(port),
        GRADIO_ANALYTICS_ENABLED="False",
        NO_PROXY="localhost,127.0.0.1",
        no_proxy="localhost,127.0.0.1",
    )
    process = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        deadline = time.monotonic() + 30
        config = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("app.py exited before startup")
            try:
                with opener.open(f"http://127.0.0.1:{port}/config", timeout=0.5) as response:
                    config = json.load(response)
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.05)  # readiness polling, not billed working time
        assert config is not None, "app.py did not become ready within 30s"
        assert config["analytics_enabled"] is False
        assert config["title"] == "Rednote Copilot · alpha"
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("value", ["0", "65536", "not-an-integer"])
def test_bad_port_is_rejected_before_app_starts(value, monkeypatch):
    import app

    monkeypatch.setenv("PORT", value)
    with pytest.raises(ValueError, match="PORT 必须"):
        app.main()


def test_main_declares_local_only_options(monkeypatch):
    import app

    captured = {}

    class FakeApp:
        def queue(self, **kwargs):
            captured["queue"] = kwargs
            return self

        def launch(self, **kwargs):
            captured["launch"] = kwargs

    monkeypatch.setattr(app, "build_app", FakeApp)
    monkeypatch.delenv("PORT", raising=False)
    app.main()
    assert captured["launch"]["server_name"] == "127.0.0.1"
    assert captured["launch"]["server_port"] == 7863
    assert captured["launch"]["share"] is False
    assert captured["launch"]["show_error"] is False
