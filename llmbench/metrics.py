"""Metric definitions, validity flags and noise-aware comparison.

Definitions (protocol 2.0)

ttft_s      Request sent -> first generated token of ANY kind (thinking or answer).
            Comparable between thinking and non-thinking models. Opening the connection
            is not part of it.
ttfa_s      Request sent -> first answer text. Equals ttft_s when the model does not think.
prefill     Prompt tokens actually processed (cached tokens excluded) per second.
            Engine-reported when the runtime exposes it. Otherwise a client estimate:
            fresh tokens / (ttft_s minus the time spent writing what arrived first).
            It still includes HTTP and templating overhead and is labelled "client". When
            the fresh-token count or that writing time cannot be known, no figure is given.
decode      Generated tokens per second after the first token. Engine-reported when
            available, else a client estimate that stays unbiased when text arrives
            several tokens at a time (see client_decode_rate).
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional, Sequence

# Flags that make a run unusable for its scenario's primary numbers.
INVALIDATING_FLAGS = {"error", "cache-hit", "prompt-truncated", "no-token-counts", "stream-incomplete"}

MIN_PREFILL_TOKENS = 512  # below this, fresh_tokens / ttft is mostly fixed overhead
CACHE_HIT_FRACTION = 0.02
DEPTH_TOLERANCE = 0.05
TRUNCATION_FRACTION = 0.80
SHORT_OUTPUT_FRACTION = 0.90
EVENT_TOKEN_FACTOR = 1.75        # an event with at most this many tokens' worth of text is one token
TYPICAL_CHARS_PER_TOKEN = 4.0    # used only when the model's own figure is unknown
ENGINE_MISMATCH = 0.15           # client and engine writing speed should agree within 15%
MAX_WRITING_SHARE_OF_TTFT = 0.8  # beyond this, too little of the wait is left to call it reading time
BURSTY_ARRIVAL = 0.5             # fewer separate arrivals than this share of the events: the text came in bursts
ENOUGH_ARRIVALS = 32             # with this many arrivals, burst edges move the rate by about 3% at most
SLOW_CONNECT_S = 0.05            # opening a local connection takes well under a millisecond
MAX_FIRST_SHARE = 0.8            # more of the text than this in the first arrival leaves too little to time
MISSING_TOKENS = 0.02            # events may fall this far short of the token count and still be "one per token"


def _number(value: Any, minimum: float = 0.0) -> Optional[float]:
    """A finite number above ``minimum``, or None. Servers send NaN, nulls and strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= minimum:
        return None
    return float(value)


def _count(value: Any) -> Optional[int]:
    """A finite, non-negative whole number, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return int(value)


def summarize(values: Sequence[Optional[float]]) -> Optional[Dict[str, float]]:
    data = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not data:
        return None
    median = statistics.median(data)
    out = {
        "n": len(data),
        "median": median,
        "min": min(data),
        "max": max(data),
        "mean": statistics.fmean(data),
    }
    if len(data) > 1:
        out["stdev"] = statistics.stdev(data)
        out["cv_pct"] = (out["stdev"] / out["mean"] * 100.0) if out["mean"] else 0.0
        out["spread_pct"] = ((out["max"] - out["min"]) / 2.0 / median * 100.0) if median else 0.0
    return out


def client_decode_rate(
    completion_tokens: Optional[int],
    text_events: int,
    first_event_chars: int,
    total_chars: int,
    window_s: Optional[float],
    hidden_tokens: int = 0,
    chars_per_token: Optional[float] = None,
    assume: Optional[str] = None,
    bursts: Optional[int] = None,
    first_burst_events: int = 1,
) -> Dict[str, Any]:
    """Estimate decode speed from the client side of a stream.

    The window runs from the first text to the last. Tokens that arrived at the very start
    were generated before the window opened, so they are excluded:

        tokens_in_window = N * (1 - share of the output that arrived first)

    With one token per event this is N - 1 tokens over N - 1 intervals. With a server that
    flushes k tokens at a time it is N - k tokens over the time it took to produce them.
    The v1 scripts divided all N tokens by the window, which overstates speed by k/(N-k):
    about 1% for per-token streams and far more for buffered ones.

    "Arrived first" is judged by arrival, not by how the server framed its events. A relay
    or a proxy can deliver sixteen one-token events in one packet; they are one burst, and
    ``first_event_chars`` and ``first_burst_events`` describe the first burst. ``bursts`` is
    how many separate arrivals there were (default: one per event).

    Fewer events than tokens has three possible causes:

    buffered    every counted token is in the stream, several per event;
    fat first   one token per event, except a first arrival that carries many;
    hidden      the server counted tokens it never streamed, typically suppressed thinking
                written before the first event.

    ``hidden_tokens`` is what the server itself declares (reasoning tokens in the usage
    details when no reasoning was streamed). Beyond that the stream's shape decides: events
    that each carry about one token's worth of text mean the missing tokens came before
    the window. That is a judgement, so the result names its reading and offers the other
    one as ``alternative_tok_s``; the caller can settle it against an engine figure.
    ``assume`` ("hidden" or "buffered") forces one reading.

    Without a token count the events are counted when they look like single tokens, and
    the text length is used otherwise. ``tokens`` and ``token_source`` say what was used.
    """
    result: Dict[str, Any] = {
        "decode_tok_s": None, "stream_granularity": None, "tokens_in_window": None, "note": None,
        "hidden_tokens": 0, "hidden_source": None, "alternative_tok_s": None, "reading": None,
        "tokens": None, "token_source": "usage", "undercount": False,
    }
    events = int(text_events or 0)
    token_size = chars_per_token or TYPICAL_CHARS_PER_TOKEN
    one_token = EVENT_TOKEN_FACTOR * token_size
    mean_event = (total_chars / events) if events and total_chars > 0 else 0.0
    tokens = completion_tokens if completion_tokens else None
    if tokens is None:
        if events < 1:
            result["note"] = "no token count and no text"
            return result
        if mean_event <= one_token:
            tokens, result["token_source"] = events, "event-count"  # each event looks like one token
        else:
            tokens, result["token_source"] = max(events, int(round(total_chars / token_size))), "character-estimate"
    elif events > 1.1 * tokens + 2:
        # More text events than tokens cannot happen in a per-token stream: the server's
        # count leaves something out (for example thinking it streamed but did not count).
        tokens, result["token_source"], result["undercount"] = events, "event-count", True
    result["tokens"] = tokens

    arrivals = min(events, bursts) if bursts else events
    first_events = min(max(1, int(first_burst_events or 1)), max(1, events))
    declared = max(0, min(int(hidden_tokens or 0), tokens - 1))
    streamed = tokens - declared
    if declared:
        result["hidden_tokens"], result["hidden_source"] = declared, "usage"
    result["stream_granularity"] = round(arrivals / streamed, 3) if streamed else None
    if arrivals < 2 or not window_s or window_s <= 0:
        result["note"] = "all text arrived at once; client decode rate is undefined"
        return result

    event_share = first_events / float(events)
    char_share = min(max(first_event_chars / total_chars, 0.0), 1.0) if total_chars > 0 else event_share
    missing = streamed - events
    alternative = None
    if missing <= max(2.0, MISSING_TOKENS * streamed) or total_chars <= 0:
        # Events are tokens. They may still have arrived in bursts, or behind a fat first event.
        fat_first = total_chars > 0 and char_share > 3.0 * event_share and first_event_chars > 3.0 * mean_event
        share = char_share if fat_first else event_share
        # Bursts matter only when there are few: the window then opens and closes on coarse
        # edges. A busy client or a scheduler hiccup also groups arrivals, harmlessly.
        bursty = arrivals < BURSTY_ARRIVAL * events and arrivals < ENOUGH_ARRIVALS
        reading = "fat-first" if fat_first else ("bursts" if bursty else "per-token")
        in_window = streamed * (1.0 - share)
    else:
        if assume in ("hidden", "buffered"):
            reading = assume
        else:
            reading = "hidden" if mean_event <= one_token else "buffered"
        if reading == "hidden":
            # One token per event, and the missing ones came before the window opened:
            # inside a first arrival big enough to hold them, or never streamed at all.
            share = event_share
            in_window = float(events - first_events)
            alternative = streamed * (1.0 - char_share)
            if assume != "hidden" and first_event_chars >= 0.5 * (missing + first_events) * mean_event:
                reading = "fat-first"
            else:
                result["hidden_tokens"] = declared + int(missing)
                result["hidden_source"] = "usage+stream" if declared else "stream"
        else:
            share = char_share
            in_window = streamed * (1.0 - char_share)
            alternative = float(events - first_events)
    result["reading"] = reading
    if share > MAX_FIRST_SHARE or in_window < 2.0:
        result["note"] = "nearly all text arrived at once; too little is left to time"
        return result
    result["tokens_in_window"] = round(in_window, 2)
    result["decode_tok_s"] = in_window / window_s
    if alternative is not None and alternative >= 2.0:
        result["alternative_tok_s"] = alternative / window_s
    return result


def normalize_engine(stream: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull engine-side timings out of whatever the runtime attached to the stream.

    llama.cpp (and servers that copy its convention) attach a ``timings`` object:
    prompt_n / prompt_ms cover prompt tokens actually evaluated (cache excluded),
    predicted_n / predicted_ms cover generation, cache_n counts reused tokens. Numbers
    that are missing, non-finite or not positive are ignored, never passed on.
    """
    timings = stream.get("timings")
    if isinstance(timings, dict) and (_number(timings.get("predicted_ms")) or _number(timings.get("prompt_ms"))):
        engine: Dict[str, Any] = {"source": str(timings.get("source") or "timings")[:40], "raw": timings}
        prompt_n, prompt_ms = _count(timings.get("prompt_n")), _number(timings.get("prompt_ms"))
        predicted_n, predicted_ms = _count(timings.get("predicted_n")), _number(timings.get("predicted_ms"))
        if prompt_n is not None and prompt_ms:
            engine["prompt_n"] = prompt_n
            engine["prompt_ms"] = prompt_ms
            engine["prefill_tok_s"] = prompt_n * 1000.0 / prompt_ms
        if predicted_n and predicted_ms:
            engine["predicted_n"] = predicted_n
            engine["predicted_ms"] = predicted_ms
            all_tokens = predicted_n * 1000.0 / predicted_ms
            engine["decode_tok_s"] = all_tokens
            engine["decode_convention"] = "all-tokens"
            # Runtimes disagree on whether the first token counts: llama.cpp divides
            # (n - 1) by the time since August 2026, Strata and Ollama divide n. Follow the
            # runtime's own convention (it is the number its users see elsewhere), but
            # recompute it exactly, because Strata rounds its stated rate to 0.1.
            stated = _number(timings.get("predicted_per_second"))
            if stated and predicted_n > 1:
                first_excluded = (predicted_n - 1) * 1000.0 / predicted_ms
                if abs(stated - first_excluded) < abs(stated - all_tokens):
                    engine["decode_tok_s"] = first_excluded
                    engine["decode_convention"] = "first-token-excluded"
        cache_n = _count(timings.get("cache_n"))
        if cache_n is not None:
            engine["cache_n"] = cache_n
        for key in ("draft_n", "draft_n_accepted", "passes", "between_pass_tokens"):
            value = _count(timings.get(key))
            if value is not None:
                engine[key] = value
        pause = _number(timings.get("between_pass_ms"), minimum=-1.0)
        if pause is not None:
            engine["between_pass_ms"] = pause
        return engine
    stats = stream.get("stats")
    if isinstance(stats, dict) and _number(stats.get("tokens_per_second")):
        engine = {"source": "stats", "raw": stats, "decode_tok_s": float(stats["tokens_per_second"])}
        first = _number(stats.get("time_to_first_token"))
        if first:
            engine["ttft_s"] = first
        return engine
    return None


def derive_run(
    stream: Dict[str, Any],
    *,
    max_tokens: int,
    expect_fresh: bool,
    target_prompt_tokens: Optional[int] = None,
    estimated_prompt_tokens: Optional[int] = None,
    context_tokens: Optional[int] = None,
    expect_cache: bool = False,
    chars_per_token: Optional[float] = None,
    cache_baseline: int = 0,
    estimate_reliable: bool = True,
) -> Dict[str, Any]:
    """Turn one raw stream record into metrics plus validity flags.

    ``chars_per_token`` is this model's measured figure for the benchmark text, when known.
    It helps to tell a buffered stream from one with hidden tokens, and to estimate the
    output when the server sends no counts. ``cache_baseline`` is how many prompt tokens
    this runtime reuses for any two requests (the chat template's fixed opening).
    ``estimate_reliable`` is False for the user's own files, whose tokens per character
    the tool cannot know well enough to accuse a runtime of cutting the prompt.
    """
    flags: List[str] = []
    run: Dict[str, Any] = {"error": stream.get("error"), "flags": flags}
    if stream.get("error"):
        flags.append("error")
        run["wall_s"] = stream.get("wall_s")
        run["connect_s"] = stream.get("connect_s")
        return run

    usage = stream.get("usage") if isinstance(stream.get("usage"), dict) else {}
    engine = normalize_engine(stream)

    prompt_tokens = _count(usage.get("prompt_tokens")) or None
    completion_tokens = _count(usage.get("completion_tokens")) or None
    prompt_source = "usage"
    if prompt_tokens is None:
        prompt_tokens = estimated_prompt_tokens
        prompt_source = "estimate"

    # ---- cached prompt tokens: the largest figure any source gives, else unknown
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    candidates = []
    if _count(details.get("cached_tokens")) is not None:
        candidates.append((_count(details.get("cached_tokens")), "usage"))
    if engine and engine.get("cache_n") is not None:
        candidates.append((engine["cache_n"], "timings"))
    elif engine and engine.get("prompt_n") is not None and prompt_source == "usage" and prompt_tokens and 0 < prompt_tokens - engine["prompt_n"] > 8:
        # The engine evaluated fewer tokens than the prompt holds: the rest came from cache.
        candidates.append((prompt_tokens - engine["prompt_n"], "timings-inferred"))
    cached_tokens, cached_source = max(candidates, key=lambda item: item[0]) if candidates else (None, None)

    ttft = stream.get("first_token_s")
    last = stream.get("last_token_s")
    window = (last - ttft) if (ttft is not None and last is not None) else None
    total_chars = int(stream.get("answer_chars") or 0) + int(stream.get("reasoning_chars") or 0)
    # Thinking the server says it generated but did not stream: the one case where hidden
    # tokens are declared instead of inferred.
    declared_hidden = 0
    output_details = usage.get("completion_tokens_details")
    if isinstance(output_details, dict) and _count(output_details.get("reasoning_tokens")) and not stream.get("reasoning_events"):
        declared_hidden = _count(output_details.get("reasoning_tokens")) or 0
    events = int(stream.get("text_events") or 0)
    shape = {
        "hidden_tokens": declared_hidden, "chars_per_token": chars_per_token,
        # How the text arrived. Streams recorded without burst data count one arrival per event.
        "bursts": int(stream.get("bursts") or events), "first_burst_events": int(stream.get("first_burst_events") or 1),
    }
    first_chars = int(stream.get("first_burst_chars") or stream.get("first_event_chars") or 0)
    estimate = (completion_tokens, events, first_chars, total_chars, window)
    client = client_decode_rate(*estimate, **shape)
    engine_rate = engine.get("decode_tok_s") if engine else None
    if engine_rate and client.get("alternative_tok_s") and client.get("decode_tok_s"):
        # Buffered or hidden? The engine's own rate settles it when only one reading agrees.
        chosen_off = abs(client["decode_tok_s"] / engine_rate - 1.0)
        other_off = abs(client["alternative_tok_s"] / engine_rate - 1.0)
        if chosen_off > ENGINE_MISMATCH >= other_off:
            other = "buffered" if client["reading"] in ("hidden", "fat-first") else "hidden"
            client = client_decode_rate(*estimate, assume=other, **shape)
            if client.get("hidden_source"):
                client["hidden_source"] = client["hidden_source"].replace("stream", "engine")
        elif client.get("hidden_source") and chosen_off <= ENGINE_MISMATCH:
            client["hidden_source"] = client["hidden_source"].replace("stream", "engine")

    completion_source = "usage"
    if completion_tokens is None:
        completion_tokens, completion_source = client.get("tokens"), client.get("token_source")
    elif client.get("undercount") and client.get("tokens"):
        completion_tokens, completion_source = client["tokens"], client.get("token_source")  # the stream showed more
    if prompt_source != "usage" or (completion_source != "usage" and not client.get("undercount")):
        flags.append("no-usage")
    if completion_tokens is None:
        flags.append("no-token-counts")

    fresh_tokens = None
    if prompt_tokens and cached_tokens is not None:
        fresh_tokens = max(0, prompt_tokens - cached_tokens)
    elif prompt_tokens and not expect_cache:
        fresh_tokens = prompt_tokens  # nothing says otherwise; a follow-up turn gets no such benefit of the doubt

    # Client-side reading speed. The first text appears only after the engine has read the
    # prompt AND written what that first arrival carries, so that writing time is taken
    # off: one token for a per-token stream, a whole chunk for a buffered one, plus any
    # tokens written but never streamed. What remains still includes HTTP and templating
    # overhead, hence the "client" label. When the writing time is unknown, or is most of
    # the wait, there is no honest figure and none is given.
    client_prefill = None
    hidden = client.get("hidden_tokens") or 0
    if ttft and client.get("decode_tok_s") and client.get("tokens_in_window") is not None and client.get("tokens"):
        before_window = max(0.0, client["tokens"] - client["tokens_in_window"])  # first arrival plus anything hidden
        writing = before_window / client["decode_tok_s"]
        if writing < MAX_WRITING_SHARE_OF_TTFT * ttft and fresh_tokens is not None and fresh_tokens >= MIN_PREFILL_TOKENS:
            client_prefill = fresh_tokens / (ttft - writing)

    engine_prefill = None
    if engine and engine.get("prefill_tok_s") is not None:
        counted_cache = engine.get("cache_n") is None and (engine.get("prompt_n") or 0) >= (prompt_tokens or 0) > 0
        if counted_cache and cached_tokens:
            # Some runtimes (Ollama's OpenAI-compatible endpoint) count cached tokens in
            # prompt_n while timing only the fresh ones, which inflates the rate on a cache hit.
            engine["prompt_n"] = max(0, prompt_tokens - cached_tokens)
            engine["prefill_tok_s"] = engine["prompt_n"] * 1000.0 / engine["prompt_ms"]
        unknowable = counted_cache and cached_tokens is None and expect_cache
        if not unknowable and engine["prompt_n"] >= MIN_PREFILL_TOKENS:  # a handful of tokens over fixed overhead is not a rate
            engine_prefill = engine["prefill_tok_s"]
    engine_decode = engine.get("decode_tok_s") if engine else None

    run.update(
        {
            "prompt_tokens": prompt_tokens,
            "prompt_tokens_source": prompt_source,
            "completion_tokens": completion_tokens,
            "completion_tokens_source": completion_source,
            "cached_tokens": cached_tokens,
            "cached_tokens_source": cached_source,
            "fresh_prompt_tokens": fresh_tokens,
            "finish_reason": stream.get("finish_reason") if isinstance(stream.get("finish_reason"), str) else None,
            "ttft_s": ttft,
            "ttfa_s": stream.get("first_answer_s"),
            "decode_window_s": window,
            "wall_s": stream.get("wall_s"),
            "connect_s": stream.get("connect_s"),
            "reasoning_seen": bool(stream.get("reasoning_events")),
            "answer_seen": bool(stream.get("answer_events")),
            "inline_think": bool(stream.get("inline_think")),
            "text_events": stream.get("text_events"),
            "bursts": shape["bursts"],
            "stream_granularity": client.get("stream_granularity"),
            "stream_reading": client.get("reading"),
            "hidden_tokens": hidden,
            "hidden_tokens_source": client.get("hidden_source"),
            "output_chars": total_chars,
            "gap_median_ms": stream.get("gap_median_ms"),
            "gap_p95_ms": stream.get("gap_p95_ms"),
            "gap_max_ms": stream.get("gap_max_ms"),
            "client_decode_tok_s": client.get("decode_tok_s"),
            "client_prefill_tok_s": client_prefill,
            "engine_decode_tok_s": engine_decode,
            "engine_prefill_tok_s": engine_prefill,
            "engine": {k: v for k, v in engine.items() if k != "raw"} if engine else None,
            "decode_tok_s": engine_decode if engine_decode is not None else client.get("decode_tok_s"),
            "decode_source": "engine" if engine_decode is not None else ("client" if client.get("decode_tok_s") is not None else None),
            "prefill_tok_s": engine_prefill if engine_prefill is not None else client_prefill,
            "prefill_source": "engine" if engine_prefill is not None else ("client" if client_prefill is not None else None),
        }
    )

    # ---- validity
    if client.get("undercount"):
        flags.append("usage-undercount")
    elif completion_source == "usage" and completion_tokens is not None and completion_tokens < SHORT_OUTPUT_FRACTION * max_tokens:
        flags.append("short-output")
    if not stream.get("answer_events") and stream.get("reasoning_events"):
        flags.append("reasoning-only")
    if hidden:
        flags.append("hidden-tokens")
    if client.get("decode_tok_s") is None and engine_decode is None:
        flags.append("single-burst")
    elif client.get("reading") in ("buffered", "bursts", "fat-first") and engine_decode is None:
        # Several tokens per arrival, and no engine figure to check the estimate against.
        flags.append("buffered-stream")
    if engine_decode and client.get("decode_tok_s") and abs(client["decode_tok_s"] / engine_decode - 1.0) > ENGINE_MISMATCH:
        flags.append("client-engine-mismatch")
    if prompt_tokens and cached_tokens is not None:
        # A short prompt has no reading speed to protect, and its only shared text is the
        # chat template's opening, which real use reuses too.
        if expect_fresh and prompt_tokens >= MIN_PREFILL_TOKENS and cached_tokens - max(0, cache_baseline) > max(64, CACHE_HIT_FRACTION * prompt_tokens):
            flags.append("cache-hit")
        if expect_cache and cached_tokens < 0.5 * prompt_tokens:
            flags.append("no-cache-reuse")
    elif expect_cache and prompt_tokens:
        flags.append("cache-unknown")
    counted = prompt_source == "usage" and bool(prompt_tokens)
    short = counted and bool(estimated_prompt_tokens) and prompt_tokens < TRUNCATION_FRACTION * estimated_prompt_tokens
    # A count that sits exactly on the window, or on the window minus the output, while
    # more was sent: the runtime cut the prompt to fit.
    pinned = bool(
        counted and context_tokens and estimated_prompt_tokens and prompt_tokens < 0.99 * estimated_prompt_tokens
        and (abs(prompt_tokens - (context_tokens - max_tokens)) <= 2 or abs(prompt_tokens - context_tokens) <= 2)
    )
    if pinned or (short and estimate_reliable):
        flags.append("prompt-truncated")
    elif counted and ((target_prompt_tokens and abs(prompt_tokens - target_prompt_tokens) > DEPTH_TOLERANCE * target_prompt_tokens) or short):
        flags.append("depth-miss")
    if context_tokens and prompt_tokens and prompt_tokens + max_tokens > context_tokens:
        flags.append("context-overflow")
    if not stream.get("saw_done") and not stream.get("finish_reason"):
        flags.append("stream-incomplete")
    if stream.get("malformed_events"):
        flags.append("malformed-events")
    if isinstance(stream.get("connect_s"), (int, float)) and stream["connect_s"] > SLOW_CONNECT_S:
        flags.append("slow-connect")
    return run


def run_is_valid(run: Dict[str, Any]) -> bool:
    return not (set(run.get("flags") or []) & INVALIDATING_FLAGS)


SUMMARY_METRICS = (
    "prompt_tokens", "fresh_prompt_tokens", "completion_tokens", "cached_tokens", "ttft_s", "ttfa_s", "wall_s",
    "prefill_tok_s", "decode_tok_s", "client_prefill_tok_s", "client_decode_tok_s",
    "engine_prefill_tok_s", "engine_decode_tok_s",
)


def summarize_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [r for r in runs if run_is_valid(r)]
    summary: Dict[str, Any] = {"runs_total": len(runs), "runs_valid": len(valid)}
    for metric in SUMMARY_METRICS:
        stats = summarize([r.get(metric) for r in valid])
        if stats:
            summary[metric] = stats
    flags: Dict[str, int] = {}
    for run in runs:
        for flag in run.get("flags") or []:
            flags[flag] = flags.get(flag, 0) + 1
    summary["flags"] = flags
    sources = {r.get("decode_source") for r in valid if r.get("decode_source")}
    summary["decode_source"] = sources.pop() if len(sources) == 1 else ("mixed" if sources else None)
    sources = {r.get("prefill_source") for r in valid if r.get("prefill_source")}
    summary["prefill_source"] = sources.pop() if len(sources) == 1 else ("mixed" if sources else None)
    return summary


DURATION_METRICS = {"ttft_s", "ttfa_s", "wall_s", "connect_s"}
TIMING_JITTER_S = 0.025  # a first-token time that wobbles by less than this is scheduler noise


def meaningful_spread(stats: Optional[Dict[str, float]], metric: str = "") -> Optional[float]:
    """Run-to-run spread in percent, or None when there is nothing meaningful to report.

    A 30 ms first-token time that wobbles by 10 ms is "+/-30%" but nobody can feel it, so
    for durations the wobble (half the range) must also reach TIMING_JITTER_S to count.
    """
    if not stats or stats.get("n", 0) < 2:
        return None
    if metric in DURATION_METRICS and (stats["max"] - stats["min"]) / 2.0 < TIMING_JITTER_S:
        return 0.0
    return stats.get("spread_pct", 0.0)


def stability(stats: Optional[Dict[str, float]], metric: str = "") -> str:
    """Plain-language label for run-to-run spread (half the range over the median)."""
    if not stats:
        return "no data"
    if stats.get("n", 0) < 2:
        return "single run"
    spread = meaningful_spread(stats, metric) or 0.0
    if spread <= 3.0:
        return "stable"
    if spread <= 7.0:
        return "ok"
    if spread <= 15.0:
        return "noisy"
    return "unstable"


# ------------------------------------------------------------------------- comparison

HIGHER_IS_BETTER = {"prefill_tok_s", "decode_tok_s", "client_prefill_tok_s", "client_decode_tok_s", "engine_prefill_tok_s", "engine_decode_tok_s"}
NOISE_FLOOR_PCT = 2.0
# Two-sided 95% points of Student's t for 1 to 30 degrees of freedom.
_T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
    2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)
# The median of a few runs wobbles more than their mean: by 16% with three runs, 20% with
# five, 25% with many. One factor on the safe side covers them all.
MEDIAN_WOBBLE = 1.25


def chance_threshold_pct(base: Dict[str, float], new: Dict[str, float]) -> Optional[float]:
    """How far apart two medians must be before run-to-run variation is an unlikely cause.

    Welch's test on the two sets of runs, at the usual one-in-twenty level, expressed as a
    percentage of the base median. With two or three runs per side the bar is high, and it
    should be: three runs that vary by 5% cannot show a 5% difference. None when either
    side has a single run, because one run says nothing about variation.
    """
    n_a, n_b = int(base.get("n", 0)), int(new.get("n", 0))
    if n_a < 2 or n_b < 2 or not base.get("median"):
        return None
    var_a, var_b = base.get("stdev", 0.0) ** 2 / n_a, new.get("stdev", 0.0) ** 2 / n_b
    error = math.sqrt(var_a + var_b)
    if error <= 0:
        return 0.0
    freedom = (var_a + var_b) ** 2 / (var_a ** 2 / (n_a - 1) + var_b ** 2 / (n_b - 1))
    index = max(1, int(freedom))  # rounded down: the cautious side
    critical = _T95[index - 1] if index <= len(_T95) else 1.96
    return critical * error * MEDIAN_WOBBLE / abs(base["median"]) * 100.0


def compare_stats(metric: str, base: Optional[Dict[str, float]], new: Optional[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    """Compare two summaries. A change counts only when chance is an unlikely explanation.

    ``noise_pct`` is the smallest change that would count: the larger of a 2% floor (25 ms
    for durations) and the chance threshold above. When either side is a single run there
    is no variation to test against; the other side's whole range is used and the verdict
    says so.
    """
    if not base or not new or not base.get("median"):
        return None
    delta_pct = (new["median"] - base["median"]) / base["median"] * 100.0
    noise = NOISE_FLOOR_PCT
    if metric in DURATION_METRICS:  # durations also get an absolute floor
        noise = max(noise, TIMING_JITTER_S / base["median"] * 100.0)
    single = base.get("n", 0) < 2 or new.get("n", 0) < 2
    threshold = chance_threshold_pct(base, new)
    if threshold is None:
        threshold = 2.0 * max(base.get("spread_pct", 0.0), new.get("spread_pct", 0.0))  # the whole range of the side that has one
    noise = max(noise, threshold)
    if abs(delta_pct) <= noise:
        verdict = "within noise"
    else:
        better = (delta_pct > 0) == (metric in HIGHER_IS_BETTER)
        verdict = "better" if better else "worse"
        if single:
            verdict += " (single run: indicative only)"
    return {"base": base["median"], "new": new["median"], "delta_pct": delta_pct, "noise_pct": noise, "verdict": verdict, "runs": [int(base.get("n", 0)), int(new.get("n", 0))]}


FIT_TOLERANCE = 0.10  # every size must sit this close to the line, and the smaller sizes must predict the largest this well


def _line(data: Sequence[Sequence[float]]) -> Optional[Sequence[float]]:
    """Least-squares (intercept, slope, r_squared) through (x, y) points, or None."""
    n = float(len(data))
    mean_x = sum(x for x, _ in data) / n
    mean_y = sum(y for _, y in data) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in data)
    syy = sum((y - mean_y) ** 2 for _, y in data)
    if sxx <= 0 or syy <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in data) / sxx
    intercept = mean_y - slope * mean_x
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in data)
    return intercept, slope, 1.0 - residual / syy


def fit_reading(points: Sequence[Sequence[float]]) -> Optional[Dict[str, float]]:
    """Fit seconds = fixed + tokens / rate through (tokens, seconds) points.

    "Tokens divided by time" hides a fixed cost per request. The v1 DeepSeek data is the
    example: 838 tok/s at 4.5K tokens and 2,506 at 250K looked like an engine that speeds up
    with depth, but the times fit about 3 seconds per request plus a rate near 2,600 tok/s.

    A straight line through a few points proves little when the largest prompt dominates
    it, and R squared says nothing about the small sizes, where the fixed cost lives. So a
    fit is reported only when all of this holds: at least three clearly different sizes;
    every size within 10% of the line; a fixed cost no larger than the fastest read; and a
    line through the smaller sizes alone predicting the largest within 10%.
    """
    data = sorted((float(x), float(y)) for x, y in points if x and y and x > 0 and y > 0)
    distinct: List[Sequence[float]] = []
    for point in data:  # sizes within 20% of each other are one size
        if not distinct or point[0] > 1.2 * distinct[-1][0]:
            distinct.append(point)
    if len(distinct) < 3:
        return None
    full = _line(data)
    rest = _line([point for point in data if point[0] < distinct[-1][0]])
    if not full or not rest:
        return None
    intercept, slope, r_squared = full
    if slope <= 0 or intercept < -FIT_TOLERANCE * data[0][1] or intercept > data[0][1]:
        return None
    worst = max(abs((intercept + slope * x) / y - 1.0) for x, y in data)
    if worst > FIT_TOLERANCE:
        return None
    largest_x, largest_y = data[-1]
    holdout = (rest[0] + rest[1] * largest_x) / largest_y - 1.0
    if abs(holdout) > FIT_TOLERANCE:
        return None
    return {
        "fixed_s": max(0.0, intercept), "marginal_tok_s": 1.0 / slope, "r_squared": r_squared, "points": len(distinct),
        "worst_point_pct": worst * 100.0, "holdout_error_pct": holdout * 100.0,
    }


def request_time(ttft_s: Optional[float], decode_tok_s: Optional[float], output_tokens: int) -> Optional[float]:
    """Seconds to finish a request: wait for the first token, then write the answer."""
    if ttft_s is None or not decode_tok_s:
        return None
    return ttft_s + output_tokens / decode_tok_s
