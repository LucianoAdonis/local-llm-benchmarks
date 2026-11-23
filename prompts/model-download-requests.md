# Copy-ready model install requests

Use these exact names/variants in Strata's model selector or setup assistant. If the version you installed does not show a model, follow its linked model card and confirm the Strata engine supports that format. Do not substitute a different quantization while keeping the same benchmark label.

## DeepSeek V4.1 Flash — IST-DAS 2.00 bpw

> Install the Strata-compatible DeepSeek V4.1 Flash 1017 IST-DAS 2.00 bpw pack from the ISTA-DASLab GSQ-RCO family. Include all model shards plus the required shared Engram and DSpark support files. Keep it as the 2.00 bpw Strata pack, and set up a 256K context profile only if the installed engine supports it and memory permits. Do not substitute another DeepSeek quantization.

This is a 763.2B-total-parameter sparse MoE; the model card says 6 of 384 routed experts are active per token. The 2.00 bpw figure is for the backbone, not the whole package. Source family: [ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF). The tested Strata pack requires all four legacy-layout backbone shards, the shared Engram table, and DSpark support; a single GGUF shard is not enough. Observed complete package footprint was 256.81 GB (239.17 GiB).

This specific model was retired in the local Strata 0.2.20 catalog. The recorded run used a side-by-side Strata 0.2.13 / engine 0.1.59 compatibility install. For a new setup, check the current Strata release/model catalog and record any alternate version or model as a different configuration.

## Inkling-2-Mini — native Strata packs

> Install Inkling-2-Mini as the native Strata `.strata` format. It has 26.4B total parameters and 3.4B active per token (5.4B effective with its loop passes). Download SQ-10, SQ-15, and SQ-20 as separate variants if comparing pack sizes. Keep the variant names distinct and use the matching model profile for each benchmark run.

Source: [strata-engine/Inkling-2-Mini-Strata](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata). Observed files: `Inkling-2-Mini-SQ-10.strata` 10.47 GB (9.75 GiB), `Inkling-2-Mini-SQ-15.strata` 14.35 GB (13.36 GiB), and `Inkling-2-Mini-SQ-20.strata` 19.35 GB (18.02 GiB). SQ-N is a pack-size family label, not an N-bit quantization label.

## Inkling-2-Mini — Unsloth GGUF variants

> Install the Unsloth GGUF build of Inkling-2-Mini. The base model has 26.4B total parameters and 3.4B active per token. Download UD-Q3_K_XL and UD-Q4_K_M as separate model variants. For UD-Q4_K_M in Strata, turn DSpark drafting off because the tested Strata GGUF + DSpark path fails with a missing tensor. Keep a separate profile and label the result as DSpark off.

Source: [UD-Q3_K_XL file](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/blob/main/Inkling-2-Mini-UD-Q3_K_XL.gguf) (13.63 GB / 12.70 GiB) and [UD-Q4_K_M file](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/blob/main/Inkling-2-Mini-UD-Q4_K_M.gguf) (16.61 GB / 15.47 GiB). This build and native `.strata` builds are different artifacts and should not share a result label.

## Qwen3.6-35B-A3B — UD-Q4_K_XL

> Install Qwen3.6-35B-A3B UD-Q4_K_XL from the Unsloth MTP GGUF repository. The model has 35B total parameters and 3B active per token. Preserve the UD-Q4_K_XL quantization and MTP support. Use a 128K context profile for the high-context coding suite, if supported by the engine and system memory.

Source: [Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/blob/main/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf). The observed file size was 22.85 GB (21.28 GiB); Strata used engine 0.1.66 with MTP 2.

## Download and verification notes

- Model names and catalog availability change; read the model card before installation.
- Keep model weights out of this Git repository. Record source repository, exact filename, quantization, revision/commit, and SHA-256 in your private run record; publish only those values that the source allows.
- Check available storage before starting. DeepSeek's multi-file pack is much larger than the GPU's VRAM and can take hours depending on network and disk speed.
- For an actual result, include the exact model profile, configured context, prompt token count, Strata version, engine version, and whether draft/speculative decoding was enabled.
