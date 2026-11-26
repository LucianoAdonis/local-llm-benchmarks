# Install a runtime and model

`llmbench` checks the machine and runtime, then measures a running model. It never downloads anything automatically or changes runtime settings. Model files can be tens or hundreds of gigabytes, so confirm the publisher, format, quantization, and disk space first. The explicit `llmbench pull` command delegates LM Studio/Bionic downloads to `lms get`; Strata manages its own model packs and engine support files.

## Guided first setup

After installing the package, run:

```sh
llmbench setup
llmbench doctor
llmbench models list
```

`setup` checks Python, `uv`, Homebrew, Strata, the LM Studio CLI (`lms`), and the Hugging Face downloader. It shows the relevant setup steps for anything missing and does not install apps or alter your runtime automatically.

On a new Mac, the shortest path is:

```sh
brew install uv
uv tool install --force --with huggingface_hub git+https://github.com/LucianoAdonis/local-llm-benchmarks.git
llmbench setup
```

Install LM Studio from its official download page if you want Bionic/LM Studio, or install Strata using the official macOS instructions below. Open LM Studio once and enable its `lms` command if you want to use the app's model library. For llama.cpp, `brew install llama.cpp` is optional. The benchmark tool itself has no required Python packages; `huggingface_hub` is only for catalog downloads.

### Choose and store a starter model

The catalog has small, workstation, and large/offload tiers. Set a destination on a roomy internal or external SSD once:

```sh
llmbench config set download-dir /Volumes/ModelSSD/llm-models
llmbench config show
```

On a Mac without an external drive, choose a folder with enough free space, such as `~/Models/llmbench`. Then pull the model you selected:

```sh
llmbench models list
llmbench models pull qwen9b-q4
# or, for a bigger machine:
llmbench models pull qwen27b-q4
```

Override the saved destination for one download with `--dir /path/to/folder`. Catalog downloads use Hugging Face's resumable client. The downloaded GGUF can be imported into LM Studio with its model import flow or `lms import /path/to/file.gguf`. Check the source model card and license first. A catalog GGUF is not automatically a Strata pack; use `strata launch` for Strata-managed formats and support files.

The 177B MoE entry is an intentional large-model experiment, not a recommended first Mac download. Its total weight footprint and context cache need to fit the host's available memory; if macOS starts swapping, expect a substantial slowdown. A fast SSD can help model loading and experiments but cannot make disk paging behave like unified memory.

### Export a result

Every benchmark result is saved as JSON by default. Export a shareable Markdown summary or spreadsheet-friendly CSV alongside it:

```sh
llmbench export local-results/run.json --format markdown
llmbench export local-results/run.json --format csv
llmbench export local-results/run.json --format json --output share/run-copy.json
```

Markdown and CSV contain summaries. JSON keeps the detailed result data; review it before sharing, and use `llmbench sanitize SOURCE DESTINATION` if you want the built-in path/address redaction applied. Always inspect exported files for private details.

## Strata

Use Strata's official installer, then follow its guided model setup. The installer selects the right engine for your system; `strata launch` guides model, context, storage, and serving choices.

Windows PowerShell:

```powershell
irm -TimeoutSec 120 https://github.com/Niko1221/Strata/releases/latest/download/install.ps1 | iex
strata launch
```

macOS or Linux:

```sh
curl -fsSL --connect-timeout 15 --max-time 120 https://github.com/Niko1221/Strata/releases/latest/download/install.sh -o install.sh
sh install.sh
strata launch
```

The desktop installer is also available from [Strata releases](https://github.com/Niko1221/Strata/releases). Use `strata launch --help` for current options. For an unattended model install, inspect the plan first and only then confirm the explicit download flags shown by that Strata version.

## LM Studio and Bionic

In Bionic, open **Settings → Local Models → Explore**, choose the model format and quantization, and download it. In LM Studio, use **Discover** or the bundled CLI. The CLI can show recommended models, or search and download a named model with a quantization:

```sh
lms get
lms get llama-3.1-8b@q4_k_m
llmbench pull --backend bionic --model llama-3.1-8b@q4_k_m
lms ls
```

`llmbench pull` requires the bundled `lms` command on `PATH` and forwards its interactive prompts and errors. It runs only when you invoke the command.

Start LM Studio's local server in its Developer tab or run `lms server start`. To pin a context and GPU placement from the terminal:

```sh
lms load my-model@q4_k_m --context-length 16384 --gpu max
```

Replace `my-model@q4_k_m` with the installed model identifier shown by `lms ls`. Use the same model identifier and context when benchmarking. See the [LM Studio Bionic model guide](https://lmstudio.ai/docs/bionic/models/download-local-models) and [LM Studio CLI guide](https://lmstudio.ai/docs/cli).

## Check and benchmark

With the runtime and model ready:

```sh
llmbench doctor
llmbench selftest
llmbench run --suite quick --context 16384 --label "runtime version, model quant, settings"
```

`doctor` reports the local machine and reachable runtimes. The benchmark records the model/runtime details the server exposes and validates that the requested prompt fits the configured context. Results go to `local-results/`; compare a later iteration with `llmbench compare BEFORE.json AFTER.json`.

See [what happens when a runtime retires a model](model-retirement.md).
