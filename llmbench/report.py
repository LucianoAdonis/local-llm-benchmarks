"""Human-readable output: terminal table, Markdown summary, and A/B comparison."""
from __future__ import annotations

import csv as csv_module
import io
from typing import Any, Dict, List, Optional

from . import PROTOCOL_VERSION
from .metrics import compare_stats, meaningful_spread, stability
from .runtimes import display_name
from .sysinfo import describe

WORDS_PER_TOKEN = 0.75  # rough English average; code and other languages differ

FLAG_NOTES = {
    "cache-hit": "CACHE HIT",
    "prompt-truncated": "PROMPT TRUNCATED",
    "no-cache-reuse": "no cache reuse",
    "short-output": "stopped early",
    "buffered-stream": "buffered stream",
    "no-usage": "estimated counts",
    "no-token-counts": "no token counts",
    "usage-undercount": "counts too low",
    "cache-unknown": "cache size unknown",
    "first-turn-failed": "first turn failed",
    "depth-miss": "size off target",
    "context-overflow": "over context",
    "reasoning-only": "thinking only",
    "hidden-tokens": "hidden tokens",
    "client-engine-mismatch": "client/engine differ",
    "single-burst": "no stream timing",
    "malformed-events": "unreadable events",
    "slow-connect": "slow connect",
    "stream-incomplete": "stream cut",
    "error": "errors",
}


def flag_label(flag: str) -> str:
    """Short label for a run flag, as shown in the table and on each run line."""
    return FLAG_NOTES.get(flag, flag)


def num(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return "{:,.0f}".format(value)
    if abs(value) >= 100:
        return "%.0f" % value
    return ("%." + str(digits) + "f") % value


def _stat(record: Dict[str, Any], metric: str) -> Optional[Dict[str, float]]:
    return (record.get("summary") or {}).get(metric)


def _median(record: Dict[str, Any], metric: str) -> Optional[float]:
    stats = _stat(record, metric)
    return stats["median"] if stats else None


def _spread(record: Dict[str, Any]) -> str:
    if record.get("kind") in ("sanity", "soak"):
        return "-"
    worst = None
    for metric in ("ttft_s", "decode_tok_s", "prefill_tok_s"):
        spread = meaningful_spread(_stat(record, metric), metric)
        if spread is not None:
            worst = max(worst or 0.0, spread)
    return "single run" if worst is None else "+/-%.1f%%" % worst


def _notes(record: Dict[str, Any]) -> str:
    summary = record.get("summary") or {}
    notes = [flag_label(flag) for flag in sorted(summary.get("flags") or {})]
    if record.get("kind") == "followup":
        cached, prompt = _median(record, "cached_tokens"), _median(record, "prompt_tokens")
        if cached is not None and prompt:
            notes.insert(0, "%.0f%% cached" % (100.0 * cached / prompt))
        speedups = sorted(r["cache_speedup"] for r in record.get("runs") or [] if r.get("cache_speedup"))
        if speedups:
            notes.insert(0, "first token x%.0f sooner" % speedups[len(speedups) // 2])
    if record.get("kind") == "parallel":
        notes.insert(0, "total across %d requests" % record.get("parallel", 0))
        if isinstance(summary.get("ttft_worst_s"), (int, float)):
            notes.insert(1, "slowest first token %.2f s" % summary["ttft_worst_s"])
    first = summary.get("first_run") or {}
    if isinstance(first.get("reading_vs_steady_pct"), (int, float)) and first["reading_vs_steady_pct"] <= -5.0:
        notes.insert(0, "first read %.0f%% slower" % -first["reading_vs_steady_pct"])
    writing = (summary.get("stability") or {}).get("writing")
    if writing:
        notes.insert(0, "worst loop %.0f%% of best over %d loops" % (writing["ratio"] * 100, summary["stability"].get("loops", 0)))
    sources = {summary.get("decode_source"), summary.get("prefill_source")} - {None}
    if sources == {"engine"}:
        notes.append("engine-timed")
    elif "engine" in sources or "mixed" in sources:
        notes.append("mixed timing")
    return ", ".join(notes)


def rows(result: Dict[str, Any]) -> List[List[str]]:
    table = [["Scenario", "Prompt tok", "First token s", "Read tok/s", "Write tok/s", "Runs", "Spread", "Notes"]]
    for record in result.get("scenarios") or []:
        if record.get("skipped") and not (record.get("summary") or {}).get("runs_valid"):
            table.append([record["id"], "-", "-", "-", "-", "0", "-", "skipped: " + str(record["skipped"])])
            continue
        summary = record.get("summary") or {}
        if record.get("kind") == "sanity":
            table.append([record["id"], "-", "-", "-", "-", "%d/%d" % (summary.get("runs_valid", 0), summary.get("runs_total", 0)), "-", "%d of %d checks passed" % (summary.get("checks_passed", 0), summary.get("checks_total", 0))])
            continue
        table.append(
            [
                record["id"],
                num(_median(record, "prompt_tokens"), 0),
                num(_median(record, "ttft_s"), 2),
                num(_median(record, "prefill_tok_s"), 0),
                num(_median(record, "decode_tok_s")),
                "%d/%d" % (summary.get("runs_valid", 0), summary.get("runs_total", 0)),
                _spread(record),
                _notes(record),
            ]
        )
    return table


def _align(table: List[List[str]]) -> List[str]:
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    lines = []
    for index, row in enumerate(table):
        cells = [row[i].ljust(widths[i]) if i in (0, len(row) - 1) else row[i].rjust(widths[i]) for i in range(len(row))]
        lines.append("  ".join(cells).rstrip())
        if index == 0:
            lines.append("  ".join("-" * w for w in widths))
    return lines


def headline_lines(result: Dict[str, Any]) -> List[str]:
    head = result.get("headline") or {}
    lines: List[str] = []
    if head.get("writing_tok_s"):
        lines.append("Writing speed        %s tok/s, about %s words per second (%s-timed)" % (num(head["writing_tok_s"]), num(head["writing_tok_s"] * WORDS_PER_TOKEN, 0), head.get("writing_source") or "client"))
    reading = head.get("reading_tok_s") or {}
    if reading:
        lines.append("Reading speed        " + " | ".join("%s tok/s at %s" % (num(v, 0), k.upper()) for k, v in reading.items()))
    reading_text = head.get("reading_chars_s") or {}
    if reading_text:
        lines.append("Reading, as text     " + " | ".join("%s chars/s at %s" % (num(v, 0), k.upper()) for k, v in reading_text.items()) + " (use this line, not tok/s, to compare different models)")
    fit = head.get("reading_fit") or {}
    if fit:
        lines.append("Reading, as a rule   about %s s per request, then %s tok/s (from %d prompt sizes; the smaller ones predict the largest within %.0f%%)" % (
            num(fit["fixed_s"], 2), num(fit["marginal_tok_s"], 0), fit["points"], max(1.0, abs(fit.get("holdout_error_pct") or 0.0))))
    steps = head.get("reading_steps") or []
    if steps:
        lines.append("Reading, in steps    " + " | ".join("%s to %s: %s tok/s" % (step["from"].upper(), step["to"].upper(), num(step["tok_s"], 0)) for step in steps) + " (extra tokens over extra seconds)")
    if head.get("chat_first_token_s") is not None:
        lines.append("Short chat           first token after %s s" % num(head["chat_first_token_s"], 2))
    labels = (
        ("quick_question_300_out", "Quick question       %s s to finish a 300-token answer"),
        ("code_review_16k_in_500_out", "Code review          %s s to read a 16K context and write 500 tokens"),
        ("followup_16k_500_out", "Follow-up question   %s s on the same context for 500 tokens"),
        ("big_read_64k_in_1000_out", "Big read             %s s to read a 64K context and write 1,000 tokens"),
    )
    times = head.get("request_seconds") or {}
    for key, template in labels:
        if times.get(key) is not None:
            lines.append(template % num(times[key]))
    share = head.get("followup_cached_share")
    if isinstance(share, (int, float)):
        lines.append("Follow-up cache      %.0f%% of the follow-up prompt came from the cache%s" % (share * 100, (", first token x%.0f sooner" % head["cache_speedup"]) if head.get("cache_speedup") else ""))
    drift = head.get("drift") or {}
    if drift.get("ratio"):
        lines.append("Start versus end     writing speed at the end was %.0f%% of the start" % (drift["ratio"] * 100))
    sensitivity = head.get("repetition_speedup") or {}
    if sensitivity:
        parts = ["%s x%.2f" % ("reading" if metric.startswith("prefill") else "writing", ratio) for metric, ratio in sensitivity.items()]
        lines.append("Repetitive text      %s versus varied text (above about 1.15 means repetition flatters this runtime)" % ", ".join(parts))
    return lines


def terminal(result: Dict[str, Any]) -> str:
    out = [""]
    out += _align(rows(result))
    head = headline_lines(result)
    if head:
        out += ["", "What this means"] + ["  " + line for line in head]
    verdict = result.get("verdict") or {}
    out += ["", "Result quality: %s" % (verdict.get("status") or "unknown")]
    for problem in verdict.get("problems") or []:
        out.append("  PROBLEM  %s" % problem)
    for caution in verdict.get("cautions") or []:
        out.append("  caution  %s" % caution)
    for note in result.get("notes") or []:
        out.append("  note     %s" % note)
    return "\n".join(out)


def markdown(result: Dict[str, Any]) -> str:
    runtime, model = result.get("runtime") or {}, result.get("model") or {}
    settings = result.get("settings") or {}
    lines = [
        "### %s" % (result.get("label") or model.get("id") or "llmbench result"),
        "",
        "- System: %s" % describe(result.get("system") or {}),
        "- Runtime: %s%s; model `%s`; context %s" % (
            display_name(runtime.get("name")), (" " + str(runtime["version"])) if runtime.get("version") else "", model.get("id"),
            "{:,}".format(settings["context_tokens"]) if settings.get("context_tokens") else "unknown"),
        "- Suite `%s`, protocol %s, %s corpus, temperature 0, %s" % (result.get("suite"), (result.get("tool") or {}).get("protocol"), settings.get("corpus"), result.get("created_utc")),
        "",
    ]
    table = rows(result)
    lines.append("| " + " | ".join(table[0]) + " |")
    lines.append("|" + "|".join(["---"] + ["---:"] * 5 + ["---", "---"]) + "|")
    for row in table[1:]:
        lines.append("| " + " | ".join(cell.replace("|", "/") for cell in row) + " |")
    head = headline_lines(result)
    if head:
        lines += [""] + ["- " + " ".join(line.split()) for line in head]
    verdict = result.get("verdict") or {}
    lines += ["", "Result quality: **%s**" % (verdict.get("status") or "unknown")]
    for item in (verdict.get("problems") or []) + (verdict.get("cautions") or []):
        lines.append("- %s" % item)
    return "\n".join(lines) + "\n"


def csv(result: Dict[str, Any]) -> str:
    """Export one row per scenario, keeping machine-readable run medians."""
    buffer = io.StringIO(newline="")
    writer = csv_module.writer(buffer)
    writer.writerow(("model", "runtime", "suite", "scenario", "prompt_tokens", "first_token_s", "read_tok_s", "write_tok_s", "runs_valid", "runs_total", "verdict"))
    runtime = result.get("runtime") or {}
    model = result.get("model") or {}
    for record in result.get("scenarios") or []:
        summary = record.get("summary") or {}
        writer.writerow((
            model.get("id"), runtime.get("name"), result.get("suite"), record.get("id"),
            _median(record, "prompt_tokens"), _median(record, "ttft_s"), _median(record, "prefill_tok_s"),
            _median(record, "decode_tok_s"), summary.get("runs_valid"), summary.get("runs_total"),
            (result.get("verdict") or {}).get("status"),
        ))
    return buffer.getvalue()


def compare(base: Dict[str, Any], new: Dict[str, Any]) -> str:
    """A/B two result files. Differences smaller than the run-to-run spread are noise."""
    out: List[str] = []
    for which, result in (("A", base), ("B", new)):
        runtime = result.get("runtime") or {}
        out.append("%s: %s | %s | %s | suite %s" % (
            which, result.get("label") or "(no label)", " ".join(str(part) for part in (display_name(runtime.get("name")), runtime.get("version")) if part),
            (result.get("model") or {}).get("id"), result.get("suite")))
    tool_a, tool_b = base.get("tool") or {}, new.get("tool") or {}
    if tool_a.get("protocol") != tool_b.get("protocol") or tool_a.get("workload") != tool_b.get("workload"):
        out.append("NOT COMPARABLE: protocol or workload versions differ (%s/%s vs %s/%s)." % (tool_a.get("protocol"), tool_a.get("workload"), tool_b.get("protocol"), tool_b.get("workload")))
        return "\n".join(out)
    if tool_a.get("protocol") != PROTOCOL_VERSION:
        out.append("note: these files use protocol %s; this tool is %s." % (tool_a.get("protocol"), PROTOCOL_VERSION))
    differences = []
    for key, label in (("corpus", "corpus"), ("context_tokens", "context window"), ("extra_body", "request options")):
        a, b = (base.get("settings") or {}).get(key), (new.get("settings") or {}).get(key)
        if a != b:
            differences.append("%s: %s vs %s" % (label, a, b))
    if (base.get("model") or {}).get("id") != (new.get("model") or {}).get("id"):
        differences.append("model differs")
    if differences:
        out.append("differences besides what you changed: " + "; ".join(differences))
    for which, result in (("A", base), ("B", new)):
        status = (result.get("verdict") or {}).get("status")
        if status and status != "clean":
            out.append("note: result %s is '%s'" % (which, status))
    table = [["Scenario", "Metric", "A", "B", "Change", "Counts above", "Runs", "Verdict"]]
    lookup = {record["id"]: record for record in new.get("scenarios") or []}
    for record in base.get("scenarios") or []:
        other = lookup.get(record["id"])
        if not other or record.get("kind") in ("sanity", "soak") or record.get("id") == "control":
            continue
        for metric, label in (("ttft_s", "first token s"), ("prefill_tok_s", "read tok/s"), ("decode_tok_s", "write tok/s")):
            stats = compare_stats(metric, _stat(record, metric), _stat(other, metric))
            if not stats:
                continue
            table.append([record["id"], label, num(stats["base"], 2), num(stats["new"], 2), "%+.1f%%" % stats["delta_pct"], "%.1f%%" % stats["noise_pct"], "%d vs %d" % tuple(stats["runs"]), stats["verdict"]])
    if len(table) == 1:
        out.append("No scenario exists in both files.")
        return "\n".join(out)
    out += [""] + _align(table)
    # One line a newcomer can read without the table: how often each metric moved.
    tally: Dict[str, Dict[str, int]] = {}
    for row in table[1:]:
        counts = tally.setdefault(row[1], {})
        key = row[-1].split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    parts = []
    for metric, counts in tally.items():
        total = sum(counts.values())
        moved = ", ".join("%s in %d" % (key, counts[key]) for key in ("better", "worse") if counts.get(key))
        parts.append("%s: %s of %d scenarios" % (metric, moved if moved else "no change that counts", total) if moved else "%s: no change that counts in %d scenarios" % (metric, total))
    out += ["", "In short (B against A): " + "; ".join(parts) + "."]
    out += [
        "",
        "A change counts only above the 'Counts above' column: the gap that run-to-run variation alone would",
        "produce less than about one time in twenty, and never under 2%. With two or three runs that bar is",
        "high. To resolve small differences, repeat both results with --runs 6 or more.",
    ]
    return "\n".join(out)


def stability_label(result: Dict[str, Any]) -> str:
    labels = [stability(_stat(record, "decode_tok_s")) for record in result.get("scenarios") or [] if not record.get("skipped")]
    for label in ("unstable", "noisy", "ok", "stable"):
        if label in labels:
            return label
    return "no data"
