import argparse
import datetime as dt
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

ENGINE_RE = re.compile(r"prompt\s+(?P<prompt>\d+)\s+tokens\s+=\s+(?P<reused>\d+)\s+reused\s+\+\s+(?P<read>\d+)\s+read\s+in\s+(?P<prefill_ms>\d+)\s+ms\s+\([\d.]+\s+tok/s\),\s+(?P<generated>\d+)\s+generated\s+in\s+(?P<decode_ms>\d+)\s+ms\s+\([\d.]+\s+tok/s\)")


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
        "\n\nBEGIN REPOSITORY EXCERPTS\n" + "\n".join(rows)
        + "\nEND REPOSITORY EXCERPTS\nGive a concise prioritized engineering review."
    )


def read_rows(log, start_cookie):
    log.seek(start_cookie)
    rows = []
    deadline = time.monotonic() + 5
    idle = None
    while time.monotonic() < deadline:
        line = log.readline()
        if line:
            found = ENGINE_RE.search(line)
            if found:
                rows.append({key: int(value) for key, value in found.groupdict().items()})
                idle = time.monotonic()
        elif rows and idle and time.monotonic() - idle > 0.3:
            break
        else:
            time.sleep(0.05)
    return rows


def run_one(url, model, nonce, sections, max_tokens, timeout, log):
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
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
    log.seek(0, 2)
    cookie = log.tell()
    start = time.perf_counter()
    first = None
    usage = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw in response:
                if not raw.startswith(b"data:"):
                    continue
                data = raw[5:].strip()
                if data == b"[DONE]":
                    break
                event = json.loads(data.decode())
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices", []):
                    content = (choice.get("delta") or {}).get("content")
                    if isinstance(content, str) and content and first is None:
                        first = time.perf_counter()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    end = time.perf_counter()
    rows = read_rows(log, cookie)
    if not rows:
        raise RuntimeError("No engine timing row was written for this request.")
    prefill_ms = sum(row["prefill_ms"] for row in rows)
    read_tokens = sum(row["read"] for row in rows)
    decode_ms = sum(row["decode_ms"] for row in rows)
    generated = sum(row["generated"] for row in rows)
    return {
        "run": nonce,
        "sections": sections,
        "api_usage": usage,
        "engine_passes": rows,
        "prompt_tokens_read": read_tokens,
        "prefill_ms": prefill_ms,
        "engine_prefill_tokens_per_s": round(read_tokens * 1000 / prefill_ms, 3) if prefill_ms else None,
        "engine_generated_tokens": generated,
        "decode_ms": decode_ms,
        "engine_decode_tokens_per_s": round(generated * 1000 / decode_ms, 3) if decode_ms else None,
        "client_first_content_s": round(first - start, 4) if first else None,
        "client_wall_s": round(end - start, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Coding-context benchmark using inference engine log timings and API streaming.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--model", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--sections", type=int, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=100)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--engine-log", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        parser.error(f"output already exists: {out}")
    log_path = Path(args.engine_log)
    if not log_path.exists():
        parser.error(f"engine log not found: {log_path}")
    results = []
    print(f"Running {args.runs} {args.context}-context coding requests ({args.sections} source sections each)", flush=True)
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        for nonce in range(1, args.runs + 1):
            result = run_one(args.url, args.model, nonce, args.sections, args.max_tokens, args.timeout, log)
            results.append(result)
            print(json.dumps(result), flush=True)
    content_times = [r["client_first_content_s"] for r in results if r["client_first_content_s"] is not None]
    document = {
        "schema": "strata-engine-log-coding-benchmark-v1",
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "profile": args.profile,
        "configured_context_tokens": args.context,
        "workload": "synthetic multi-file Python code review; unique section names per request",
        "sections_per_request": args.sections,
        "max_output_tokens": args.max_tokens,
        "temperature": 0,
        "measurement": "engine-log prompt and decode token/time rows; client-observed TTFT and total wall time",
        "summary": {
            "median_prompt_tokens_read": statistics.median(r["prompt_tokens_read"] for r in results),
            "median_engine_prefill_tokens_per_s": round(statistics.median(r["engine_prefill_tokens_per_s"] for r in results), 3),
            "median_engine_decode_tokens_per_s": round(statistics.median(r["engine_decode_tokens_per_s"] for r in results), 3),
            "median_client_first_content_s": round(statistics.median(content_times), 4) if content_times else None,
            "median_client_wall_s": round(statistics.median(r["client_wall_s"] for r in results), 4),
        },
        "runs": results,
        "caveats": [
            "Engine decode and prefill values come from this engine's own timing rows; compare only matching model, engine, context, workload, and settings.",
            "Synthetic code-review prompts measure serving speed, not coding quality.",
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(out), "summary": document["summary"]}), flush=True)


if __name__ == "__main__":
    main()
