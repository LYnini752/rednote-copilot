"""Dependency-free OpenAI-compatible Chat Completions client.

Secrets are read only from api_key_env. Configuration is validated without
normalizing it silently. Limits: temperature 0..2, max_tokens 1..131072,
timeout (0, 300] seconds, response body at most 4,000,000 bytes.
"""

import http.client
import ipaddress
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE_BYTES = 4_000_000
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_BLOCKED_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "cookie2",
    "set-cookie",
    "api-key",
    "x-api-key",
    "apikey",
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "content-type",
    "accept-encoding",
}


class ProviderError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("Endpoint redirected; configure the final URL explicitly.")

    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        raise ProviderError("Endpoint redirected; configure the final URL explicitly.")

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _clean_string(value, field, *, empty=False):
    if (
        not isinstance(value, str)
        or (not empty and not value)
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError(f"Invalid configuration string: {field}")


def _numeric(value, field):
    if field == "max_tokens":
        valid = type(value) is int and 1 <= value <= 131072
    else:
        valid = type(value) in (int, float)
        if valid:
            # Compare before isfinite: huge Python integers must not overflow.
            valid = 0 <= value <= 2 if field == "temperature" else 0 < value <= 300
            valid = valid and math.isfinite(value)
    if not valid:
        raise ValueError(f"Invalid or out-of-range {field}")


def _validate_url(value):
    _clean_string(value, "base_url")
    try:
        if any(c.isspace() for c in value) or any(c in value for c in "\\?#"):
            raise ValueError
        url = urllib.parse.urlsplit(value)
        host = url.hostname
        port = url.port  # Also validates nonnumeric and out-of-range ports.
        if (
            url.username is not None
            or url.password is not None
            or not host
            or url.netloc.endswith(":")
            or port == 0
        ):
            raise ValueError
        if not re.fullmatch(r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]+)?", url.netloc):
            raise ValueError
        if url.scheme not in {"http", "https"}:
            raise ValueError
        if url.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError
        if "%" in host:
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if ":" in host or len(host) > 253:
                raise ValueError from None
            labels = host.rstrip(".").split(".")
            if any(
                not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in labels
            ):
                raise ValueError from None
            if all(label.isdigit() for label in labels):
                raise ValueError from None
        if (
            re.search(r"%(?![0-9A-Fa-f]{2})", url.path)
            or not value.isascii()
            or re.search(r"[^A-Za-z0-9/:%@!$&'()*+,;=._~-]", url.path)
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(
            "Invalid base_url; use HTTPS or HTTP on localhost, without credentials, query or fragment"
        ) from None


def validate_model(spec):
    """Validate configuration in place; return None, never include values in errors."""
    if not isinstance(spec, dict):
        raise ValueError("Model configuration must be an object")
    for field in ("name", "model", "base_url"):
        _clean_string(spec.get(field), field)
    _validate_url(spec["base_url"])
    for field in spec:
        if isinstance(field, str) and field.lower().replace("-", "_") in {
            "api_key",
            "apikey",
            "cookie",
            "authorization",
            "proxy_authorization",
        }:
            raise ValueError("Use api_key_env, never literal credentials in config")
    key_env = spec.get("api_key_env", "")
    _clean_string(key_env, "api_key_env", empty=True)
    if key_env and not _ENV.fullmatch(key_env):
        raise ValueError("api_key_env must be an environment variable name")
    for field in ("temperature", "timeout", "max_tokens"):
        if field in spec:
            _numeric(spec[field], field)
    headers = spec.get("headers")
    if headers is not None:
        if not isinstance(headers, dict):
            raise ValueError("headers must be an object of string pairs")
        seen = set()
        for name, value in headers.items():
            if not isinstance(name, str) or not _TOKEN.fullmatch(name):
                raise ValueError("Invalid custom header name")
            normalized = name.lower()
            if normalized.replace("_", "-") in _BLOCKED_HEADERS or normalized in seen:
                raise ValueError("Credential, transport or duplicate custom header is forbidden")
            seen.add(normalized)
            _clean_string(value, "header value", empty=True)
            if not value.isascii():
                raise ValueError("Custom header values must be ASCII")


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _decode_json(raw):
    return json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float)


def _response_fields(result, default_model):
    if not isinstance(result, dict):
        raise ValueError
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError
    choice = choices[0]
    finish = choice.get("finish_reason")
    if finish is not None and (not isinstance(finish, str) or not finish.strip()):
        raise ValueError
    if finish == "length":
        raise ProviderError("Answer truncated; increase max_tokens or shorten the prompt")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("Model returned an empty or non-text answer")
    model = result.get("model", default_model)
    if not isinstance(model, str) or not model.strip():
        raise ValueError
    usage = result.get("usage")
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        raise ValueError
    # Return only numeric accounting fields, not arbitrary server payloads.
    safe_usage = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if field in usage:
            value = usage[field]
            if type(value) is not int or value < 0:
                raise ValueError
            safe_usage[field] = value
    return content, model, safe_usage


def chat(spec, messages, *, temperature=0.3, max_tokens=1500, timeout=120):
    """POST to base_url + /chat/completions, without retries or redirects."""
    validate_model(spec)
    temperature = spec.get("temperature", temperature)
    max_tokens = spec.get("max_tokens", max_tokens)
    timeout = spec.get("timeout", timeout)
    for field, value in (
        ("temperature", temperature),
        ("max_tokens", max_tokens),
        ("timeout", timeout),
    ):
        _numeric(value, field)
    if (
        not isinstance(messages, list)
        or not messages
        or any(
            not isinstance(m, dict)
            or not isinstance(m.get("role"), str)
            or not m["role"].strip()
            or not isinstance(m.get("content"), str)
            for m in messages
        )
    ):
        raise ValueError("messages must be a nonempty list of role/content text objects")
    key_env = spec.get("api_key_env")
    key = os.environ.get(key_env, "") if key_env else ""
    if key_env and not key:
        raise ProviderError("Missing API key environment variable")
    if key and (
        key != key.strip() or not key.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in key)
    ):
        raise ProviderError("Invalid API key environment value")
    headers = {"Content-Type": "application/json", "User-Agent": "rednote-copilot/alpha"}
    headers.update(spec.get("headers") or {})
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        data = json.dumps(
            {
                "model": spec["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Invalid request JSON") from None
    start = time.monotonic()
    try:
        request = urllib.request.Request(
            spec["base_url"].rstrip("/") + "/chat/completions", data=data, headers=headers
        )
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise ProviderError("Model API returned an unexpected HTTP status")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("Response exceeded 4 MB")
        content, model, usage = _response_fields(_decode_json(raw), spec["model"])
        return {
            "text": content,
            "seconds": round(time.monotonic() - start, 3),
            "usage": usage,
            "model": model,
        }
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ProviderError(
            f"Model API returned HTTP {code}; check credentials and model support"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise ProviderError("Cannot reach model API or request timed out") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        raise ProviderError("Invalid Chat Completions response") from None


def parse_json(text):
    """Accept a JSON object, optionally wrapped in a complete json/plain fence."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError
        text = text.strip()
        if text.startswith("```"):
            match = re.fullmatch(
                r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.DOTALL | re.IGNORECASE
            )
            if not match:
                raise ValueError
            text = match.group(1).strip()
        value = _decode_json(text)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(
            "Expected a valid JSON object, optionally in a complete JSON code fence"
        ) from None
