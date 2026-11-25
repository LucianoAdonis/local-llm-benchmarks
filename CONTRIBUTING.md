# Contributing

Issues and pull requests are welcome. Include enough evidence for another person to reproduce a claim.

## New benchmark runs

Measure with `llmbench` ([docs/llmbench.md](docs/llmbench.md)). On Windows type `py` where the commands say `python3`.

```bash
python3 -m llmbench run --suite standard --label "what you ran and what you changed"
```

- Copy the result file from `local-results/` to `results/YYYY-MM-DD/` and add the Markdown summary printed by `python3 -m llmbench report --markdown <file>`.
- Put in `--label` what the tool cannot see: the exact model file and quantization, runtime settings such as drafting, and what changed since your last run.
- Run `python3 -m llmbench sanitize --check <file>` and read the file yourself. Do not upload weights, tokens, private paths, real repository source, or unredacted logs.
- Results marked `invalid` are not accepted. Results marked `usable with cautions` are fine: keep the cautions in the summary.
- Do not call speed a quality score.
- Do not put results from different protocol or workload versions in one table. The v1 files under `results/2026-11-23/` stay as they are.

## Code changes

- `python3 -m unittest` and `python3 -m llmbench selftest` must pass.
- The tool must stay dependency-free and run on Python 3.9, on Windows, macOS and Linux.
- Changing the generated text changes every published workload: bump `WORKLOAD_VERSION` in `llmbench/__init__.py` and update the pinned hashes in `tests/test_workload.py`.
- Changing what a metric means: bump `PROTOCOL_VERSION`. Results from different versions are never compared.
- Preserve raw per-run data and never rewrite results to make a change appear faster.
