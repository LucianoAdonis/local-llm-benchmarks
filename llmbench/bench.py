"""Scenario definitions and the suite runner.

A suite is a fixed list of scenarios, like the scenes of a graphics benchmark. Each scenario
answers one question a user actually has:

chat          How long until a short question starts answering, and how fast does it write?
gen-long      Does writing speed hold up over a long answer (heat, throttling)?
ctx-<N>k      How long does it take to read a fresh context that fills an N-thousand-token window?
followup-<N>k After that first read, how quick is the next question on the same context (cache)?
repeat-<N>k   Same size but repetitive text: does this runtime speed up on repeated content?
parallel-<n>  What happens to total throughput with n requests at once?
schema        Asked for JSON in a fixed form, does the server hold the model to it, or only
              check the answer afterwards (and refuse it, or pass it on broken)?
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import PROTOCOL_VERSION, RESULT_SCHEMA, WORKLOAD_VERSION, __version__
from . import runtimes, sysinfo
from .client import EndpointError, post_json, split_base_url, stream_chat
from .metrics import MIN_PREFILL_TOKENS, derive_run, fit_reading, normalize_engine, request_time, run_is_valid, stability, summarize_runs
from .sanitize import clean_text
from .workload import (
    SANITY_CHECKS, Corpus, chat_messages, check_schema, context_messages, followup_messages, message_chars, sanity_messages, schema_form,
    schema_messages, seed_from,
)

# A depth class is named after the context window it fits. The prompt targets 90% of what
# that window leaves after the answer, so prompt plus output plus the drift between two
# texts of the same length still fits a window of exactly that size: ctx-32k sends about
# 29,300 tokens and fits a 32,768-token profile.
DEPTH_CLASSES = {"4k": 4, "8k": 8, "16k": 16, "32k": 32, "64k": 64, "128k": 128, "256k": 256, "512k": 512, "1m": 1024}
FILL_FRACTION = 0.90
FIT_MARGIN = 0.03
DEPTH_WHEN_CONTEXT_UNKNOWN = "16k"
# 256 tokens gives the writing-speed measurement at depth a window of a second or more on
# fast machines; shorter windows were visibly noisy in the v1 data.
CONTEXT_OUTPUT_TOKENS = 256
FOLLOWUP_QUESTION_TOKENS = 96
DRIFT_TOLERANCE = 0.10
DEFAULT_CHARS_PER_TOKEN = 3.3
CHARS_PER_TOKEN_RANGE = (1.0, 8.0)
SOAK_MIN_LOOPS = 3
SOAK_MAX_LOOPS = 5000
SOAK_STABLE_RATIO = 0.97   # 3DMark's stress-test pass mark, used here as a caution line
THINKING_OFF_BODY = {"reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False}}
# What a server says when the prompt is larger than the model's window. A bare "context"
# or "exceeded" is not enough: "context canceled" and "rate limit exceeded" are not about size.
SIZE_REJECTION = re.compile(
    r"(?i)context (size|length|window)|maximum context|exceed_context|exceeds? (the )?(available |maximum |model'?s? )?context|"
    r"too (long|large|many tokens)|n_ctx|token limit|prompt is too|input is too"
)
TIMED_OUT = re.compile(r"(?i)timed out|no answer within")
# Strata answers HTTP 502 with error.code "structured_output_failed" when the model's answer
# does not fit the requested schema: it prompts with the schema instead of constraining the
# decoding to it. A caller should ask again, as for any answer that does not fit.
FORMAT_REFUSAL = re.compile(r"structured_output_failed")
SCHEMA_RETRIES = 2


def depth_target(label: str, reserve: int = CONTEXT_OUTPUT_TOKENS) -> int:
    return int((DEPTH_CLASSES[label] * 1024 - reserve) * FILL_FRACTION)


def followup_target(label: str) -> int:
    """First-turn size for a follow-up pair: both turns must fit the window."""
    return depth_target(label, reserve=2 * CONTEXT_OUTPUT_TOKENS + FOLLOWUP_QUESTION_TOKENS)


def scenario(sid: str, kind: str, max_tokens: int, runs: int, title: str, **extra: Any) -> Dict[str, Any]:
    spec = {"id": sid, "kind": kind, "max_tokens": max_tokens, "runs": runs, "title": title}
    spec.update(extra)
    return spec


def chat_scenario(runs: int = 5) -> Dict[str, Any]:
    return scenario("chat", "chat", 256, runs, "Short question, 256-token answer")


def gen_scenario(runs: int = 3) -> Dict[str, Any]:
    return scenario("gen-long", "chat", 1024, runs, "Short question, 1,024-token answer (sustained writing)")


def ctx_scenario(depth: str, runs: int = 3) -> Dict[str, Any]:
    # Counted runs, after the uncounted first read. Three everywhere: a comparison of two
    # results has nothing to work with when a row rests on fewer.
    return scenario("ctx-%s" % depth, "context", CONTEXT_OUTPUT_TOKENS, runs, "Read a fresh context that fits a %s window" % depth.upper(), depth=depth)


def followup_scenario(depth: str, runs: int = 3) -> Dict[str, Any]:
    return scenario("followup-%s" % depth, "followup", CONTEXT_OUTPUT_TOKENS, runs, "Second question on the same %s context (prefix cache)" % depth.upper(), depth=depth)


def repeat_scenario(depth: str, runs: int = 3) -> Dict[str, Any]:
    return scenario("repeat-%s" % depth, "context", CONTEXT_OUTPUT_TOKENS, runs, "%s of repetitive text (content-sensitivity probe)" % depth.upper(), depth=depth, corpus="repetitive")


def parallel_scenario(count: int, runs: int = 2) -> Dict[str, Any]:
    return scenario("parallel-%d" % count, "parallel", 256, runs, "%d short requests at the same time" % count, parallel=count)


def schema_scenario(runs: int = 3) -> Dict[str, Any]:
    return scenario("schema", "schema", 2048, runs, "Copy a catalogue into a fixed JSON form (is the schema enforced?)")


def control_scenario() -> Dict[str, Any]:
    return scenario("control", "chat", 256, 2, "The first scenario again, at the end, to detect drift")


def sanity_scenario() -> Dict[str, Any]:
    return scenario("sanity", "sanity", 1024, len(SANITY_CHECKS), "Three exact-answer checks, one of them a 4K read: does the model see the whole prompt?", depth="4k")


def soak_scenario(minutes: float = 10.0) -> Dict[str, Any]:
    return scenario("soak", "soak", 256, SOAK_MIN_LOOPS, "Repeat a 4K read and a 256-token answer for %g minutes (heat and stability)" % minutes, depth="4k", minutes=minutes)


def build_suite(name: str) -> List[Dict[str, Any]]:
    if name == "quick":
        return [chat_scenario(3), ctx_scenario("4k"), ctx_scenario("16k")]
    if name == "standard":
        return [chat_scenario(5), gen_scenario(3), ctx_scenario("4k"), ctx_scenario("16k"), followup_scenario("16k"), ctx_scenario("64k"), sanity_scenario(), control_scenario()]
    if name == "deep":
        return [
            chat_scenario(5), gen_scenario(3), ctx_scenario("4k"), ctx_scenario("16k"), followup_scenario("16k"),
            repeat_scenario("16k"), ctx_scenario("32k"), ctx_scenario("64k"), ctx_scenario("128k"), ctx_scenario("256k"),
            parallel_scenario(4), schema_scenario(), sanity_scenario(), control_scenario(),
        ]
    raise ValueError("unknown suite %r (choose quick, standard or deep)" % name)


def grade_sanity(answer: str, expectation: Dict[str, Any]) -> Optional[bool]:
    """True or False for a definite result, None when the model gave no answer text."""
    text = answer.strip()
    if not text:
        return None
    if "contains" in expectation:
        return all(str(item).lower() in text.lower() for item in expectation["contains"])
    if "json" in expectation:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return False
        try:
            data = json.loads(text[start : end + 1])
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        for key, wanted in expectation["json"].items():
            got = data.get(key)
            if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
                try:
                    if float(got) != float(wanted):
                        return False
                except (TypeError, ValueError):
                    return False
            elif str(got).strip().lower() != str(wanted).lower():
                return False
        return True
    return None


def sanity_summary(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "checks_total": len(runs),
        "checks_passed": sum(1 for r in runs if r.get("passed") is True),
        "checks_failed": [r.get("check") for r in runs if r.get("passed") is False],
        "checks_errored": [r.get("check") for r in runs if r.get("passed") is None and r.get("error")],
        "checks_inconclusive": [r.get("check") for r in runs if r.get("passed") is None and not r.get("error")],
    }


def schema_outcome(stream: Dict[str, Any], form: Dict[str, Any]) -> Tuple[str, List[str]]:
    """fits, violates, not-json, no-answer (thinking used the cap), refused (the server's own
    schema check said no) or error (a failure unrelated to the form)."""
    error = stream.get("error")
    if error:
        return ("refused", ["the server refused the answer: structured_output_failed"]) if FORMAT_REFUSAL.search(str(error)) else ("error", [])
    text = (stream.get("answer_text") or "").strip()
    if not text:
        return "no-answer", []
    start, end = text.find("{"), text.rfind("}")
    try:
        value = json.loads(text[start : end + 1]) if 0 <= start < end else None
    except ValueError:
        value = None
    if value is None:
        return "not-json", ["the answer is not one JSON object"]
    found = check_schema(value, form)
    return ("violates", found) if found else ("fits", [])


SCHEMA_BROKEN = ("violates", "not-json", "refused")


def schema_summary(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    outcomes = [r["schema"] for r in runs if isinstance(r.get("schema"), dict)]
    first: Dict[str, int] = {}
    for outcome in outcomes:
        first[outcome["first_try"]] = first.get(outcome["first_try"], 0) + 1
    judged = [o for o in outcomes if o["first_try"] not in ("error", "no-answer")]
    return {
        "requests": len(outcomes),
        "first_try": first,
        "fit_in_the_end": sum(1 for o in outcomes if o["final"] == "fits"),
        "retries": sum(o["attempts"] - 1 for o in outcomes),
        # None when nothing could be judged (every request failed, or thinking used the cap).
        "held_to_form": (not any(o["first_try"] in SCHEMA_BROKEN for o in judged)) if judged else None,
    }


def schema_line(outcome: Dict[str, Any]) -> str:
    first, final, attempts = outcome.get("first_try"), outcome.get("final"), outcome.get("attempts", 1)
    if first == "fits":
        return "fits the form"
    if attempts > 1:
        return "%s, then %s after %d %s" % (first, final, attempts - 1, "retry" if attempts == 2 else "retries")
    return str(first)


def first_run_summary(first: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """The uncounted first read at a size, next to the steady-state medians."""
    out: Dict[str, Any] = {key: first.get(key) for key in ("ttft_s", "prefill_tok_s", "decode_tok_s", "prompt_tokens", "flags")}
    for metric, name in (("prefill_tok_s", "reading_vs_steady_pct"), ("decode_tok_s", "writing_vs_steady_pct")):
        steady = (summary.get(metric) or {}).get("median")
        if steady and first.get(metric):
            out[name] = (first[metric] / steady - 1.0) * 100.0
    return out


def soak_stability(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Worst loop divided by best loop, the way graphics stress tests report stability."""
    out: Dict[str, Any] = {"loops": len(runs)}
    for metric, name in (("decode_tok_s", "writing"), ("prefill_tok_s", "reading")):
        values = [r[metric] for r in runs if run_is_valid(r) and r.get(metric)]
        if len(values) >= 2:
            out[name] = {"first": values[0], "best": max(values), "worst": min(values), "last": values[-1], "ratio": min(values) / max(values)}
    return out


SUITE_NAMES = ("quick", "standard", "deep")


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-")[:60] or "model"


def tidy(value: Any) -> Any:
    """Round floats to six significant digits so result files stay readable and diff well."""
    if isinstance(value, float):
        return float("%.6g" % value)
    if isinstance(value, dict):
        return {key: tidy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [tidy(item) for item in value]
    return value


def _fmt(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return "{:,.0f}".format(value)
    return ("%." + str(digits) + "f") % value


def _safe(text: Any, limit: int = 0) -> str:
    """Server text, redacted before it is shown or stored, then cut. Never the other way round."""
    cleaned = clean_text(str(text), free_text=True)
    return cleaned[:limit] if limit else cleaned


def _attempted(record: Dict[str, Any]) -> bool:
    return bool(record.get("runs")) or record.get("first_run") is not None or bool((record.get("summary") or {}).get("runs_total"))


def normalize_ids(ids: List[str]) -> List[str]:
    """Lower-case, drop repeats, and keep the drift check last."""
    seen: List[str] = []
    for sid in ids:
        sid = sid.strip().lower()
        if sid and sid not in seen:
            seen.append(sid)
    if "control" in seen:
        seen.remove("control")
        seen.append("control")
    return seen


class Bench:
    def __init__(
        self,
        url: str,
        model: Optional[str] = None,
        suite: str = "standard",
        context: Optional[int] = None,
        corpus: str = "diverse",
        runs: Optional[int] = None,
        depths: Optional[List[str]] = None,
        only: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        timeout: float = 1800.0,
        extra_body: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None,
        seed: str = "llmbench",
        engine_log: Optional[str] = None,
        cold: bool = False,
        checkpoint: Optional[Callable[[Dict[str, Any]], None]] = None,
        thinking: str = "default",
        soak_minutes: float = 0.0,
        size_warmup: bool = True,
        fixed_text: bool = False,
        emit: Callable[[str], None] = print,
    ) -> None:
        self.root, chat_path = split_base_url(url)
        self.chat_url = self.root + chat_path
        self.model = model
        self.suite_name = suite
        if context is not None and context < 1024:
            raise ValueError("--context is a size in tokens (for example 16384)")
        self.context = context
        self.context_source = "argument" if context else None
        self.corpus = Corpus(corpus)
        self.corpora: Dict[str, Corpus] = {self.corpus.key: self.corpus}
        if runs is not None and runs < 1:
            raise ValueError("--runs must be 1 or more")
        self.runs_override = runs
        self.api_key = api_key
        self.timeout = timeout
        if extra_body is not None and not isinstance(extra_body, dict):
            raise ValueError("the extra request body must be a JSON object")
        self.extra_body = dict(extra_body or {})
        self.size_warmup = size_warmup
        self.checkpoint = checkpoint
        self.clock_zero = time.monotonic()
        self.thinking = thinking
        if thinking == "off":
            # Best effort: the two request fields current runtimes understand. Whether the
            # model really stopped thinking is visible in the result (reasoning_seen).
            self.extra_body.setdefault("reasoning_effort", THINKING_OFF_BODY["reasoning_effort"])
            template = self.extra_body.setdefault("chat_template_kwargs", {})
            if isinstance(template, dict):
                template.setdefault("enable_thinking", False)
        elif thinking != "default":
            raise ValueError("thinking must be 'default' or 'off'")
        self.label = label
        self.seed = seed
        self.engine_log = engine_log
        self.cold = cold
        self.emit = emit
        # A new salt for every invocation. It goes into the run markers and, unless
        # fixed_text is asked for, into the text itself: an engine that caches by content
        # (or keeps conversations on disk across restarts) then has nothing from an
        # earlier invocation to reuse.
        self.salt = os.urandom(4).hex()
        self.fixed_text = fixed_text
        self.calibration: Dict[str, Dict[str, Any]] = {}
        self.cache_baseline = 0
        self.runtime: Dict[str, Any] = {}
        self.loaded_before: Optional[bool] = None
        self.notes: List[str] = []
        self.last_size: Dict[str, Tuple[int, int]] = {}
        self.started: Optional[dt.datetime] = None
        self.system: Dict[str, Any] = {}
        self.state_before: Dict[str, Any] = {}
        self.warnings: List[str] = []
        self.warm: Dict[str, Any] = {}
        self.scenarios = build_suite(suite)
        self.custom_selection = bool(depths or only or runs or (soak_minutes and soak_minutes > 0))
        if depths:
            depths = normalize_ids(depths)
            for depth in depths:
                if depth not in DEPTH_CLASSES:
                    raise ValueError("unknown depth %r (choose from %s)" % (depth, ", ".join(DEPTH_CLASSES)))
            kept = [s for s in self.scenarios if s["kind"] != "context" or s.get("corpus")]
            first_context = next((i for i, s in enumerate(self.scenarios) if s["kind"] == "context"), len(kept))
            position = min(first_context, len(kept))
            self.scenarios = kept[:position] + [ctx_scenario(d) for d in depths] + kept[position:]
        if only:
            only = normalize_ids(only)
            known = {s["id"]: s for s in self.scenarios}
            self.scenarios = [known[sid] if sid in known else self._scenario_from_id(sid) for sid in only]
        if runs:
            for spec in self.scenarios:
                if spec["kind"] not in ("soak", "sanity") and spec["id"] != "control":
                    spec["runs"] = runs
        if soak_minutes and soak_minutes > 0:
            existing = next((s for s in self.scenarios if s["kind"] == "soak"), None)
            if existing:
                existing.update(soak_scenario(soak_minutes))
            else:
                position = next((i for i, s in enumerate(self.scenarios) if s["id"] == "control"), len(self.scenarios))
                self.scenarios.insert(position, soak_scenario(soak_minutes))  # the drift check stays last

    @staticmethod
    def _scenario_from_id(sid: str) -> Dict[str, Any]:
        if sid == "chat":
            return chat_scenario()
        if sid == "gen-long":
            return gen_scenario()
        if sid == "sanity":
            return sanity_scenario()
        if sid == "schema":
            return schema_scenario()
        if sid == "control":
            return control_scenario()
        if sid == "soak":
            return soak_scenario()
        for prefix, factory in (("ctx-", ctx_scenario), ("followup-", followup_scenario), ("repeat-", repeat_scenario)):
            if sid.startswith(prefix) and sid[len(prefix):] in DEPTH_CLASSES:
                return factory(sid[len(prefix):])
        if sid.startswith("parallel-") and sid[9:].isdigit() and 2 <= int(sid[9:]) <= 64:
            return parallel_scenario(int(sid[9:]))
        raise ValueError("unknown scenario %r (see `llmbench scenarios`)" % sid)

    # ----------------------------------------------------------------- plumbing

    def _nonce(self, *parts: object) -> str:
        # The random part leads, so two requests share no text beyond the chat template's
        # own opening and "[run ".
        return "-".join([os.urandom(4).hex(), self.salt] + [str(p) for p in parts])

    def _seed(self, *parts: object) -> int:
        return seed_from(self.seed, *(() if self.fixed_text else (self.salt,)), *parts)

    def _payload(self, messages: List[Dict[str, str]], max_tokens: int, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
        payload.update(self.extra_body)
        payload.update(extra or {})
        return payload

    def _count_tokens(self, messages: List[Dict[str, str]]) -> Tuple[Optional[int], float, Optional[int]]:
        """Ask the server how many prompt tokens a message list is (1-token completion).

        Returns (prompt tokens, seconds, cached prompt tokens when the server reports them).
        """
        try:
            status, body, elapsed = post_json(self.chat_url, self._payload(messages, 1), timeout=self.timeout, api_key=self.api_key)
        except EndpointError:
            return None, 0.0, None
        if status != 200 or not isinstance(body, dict):
            return None, elapsed, None
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        tokens = usage.get("prompt_tokens")
        details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        cached = details.get("cached_tokens")
        engine = normalize_engine({"timings": body.get("timings")}) or {}
        if not isinstance(cached, int) and engine.get("cache_n") is not None:
            cached = engine["cache_n"]
        return (tokens if isinstance(tokens, int) and tokens > 0 else None), elapsed, (cached if isinstance(cached, int) and cached >= 0 else None)

    def _corpus_for(self, spec: Dict[str, Any]) -> Corpus:
        kind = spec.get("corpus")
        if not kind:
            return self.corpus
        if kind not in self.corpora:
            self.corpora[kind] = Corpus(kind)
        return self.corpora[kind]

    def calibrate(self, corpus: Corpus) -> Dict[str, Any]:
        """Learn this model's characters-per-token for this corpus from two tiny probes.

        Tokenizers differ, so the same text is a different number of tokens on each model.
        Probing lets every model receive the same number of TOKENS rather than the same text.
        The second probe also shows how many tokens the runtime reuses between two requests
        that share nothing but the chat template: the baseline for the cache-hit rule.
        """
        key = corpus.key
        if key in self.calibration:
            return self.calibration[key]
        tiny = context_messages("", self._nonce("calibration", "a"))
        text, _ = corpus.build(12_000, self._seed("calibration", corpus.key))
        probe = context_messages(text, self._nonce("calibration", "b"))
        tokens_a, time_a, _ = self._count_tokens(tiny)
        tokens_b, time_b, cached_b = self._count_tokens(probe)
        calibration: Dict[str, Any] = {"corpus": corpus.kind, "source": "default", "chars_per_token": DEFAULT_CHARS_PER_TOKEN, "overhead_tokens": 30.0}
        ratio = None
        if tokens_a and tokens_b and tokens_b > tokens_a:
            ratio = (message_chars(probe) - message_chars(tiny)) / float(tokens_b - tokens_a)
        if ratio is not None and CHARS_PER_TOKEN_RANGE[0] <= ratio <= CHARS_PER_TOKEN_RANGE[1]:
            calibration.update({"source": "probe", "chars_per_token": ratio, "overhead_tokens": tokens_a - message_chars(tiny) / ratio, "probe_tokens": tokens_b})
            if time_b > time_a > 0:
                calibration["rough_prefill_tok_s"] = (tokens_b - tokens_a) / (time_b - time_a)
            if cached_b is not None:
                calibration["template_cached_tokens"] = cached_b
                self.cache_baseline = max(self.cache_baseline, cached_b)
        elif ratio is not None:
            self.notes.append("The server's token counts do not make sense (%.1f characters per token); prompt sizes use a default estimate." % ratio)
        else:
            self.notes.append("Could not read token counts from the server; prompt sizes use a default estimate.")
        self.calibration[key] = calibration
        return calibration

    def _context_prompt(self, corpus: Corpus, target_tokens: int, seed: int, nonce: str) -> Tuple[List[Dict[str, str]], Dict[str, Any], int]:
        cal = self.calibrate(corpus)
        shell = message_chars(context_messages("", nonce))
        corpus_chars = max(200, int((target_tokens - cal["overhead_tokens"]) * cal["chars_per_token"]) - shell)
        text, info = corpus.build(corpus_chars, seed)
        messages = context_messages(text, nonce)
        estimate = int(round(cal["overhead_tokens"] + message_chars(messages) / cal["chars_per_token"]))
        return messages, info, estimate

    def _learn(self, corpus: Corpus, messages: List[Dict[str, str]], run: Dict[str, Any]) -> None:
        """Refine the characters-per-token estimate from a real run, within bounds."""
        cal = self.calibration.get(corpus.key)
        tokens = run.get("prompt_tokens")
        if not cal or run.get("prompt_tokens_source") != "usage" or not tokens or "prompt-truncated" in run["flags"]:
            return
        body_tokens = tokens - cal["overhead_tokens"]
        if body_tokens > 200:
            current = cal["chars_per_token"]
            observed = message_chars(messages) / body_tokens
            # One run may move the estimate by a quarter at most, and never out of the
            # range real tokenizers occupy: a server whose count stopped following the
            # text must not make the prompts grow without limit.
            observed = min(max(observed, 0.75 * current, CHARS_PER_TOKEN_RANGE[0]), 1.25 * current, CHARS_PER_TOKEN_RANGE[1])
            cal["chars_per_token"] = 0.5 * current + 0.5 * observed
            cal["source"] = ("probe" if cal["source"].startswith("probe") else "default") + "+runs"

    def _pinned(self, key: str, messages: List[Dict[str, str]], run: Dict[str, Any]) -> None:
        """Two different texts that count as the same number of tokens were cut to a limit."""
        tokens, chars = run.get("prompt_tokens"), message_chars(messages)
        if run.get("prompt_tokens_source") != "usage" or not tokens:
            return
        before = self.last_size.get(key)
        self.last_size[key] = (tokens, chars)
        if before and abs(before[0] - tokens) <= 1 and abs(before[1] - chars) > 0.01 * chars and "prompt-truncated" not in run["flags"]:
            run["flags"].append("prompt-truncated")

    def _target(self, spec: Dict[str, Any]) -> int:
        return followup_target(spec["depth"]) if spec["kind"] == "followup" else depth_target(spec["depth"])

    def _fits(self, spec: Dict[str, Any]) -> Optional[str]:
        """Return a reason to skip a depth scenario, or None when it can run."""
        depth = spec.get("depth")
        if not depth:
            return None
        need = int(self._target(spec) * (1 + FIT_MARGIN)) + CONTEXT_OUTPUT_TOKENS
        if spec["kind"] == "followup":  # the second turn carries the first answer and a new question
            need += CONTEXT_OUTPUT_TOKENS + FOLLOWUP_QUESTION_TOKENS
        if self.context:
            if need > self.context and spec["kind"] != "sanity":
                return "needs a context window of about {:,} tokens; this run has {:,}".format(need, self.context)
            return None
        if DEPTH_CLASSES[depth] > DEPTH_CLASSES[DEPTH_WHEN_CONTEXT_UNKNOWN]:
            return "context window unknown; pass --context N (the size your runtime loaded the model with) to run this depth"
        return None

    def _estimate_seconds(self, calibration: Dict[str, Any], warm: Dict[str, Any]) -> Optional[float]:
        """Rough duration from the calibration probe (reading) and the warm-up (writing)."""
        reading, writing = calibration.get("rough_prefill_tok_s"), warm.get("decode_tok_s")
        if not reading or not writing:
            return None
        total = 0.0
        for spec in self.scenarios:
            if self._fits(spec):
                continue
            if spec["kind"] == "soak":
                total += float(spec.get("minutes") or 0) * 60.0
                continue
            reads = spec["runs"] + (1 if spec["kind"] == "context" and self.size_warmup else 0)
            read = self._target(spec) / reading if spec.get("depth") and spec["kind"] != "sanity" else 0.5
            write = (spec["max_tokens"] if spec["kind"] != "sanity" else 200) / writing
            total += reads * (read + write * (2 if spec["kind"] == "followup" else 1))
        return total

    # ---------------------------------------------------------------- scenarios

    def _token_size(self) -> Optional[float]:
        """Characters per token this model was measured at, once the probe has run."""
        calibration = self.calibration.get(self.corpus.key) or {}
        return calibration.get("chars_per_token") if calibration.get("source", "default") != "default" else None

    def _measure(self, messages: List[Dict[str, str]], max_tokens: int, extra: Optional[Dict[str, Any]] = None, **derive: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        log_mark = runtimes.engine_log_mark(self.engine_log) if self.engine_log else None
        sent_at = time.monotonic() - self.clock_zero
        stream = stream_chat(self.chat_url, self._payload(messages, max_tokens, extra), timeout=self.timeout, api_key=self.api_key)
        if log_mark is not None and not stream.get("error"):
            usage = stream.get("usage") or {}
            timings = runtimes.engine_log_timings(self.engine_log, log_mark, usage.get("prompt_tokens"), usage.get("completion_tokens"))
            if timings:
                stream["timings"] = timings
        derive.setdefault("cache_baseline", self.cache_baseline)
        run = derive_run(stream, max_tokens=max_tokens, context_tokens=self.context, chars_per_token=self._token_size(), **derive)
        if run.get("error"):
            run["error"] = _safe(run["error"])
        run["at_s"] = round(sent_at, 3)  # seconds since the suite started, to line runs up with telemetry
        return stream, run

    def _run_chat(self, spec: Dict[str, Any], index: int) -> Dict[str, Any]:
        nonce = self._nonce(spec["id"], index)
        messages = chat_messages(nonce, self._seed(spec["id"], index))
        _, run = self._measure(messages, spec["max_tokens"], expect_fresh=True)
        run["nonce"] = nonce
        return run

    def _run_context(self, spec: Dict[str, Any], index: int) -> Dict[str, Any]:
        corpus = self._corpus_for(spec)
        target = self._target(spec)
        nonce = self._nonce(spec["id"], index)
        messages, info, estimate = self._context_prompt(corpus, target, self._seed(spec["id"], index), nonce)
        _, run = self._measure(messages, spec["max_tokens"], expect_fresh=True, target_prompt_tokens=target, estimated_prompt_tokens=estimate, estimate_reliable=corpus.kind != "file")
        self._pinned(spec["id"], messages, run)
        self._learn(corpus, messages, run)
        run.update({"nonce": nonce, "workload": info, "target_prompt_tokens": target, "estimated_prompt_tokens": estimate, "prompt_chars": message_chars(messages)})
        return run

    def _run_followup(self, spec: Dict[str, Any], index: int) -> Dict[str, Any]:
        corpus = self._corpus_for(spec)
        target = self._target(spec)
        nonce = self._nonce(spec["id"], index)
        seed = self._seed(spec["id"], index)
        messages, info, estimate = self._context_prompt(corpus, target, seed, nonce)
        first_stream, first = self._measure(messages, spec["max_tokens"], expect_fresh=True, target_prompt_tokens=target, estimated_prompt_tokens=estimate, estimate_reliable=corpus.kind != "file")
        self._learn(corpus, messages, first)
        if not run_is_valid(first):
            first.update({"nonce": nonce, "workload": info, "flags": first["flags"] + ["first-turn-failed"]})
            if "error" not in first["flags"]:
                first["flags"].append("error")
                first["error"] = first.get("error") or "first turn was not a valid fresh read"
            return first
        second_messages = followup_messages(messages, first_stream.get("answer_text") or "", self._nonce(spec["id"], index, "b"), seed)
        _, run = self._measure(second_messages, spec["max_tokens"], expect_fresh=False, expect_cache=True)
        for flag in ("depth-miss", "context-overflow"):  # the first turn's size problems belong to the pair
            if flag in first["flags"] and flag not in run["flags"]:
                run["flags"].append(flag)
        run.update(
            {
                "nonce": nonce,
                "workload": info,
                "target_prompt_tokens": target,
                "prompt_chars": message_chars(second_messages),
                "first_turn": {key: first.get(key) for key in ("prompt_tokens", "ttft_s", "prefill_tok_s", "prefill_source", "decode_tok_s", "cached_tokens", "flags")},
            }
        )
        if first.get("ttft_s") and run.get("ttft_s"):
            run["cache_speedup"] = first["ttft_s"] / run["ttft_s"]
        return run

    def _run_sanity(self, spec: Dict[str, Any], index: int) -> Dict[str, Any]:
        check = SANITY_CHECKS[index]
        nonce = self._nonce(spec["id"], check)
        seed = self._seed(spec["id"], check)
        corpus_text = ""
        info: Optional[Dict[str, Any]] = None
        estimate = None
        if check == "needle":
            # As deep as the 4K class allows, smaller when the loaded window is tiny.
            target = depth_target("4k", reserve=spec["max_tokens"])
            if self.context:
                target = max(600, min(target, int(self.context * 0.9) - spec["max_tokens"]))
            cal = self.calibrate(self.corpus)
            corpus_text, info = self.corpus.build(max(400, int((target - cal["overhead_tokens"] - 120) * cal["chars_per_token"])), seed)
        messages, expectation = sanity_messages(check, nonce, seed, corpus_text)
        if check == "needle":
            cal = self.calibration[self.corpus.key]
            estimate = int(round(cal["overhead_tokens"] + message_chars(messages) / cal["chars_per_token"]))
        stream, run = self._measure(messages, spec["max_tokens"], expect_fresh=True, estimated_prompt_tokens=estimate, estimate_reliable=self.corpus.kind != "file")
        run["flags"] = [flag for flag in run["flags"] if flag not in ("short-output", "single-burst", "buffered-stream")]  # a short, correct answer is the point
        run.update({"nonce": nonce, "check": check, "passed": grade_sanity(stream.get("answer_text") or "", expectation) if not run.get("error") else None})
        if info:
            run["workload"] = info
        return run

    def _run_schema(self, spec: Dict[str, Any], index: int) -> Dict[str, Any]:
        """One catalogue copied into a JSON form, asked again (as a real caller would) when the
        answer does not fit. The timing is that of the first answer that came back."""
        form = schema_form()
        extra = {"response_format": {"type": "json_schema", "json_schema": {"name": "catalogue", "strict": True, "schema": form}}}
        nonce = self._nonce(spec["id"], index)
        messages = schema_messages(nonce, self._seed(spec["id"], index))
        statuses: List[str] = []
        problems: List[str] = []
        timed: Optional[Dict[str, Any]] = None
        last: Dict[str, Any] = {}
        for attempt in range(SCHEMA_RETRIES + 1):
            stream, run = self._measure(messages, spec["max_tokens"], extra=extra, expect_fresh=attempt == 0)
            status, found = schema_outcome(stream, form)
            statuses.append(status)
            problems += found[:3]
            last = run
            if timed is None and status != "refused":
                timed = run
            if status in ("fits", "error"):
                break  # done, or a failure that has nothing to do with the form
            said = "; ".join(found[:3]) or status
            if status != "refused" and stream.get("answer_text"):
                messages = messages + [{"role": "assistant", "content": stream["answer_text"]}]
            messages = messages + [{"role": "user", "content": "Your answer does not fit the form (%s). Answer again with only one JSON object that fits it." % _safe(said, 400)}]
        run = timed if timed is not None else last
        if timed is None and statuses[-1] == "refused":
            # Every answer came back and every one was refused by the server's own schema
            # check: that is this scenario's finding, not a failed request. No timing exists.
            run["error"] = None
            run["flags"] = [flag for flag in run["flags"] if flag != "error"]
        run["flags"] = [flag for flag in run["flags"] if flag not in ("short-output", "single-burst", "buffered-stream")]
        run.update({"nonce": nonce, "schema": {"first_try": statuses[0], "final": statuses[-1], "attempts": len(statuses), "problems": [_safe(p, 200) for p in problems[:5]]}})
        return run

    def _run_parallel(self, spec: Dict[str, Any], index: int) -> Dict[str, Any]:
        count = spec["parallel"]
        results: List[Optional[Dict[str, Any]]] = [None] * count
        sent: List[Optional[float]] = [None] * count
        ended: List[float] = [0.0] * count
        gate = threading.Barrier(count)

        def worker(slot: int) -> None:
            messages = chat_messages(self._nonce(spec["id"], index, slot), self._seed(spec["id"], index, slot))
            gate.wait()
            stream, results[slot] = self._measure(messages, spec["max_tokens"], expect_fresh=True)
            sent[slot] = stream.get("sent_at")  # taken after the connection was open
            ended[slot] = time.perf_counter()

        threads = [threading.Thread(target=worker, args=(slot,), daemon=True) for slot in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        streams = [r for r in results if r]
        good = [r for r in streams if run_is_valid(r)]
        flags: List[str] = []
        for request in streams:  # what was wrong with any request is wrong with the total
            for flag in request.get("flags") or []:
                if flag not in flags and flag != "error":
                    flags.append(flag)
        run: Dict[str, Any] = {"flags": flags, "error": None, "parallel": count, "requests_ok": len(good)}
        if len(good) < count:
            run["flags"].append("error")
            run["error"] = next((r.get("error") for r in streams if r.get("error")), "one or more parallel requests failed")
            return run
        tokens = sum(r.get("completion_tokens") or 0 for r in good)
        starts = [s for s in sent if s is not None]
        span = (max(ended) - min(starts)) if starts else None
        ttfts = [r["ttft_s"] for r in good if r.get("ttft_s") is not None]
        run.update(
            {
                "completion_tokens": tokens,
                "wall_s": span,
                "ttft_s": statistics.median(ttfts) if ttfts else None,
                "ttft_worst_s": max(ttfts) if ttfts else None,
                "decode_tok_s": tokens / span if span and span > 0 else None,  # total tokens per second across requests
                "decode_source": "aggregate",
                "per_request_decode_tok_s": [r.get("decode_tok_s") for r in good],
            }
        )
        return run

    # ---------------------------------------------------------------------- run

    def prepare(self) -> None:
        """Detect the runtime and pick the model. Raises EndpointError when unreachable."""
        self.runtime = runtimes.detect(self.root, api_key=self.api_key)
        if not self.runtime.get("reachable"):
            status = self.runtime.get("models_status")
            if not status:
                raise EndpointError("no server answered at %s (is the runtime running and the port right?)" % runtimes.endpoint_class(self.root))
            if not self.model:
                hint = " It may need a key: pass --api-key-env." if status in (401, 403) else ""
                raise EndpointError("the server answered HTTP %d when asked for its model list; pass --model with the name it expects.%s" % (status, hint))
            self.notes.append("The server did not list its models (HTTP %d); the model name was taken as given." % status)
        if self.model:
            self.model = runtimes.resolve_model(self.runtime, self.model)
        else:
            self.model = runtimes.choose_model(self.runtime)
            if not self.model:
                raise EndpointError(runtimes.model_choice_problem(self.runtime))
        if self.runtime.get("name") in runtimes.LOADS_ON_FIRST_REQUEST:
            self.loaded_before = self.model in (self.runtime.get("loaded_models") or [])

    def _load_note(self) -> Optional[str]:
        """Say so when the run itself made the runtime load the model.

        LM Studio and Ollama load a model on its first request, with their own default
        context window. The user then measures settings they did not choose.
        """
        if self.loaded_before is not False:
            return None
        context = " (context window {:,} tokens)".format(self.context) if self.context and self.context_source == "runtime" else ""
        return "the model was not loaded when the run started, so %s loaded it with its default settings%s. To choose the context window, load the model yourself before the run." % (
            runtimes.display_name(self.runtime.get("name")), context)

    def learn_runtime(self) -> None:
        """Read what the runtime reports once the model is loaded (after the warm-up).

        LM Studio and Ollama load a model on first use, so the context window it was
        actually loaded with is only visible at this point.
        """
        runtimes.refresh(self.root, self.runtime, api_key=self.api_key)
        runtimes.enrich_model(self.root, self.runtime, self.model or "", api_key=self.api_key)
        if not self.context and self.runtime.get("context_tokens"):
            self.context = int(self.runtime["context_tokens"])
            self.context_source = "runtime"

    def _stop_reason(self, error: Any, succeeded: bool) -> Optional[str]:
        """Why a scenario should stop and deeper ones be skipped, or None for an ordinary failure.

        Only a size rejection or a timeout says something about larger prompts, and only
        while nothing of this size has worked yet. A 429, a 500 or one slow request after
        good runs is a failed run and nothing more.
        """
        text = str(error or "")
        if succeeded or not text:
            return None
        if SIZE_REJECTION.search(text):
            return "the server rejected this prompt size: %s" % text[:200]
        if TIMED_OUT.search(text):
            return "the server did not answer within %d s at this prompt size" % self.timeout
        return None

    def run(self) -> Dict[str, Any]:
        self.started = dt.datetime.now(dt.timezone.utc)
        self.prepare()
        self.system = sysinfo.capture_system()
        self.state_before = sysinfo.capture_state()
        self.warnings = sysinfo.preflight_warnings(self.system, self.state_before)
        emit = self.emit
        emit("llmbench %s | suite %s | protocol %s" % (__version__, self.suite_name, PROTOCOL_VERSION))
        emit("System : %s" % sysinfo.describe(self.system))
        for warning in self.warnings:
            emit("WARNING: %s" % warning)

        # Warm-up: loads the model if needed and is never counted in a scenario.
        warm_messages = chat_messages(self._nonce("warmup"), self._seed("warmup"))
        _, warm = self._measure(warm_messages, 32, expect_fresh=True)
        if warm.get("error") and "no generated text" in str(warm["error"]):
            # A model that thinks without showing it can spend 32 tokens and show nothing.
            self.notes.append("The warm-up request returned no visible text. If the model thinks without showing it, try --thinking off.")
            emit("Note   : the warm-up request returned no visible text; continuing")
        elif warm.get("error"):
            raise EndpointError("warm-up request failed: %s" % warm["error"])
        self.warm = warm
        self.learn_runtime()
        engine = self.runtime.get("engine")
        emit("Runtime: %s%s%s | model %s | context %s" % (
            runtimes.display_name(self.runtime.get("name")), (" " + _safe(self.runtime["version"])) if self.runtime.get("version") else "",
            (" (%s%s)" % (_safe(engine), (" " + _safe(self.runtime["engine_version"])) if self.runtime.get("engine_version") else "")) if engine else "",
            _safe(runtimes.public_model_id(self.model)), ("{:,} ({})".format(self.context, self.context_source)) if self.context else "unknown"))
        emit("Warm-up: first token after %.2f s%s" % (warm.get("ttft_s") or 0.0, " (cold start as declared)" if self.cold else ""))
        load_note = self._load_note()
        if load_note:
            self.notes.append(load_note[0].upper() + load_note[1:])
            emit("Note   : " + load_note)
        calibration = self.calibrate(self.corpus)
        emit("Workload: %s corpus, %.2f characters per token for this model (%s)" % (self.corpus.kind, calibration["chars_per_token"], calibration["source"]))
        estimate = self._estimate_seconds(calibration, warm)
        if estimate and estimate >= 90:
            emit("Estimated time: about %d minutes (Ctrl+C keeps the runs finished so far)" % max(2, round(estimate / 60.0)))

        sampler = sysinfo.GpuSampler()
        records: List[Dict[str, Any]] = []
        aborted = False
        blocked_depth: Optional[int] = None
        blocked_by = ""
        try:
            for spec in self.scenarios:
                record: Dict[str, Any] = dict(spec)
                record["runs"] = []
                record["planned_runs"] = spec["runs"]
                records.append(record)
                reason = self._fits(spec)
                if not reason and blocked_depth and spec.get("depth") and spec["kind"] != "sanity" and DEPTH_CLASSES[spec["depth"]] >= blocked_depth:
                    reason = "not run: %s" % blocked_by
                    record["blocked"] = True
                if reason:
                    record["skipped"] = reason
                    emit("%-14s skipped: %s" % (spec["id"], reason))
                    continue
                runner = {
                    "chat": self._run_chat, "context": self._run_context, "followup": self._run_followup,
                    "parallel": self._run_parallel, "soak": self._run_context, "sanity": self._run_sanity,
                    "schema": self._run_schema,
                }[spec["kind"]]
                sampler.start()
                try:
                    succeeded = False
                    stop: Optional[str] = None
                    if spec["kind"] == "context" and self.size_warmup:
                        # The first request at a new prompt size is slower on every engine tried
                        # (buffers, kernels, clocks). Make it once, report it, keep it out of
                        # the medians.
                        first = runner(spec, -1)
                        record["first_run"] = first
                        emit(self._run_line(spec, -1, first))
                        succeeded = run_is_valid(first)
                        stop = self._stop_reason(first.get("error"), succeeded)
                    soak_until = time.monotonic() + float(spec.get("minutes") or 0) * 60.0
                    index = failures = 0
                    while not stop:
                        if spec["kind"] == "soak":  # loop by the clock, at least three times
                            if index >= SOAK_MIN_LOOPS and time.monotonic() >= soak_until:
                                break
                            if index >= SOAK_MAX_LOOPS:
                                record["ended_early"] = "stopped after %d loops, before the requested time was up" % SOAK_MAX_LOOPS
                                break
                        elif index >= spec["runs"]:
                            break
                        run = runner(spec, index)
                        record["runs"].append(run)
                        emit(self._run_line(spec, index, run))
                        index += 1
                        if run_is_valid(run):
                            succeeded, failures = True, 0
                        elif run.get("error"):
                            failures += 1
                            stop = self._stop_reason(run["error"], succeeded)
                            if not stop and failures >= 3 and spec["kind"] == "soak":
                                stop = "three requests in a row failed"
                    if stop:
                        record["stopped"] = stop
                        if not succeeded:
                            # Nothing of this size ever worked: the scenario was not measurable
                            # here, which is a fact about the setup, not a failed measurement.
                            record["skipped"] = stop
                        if not succeeded and spec.get("depth") and spec["kind"] != "sanity":
                            blocked_depth = min(blocked_depth or 10**9, DEPTH_CLASSES[spec["depth"]])
                            blocked_by = "%s at %s (%s)" % ("the server gave no answer in time" if TIMED_OUT.search(stop) else "the server rejected the prompt", spec["depth"].upper(), spec["id"])
                finally:
                    gpu = sampler.stop()
                if gpu:
                    record["gpu"] = gpu
                self._close_record(record)
                if self.checkpoint:
                    # Finished scenarios are handed over at once, so a crash or a power cut
                    # during a 20-minute deep run cannot take the earlier results with it.
                    self.checkpoint(self.result([r for r in records if "summary" in r or "skipped" in r], partial=True))
        except KeyboardInterrupt:
            aborted = True
            emit("Interrupted: writing the runs completed so far.")
        for record in records:
            if "summary" not in record:
                self._close_record(record)
        return self.result(records, aborted=aborted)

    def _close_record(self, record: Dict[str, Any]) -> None:
        record["summary"] = summarize_runs(record["runs"])
        if record.get("first_run") is not None:
            record["summary"]["first_run"] = first_run_summary(record["first_run"], record["summary"])
        if record["kind"] == "soak":
            record["summary"]["stability"] = soak_stability(record["runs"])
        if record["kind"] == "sanity":
            record["summary"].update(sanity_summary(record["runs"]))
        if record["kind"] == "schema":
            record["summary"]["schema"] = schema_summary(record["runs"])
        if record["kind"] == "parallel":
            worst = [r["ttft_worst_s"] for r in record["runs"] if run_is_valid(r) and r.get("ttft_worst_s") is not None]
            if worst:
                record["summary"]["ttft_worst_s"] = max(worst)

    def result(self, records: List[Dict[str, Any]], aborted: bool = False, partial: bool = False) -> Dict[str, Any]:
        """Assemble the result file. A checkpoint is the same thing with ``partial`` set."""
        started = self.started or dt.datetime.now(dt.timezone.utc)
        state_after: Dict[str, Any] = {}
        if not partial:
            try:
                state_after = sysinfo.capture_state()
            except KeyboardInterrupt:  # a second Ctrl+C must not cost the result
                state_after = {}
        temperature = self.extra_body.get("temperature", 0)
        result: Dict[str, Any] = {
            "schema": RESULT_SCHEMA,
            "tool": {"name": "llmbench", "version": __version__, "protocol": PROTOCOL_VERSION, "workload": WORKLOAD_VERSION},
            "created_utc": started.isoformat(timespec="seconds"),
            "duration_s": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
            "label": self.label,
            "suite": self.suite_name,
            "aborted": aborted,
            "system": self.system,
            "state_before": self.state_before,
            "state_after": state_after,
            "preflight_warnings": self.warnings,
            "runtime": dict(
                {key: value for key, value in self.runtime.items() if key not in ("models", "reachable", "loaded_models", "lmstudio_models", "ollama_running", "models_status")},
                loaded_models=[runtimes.public_model_id(m) for m in self.runtime.get("loaded_models") or []],
            ),
            "model": {"id": runtimes.public_model_id(self.model), "details": self.runtime.get("model_details")},
            "settings": {
                "temperature": temperature if isinstance(temperature, (int, float)) else 0,
                "context_tokens": self.context,
                "context_source": self.context_source,
                "corpus": self.corpus.kind,
                "seed": self.seed,
                "text_salt": None if self.fixed_text else self.salt,
                "scenario_ids": [spec["id"] for spec in self.scenarios],
                "custom_selection": self.custom_selection,
                "extra_body": self.extra_body or None,
                "endpoint": runtimes.endpoint_class(self.root),
                "declared_cold_start": self.cold,
                "thinking": self.thinking,
                "size_warmup": self.size_warmup,
                "engine_log_used": bool(self.engine_log),
            },
            "warmup": {key: self.warm.get(key) for key in ("ttft_s", "wall_s", "prompt_tokens", "completion_tokens", "flags")},
            "calibration": self.calibration,
            "scenarios": records,
            "notes": list(self.notes),
        }
        if partial:
            result["partial"] = True
        result["headline"] = headline(result)
        result["verdict"] = verdict(result)
        return tidy(result)

    def _run_line(self, spec: Dict[str, Any], index: int, run: Dict[str, Any]) -> str:
        from .report import flag_label

        if index < 0:
            prefix = "%-14s first read at this size (not counted)" % spec["id"]
        elif spec["kind"] == "soak":
            prefix = "%-14s loop %d" % (spec["id"], index + 1)
        elif spec["kind"] == "sanity":
            prefix = "%-14s %-10s" % (spec["id"], run.get("check"))
        elif spec["kind"] == "schema":
            prefix = "%-14s run %d/%d  %s" % (spec["id"], index + 1, spec["runs"], schema_line(run.get("schema") or {}))
        else:
            prefix = "%-14s run %d/%d" % (spec["id"], index + 1, spec["runs"])
        if run.get("error"):
            return "%s  FAILED: %s" % (prefix, str(run["error"])[:160])
        parts = [prefix]
        if spec["kind"] == "sanity":
            parts.append({True: "passed", False: "FAILED", None: "no answer text (inconclusive)"}[run.get("passed")])
        if run.get("prompt_tokens"):
            parts.append("prompt {:,} tok".format(run["prompt_tokens"]))
        if run.get("cached_tokens") and run.get("prompt_tokens") and run["cached_tokens"] >= max(64, 0.05 * run["prompt_tokens"]):
            parts.append("cached {:,}".format(run["cached_tokens"]))
        if run.get("ttft_s") is not None:
            parts.append("first token %.2f s" % run["ttft_s"])
        if run.get("prefill_tok_s"):
            parts.append("read %s tok/s" % _fmt(run["prefill_tok_s"], 0))
        if run.get("decode_tok_s"):
            parts.append("write %s tok/s" % _fmt(run["decode_tok_s"]))
        if run.get("flags"):
            parts.append("[%s]" % ", ".join(flag_label(flag) for flag in run["flags"]))
        return "  ".join(parts)


# ------------------------------------------------------------------------ headline


def _median(record: Optional[Dict[str, Any]], metric: str) -> Optional[float]:
    stats = ((record or {}).get("summary") or {}).get(metric)
    return stats.get("median") if stats else None


def _usable(record: Dict[str, Any]) -> bool:
    """A scenario the headline may quote: it ran to its end and has valid runs."""
    return not record.get("skipped") and not record.get("stopped") and bool((record.get("summary") or {}).get("runs_valid"))


def _find(result: Dict[str, Any], sid: str) -> Optional[Dict[str, Any]]:
    for record in result.get("scenarios") or []:
        if record.get("id") == sid and _usable(record):
            return record
    return None


def headline(result: Dict[str, Any]) -> Dict[str, Any]:
    """The few numbers a newcomer should read first.

    The request times are the physically meaningful ones: seconds until a typical request
    is finished, built from measured time to first token and measured writing speed.
    """
    out: Dict[str, Any] = {}
    chat, gen = _find(result, "chat"), _find(result, "gen-long")
    writer = gen if (gen and _median(gen, "decode_tok_s")) else chat
    out["chat_first_token_s"] = _median(chat, "ttft_s")
    out["writing_tok_s"] = _median(writer, "decode_tok_s")
    out["writing_source"] = (writer or {}).get("summary", {}).get("decode_source") if writer else None
    reads = [r for r in result.get("scenarios") or [] if r.get("kind") == "context" and not r.get("corpus") and _usable(r)]
    reading: Dict[str, Any] = {}
    reading_text: Dict[str, Any] = {}
    points = []
    for record in reads:
        if _median(record, "prefill_tok_s"):
            reading[record["depth"]] = _median(record, "prefill_tok_s")
            # The same reading speed in characters. A token is a different amount of text for
            # each model (3.1 to 4.2 characters in the v1 data), so tok/s cannot rank two models.
            rates = [
                r["prefill_tok_s"] * r["prompt_chars"] / r["prompt_tokens"]
                for r in record.get("runs") or []
                if run_is_valid(r) and r.get("prefill_tok_s") and r.get("prompt_chars") and r.get("prompt_tokens")
            ]
            if rates:
                reading_text[record["depth"]] = statistics.median(rates)
        tokens, seconds = _median(record, "fresh_prompt_tokens") or _median(record, "prompt_tokens"), _median(record, "ttft_s")
        if tokens and seconds:
            points.append((record["depth"], tokens, seconds))
    out["reading_tok_s"] = reading
    if reading_text:
        out["reading_chars_s"] = reading_text
    # Extra tokens divided by extra seconds between two prompt sizes: the wait every request
    # pays whatever its size drops out, and no model of the engine is assumed.
    points.sort(key=lambda point: point[1])
    steps = []
    for (label_a, tokens_a, seconds_a), (label_b, tokens_b, seconds_b) in zip(points, points[1:]):
        if tokens_b > 1.2 * tokens_a and seconds_b > seconds_a:
            steps.append({"from": label_a, "to": label_b, "tok_s": (tokens_b - tokens_a) / (seconds_b - seconds_a)})
    if steps:
        out["reading_steps"] = steps
    fit = fit_reading([(tokens, seconds) for _, tokens, seconds in points])
    if fit:
        out["reading_fit"] = fit
    times: Dict[str, Any] = {}
    if chat:
        times["quick_question_300_out"] = request_time(_median(chat, "ttft_s"), _median(chat, "decode_tok_s"), 300)
    for depth, key, output in (("16k", "code_review_16k_in_500_out", 500), ("64k", "big_read_64k_in_1000_out", 1000)):
        record = _find(result, "ctx-%s" % depth)
        if record:
            times[key] = request_time(_median(record, "ttft_s"), _median(record, "decode_tok_s"), output)
    follow = _find(result, "followup-16k")
    if follow:
        times["followup_16k_500_out"] = request_time(_median(follow, "ttft_s"), _median(follow, "decode_tok_s"), 500)
        speedups = [r.get("cache_speedup") for r in follow["runs"] if run_is_valid(r) and r.get("cache_speedup")]
        if speedups:
            out["cache_speedup"] = statistics.median(speedups)
        cached, prompt = _median(follow, "cached_tokens"), _median(follow, "prompt_tokens")
        out["followup_cached_share"] = (cached / prompt) if (cached is not None and prompt) else None
    out["request_seconds"] = {key: value for key, value in times.items() if value is not None}
    control = _find(result, "control")
    if chat and control:
        start, end = _median(chat, "decode_tok_s"), _median(control, "decode_tok_s")
        if start and end:
            out["drift"] = {"writing_start_tok_s": start, "writing_end_tok_s": end, "ratio": end / start}
    plain, repeated = _find(result, "ctx-16k"), _find(result, "repeat-16k")
    if plain and repeated:
        sensitivity = {}
        for metric in ("prefill_tok_s", "decode_tok_s"):
            a, b = _median(plain, metric), _median(repeated, metric)
            if a and b:
                sensitivity[metric] = b / a
        out["repetition_speedup"] = sensitivity
    return out


FLAG_TEXT = (
    ("cache-hit", "the runtime reused cached prompt tokens in a run that was meant to be fresh"),
    ("prompt-truncated", "the runtime shortened the prompt without saying so (context window too small?)"),
    ("error", "a request failed"),
    ("no-token-counts", "the server sent neither token counts nor a usable stream"),
    ("stream-incomplete", "the reply ended without a finish marker: the connection was cut or the server stopped"),
    ("no-cache-reuse", "the follow-up turn did not reuse the cached context"),
    ("cache-unknown", "the runtime does not say how much of the follow-up prompt came from its cache, so no reading speed is given for that turn"),
    ("short-output", "the model stopped before the output cap, so runs wrote different amounts"),
    ("single-burst", "the reply arrived all at once, so writing could not be timed and no reading speed is given"),
    ("buffered-stream", "text arrived several tokens at a time (a buffered stream, a relay or a proxy) and there is no engine figure to check against; writing speed is an estimate"),
    ("no-usage", "the server sent no token counts; numbers are estimates"),
    ("usage-undercount", "the server counted fewer tokens than it streamed; the stream was used"),
    ("depth-miss", "the prompt size missed its target by more than 5%"),
    ("context-overflow", "prompt plus output exceeded the context window"),
    ("reasoning-only", "the model only produced thinking within the output cap (speeds are still valid)"),
    ("hidden-tokens", "the server counted tokens that never appeared in the stream (often suppressed thinking); the wait for the first token includes writing them"),
    ("client-engine-mismatch", "client-side and engine-side writing speed differ by more than 15%; the engine figure is reported"),
    ("malformed-events", "some stream events could not be read; a token may be missing from the timings"),
    ("slow-connect", "opening the connection took more than 50 ms each time (not counted in the timings); if the address says localhost, use 127.0.0.1"),
)
INVALIDATING = ("cache-hit", "prompt-truncated", "error", "no-token-counts", "stream-incomplete")


def verdict(result: Dict[str, Any]) -> Dict[str, Any]:
    """Is this result trustworthy enough to compare with another one?

    invalid               a scenario that was attempted produced no usable run, nothing
                          was measured at all, or the run was interrupted
    usable with cautions  numbers exist, but something below may explain a difference
    clean                 nothing to report
    """
    problems: List[str] = []
    cautions: List[str] = []
    measured = 0
    blocked: List[str] = []
    for record in result.get("scenarios") or []:
        sid = record["id"]
        if not _attempted(record):
            if record.get("blocked"):
                blocked.append(sid)
            continue  # skipped before any request was sent: nothing to judge
        summary = record.get("summary") or {}
        flags = summary.get("flags") or {}
        total, valid = summary.get("runs_total", 0), summary.get("runs_valid", 0)
        if record.get("skipped") and record.get("stopped") and not valid:
            cautions.append("%s: not measured: %s. The context window is smaller than this prompt, or the server is too slow at this size" % (sid, record["stopped"]))
            continue
        measured += valid
        if not valid:
            problems.append("%s: no usable runs%s" % (sid, (" (%s)" % record["stopped"]) if record.get("stopped") else ""))
        else:
            if record.get("stopped"):
                cautions.append("%s: ended early: %s" % (sid, record["stopped"]))
            if valid < total:
                cautions.append("%s: %d of %d runs were unusable and are excluded from the medians" % (sid, total - valid, total))
            if valid == 1 and record.get("planned_runs", 1) > 1 and record.get("kind") not in ("sanity", "soak"):
                cautions.append("%s: the figures rest on a single run" % sid)
        if record.get("ended_early"):
            cautions.append("%s: %s" % (sid, record["ended_early"]))
        for flag, text in FLAG_TEXT:
            if flags.get(flag):
                (problems if (flag in INVALIDATING and not valid) else cautions).append("%s: %s" % (sid, text))
        for metric, name in (("decode_tok_s", "writing speed"), ("prefill_tok_s", "reading speed"), ("ttft_s", "time to first token")):
            # Sanity checks are three different questions and a soak is judged by its own
            # stability ratio, so run-to-run spread means nothing for either.
            label = stability(summary.get(metric), metric) if record.get("kind") not in ("sanity", "soak") else "n/a"
            if label in ("noisy", "unstable"):
                cautions.append("%s: %s varied by +/-%.0f%% between runs (%s)" % (sid, name, summary[metric].get("spread_pct", 0.0), label))
        gpu = record.get("gpu") or {}
        if (gpu.get("temperature_c") or {}).get("max", 0) >= 87:
            cautions.append("%s: GPU reached %.0f C, thermal throttling is likely" % (sid, gpu["temperature_c"]["max"]))
        for name, stats in (summary.get("stability") or {}).items():
            if isinstance(stats, dict) and stats.get("ratio") is not None and stats["ratio"] < SOAK_STABLE_RATIO:
                cautions.append("%s: %s speed fell to %.0f%% of its best loop (throttling or background load)" % (sid, name, stats["ratio"] * 100))
        if summary.get("checks_failed"):
            cautions.append("%s: failed %s. The model may not be receiving the whole prompt, or it answers unreliably at these settings" % (sid, ", ".join(summary["checks_failed"])))
        if summary.get("checks_inconclusive"):
            cautions.append("%s: no answer text for %s within the output cap (thinking used it up)" % (sid, ", ".join(str(c) for c in summary["checks_inconclusive"])))
        if summary.get("checks_errored"):
            cautions.append("%s: the request for %s failed, so that check says nothing" % (sid, ", ".join(str(c) for c in summary["checks_errored"])))
        shape = summary.get("schema") or {}
        if shape.get("held_to_form") is False:
            broken = sum(count for status, count in (shape.get("first_try") or {}).items() if status in SCHEMA_BROKEN)
            cautions.append(
                "%s: %d of %d first answers did not fit the JSON schema (%s); this server does not hold the model to the schema, "
                "so callers must validate and ask again (%d of %d fit after up to %d retries)" % (
                    sid, broken, shape.get("requests", 0), ", ".join("%s %d" % item for item in sorted((shape.get("first_try") or {}).items())),
                    shape.get("fit_in_the_end", 0), shape.get("requests", 0), SCHEMA_RETRIES))
        elif shape.get("requests") and shape.get("held_to_form") is None:
            cautions.append("%s: no answer could be judged against the schema (failed requests, or thinking used the output cap)" % sid)
        if any((run.get("workload") or {}).get("wrapped") for run in record.get("runs") or []):
            cautions.append("%s: the corpus is smaller than the prompt, so its text repeats inside it (this flatters engines that speed up on repeated text)" % sid)
    if blocked:
        cautions.append("%s: not run, because a smaller prompt was rejected or got no answer in time" % ", ".join(blocked))
    if not measured and not result.get("partial"):
        problems.append("nothing was measured")
    runs = [run for record in result.get("scenarios") or [] for run in record.get("runs") or [] if run_is_valid(run) and "reasoning_seen" in run]
    if (result.get("settings") or {}).get("thinking") == "off" and runs:
        thought = sum(1 for run in runs if run.get("reasoning_seen") or run.get("hidden_tokens"))
        if thought:
            cautions.append("thinking was asked to be off, but the model still produced it in %d of %d runs" % (thought, len(runs)))
    before, after = result.get("state_before") or {}, result.get("state_after") or {}
    if isinstance(before.get("swap_used_mb"), (int, float)) and isinstance(after.get("swap_used_mb"), (int, float)) and after["swap_used_mb"] - before["swap_used_mb"] > 256:
        cautions.append("swap use grew by %.1f GB during the run: the model does not fit comfortably in memory" % ((after["swap_used_mb"] - before["swap_used_mb"]) / 1024))
    shared_before, shared_after = before.get("gpu_shared_memory_mb"), after.get("gpu_shared_memory_mb")
    if isinstance(shared_before, (int, float)) and isinstance(shared_after, (int, float)) and shared_after - shared_before > 512:
        cautions.append("shared GPU memory grew by %.1f GB during the run: the model is spilling out of VRAM into system RAM (Windows sysmem fallback)" % ((shared_after - shared_before) / 1024))
    drift = (result.get("headline") or {}).get("drift") or {}
    if drift.get("ratio") and abs(drift["ratio"] - 1.0) > DRIFT_TOLERANCE:
        cautions.append("writing speed at the end of the run was %.0f%% of the start (%.1f vs %.1f tok/s): heat, background load or the runtime changed state" % (drift["ratio"] * 100, drift["writing_end_tok_s"], drift["writing_start_tok_s"]))
    if result.get("preflight_warnings"):
        cautions.extend(result["preflight_warnings"])
    if result.get("aborted"):
        problems.append("the run was interrupted")
    status = "invalid" if problems else ("usable with cautions" if cautions else "clean")
    if result.get("partial"):
        status = "unfinished"
    return {"status": status, "problems": problems, "cautions": cautions}


def default_output_path(result: Dict[str, Any], folder: str = "local-results") -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return os.path.join(folder, "%s_%s_%s_%s.json" % (stamp, _slug(str((result.get("runtime") or {}).get("name") or "runtime")), _slug(str(result["model"]["id"])), result["suite"]))
