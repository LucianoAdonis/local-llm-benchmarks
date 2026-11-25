"""Self-test: check the measuring code against a server whose speeds are known.

A benchmark that cannot be checked is just a number generator. ``llmbench selftest``
starts the mock server in a separate process (so the two do not share a Python GIL),
replays the awkward cases that distort naive measurements, and fails if the client's
numbers drift from the truth by more than the tolerances below.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from .bench import Bench, depth_target
from .client import stream_chat
from .metrics import derive_run
from .mockserver import DEFAULTS, count_tokens, expected_timing, flatten
from .workload import Corpus, context_messages, seed_from

DECODE_TOLERANCE = 0.04       # +/- 4% on writing speed
TTFT_LATE_S = 0.040           # first token may be seen up to 40 ms late (scheduler, loopback)
TTFT_EARLY_S = 0.003
ATTEMPTS = 3


def spawn_mock(args: Optional[List[str]] = None) -> Tuple[subprocess.Popen, str]:
    """Start ``python -m llmbench mock-server`` on a free port and return (process, url)."""
    command = [sys.executable, "-m", "llmbench", "mock-server", "--port", "0", "--announce"] + list(args or [])
    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = package_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if not line.startswith("PORT "):
        proc.kill()
        raise RuntimeError("mock server did not start (got %r)" % line)
    return proc, "http://127.0.0.1:%s" % line.split()[1]


def _mock_prompt_tokens(messages: List[Dict[str, str]]) -> int:
    return count_tokens(flatten(messages)) + 4 * len(messages) + 3


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


TIMING_CASES: List[Tuple[str, Dict[str, Any]]] = [
    ("one token per event", {}),
    ("two tokens per event", {"chunk_tokens": 2}),
    ("16 tokens per event (buffered)", {"chunk_tokens": 16}),
    ("thinking in reasoning_content, then answer", {"reasoning_tokens": 60}),
    ("thinking in reasoning field, then answer", {"reasoning_tokens": 60, "reasoning_field": "reasoning"}),
    ("thinking inline as <think> tags", {"reasoning_tokens": 60, "reasoning_field": "inline"}),
    ("only thinking within the output cap", {"reasoning_tokens": 100000}),
    ("thinking counted but never streamed, declared", {"reasoning_tokens": 60, "reasoning_field": "hidden", "reasoning_details": True}),
    ("thinking counted but never streamed, undeclared", {"reasoning_tokens": 60, "reasoning_field": "hidden"}),
    ("server sends no token counts", {"include_usage": False}),
    ("fast writer, 400 tok/s", {"decode_tok_s": 400.0, "prefill_tok_s": 40000.0}),
]


def run_selftest(emit: Callable[[str], None] = print) -> bool:
    proc, url = spawn_mock()
    chat_url = url + "/v1/chat/completions"
    failures = 0
    try:
        text, _ = Corpus("diverse").build(6000, seed_from("selftest", 0))
        messages = context_messages(text, "selftest")
        prompt_tokens = _mock_prompt_tokens(messages)
        base = {"prefill_tok_s": 6000.0, "decode_tok_s": 80.0, "overhead_ms": 10.0}
        stream_chat(chat_url, {"model": "mock-model", "messages": messages, "max_tokens": 8, "mock": base})  # warm the connection path

        emit("Timing accuracy (mock server with known speeds)")
        emit("  %-48s %10s %10s %9s %9s  %s" % ("case", "write true", "measured", "error", "ttft err", "result"))
        for name, override in TIMING_CASES:
            mock = dict(base)
            mock.update(override)
            config = dict(DEFAULTS)
            config.update(mock)
            max_tokens = 240 if config["decode_tok_s"] > 200 else 120
            truth = expected_timing(config, prompt_tokens, max_tokens)
            decode_errors: List[float] = []
            ttft_errors: List[float] = []
            measured = 0.0
            ok = False
            for _ in range(ATTEMPTS):
                stream = stream_chat(chat_url, {"model": "mock-model", "messages": messages, "max_tokens": max_tokens, "mock": mock})
                run = derive_run(stream, max_tokens=max_tokens, expect_fresh=True, estimated_prompt_tokens=prompt_tokens)
                if run.get("error") or not run.get("client_decode_tok_s"):
                    decode_errors.append(1.0)
                    ttft_errors.append(1.0)
                    continue
                measured = run["client_decode_tok_s"]
                decode_errors.append(measured / truth["decode_tok_s"] - 1.0)
                ttft_errors.append(run["ttft_s"] - truth["first_event_s"])
                decode_error, ttft_error = _median(decode_errors), _median(ttft_errors)
                ok = abs(decode_error) <= DECODE_TOLERANCE and -TTFT_EARLY_S <= ttft_error <= TTFT_LATE_S
                if ok:
                    break
            decode_error, ttft_error = _median(decode_errors), _median(ttft_errors)
            failures += 0 if ok else 1
            emit("  %-48s %10.1f %10.1f %+8.1f%% %+7.1fms  %s" % (name, truth["decode_tok_s"], measured, decode_error * 100, ttft_error * 1000, "ok" if ok else "FAIL"))

        emit("")
        emit("Validity checks (the client must notice these)")

        def check(name: str, passed: bool, detail: str = "") -> None:
            nonlocal failures
            failures += 0 if passed else 1
            emit("  %-58s %s%s" % (name, "ok" if passed else "FAIL", (" (" + detail + ")") if detail and not passed else ""))

        def one(mock: Dict[str, Any], msgs: List[Dict[str, str]], max_tokens: int = 40, **derive: Any) -> Dict[str, Any]:
            settings = dict(base, decode_tok_s=400.0, prefill_tok_s=60000.0)
            settings.update(mock)
            stream = stream_chat(chat_url, {"model": "mock-model", "messages": msgs, "max_tokens": max_tokens, "mock": settings})
            derive.setdefault("expect_fresh", True)
            return derive_run(stream, max_tokens=max_tokens, estimated_prompt_tokens=_mock_prompt_tokens(msgs), **derive)

        cache_messages = context_messages(text, "cache-probe")
        one({"cache": True}, cache_messages)
        repeat = one({"cache": True}, cache_messages)
        check("repeated prompt is flagged as a cache hit", "cache-hit" in repeat["flags"], str(repeat["flags"]))
        check("cached tokens are excluded from the reading rate", (repeat.get("fresh_prompt_tokens") or 10**9) < 0.1 * prompt_tokens, str(repeat.get("fresh_prompt_tokens")))
        fresh = one({"cache": True}, context_messages(text, "a-different-run"))
        check("a new run marker defeats the prefix cache", "cache-hit" not in fresh["flags"], str(fresh["flags"]))
        truncated = one({"n_ctx": 600}, messages)
        check("silently truncated prompt is flagged", "prompt-truncated" in truncated["flags"], str(truncated["flags"]))
        rejected = one({"n_ctx": 600, "context_error": True}, messages)
        check("context-size rejection is reported as an error", bool(rejected.get("error")) and "context" in str(rejected["error"]), str(rejected.get("error")))
        early = one({"stop_after_tokens": 10}, messages, max_tokens=120)
        check("early stop is flagged as short output", "short-output" in early["flags"], str(early["flags"]))
        silent = one({"include_usage": False}, messages)
        check("missing token counts are flagged", "no-usage" in silent["flags"], str(silent["flags"]))
        thinking = one({"reasoning_tokens": 100000}, messages)
        check("thinking-only output is measured and labelled", "reasoning-only" in thinking["flags"] and bool(thinking.get("decode_tok_s")), str(thinking["flags"]))
        engine = one({"include_timings": True, "chunk_tokens": 40}, messages)
        check("engine timings are preferred when present", engine.get("decode_source") == "engine" and abs((engine.get("decode_tok_s") or 0) / 400.0 - 1) < 0.001, str(engine.get("decode_source")))
        hidden = one({"reasoning_tokens": 60, "reasoning_field": "hidden", "reasoning_details": True}, messages, max_tokens=120)
        check("hidden thinking is counted as hidden, not as speed", hidden.get("hidden_tokens") == 60 and "hidden-tokens" in hidden["flags"] and abs((hidden.get("decode_tok_s") or 0) / 400.0 - 1) < 0.1, "%s %s" % (hidden.get("hidden_tokens"), hidden.get("decode_tok_s")))
        pairs = one({"chunk_tokens": 2}, messages, max_tokens=120)
        check("two tokens per event are not mistaken for hidden tokens", not pairs.get("hidden_tokens") and abs((pairs.get("decode_tok_s") or 0) / 400.0 - 1) < 0.1, "%s %s" % (pairs.get("hidden_tokens"), pairs.get("decode_tok_s")))

        emit("")
        emit("End-to-end quick suite against the mock (read 40,000 tok/s, write 150 tok/s)")
        fast = {"prefill_tok_s": 40000.0, "decode_tok_s": 150.0, "overhead_ms": 10.0}
        bench = Bench(url=url, model="mock-model", suite="quick", extra_body={"mock": fast}, emit=lambda line: None)
        result = bench.run()
        head = result["headline"]
        writing = head.get("writing_tok_s") or 0.0
        check("writing speed within 4%% (measured %.1f)" % writing, abs(writing / 150.0 - 1) <= DECODE_TOLERANCE)
        target = depth_target("16k")
        expected_proxy = target / (0.010 + target / 40000.0)  # only the fixed overhead remains in the estimate
        reading = (head.get("reading_tok_s") or {}).get("16k") or 0.0
        check("reading speed at 16K within 6%% (measured %.0f, expected %.0f)" % (reading, expected_proxy), abs(reading / expected_proxy - 1) <= 0.06)
        sizes = [r.get("prompt_tokens") for s in result["scenarios"] if s["id"] == "ctx-16k" for r in s["runs"]]
        check("prompt size hits the 16K target within 5%% (got %s)" % sizes, all(s and abs(s - target) <= 0.05 * target for s in sizes))
        check("result quality is not 'invalid' (got %s)" % result["verdict"]["status"], result["verdict"]["status"] != "invalid")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    emit("")
    emit("Self-test %s" % ("passed: the client measures correctly on this machine." if not failures else "FAILED: %d check(s). Close heavy background work and retry before trusting results." % failures))
    return failures == 0
