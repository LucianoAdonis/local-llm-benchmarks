# Benchmark results — 2026-11-23

All JSON files in `coding-context/` are per-run evidence copied from the local Strata test directory and sanitized with this repository's `scripts/sanitize_results.py`. No model weights, API credentials, user-home paths, local engine logs, or real project source are included.

See the [model catalog](../../docs/model-catalog.md) for parameter counts and exact file sizes, [expected performance guide](../../docs/expected-performance.md) for interpreting tok/s, [quantization primer](../../docs/quantization-primer.md), and [storage follow-up plan](../../docs/storage-follow-up.md).

## Machine and test configuration

- Ryzen 9 9950X3D, 16 cores
- NVIDIA GeForce RTX 5090, 32 GB VRAM; driver 621.01
- 128 GB RAM; Windows 11 Pro
- 2 TB Kingston FURY Renegade G5 PCIe 5.0 NVMe, model files on C:; owner-reported first CPU-connected `M2A_CPU` slot
- Crucial T500 4 TB not installed yet; planned comparison slot is chipset-connected `M2D_SB`
- Strata 0.2.20 / engine 0.1.66 for Inkling and Qwen
- Strata 0.2.13 / DeepSeek engine 0.1.59 for DeepSeek V4.1 Flash IST-DAS 2.00 bpw (the model was marked retired in Strata 0.2.20)
- Temperature 0; 100-token output cap; synthetic multi-file Python code-review workload

## Long-context comparison

| Model | Configured context | Prompt tokens | Prefill tok/s | Decode tok/s | Repeats |
|---|---:|---:|---:|---:|---:|
| DeepSeek 2.00 bpw | 128K | 50,119 | 2,319 (engine) | 23.1 (engine) | 2 |
| Inkling SQ-10 | 128K | 64,513 | 3,943 (client proxy) | 64.9 (client stream) | 2 |
| Inkling UD-Q4_K_M, DSpark off | 128K | 64,513 | 2,716 (client proxy) | 86.5 (client stream) | 2 |
| Qwen3.6 UD-Q4_K_XL | 128K | 54,901 | 4,158 (engine) | 92.6 (engine) | 2 |
| DeepSeek 2.00 bpw | 256K | 250,119 | 2,506 (engine) | 20.9 (engine) | 1 |

DeepSeek's near-full request used 250,119 prompt tokens and a 100-token output cap, about 95.5% of the configured 262,144-token window. Client time to first content was 102.6 seconds; total request wall time was 104.1 seconds.

## 32K context tests

### DeepSeek V4.1 Flash, IST-DAS 2.00 bpw

| Prompt depth | Prefill tok/s | Decode tok/s | Repeats | Evidence |
|---:|---:|---:|---:|---|
| 4,494 | 838.0 | 26.9 | 3 | [JSON](coding-context/deepseek-2bpw-32k-coding-4k-fresh-engine-2026-11-23.json) |
| 15,119 | 1,510.0 | 27.2 | 3 | [JSON](coding-context/deepseek-2bpw-32k-coding-16k-fresh-engine-2026-11-23.json) |
| 27,619 | 1,426.5 | 11.6 | 2 | [JSON](coding-context/deepseek-2bpw-32k-coding-nearfull-unique-repeat-2026-11-23.json) |

### Inkling-2-Mini variants

4K results use a 5,748-token prompt, three runs each. Decode is client stream rate; end-to-end is the 100 output tokens divided by total request wall time.

| Variant | Decode-window tok/s | End-to-end tok/s | Evidence |
|---|---:|---:|---|
| SQ-10 | 170.2 | 58.8 | [JSON](coding-context/inkling-sq10-32k-coding-4k-2026-11-23.json) |
| SQ-15 | 141.0 | 56.0 | [JSON](coding-context/inkling-sq15-32k-coding-4k-2026-11-23.json) |
| SQ-20 | 134.2 | 56.6 | [JSON](coding-context/inkling-sq20-32k-coding-4k-2026-11-23.json) |
| UD-Q3_K_XL, DSpark off | 99.9 | 41.8 | [JSON](coding-context/inkling-ud-q3xl-32k-coding-4k-2026-11-23.json) |
| UD-Q4_K_M, DSpark off | 119.9 | 39.2 | [JSON](coding-context/inkling-ud-q4km-32k-coding-4k-2026-11-23.json) |

Longer Inkling results:

| Variant | Prompt tokens | Decode-window tok/s | End-to-end tok/s | Evidence |
|---|---:|---:|---:|---|
| SQ-10 | 16,213 | 143.9 | 26.7 | [JSON](coding-context/inkling-sq10-32k-coding-16k-2026-11-23.json) |
| SQ-10 | 27,483 | 120.5 | 15.0 | [JSON](coding-context/inkling-sq10-32k-coding-nearfull-2026-11-23.json) |
| UD-Q4_K_M | 16,213 | 113.3 | 17.3 | [JSON](coding-context/inkling-ud-q4km-32k-coding-16k-2026-11-23.json) |
| UD-Q4_K_M | 27,483 | 105.5 | 10.3 | [JSON](coding-context/inkling-ud-q4km-32k-coding-nearfull-2026-11-23.json) |

### Qwen3.6-35B-A3B UD-Q4_K_XL

Engine-log results, 100 output tokens per run:

| Prompt tokens | Prefill tok/s | Decode tok/s | Repeats | Evidence |
|---:|---:|---:|---:|---|
| 4,896 | 10,784.1 | 309.6 | 3 | [JSON](coding-context/qwen36-q4xl-32k-coding-4k-engine-run2-2026-11-23.json) |
| 16,541 | 9,452.0 | 225.7 | 3 | [JSON](coding-context/qwen36-q4xl-32k-coding-16k-engine-2026-11-23.json) |
| 27,501 | 7,327.7 | 163.1 | 1 | [JSON](coding-context/qwen36-q4xl-32k-coding-nearfull-engine-2026-11-23.json) |

## Interpretation and comparison limits

- The same synthetic source produces different token counts with different model tokenizers; compare actual prompt token counts, not section count.
- DeepSeek and Qwen figures are engine-log timings. Inkling figures are client-observed; its prefill proxy includes client/API overhead and its decode-window rate can be affected by stream buffering.
- The DeepSeek engine counted 83 internal generated tokens for some 100-token API completions because it uses internal generation passes. Raw per-run JSON preserves both counts.
- The 256K Reddit reference uses a custom llama.cpp patch and mixed Q8/Q4/Q2 quant; it is not an apples-to-apples comparison.
- Speed is not code quality. The task is synthetic and does not grade correctness.
- A Crucial T500 before/after storage comparison remains future work. These numbers are the pre-install baseline.

## Result files

See the 20 JSON records in [`coding-context/`](coding-context/). The JSON is the evidence; this page is a readable summary.
