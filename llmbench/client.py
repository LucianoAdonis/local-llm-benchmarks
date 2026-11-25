"""Minimal HTTP client for OpenAI-compatible chat endpoints, with per-event timing.

Only the standard library is used. The streaming reader timestamps every server-sent
event so the caller can separate time to first token (of any kind) from time to first
answer text, and can tell a per-token stream from a buffered one.

Connections go straight to the address given. No proxy setting is consulted, so a local
benchmark is never relayed through a system proxy.
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

# Fields that carry model "thinking" in a streamed delta. llama.cpp, vLLM and DeepSeek-style
# servers use reasoning_content; Ollama and LM Studio use reasoning; a few use thinking.
REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")
MAX_KEPT_TEXT = 60_000
THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
# A line that was already waiting when the reader asked for it arrived together with the
# one before it. Events that arrive together are one burst, however the server framed them.
BURST_GAP_S = 0.0001
SLOW_CONNECT_S = 0.05
_BOM = b"\xef\xbb\xbf"
_SSL_CONTEXT: Optional[ssl.SSLContext] = None


class EndpointError(RuntimeError):
    pass


def split_base_url(url: str) -> Tuple[str, str]:
    """Return (root, chat_path). Accepts a bare host, .../v1, .../v1/models or .../v1/chat/completions.

    Raises EndpointError for an address with no host or an invalid port, so callers never
    see a TypeError or ValueError from the URL machinery.
    """
    url = str(url or "").strip()
    if "://" not in url:
        url = "http://" + url
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise EndpointError("not a usable address: %s" % exc) from None
    if not host or parts.scheme.lower() not in ("http", "https"):
        raise EndpointError("not a usable address (expected something like http://127.0.0.1:1234)")
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
    if path.lower().endswith("/v1"):
        path = path[:-3]
    netloc = ("[%s]" % host if ":" in host else host) + (":%d" % port if port else "")
    root = "%s://%s%s" % (parts.scheme.lower(), netloc, path.rstrip("/"))
    return root, "/v1/chat/completions"


def clean_api_key(value: Optional[str], source: str = "the API key") -> Optional[str]:
    """Strip a key read from the environment and refuse one that cannot be a header value.

    A key read from a file often ends in a newline. http.client rejects such a header with
    an error that quotes the whole value, so it is cleaned here and never echoed.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise EndpointError("%s contains a space, line break or other character that cannot be sent in a header" % source)
    return value


def _ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:  # loading the CA bundle takes milliseconds: do it once, outside any stopwatch
        _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def _connection(url: str, timeout: float) -> Tuple[http.client.HTTPConnection, str]:
    parts = urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout, context=_ssl_context())
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    return conn, target


def _headers(api_key: Optional[str], stream: bool) -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if stream else "application/json", "User-Agent": "llmbench"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    return headers


def get_json(url: str, timeout: float = 5.0, api_key: Optional[str] = None) -> Tuple[int, Any]:
    """GET a URL. Returns (status, parsed JSON or raw text). Status 0 means unreachable."""
    try:
        conn, target = _connection(url, timeout)
        try:
            conn.request("GET", target, headers=_headers(api_key, False))
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
        finally:
            conn.close()
    except (OSError, http.client.HTTPException, ValueError, TypeError):
        return 0, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


def post_json(url: str, payload: Dict[str, Any], timeout: float = 600.0, api_key: Optional[str] = None) -> Tuple[int, Any, float]:
    """POST JSON without streaming. Returns (status, parsed body, seconds from request to full reply)."""
    body = json.dumps(payload).encode("utf-8")
    try:
        conn, target = _connection(url, timeout)
        try:
            conn.connect()  # connection setup is not part of the request time
            started = time.perf_counter()
            conn.request("POST", target, body=body, headers=_headers(api_key, False))
            resp = conn.getresponse()
            text = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            elapsed = time.perf_counter() - started
        finally:
            conn.close()
    except (OSError, http.client.HTTPException) as exc:
        raise EndpointError("request failed: %s" % exc) from exc
    except (ValueError, TypeError):
        raise EndpointError("request could not be sent: the address or a header value is not valid") from None
    try:
        return status, json.loads(text), elapsed
    except ValueError:
        return status, text, elapsed


def _delta_text(choice: Dict[str, Any]) -> Tuple[str, str]:
    """Return (answer_text, reasoning_text) carried by one streamed choice."""
    delta = choice.get("delta") or choice.get("message") or {}
    if not isinstance(delta, dict):
        return "", ""
    content = delta.get("content")
    if isinstance(content, list):  # content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    answer = content if isinstance(content, str) else ""
    reasoning = ""
    for key in REASONING_KEYS:
        value = delta.get(key)
        if isinstance(value, str) and value:
            reasoning += value
    calls = delta.get("tool_calls")
    for call in calls if isinstance(calls, list) else []:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and isinstance(function.get("arguments"), str):
            answer += function["arguments"]
    if not answer and not reasoning and isinstance(choice.get("text"), str):
        answer = choice["text"]  # legacy completions shape
    return answer, reasoning


def _percentile(sorted_values: List[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


class _TextAccounting:
    """Classifies streamed text as answer or reasoning and keeps the counters.

    Handles the shapes seen in the wild: a separate reasoning field; thinking inline in the
    content as <think>...</think>, with the tags anywhere inside an event or split across
    events; a lone </think> when the chat template opened the block inside the prompt; and
    plain answers. While the first characters could still turn out to be an opening tag,
    events are held as "pending" and assigned once the stream shows which it is.
    """

    def __init__(self, out: Dict[str, Any]) -> None:
        self.out = out
        self.state = "unknown"  # unknown -> open -> closed, or unknown -> none (-> closed on a lone close tag)
        self.head = ""
        self.carry = ""  # the last few characters seen, to find a close tag split across events
        self.kept: List[str] = []
        self.kept_chars = 0
        self.pending: List[Tuple[float, str]] = []

    def _add_answer(self, now: float, text: str) -> None:
        out = self.out
        if out["first_answer_s"] is None:
            out["first_answer_s"] = now
        out["answer_events"] += 1
        out["answer_chars"] += len(text)
        if self.kept_chars < MAX_KEPT_TEXT:
            self.kept.append(text)
            self.kept_chars += len(text)

    def _add_reasoning(self, text: str) -> None:
        self.out["reasoning_events"] += 1
        self.out["reasoning_chars"] += len(text)

    def _flush_pending(self, as_reasoning: bool) -> None:
        for when, text in self.pending:
            if as_reasoning:
                self._add_reasoning(text)
            else:
                self._add_answer(when, text)
        self.pending = []

    def _split_at_close(self, text: str) -> Optional[Tuple[str, str]]:
        """If a close tag ends inside this event, return (text up to and including it, text after it)."""
        joined = self.carry + text
        at = joined.find(THINK_CLOSE)
        if at < 0:
            self.carry = joined[-(len(THINK_CLOSE) - 1):]
            return None
        end = max(0, at + len(THINK_CLOSE) - len(self.carry))
        self.carry = ""
        return text[:end], text[end:]

    def _close(self, now: float, thinking: str, rest: str) -> None:
        if thinking:
            self._add_reasoning(thinking)
        if rest:
            self._add_answer(now, rest)  # answer text that shares an event with the close tag
        self.state = "closed"

    def add(self, now: float, answer: str, reasoning: str) -> None:
        if reasoning:
            self._add_reasoning(reasoning)
        if not answer:
            return
        if self.state == "unknown":
            self.head += answer
            head = self.head.lstrip()
            if head.startswith(THINK_OPEN):
                self.state = "open"
                self.out["inline_think"] = True
                self._flush_pending(as_reasoning=True)
                at = self.head.find(THINK_CLOSE)
                if at < 0:
                    self._add_reasoning(answer)
                    self.carry = self.head[-(len(THINK_CLOSE) - 1):]
                else:  # the whole block, and maybe the start of the answer, came in this event
                    rest = self.head[at + len(THINK_CLOSE):]
                    self._close(now, answer[: len(answer) - len(rest)], rest)
                return
            if not head or THINK_OPEN.startswith(head):
                self.pending.append((now, answer))  # whitespace so far, or a partial "<thi"
                return
            self.state = "none"
            self._flush_pending(as_reasoning=False)
        if self.state == "open":
            split = self._split_at_close(answer)
            if split is None:
                self._add_reasoning(answer)
            else:
                self._close(now, split[0], split[1])
            return
        if self.state == "none":
            split = self._split_at_close(answer)
            if split is not None:
                # A close tag without an opening one: the template opened the block inside
                # the prompt, so everything counted as answer until now was thinking.
                out = self.out
                out["reasoning_events"] += out["answer_events"]
                out["reasoning_chars"] += out["answer_chars"]
                out["answer_events"], out["answer_chars"], out["first_answer_s"] = 0, 0, None
                out["inline_think"] = True
                self.kept, self.kept_chars = [], 0
                self._close(now, split[0], split[1])
                return
        self._add_answer(now, answer)

    def finish(self) -> str:
        self._flush_pending(as_reasoning=False)
        return "".join(self.kept)


def stream_chat(chat_url: str, payload: Dict[str, Any], timeout: float = 1800.0, api_key: Optional[str] = None) -> Dict[str, Any]:
    """Send one streaming chat completion and time every event.

    All ``*_s`` values except ``connect_s`` are seconds from the moment the request was
    sent, after the connection was open. The dict always contains ``error`` (None on
    success) so callers never need a try/except.
    """
    request = dict(payload)
    request["stream"] = True
    request.setdefault("stream_options", {"include_usage": True})
    out = _stream_once(chat_url, request, timeout, api_key)
    if out.get("http_status") in (400, 422) and "stream_options" in str(out.get("error")):
        # An older server that does not know the field: ask again without it. Token counts
        # will then be estimated and the run is flagged "no-usage".
        request.pop("stream_options", None)
        out = _stream_once(chat_url, request, timeout, api_key)
    return out


def _stream_once(chat_url: str, request: Dict[str, Any], timeout: float, api_key: Optional[str]) -> Dict[str, Any]:
    body = json.dumps(request).encode("utf-8")

    out: Dict[str, Any] = {
        "error": None, "http_status": None, "connect_s": None, "headers_s": None, "first_event_s": None,
        "first_token_s": None, "first_answer_s": None, "last_token_s": None, "wall_s": None,
        "text_events": 0, "answer_events": 0, "reasoning_events": 0, "answer_chars": 0,
        "reasoning_chars": 0, "first_event_chars": 0, "bursts": 0, "first_burst_events": 0, "first_burst_chars": 0,
        "inline_think": False, "finish_reason": None, "sent_at": None,
        "usage": None, "timings": None, "stats": None, "saw_done": False, "malformed_events": 0,
        "gap_median_ms": None, "gap_p95_ms": None, "gap_max_ms": None, "answer_text": "",
    }
    gaps: List[float] = []
    accounting = _TextAccounting(out)
    last_text_at: Optional[float] = None
    conn: Optional[http.client.HTTPConnection] = None
    opened = started = time.perf_counter()
    stray = b""          # what the server said outside the event stream, for the error message
    event_name = ""      # the last "event:" field, so an event named "error" is recognised
    held = ""            # data lines of one event that is spread over several lines
    first_line = True
    try:
        try:
            conn, target = _connection(chat_url, timeout)
        except (ValueError, TypeError):
            out["error"] = "request could not be sent: the address is not valid"
            return out
        try:
            conn.connect()   # name lookup, address fallback and TLS are not the model's wait
        except socket.timeout:
            out["error"] = "connection failed: no answer within %.0f s" % timeout
            return out
        started = time.perf_counter()
        out["connect_s"] = started - opened
        out["sent_at"] = started
        try:
            conn.request("POST", target, body=body, headers=_headers(api_key, True))
        except (BrokenPipeError, ConnectionResetError):
            pass  # the server may have answered (for example "too large") before reading the body
        except (ValueError, TypeError):
            # http.client quotes the offending header value in its message: never pass that on.
            out["error"] = "request could not be sent: a header value is not valid"
            return out
        resp = conn.getresponse()
        out["headers_s"] = time.perf_counter() - started
        out["http_status"] = resp.status
        if resp.status != 200:
            detail = resp.read(4000).decode("utf-8", errors="replace")
            out["error"] = "HTTP %d: %s" % (resp.status, detail.strip()[:600])
            return out
        while True:
            asked = time.perf_counter()
            line = resp.readline()
            if not line:
                break
            arrived = time.perf_counter()
            now = arrived - started
            waited = arrived - asked
            if first_line:
                first_line = False
                if line.startswith(_BOM):
                    line = line[len(_BOM):]
            line = line.strip()
            if not line:  # a blank line ends an event
                if held:
                    out["malformed_events"] += 1
                    held = ""
                event_name = ""
                continue
            if line.startswith(b":"):
                continue  # comment or keep-alive
            if line.startswith(b"event:"):
                event_name = line[6:].strip().decode("utf-8", errors="replace").lower()
                continue
            if not line.startswith(b"data:"):
                if len(stray) < 600 and not line.startswith((b"id:", b"retry:")):
                    stray += line[:600] + b" "
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                out["saw_done"] = True
                break
            piece = data.decode("utf-8", errors="replace")
            try:
                event = json.loads(held + "\n" + piece if held else piece)
            except ValueError:
                try:  # a damaged line before this one must not swallow the events after it
                    event = json.loads(piece) if held else None
                except ValueError:
                    event = None
                if event is None:
                    held = held + "\n" + piece if held else piece  # perhaps one event spread over several data lines
                    continue
                out["malformed_events"] += 1
            held = ""
            if out["first_event_s"] is None:
                out["first_event_s"] = now
            if event_name == "error":
                out["error"] = "stream error: %s" % json.dumps(event)[:600]
                break
            if not isinstance(event, dict):
                continue
            if event.get("error"):
                out["error"] = "stream error: %s" % json.dumps(event["error"])[:600]
                break
            try:
                if isinstance(event.get("usage"), dict):
                    out["usage"] = event["usage"]
                if isinstance(event.get("timings"), dict):
                    out["timings"] = event["timings"]
                if isinstance(event.get("stats"), dict):
                    out["stats"] = event["stats"]
                answer = reasoning = ""
                choices = event.get("choices")
                for choice in choices if isinstance(choices, list) else []:
                    if not isinstance(choice, dict):
                        continue
                    if choice.get("finish_reason"):
                        out["finish_reason"] = choice["finish_reason"]
                    part_answer, part_reasoning = _delta_text(choice)
                    answer += part_answer
                    reasoning += part_reasoning
            except (AttributeError, TypeError, KeyError):
                out["malformed_events"] += 1  # valid JSON of an unexpected shape
                continue
            if not answer and not reasoning:
                continue
            size = len(answer) + len(reasoning)
            out["text_events"] += 1
            if out["first_token_s"] is None:
                out["first_token_s"] = now
                out["first_event_chars"] = size
            together = last_text_at is not None and waited < BURST_GAP_S
            if not together:
                out["bursts"] += 1
            if out["bursts"] == 1:
                out["first_burst_events"] += 1
                out["first_burst_chars"] += size
            if last_text_at is not None:
                gaps.append(now - last_text_at)
            last_text_at = now
            out["last_token_s"] = now
            accounting.add(now, answer, reasoning)
    except socket.timeout:
        out["error"] = "timed out after %.0f s without data" % timeout
    except (OSError, http.client.HTTPException) as exc:
        out["error"] = "connection failed: %s" % exc
    finally:
        out["wall_s"] = time.perf_counter() - started
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
    if held:
        out["malformed_events"] += 1
    out["answer_text"] = accounting.finish()
    if gaps:
        ordered = sorted(gaps)
        out["gap_median_ms"] = round(_percentile(ordered, 0.5) * 1000, 3)
        out["gap_p95_ms"] = round(_percentile(ordered, 0.95) * 1000, 3)
        out["gap_max_ms"] = round(ordered[-1] * 1000, 3)
    if out["error"] is None and out["text_events"] == 0:
        said = (stray or held.encode("utf-8", errors="replace")).decode("utf-8", errors="replace").strip()
        out["error"] = "the server returned no generated text" + ((" (it said: %s)" % said[:300]) if said else "")
    return out
