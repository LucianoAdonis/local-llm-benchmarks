# Start here: how fast will a local LLM be, and why

For anyone who has installed Strata, LM Studio (or its Bionic agent app), llama.cpp or Ollama and wants to know what speed to expect, what limits it, and which settings are worth touching.

How to use this page:

- Numbers here were measured by someone and are linked, on this page or in the evidence tables of [community-baselines.md](community-baselines.md), or they are marked as arithmetic.
- Unfamiliar words are in the [glossary](#glossary) at the end.
- The worked examples use two machines: a PC with an RTX 5090 graphics card and a base M4 Mac. For any other card or Mac, find your row in [community-baselines.md](community-baselines.md).
- To measure your own machine, go to [section 8](#8-measure-your-own-machine).

## The short version

1. **There are two speeds, not one.** The model first *reads* your prompt (everything sent to it: your message, attached files and the conversation so far), then *writes* its answer. Both are counted in tokens, which are word pieces: as a rule of thumb, 1,000 tokens is about 750 English words. "Tokens per second" in an app almost always means writing. Reading decides how long you wait before anything appears.
2. **Fitting in fast memory matters more than anything else.** A model that does not fit in your graphics card's memory (VRAM) runs 5 to 10 times slower.
3. **Writing speed has a ceiling set by memory speed. Reading speed is set by computing power.** On the same small model, a base M4 Mac trails an RTX 5090 by about 12 times at writing and by more than 60 times at reading.
4. **Long prompts cost real time.** In one test the same 4,000-token prompt was read in 0.15 seconds on an RTX 5090 and 17 seconds on an M4 MacBook Air ([source](https://scottjg.com/posts/2026-05-05-egpu-mac-gaming/)).
5. **Thinking counts as writing.** Many models write notes to themselves before the visible answer. You wait through them at writing speed.
6. **On the same model file, runtimes that share an engine differ by a few percent.** A runtime is the program that runs the model: Strata, LM Studio, llama.cpp, Ollama. A different engine or file format can change speed by 15 to 30%, and the gap is large when the model does not fit or when a runtime guesses ahead ("drafting").
7. **A repeated prompt is not a fair test.** Runtimes reuse work on text they have just seen. That helps in a real conversation, but it is not the speed you get on new text: one very large model ran 1.2 to 4 times faster on repeats. Measure with different text each run.

## 1. Two speeds and a wait

Think of someone who has to read a brief before answering it.

| Step | Name you will see | Typical speed | What it costs you |
|---|---|---|---|
| Read the prompt | prefill, prompt processing, prompt eval | thousands of tokens per second on a big GPU, hundreds on most Macs (thousands on an M5 Pro or better) | the wait before the first word |
| Write the answer | decode, generation, eval | tens to hundreds of tokens per second | how fast text streams out |

Prompts grow quickly. 16,000 tokens is about 64,000 characters, a few source files (arithmetic, at 4 characters per token).

**Time to finish a request = prompt tokens ÷ reading speed + output tokens ÷ writing speed.**

Output is the answer plus any thinking the model writes first. At 20 tok/s, 200 to 600 thinking tokens add 10 to 30 seconds of silence after the reading is done (arithmetic).

Model names carry two numbers. "9B" means 9 billion parameters, the numbers a model is made of (also called weights). "4-bit" says how tightly they are compressed (section 2.5). A name like `35B-A3B` means 35 billion parameters, of which about 3 billion are used for each token (section 2.1).

Here is the sum for one job on three setups: a 16,000-token coding prompt with a 500-token answer and no thinking, using measured rates.

| Machine and model | Reading | Writing | Total | Where the rates come from |
|---|---|---|---|---|
| RTX 5090, Qwen3.6-35B-A3B (4-bit, llama.cpp) | 16,000 ÷ 7,714 = 2.1 s | 500 ÷ 271 = 1.8 s | **about 4 s** | [RTX 5090 dataset](https://huggingface.co/datasets/witcheer/rtx-5090-benchmarks) |
| Base M4 Mac, a 9B model (4-bit) | 16,000 ÷ 230 = 70 s | 500 ÷ 20 = 25 s | **about 95 s** | [24 GB M4 test](https://computingforgeeks.com/ollama-lm-studio-mlx-mac/) |
| RTX 5090 + 128 GB RAM, DeepSeek V4.1 Flash (2-bit, Strata 0.2.13; later versions dropped this model) | 3.1 s + 16,000 ÷ 2,600 = 9.3 s | 500 ÷ 27.2 = 18.4 s | **about 28 s** | [this repo](../results/2026-11-23/README.md), repetitive text |

These are sums from measured rates, not measured totals. Three cautions:

- The writing rates in the first two rows were measured after short prompts. They are somewhat lower after a long one (section 2.4).
- The Mac's reading rate was measured on a 1,663-token prompt, so its 16,000-token time is an extrapolation.
- The third row adds 3.1 seconds because that engine spent about 3 seconds on every request before its reading rate applied ([details](benchmark-design.md#what-the-files-show-row-by-row)).

The Mac spends most of its time reading. DeepSeek, a 763-billion-parameter model far larger than the card's memory, spends most of its time writing. A single "tok/s" figure would hide both facts.

**How writing speed feels** (subjective):

| Writing speed | Feel |
|---:|---|
| under 10 tok/s | slow for chat |
| 10 to 20 | usable, long answers take a while |
| 20 to 40 | comfortable |
| 40 to 80 | quick |
| over 80 | a 500-word answer in under 10 seconds |

Even 10 tok/s is about 7 words per second (arithmetic). Higher speeds pay off when you skim, generate code, or the model thinks before it answers.

**The second question is cheaper than the first.** With every message, the app sends the whole conversation again: its built-in instructions (the system prompt), any files, and all earlier messages. Runtimes keep what they have already read, so when that earlier part is unchanged, only your new message is read. In one coding-agent session the first 9,443-token prompt took 10 seconds and later turns took 1 to 2 seconds ([Strata docs](https://github.com/Niko1221/Strata/blob/main/docs/DETAILS.md)). Editing an earlier message, swapping a file or changing the instructions makes the runtime read again from that point.

## 2. What decides your speed, in order of importance

### 2.1 Does the model fit in fast memory?

Fast memory means the graphics card's VRAM on a PC, or the unified memory of an Apple Silicon Mac. Two things have to fit there: the model file (its size is on the download page) and working memory for the context (about 2 GB at 16,000 tokens and a little over 4 GB at 32,000 for an 8B model, section 2.4).

Every way of not fitting is silent. Nothing tells you; the model just runs slowly.

| What happens when it does not fit | Measured |
|---|---|
| Only part of a normal ("dense") model fits on the card, and the rest runs on the CPU | 53 to 55 tok/s became 2 to 10 in user reports (16 GB cards: a file that fits against a larger Q4 or Q5 one that does not) |
| Another program is already holding the VRAM | 180 tok/s became 18 |
| Windows quietly moves the overflow into ordinary RAM | 102 tok/s became 13.7 |
| A Mac starts swapping to disk | a 19 GB model on a 24 GB Mac ran at 5.7 tok/s |

Sources and details are in [community-baselines.md](community-baselines.md#5-what-moves-a-number-more-than-the-hardware-does).

How to check:

- `llmbench doctor` (section 8) shows how much VRAM an NVIDIA card has and how much is in use. A run warns when shared GPU memory or swap grows while it measures.
- On Windows without it: Task Manager, Performance, GPU. "Dedicated GPU memory" is the VRAM. "Shared GPU memory" that grows while the model loads is the overflow.
- On a Mac: Activity Monitor, Memory. Watch "Memory Pressure" and "Swap Used". On a 24 GB Mac the system lets the GPU use about 19 GB (17.8 GiB), so a model file plus its context should stay near 16 GB.

**Mixture-of-experts (MoE) models are the exception that makes small cards useful.** A model named like `35B-A3B` has 35 billion parameters but uses only about 3 billion for each token. The unused "experts" can wait in ordinary RAM, so the PC needs enough free RAM for the part of the file that is not on the card (the 4-bit file measured in this repo is 22.85 GB). With that, a 35B MoE still writes at 19 to 68 tok/s on 8 to 12 GB cards. Where it lands in that range depends on RAM speed and one setting (tip 5).

A dense 27B model has no such escape: at 4 to 5 bits it dropped to 2 to 10 tok/s in user reports when it spilled off a 16 GB card. It stays usable on a small card only when squeezed much harder, which costs quality (about 30 tok/s at 2 bits on one [8 GB card](https://llamaperf.com/gpu/rtx-5060-8gb)).

### 2.2 Memory speed sets the writing ceiling

What to take from this section:

- **Slow memory, big model: you run close to the ceiling** (a Mac reaches 80% or more). No setting except drafting will double it.
- **Fast memory, small active model: you are far below the ceiling.** The time goes to fixed work done for every token, which is where drafting and parallel requests (section 3) help.
- **A drive is 100 or more times slower than VRAM.** Anything read from disk for every token dominates everything else.

Why: to write one token, the engine reads every weight it uses once. Memory delivers only so many gigabytes per second, which is its bandwidth. So:

**Fastest possible writing speed ≈ gigabytes per second the memory delivers ÷ gigabytes read per token.**

For a dense model, gigabytes per token is about the file size. For a MoE model it is only the active part: a `35B-A3B` file at about 5 bits per weight reads about 1.9 GB per token, not 22 GB.

| Where the model sits | Bandwidth |
|---|---:|
| RTX 5090 | 1,792 GB/s |
| RTX 4090 | 1,008 GB/s |
| RTX 3090 | 936 GB/s |
| Apple M4 | 120 GB/s |
| Apple M4 Pro | 273 GB/s |
| Apple M4 Max | 410 or 546 GB/s, by version |
| Apple M5 | 153 GB/s |
| Apple M5 Pro | 307 GB/s |
| Apple M5 Max | 460 or 614 GB/s, by version |
| Desktop RAM, two sticks of DDR5-6000 | 96 GB/s on paper, about 78 measured |
| Ryzen AI Max+ 395 "Strix Halo" | 256 GB/s on paper, about 215 measured |
| A fast NVMe SSD (PCIe 4.0) | about 7 GB/s in a straight read, far less for scattered reads |

Graphics card and RAM figures are specifications (bus width × speed ÷ 8). Apple's are its stated peaks.

Worked examples. "Ceiling" is arithmetic; "measured" is what people get.

| Setup | GB read per token | Ceiling | Measured | Share of ceiling |
|---|---|---:|---:|---|
| Base M4, 7 to 9B model at 4-bit | 4.7 to 5.3 GB | 23 to 26 tok/s | 15 to 24 | 65 to 92% |
| RTX 5090, 7B model at 4-bit | 3.8 GB | 1,792 ÷ 3.8 ≈ 470 tok/s | 300 | about 64% |
| RTX 5090, 35B MoE with 3B active at 5.1 bits | about 1.9 GB | ≈ 940 tok/s | 183 to 271 | 20 to 29% |
| DeepSeek V4.1 Flash at 2 bits, the experts used per token (about 8.7B parameters) read from desktop RAM | about 2.2 GB | 36 to 44 tok/s | 21 to 28 on new text with 128 GB; 15 to 16 when part comes from the SSD | about 50 to 80% for the first figure; it depends on how much is already in fast memory |
| Same model, experts read from an NVMe SSD | about 2.2 GB | 1 to 3 tok/s | about 5 | above the ceiling, because much of the model was already cached in 64 GB of RAM |

Sources: [bandwidth-bound decoding](https://arxiv.org/pdf/2608.28048), llama.cpp scoreboards ([CUDA](https://github.com/ggml-org/llama.cpp/discussions/15013), [Apple](https://github.com/ggml-org/llama.cpp/discussions/4167)), [Apple](https://www.apple.com/newsroom/2024/10/apple-introduces-m4-pro-and-m4-max/), [Puget Systems](https://www.pugetsystems.com/parts/Video-Card/NVIDIA-GeForce-RTX-5090-32GB-Extended-Lead-Times-16123/). The percentages are our arithmetic from those sources.

### 2.3 Computing power, and model size, set the reading speed

Reading a prompt processes many tokens at once, so it uses the GPU's full computing power instead of waiting on memory. On the same 7B model an RTX 5090 reads about 15,000 tok/s and a base M4 about 220. That gap of more than 60 times is hardware.

A bigger model reads more slowly on the same card: about 7,700 tok/s for a 35B MoE on the RTX 5090, and about 2,600 for the 763B model in this repo. So one machine has many reading speeds, one per model.

The only real cure for slow reading is not re-reading: keep prompts cacheable (section 1) and keep them short.

### 2.4 How long the conversation already is

A longer context costs twice. It takes longer to read, and each new token must look back over everything before it.

- One test of an 8B model on an RTX 5090 wrote 186 tok/s with 4K tokens of context, 112 at 32K and 49 at 131K ([hardware-corner.net](https://www.hardware-corner.net/en/rtx-5090-llm-benchmarks/)).
- The context also needs memory of its own: roughly 131 to 147 MB per 1,000 tokens for an 8B model with a 16-bit cache, so about 4 to 4.5 GiB for a 32K window ([survey, Table 1](https://arxiv.org/pdf/2608.28048); [worked calculation](https://sebastianraschka.com/llm-architecture-gallery/kv-cache-calculations/)).

The **context window** is the most tokens (prompt plus answer) a loaded model can hold. It is chosen when the model loads, by you or by the runtime, and its memory is reserved up front. A window far larger than you need can push the model out of fast memory. 16,000 tokens holds about 12,000 words (arithmetic) and is a reasonable first setting for chat.

### 2.5 Compression (quantization)

A model is a long list of numbers called weights. A "4-bit" file stores each one in about 4 bits instead of 16. Smaller files fit in more places and move fewer bytes, but answers get less accurate as the bits go down, and the speed gain is smaller than the size gain. 4-bit is the usual balance. Go lower only when nothing else fits.

In llama.cpp's own table for an 8B model, shrinking from 15 GiB to 4.6 GiB raised writing speed from 29 to 72 tok/s, and shrinking further to 1.9 GiB only reached 80. Reading speed did not improve at all ([table](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md)). See [quantization-primer.md](quantization-primer.md).

### 2.6 Power and heat

- A MacBook Pro on battery in Low Power Mode wrote at 28 tok/s, against 63 on mains in High Power mode.
- A fanless MacBook Air settled at 69 to 77% of its cold speed after about two and a half minutes of load. Once warm it was 7 to 12% slower on mains than on battery.
- Capping an RTX 3090 from 350 W to 250 W cost about 1%. At 200 W it cost 36%.

So: switch off Low Power Mode, keep the power source the same when you compare runs, and do not fear a moderate GPU power limit.

## 3. Ceilings: what is possible and what is not

| Question | Answer |
|---|---|
| Can a setting make writing much faster than the bandwidth ceiling? | Only "drafting", where the runtime guesses several tokens and checks them in one pass. Measured gains are 1.4 to 2.2 times on dense models, with the top of the range on JSON-like or repetitive text. On MoE models results run from a loss to about 1.35 times in llama.cpp, and to about 1.6 times in Strata's own tests of its engine. On creative text or on llama.cpp's Mac backend it can be slower. |
| Can reading be made much faster? | Mostly not. It follows GPU power. Batch size moved it by 1.3 to 1.8 times in two tests, and one badly chosen offload setting cut it 5 times. Caching avoids repeating it. |
| Can I get more total output from the same card? | Yes, by serving several requests at once. In [Strata's own test](https://github.com/Niko1221/Strata/blob/main/docs/QWEN36.md) on a 32 GB Radeon card, eight parallel requests gave 2.8 times (llama.cpp) to 3.9 times (Strata) the total output. Each request ran at about a third to a half of its solo speed (arithmetic: 2.8 ÷ 8 and 3.9 ÷ 8). |
| Will a faster SSD raise tok/s? | Not when the model is already in memory. It shortens loading. It matters during generation only for models so large that parts are read from disk for every token. |
| Will more system RAM help? | Only for models larger than VRAM. For DeepSeek V4.1 Flash on one RTX 5090, reports run from about 10 tok/s with 64 GB ([one user's post](https://llamaperf.com/report/a3d7a2c1-059e-48dd-a878-d7c172f4cd6c)) to about 37 with 384 GB on a server board ([Strata issue 4931](https://github.com/Niko1221/Strata/issues/4931)). The two machines differ in more than RAM. |
| Does a bigger context window cost anything if I do not fill it? | It reserves memory, and on some engines it slows writing even when mostly empty. Set it on purpose. |

What other people measure on hardware like the two machines behind this repository. The tables are in [community-baselines.md](community-baselines.md), where you can also find other cards and Macs.

- **RTX 5090 with 128 GB RAM.** A 35B MoE at 183 to 271 tok/s without drafting (310 measured here with drafting on repeated text, a best case). A dense 27B at about 77 to 80. A 120B MoE that does not fit at about 46 by keeping experts in RAM (measured with 64 GB). A 763B model at about 2 bits at 15 to 28 tok/s on new text and up to 36 on repeated text (21 to 27 measured here, on repeated text). It read a 250,000-token prompt in about 100 seconds.
- **Base M4 with 24 GB.** A dense 7 to 9B model at 15 to 24 tok/s (25 to 28 with drafting). A 20B MoE (gpt-oss-20b) at 26 to 36, faster than the smaller dense model because only part of it is used per token. A 35B MoE squeezed to 3 bits at anywhere from 16 to 58 in user reports, depending on the build and on whether its experts are moved out of memory. Reading at roughly 70 to 450 tok/s, so long prompts take minutes.

## 4. The runtimes in plain words

Four of these run models and serve the same kind of local web address that other apps can talk to. The fifth, Bionic, is an agent app that uses LM Studio's. They differ in how much they decide for you.

| | What it is | Usual address | Shows speed | Runs on |
|---|---|---|---|---|
| **llama.cpp** | The engine most others are built on. A command-line server (`llama-server`) and a raw speed test (`llama-bench`). Most control, least hand-holding. | `127.0.0.1:9931` (was 8080 before October 2026) | in every reply, as `timings` | Windows, macOS, Linux |
| **LM Studio** | A desktop app that downloads and runs models. Uses llama.cpp for GGUF files and Apple's MLX on Macs. | `127.0.0.1:1234` | under each chat message | Windows, macOS, Linux |
| **LM Studio Bionic** | A separate *agent* app from the same company (July 2026). It runs local models on the same runtime as LM Studio (llama.cpp for GGUF, MLX on Macs), which it carries built in, so it also works without LM Studio installed. | same as LM Studio | not shown in the app | Windows, macOS, Linux |
| **Ollama** | A one-command model runner. Since May 2026 it starts llama.cpp's server underneath for GGUF files and uses MLX on Macs for others. | `127.0.0.1:11434` | `ollama run --verbose` | Windows, macOS, Linux |
| **Strata** | A newer engine (first release September 2026) built to run very large MoE models on ordinary PCs by spreading them across VRAM, RAM and SSD. | `127.0.0.1:8080` | in every reply, as `timings` | Windows, Linux, Apple Silicon (new) |

### What to expect from each

**llama.cpp.** The reference point. When someone quotes a speed without naming a runtime, it is usually this. Recent builds choose most settings automatically (how much goes on the GPU, the context size from the model, how many requests it serves at once), so two people with "default settings" may not be running the same thing. Builds improve quickly: the same card and file went from 153 to 180 tok/s within weeks.

**LM Studio.** When a model fits, published same-file tests mostly put it 0 to 9% behind llama.cpp (seven of eight results in three write-ups); one found it 29% behind on an M3 Max. Four defaults explain most surprises:

- The context window is 8,000 tokens ([changelog](https://lmstudio.ai/changelog/lmstudio/lmstudio-v0.4.16)).
- The model loads on the first message, so that reply is slow.
- A model loaded that way unloads after 60 idle minutes, so the first reply after a break is slow again ([docs](https://lmstudio.ai/docs/developer/core/ttl-and-auto-evict)).
- When a chat grows past the context window, the default overflow policy ("Truncate Middle") drops messages from the middle with no warning and keeps the system prompt and the first user message. A single prompt that is itself longer than the window is not trimmed: users report an error or an empty reply ([546](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/546), [2256](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2256), [2339](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2339)).

On a Mac, try both the MLX and the GGUF version of a model: on a 24 GB M4, LM Studio's MLX engine wrote 15% faster than its llama.cpp engine.

**Bionic.** Treat it as LM Studio's engine with an agent on top. If LM Studio is open, Bionic uses the model LM Studio has loaded, with LM Studio's settings, so that is what you are measuring. Its automatic context sizing has loaded a 176,000-token window on an RTX 5090, which overflowed from VRAM into ordinary RAM and turned 3-second replies into 33 to 41 seconds ([report](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2543)). Load the model yourself with an explicit context size if replies feel slow.

**Ollama.** The easiest start and, with a GGUF file, the same engine as llama.cpp. Two defaults matter. The context window depends on your VRAM: 4K below 24 GiB, 32K up to 48 GiB, 256K above ([docs](https://github.com/ollama/ollama/blob/main/docs/context-length.mdx)). And when a chat is longer than the window, the oldest messages are dropped without an error, which makes a long prompt look fast because most of it was never read.

**Strata.** Different in kind. It is not a general model runner: it runs the model families its engines implement (in November 2026: Qwen3.8-Flash-Next, Qwen3.6-35B-A3B, Hy4-Flash and Inkling-2-Mini). What to expect:

- **On models larger than your VRAM, large gains over llama.cpp in the vendor's own test.** The maintainers report 41.6 tok/s against 9.1 for a tuned llama.cpp (9.6 with its defaults) on an RTX 3060, with the same file ([their test](https://github.com/Niko1221/Strata/blob/main/docs/bench-results/2026-10-06-llamacpp-0.6.0/README.md), 6 October 2026, llama.cpp v0.6.0). The test predates llama.cpp's own expert cache (`--moe-cache-mib`, merged the next day), which llama.cpp's authors measured at 1.6 to 2.2 times on the same model family. It is the vendor's own figure, for a model larger than that card. How large the gap is on your model depends on how llama.cpp is set up (tip 5).
- **On models that fit, close to llama.cpp at short prompts**, plus built-in drafting: 84 against 74 tok/s without drafting in the vendor's test and 109 against 92 in one user's. On Qwen3.6 it falls behind as the context fills (60 against 87 tok/s at 16K, 7.6 against 40 at 64K in user reports, [issue 2464](https://github.com/Niko1221/Strata/issues/2464)).
- **Results move.** Its expert cache adapts while it runs: the maintainers saw up to 9% between repeated runs, one RTX 5090 report saw ±15% at a fixed configuration, and speed depends on the kind of text.
- **It ships almost daily** ([74 releases](https://github.com/Niko1221/Strata/releases) in two months). Always write down the app and engine versions.
- **Known rough edges in late 2026:** Qwen3.6 writing speed falls steeply as the context fills, DeepSeek V4.1 Flash was dropped after version 0.2.13, and Mac support is new (Qwen3.6 does not run there; on a 24 GB Mac the model that fits is Inkling-2-Mini in Strata's SQ-15 format, a 14 GB file).

### Which one should I use?

| Situation | Reasonable choice |
|---|---|
| The model fits in VRAM and I want it to just work | LM Studio or Ollama |
| I want every setting under my control, or I am benchmarking | llama.cpp |
| I want a MoE model far larger than my VRAM, on a PC with enough RAM to hold it | Strata if it supports that model; otherwise llama.cpp with experts kept in RAM (tip 5) |
| I am on a Mac | LM Studio with the MLX version of the model, which wrote 15% faster than the GGUF version in one test. Measure both: in the same test Ollama's MLX runner without drafting was 6% slower than its GGUF one. |
| I want an agent that edits files and runs tools | Bionic or any agent, pointed at whichever engine is fastest for you |

## 5. Tips, ranked by how much they usually help

| # | Do this | Why | Measured effect |
|---|---|---|---|
| 1 | **Pick a model and compression level that fits in fast memory** with a couple of GB to spare. | Overflow is the largest slowdown there is. | 5 to 10 times |
| 2 | **Close other programs that use the GPU**, including a second model runner left open. | They hold VRAM. Your model silently lands on the CPU. | 10 times in one write-up |
| 3 | **Set the context window on purpose.** Large enough for your prompts, no larger. 16,000 tokens is a good first value. | It uses memory, and automatic sizing can overshoot. | 33 to 41 s replies became 3 s |
| 4 | **Keep the start of your prompt stable** across turns. | Lets the runtime skip re-reading. | 10 s became 1 to 2 s |
| 5 | **Short of VRAM? Prefer a MoE model** and keep its experts in RAM (llama.cpp: `--cpu-moe`, `-ncmoe N`, `--moe-cache-mib`; or use Strata). | Only a small part is needed per token. | 19 to 68 tok/s on 8 to 12 GB cards, where user reports of a dense 27B at 4-bit spilling off a 16 GB card run from 2 to about 11 |
| 6 | **Leave Low Power Mode off, and use the same power source for every run you compare.** Expect thin fanless laptops to settle lower after a few minutes. | Power and heat limits. | more than 2 times between battery in Low Power Mode and mains in High Power mode, in one test |
| 7 | **Try drafting and measure it on your own kind of text.** Apps call it speculative decoding. Some model files have it built in and say "MTP" in the name. | Big gains on predictable text and dense models. Can lose on MoE, on creative text, and on llama.cpp's Mac backend. It also slows reading. | from about 0.6 to 2.3 times with a 2-token draft (up to 3 times on code or repetitive text with a longer draft) |
| 8 | **Keep the runtime up to date and write down its version.** | New models often get faster in the weeks after release. | 153 to 180 tok/s between builds 12 days apart, in one case |
| 9 | **If part of the model lives in system RAM, make the RAM fast**: turn on XMP or EXPO in the BIOS and use two matched sticks. | RAM bandwidth becomes your ceiling. | not measured here (arithmetic: the section 2.2 ceiling scales with RAM bandwidth) |
| 10 | **Leave the K and V cache types at their defaults** (llama.cpp `-ctk` and `-ctv`, and the matching LM Studio settings). If you change one, set both to the same value. | In [one report](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2246), different values made an NVIDIA card fall back to a slow path. | more than 6 times |
| 11 | **Do not buy a faster SSD for tok/s** unless your model is so large that it reads from disk while writing. | In-memory generation never touches the disk. | measured: a 22 GB model loaded in 11.8 s from a CPU-attached Gen 5 drive and 14.0 s from a chipset-attached Gen 4 drive, and wrote 230 to 241 tok/s from either ([2026-11-28](../results/2026-11-28/README.md)) |
| 12 | **Need more total output, not a faster single reply? Use parallel requests.** | The card can do more work per pass. | 2.8 to 3.9 times at eight requests in Strata's Radeon test; on an RTX 5090, 1.7 times at four in LM Studio and none in Strata 0.2.21 |

On Windows with an NVIDIA card, one more: in NVIDIA Control Panel, under Manage 3D Settings, set "CUDA - Sysmem Fallback Policy" to "Prefer No Sysmem Fallback". The setting is meant to make a full card fail instead of spilling into system memory, where one over-full run was 7 times slower (102 tok/s became 13.7). Strata's documentation lists it, for the engine's program, as one of three fixes, after leaving a VRAM reserve and choosing a smaller context window. It is not a guarantee: the same page reports a 16 GB RTX 5080 with the setting on that still fell from 40.9 to 16.6 tok/s when no VRAM was left free.

## 6. Things people believe that are not true

| Belief | What the measurements say |
|---|---|
| "My setup does 80 tok/s." | That is one speed of two, at one prompt length. Among machines that write about 80 tok/s, a 16K prompt means a wait of about 4 seconds (RTX 5090, dense 27B) to about 13 (M4 Max) (arithmetic from community-baselines.md). On a base M4, which writes about 20 tok/s, it is about 70 seconds. |
| "A 2-bit model is twice as fast as a 4-bit one." | Going well below 4 bits gave 1 to 25% over the common 4-bit file (Q4_K_M) in llama.cpp's table, about 11% for most 2-bit formats, and some small formats are slower than larger ones. |
| "A bigger context window is free until I use it." | It reserves memory and can slow writing. |
| "A faster SSD makes generation faster." | Only for models that read from disk on every token. |
| "Run the same prompt three times and average." | Three runs are right. The same prompt is not: the second and third runs can reuse the first. DeepSeek V4.1 Flash measured 1.2 to 4 times faster on repeats than on new text. Use different text of the same length each time. |
| "Runtime X is twice as fast as runtime Y." | On the same file with the model in memory, LM Studio, Ollama and llama.cpp were within 6% in four of five tests and 9.5% apart in the fifth. Large gaps usually mean one of them did not fit the model, used a different context size, was drafting, or **had thinking on**. This repository made that mistake itself: Strata looked about twice as fast as LM Studio until both ran one file with thinking off ([2026-11-28](../results/2026-11-28/README.md)). |
| "Drafting always helps." | It ranged from almost 40% slower (a fast 30B MoE on prose, RTX 5090) to 2.3 times faster (a dense 27B on code and repetitive text, same card), and up to 3 times with a longer draft, depending on model, text and backend. |

## 7. Comparing two numbers honestly

Before believing that A is faster than B, check that both used:

1. the same model file (not just the same model name) and the same runtime version;
2. the same number of prompt tokens, counted by the server, not the configured window;
3. fresh text for each run, or cached text for each run, but not a mix;
4. the engine's own timing, or the same stopwatch method on both;
5. at least three runs, with the difference larger than the runs vary among themselves.

`llmbench` checks items 2 and 3 for you, counts three runs of every scenario that measures speed (the end-of-run control runs twice), compares any difference with the run-to-run spread (item 5), and says which kind of timing (item 4) it used. Its design is explained in [benchmark-design.md](benchmark-design.md).

## 8. Measure your own machine

1. Download this repository (on GitHub: Code, then Download ZIP, and unpack it) and open a terminal in its folder.
2. Start your runtime and load a model, with a context window of 16,384 tokens or more.
3. Run the two commands below. They are written for macOS and Linux. On Windows type `py` where they say `python3`.

```bash
python3 -m llmbench doctor
```

```bash
python3 -m llmbench run --suite quick
```

`doctor` describes your machine and finds the running runtime. `run` reports reading speed, writing speed and how long typical requests take. It needs under a minute on a fast PC when the model fits in VRAM, up to about three minutes with a very large model, and about 8 minutes on a base M4 Mac. These are arithmetic from the section 1 rates (about 74,000 tokens read and 2,800 written), not timings: `llmbench` has not yet been run against a loaded model. Step-by-step setup for each runtime is in [llmbench.md](llmbench.md).

Is your number good? Find your hardware in [community-baselines.md](community-baselines.md) and compare. If you are far below it, check in this order: does the model fit (section 2.1), is another program using the GPU, is the context window larger than you need, is the machine in a low-power mode.

## 9. Questions people ask next

**Which file should I download first?** One that leaves a couple of GB of fast memory free after the context is added (section 2.1). "GGUF" files work in llama.cpp, LM Studio and Ollama on any system. "MLX" files are for Macs. A name with `Q4_K_M` or "4-bit" is the usual compression choice.

**I have no NVIDIA card. Does this apply to me?** Yes. Everything here applies to AMD, Intel and Apple graphics, and `llmbench` measures any runtime. Only its VRAM readout and its temperature sampling need an NVIDIA card.

**What should I buy?** This page does not give buying advice. The two numbers that decide local speed are how much fast memory you have (what fits) and its bandwidth (how fast it writes). Section 2.2 lists both.

**How much quality do I lose with a smaller or more compressed model?** This repository measures speed only. Treat 4-bit as the default, and judge anything lower on your own tasks.

**How do I switch thinking off?** Look for a "reasoning" or "thinking" setting on the model in your app, or send `"reasoning_effort": "none"` with each request (LM Studio and Strata both honour it). `llmbench run --thinking off` asks the runtime to do it for a test, and the result shows whether it worked. Answers can get worse without thinking, so compare both on your own tasks. On one JSON-extraction job, Qwen3.6 with thinking off was 4.2 times faster and about as accurate; on a short JSON task with thinking on it never reached an answer within 2,048 tokens.

**Do LM Studio and Ollama keep a MoE model's experts in RAM by themselves?** Both choose their own split when a model is larger than the card. In one test of a 16.8 GB MoE on an 8 GB laptop card, Ollama wrote 43.6 tok/s and LM Studio 27.8 with automatic settings, against 38.8 for llama.cpp with `-ncmoe 99` ([kingy.ai](https://kingy.ai/blog/ollama-vs-lm-studio-vs-llama-cpp/)). We have not verified what each keeps in RAM. Most small-card results quoted on this page used llama.cpp's flags; two name no engine and one used LM Studio.

**Is the benchmark safe to run?** It talks only to the address you give it, or looks for a runtime on six usual ports of your own machine. It reads facts about the machine with the system's own tools, writes its result under `local-results/` (a small file, about 100 KB), changes no setting and sends nothing to the internet. If no model is loaded, LM Studio and Ollama will load one on its first request.

**Should I close my chat or agent app during a run?** Yes, or at least leave it idle. A second program using the model or the GPU changes the numbers. The run uses the model you loaded and does not unload it.

**Can I raise a Mac's GPU memory limit?** Yes, with `sudo sysctl iogpu.wired_limit_mb=<megabytes>`, until the next restart. It lets a larger model load and leaves less for everything else. The one measured case on a 24 GB Mac ended in swap at 5.7 tok/s (section 2.1). `doctor` shows whether the limit is the macOS default.

## Glossary

| Term | Meaning |
|---|---|
| Token | A word piece. About 0.75 English words. |
| Prompt | Everything sent to the model for one reply: instructions, files, earlier messages and your new message. |
| Runtime | The program that runs the model: Strata, LM Studio, llama.cpp, Ollama. |
| Engine | The part of a runtime that does the computing. Several runtimes share llama.cpp's. |
| Parameters, weights | The numbers a model is made of. "9B" means 9 billion of them. |
| Prefill, prompt processing | Reading the prompt. |
| Decode, generation | Writing the answer. |
| TTFT, time to first token | Wait from sending the request until the first token arrives. Mostly reading time. |
| Context | The text the model is working with: the prompt plus what it has written so far. |
| Context window | The most tokens (prompt plus answer) a loaded model can hold. Set when the model is loaded. |
| KV cache | The engine's working memory of the tokens read so far. Grows with the context. |
| Prefix cache, prompt cache | Reusing that working memory when a new request starts with the same text. |
| Cold, warm | Cold is the first request after the runtime or the model has just started, which is slower. Warm is every request after that. |
| VRAM | Memory on the graphics card. |
| Unified memory | Apple Silicon's single pool shared by CPU and GPU. |
| Shared GPU memory | On Windows, ordinary RAM that the graphics driver uses when VRAM is full. Slow. |
| Memory bandwidth | How many gigabytes per second memory can deliver. |
| Quantization, "Q4", "4-bit", bpw | Storing weights with fewer bits. bpw is bits per weight. |
| GB, GiB | Two ways to count the same bytes. 1 GiB is about 1.07 GB. Download pages usually show GB. |
| GGUF | The model file format used by llama.cpp, LM Studio and Ollama. |
| MLX | Apple's machine-learning framework for Apple Silicon, with its own model format. |
| Dense model | Every weight is used for every token. |
| MoE, mixture of experts | Only a few "experts" are used for each token. `35B-A3B` means 35 billion parameters, 3 billion active. |
| Offload | Placing part of a model on the GPU and the rest elsewhere. |
| Drafting, speculative decoding, MTP | Guessing several tokens cheaply, then checking them in one pass of the full model. |
| Thinking, reasoning tokens | Tokens a model writes to itself before the visible answer. They take time and count as output. |
| Engine timing | Speed measured inside the runtime. More exact than timing from outside. |
