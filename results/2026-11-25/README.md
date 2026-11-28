# Runtime iteration — 2026-11-25

> **Correction, 2026-11-28.** Every `llmbench` run below had model thinking on, and within each output cap the models wrote only thinking. The rates are valid as generated tokens but are not the speed at which answers appear. The Strata and Bionic tables also use different model files and timing sources, so together they suggested that Strata was about twice as fast as LM Studio. On one file with thinking off the two are close, and LM Studio is faster with parallel requests. See [2026-11-28](../2026-11-28/README.md).

This iteration exercises LLMBench on the same PC used for the November 23 baseline. It updates Strata's inference components, benchmarks two Strata models with the native suite, and benchmarks the same model family through Bionic's native API. Raw Strata reports remain local because they include machine paths and generated output; the sanitized summary JSON files here contain the metrics needed for comparison.

## Machine and software

- CPU: AMD Ryzen 9 9950X3D, 16 cores
- GPU: NVIDIA GeForce RTX 5090, 32 GB VRAM; driver 621.01
- RAM: 128 GB
- OS: Windows 11 Pro, build 26300
- Model SSD: Kingston FURY Renegade G5 2 TB, OS model `KINGSTON SFYR2S2T0`; user-reported first CPU-connected slot `M2A_CPU`
- Crucial T500 4 TB: not installed during this run; planned slot remains chipset-connected `M2D_SB`
- Strata: Terminal 0.2.21.1 / Control 0.1.68; active general and Inkling engines 0.1.67
- LM Studio Bionic: product version 1.2.2.0 (file build 1.2.2+3); bundled `lms` CLI commit 138dcff

## Strata native engine suite

Strata's native standard suite reports engine prompt/decode timings. It uses its own fixed prompts, so these values are useful machine references but are not the same workload as the synthetic repository-review test in `llmb bench`.

| Model / artifact | Actual prompt tokens | Prefill tok/s | Decode tok/s | TTFT | Runs |
|---|---:|---:|---:|---:|---:|
| Inkling-2-Mini SQ-10, 32K | 3,423 | 7,854.5 | 168.8 | 0.469 s | 3 |
| Inkling-2-Mini SQ-10, 32K | 13,775 | 7,604.2 | 144.5 | 1.860 s | 3 |
| Qwen3.6-35B-A3B UD-Q4_K_XL, 32K | 4,051 | 10,403.2 | 186.1 | 0.422 s | 3 |
| Qwen3.6-35B-A3B UD-Q4_K_XL, 32K | 16,345 | 8,830.4 | 164.8 | 1.875 s | 3 |

Qwen's native report completed. Inkling's report is marked **nonconforming** because Strata could not hash the native `.strata` model file and its standard protocol prompt targets did not match this model's tokenizer within tolerance. The measured per-run engine timings are included with this conformance label; they should not be represented as a conforming Strata score.

Sanitized machine-readable summaries: [Inkling SQ-10](strata-inkling-sq10-engine-0.1.67.json), [Qwen3.6](strata-qwen36-q4xl-engine-0.1.67.json).

## Bionic native API benchmark

| Model / artifact | Context | Prompt tokens | Decode tok/s | First token | End-to-end rate | Runs |
|---|---:|---:|---:|---:|---:|---:|
| Inkling-2-Mini, Q4_K_M, 18.12 GB | 32K | 5,749 median | 74.5 median | 3.32 s median | 21.0 tok/s median | 3 |

This uses the same synthetic 35-section repository workload and 100-token output cap on all three requests. Metrics come from LM Studio's native `/api/v1/chat` stats, not client token estimates. The CLI reported the model loaded successfully in 2 minutes 53.53 seconds; this is a first load observation, not an SSD A/B result. [Per-run JSON](bionic-inkling-q4-32k-native.json).

## How to read these numbers

The Strata SQ-10 and Bionic Q4_K_M artifacts differ in format and size (10.47 GB vs 18.12 GB), and Strata's standard workload differs from the Bionic synthetic workload. Do not use the table as a same-build runtime race. It does show usable reference points for this PC and demonstrates the two native measurement paths. For later comparisons, hold the exact model files, context, prompt depth, cache state, and runtime build fixed.

The prior short Inkling result of 170.2 tok/s was a client stream estimate from Strata 0.2.20; this iteration's 168.8 tok/s is engine-timed under 0.1.67. Because the measurement source and workload differ, the near-match is orientation only, not a controlled before/after conclusion.

## Cross-runtime utility smoke benchmark

`llmbench` 0.1.0 then ran its `quick` diverse-corpus suite against the same Strata Inkling SQ-10 profile. The actual PC result has three measured runs per scenario and is marked **usable with cautions** because Strata reported hidden output tokens:

| Prompt depth | Actual prompt tokens | Read | Write | Runs |
|---|---:|---:|---:|---:|
| Inkling, about 3.5K | 3,476 | 7,387 tok/s | 195 tok/s | 3 |
| Inkling, about 14.5K | 14,462 | 7,121 tok/s | 168 tok/s | 3 |
| Qwen, about 3.4K | 3,445 | 11,168 tok/s | 284 tok/s | 3 |
| Qwen, about 14.6K | 14,562 | 9,626 tok/s | 215 tok/s | 3 |

The 32K configured context is capacity; the largest supplied prompt was about 14.5K tokens. Both models' results use a varied corpus and `llmbench` protocol 2.0. Both report hidden thinking tokens; Qwen also reached 97% VRAM use and missed the 4K prompt target tolerance. The token-rate gap is a speed observation, not a quality result, and should be rechecked with Qwen at lower context. These runs are not directly comparable to the repeated-text v1 results or Strata's native fixed-prompt suite. [Inkling JSON](llmbench-inkling-sq10-32k.json) · [Qwen JSON](llmbench-qwen36-q4xl-32k.json).

During the run the Bionic server was bound to `127.0.0.1`; the tested model was unloaded and its server stopped afterward. Strata's tested profiles were also stopped. The GPU returned to idle after cleanup.
