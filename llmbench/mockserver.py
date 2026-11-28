"""A deterministic stand-in for an OpenAI-compatible server.

It "reads" prompts and "writes" tokens at speeds you choose, so the benchmark client can
be checked against a known answer: if the mock decodes at 80 tok/s and the client reports
120, the client is wrong. It also imitates the server behaviors that distort naive
measurements: thinking tokens, buffered streams, prefix caches, missing usage, silent
prompt truncation and early stops.

Per-request overrides: put a ``"mock": {...}`` object in the request body.
"""
from __future__ import annotations

import json
import math
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

CHARS_PER_TOKEN = 4
WORDS = (
    "the cache layer retries failed writes before the queue drains and every worker "
    "reports latency so operators can compare batches without guessing which shard is slow"
).split()

DEFAULTS: Dict[str, Any] = {
    "prefill_tok_s": 2000.0,     # prompt tokens processed per second
    "decode_tok_s": 100.0,       # tokens generated per second
    "overhead_ms": 20.0,         # fixed cost before prefill starts (HTTP, templating)
    "chunk_tokens": 1,           # tokens per streamed event (1 = per-token stream)
    "reasoning_tokens": 0,       # tokens emitted as thinking before the answer
    "reasoning_field": "reasoning_content",  # or "reasoning", "inline" for <think> tags, "hidden" to count but not send them
    "reasoning_details": False,  # report reasoning tokens in usage.completion_tokens_details
    "include_usage": True,
    "include_timings": False,    # attach llama.cpp-style timings to the final chunk
    "cache": False,              # reuse the longest common prefix with an earlier request
    "cache_slots": 1,            # how many earlier prompts are remembered (slots / RAM cache)
    "n_ctx": 0,                  # >0: context window in tokens
    "context_error": False,      # with n_ctx: reject oversized prompts instead of truncating
    "stop_after_tokens": 0,      # >0: end early with finish_reason "stop"
    # How a request with a JSON schema in response_format is answered: "enforce" holds the
    # answer to the schema (a grammar, as llama.cpp and LM Studio do); "ignore" copies the
    # catalogue's long descriptions and so breaks maxLength; "refuse" answers HTTP 502
    # structured_output_failed, as Strata does. The last two fit once they are told what was
    # wrong, so a caller's retry is exercised too. "" leaves response_format unread.
    "schema": "enforce",
}

_CATALOGUE_LINE = re.compile(r"^\d+\. (.+?) \| (\d+) \| (.+)$", re.M)
SCHEMA_REFUSAL = {"error": {"code": "structured_output_failed", "message": "the model's answer does not match the requested schema", "type": "server_error"}}


def schema_answer(messages: List[Dict[str, Any]], fit: bool) -> str:
    """The catalogue in the probe's JSON form, its descriptions cut to fit or left whole."""
    text = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    items = []
    for name, price, description in _CATALOGUE_LINE.findall(text):
        items.append({"name": name[:60], "price": int(price), "description": description[:80] if fit else description})
    return json.dumps({"items": items})

# time.sleep() is not precise enough to pace tokens: measured overshoot is 4 to 15 ms on
# macOS (timer coalescing) and up to a 15.6 ms tick on older Windows Pythons. So sleep only
# while the deadline is far away, then yield in a tight loop for the last stretch.
_SPIN_MARGIN_S = 0.025


def sleep_until(deadline: float) -> None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > _SPIN_MARGIN_S:
            time.sleep(remaining - _SPIN_MARGIN_S)
        else:
            time.sleep(0)  # yield the GIL without giving up accuracy


def count_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def common_prefix(a: str, b: str) -> int:
    """Length of the shared prefix, found by bisection on slices (fast for long prompts)."""
    low, high = 0, min(len(a), len(b))
    while low < high:
        middle = (low + high + 1) // 2
        if a[:middle] == b[:middle]:
            low = middle
        else:
            high = middle - 1
    return low


def flatten(messages: List[Dict[str, Any]]) -> str:
    return "".join("%s:%s\n" % (m.get("role", ""), m.get("content") or "") for m in messages)


_EXACT_WORD = re.compile(r"Reply with exactly this word and nothing else: (\S+)")
_SUM = re.compile(r"the sum of (\d+) and (\d+)")
_NEEDLE = re.compile(r"(ACCESS-CODE-(?:ALPHA|OMEGA)) = (\S+)")


def scripted_answer(messages: List[Dict[str, Any]], visible_text: str) -> Optional[str]:
    """Answer the benchmark's exact-answer checks the way a correct model would.

    The needle answer is built only from text that survived truncation, so a mock with a
    small ``n_ctx`` loses the early needle exactly as a truncating runtime does.
    """
    question = str(messages[-1].get("content") or "") if messages else ""
    match = _EXACT_WORD.search(question)
    if match:
        return match.group(1)
    match = _SUM.search(question)
    if match and "JSON" in question:
        return json.dumps({"status": "ok", "sum": int(match.group(1)) + int(match.group(2))})
    if "ACCESS-CODE-ALPHA and ACCESS-CODE-OMEGA" in question:
        found = dict(_NEEDLE.findall(visible_text))
        return "ALPHA is %s and OMEGA is %s" % (found.get("ACCESS-CODE-ALPHA", "unknown"), found.get("ACCESS-CODE-OMEGA", "unknown"))
    return None


def expected_timing(config: Dict[str, Any], fresh_tokens: int, completion_tokens: int) -> Dict[str, float]:
    """Ground truth for a request, used by the self-test."""
    prefill_s = fresh_tokens / config["prefill_tok_s"]
    first = config["overhead_ms"] / 1000.0 + prefill_s + 1.0 / config["decode_tok_s"]
    chunk = max(1, int(config["chunk_tokens"]))
    # The first event a client sees is the first group that holds a streamed token: groups
    # made only of hidden thinking tokens are generated but never sent.
    hidden = min(int(config["reasoning_tokens"]), completion_tokens) if config.get("reasoning_field") == "hidden" else 0
    first_group_end = min((hidden // chunk + 1) * chunk, completion_tokens)
    first_event = first + (first_group_end - 1) / config["decode_tok_s"]
    return {
        "first_token_s": first,
        "first_event_s": first_event,
        "last_token_s": first + (completion_tokens - 1) / config["decode_tok_s"],
        "decode_tok_s": config["decode_tok_s"],
        "prefill_tok_s": config["prefill_tok_s"],
    }


class MockState:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = dict(DEFAULTS)
        self.config.update(config)
        self.lock = threading.Lock()
        self.cached_texts: List[str] = []
        self.requests = 0


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "llmbench-mock"

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def handle(self) -> None:
        # Clients hang up as soon as they see [DONE]; that is not an error worth a traceback.
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    # ---- helpers
    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _chunk(self, payload: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
        self.wfile.flush()

    def _event(self, obj: Any) -> None:
        self._chunk(b"data: " + json.dumps(obj).encode("utf-8") + b"\n\n")

    # ---- routes
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.rstrip("/") == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "mock-model", "object": "model", "owned_by": "llmbench"}]})
        elif self.path.rstrip("/") == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        received = time.perf_counter()
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            self._json(400, {"error": {"message": "invalid JSON"}})
            return
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        state: MockState = self.server.state  # type: ignore[attr-defined]
        config = dict(state.config)
        if isinstance(request.get("mock"), dict):
            config.update(request["mock"])

        messages = request.get("messages") or []
        prompt_text = flatten(messages)
        prompt_tokens = count_tokens(prompt_text) + 4 * len(messages) + 3
        max_tokens = int(request.get("max_tokens") or request.get("max_completion_tokens") or 128)

        visible_text = prompt_text
        if config["n_ctx"] and prompt_tokens + max_tokens > config["n_ctx"]:
            if config["context_error"]:
                self._json(400, {"error": {"message": "request (%d tokens) exceeds the available context size (%d tokens)" % (prompt_tokens, config["n_ctx"]), "type": "exceed_context_size_error"}})
                return
            prompt_tokens = max(1, int(config["n_ctx"]) - max_tokens)  # silent truncation
            visible_text = prompt_text[-prompt_tokens * CHARS_PER_TOKEN:]  # the oldest text is dropped

        with state.lock:
            state.requests += 1
            cached_tokens = 0
            if config["cache"]:
                best = max((common_prefix(prompt_text, earlier) for earlier in state.cached_texts), default=0)
                cached_tokens = min(prompt_tokens - 1, best // CHARS_PER_TOKEN)
        fresh_tokens = prompt_tokens - cached_tokens

        completion_tokens = max_tokens
        finish_reason = "length"
        if config["stop_after_tokens"] and config["stop_after_tokens"] < max_tokens:
            completion_tokens = int(config["stop_after_tokens"])
            finish_reason = "stop"
        reasoning_tokens = min(int(config["reasoning_tokens"]), completion_tokens)
        inline = config["reasoning_field"] == "inline"
        scripted = scripted_answer(messages, visible_text)
        response_format = request.get("response_format")
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema" and config["schema"]:
            told = "does not fit the form" in str((messages[-1] if messages else {}).get("content") or "")
            if (config["schema"] == "refuse" and not told) or config["schema"] == "refuse-always":
                self._json(502, SCHEMA_REFUSAL)
                return
            scripted = schema_answer(messages, fit=config["schema"] == "enforce" or told)
        scripted_words: List[str] = []
        if scripted is not None:  # a question with a known right answer: think, answer, stop
            scripted_words = scripted.split(" ")
            wanted = reasoning_tokens + len(scripted_words)
            if wanted <= max_tokens:
                completion_tokens, finish_reason = wanted, "stop"

        tokens: List[Tuple[str, str]] = []  # (kind, text)
        for i in range(completion_tokens):
            if scripted is not None and i >= reasoning_tokens:
                word = scripted_words[i - reasoning_tokens] + " "
            else:
                word = WORDS[i % len(WORDS)] + " "
            if i < reasoning_tokens:
                if inline:
                    text = ("<think>" + word) if i == 0 else word
                    if i == reasoning_tokens - 1:
                        text += "</think>"
                    tokens.append(("content", text))
                else:
                    tokens.append(("reasoning", word))
            else:
                tokens.append(("content", word))
        answer_text = "".join(text for kind, text in tokens[reasoning_tokens:])

        truth = expected_timing(config, fresh_tokens, completion_tokens)
        first_at = received + truth["first_token_s"]
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        }
        if config["reasoning_details"]:
            usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
        timings = {
            "cache_n": cached_tokens,
            "prompt_n": fresh_tokens,
            "prompt_ms": fresh_tokens / config["prefill_tok_s"] * 1000.0,
            "prompt_per_second": config["prefill_tok_s"],
            "predicted_n": completion_tokens,
            "predicted_ms": completion_tokens / config["decode_tok_s"] * 1000.0,
            "predicted_per_second": config["decode_tok_s"],
        }

        def remember() -> None:
            if config["cache"]:
                with state.lock:
                    state.cached_texts.append(prompt_text + "assistant:" + answer_text + "\n")
                    del state.cached_texts[: -max(1, int(config["cache_slots"]))]

        if not request.get("stream"):
            sleep_until(first_at + (completion_tokens - 1) / config["decode_tok_s"])
            message: Dict[str, Any] = {"role": "assistant", "content": answer_text}
            if reasoning_tokens and not inline and config["reasoning_field"] != "hidden":
                message[config["reasoning_field"]] = "".join(text for kind, text in tokens[:reasoning_tokens])
            body: Dict[str, Any] = {"id": "mock", "object": "chat.completion", "model": "mock-model", "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}], "usage": usage}
            if config["include_timings"]:
                body["timings"] = timings
            remember()
            self._json(200, body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        base = {"id": "mock", "object": "chat.completion.chunk", "model": "mock-model"}
        try:
            # Role-only frame arrives immediately, as on real servers. It carries no token.
            self._event(dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]))
            chunk = max(1, int(config["chunk_tokens"]))
            index = 0
            while index < completion_tokens:
                group = tokens[index : index + chunk]
                index += len(group)
                sleep_until(first_at + (index - 1) / config["decode_tok_s"])
                delta: Dict[str, str] = {}
                for kind, text in group:
                    if kind != "content" and config["reasoning_field"] == "hidden":
                        continue  # generated and counted, never sent
                    key = "content" if kind == "content" else config["reasoning_field"]
                    delta[key] = delta.get(key, "") + text
                if delta:
                    self._event(dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]))
            # Update the cache before telling the client we are done: a follow-up request can
            # arrive the instant [DONE] is read, and a real engine's cache is ready by then.
            remember()
            final = dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": finish_reason}])
            if config["include_timings"]:
                final["timings"] = timings
            self._event(final)
            if config["include_usage"] and (request.get("stream_options") or {}).get("include_usage"):
                self._event(dict(base, choices=[], usage=usage))
            self._chunk(b"data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


class _Server(ThreadingHTTPServer):
    # The default backlog of 5 refuses connections when a parallel scenario opens many at
    # once on Windows; real runtimes accept far more.
    request_queue_size = 128


class MockServer:
    """Runs the mock in a background thread. Use as a context manager in tests."""

    def __init__(self, port: int = 0, host: str = "127.0.0.1", **config: Any) -> None:
        self.httpd = _Server((host, port), MockHandler)
        self.httpd.daemon_threads = True
        self.httpd.state = MockState(config)  # type: ignore[attr-defined]
        self.thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.port

    @property
    def state(self) -> MockState:
        return self.httpd.state  # type: ignore[attr-defined]

    def start(self) -> "MockServer":
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=2)

    def __enter__(self) -> "MockServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
