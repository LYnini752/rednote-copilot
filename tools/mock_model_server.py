"""Local OpenAI-compatible stub for UI acceptance only.

This is NOT a model. It returns a fixed, obviously synthetic note so that the
browser acceptance can exercise slow responses, HTTP failures and malformed
payloads without any credential or network access.

Usage:
    python3 tools/mock_model_server.py --port 7870 --delay 4 --mode ok
    python3 tools/mock_model_server.py --port 7870 --delay 1 --mode http_500

Endpoints:
    POST /v1/chat/completions  -> configurable behaviour
    GET  /stats                -> {"requests": n, "modes": {...}}
    GET  /health               -> {"ok": true}

Binds 127.0.0.1 only. No request bodies, headers or credentials are logged.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ("ok", "http_500", "bad_json", "empty_content", "truncated")

_COUNTER = {"requests": 0, "modes": {}}
_LOCK = threading.Lock()


def _note_text(marker: str, index: int) -> str:
    return json.dumps(
        {
            "title": f"STUB 合成草稿 #{index}",
            "body": (
                "这是本地合成 stub 返回的固定文本，不是真实模型输出，也不是真实笔记。\n"
                f"请求标记：{marker}\n"
                f"序号：{index}"
            ),
            "tags": ["合成验收", "stub"],
            "missing_info": ["本地 stub 数据，请勿当作真实素材"],
        },
        ensure_ascii=False,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "rednote-stub/1"
    protocol_version = "HTTP/1.1"

    # Keep the log quiet; acceptance evidence comes from /stats and the browser.
    def log_message(self, fmt, *args):  # noqa: A002 - signature from stdlib
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if self.path == "/stats":
            with _LOCK:
                self._json(200, json.loads(json.dumps(_COUNTER)))
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 - stdlib naming
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON body"})
            return

        cfg = self.server.cfg  # type: ignore[attr-defined]
        with _LOCK:
            _COUNTER["requests"] += 1
            index = _COUNTER["requests"]
            _COUNTER["modes"][cfg.mode] = _COUNTER["modes"].get(cfg.mode, 0) + 1

        if cfg.delay > 0:
            time.sleep(cfg.delay)

        model = request.get("model") or "stub-model"
        mode = cfg.mode
        if mode == "http_500":
            self._json(500, {"error": {"message": "synthetic failure"}})
            return
        if mode == "bad_json":
            content = "这不是 JSON，stub 用于验证解析失败路径。"
        elif mode == "empty_content":
            content = "   "
        elif mode == "truncated":
            payload = {
                "model": model,
                "choices": [{"message": {"content": _note_text(cfg.marker, index)}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            payload["choices"][0]["finish_reason"] = "length"
            self._json(200, payload)
            return
        else:
            content = _note_text(cfg.marker, index)

        self._json(
            200,
            {
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
            },
        )


def serve(port: int, delay: float, mode: str, marker: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.cfg = argparse.Namespace(delay=delay, mode=mode, marker=marker)  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7870)
    parser.add_argument(
        "--delay", type=float, default=0.0, help="seconds to sleep before responding"
    )
    parser.add_argument("--mode", choices=MODES, default="ok")
    parser.add_argument("--marker", default="acceptance", help="label echoed in the synthetic note")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be 1-65535")
    if not 0 <= args.delay <= 120:
        raise SystemExit("--delay must be 0-120 seconds")

    server = serve(args.port, args.delay, args.mode, args.marker)
    print(
        json.dumps(
            {"listening": f"http://127.0.0.1:{args.port}", "mode": args.mode, "delay": args.delay}
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
