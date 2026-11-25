# Synthetic coding-context prompt

This describes the v1 workload behind the 2026-11-23 baseline. `llmbench` uses a different, varied workload; see [docs/benchmark-design.md](../docs/benchmark-design.md#the-workload).

The benchmark client generates the prompt in `scripts/strata_coding_context_benchmark.py`. The two engine-log clients use a close variant: slightly different instruction wording, and file and class names that include the run number (519 characters per section instead of 503). Inkling was measured with the first, DeepSeek and Qwen with the second. Each section is a synthetic Python worker module with a section number; the run number is included at the start of every request.

Two properties of this workload matter when reading the results. It is highly repetitive: eight of ten lines in every section are identical. And the run number restarts at 1 for every invocation, so a later invocation resends prompts an engine may already have cached.

The instruction asks a model to review only the supplied excerpts for concrete correctness, reliability, and performance risks; cite file names; and give a concise prioritized engineering review. It does not include any real project source.

Do not hand-edit the generated prompt for a comparison run. Change `--sections` to vary the workload size and use API-reported `prompt_tokens` to record the actual context depth. Different model tokenizers produce different prompt-token counts from the same source text.
