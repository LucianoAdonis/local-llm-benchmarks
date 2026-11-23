# Contributing

Issues and pull requests are welcome. Include enough evidence for another person to reproduce a claim.

## New benchmark runs

- Add results under `results/YYYY-MM-DD/<workload>/`.
- Include one JSON per run plus a human-readable summary.
- Record hardware, OS, driver, storage, Strata/engine versions, model source and revision, quantization, context capacity, actual prompt tokens, output limit, temperature, cache state, and background GPU load.
- Keep prefill and decode separate. Identify whether the measurement came from an engine log or client stream.
- Use the provided redactor and inspect every public artifact. Do not upload weights, tokens, private paths, real repository source, or unredacted logs.
- Label one-off long-context runs as single observations. Do not call speed a quality score.

## Code changes

Keep the benchmark workload deterministic except for its unique run marker. Preserve raw per-run data and avoid rewriting results to make a change appear faster. Document any protocol change and use a new protocol version if metrics become incompatible.
