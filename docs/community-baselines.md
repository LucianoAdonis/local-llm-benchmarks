# Community baselines: what other people measure

Collected 2026-11-23 from public sources. Use it to answer one question: **is my number in the normal range for my hardware?** It is not a leaderboard. Almost every row comes from a different person, build and prompt.

For the plain-language version see [start-here.md](start-here.md). To measure your own machine see [llmbench.md](llmbench.md).

## How to read these tables

- **Read** = prompt processing (prefill) in tokens per second. **Write** = generation (decode) in tokens per second. One request at a time unless stated.
- **Grade** says how much to trust a row:
  - **A**: a first-hand measurement that states hardware, runtime build, model file and method, or an official scoreboard.
  - **B**: one user's report, or a vendor's own numbers, with partial method.
  - **C**: an aggregator's summary of someone else's post ([llamaperf.com](https://llamaperf.com/about) describes its entries as individual setups, extracted by a language model, not a controlled benchmark).
- A range such as `183 to 271` is the spread between sources, not run-to-run noise.
- Empty means nobody published it. Cells are left empty instead of estimated.

## 1. The common yardstick: Llama 2 7B Q4_0 in `llama-bench`

The llama.cpp project keeps scoreboards where everyone runs the same old model with the same command (`pp512` read test, `tg128` write test). It is the closest thing local inference has to a Cinebench score. It measures the engine alone, with random tokens and no server, so it reads higher than what a chat app shows.

| Hardware | Read tok/s | Write tok/s | Backend | Grade |
|---|---:|---:|---|---|
| RTX 5090 32 GB | 14,970 | 300 | CUDA | A |
| RTX 4090 24 GB | 14,771 | 189 | CUDA | A |
| RTX 5080 16 GB | 9,488 | 185 | CUDA | A |
| RTX 5070 Ti 16 GB | 8,420 | 182 | CUDA | A |
| RTX 3090 24 GB | 5,560 | 162 | CUDA | A |
| RTX 4080 16 GB | 9,206 | 143 | CUDA | A |
| RTX 4070 Ti Super 16 GB | 7,612 | 133 | CUDA | A |
| RTX 5060 Ti 16 GB | 4,196 | 93 | CUDA | A |
| RTX 3060 12 GB | 2,408 | 77 | CUDA | A |
| RTX 4060 Ti 8 GB | 3,803 | 64 | CUDA | A |
| RX 7900 XTX 24 GB | 3,890 | 191 | Vulkan | A |
| Radeon AI PRO R9700 32 GB | 5,908 | 153 | Vulkan (Linux) | A |
| RX 9070 XT 16 GB | 5,604 | 142 | Vulkan | A |
| Arc Pro B70 | 4,570 | 113 | Vulkan | A |
| Apple M4 (10 GPU cores) | 221 | 24 | Metal, 2023 build | A |
| Apple M4 Pro | 364 to 440 | 50 to 51 | Metal, 2023 build | A |
| Apple M4 Max | 714 to 886 | 70 to 83 | Metal, 2023 build | A |
| Apple M3 Ultra | 1,073 to 1,471 | 88 to 92 | Metal, 2023 build | A |
| Apple M5 | 723 | 32 | Metal, 2026 build | A |
| Apple M5 Max (40 GPU cores) | 3,220 | 120 | Metal, 2026 build | A |
| Ryzen AI Max+ 395 "Strix Halo" | 1,338 to 1,704 | 51 to 56 | Vulkan / ROCm | A |

Sources: llama.cpp scoreboards for [CUDA](https://github.com/ggml-org/llama.cpp/discussions/15013), [Vulkan](https://github.com/ggml-org/llama.cpp/discussions/10879) and [Apple Silicon](https://github.com/ggml-org/llama.cpp/discussions/4167); Strix Halo from [kyuz0](https://github.com/kyuz0/amd-strix-halo-toolboxes) and [visorcraft](https://github.com/visorcraft/strix-halo-llm-perf).

Two things stand out and both recur everywhere below:

1. **Writing speed follows memory speed.** A 5090 writes about 12 times faster than a base M4, and its memory is about 15 times faster (1,792 GB/s, from a 512-bit bus at 28 Gbps, against 120 GB/s).
2. **Reading speed follows raw compute.** The same 5090 reads more than 60 times faster than the M4. Macs are slow readers. The Apple rows for M1 to M4 also use a frozen 2023 build so that chips can be compared with each other; current builds are faster (the thread shows an M2 Ultra going from 94 to 125 tok/s on newer code).

## 2. Current models on NVIDIA cards

All llama.cpp, model fully in VRAM, no drafting, unless the row says otherwise.

### RTX 5090 (32 GB)

| Model and file | Read tok/s | Write tok/s | Notes | Grade |
|---|---:|---:|---|---|
| Qwen3.6-35B-A3B, Q4 | 2,892 to 9,240 | 183 to 271 | 183 on an April build (b8870) under WSL2, 271 in a run dated 28 May on Ubuntu (build not stated) | A |
| 35B-A3B MoE, Q4, with MTP drafting | | 267 (one [dev.to post](https://dev.to/prospectorlabs/267-toks-local-inference-on-rtx-5090-llamacpp-mtp-qwen3-35b-a3b-moe-2m6p) under WSL2; model named "Qwen3-35B-A3B") | no method; a 24 GB laptop 5090 is reported at 249 on a page that could not be read | C |
| Qwen3.6-27B (dense), Q4_K_M | 3,826 | 77 | | A |
| Qwen3.8-27B (dense), Q4_K_M | 3,881 | 79 | aggregator median of 7 plain runs: 80 | A |
| gpt-oss-20b, Q4_K_M | 16,750 | 368 | read falls to 6,678 at a 16K prompt | A |
| Gemma 4 12B, Q6_K | 7,160 | 122 | | A |
| Gemma 4 31B, QAT Q4_0 | 4,255 | 76 | 125 with MTP drafting (the source says 1.67 times; 125 / 76 is 1.64) | A |
| gpt-oss-120b, MXFP4 (59 GB, does not fit) | 484 | 46.5 | experts of 20 layers kept in system RAM | A |
| Inkling-2-Mini, UD-IQ4_XS | 2,318 | 97 | days after release | C |

Sources: [RTX 5090 dataset](https://huggingface.co/datasets/witcheer/rtx-5090-benchmarks) (a 49-row copy of its May and June rows is at [omegaprime669](https://huggingface.co/datasets/omegaprime669/rtx-5090-benchmarks)), the [zenn write-up](https://zenn.dev/toki_mwc/articles/rtx5090-qwen36-35b-a3b-llmacpp-bench), [llamaperf](https://llamaperf.com/gpu/rtx-5090).

### 24 GB cards (RTX 4090, RTX 3090)

| Model | Card | Read tok/s | Write tok/s | Grade |
|---|---|---:|---:|---|
| 35B-A3B MoE (Qwen3.5 / 3.6), Q4 or Q3 | 3090 | 2,440 (one report) | 81 to 149 | B/C |
| 35B-A3B MoE | 4090 | | 185 | C |
| Dense 27B, Q4 | 3090 | about 1,000 (one report) | 34 to 42 | B/C |
| Dense 27B, Q4, with MTP drafting | 3090 | 830 to 1,100 (three reports) | 49 to 73 | B/C |
| Dense 27B, 4-bit | 4090 | | 40 (median of 3) | C |

Sources: [aminrj.com](https://aminrj.com/posts/llamacpp-qwen36-35b/), [jeanfbrito](https://jeanfbrito.github.io/posts/dense-vs-moe-mtp-qwen3.6/), [llama.cpp discussion 19890](https://github.com/ggml-org/llama.cpp/discussions/19890), llamaperf.

### 16 GB, 12 GB and 8 GB cards

A 35B mixture-of-experts model at 4-bit (about 20 GB) does not fit in these cards (a 3-bit file of about 13 GB does fit in 16 GB), but it stays usable because only a small part of it is needed per token and the rest can sit in system RAM. A dense 27B model has no such escape: every weight is read for every token.

| Card class | 35B-A3B MoE, experts partly in RAM (write tok/s) | Dense 27B (write tok/s) | Grade |
|---|---:|---|---|
| RTX 5080 / 4080 | 30 to 70 | 33 at 3-bit (4080 Super); about 39 in LM Studio, quant not stated | C |
| RTX 5070 Ti / 4070 Ti Super | 40 to 112 | 53 to 55 at 3 to 4 bit; **2 to 10** when a Q4 or Q5 file spills to CPU | C |
| RTX 5060 Ti / 4060 Ti 16 GB | 19.5 to 50 | 14 to 29 at 3 to 4 bit | C |
| RTX 3060 12 GB | 23 to 47 at 3 to 5 bit; 68 with a 2-bit file | 29 to 38 at 3-bit; about 10 at Q4 | B/C |
| 8 GB cards | 19 to 65 (one fully specified run: 27.0 write, 517 read) | 30 at 2-bit (one run); 4 to 6 when Q4 spills to CPU | A for the one run, else C |

Sources for the C-graded cells: llamaperf report lists for the [RTX 5080](https://llamaperf.com/gpu/rtx-5080/reports), [4080](https://llamaperf.com/gpu/rtx-4080/reports), [4080 Super](https://llamaperf.com/gpu/rtx-4080-super/reports), [5070 Ti](https://llamaperf.com/gpu/rtx-5070-ti/reports), [4070 Ti Super](https://llamaperf.com/gpu/rtx-4070-ti-super/reports), [5060 Ti 16 GB](https://llamaperf.com/gpu/rtx-5060-ti-16gb/reports), [4060 Ti 16 GB](https://llamaperf.com/gpu/rtx-4060-ti-16gb/reports), [3060 12 GB](https://llamaperf.com/gpu/rtx-3060-12gb/reports) and the [8 GB cards](https://llamaperf.com/gpu/rtx-5060-8gb).

The best-documented small-card runs are a [3060 with a Xeon and DDR4](https://jeanfbrito.github.io/posts/running-qwen3.6-35b-moe-rtx3060-ncmoe/) (out of memory to 22.9 tok/s by moving experts of 25 layers to RAM) and a [3070 on native Windows](https://note.com/ripe_hosta6920/n/nb81b72d54ad7), where moving one more layer's experts off the card took read speed from 95 to 517 tok/s. Host RAM speed and that one setting explain most of the spread in these rows.

### AMD and Intel cards

| Card | 35B-A3B MoE, Q4 (read / write) | Dense 27B Q4 (write) | Grade |
|---|---|---:|---|
| Radeon AI PRO R9700 32 GB, Vulkan | 2,404 to 2,900 / 105 to 153 on stock builds (164 with a one-line patch) | 29 (33 with the patch) | A |
| RX 7900 XTX 24 GB | 1,875 over a 427-token prompt / 125 (Vulkan, in LM Studio) | 40 (median of 7, backend not stated) | C |
| RX 9070 XT 16 GB, experts in RAM | 333 to 1,616 / 29 to 62 | 17 to 31 at 3-bit | A/B |
| Arc Pro B70, Vulkan or SYCL | 615 to 1,225 / 55 to 77 | 20 to 27 | A/B |

Sources: llama.cpp discussions [19890](https://github.com/ggml-org/llama.cpp/discussions/19890), [21043](https://github.com/ggml-org/llama.cpp/discussions/21043), [23313](https://github.com/ggml-org/llama.cpp/discussions/23313), issue [26581](https://github.com/ggml-org/llama.cpp/issues/26581), [kr4ckhe4d's 9070 XT results](https://github.com/kr4ckhe4d/local-llm-benchmarks). Driver, backend and build move these by tens of percent. On the RX 9070 XT, [one repository](https://github.com/kr4ckhe4d/local-llm-benchmarks) measured llama.cpp faster on ROCm than on Vulkan, while [another](https://github.com/seb-caw/rdna4-llm-stack) found llama.cpp on Vulkan (62 tok/s) faster than vLLM on ROCm (48), which is a different engine.

## 3. Apple Silicon and other shared-memory machines

### Base M4 (the 16 to 32 GB Mac mini, MacBook Air and MacBook Pro)

| Model | Read tok/s | Write tok/s | Notes | Grade |
|---|---:|---:|---|---|
| 7 to 9B at 4-bit | 216 to 240 | 15 to 24 | 25 to 28 with Ollama's MLX runner and drafting | A |
| 12 to 14B at 4-bit | 95 to 130 | 11 to 15 | | B |
| gpt-oss-20b | 325 to 430 | 26 to 36 (MXFP4-Q8 build; full 4-bit builds reach 38 to 47) | at a 64K prompt: 175 read, 13.5 write, 6 minutes to first token | B |
| Qwen3.6-35B-A3B, 3-bit, on 24 GB | 73 to 518 | 16 to 58 | user rows spread widely: 16 to 24 in one batch with expert offload on, 31 to 58 in other 3-bit rows; 4-bit rows on 24 GB run from 4 to 48 | B |
| Qwen3.6-35B-A3B, 4-bit, on 32 GB | 499 to 510 | 47 to 48 | one user's session ([oMLX row](https://omlx.ai/benchmarks/performance/9fqprevx)); other 32 GB rows write 12 to 46 | B |
| Inkling-2-Mini, 4-bit MLX, on 24 GB | 228 to 237 | 20 to 24 | with MTP drafting and 4-bit KV on; 18 to 19 GB peak; vendor says 32 GB minimum | B |
| Gemma 4 12B, 4-bit | 95 to 142 | 11 to 14 | 14 at a 1K prompt, 11 at 64K; 11 minutes to first token at a 64K prompt | B |

One measurement deserves its own line because it shows how much the runtime matters on identical hardware. On a **24 GB M4 Mac mini**, the same 9B model wrote at 27.3 tok/s (Ollama, MLX runner with drafting), 21.3 (mlx-lm), 20.1 (LM Studio, MLX engine), 17.5 (LM Studio, llama.cpp engine), 17.1 (Ollama, GGUF) and 16.1 (Ollama, MLX without drafting). Reading speed was 216 to 237 tok/s on all six. Source: [computingforgeeks.com](https://computingforgeeks.com/ollama-lm-studio-mlx-mac/), 2026-11-11, grade A.

Other sources: [llama-bench on a 24 GB M4](https://github.com/ggml-org/llama.cpp/discussions/4167#discussioncomment-16886673), oMLX community rows for [gpt-oss-20b](https://omlx.ai/benchmarks/performance/5ershxbw), [Qwen3.6](https://omlx.ai/benchmarks/performance/y2tq60zu), [Inkling](https://omlx.ai/benchmarks/performance/re8auw5m) and [Gemma 4](https://omlx.ai/benchmarks/performance/49huaw8t) (user-submitted, not independently verified), a [16 GB M4 mini](https://petronellatech.com/ai/llm-benchmarks/hardware/mac-mini/), [Jeff Geerling's M4 mini](https://github.com/geerlingguy/ai-benchmarks/issues/2).

**The 24 GB limit in practice.** macOS lets the GPU use 18,186 MiB (about 17.8 GiB) of a 24 GB Mac by default. A 19 GB model was refused until the limit was raised by hand, and then ran at 5.7 tok/s with 2.4 GB in swap (same source as above). As a rule of thumb, plan for model plus context to stay near 16 GB.

### Larger Macs, Strix Halo, DGX Spark, CPU only

| Machine | Model | Read tok/s | Write tok/s | Grade |
|---|---|---:|---:|---|
| M4 Pro | gpt-oss-20b | 701 (420 at 32K) | 63 | B |
| M4 Pro 24 GB | Inkling-2-Mini 4-bit MLX | 400 to 410 | 31 to 47 depending on build | B |
| M4 Max | gpt-oss-20b | 1,277 (568 at 32K) | 92 | A |
| M4 Max 128 GB | Qwen3.5-35B-A3B 4-bit | | 43 Ollama, 71 llama.cpp, 130 mlx-lm | B |
| M5 Ultra 256 GB | Qwen3.6-35B-A3B 4-bit | 4,877 to 5,584 | 136 to 146 | A |
| Strix Halo 128 GB | 30 to 35B-A3B MoE, Q4 | 1,120 to 1,142 | 60 to 86 | A |
| Strix Halo 128 GB | gpt-oss-20b | 1,813 | 80 | A |
| DGX Spark | gpt-oss-20b | 4,506 (2,689 for 2K more tokens at 32K depth) | 83 (88 on a Dell GB10 under Ollama) | A |
| Ryzen 9 9950X, CPU only | Llama-3.1-8B Q4_0 | 99 to 306 | 11 | B |
| Ryzen 9 9950X, CPU only, DDR5-6400 | Qwen3-30B-A3B MoE (ik_llama.cpp fork, June 2025) | 527 to 577 | 33 to 34 | B |

Sources: llama.cpp [gpt-oss guide](https://github.com/ggml-org/llama.cpp/discussions/15396), [nedcut/inkling2-mini-mac](https://github.com/nedcut/inkling2-mini-mac), [antekapetanovic.com](https://antekapetanovic.com/blog/qwen3.5-apple-silicon-benchmark/), [M5 Ultra dataset](https://huggingface.co/datasets/tristanbes/m5-ultra-llm-bench), Strix Halo repos above, llama.cpp's [DGX Spark file](https://github.com/ggml-org/llama.cpp/blob/master/benches/dgx-spark/dgx-spark.md), [Geerling's table](https://github.com/geerlingguy/ai-benchmarks), [ubergarm](https://huggingface.co/ubergarm/Qwen3-30B-A3B-GGUF/discussions/2), llama.cpp [PR 30036](https://github.com/ggml-org/llama.cpp/pull/30036).

## 4. The three models this repository measured

Machine: RTX 5090 32 GB, Ryzen 9 9950X3D, 128 GB RAM, Windows 11. Our numbers are in [results/2026-11-23](../results/2026-11-23/README.md) and were taken with the v1 scripts on a repetitive prompt; [benchmark-design.md](benchmark-design.md) explains why that matters.

### DeepSeek V4.1 Flash, 2.00 bpw (far larger than VRAM)

| Who | Setup | Fresh content | Repeated content | Grade |
|---|---|---:|---:|---|
| **This repo** | Strata 0.2.13, 5090, 128 GB | not measured | 21 to 27 write, 838 to 2,506 read | |
| [Strata issue 4170](https://github.com/Niko1221/Strata/issues/4170) | Strata 0.2.6, 5090, 7800X3D, 128 GB, Windows, 2.25 bpw | 15 to 16 | 25 | A |
| [acrogenesis recipe kit](https://github.com/acrogenesis/deepseek-v41-flash-recipe-kit) | custom llama.cpp runtime, 5090, 9950X3D, 128 GB, Linux | 21 to 28 | 25 to 36 | A |
| [JigSawPT](https://github.com/JigSawPT/deepseek-v41-flash-on-5090) | llama.cpp fork, 502 GB file, 5090, 126 GB | 5.1 | 21.3 | A |
| [Strata issue 4931](https://github.com/Niko1221/Strata/issues/4931) | Strata, 5090, **384 GB RAM**, Linux | about 37 (32 to 42), read 1,500 to 1,700 | | A |
| [Strata issue 5552](https://github.com/Niko1221/Strata/issues/5552) | Strata 0.2.11, 5090, 192 GB, WSL2, 2.25 bpw | 14 to 19 write; 16K of Python read at 956 vs 1,120 for synthetic records | | B |

**Reading.** Our writing speed sits inside the range other 5090 owners report, but every source that tested both ways found repeated content 1.2 to 4 times faster than content the engine had not seen. With greedy decoding, a repeated prompt produces the same tokens, which route to the same experts, which are already in fast memory. Our v1 prompt was one Python class repeated hundreds of times, and the engine log shows only 0.4 to 1.2% of experts served from the slow lane. So our DeepSeek rows are probably a **warm, best-case** figure. We did not measure varied text ourselves, so the size of the effect on this machine is unknown; the three sources that tested both ways saw fresh content run 15% to 76% slower than repeated content (repeats 1.2 to 4 times faster). Strata's own release notes say the same about reading speed: its word-list prompts read at 214 to 234 tok/s where ordinary prose read at 124 to 164 on one machine ([v0.2.7](https://github.com/Niko1221/Strata/releases/tag/v0.2.7)).

These rows can only be reproduced on Strata 0.2.13, the last release that ran this model.

### Qwen3.6-35B-A3B, UD-Q4_K_XL, with MTP drafting

| Who | Setup | Write tok/s | Grade |
|---|---|---:|---|
| **This repo** | Strata 0.2.20, MTP 2, 4.9K prompt | 310 | |
| **This repo** | same, 54.9K prompt | 93 | |
| RTX 5090 dataset | llama.cpp, Q4_K_M, no drafting, empty context | 271 | A |
| zenn write-up | llama.cpp under WSL2, April build, no drafting | 183 | A |
| [Hugging Face discussion](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/discussions/11) | llama.cpp, 5090 + 9950X3D, Windows, Q5 | 175 plain, 120 with MTP | B |
| Strata's own page | Radeon R9700, same file | 118 plain, 184 with MTP 2 | B (vendor) |

**Reading.** 310 tok/s at a short prompt is above every llama.cpp figure for this card. Drafting explains part of it, and a repetitive prompt raises draft acceptance, so that figure is probably flattered. The steep fall to 93 tok/s at 55K tokens is **not** a hardware limit. It is a documented behaviour of Strata's Qwen3.6 engine, confirmed by its maintainer ([issue 2464](https://github.com/Niko1221/Strata/issues/2464)): decode slows as the context fills and also depends on the configured window, while llama.cpp stayed near 90 tok/s on the reporter's card where Strata fell from 109 to 15. Unsloth's documentation puts the MTP gain on mixture-of-experts models at only 1.15 to 1.25 times ([docs](https://unsloth.ai/docs/models/qwen3.6)).

### Inkling-2-Mini

| Who | Setup | Write tok/s | Grade |
|---|---|---:|---|
| **This repo** | Strata 0.2.20, SQ-10 / SQ-20, 5.7K prompt, client-timed | 170 / 134 | |
| **This repo** | UD-Q4_K_M, drafting off | 120 | |
| [Strata's model card](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata) | 5090, SQ-10 / SQ-20, drafting on, context not stated | 239 to 250 / 177 to 199 | B (vendor) |
| [Strata PR 6909](https://github.com/Niko1221/Strata/pull/6909) | 5090, Linux, SQ-20, engine timings | 161 (144 to 244); read 8,713 / 7,860 / 6,742 at 4K / 16K / 32K | B |
| [Strata issue 6684](https://github.com/Niko1221/Strata/issues/6684) | RTX PRO 6000, 24K prompt | SQ-10: 107 with drafting, 79 without | A |
| llamaperf | 5090, llama.cpp, no drafting | 97 | C |

**Reading.** Our numbers are below the vendor's and in line with independent reports. Three things make Inkling hard to time from the outside: its drafter is bimodal (one user saw the same prompt at either 85 to 95 or 205 to 222 tok/s, [issue 6683](https://github.com/Niko1221/Strata/issues/6683)), it can be slower with drafting on ordinary code and prose ([issue 6716](https://github.com/Niko1221/Strata/issues/6716)), and it writes hidden thinking tokens that the server counts but does not stream ([PR 6906](https://github.com/Niko1221/Strata/pull/6906)). Our Inkling rows were timed from the client, so treat them as approximate until they are re-run with engine timings.

## 5. What moves a number more than the hardware does

Measured effect sizes from the sources above. This is the list to check before concluding that your machine is slow.

| Cause | Measured effect | Source |
|---|---|---|
| Another app is holding VRAM, so the model silently runs on CPU | 180 tok/s became 18 | [zenn](https://zenn.dev/toki_mwc/articles/rtx5090-qwen36-35b-a3b-llmacpp-bench) |
| Only part of a dense model fits on the card | 81.5 tok/s on a 5090, 5.7 on a 12 GB 4070 Super with 38 of 66 layers on GPU | [llamaperf](https://llamaperf.com/report/4c35c0b1-aa3d-49b1-b457-a6d1d1860461) |
| Windows moves overflowing VRAM into system memory | 102 tok/s became 13.7 after 0.86 GiB of overflow | [Strata docs](https://github.com/Niko1221/Strata/blob/main/docs/DETAILS.md) |
| An automatic context size far larger than needed | replies took 33 to 41 s instead of about 3 s | [LM Studio issue 2543](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2543) |
| Older runtime build | same 5090 and file: 153 tok/s, then 180 on a build a few weeks newer. Another 5090 a month later: 271 (different quant and OS) | zenn, 5090 dataset |
| Long context | one site's 8B test on a 5090: 186 tok/s at 4K, 112 at 32K, 49 at 131K | [hardware-corner.net](https://www.hardware-corner.net/en/rtx-5090-llm-benchmarks/) |
| Long context on weaker backends | Arc B70: 70.7 at empty, 20.7 at 127K | [llama.cpp issue 26581](https://github.com/ggml-org/llama.cpp/issues/26581) |
| Drafting (MTP) on a dense model | writing +40 to +67%, reading about 18% slower | jeanfbrito, 5090 dataset, llamaperf |
| Drafting (MTP) on a mixture-of-experts model | from about 38% slower to about 38% faster | jeanfbrito, 5090 dataset |
| Drafting on llama.cpp's Mac backend | slower: 25.3 became 19 to 22 | [llama.cpp issue 23752](https://github.com/ggml-org/llama.cpp/issues/23752) |
| Mismatched K and V cache types on CUDA | 121 tok/s became 18 | [LM Studio issue 2246](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2246) |
| Mac in Low Power Mode | 63 tok/s became 28 | [emasblog.dev](https://emasblog.dev/posts/2026/11/qwen3.8-27b-on-m5-pro-macbook-pro/) |
| Fanless Mac after 150 seconds of load | settles at 70 to 77% of its cold speed | [zachrattner.com](https://zachrattner.com/projects/ai-mac-cluster/fanless-benchmarking) |
| GPU power limit | RTX 3090: 350 W to 250 W cost about 1%; 200 W cost 36% | [jeanfbrito](https://jeanfbrito.github.io/posts/rtx-3090-power-limit-sweet-spot/) |
| GPU in a chipset x4 slot instead of a CPU x16 slot | writing 22% slower | [llama.cpp discussion 19890](https://github.com/ggml-org/llama.cpp/discussions/19890) |
| Busy Windows desktop during a run | writing 12% slower, much wider spread | [llama.cpp scoreboard comment](https://github.com/ggml-org/llama.cpp/discussions/15013#discussioncomment-18108605) |
| WSL2 instead of native Linux | about 1.7% slower writing in llama.cpp (one card); 13% slower in vLLM | same comment; [hwbusters](https://hwbusters.com/systems/rtx-5090-rtx-5080-ubuntu-windows-ai-rendering-workstation/4/) |
| Runtime choice on the same file when the model fits | LM Studio, Ollama and llama.cpp within 6% in four of five tests, 9.5% apart in the fifth | [kingy.ai](https://kingy.ai/blog/ollama-vs-lm-studio-vs-llama-cpp/) |

### How noisy are these measurements?

- `llama-bench` writing speed usually repeats within 1%. Reading speed can swing 8% on one GPU and 23% on a multi-GPU split ([scoreboard thread](https://github.com/ggml-org/llama.cpp/discussions/15013)).
- Strata's own published runs show 9% run-to-run variation in writing speed from its adaptive expert cache, and a 5090 community run ranged from 139 to 214 tok/s across identical requests ([pilot](https://github.com/Niko1221/Strata/blob/main/docs/bench-results/2026-10-20-0.2.1-bench/README.md), [5090 run](https://github.com/Niko1221/Strata/blob/main/docs/bench-results/2026-10-03-dev-5090/README.md)).
- Short samples flatter: on one Mac a 24-token sample read 53 to 60 tok/s where 700 tokens sustained 41 ([dataset](https://huggingface.co/datasets/RaynarDM/apple-silicon-llm-benchmarks)).

A difference under 2% between two runs is noise. On Strata, treat anything under 10% as unproven until repeated.

## 6. What nobody has published yet

These gaps are where a careful result from this repository would be new information.

- A same-machine comparison of native Windows and native Linux for llama.cpp on a single RTX 5090.
- Strata, LM Studio or Ollama numbers for these three models on a Windows RTX 5090 with a stated method.
- Any Strata measurement on a 24 GB Mac. Upstream measured 32 GB and 128 GB machines only.
- Inkling-2-Mini through llama.cpp, Ollama or LM Studio on a base M4.
- A logged thermal or Low Power Mode test on a base M4, and a power-limit sweep on an RTX 5090.
- `strata bench run` results for an RTX 5090, for Windows, or for any Mac.

## Caveats

- Community attention moves fast. In late 2026 most new reports cover Qwen3.8 27B, Qwen3.8-Flash-Next and Inkling-2-Mini.
- "Context" in community posts is usually the configured limit, not how many tokens were in the prompt. Prompt-size-controlled numbers exist for only a handful of setups.
- Reddit threads could not be read directly while compiling this page. Rows that originate there come through llamaperf summaries and are graded C.
- Vendor numbers (Strata's release notes and model cards, Unsloth's documentation) are marked as such. Several state no method.
