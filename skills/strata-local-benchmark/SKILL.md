---
name: strata-local-benchmark
description: Install or configure Strata models and run repeatable local coding-context speed benchmarks. Use when comparing context depth, model quantization, runtime versions, GPU, RAM, or storage changes.
---

# Strata local benchmark skill

Use this runbook when the user wants a Strata setup, model-download plan, or reproducible local inference benchmark.

## Required behavior

- Separate model setup from benchmarking. Identify the exact model source, quantization, Strata/engine version, and context capacity.
- Check current Strata command help and official install docs before using release-sensitive flags.
- Never present a model’s speed result as a coding-quality result.
- Keep prompt ingestion (prefill) and generation (decode) separate. Label engine timings separately from client-observed estimates.
- Record actual API prompt-token counts and output counts. A configured context is not an actual prompt depth.
- Use a unique nonce per run. Report reused prompt tokens if the engine exposes them.
- Capture at least three repeated runs for low-cost cases; for expensive long-context cases, use fewer runs and clearly label the count and range.
- Do not copy model weights into the repository.
- Before publishing JSON, redact local paths, hostnames, local addresses, API keys, and private prompts. Inspect the redacted files manually.
- Use one active model at a time unless concurrency is the test itself. Stop the model after the benchmark and verify the runtime status.

## Workflow

1. Read `docs/strata-replication.md` and `prompts/model-download-requests.md`.
2. Install Strata from its official release path and confirm `strata --version`, `strata doctor`, and `strata models list`.
3. Select the exact model variant from a managed Strata catalog or the linked model card. For pack formats, install all required support files. Do not substitute a similarly named quantization.
4. Create a new named profile for each context size. Preserve the original profile and verify config/model paths before loading it.
5. Record a baseline with `strata bench run` when the installed version supports it.
6. Run `scripts/strata_coding_context_benchmark.py` with a fixed workload and actual token-count reporting. Use the engine-log parser for DeepSeek/Qwen where logs expose engine timings.
7. Save each JSON result to a new directory, use `scripts/sanitize_results.py` to make a public copy, review it, then write a summary with hardware, runtime, model, settings, measurement source, repetitions, and caveats.
8. Stop the runtime; verify GPU memory returns to the idle baseline.

## Result interpretation

- Compare only runs with matching model/quantization, runtime, prompt depth, context profile, cache state, output limit, and background load.
- TTFC includes prefill and server/client overhead. Decode-window throughput from an OpenAI stream is not necessarily the engine’s kernel decode rate.
- Include per-run JSON, not only a selected best speed. Use median and range for repeats.
- For long context, report context capacity and actual prompt size separately.
- For code quality, design a separate correctness set with known expected outputs and inspect answers.

See `docs/methodology.md` for definitions and `results/2026-11-23/README.md` for the first machine’s results.
