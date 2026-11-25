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
- Measure with `python3 -m llmbench` (type `py` instead of `python3` on Windows; see `docs/llmbench.md`). It works against Strata, LM Studio, llama.cpp and Ollama on Windows, macOS and Linux. The `scripts/strata_*.py` files are the v1 method, kept only to reproduce the 2026-11-23 baseline.
- Keep prompt ingestion (prefill) and generation (decode) separate. Label engine timings separately from client-observed estimates.
- Never benchmark with a repeated prompt or a repetitive text: caches and content-dependent engines make it faster than real use.
- Record actual API prompt-token counts and output counts. A configured context is not an actual prompt depth.
- Use a unique random marker per run. Report reused prompt tokens if the engine exposes them, and discard a fresh run that reused any.
- Capture at least three repeated runs after a warm-up for low-cost cases; for expensive long-context cases, use at least two and clearly label the count and range.
- Do not copy model weights into the repository.
- Before publishing JSON, redact local paths, hostnames, local addresses, API keys, and private prompts. Inspect the redacted files manually.
- Use one active model at a time unless concurrency is the test itself. Stop the model after the benchmark and verify the runtime status.

## Workflow

1. Install `llmbench` with the steps in `docs/model-setup.md`, then run `llmbench doctor` to capture the machine and runtime baseline. Read `docs/strata-replication.md` and `prompts/model-download-requests.md`.
2. Install Strata from its official release path and confirm `strata --version`, `strata doctor`, and `strata models list`.
3. Select the exact model variant from a managed Strata catalog or the linked model card. For pack formats, install all required support files. Do not substitute a similarly named quantization.
4. Create a new named profile for each context size. Preserve the original profile and verify config/model paths before loading it.
5. Record a baseline with `strata bench run` when the installed version supports it.
6. Run `python3 -m llmbench doctor`, then `python3 -m llmbench run --url http://127.0.0.1:8080 --context <profile context> --suite standard --label "<Strata and engine versions, model file, drafting setting>"`. For the retired DeepSeek engine add `--engine-log <profile log>`.
7. Read the result quality line. Fix anything marked PROBLEM and re-run. Use `python3 -m llmbench compare <before> <after>` for an A/B, changing one thing at a time.
8. Check the saved file with `python3 -m llmbench sanitize --check <file>`, review it, then write a summary with `python3 -m llmbench report --markdown <file>` plus the caveats.
9. Stop the runtime; verify GPU memory returns to the idle baseline.

## Result interpretation

- Compare only runs with matching model/quantization, runtime, prompt depth, context profile, cache state, output limit, and background load.
- TTFC includes prefill and server/client overhead. Decode-window throughput from an OpenAI stream is not necessarily the engine’s kernel decode rate.
- Include per-run JSON, not only a selected best speed. Use median and range for repeats.
- For long context, report context capacity and actual prompt size separately.
- For code quality, design a separate correctness set with known expected outputs and inspect answers.

See `docs/benchmark-design.md` for definitions and the review of the first method, `docs/start-here.md` for what to expect, and `results/2026-11-23/README.md` for the first machine’s results.
