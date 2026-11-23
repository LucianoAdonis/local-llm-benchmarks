import argparse
import datetime as dt
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

PROMPT = (
    "Write a detailed, practical technical guide for diagnosing a slow web application. "
    "Use numbered sections 1 through 18, with several complete sentences in every section. "
    "Cover how to measure latency and throughput, inspect CPU and GPU use, memory pressure, "
    "storage and paging, network delays, caching, database queries, profiling, and how to "
    "verify a fix. Keep explaining each section in useful detail; use the available response "
    "length and do not end with a brief summary."
)


def request_stream(url, model, nonce, max_tokens, timeout):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a clear technical writer. Follow the requested format."},
            {"role": "user", "content": f"Measurement run {nonce}. {PROMPT}"},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.perf_counter()
    first_content = None
    usage = None
    chars = 0
    finish_reason = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                if not raw_line.startswith(b"data:"):
                    continue
                data = raw_line[5:].strip()
                if data == b"[DONE]":
                    break
                event = json.loads(data.decode("utf-8"))
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices", []):
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        if first_content is None:
                            first_content = time.perf_counter()
                        chars += len(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    ended = time.perf_counter()
    if first_content is None:
        raise RuntimeError("The server returned no streamed text.")
    if not usage or not usage.get("completion_tokens"):
        raise RuntimeError("The stream did not include token usage; no tokens/sec result was saved.")
    completion_tokens = int(usage["completion_tokens"])
    total_s = ended - started
    decode_window_s = ended - first_content
    return {
        "nonce": nonce,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion_tokens,
        "total_tokens": usage.get("total_tokens"),
        "time_to_first_content_s": round(first_content - started, 4),
        "request_wall_s": round(total_s, 4),
        "decode_window_s": round(decode_window_s, 4),
        "output_tokens_per_s_decode_window": round(completion_tokens / decode_window_s, 3) if decode_window_s > 0 else None,
        "output_tokens_per_s_end_to_end": round(completion_tokens / total_s, 3) if total_s > 0 else None,
        "completion_chars": chars,
        "finish_reason": finish_reason,
    }


def main():
    parser = argparse.ArgumentParser(description="Repeatable streamed generation benchmark for a local OpenAI-compatible Strata endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 10:
        parser.error("--runs must be between 1 and 10")
    out = Path(args.output)
    if out.exists():
        parser.error(f"output file already exists: {out}")
    results = []
    print(f"Starting {args.runs} measured streamed generations, max_tokens={args.max_tokens}", flush=True)
    for run in range(1, args.runs + 1):
        result = request_stream(args.url, args.model, run, args.max_tokens, args.timeout)
        results.append(result)
        print(json.dumps({"run": run, **result}), flush=True)
    decode = [r["output_tokens_per_s_decode_window"] for r in results]
    end_to_end = [r["output_tokens_per_s_end_to_end"] for r in results]
    document = {
        "schema": "strata-local-stream-benchmark-v1",
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoint": args.url,
        "model": args.model,
        "profile": "deepseek-offload-benchmark",
        "context_tokens": 8192,
        "run_count": len(results),
        "max_tokens_per_run": args.max_tokens,
        "method": "streaming chat completions; usage token counts; client-side first-content and wall-clock timing",
        "caveats": [
            "The decode-window rate divides completion tokens by time from first streamed text to stream end; it is a client-observed estimate, not a backend kernel-only rate.",
            "TTFT includes request/network/server queue and prefill; endpoint is loopback.",
            "All runs use a fixed prompt template with a unique leading run number to reduce prompt-cache reuse.",
            "This measures serving speed, not answer quality; compare only runs with the same model files, profile, prompt, context, and settings.",
        ],
        "summary": {
            "median_decode_window_tokens_per_s": round(statistics.median(decode), 3),
            "median_end_to_end_tokens_per_s": round(statistics.median(end_to_end), 3),
            "median_time_to_first_content_s": round(statistics.median([r["time_to_first_content_s"] for r in results]), 4),
            "median_request_wall_s": round(statistics.median([r["request_wall_s"] for r in results]), 4),
        },
        "runs": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(out), "summary": document["summary"]}), flush=True)


if __name__ == "__main__":
    main()
