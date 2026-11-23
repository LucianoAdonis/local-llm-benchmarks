import argparse
import datetime as dt
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path


def make_prompt(nonce, sections):
    rows = []
    for i in range(sections):
        rows.append(
            f"# src/workers/worker_{i:04d}.py\n"
            f"class Worker{i:04d}:\n"
            f"    def handle(self, request, store, cache, queue):\n"
            f"        request_id = request.headers.get('x-request-id') or make_id()\n"
            f"        record = store.load(request.project_id, request.item_id)\n"
            f"        if record is None: return error(404, request_id)\n"
            f"        if cache.contains(record.version): return cache.get(record.version)\n"
            f"        result = queue.submit(self.execute, record, request_id)\n"
            f"        store.save_status(request_id, 'running')\n"
            f"        return result\n"
        )
    context = "\n".join(rows)
    return (
        f"Benchmark case {nonce}. Review the following synthetic multi-file Python repository context. "
        "Identify likely correctness, reliability, and performance risks supported by the excerpts. "
        "Prioritize concrete fixes, cite file names, and do not assume behavior that is not shown. "
        "\n\nBEGIN REPOSITORY EXCERPTS\n"
        f"{context}\n"
        "END REPOSITORY EXCERPTS\n"
        "Give a concise prioritized engineering review."
    )


def run_request(url, model, nonce, sections, max_tokens, timeout):
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
                    content = (choice.get("delta") or {}).get("content")
                    if isinstance(content, str) and content:
                        if first_content is None:
                            first_content = time.perf_counter()
                        chars += len(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    ended = time.perf_counter()
    if first_content is None or not usage or not usage.get("completion_tokens"):
        raise RuntimeError("The server did not return streamed text with token usage.")
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage["completion_tokens"])
    total_s = ended - started
    ttft = first_content - started
    decode_window = ended - first_content
    return {
        "nonce": nonce,
        "sections": sections,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "time_to_first_content_s": round(ttft, 4),
        "request_wall_s": round(total_s, 4),
        "decode_window_s": round(decode_window, 4),
        "prompt_tokens_per_s_to_first_content": round(prompt_tokens / ttft, 3) if ttft > 0 else None,
        "output_tokens_per_s_decode_window": round(completion_tokens / decode_window, 3) if decode_window > 0 else None,
        "output_tokens_per_s_end_to_end": round(completion_tokens / total_s, 3) if total_s > 0 else None,
        "completion_chars": chars,
        "finish_reason": finish_reason,
    }


def main():
    parser = argparse.ArgumentParser(description="Coding-context performance benchmark for a local OpenAI-compatible Strata endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--sections", type=int, required=True, help="synthetic repository sections; record actual prompt token usage")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--profile", default="deepseek-coding-32k")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    if not 1 <= args.sections <= 1000:
        parser.error("--sections must be between 1 and 1000")
    out = Path(args.output)
    if out.exists():
        parser.error(f"output file already exists: {out}")
    results = []
    print(f"Starting {args.runs} coding-context requests with {args.sections} repository sections and {args.context} context", flush=True)
    for i in range(1, args.runs + 1):
        result = run_request(args.url, args.model, i, args.sections, args.max_tokens, args.timeout)
        if result["prompt_tokens"] + args.max_tokens > args.context:
            raise RuntimeError(f"Request used {result['prompt_tokens']} prompt tokens; prompt plus output cap exceeds configured context {args.context}.")
        results.append(result)
        print(json.dumps({"run": i, **result}), flush=True)
    document = {
        "schema": "strata-coding-context-benchmark-v1",
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoint": args.url,
        "model": args.model,
        "profile": args.profile,
        "configured_context_tokens": args.context,
        "workload": "synthetic multi-file Python code review",
        "sections_per_request": args.sections,
        "max_output_tokens": args.max_tokens,
        "temperature": 0,
        "measurement": "streaming API usage counts and client-observed first-content/request timing",
        "summary": {
            "median_prompt_tokens": statistics.median(r["prompt_tokens"] for r in results),
            "median_prompt_tokens_per_s_to_first_content": round(statistics.median(r["prompt_tokens_per_s_to_first_content"] for r in results), 3),
            "median_time_to_first_content_s": round(statistics.median(r["time_to_first_content_s"] for r in results), 4),
            "median_decode_window_output_tokens_per_s": round(statistics.median(r["output_tokens_per_s_decode_window"] for r in results), 3),
            "median_end_to_end_output_tokens_per_s": round(statistics.median(r["output_tokens_per_s_end_to_end"] for r in results), 3),
        },
        "caveats": [
            "Prompt throughput is prompt_tokens divided by time to first streamed content; TTFT includes loopback request overhead and any server queueing, so it is a client-observed prefill proxy.",
            "Decode-window rate is output tokens divided by time from first streamed text to stream end; it is not kernel-only decode speed.",
            "The generated source excerpts form a repeatable synthetic coding workload, not a quality benchmark or a real repository audit.",
            "Unique benchmark run identifiers are placed before the source excerpts to reduce prompt-cache reuse across repeats.",
        ],
        "runs": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(out), "summary": document["summary"]}), flush=True)


if __name__ == "__main__":
    main()
