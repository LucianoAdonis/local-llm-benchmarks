import argparse
import datetime as dt
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

ENGINE_RE = re.compile(
    r"prompt\s+(?P<prompt>\d+)\s+tokens\s+=\s+(?P<reused>\d+)\s+reused\s+\+\s+(?P<read>\d+)\s+read\s+in\s+(?P<prefill_ms>\d+)\s+ms\s+\([\d.]+\s+tok/s\),\s+(?P<generated>\d+)\s+generated\s+in\s+(?P<decode_ms>\d+)\s+ms\s+\([\d.]+\s+tok/s\)"
)


def make_prompt(nonce, sections):
    rows = []
    for i in range(sections):
        name = f"w{nonce:02d}_{i:04d}"
        rows.append(
            f"# src/run_{nonce:02d}/workers/worker_{name}.py\n"
            f"class Worker_{name}:\n"
            f"    def handle(self, request, store, cache, queue):\n"
            f"        request_id = request.headers.get('x-request-id') or make_id()\n"
            f"        record = store.load(request.project_id, request.item_id)\n"
            f"        if record is None: return error(404, request_id)\n"
            f"        if cache.contains(record.version): return cache.get(record.version)\n"
            f"        result = queue.submit(self.execute, record, request_id)\n"
            f"        store.save_status(request_id, 'running')\n"
            f"        return result\n"
        )
    return (
        f"Benchmark case {nonce}. Review this synthetic multi-file Python repository context. "
        "Identify correctness, reliability, and performance risks supported by the excerpts. "
        "Prioritize concrete fixes, cite file names, and do not assume behavior that is not shown. "
        "\n\nBEGIN REPOSITORY EXCERPTS\n"
        + "\n".join(rows)
        + "\nEND REPOSITORY EXCERPTS\nGive a concise prioritized engineering review."
    )


def read_engine_metrics(log, start_cookie):
    log.seek(start_cookie)
    metrics = []
    lines = []
    idle_since = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        line = log.readline()
        if line:
            lines.append(line.rstrip())
            match = ENGINE_RE.search(line)
            if match:
                metrics.append({key: int(value) for key, value in match.groupdict().items()})
                idle_since = time.monotonic()
        else:
            if metrics and idle_since and time.monotonic() - idle_since >= 0.35:
                break
            time.sleep(0.05)
    return metrics, lines


def request_one(url, model, nonce, sections, max_tokens, timeout, log):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful senior software engineer. Analyze only the provided evidence."},
            {"role": "user", "content": make_prompt(nonce, sections)},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
    log.seek(0, 2)
    start_cookie = log.tell()
    started = time.perf_counter()
    first_content = None
    usage = None
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
                    content = (choice.get("delta") or {}).get("content")
                    if isinstance(content, str) and content and first_content is None:
                        first_content = time.perf_counter()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    ended = time.perf_counter()
    engine, new_lines = read_engine_metrics(log, start_cookie)
    if first_content is None or not usage or not usage.get("completion_tokens"):
        raise RuntimeError("The API did not return streamed text with token usage.")
    if not engine:
        raise RuntimeError("No DeepSeek engine timing rows were added to the configured engine log.")
    engine_read = sum(row["read"] for row in engine)
    engine_prefill_ms = sum(row["prefill_ms"] for row in engine)
    engine_generated = sum(row["generated"] for row in engine)
    engine_decode_ms = sum(row["decode_ms"] for row in engine)
    elapsed = ended - started
    return {
        "run": nonce,
        "sections": sections,
        "api_prompt_tokens": usage.get("prompt_tokens"),
        "api_completion_tokens": usage.get("completion_tokens"),
        "client_time_to_first_content_s": round(first_content - started, 4),
        "client_request_wall_s": round(elapsed, 4),
        "engine_passes": engine,
        "engine_prompt_tokens_read": engine_read,
        "engine_prefill_ms": engine_prefill_ms,
        "engine_prefill_tokens_per_s": round(engine_read * 1000 / engine_prefill_ms, 3) if engine_prefill_ms else None,
        "engine_generated_tokens": engine_generated,
        "engine_decode_ms": engine_decode_ms,
        "engine_decode_tokens_per_s": round(engine_generated * 1000 / engine_decode_ms, 3) if engine_decode_ms else None,
        "finish_reason": finish_reason,
        "engine_log_excerpt": new_lines,
    }


def main():
    parser = argparse.ArgumentParser(description="DeepSeek coding-context benchmark using Strata's engine timing rows and API usage.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--sections", type=int, required=True)
    parser.add_argument("--start-run", type=int, default=1, help="first unique prompt nonce")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=100)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--profile", default="deepseek-coding-32k")
    parser.add_argument("--engine-log", required=True, help="path to the Strata profile's engine log")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10 or not 1 <= args.sections <= 2100:
        parser.error("runs must be 1..10 and sections 1..2100")
    out = Path(args.output)
    if out.exists():
        parser.error(f"output file already exists: {out}")
    log_path = Path(args.engine_log)
    if not log_path.exists():
        parser.error(f"engine log not found: {log_path}")
    results = []
    print(f"DeepSeek coding workload: {args.runs} runs, {args.sections} unique source sections, context {args.context}", flush=True)
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        for nonce in range(args.start_run, args.start_run + args.runs):
            result = request_one(args.url, args.model, nonce, args.sections, args.max_tokens, args.timeout, log)
            if result["api_prompt_tokens"] and result["api_prompt_tokens"] + args.max_tokens > args.context:
                raise RuntimeError(f"Actual prompt {result['api_prompt_tokens']} plus output limit exceeds context {args.context}.")
            results.append(result)
            print(json.dumps({"run": nonce, **{k: v for k, v in result.items() if k != "engine_log_excerpt"}}), flush=True)
    document = {
        "schema": "strata-deepseek-engine-coding-benchmark-v1",
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "profile": args.profile,
        "configured_context_tokens": args.context,
        "workload": "synthetic multi-file Python code review; every section is unique per run to avoid prompt-cache reuse",
        "sections_per_request": args.sections,
        "max_output_tokens": args.max_tokens,
        "temperature": 0,
        "metrics": "engine-reported prompt-read and generation milliseconds/tokens, plus API-reported prompt/completion token counts",
        "summary": {
            "median_api_prompt_tokens": statistics.median(r["api_prompt_tokens"] for r in results),
            "median_engine_prefill_tokens_per_s": round(statistics.median(r["engine_prefill_tokens_per_s"] for r in results), 3),
            "median_engine_decode_tokens_per_s": round(statistics.median(r["engine_decode_tokens_per_s"] for r in results), 3),
            "median_client_first_content_s": round(statistics.median(r["client_time_to_first_content_s"] for r in results), 4),
            "median_client_request_wall_s": round(statistics.median(r["client_request_wall_s"] for r in results), 4),
        },
        "runs": results,
        "caveats": [
            "Engine timing rows are specific to this Strata DeepSeek engine build; compare only with the same engine, quantization, settings, prompt size, context, and cache policy.",
            "This synthetic code-review workload measures performance, not code quality.",
            "API completion usage can differ from engine subcall generated-token counts because the engine may make multiple internal generation passes; both are recorded.",
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(out), "summary": document["summary"]}), flush=True)


if __name__ == "__main__":
    main()
