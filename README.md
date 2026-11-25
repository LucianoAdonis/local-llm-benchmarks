# Local LLM Hardware Benchmarks

Repeatable speed tests for running language models on your own computer, plus plain-language guides to what the numbers mean. The aim is the kind of test people run on a new PC build: the same scenes every time, the machine recorded, the result checked, two runs compared honestly.

Three things live here:

1. **[`llmbench`](docs/llmbench.md)**, a small tool that measures the speed of the program running your model (Strata, LM Studio and its Bionic app, llama.cpp, Ollama). It needs only Python. It is written for Windows, macOS and Linux; the latest Windows PC run is recorded below.
2. **Guides**: what speed to expect, what limits it, and which settings matter.
3. **A first baseline** from one Windows PC, measured on 2026-11-23 with the earlier scripts.

## Start here

| If you want to… | Read |
|---|---|
| understand local LLM speed from scratch: what speed to expect from Strata, LM Studio, llama.cpp and Ollama, what limits it, and which settings matter | [docs/start-here.md](docs/start-here.md) |
| measure your own machine | [docs/llmbench.md](docs/llmbench.md) |
| see what other people get on similar hardware | [docs/community-baselines.md](docs/community-baselines.md) |
| know how the test is designed, and what was wrong with the first version | [docs/benchmark-design.md](docs/benchmark-design.md) |
| install Strata, Bionic, or a model | [docs/model-setup.md](docs/model-setup.md) |

## Measure your own machine

You need Python 3.9 or newer, this repository on your disk (on GitHub: Code, then Download ZIP, and unpack it; or clone it) and a runtime with a model loaded. Open a terminal in the unpacked folder, the one that contains `llmbench`. No Python packages are needed.

macOS and Linux:

```bash
python3 -m llmbench selftest
```

```bash
python3 -m llmbench doctor
```

```bash
python3 -m llmbench run --suite quick
```

Windows:

```powershell
py -m llmbench selftest
```

```powershell
py -m llmbench doctor
```

```powershell
py -m llmbench run --suite quick
```

`selftest` checks the stopwatch code against a fake server with known speeds. `doctor` describes your machine and finds running runtimes. `run` measures reading speed, writing speed and how long typical requests take, and prints the name of the file it saved after `Saved:`.

To compare two runs, name the files yourself with `--output`:

```bash
python3 -m llmbench run --suite quick --output local-results/before.json
```

Change one thing (a driver, a runtime version, one setting), run again with `after.json`, then:

```bash
python3 -m llmbench compare local-results/before.json local-results/after.json
```

On Windows type `py` where these say `python3`. Per-runtime setup, the scenario list and how to read the output are in [docs/llmbench.md](docs/llmbench.md).

## Install as a command

Python 3.9 or newer is required. Install the released command with `uv` on Windows, macOS, or Linux:

```sh
uv tool install git+https://github.com/LucianoAdonis/local-llm-benchmarks.git@v0.1.0
llmbench doctor
```

`pipx` also works if you already use it: `pipx install git+https://github.com/LucianoAdonis/local-llm-benchmarks.git@v0.1.0`.

On macOS with Homebrew:

```sh
brew install --formula https://raw.githubusercontent.com/LucianoAdonis/local-llm-benchmarks/main/Formula/llmbench.rb
```

The [GitHub release](https://github.com/LucianoAdonis/local-llm-benchmarks/releases) contains the wheel and source archive. The utility checks your computer and local runtime, then benchmarks the loaded model; it leaves model downloads and runtime changes to Strata or LM Studio. See [runtime and model setup](docs/model-setup.md).

## The 2026-11-23 baseline

One Windows PC across Strata models, from short prompts to a near-full 256K DeepSeek context. It is a performance record, not a model-quality ranking.

| Component | Configuration |
|---|---|
| CPU | AMD Ryzen 9 9950X3D (16 cores) |
| GPU | NVIDIA GeForce RTX 5090, 32 GB VRAM |
| System memory | 128 GB |
| OS | Windows 11 Pro |
| Storage during run | Kingston FURY Renegade G5 2 TB PCIe 5.0 NVMe in the first CPU-connected M.2 slot (`M2A_CPU`, owner-reported); Crucial T500 had not yet been installed |
| Strata | 0.2.20 / engine 0.1.66 for Inkling and Qwen; DeepSeek compatibility install 0.2.13 / engine 0.1.59 |

Models were installed locally; this repository contains no model weights.

These are one day's measurements with the earlier scripts, on repetitive text. They are probably best-case values, and the rows cannot be compared with each other. The notes under the table say why.

| Model / variant | Context profile | Actual prompt tokens | Reading (prefill) | Writing (decode) |
|---|---:|---:|---:|---:|
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 256K | 250,119 | 2,506 tok/s | 20.9 tok/s |
| Qwen3.6-35B-A3B UD-Q4_K_XL | 128K | 54,901 | 4,158 tok/s | 92.6 tok/s |
| Inkling-2-Mini UD-Q4_K_M | 128K | 64,513 | 2,716 tok/s* | 86.5 tok/s* |
| Inkling-2-Mini SQ-10 | 128K | 64,513 | 3,943 tok/s* | 64.9 tok/s* |

DeepSeek and Qwen speeds are the engine's own timings, read from its log. Inkling values marked `*` were timed from outside with a stopwatch, so its reading speed includes request overhead. See [all results and caveats](results/2026-11-23/README.md).

The DeepSeek 256K run read 250,119 prompt tokens plus a 100-token output cap (about 95.5% of its 262,144-token window). It took 102.6 seconds to first text.

### Read this before quoting these numbers

A later review ([docs/benchmark-design.md](docs/benchmark-design.md)) recomputed every number from the stored files. The arithmetic is sound and the tables contain no transcription errors. What the review changed is how the rows should be read:

- **The rows above cannot be ranked against each other.** They use two timing methods, and one "128K" label covers three prompt sizes (54,901 and 64,513 tokens above, and 50,119 for a DeepSeek row in the full results). A token is also a different amount of text for each model.
- **The test text was one Python class repeated hundreds of times.** That is probably close to a best case for engines whose speed depends on content. Other people measured DeepSeek V4.1 Flash 1.2 to 4 times faster on repeated content than on new content. These files cannot say how large the effect is here.
- **One row includes cached work.** Every DeepSeek 15.1K run reused 3,982 of its 15,119 prompt tokens from the earlier 4.5K runs.
- **First requests are slower.** The first run read its prompt most slowly in all 16 files that have more than one. The single-run rows are such first requests, and the engine log lines stored with the runs indicate that the 256K run was also the first request after an engine start.
- **The 27.6K DeepSeek row is an unexplained outlier**, not evidence that a nearly full window halves speed.
- **No answer text arrived in any Qwen run.** Its 100 generated tokens were most likely thinking, so there is no time-to-first-answer for it.

They remain a fair record of what was measured on that day. New measurements should use `llmbench`, and the two should not be mixed in one table.

## The 2026-11-25 PC iteration

Using `llmbench` 0.1.0 on the same Ryzen 9 9950X3D / RTX 5090 PC and Strata 0.2.21.1 / engine 0.1.67, the 32K Inkling SQ-10 run measured **195 tok/s at 3.5K prompt tokens** and **168 tok/s at 14.5K**, with about **7.1K tok/s reading** at the larger depth. Qwen3.6 UD-Q4_K_XL measured **284 tok/s at 3.4K** and **215 tok/s at 14.6K**, with **9.6K tok/s reading** at the larger depth. Each scenario has three runs. Both results carry cautions: Strata reported hidden thinking tokens, and Qwen reached 97% VRAM use. These diverse-corpus quick runs are not direct comparisons to the older repeated-text baseline or Strata's native standard suite. See the [sanitized results and full run details](results/2026-11-25/README.md).

## Models and files

| Model | Parameters | Tested file/quant | Local download size |
|---|---|---|---:|
| [DeepSeek V4.1 Flash 1017](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF) | 763.2B total; 6/384 routed experts active per token | IST-DAS IQ2_XXS backbone, 2.00 bpw, plus Engram and DSpark | 256.81 GB total pack |
| [Inkling-2-Mini](https://huggingface.co/thinkingmachines/Inkling-2-Mini) | 26.4B total; 3.4B active | [native SQ-10 / SQ-15 / SQ-20](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata); [UD-Q3_K_XL / UD-Q4_K_M GGUF](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) | SQ-10 10.47 GB, SQ-15 14.35 GB, SQ-20 19.35 GB, UD-Q3_K_XL 13.63 GB, UD-Q4_K_M 16.61 GB |
| [Qwen3.6-35B-A3B](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) | 35B total; 3B active | [UD-Q4_K_XL MTP GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/blob/main/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf) | 22.85 GB |

The file sizes above are measured local downloads; DeepSeek's package includes support files in addition to its 2.00 bpw backbone. See the [model catalog](docs/model-catalog.md) for exact filenames, GB/GiB breakdowns, parameter explanations, and direct file links. Model licenses and acceptable-use terms belong to their publishers.

## More background

- [How to read tok/s and what to expect on this PC](docs/expected-performance.md)
- [Quantization primer: 4-bit versus DeepSeek at 2.00 bpw](docs/quantization-primer.md)
- [Storage topology and planned Kingston-versus-T500 test](docs/storage-follow-up.md)
- [Strata replication playbook](docs/strata-replication.md) and [copy-ready model requests](prompts/model-download-requests.md)
- An AI-assistant-ready procedure: [`skills/strata-local-benchmark/SKILL.md`](skills/strata-local-benchmark/SKILL.md)

## How the test is designed

- Reading the prompt (prefill) and writing the answer (decode) are separate measurements.
- The first token of any kind starts the writing clock. Model thinking is output too.
- Every run gets a random marker and different, varied text, so no cache can reuse earlier work. Cached tokens reported by the runtime are checked, and a "fresh" run that hit a cache is thrown out.
- Prompts are sized in tokens for each model, not in characters or sections. A configured context window is capacity, not the number of tokens supplied.
- Engine timings are preferred. Stopwatch figures are labelled as such.
- One uncounted first read at each size, then repeated runs. Medians with the spread, never a single best run.
- The machine, power state, runtime and model details are recorded automatically.
- Every result says whether it is clean, usable with cautions, or invalid.
- Speed and quality are separate evaluations.

Details and the reasoning are in [docs/benchmark-design.md](docs/benchmark-design.md). The structure borrows conventions from [Strata's benchmark protocol](https://github.com/Niko1221/Strata/blob/main/docs/BENCHMARK_PROTOCOL.md), [llama-benchy](https://github.com/eugr/llama-benchy), [llama.cpp `llama-bench`](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench) and MLPerf Client. The code here is original; no benchmark tool code was copied from those projects.

## Reproducing the v1 baseline

The scripts in `scripts/` produced the 2026-11-23 numbers and are kept so those can be re-derived. They carry the limitations described above; use `llmbench` for anything new.

1. Install Strata and the same model variants: [docs/strata-replication.md](docs/strata-replication.md), [prompts/model-download-requests.md](prompts/model-download-requests.md).
2. Start one profile and run the matching script against Strata's OpenAI-compatible endpoint. Example (PowerShell):

```powershell
python scripts/strata_coding_context_benchmark.py `
  --url http://127.0.0.1:8080/v1/chat/completions `
  --model inkling-2-mini-sq-10 `
  --sections 400 --runs 2 --max-tokens 100 `
  --context 131072 --timeout 600 `
  --profile inkling-sq10-128k `
  --output results/my-run.json
```

This is the command behind the Inkling SQ-10 128K row (400 sections, 64,513 tokens, two runs). `--sections` controls the synthetic repository size; model tokenizers count the same text differently, so use the reported `prompt_tokens` as the actual input depth. Always pass `--max-tokens 100`: the script's default is 128. For engine-log timing collection, see [the playbook](docs/strata-replication.md#5-run-the-coding-context-suite). The DeepSeek rows can only be reproduced on Strata 0.2.13, the last release that ran that model.

## Known limitations

- The baseline was measured on a repetitive synthetic prompt with the v1 scripts. See "Read this before quoting these numbers" above.
- The DeepSeek GGUF-pack run used Strata 0.2.13 / engine 0.1.59 because later Strata releases dropped this model.
- Inkling UD-Q4_K_M was run with DSpark disabled due to a Strata GGUF + DSpark missing-tensor issue ([Strata issue #6762](https://github.com/Niko1221/Strata/issues/6762)).
- The synthetic code-review input checks serving behavior, not code-review correctness.
- An earlier 82.3 tok/s DeepSeek figure is superseded. It came from a token-accounting error: the script divided all 100 billed tokens by the time in which 33 of them were generated. The original explanation, stream buffering, is neither confirmed nor ruled out by the files ([details](docs/benchmark-design.md#what-the-files-show-row-by-row)). Use the engine-timed results.
- `llmbench` has now been run on Windows against a loaded Strata model, and its 151 unit tests pass locally on Windows. The macOS smoke run used the built-in test server and LM Studio's model listing; Linux remains to be confirmed by CI. If a number looks wrong, please open an issue.

## Repository layout

- `llmbench/` — the benchmark tool. `tests/` — its unit tests (`python3 -m unittest`, or `py -m unittest` on Windows).
- `docs/` — guides, community baselines, benchmark design, and the Strata replication playbook.
- `prompts/` — copy-ready model install requests and the v1 workload description.
- `scripts/` — the v1 benchmark clients and engine-log parsers (kept for the record) and a results redactor.
- `results/2026-11-23/` — sanitized metadata, summary, and per-run JSON from the v1 baseline.
- `results/2026-11-25/` — sanitized Strata/Bionic engine runs and the first v2 `llmbench` run on the baseline PC.
- `Formula/` and `.github/workflows/release.yml` — Homebrew formula and tagged wheel/source release.
- `docs/model-setup.md` — runtime installation and native model download steps.
- `local-results/` — where `llmbench` saves by default. Ignored by Git.

## License and attribution

Original documentation and scripts are released under the MIT License. This does not license, redistribute, or change the terms of any model weights, Strata, llama.cpp, or other upstream software. See [LICENSE](LICENSE).
