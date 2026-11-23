# Strata replication playbook

This is a repeatable, skill-like procedure for preparing Strata, installing the tested model variants, and running the coding-context benchmark. It is written for Windows PowerShell, matching the recorded machine. Strata changes its model catalog and flags over time; verify commands with the installed version’s `--help` before using them.

## When to use this

Use this procedure to establish a baseline before changing a GPU, system RAM, SSD, Strata/engine version, quantization, or inference setting. It is also suitable for collecting a comparable run on another machine.

## Requirements

- Windows 11, NVIDIA GPU with a supported driver, and enough RAM/storage for the selected model.
- Strata Terminal or desktop app and an installed model profile.
- Python 3.10+ (the included clients use only the standard library).
- The public model files are not included here. Check model cards and licenses before downloading.

## 1. Install Strata

Use Strata's official Windows installer in PowerShell, then open a new terminal and launch its guided setup:

```powershell
irm -TimeoutSec 120 https://github.com/Niko1221/Strata/releases/latest/download/install.ps1 | iex
strata launch
```

The guided UI offers model selection and install steps. If `strata` is not on `PATH`, open the installed Strata Terminal app and use its terminal, or follow the current [official Strata install guide](https://github.com/Niko1221/Strata/blob/main/docs/INSTALL.md). Check what was installed:

```powershell
strata --version
strata doctor --output json
strata models list --output json
```

Do not mix model weights from a different quantization with a Strata pack/config. Keep the source model revision, quantization, file name, and Strata/engine version in the run record.

## 2. Install the exact model variant

Use the copy-ready text in [`../prompts/model-download-requests.md`](../prompts/model-download-requests.md) in the Strata model selector/assistant. If a request is not listed in the current release, use its model card and the matching Strata-supported pack. For this recorded run:

- DeepSeek V4.1 Flash IST-DAS 2.00 bpw was run under a separate Strata 0.2.13 install with engine 0.1.59 because Strata 0.2.20 marked that model retired.
- Inkling-2-Mini and Qwen3.6 were run under Strata 0.2.20 with engine 0.1.66.
- DeepSeek’s Strata pack is a multi-file package with shared Engram/DSpark files. Use a Strata-managed pack; downloading one GGUF shard alone is not a complete install.

Model cards: [DeepSeek ISTA-DASLab](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF), [Inkling Strata packs](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata), [Inkling Unsloth GGUF](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF), [Qwen3.6 Unsloth MTP GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF).

Approximate download sizes observed on this PC: DeepSeek pack about 257 GB; Inkling SQ-10 10.47 GB; SQ-15 14.35 GB; SQ-20 19.35 GB; Inkling UD-Q3_K_XL 13.63 GB; Inkling UD-Q4_K_M 16.61 GB; Qwen3.6 UD-Q4_K_XL 22.85 GB. Allow additional space for shared support files, conversion/preparation, and temporary downloads.

## 3. Prepare a context profile

Use a separate named profile for each model and context capacity. The tested profile capacities were:

- `32768` for the short and medium context baseline.
- `131072` for the long coding-context comparison.
- `262144` for DeepSeek’s near-full-context run.

Only set a context size supported by that model build and your available memory. Context is an upper capacity, not a promise that a prompt of that length will be fast or fit every quantization. For the exact DeepSeek model, 256K was tested; Inkling/Qwen were tested at 128K in this comparison.

In the installed model’s run config, copy the config to a new file, change the integer immediately following `--max-context` in `args`, and give the new config a distinct `log` path. Then create and validate a Strata profile. Example:

```powershell
strata profile create my-model-128k --from-config C:\path\to\strata-my-model-128k.json
strata profile validate my-model-128k --output json
```

For a profile created from the installed model config, ensure model paths still point to the installed files. Do not overwrite your working profile; keep a separate baseline and context variant.

## 4. Record a Strata standard baseline

Strata’s standard benchmark follows its published fixed protocol and writes local JSON evidence. For a supported Strata profile:

```powershell
strata bench run --profile my-model-128k --track custom `
  --track-notes "Strata version, engine version, model revision, quantization, context and settings"
```

The protocol is version-specific. Check `strata bench run --help`; save the output folder and do not call it a coding-quality benchmark. The custom suite below complements it with deterministic synthetic coding input at selected depths.

## 5. Run the coding-context suite

Start only one model/runtime at a time. Close GPU-heavy applications, stop other Strata profiles, and use the model’s exact API model name. From the repository root:

```powershell
python scripts/strata_coding_context_benchmark.py `
  --url http://127.0.0.1:8080/v1/chat/completions `
  --model inkling-2-mini-sq-10 `
  --sections 100 --runs 3 --max-tokens 100 `
  --context 131072 --timeout 600 `
  --profile inkling-sq10-128k `
  --output results/my-run.json
```

The same workload has about 5.7K API prompt tokens at 35 sections, 16K at 100 sections, and around 50–65K at 400 sections depending on tokenizer. The near-full 32K case used 170 sections for Inkling and produced about 27.5K prompt tokens. Always use actual `prompt_tokens` in the JSON, not the section count.

For DeepSeek, use engine-log capture to distinguish backend timings from client streaming:

```powershell
python scripts/strata_deepseek_engine_benchmark.py `
  --url http://127.0.0.1:8080/v1/chat/completions `
  --model deepseek-v4.1-flash --sections 400 --start-run 1 --runs 2 `
  --max-tokens 100 --context 131072 --timeout 600 `
  --profile deepseek-coding-128k `
  --engine-log C:\path\to\the\profile-engine.log `
  --output results/deepseek-128k.json
```

For Qwen use `strata_engine_log_coding_benchmark.py` with `--engine-log` set to its run log. For Inkling, use the client harness; its prefill/decode-window values are client estimates rather than raw kernel timings.

## 6. Preserve and share results

Save one JSON per run, then redact before publishing:

```powershell
python scripts/sanitize_results.py results\local-run.json results\public-run.json
```

Read the output before sharing. The sanitizer replaces Windows home paths, local API URLs, and common API-key patterns, but no redactor can know every private detail. Never commit engine logs, `.env` files, model files, auth tokens, or private project prompts. This repository’s published JSON uses synthetic source and has been sanitized.

For each public run, record:

- CPU, GPU(s), VRAM, system RAM, OS, driver, storage, and background GPU load.
- Strata and engine versions, model source/revision, quantization, and profile settings.
- Configured context separately from actual prompt tokens.
- Repetition count, cache state, output cap, temperature, and measurement source (engine or client).
- Per-run JSON, median, and range; call out single-run results.

## 7. Interpret the result

Read prompt throughput and generation throughput separately. A large context may slow the first response while leaving decode comparatively fast. Client TTFC contains network/API/queue overhead. Compare runs only when workload, quantization, runtime, context depth, and cache policy match. Run a separate correctness suite before claiming one model is better at coding.

## Troubleshooting

- **Model retired or missing:** use a Strata version that supports the exact pack, or select a supported current model; record that change as a different configuration.
- **GGUF + Inkling DSpark missing tensor:** disable DSpark for that profile or use a native `.strata` pack. The recorded UD-Q4_K_M run used DSpark off; see [Strata issue #6762](https://www.stratat.com/en/issues/6762).
- **Out of memory at large context:** stop the runtime, lower context, or choose a smaller pack. Do not repeatedly relaunch the same failing profile without reducing resource demand.
- **No response from API:** check `strata status`, profile state, API URL, and the Strata engine log. Do not publish the log without redacting paths and credentials.
