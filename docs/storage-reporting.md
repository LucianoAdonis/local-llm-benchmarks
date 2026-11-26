# Reporting a storage benchmark

Use the same host, GPU, driver, runtime build, exact model files and quantization, context, output cap, and prompt corpus. Confirm each model and its shared files resolve to the intended physical drive. Keep background load and power settings comparable. Save one JSON result per drive and use the same workload and protocol versions.

Run the same command on each newly started runtime. For DeepSeek 0.1.59, pass that run's engine log.

    llmbench run --url http://127.0.0.1:8098 --context 32768 --suite quick --scenarios ctx-4k,ctx-16k --runs 3 --fixed-text --engine-log ENGINE.log --output RUN.json

Record actual prompt tokens, cache reuse, TTFT, prefill, decode, timing source, repeats, spread and validity flags. Treat startup, first requests and warmed inference as separate measurements. Record the cache setup for each launch and alternate drive order across repetitions if estimating an effect. A process restart can leave OS caches warm. Report shorter preload time separately from any change in generation speed.

    llmbench compare KINGSTON.json T500.json
    llmbench export T500.json --format csv
    llmbench export T500.json --format markdown

Keep the original JSON next to any export. Review results for private paths before publishing. See [storage topology](storage-follow-up.md) for the hardware baseline.

Use the [storage A/B report template](storage-report-template.md) to publish a consistent summary. Check actual token counts even with fixed seed: runtime token accounting and adaptive prompt sizing can produce small differences.
