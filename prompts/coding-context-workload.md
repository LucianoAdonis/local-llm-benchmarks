# Synthetic coding-context prompt

The benchmark client generates the prompt in `scripts/strata_coding_context_benchmark.py` and the engine-log clients use the same construction. Each section is a synthetic Python worker module with a unique section number; a unique benchmark nonce is included at the start of every request.

The instruction asks a model to review only the supplied excerpts for concrete correctness, reliability, and performance risks; cite file names; and give a concise prioritized engineering review. It does not include any real project source.

Do not hand-edit the generated prompt for a comparison run. Change `--sections` to vary the workload size and use API-reported `prompt_tokens` to record the actual context depth. Different model tokenizers produce different prompt-token counts from the same source text.
