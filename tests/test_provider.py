import io
import json
import socket
import urllib.error
from unittest.mock import MagicMock

import pytest

import provider
from provider import ProviderError, chat, parse_json, validate_model

SPEC = {"name": "test", "model": "demo", "base_url": "https://example.com/v1"}
MESSAGES = [{"role": "user", "content": "你好"}]
SECRET = "synthetic-secret-for-tests"


def response_payload(**overrides):
    return {
        "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "model": "served-model",
        **overrides,
    }


@pytest.fixture
def transport(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(response_payload()).encode()
    opener = MagicMock()
    opener.open.return_value = response
    build = MagicMock(return_value=opener)
    monkeypatch.setattr(provider.urllib.request, "build_opener", build)
    return build, opener, response


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "https://example.com:443/v1/",
        "https://example.com./v1",
        "http://localhost:8080/v1",
        "http://127.0.0.1:1/v1",
        "http://[::1]:65535/v1",
        "https://[2001:db8::1]/v1",
        "https://example.com/a%20b",
    ],
)
def test_valid_urls(url):
    assert validate_model({**SPEC, "base_url": url}) is None


@pytest.mark.parametrize(
    "url",
    [
        "",
        " https://example.com",
        "https://example.com ",
        "https://exa mple.com",
        "https://example.com/white space",
        "https://example.com/\npath",
        "https://example.com/\tpath",
        "https://example.com/\x00",
        "https://example.com/\x7f",
        "https://example.com/\\evil",
        "https://user:password@example.com",
        "https://@example.com",
        "https://example.com?",
        "https://example.com?key=secret",
        "https://example.com#",
        "https://example.com#secret",
        "http://example.com",
        "ftp://localhost",
        "example.com",
        "https:///v1",
        "https://example.com:abc",
        "https://example.com:65536",
        "https://example.com:0",
        "https://example.com:-1",
        "https://example.com:",
        "https://example.com:+80",
        "https://[::1",
        "https://[::1]extra",
        "https://[::1]:80:90",
        "https://bad_host.com",
        "https://-bad.com",
        "https://bad-.com",
        "https://bad..com",
        "https://999.999.999.999",
        "https://%65xample.com",
        "https://example.com/%zz",
        "https://example.com/%",
        "https://例子.com",
        "https://example.com/中文",
        "http://127.0.0.2",
        "http://localhost.evil",
        "https://[fe80::1%25eth0]",
    ],
)
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        validate_model({**SPEC, "base_url": url})


@pytest.mark.parametrize(
    "spec",
    [
        None,
        [],
        "secret",
        {},
        {**SPEC, "name": None},
        {**SPEC, "model": " demo"},
        {**SPEC, "name": "test\n"},
        {**SPEC, "model": ""},
        {**SPEC, "api_key_env": None},
        {**SPEC, "api_key_env": " ENV"},
        {**SPEC, "api_key_env": "ENV-KEY"},
        {**SPEC, "api_key_env": "1KEY"},
        {**SPEC, "api_key_env": "KEY\n"},
        {**SPEC, "headers": []},
    ],
)
def test_invalid_config(spec):
    with pytest.raises(ValueError):
        validate_model(spec)


@pytest.mark.parametrize(
    "field",
    ["api_key", "API_KEY", "api-key", "apikey", "Cookie", "Authorization", "proxy_authorization"],
)
def test_literal_credentials_rejected(field):
    with pytest.raises(ValueError) as error:
        validate_model({**SPEC, field: SECRET})
    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": SECRET},
        {"aUtHoRiZaTiOn": SECRET},
        {"Cookie": SECRET},
        {"Proxy-Authorization": SECRET},
        {"X-API-Key": SECRET},
        {"api-key": SECRET},
        {"apikey": SECRET},
        {"Set-Cookie": SECRET},
        {"Cookie2": SECRET},
        {"Host": "evil"},
        {"Content-Length": "1"},
        {"Transfer-Encoding": "chunked"},
        {"Content-Type": "text/plain"},
        {"Connection": "keep-alive"},
        {"Accept-Encoding": "gzip"},
        {"X-Test": 1},
        {1: "x"},
        {" X-Test": "x"},
        {"X Test": "x"},
        {"X-Test\r\n": "x"},
        {"X-Test": "a\r\nCookie: secret"},
        {"X-Test": " x"},
        {"X-Test": "x "},
        {"X-Test": "\x00"},
        {"X-Test": "\x7f"},
        {"X-Test": "中文"},
        {"X-Test": "a", "x-test": "b"},
    ],
)
def test_bad_headers(headers):
    with pytest.raises(ValueError) as error:
        validate_model({**SPEC, "headers": headers})
    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    "field,values",
    [
        (
            "temperature",
            [True, False, float("nan"), float("inf"), -0.01, 2.01, "0.3", None, 10**500],
        ),
        ("timeout", [True, False, float("nan"), float("inf"), 0, -1, 300.01, "120", None, 10**500]),
        ("max_tokens", [True, False, float("nan"), float("inf"), 0, -1, 131073, 1.5, "1", None]),
    ],
)
def test_numeric_config_and_arguments(field, values, transport):
    for value in values:
        with pytest.raises(ValueError):
            validate_model({**SPEC, field: value})
        with pytest.raises(ValueError):
            chat(SPEC, MESSAGES, **{field: value})
    transport[1].open.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", 0),
        ("temperature", 2),
        ("timeout", 0.001),
        ("timeout", 300),
        ("max_tokens", 1),
        ("max_tokens", 131072),
    ],
)
def test_numeric_boundaries(field, value):
    validate_model({**SPEC, field: value})


def test_request_and_return_contract(transport, monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", SECRET)
    build, opener, response = transport
    result = chat(
        {
            **SPEC,
            "base_url": SPEC["base_url"] + "/",
            "api_key_env": "TEST_PROVIDER_KEY",
            "headers": {"X-Project": "alpha"},
            "timeout": 0.25,
            "temperature": 0,
            "max_tokens": 1,
        },
        MESSAGES,
        timeout=12,
        temperature=1,
        max_tokens=20,
    )
    build.assert_called_once_with(provider.NoRedirect)
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://example.com/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer " + SECRET
    assert request.get_header("X-project") == "alpha"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "model": "demo",
        "messages": MESSAGES,
        "temperature": 0,
        "max_tokens": 1,
        "stream": False,
    }
    assert opener.open.call_args.kwargs == {"timeout": 0.25}
    response.read.assert_called_once_with(4_000_001)
    assert result["text"] == "answer" and result["model"] == "served-model"
    assert result["usage"]["total_tokens"] == 5
    assert isinstance(result["seconds"], float) and result["seconds"] >= 0
    response.__exit__.assert_called_once()


@pytest.mark.parametrize("key", [None, "", " secret", "secret ", "bad\nkey", "中文"])
def test_missing_or_invalid_env_key(key, monkeypatch, transport):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("TEST_PROVIDER_KEY", key)
    with pytest.raises(ProviderError):
        chat({**SPEC, "api_key_env": "TEST_PROVIDER_KEY"}, MESSAGES)
    transport[1].open.assert_not_called()


def test_no_key_and_defaults(transport):
    chat(SPEC, MESSAGES)
    request = transport[1].open.call_args.args[0]
    assert request.get_header("Authorization") is None
    payload = json.loads(request.data)
    assert (payload["temperature"], payload["max_tokens"]) == (0.3, 1500)
    assert transport[1].open.call_args.kwargs["timeout"] == 120


@pytest.mark.parametrize(
    "messages",
    [
        None,
        {},
        [],
        [None],
        [{}],
        [{"role": "", "content": "x"}],
        [{"role": "user", "content": None}],
        [{"role": 1, "content": "x"}],
    ],
)
def test_invalid_messages(messages, transport):
    with pytest.raises(ValueError):
        chat(SPEC, messages)
    transport[1].open.assert_not_called()


def test_nonfinite_request_json(transport):
    with pytest.raises(ValueError, match="Invalid request JSON"):
        chat(SPEC, [{"role": "user", "content": "x", "extra": float("nan")}])
    transport[1].open.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON synthetic-secret-for-tests",
        b"\xff",
        b"",
        b"[]",
        b"null",
        b"1",
        b'{"choices":NaN}',
        b'{"choices":[]}',
        b'{"choices":{}}',
        b'{"choices":[null]}',
        b'{"choices":[[]]}',
        b'{"choices":[{}]}',
        b'{"choices":[{"message":null}]}',
        b'{"choices":[{"message":{"content":null}}]}',
        b'{"choices":[{"message":{"content":[]}}]}',
        b'{"choices":[{"message":{"content":"  "}}]}',
        json.dumps(response_payload(usage=[])).encode(),
        json.dumps(response_payload(usage={"total_tokens": True})).encode(),
        json.dumps(response_payload(usage={"total_tokens": -1})).encode(),
        json.dumps(response_payload(usage={"total_tokens": 1.5})).encode(),
        json.dumps(response_payload(model=None)).encode(),
        json.dumps(response_payload(model="")).encode(),
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_invalid_responses_are_sanitized(body, transport):
    transport[2].read.return_value = body
    with pytest.raises(ProviderError) as error:
        chat(SPEC, MESSAGES)
    assert SECRET not in str(error.value)
    assert error.value.__context__ is None or error.value.__suppress_context__


def test_response_size_limit(transport):
    transport[2].read.return_value = b" " * 4_000_001
    with pytest.raises(ProviderError, match="exceeded"):
        chat(SPEC, MESSAGES)
    # Exactly the byte limit is permitted.
    body = json.dumps(response_payload()).encode()
    transport[2].read.return_value = body + b" " * (4_000_000 - len(body))
    assert chat(SPEC, MESSAGES)["text"] == "answer"


def test_usage_filter_and_missing_metadata(transport):
    transport[2].read.return_value = json.dumps(
        {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"total_tokens": 1, "error": SECRET},
        }
    ).encode()
    result = chat(SPEC, MESSAGES)
    assert result["model"] == "demo" and result["usage"] == {"total_tokens": 1}
    transport[2].read.return_value = json.dumps(response_payload(usage=None)).encode()
    assert chat(SPEC, MESSAGES)["usage"] == {}


def test_truncation(transport):
    transport[2].read.return_value = json.dumps({"choices": [{"finish_reason": "length"}]}).encode()
    with pytest.raises(ProviderError, match="truncated"):
        chat(SPEC, MESSAGES)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308, 400, 401, 403, 429, 500])
def test_http_errors_never_read_secret_body(code, transport):
    body = MagicMock(wraps=io.BytesIO(SECRET.encode()))
    error = urllib.error.HTTPError(SPEC["base_url"], code, SECRET, {}, body)
    transport[1].open.side_effect = error
    with pytest.raises(ProviderError, match=f"HTTP {code}") as caught:
        chat(SPEC, MESSAGES)
    assert SECRET not in str(caught.value)
    body.read.assert_not_called()
    body.close.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [urllib.error.URLError(SECRET), TimeoutError(SECRET), socket.timeout(SECRET), OSError(SECRET)],
)
def test_transport_errors_sanitized(error, transport):
    transport[1].open.side_effect = error
    with pytest.raises(ProviderError) as caught:
        chat(SPEC, MESSAGES)
    assert SECRET not in str(caught.value)


def test_redirect_handler():
    with pytest.raises(ProviderError, match="redirected"):
        provider.NoRedirect().redirect_request(None, None, 302, SECRET, {}, "https://evil.test")


@pytest.mark.parametrize(
    "text",
    [
        '{"title":"x"}',
        '  {"title":"x"}  ',
        '```json\n{"title":"x"}\n```',
        '```\n{"title":"x"}\n```',
        '```JSON\r\n{"title":"x"}\r\n```',
    ],
)
def test_parse_json_valid(text):
    assert parse_json(text) == {"title": "x"}


@pytest.mark.parametrize(
    "text",
    [
        None,
        1,
        [],
        "",
        "```",
        "``````",
        "```json```",
        "```json\n{}",
        "```python\n{}\n```",
        "```json\n{}\n```suffix",
        "prefix```json\n{}\n```",
        "```json {} ```",
        "```json\n{}\n```\n```",
        "```json\nsynthetic-secret-for-tests\n```",
        "[]",
        "null",
        "true",
        "1",
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        '{"x":}',
        "[" * 2000 + "]" * 2000,
        " " * 4_000_001,
        "\ud800",
    ],
)
def test_parse_json_malformed_is_safe(text):
    with pytest.raises(ValueError) as error:
        parse_json(text)
    assert SECRET not in str(error.value)
    assert error.value.__context__ is None or error.value.__suppress_context__


@pytest.mark.parametrize(
    "url", ["https://example.com/<tag>", 'https://example.com/"x"', "https://example.com/[x]"]
)
def test_illegal_url_path_characters(url):
    with pytest.raises(ValueError):
        validate_model({**SPEC, "base_url": url})


@pytest.mark.parametrize("name", ["X_API_KEY", "API_KEY"])
def test_credential_header_separator_aliases(name):
    with pytest.raises(ValueError):
        validate_model({**SPEC, "headers": {name: SECRET}})


@pytest.mark.parametrize("value", [[], {}, 1, True, ""])
def test_bad_finish_reason(value, transport):
    payload = response_payload()
    payload["choices"][0]["finish_reason"] = value
    transport[2].read.return_value = json.dumps(payload).encode()
    with pytest.raises(ProviderError, match="Invalid Chat Completions response"):
        chat(SPEC, MESSAGES)


@pytest.mark.parametrize("text", ['{"x":1e999}', '{"x":-1e999}'])
def test_json_float_overflow(text, transport):
    with pytest.raises(ValueError):
        parse_json(text)
    transport[2].read.return_value = text.encode()
    with pytest.raises(ProviderError):
        chat(SPEC, MESSAGES)


@pytest.mark.parametrize("status", [101, 300, 304])
def test_unexpected_response_status(status, transport):
    transport[2].status = status
    with pytest.raises(ProviderError, match="unexpected HTTP status"):
        chat(SPEC, MESSAGES)
    transport[2].read.assert_not_called()
    transport[2].__exit__.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        provider.http.client.IncompleteRead(SECRET.encode()),
        provider.http.client.BadStatusLine(SECRET),
        OSError(SECRET),
    ],
)
def test_read_failures_closed_and_sanitized(failure, transport):
    transport[2].read.side_effect = failure
    with pytest.raises(ProviderError) as error:
        chat(SPEC, MESSAGES)
    assert SECRET not in str(error.value)
    transport[2].__exit__.assert_called_once()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_response_is_closed(status):
    response = MagicMock()
    handler = provider.NoRedirect()
    with pytest.raises(ProviderError, match="redirected"):
        getattr(handler, f"http_error_{status}")(None, response, status, SECRET, {})
    response.close.assert_called_once()


def test_request_serialization_failure_is_sanitized(transport):
    with pytest.raises(ValueError, match="Invalid request JSON") as error:
        chat(SPEC, [{"role": "user", "content": "x", "extra": object()}])
    assert SECRET not in str(error.value)
    transport[1].open.assert_not_called()


def test_json_float_accepted():
    assert parse_json('{"x":0.25}') == {"x": 0.25}
