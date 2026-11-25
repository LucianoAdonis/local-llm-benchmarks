# Model catalog: parameters, quantization, and files

`B` means billion parameters. For mixture-of-experts (MoE) models, **total** parameters are the full parameter inventory; **active** parameters are the routed/shared weights used per token. A pack's download size is the bytes on disk, not its parameter count. `GB` uses decimal bytes (10^9); `GiB` uses binary bytes (2^30).

Sizes below come from the files used in the November 23, 2026 benchmark unless marked as publisher-rounded. Local byte counts can vary with revisions and support files.

## Starter catalog for `llmbench models`

These entries are intended to make a first download straightforward. The picks use Hugging Face GGUF repos with strong download activity observed on 2026-11-25; popularity changes, so treat this as a dated snapshot rather than a current ranking. Quant names and sizes are shown to make storage needs concrete. Model fit depends on available VRAM/unified memory, context length, KV cache, and what else is running.

| Catalog ID | Model and variant | Approximate download | Hugging Face repo downloads, 2026-11-25 snapshot | Intended use |
|---|---|---:|---:|---|
| `qwen9b-q4` | Qwen3.5 9B, Q4_K_M | 5.68 GB | 2.20M | First Mac/PC download; leaves more memory for context |
| `qwen27b-q4` | Qwen3.5 27B, Q4_K_M | 16.74 GB | 406K | Higher capacity; needs enough fast memory for weights plus context |
| `qwen35b-a3b-q4xl` | Qwen3.6 35B-A3B, UD-Q4_K_XL | 22.85 GB | 3.05M | Larger MoE model; 3B active per token does not mean only 3B of weights need memory |
| `qwen177b-iq2xs` | Qwen3.8 Flash Next 177B, UD-IQ2_XS | 75.83 GB / 3 shards | 4.05M | Large offload experiment; not a sensible first download on a Mac with limited memory |

Install the optional downloader with `uv tool install --force --with huggingface_hub ...`, pick a destination using `llmbench config set download-dir PATH`, and review available entries with `llmbench models list`. A pull goes to a folder named after the catalog ID. These are GGUF artifacts, not Strata `.strata` packs; use Strata's guided installer for its managed model formats and required support files.

The catalog can evolve. Before a release, recheck the model cards, exact files, sizes, licenses, and supported runtime versions. `qwen177b-iq2xs` is meant to exercise memory/offload behavior; SSD paging may make generation uncomfortably slow. The existing 763B DeepSeek V4.1 Flash 2.00 bpw measurement is documented below; the observed full package was 256.81 GB and exceeded the PC's 128 GB RAM, so it is an explicit storage/offload experiment, not an expected-fit model.

### Beyond the PC baseline

DeepSeek V4 Pro is a larger model family at roughly 1.6T parameters. A community GGUF lists an IQ1_M build around **346.6 GiB for weights alone**. That exceeds this PC's 128 GB of system RAM by a wide margin before context and runtime memory, and it is not a standard Strata managed pack. The 4 TB SSD could hold the files, but that does not make inference practical: loading and paging from SSD is far slower than RAM, and there is no validated run for this PC. So the curated pull list stops at 177B; the already-tested 763B DeepSeek Flash remains the largest model with evidence on this machine. [DeepSeek V4 Pro quantization files](https://huggingface.co/qtum/DeepSeek-V4-Pro-0813-GGUF)

## Tested models

| Model | Total / active parameters | Tested artifact and quantization | Local download size | Context |
|---|---|---|---:|---:|
| DeepSeek V4.1 Flash 1017 | 763.2B total; 6 of 384 routed experts active per token (publisher model card) | ISTA-DAS GSQ-RCO IQ2_XXS, 2.00 bpw backbone; Strata support pack | 256.81 GB / 239.17 GiB full pack | 1M native; benchmarked at 32K, 128K, and 256K |
| Inkling-2-Mini | 26.4B total; 3.4B active (5.4B effective with loop passes) | Strata native SQ-10 | 10.47 GB / 9.75 GiB | 1M native; benchmarked at 32K and 128K |
| Inkling-2-Mini | same base model | Strata native SQ-15 | 14.35 GB / 13.36 GiB | 1M native; benchmarked at 32K |
| Inkling-2-Mini | same base model | Strata native SQ-20 | 19.35 GB / 18.02 GiB | 1M native; benchmarked at 32K |
| Inkling-2-Mini | same base model | Unsloth UD-Q3_K_XL GGUF | 13.63 GB / 12.70 GiB | 1M native; benchmarked at 32K |
| Inkling-2-Mini | same base model | Unsloth UD-Q4_K_M GGUF | 16.61 GB / 15.47 GiB | 1M native; benchmarked at 32K and 128K; DSpark off |
| Qwen3.6-35B-A3B | 35B total; 3B active | Unsloth UD-Q4_K_XL MTP GGUF | 22.85 GB / 21.28 GiB | 262,144 native; benchmarked at 32K and 128K |

The published parameter counts are from the [DeepSeek/ISTA-DAS model card](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF), [Thinking Machines Inkling model card](https://huggingface.co/thinkingmachines/Inkling-2-Mini), and [Unsloth Qwen3.6 MTP model card](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF). Qwen's model card lists 35B total / 3B active; the Hugging Face GGUF catalog rounds its displayed model size to 36B.

For Inkling, `SQ-10`, `SQ-15`, and `SQ-20` refer to approximate pack sizes in GB, not 10-, 15-, or 20-bit quantization. The native pack sizes are published on the [Strata Inkling model card](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata). The GGUF variant names carry the quantization family (`Q3` or `Q4`); exact local byte sizes appear in the table.

## Exact tested files

### DeepSeek V4.1 Flash 1017, 2.00 bpw

The local Strata installation used a legacy four-shard IQ2_XXS layout. This is the observed layout from the test machine; the current [ISTA-DASLab repository](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF) uses a newer five-backbone-shard layout. Use Strata's managed installer so it prepares the matching runtime files rather than downloading one shard in isolation.

| Local filename | Size (GB) | Size (GiB) |
|---|---:|---:|
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf` | 39.08 | 36.39 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00002-of-00004.gguf` | 39.39 | 36.68 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00003-of-00004.gguf` | 39.25 | 36.55 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00004-of-00004.gguf` | 20.53 | 19.12 |
| **Backbone shards subtotal** | **138.24** | **128.75** |
| `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` (shared Engram tables) | 110.60 | 103.00 |
| `dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf` (draft support) | 7.98 | 7.43 |
| **Observed model + support files** | **256.81** | **239.17** |

The 2.00 bpw label describes the backbone's average bits per weight. The Engram lookup file uses IQ4_NL (4.50 bpw) and DSpark support is Q8_0, so the complete download is not a uniform 2-bit file. The publisher's current table lists 138.24 GB for the IQ2_XXS backbone plus 110.60 GB for shared Engram = 248.84 GB before Strata's DSpark draft file.

### Inkling-2-Mini

Native Strata files: [SQ-10](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata/blob/main/Inkling-2-Mini-SQ-10.strata), [SQ-15](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata/blob/main/Inkling-2-Mini-SQ-15.strata), [SQ-20](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata/blob/main/Inkling-2-Mini-SQ-20.strata).

Unsloth GGUF files: [UD-Q3_K_XL](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/blob/main/Inkling-2-Mini-UD-Q3_K_XL.gguf) and [UD-Q4_K_M](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/blob/main/Inkling-2-Mini-UD-Q4_K_M.gguf). The GGUF install also had a 0.40 GB Q8_0 DSpark drafter available; it was turned off for the UD-Q4_K_M benchmark because the tested Strata engine path failed on a missing tensor.

### Qwen3.6-35B-A3B

The tested file is [Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/blob/main/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf). Local disk size: 22,853,663,008 bytes (22.85 GB, 21.28 GiB). Strata used engine 0.1.66 with MTP 2 enabled.

## What the parameter labels do and don't say

A 35B model is not automatically a 35 GB download. Parameter count describes how many learned values are in the model; quantization packs those values at lower precision, while MoE routing means only some experts are used for an individual token. GGUF/Strata headers, scales, embeddings, lookup tables, draft models, and vision files add their own size. Always record both the model's parameter description and the exact downloaded artifact size.
