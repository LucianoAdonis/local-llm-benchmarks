# Install a runtime and model

`llmbench` checks the machine and runtime, then measures a running model. It never downloads anything automatically or changes runtime settings. Model files can be tens or hundreds of gigabytes, so confirm the publisher, format, quantization, and disk space first. The explicit `llmbench pull` command delegates LM Studio/Bionic downloads to `lms get`; Strata manages its own model packs and engine support files.

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
