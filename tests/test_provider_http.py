"""Real local HTTP transport tests; no remote API or real model is contacted."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from provider import ProviderError, chat

MESSAGES = [{"role": "user", "content": "你好，loopback"}]
SYNTHETIC_KEY = "loopback-synthetic-key"


@pytest.fixture
def loopback(monkeypatch):
    # Never route a loopback test through machine-configured proxies.
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    state = {
        "requests": [],
        "status": 200,
        "headers": {},
        "delay": 0,
        "body": json.dumps(
            {
                "choices": [{"message": {"content": "本地测试响应"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 7},
                "model": "loopback-stub",
            }
        ).encode(),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state["requests"].append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                    "method": self.command,
                }
            )
            time.sleep(state["delay"])
            try:
                self.send_response(state["status"])
                self.send_header("Content-Type", "application/json")
                if state.get("chunked"):
                    self.send_header("Transfer-Encoding", "chunked")
                else:
                    self.send_header("Content-Length", str(len(state["body"])))

                for name, value in state["headers"].items():
                    self.send_header(name, value)
                self.end_headers()
                if state.get("chunked"):
                    body = state["body"]
                    prefix = (
                        b"not-a-chunk-size" if state.get("bad_chunk") else f"{len(body):x}".encode()
                    )
                    self.wfile.write(prefix + b"\r\n" + body + b"\r\n0\r\n\r\n")
                else:
                    self.wfile.write(state["body"])

            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when client times out or enforces a size cap.

        do_GET = do_POST

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    state["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def spec(state, **extra):
    return {"name": "loopback", "model": "test-model", "base_url": state["base_url"], **extra}


def test_real_post_contract(loopback, monkeypatch):
    monkeypatch.setenv("LOOPBACK_TEST_KEY", SYNTHETIC_KEY)
    result = chat(
        spec(loopback, api_key_env="LOOPBACK_TEST_KEY", headers={"X-Project": "alpha"}),
        MESSAGES,
        temperature=0.5,
        max_tokens=32,
        timeout=2,
    )
    assert result["text"] == "本地测试响应"
    assert result["model"] == "loopback-stub"
    assert result["usage"] == {"total_tokens": 7}
    assert result["seconds"] >= 0
    assert len(loopback["requests"]) == 1
    request = loopback["requests"][0]
    assert request["method"] == "POST"
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer " + SYNTHETIC_KEY
    assert request["headers"]["X-Project"] == "alpha"
    assert request["headers"]["Content-Type"] == "application/json"
    assert json.loads(request["body"]) == {
        "model": "test-model",
        "messages": MESSAGES,
        "temperature": 0.5,
        "max_tokens": 32,
        "stream": False,
    }
    assert SYNTHETIC_KEY.encode() not in request["body"]


def test_real_no_auth(loopback):
    assert chat(spec(loopback), MESSAGES)["text"]
    assert "Authorization" not in loopback["requests"][0]["headers"]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("destination", ["relative", "absolute"])
def test_real_redirect_never_followed(loopback, monkeypatch, status, destination):
    monkeypatch.setenv("LOOPBACK_TEST_KEY", SYNTHETIC_KEY)
    loopback["status"] = status
    loopback["headers"]["Location"] = (
        "/credential-sink"
        if destination == "relative"
        else loopback["base_url"].replace("/v1", "/credential-sink")
    )
    loopback["body"] = SYNTHETIC_KEY.encode()
    with pytest.raises(ProviderError) as error:
        chat(spec(loopback, api_key_env="LOOPBACK_TEST_KEY"), MESSAGES)
    assert SYNTHETIC_KEY not in str(error.value)
    assert len(loopback["requests"]) == 1
    assert loopback["requests"][0]["path"] == "/v1/chat/completions"


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_real_error_payload_never_disclosed(loopback, status):
    loopback["status"] = status
    loopback["body"] = json.dumps({"error": {"message": SYNTHETIC_KEY}}).encode()
    with pytest.raises(ProviderError, match=f"HTTP {status}") as error:
        chat(spec(loopback), MESSAGES)
    assert SYNTHETIC_KEY not in str(error.value)
    assert len(loopback["requests"]) == 1  # No implicit retries.


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"\xff",
        b"null",
        b"[]",
        b'{"choices":[]}',
        b'{"choices":[{"message":{"content":42}}]}',
        json.dumps({"error": SYNTHETIC_KEY}).encode(),
    ],
)
def test_real_bad_response(loopback, body):
    loopback["body"] = body
    with pytest.raises(ProviderError) as error:
        chat(spec(loopback), MESSAGES)
    assert SYNTHETIC_KEY not in str(error.value)


def test_real_oversized_response(loopback):
    loopback["body"] = b" " * 4_000_001
    with pytest.raises(ProviderError, match="exceeded"):
        chat(spec(loopback), MESSAGES)


def test_real_timeout(loopback):
    loopback["delay"] = 0.2
    with pytest.raises(ProviderError, match="timed out"):
        chat(spec(loopback), MESSAGES, timeout=0.02)
    assert len(loopback["requests"]) == 1


def test_real_truncated_answer(loopback):
    loopback["body"] = b'{"choices":[{"finish_reason":"length","message":{"content":"partial"}}]}'
    with pytest.raises(ProviderError, match="truncated"):
        chat(spec(loopback), MESSAGES)


def test_real_chunked_response(loopback):
    loopback["chunked"] = True
    assert chat(spec(loopback), MESSAGES)["text"] == "本地测试响应"


def test_real_malformed_chunked_response(loopback):
    loopback["chunked"] = True
    loopback["bad_chunk"] = True
    loopback["body"] = SYNTHETIC_KEY.encode()
    with pytest.raises(ProviderError) as error:
        chat(spec(loopback), MESSAGES)
    assert SYNTHETIC_KEY not in str(error.value)


def test_real_exact_size_boundary(loopback):
    loopback["body"] += b" " * (4_000_000 - len(loopback["body"]))
    assert chat(spec(loopback), MESSAGES)["text"] == "本地测试响应"


def test_real_empty_success_body(loopback):
    loopback["status"] = 204
    loopback["body"] = b""
    with pytest.raises(ProviderError, match="Invalid Chat Completions response"):
        chat(spec(loopback), MESSAGES)


def test_bad_config_makes_no_real_request(loopback):
    with pytest.raises(ValueError):
        chat(spec(loopback, headers={"Cookie": SYNTHETIC_KEY}), MESSAGES)
    assert loopback["requests"] == []
