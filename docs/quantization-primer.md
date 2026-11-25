# Quantization primer: 4-bit, 2-bit, and DeepSeek

## What “4-bit” describes

A quantization level describes how model weights are stored approximately. Four bits per weight is half a byte per value before scales, tensor metadata, embeddings, and other overhead. Two bits per weight is about half that storage again. Real model files are not exactly `parameter_count × bits / 8`: different tensor groups may use different types, and auxiliary data can remain at higher precision.

Quantization does **not** change a 35B model into a 4B model. It changes how its weights are represented on disk and loaded for computation. For an MoE model, total parameters and active parameters also differ: only selected experts are used for each token, while all experts still have to be stored somewhere.

Four-bit is a popular balance between fidelity and size; it is not a hard ceiling or a guarantee of quality. Lower-bit models can fit on smaller systems and move fewer bytes, but they usually have less representational precision and may lose accuracy. Actual speed depends on the engine's kernels, GPU/CPU placement, memory bandwidth, and offloading. A 2-bit model is not automatically twice as fast as a 4-bit model.

## Why the 763B DeepSeek pack is called “2.00 bpw”

DeepSeek V4.1 Flash has 763.2B total parameters and uses a sparse MoE design with 6 of 384 routed experts active per token. The benchmark used ISTA-DASLab's IQ2_XXS GSQ-RCO backbone, whose average is 2.00 bits per weight (bpw). That label applies to the backbone, not every file in the Strata package:

- Backbone shards: 138.24 GB combined, 2.00 bpw average.
- Shared Engram lookup data: 110.60 GB, IQ4_NL at 4.50 bpw.
- DSpark draft support: 7.98 GB, Q8_0.
- Total local model/support package: about 256.81 GB (239.17 GiB).

The pack is much larger than 32 GB of VRAM, so the system relies on Strata's memory/offload behavior and SSD-backed data. This is why storage placement may matter for cold load or paging, though it does not guarantee faster token generation. Full per-file sizes are in the [model catalog](model-catalog.md).

## Tradeoffs for this benchmark

**2.00 bpw DeepSeek advantages**

- Makes a very large 763B-parameter model usable on a consumer PC with one 32 GB GPU and 128 GB system RAM, by keeping/offloading weights beyond VRAM.
- Uses a much smaller backbone than a 4-bit representation of the same tensors would. A simple idealized 4.00 bpw backbone would be roughly 276.5 GB before auxiliary data, versus the measured 138.24 GB at 2.00 bpw.
- The publisher's published test suite reports the IQ2_XXS build matching the base-model task average on its AIME25, GPQA-Diamond, and LiveCodeBench v6 measurements. That is a useful reference, not a guarantee for every coding task or prompt.

**Costs and limitations**

- More aggressive weight compression can alter model behavior and reduce quality on tasks not covered by published evaluations.
- The complete pack still needs about 257 GB of storage because Engram and DSpark support files are additional and use higher precision.
- Offloading, SSD access, CPU memory bandwidth, and context length can dominate speed. This run measured 26 to 28 tok/s decode at 4.5K and 15.1K input, 25.3 on the second request at 50K, and 20.9 on the two requests that were first after an engine start (50K and 250K). No effect of depth on decode is resolved: depth, profile and being a first request are tangled together. Prompt ingestion fits a per-request cost of roughly 2 to 4 seconds plus a steady rate near 2,600 tok/s, which is why the simple rate rises from 838 tok/s at 4.5K to 2,506 at 250K; time to first content at 250K was 102.6 seconds. All of this was measured on a repetitive prompt, which is probably a best case; see [benchmark-design.md](benchmark-design.md).
- The user's 4-bit Inkling and Qwen models are different model families; their speed/quality cannot isolate the effect of quantization. This repository does not yet have a same-model DeepSeek 4-bit A/B run.

## A fair 2-bit versus 4-bit comparison

To measure the quantization effect rather than compare unrelated models, use the same DeepSeek checkpoint family and runtime, with matching context, prompts, cache policy, generation settings, and hardware placement. Record prefill, decode, TTFC, output quality, RAM/VRAM, and storage reads. If a 4-bit DeepSeek pack does not fit the same memory tier, report the changed offload plan as part of the comparison; it is a system configuration difference as well as a bit-width difference.

Reference: [ISTA-DASLab model card and quantization results](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF). Its result table reports task-average parity for IQ2_XXS on the listed evaluations; it does not establish a universal 4-bit/2-bit quality rule.
