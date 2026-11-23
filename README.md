# Local LLM Hardware Benchmarks

Repeatable local-inference benchmarks for coding workloads. This repository records model, quantization, context depth, prompt ingestion, generation speed, settings, machine details, and per-run JSON so hardware or software changes can be compared later.

This first public run measures one Windows PC across Strata models from short prompts through a near-full 256K DeepSeek context. It is a performance record, not a model-quality ranking.

## Baseline machine

| Component | Configuration |
|---|---|
| CPU | AMD Ryzen 9 9950X3D (16 cores) |
| GPU | NVIDIA GeForce RTX 5090, 32 GB VRAM |
| System memory | 128 GB |
| OS | Windows 11 Pro |
| Storage during run | Kingston FURY Renegade G5 2 TB PCIe 5.0 NVMe in the first CPU-connected M.2 slot (`M2A_CPU`, owner-reported); Crucial T500 had not yet been installed |
| Strata | 0.2.20 / engine 0.1.66 for Inkling and Qwen; DeepSeek compatibility install 0.2.13 / engine 0.1.59 |

Models were installed locally; this repository contains no model weights. See [the Strata replication playbook](docs/strata-replication.md) and [copy-ready model requests](prompts/model-download-requests.md).
An AI-assistant-ready procedure is also available as [`skills/strata-local-benchmark/SKILL.md`](skills/strata-local-benchmark/SKILL.md).

## Highlights

| Model / variant | Context profile | Actual prompt tokens | Prefill | Decode |
|---|---:|---:|---:|---:|
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 256K | 250,119 | 2,506 tok/s | 20.9 tok/s |
| Qwen3.6-35B-A3B UD-Q4_K_XL | 128K | 54,901 | 4,158 tok/s | 92.6 tok/s |
| Inkling-2-Mini UD-Q4_K_M | 128K | 64,513 | 2,716 tok/s* | 86.5 tok/s* |
| Inkling-2-Mini SQ-10 | 128K | 64,513 | 3,943 tok/s* | 64.9 tok/s* |

DeepSeek and Qwen speeds are from engine timing logs. Inkling values marked `*` are client-observed stream rates; Inkling prefill is a proxy that includes client/API overhead. See [all results and caveats](results/2026-11-23/README.md).

The DeepSeek 256K run read 250,119 prompt tokens plus a 100-token output cap (about 95.5% of its 262,144-token window). It took 102.6 seconds to first text. Long-context speed is therefore a tradeoff: the model continued generating at about 21 tok/s, but reading the prompt took most of the wait.

## Models and files

| Model | Parameters | Tested file/quant | Local download size |
|---|---|---|---:|
| [DeepSeek V4.1 Flash 1017](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF) | 763.2B total; 6/384 routed experts active per token | IST-DAS IQ2_XXS backbone, 2.00 bpw, plus Engram and DSpark | 256.81 GB total pack |
| [Inkling-2-Mini](https://huggingface.co/thinkingmachines/Inkling-2-Mini) | 26.4B total; 3.4B active | [native SQ-10 / SQ-15 / SQ-20](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata); [UD-Q3_K_XL / UD-Q4_K_M GGUF](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) | 10.47 / 14.35 / 19.35 / 13.63 / 16.61 GB |
| [Qwen3.6-35B-A3B](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | 35B total; 3B active | [UD-Q4_K_XL MTP GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/blob/main/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf) | 22.85 GB |

The file sizes above are measured local downloads; DeepSeek's package includes support files in addition to its 2.00 bpw backbone. See the [model catalog](docs/model-catalog.md) for exact filenames, GB/GiB breakdowns, parameter explanations, and direct file links. Model licenses and acceptable-use terms belong to their publishers.

## Read the results and plan the next tuning step

- [How to read tok/s and what to expect on this PC](docs/expected-performance.md)
- [Quantization primer: 4-bit versus DeepSeek at 2.00 bpw](docs/quantization-primer.md)
- [Storage topology and planned Kingston-versus-T500 test](docs/storage-follow-up.md)

## Reproduce

1. Install Strata and download the same model variants. Follow [docs/strata-replication.md](docs/strata-replication.md) and use the exact model requests in [prompts/model-download-requests.md](prompts/model-download-requests.md).
2. Record a clean baseline with Strata's standard suite. Close GPU-heavy programs, start a fresh engine, and save the JSON output.
3. Run this repository's coding-context harness against Strata's OpenAI-compatible endpoint. The harness records actual token usage, time to first content, request wall time, and client stream decode-window rate.
4. For DeepSeek and Qwen, optionally collect engine-log timings using the supplied parsers. Label engine timings and client estimates separately.
5. Keep context capacity, prompt depth, model revision, quantization, Strata/engine versions, driver, cache state, and background load in every comparison.

Example (PowerShell, after the profile is running):

```powershell
python scripts/strata_coding_context_benchmark.py `
  --url http://127.0.0.1:8080/v1/chat/completions `
  --model inkling-2-mini-sq-10 `
  --sections 100 --runs 3 --max-tokens 100 `
  --context 131072 --timeout 600 `
  --profile inkling-sq10-128k `
  --output results/my-run.json
```

`--sections` controls the synthetic repository size; model tokenizers count the same text differently. Use the reported `prompt_tokens` as the actual input depth. For engine-log timing collection, see [the playbook](docs/strata-replication.md#coding-context-suite).

## Benchmark design

- Keep prompt prefill and token generation as separate measurements.
- Use unique run markers to reduce accidental prefix-cache reuse; record any tokens the engine says it reused.
- Report prompt tokens, output tokens, time to first content, total wall time, and per-run values, not only one aggregate speed.
- Run short, medium, and long prompt depths. A configured context window is capacity; it is not the same as the number of tokens actually supplied.
- Save raw JSON and report medians/ranges. Use one run only for very expensive near-capacity prompts and label it clearly.
- Treat speed and quality as separate evaluations.

The structure borrows useful conventions from [Strata's community benchmark protocol](https://github.com/Niko1221/Strata/blob/main/docs/COMMUNITY_BENCHMARKS.md) (per-run JSON, machine/settings metadata, anonymization, comparisons) and the context-depth split used by [llama-benchy](https://github.com/eugr/llama-benchy) (prompt processing versus generation across depths). The harnesses here are original scripts adapted from this machine's experiment; no benchmark tool code was copied from those projects.

## Known limitations

- The Reddit RTX 5090 / 9950X3D DeepSeek comparison uses a different mixed quant and a custom llama.cpp patch. Its reported 256K results are orientation only, not a direct comparison.
- The DeepSeek GGUF-pack run used Strata 0.2.13 / engine 0.1.59 because the newer local Strata release marked this model retired.
- Inkling UD-Q4_K_M was run with DSpark disabled due to a current Strata GGUF + DSpark missing-tensor issue ([Strata issue #6762](https://www.stratat.com/en/issues/6762)).
- The synthetic code-review input checks serving behavior, not code-review correctness.
- The initial 82.3 tok/s DeepSeek client-stream estimate was inflated by stream buffering. It is superseded; use the engine-timed JSON results in this repository.

## Repository layout

- `docs/` — methodology and Strata replication playbook.
- `prompts/` — copy-ready model install requests and fixed workload prompt description.
- `scripts/` — benchmark clients, engine-log parsers, and a public-results redactor.
- `results/2026-11-23/` — sanitized metadata, summary, and per-run JSON.

## License and attribution

Original documentation and scripts are released under the MIT License. This does not license, redistribute, or change the terms of any model weights, Strata, llama.cpp, or other upstream software. See [LICENSE](LICENSE).
