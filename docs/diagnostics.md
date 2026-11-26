# Machine and benchmark diagnostics

Use the CLI as the data source for an app. Start with a live snapshot, then attach saved results from controlled runs.

    llmbench diagnose --output local-results/machine.json
    llmbench diagnose results/2026-11-26-storage/*.json --output local-results/diagnostic.json

The command emits JSON to stdout when no output path is supplied. The schema is llmbench-diagnostic/1. It contains live system and state data, preflight warnings, saved run summaries, evidence-backed findings, and a measurement catalog. A finding references its source and optional zero-based run index. Its measurement ID links to a suggested follow-up. Missing readings indicate unavailable data. GPU readings in state are snapshots at the reported time.

A future app can present four steps:

1. **Check the computer.** Show hardware, available memory, power, temperatures and GPU usage where available.
2. **Run a baseline.** Select the loaded runtime and model. Use the quick suite and keep the raw JSON. Display TTFT, prefill, decode, repeat count and spread.
3. **Change one setting.** Repeat with a smaller context or quantization if memory pressure was observed. Use identical scenarios for the A/B, then run longer prompts separately.
4. **Compare and export.** Call llmbench compare for the noise-aware comparison. Attach the JSON and export CSV or Markdown. Keep measurement validity and caveats visible.

Disk read throughput, cold startup and task correctness require separate measurements. Follow the [storage procedure](storage-reporting.md) for a drive comparison. Use the same task and acceptance checks to compare end-to-end coding speed.
