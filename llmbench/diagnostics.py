"""Versioned evidence and follow-up measurements for a diagnostic UI."""
from __future__ import annotations

from . import __version__, sysinfo
from .sanitize import clean

MEASUREMENTS = [
    {"id": "interactive", "method": "llmbench run --suite quick --context 16384 --fixed-text",
     "metrics": ["first token latency", "prefill tok/s", "decode tok/s", "run spread"]},
    {"id": "context", "method": "Repeat at 32K with common scenarios, then measure a longer prompt separately.",
     "metrics": ["first visible answer", "peak VRAM", "shared GPU memory change", "swap change"]},
    {"id": "storage", "method": "Alternate drives with identical weights and record cache state. See docs/storage-reporting.md.",
     "metrics": ["preload bytes and seconds", "disk read throughput", "disk active time", "first token latency"]},
    {"id": "task", "method": "Repeat the same representative coding task and acceptance checks.",
     "metrics": ["wall time to passing result", "acceptance checks passed"]},
]


def build(system, state, results):
    findings = []

    def inspect(snapshot, source, index=None):
        gpu = snapshot.get("gpu") or {}
        used, total = gpu.get("vram_used_mb"), gpu.get("vram_total_mb")
        if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0 and used / total >= .95:
            findings.append({
                "id": "vram_headroom", "source": source, "run_index": index,
                "evidence": {"used_mb": used, "total_mb": total},
                "suggestion": "Compare a smaller context or quantization with one active request. Track first-token latency and shared GPU memory.",
                "measurement_id": "context",
            })

    inspect(state, "live")
    runs = []
    for index, result in enumerate(results):
        before = result.get("state_before") or {}
        after = result.get("state_after") or {}
        verdict = result.get("verdict") or {}
        if verdict.get("status") in ("clean", "usable with cautions"):
            inspect(before, "run_start", index)
            inspect(after, "run_end", index)
            for key, threshold in (("gpu_shared_memory_mb", 512), ("swap_used_mb", 256)):
                start, end = before.get(key), after.get(key)
                if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end - start > threshold:
                    findings.append({
                        "id": key + "_growth", "source": "run_delta", "run_index": index,
                        "evidence": {"before_mb": start, "after_mb": end, "delta_mb": end - start},
                        "suggestion": "Repeat with a smaller model or context and check whether memory growth and latency fall together.",
                        "measurement_id": "context",
                    })
        runs.append({
            "label": result.get("label"), "model": result.get("model"), "runtime": result.get("runtime"),
            "system": result.get("system"), "settings": result.get("settings"), "tool": result.get("tool"),
            "state_before": before, "state_after": after, "verdict": verdict,
            "scenarios": [
                {"id": scenario.get("id"), "summary": scenario.get("summary"), "skipped": scenario.get("skipped")}
                for scenario in result.get("scenarios") or []
            ],
        })

    return clean({
        "schema": "llmbench-diagnostic/1", "tool_version": __version__,
        "system": system, "state": state, "warnings": sysinfo.preflight_warnings(system, state),
        "runs": runs, "findings": findings, "measurements": MEASUREMENTS,
    })
