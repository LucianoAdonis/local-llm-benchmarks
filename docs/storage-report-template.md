# Storage A/B report template

- Date and run order:
- PC, OS, GPU and driver:
- SSD models, firmware, physical slots and negotiated links:
- Runtime, engine, llmbench version and workload protocol:
- Model, quantization and checksum manifest:
- Context, output cap, scenarios, seed and exact command:
- Cache state, warm-up, other workloads, power and temperatures:
- Source paths checked locally for weights and shared files:

| Drive | Scenario | Actual prompt tokens | Valid / attempted | TTFT (s) | Prefill (tok/s) | Decode (tok/s) | Timing source | Spread and flags |
|---|---|---:|---:|---:|---:|---:|---|---|

Record preload bytes and seconds separately. Attach sanitized JSON and the compare output. Report practical effect and which variables changed together. Save per-run prompt token counts and cache reuse when judging comparability.
