# Plan: a desktop manager for local LLM engines

Status: draft for review, 2026-11-27; revised 2026-11-28 after the same-file engine runs in [results/2026-11-28](../results/2026-11-28/README.md), which overturned the earlier reading that Strata is about twice as fast as LM Studio (see [section 2.1](#21-what-the-2026-11-28-runs-changed)). Working name in this document: **Anvil** (placeholder; pick a real name before the first public release, see [open questions](#12-open-research-questions)).

Anvil is to local LLM engines what Stability Matrix is to Stable Diffusion front ends: one desktop app that installs and updates the engines (Strata, LM Studio first; llama.cpp and Ollama next), downloads models once and makes them available to every engine, keeps engine configurations as named profiles, runs `llmbench` and turns the results into reports, and looks at the PC itself to suggest upgrades that would actually help (VRAM, RAM, SSD, slot placement). Windows and macOS ship first. Linux comes for free with the chosen stack but is not a release target until someone tests it.

This plan is written so that a coding agent (Claude on Monday, or a local model later) can start at [section 9, "Day one"](#9-day-one-checklist) and work down the phases. Every phase ends in something that runs and can be checked.

---

## 1. Decisions at a glance

| Question | Decision | Why, in one line |
|---|---|---|
| App framework | **Tauri 2** (Rust core) with a **React + TypeScript** UI | Small installers, native webview, first-party updater and signing flow, and the React frontend the friend suggested without Qt's C++ and licensing weight. |
| 3D PC view | **three.js through react-three-fiber**, procedural model from detected specs | Runs in the webview, no extra runtime; BuildCores renders later through their React client. |
| Benchmark engine | Reuse **`llmbench`** from this repo, shipped as a sidecar binary | It already measures Strata, LM Studio, llama.cpp and Ollama, and `llmbench diagnose` already emits app-ready JSON. Do not rewrite it in phase 1. |
| Model storage | One **shared model library** on disk; engines see models through hard links (same volume) or symlinks / engine import (other volume) | The Stability Matrix pattern; avoids storing a 23 GB GGUF twice. |
| Engine integration | One **adapter per engine** behind a common Rust trait | Each engine installs, updates and stores models differently; the UI should not care. |
| Releases | GitHub Actions matrix, **tauri-action**, GitHub Releases as the update feed | One tag builds, signs and publishes both platforms; the app updates itself from `latest.json`. |
| Signing | Apple Developer ID + notarization; Windows via **Azure Trusted Signing** (now branded Artifact Signing) | The cheapest path that removes Gatekeeper and SmartScreen warnings. Unsigned builds are acceptable only for private alphas. |
| Repo | New repo for the app (`anvil`), this repo stays the benchmark library | Keeps `llmbench` small and pip-installable; the app pins a `llmbench` version. Engine and benchmark findings and fixes land here first, then the app picks them up by bumping the pin. |
| Engine recommendations | **Measured per task, never from tok/s alone**; every comparison holds model file, context and thinking state fixed | Thinking state, parallel slots and schema enforcement each changed the winner on the reference PC more than the engine did. |
| Default model settings | **Thinking off** unless the user turns it on for a profile; parallel slots set explicitly | Thinking off made a real job 4.2 times faster at similar accuracy; four LM Studio slots gave 1.7 times more output. |

---

## 2. What already exists in this repo

The app is not starting from zero. `llmbench` (v0.2.0, stdlib-only Python, 153 unit tests, CI on Windows/macOS/Linux) already does most of the hard measurement and detection work:

| Capability | Where | How the app uses it |
|---|---|---|
| Runtime detection: Strata (`/health` service=strata, `/props`), LM Studio (`/api/v0/models`), Ollama (`/api/version`, `/api/ps`), llama.cpp (`/props`) | `llmbench/runtimes.py` | The engine status panel; also confirms an engine an adapter just started is actually serving. |
| Machine description: CPU, cores, RAM size/modules/speed, GPUs + driver, disks (bus, media, size), power plan, shared-GPU-memory spill on Windows | `llmbench/sysinfo.py` | Feeds the hardware page, the 3D model and the upgrade advisor. |
| Benchmark suites (quick / standard / deep), prefill vs decode separated, cache detection, validity verdicts | `llmbench/bench.py`, `metrics.py`, `workload.py` | The Benchmarks page runs `llmbench run --suite quick --output …` and renders the JSON. |
| Noise-aware A/B | `llmbench compare` | "Before / after" view when the user changes a setting or a part. |
| App-shaped diagnostic JSON (schema `llmbench-diagnostic/1`): live state, preflight warnings, run summaries, evidence-backed findings, suggested follow-up measurements | `llmbench diagnose`, [docs/diagnostics.md](diagnostics.md) | The upgrade advisor's main input. The four-step flow in that doc becomes the Benchmarks page. |
| Curated starter model catalog with byte sizes and tiers | `llmbench/catalog.py` | Seeds the model browser before a Hugging Face search exists. |
| LM Studio download delegation (`lms get`), setup checks for Strata / `lms` / uv / Homebrew | `llmbench pull`, `llmbench setup` | Adapter logic to port into Rust (or call) in phase 2. |
| Redaction of paths, addresses, secrets | `llmbench sanitize` | Applied before any report is exported or shared. |
| Structured-output probe (`schema` scenario) and thinking-aware `compare` | `llmbench/bench.py`, `llmbench/report.py` | Fills the engine capability table ("holds JSON to the schema: yes / no") and stops the Benchmarks page from presenting a thinking-on against thinking-off comparison as an engine race. |
| Real data from the reference PC (Ryzen 9 9950X3D, RTX 5090 32 GB, 128 GB RAM, Kingston Gen5 + Crucial T500) | `results/` | Fixtures for UI development and advisor tests. `results/2026-11-28/` is the first same-file engine comparison (thinking on and off, parallel, schema); `results/2026-11-26-storage/` is the DeepSeek offload drive A/B. |

Gaps the app must fill: installing and updating engines, a model library with sync, engine configuration profiles, a GUI, packaging and updates.

### 2.1 What the 2026-11-28 runs changed

The first draft of this plan leaned on the 2026-11-25 results, where Strata's numbers looked about twice LM Studio's. Those runs had Qwen's thinking on, and the Strata and Bionic figures came from different model files and timing sources. Measured again on one Qwen3.6 UD-Q4_K_XL file:

| Question | Finding | What the app does with it |
|---|---|---|
| Is Strata faster than LM Studio? | With thinking off, Strata writes 0 to 35% faster on one request and the gap is gone at a 16K prompt. On a whole JSON job Strata was 15% slower. | No engine is "the fast one". Recommend per task from the user's own measurements. |
| What decided job time? | Thinking. Off was 4.2 times faster on a real job at similar accuracy; on a short JSON task Qwen with thinking on never reached an answer within 2,048 tokens. | Profiles carry an explicit thinking setting, off by default; the Benchmarks page always shows it and can run both. |
| Do parallel requests help? | LM Studio: 1.7 times the output at four requests (its default is 4 slots). Strata 0.2.21: none with one slot, and worse with four. | Profiles carry parallel slots; the advisor suggests them when work arrives concurrently. |
| Is JSON held to the schema? | LM Studio: yes, by grammar. Strata: no; it prompts with the schema and answers HTTP 502 `structured_output_failed` or passes on text that breaks `maxLength`. | Shown in the engine capability table; callers on Strata must validate and retry. |
| Does the drive matter? | Only at load: 11.8 s from the CPU-attached Kingston against 14.0 s from the chipset-attached T500, identical generation once in VRAM. | The advisor never suggests a drive change for tok/s on a model that fits in VRAM. |
| Smaller context or lighter quant? | 16K lost the longest inputs and was slower through retries; IQ3_M saved 5 GB of VRAM but was not faster and less accurate. | Suggest them only when VRAM is the constraint, never as a speed tip for a small-active MoE. |

---

## 3. Product scope

### 3.1 The Stability Matrix pattern, translated

| Stability Matrix does | Anvil does |
|---|---|
| Installs ComfyUI, SwarmUI, Forge… each into its own folder with its own Python env | Installs Strata, LM Studio (llmster headless or desktop), llama.cpp builds, Ollama, each through the engine's own official installer or release asset |
| Keeps one shared `Models` folder and links it into each package | Keeps one model library and links or imports each model into the engines that can use it |
| Updates packages from their git/release channels | Checks each engine's release feed, shows the changelog, updates on request, can pin or roll back |
| Per-package launch options | Per-engine **profiles**: model, context length, GPU layers / offload, KV cache type, flash attention, port, parallel slots, thinking on/off (off by default) |
| Model browser (CivitAI, Hugging Face) | Model browser (curated catalog, then Hugging Face search filtered to GGUF / engine-native formats) with a "will this fit?" estimate |
| — | Benchmarks and reports through `llmbench` |
| — | Hardware page with a 3D model of the PC and upgrade suggestions backed by measurements |

### 3.2 Out of scope for v1

Chat UI (the engines and their own apps already do that), fine-tuning, cloud providers, multi-machine management, Linux packaging, and redistributing any engine or model (the app always downloads from the official source).

### 3.3 Users and the main flows

1. **New machine:** open app → it detects hardware → recommends an engine and a first model that fits → installs both → runs a quick benchmark → shows the result next to community baselines.
2. **Existing setup (the reference PC):** app finds Strata on :8080 and LM Studio on :1234/:1235, imports their existing models into the library without copying, shows versions with update badges, and shows each engine's measured capabilities (thinking switch honoured, JSON schema enforced, parallel slots that help).
3. **Tuning:** pick a profile, change one setting, rerun, see the noise-aware comparison.
4. **Upgrade planning:** hardware page shows what limits this machine (for example "Qwen3.6 Q4 at 32K on Strata used 97% of VRAM; check for spill into shared memory") and ranks concrete upgrades by expected effect and evidence.

---

## 4. Framework comparison and recommendation

The friend's suggestion was Qt, possibly with a React frontend. That combination means Qt WebEngine (Chromium inside Qt) hosting React, which carries Electron's size plus Qt's build complexity and licensing. The realistic options:

| | **Tauri 2 + React** | Qt 6 (QML, or WebEngine + React) | Electron + React | Avalonia (.NET) | Flutter |
|---|---|---|---|---|---|
| Used by | many modern dev tools | KDE, many industrial apps | VS Code, LM Studio, Ollama's old app | **Stability Matrix itself** | Ubuntu installer |
| UI language | React/TS (huge ecosystem, agents write it well) | QML or C++ widgets; React only via WebEngine | React/TS | XAML + C# | Dart |
| 3D | three.js / react-three-fiber in webview | Qt Quick 3D (GPL or commercial licence) | three.js | limited; needs custom GL | limited |
| Installer size (hello world) | ~3–10 MB (uses WebView2 / WKWebView) | 30–80 MB; 150 MB+ with WebEngine | 80–150 MB | 30–60 MB | 20–40 MB |
| Memory at idle | low | low (QML) / high (WebEngine) | high | medium | medium |
| Backend for installs, processes, files | Rust (strong for downloads, hashing, processes) | C++ | Node | C# | Dart / platform channels |
| Auto-update | first-party plugin, signed `latest.json` | build your own or Qt Installer Framework | electron-updater (mature) | build your own (Velopack works) | build your own |
| CI / signing | `tauri-action` handles build, sign, notarize, publish | manual, `macdeployqt`/`windeployqt` | electron-builder handles it | manual or Velopack | manual |
| Licensing | MIT/Apache | LGPLv3 for core (dynamic linking, relinkable); some modules GPL-only; commercial otherwise | MIT | MIT | BSD |
| Webview differences between OSes | **yes** (WebView2 vs WKWebView); test both | no | no (ships Chromium) | no | no |
| Agent friendliness (Claude or a local model writing it) | high: TS + small, well-documented Rust | medium-low: QML + CMake + deployment tooling | high | medium | medium |

**Recommendation: Tauri 2 + React + TypeScript.** It gives the React UI the friend wanted, the smallest and fastest app, a Rust core that is good at exactly the hard parts here (multi-GB resumable downloads, hashing, hard links, child processes), and the least release plumbing because `tauri-action` covers building, signing, notarizing and publishing an update feed. Its one real cost is two webviews to test (Edge WebView2 on Windows, WebKit on macOS); keep the 3D scene on plain WebGL 2 and test it on both from phase 1.

**When Qt would be the better call:** if the app had to run without a webview, needed native widgets everywhere, or had a team already fluent in Qt/C++. None of those hold here, and Qt Quick 3D's licence (GPL or paid) is awkward for an MIT project. **Electron** is the fallback if the WebKit side causes real trouble on macOS: the React code moves over almost unchanged, at the price of a ~100 MB installer. **Avalonia** is worth knowing about because Stability Matrix proves it works for this exact kind of app, but it gives up the React frontend.

---

## 5. Architecture

### 5.1 Processes

```
┌──────────────────────── Anvil app (one process) ─────────────────────────┐
│  React UI (webview)                                                      │
│   pages: Home · Engines · Models · Profiles · Benchmarks · Hardware      │
│   3D scene (react-three-fiber)        state: TanStack Query + Zustand    │
│        │  Tauri commands (typed via tauri-specta) + events (progress)    │
│  Rust core                                                               │
│   engines/  (adapter trait + strata, lmstudio, llamacpp, ollama)         │
│   library/  (model store, hashing, links, HF client, download queue)     │
│   profiles/ (TOML profiles → engine launch args / API calls)             │
│   hardware/ (calls llmbench sysinfo/diagnose; native fallbacks)          │
│   advisor/  (rules over hardware + benchmark evidence)                   │
│   jobs/     (long tasks: install, download, benchmark; cancel, resume)   │
│   store/    (SQLite via sqlx: inventory, jobs, results index)            │
└───────┬──────────────────────────────┬───────────────────────────────────┘
        │ spawn sidecar                │ spawn / HTTP
   llmbench (frozen binary)       engines: strata (:8080), llmster/LM Studio (:1234),
   run · diagnose · compare        llama-server, ollama (:11434)
```

- The UI never touches the filesystem or network directly; every action is a Tauri command, and long actions are **jobs** that emit progress events and survive a UI reload. Jobs persist in SQLite so a download interrupted by a restart resumes.
- The app does not keep engines running in the background unless the user starts them. Engines it did not start (for example Strata already running) are detected and shown as "external", never killed.

### 5.2 Engine adapter interface

```rust
#[async_trait]
pub trait EngineAdapter: Send + Sync {
    fn id(&self) -> EngineId;                         // "strata", "lmstudio", ...
    async fn detect(&self) -> Result<Installation>;   // installed? version? path? running? port?
    async fn latest_release(&self) -> Result<Release>;// version, notes, asset url, published_at
    async fn install(&self, job: &JobCtx, opts: InstallOpts) -> Result<()>;
    async fn update(&self, job: &JobCtx, to: Option<Version>) -> Result<()>;
    async fn uninstall(&self, job: &JobCtx, keep_models: bool) -> Result<()>;
    fn model_formats(&self) -> &[ModelFormat];        // Gguf, StrataPack, Mlx, OllamaBlob
    async fn list_models(&self) -> Result<Vec<EngineModel>>;
    async fn expose_model(&self, m: &LibraryModel, how: LinkMode) -> Result<()>; // link/import
    async fn start(&self, profile: &Profile) -> Result<RunningEngine>;
    async fn stop(&self, run: &RunningEngine) -> Result<()>;
    fn openai_base_url(&self, run: &RunningEngine) -> Url; // what llmbench is pointed at
}
```

Per-engine notes (verify each during phase 2; these engines change monthly):

| Engine | Install / update | Models | Start with a profile |
|---|---|---|---|
| **Strata** | Measured 2026-11-28 (0.2.21.1 / engine 0.1.67): honours `reasoning_effort: none`; does **not** constrain decoding to a JSON schema (HTTP 502 `structured_output_failed`, or over-long fields; the check is skipped entirely when its Python `jsonschema` package is missing); one slot by default, and `parallel=4` lowered both single and total output. Official `install.ps1` (Windows) / `install.sh` (macOS) from `github.com/Niko1221/Strata/releases/latest`; desktop installer also exists. Update = rerun installer with a pinned version. Note: model support changes between releases (DeepSeek only runs on 0.2.13 / engine 0.1.59), so **pinning and side-by-side versions matter**. | Native packs (`SQ-10`…) managed by `strata launch`; also loads GGUF (the Inkling UD-Q4_K_M run). Pack location and a non-interactive pack install are open questions. | CLI flags or its config; serves OpenAI-compatible on :8080 with `/health` and `/props`. |
| **LM Studio** | Measured 2026-11-28 (llama.cpp CUDA runtime 2.83.0): honours `reasoning_effort: none`; holds JSON to the schema by grammar; loads with 4 parallel slots by default, worth 1.7 times the output at four requests. Desktop app installer, or headless **llmster** (`lms daemon up/down/status`, `lms daemon update`). Prefer llmster for app-managed installs; detect the desktop app if present. | `~/.lmstudio/models/<publisher>/<repo>/<file>.gguf`; `lms import` adds a file (check its link vs copy flags); `lms get` downloads. | `lms server start`, `lms load <id> --context-length N --gpu max`; REST `/api/v0/models` for state. |
| **llama.cpp** (phase 3) | Download the matching release asset (CUDA / Vulkan / Metal) from `ggml-org/llama.cpp` releases; Homebrew on macOS. | Any GGUF path. | `llama-server -m … -c … -ngl … --port …`. |
| **Ollama** (phase 3) | Official installer; `ollama --version`. | Own blob store; import GGUF through a Modelfile (`FROM ./file.gguf`), which copies, so mark it "copy required". | `ollama serve`; per-model params in Modelfile. |

### 5.3 Model library and sync

- **Library root** chosen at first run (default `~/Anvil/models`, recommend the fastest large SSD; the advisor can say which). Layout: `library/<publisher>/<repo>/<file>` mirroring Hugging Face, plus `library/.anvil/manifest.sqlite`.
- **Identity:** a model file is identified by SHA-256 (computed once, streamed while downloading) plus its HF `repo@revision/file`. This lets the app recognise that the GGUF in LM Studio's folder and the one in the library are the same file.
- **Adopt, don't copy:** on first run, scan each engine's model folders, hash files, and offer "move into library and link back" (same volume: hard link, zero extra space and no admin rights on Windows NTFS or macOS APFS) or "leave in place and index".
- **Expose to engines:** per model, a checkbox per compatible engine. Link mode is chosen automatically: hard link (same volume) → symlink (cross-volume; Windows needs Developer Mode or admin, so fall back) → engine import → copy (warn with the size). Strata packs stay Strata-only; GGUF can go to all four.
- **Sync** means: the library's manifest is the source of truth; a background check finds broken links, files an engine deleted, and new models an engine downloaded on its own, and offers to reconcile. No silent deletion, ever.
- **Downloads:** Rust HTTP client with range resume, parallel chunks for files over 1 GB, checksum against HF's LFS SHA-256, disk-space check before starting, and a queue. Hugging Face token stored in the OS keychain (`keyring` crate), never in a file.
- **"Will it fit?"** estimate shown before download: weights size + KV cache for the chosen context (from the GGUF header: layers, KV heads, head dim, cache type) against VRAM and RAM, with a "partial offload" band. Read GGUF headers with a small Rust parser (or the `gguf` crate).

### 5.4 Profiles (configuration)

A profile is a TOML file under `~/Anvil/profiles/` (human-editable, diffable, easy to share):

```toml
name = "qwen36-32k-lmstudio"
engine = "lmstudio"
engine_version = "2.83.0"     # optional pin (LM Studio runtime)
model = "unsloth/Qwen3.6-35B-A3B-MTP-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
context = 32768               # per slot; size it to the task's longest input
parallel = 4                  # LM Studio: 1.7x output at four requests on the reference PC
gpu_layers = "max"
kv_cache = "q8_0"
flash_attention = true
thinking = "off"              # explicit, off by default; sent as reasoning_effort "none"
port = 1235
[extra]                        # passed through verbatim to the engine
```

The adapter translates the common fields; `[extra]` covers engine-specific flags. A benchmark result stores the profile it ran with, so "before / after" comparisons are always one diff apart. `thinking` and `parallel` are never left implicit: they changed job time more than the choice of engine did, and an engine's own default (thinking on for Qwen3.6 in both engines; 4 slots in LM Studio, 1 in Strata) is recorded when the profile does not set them.

### 5.5 Benchmarks and reports

- Phase 1 ships `llmbench` as a **frozen sidecar** (PyInstaller or Nuitka one-file per platform, built in CI from a pinned tag of this repo). It is stdlib-only, so the freeze is small and simple. Alternative if freezing is painful: bundle python-build-standalone and run `-m llmbench`.
- The app calls `llmbench run … --output <file>`, `llmbench diagnose <files> --output -`, and `llmbench compare a b`, and parses the JSON. Add a `--progress-json` flag to `llmbench run` (one JSON line per finished run on stdout) so the UI can show live progress; that is a small change in this repo.
- Every comparison view shows the thinking state of both sides and refuses to label a winner when they differ (`llmbench compare` prints `THINKING DIFFERS`). A "thinking on vs off" pair is offered as its own one-click benchmark.
- Engine capability table, filled from `llmbench run --scenarios schema,parallel-4 --thinking off` per engine: schema enforced, refusals, retries needed, parallel gain, thinking switch honoured.
- Later (phase 4+): **task benchmarks**, the user's own job (for example 20 documents through a JSON extraction) timed end to end with an accuracy check against a reviewed sample. The 2026-11-28 runs showed tok/s and job time can rank engines differently.
- Reports: a results index in SQLite, a run detail view (TTFT, prefill, decode, spread, validity verdict, caveats), comparisons, and export to Markdown / CSV / JSON via `llmbench export`, always sanitized. Charts with a small library (visx or Recharts); keep validity warnings visible next to every number, as the repo's methodology requires.
- Later: optional anonymous submission to a community baseline (opt-in, sanitized, reviewed before sending).

### 5.6 Hardware detection and the upgrade advisor

Inputs: `llmbench diagnose` JSON (system, live state, findings) plus a few extra native reads the app adds in Rust: motherboard model and M.2 slot / PCIe link (Windows: `Win32_BaseBoard`, `MSFT_PhysicalDisk` / `Get-PhysicalDisk`, NVMe link via `Get-PnpDeviceProperty`; macOS: `system_profiler SPHardwareDataType SPNVMeDataType SPDisplaysDataType -json`), free RAM slots and max supported RAM (from `Win32_PhysicalMemoryArray`).

The advisor is **a set of explicit rules with evidence**, not a model guessing. Each suggestion carries: what was observed, which measurement shows it, the expected effect, confidence, and the next measurement that would confirm it. Starter rules:

| Observation | Suggestion | Evidence source |
|---|---|---|
| VRAM use above ~95% during a run, or shared GPU memory grew | Smaller quant or context; or a GPU with more VRAM. Decode speed is bound by VRAM bandwidth when the model fits, and collapses when it spills. | `gpu_shared_memory_mb`, GPU sampler, 97% VRAM caution in `results/2026-11-25` |
| Model + KV cache exceed VRAM but fit VRAM + RAM; RAM nearly full | More RAM (show free slots and max capacity); for MoE offload models, RAM bandwidth (channels, speed) matters | sysinfo RAM modules / speed, fit estimator |
| RAM runs below its rated speed (e.g. JEDEC default, XMP/EXPO off) | Enable XMP/EXPO in BIOS | `ram_speed_mhz` vs module rating |
| Models live on a SATA SSD or HDD, or a Gen5 drive sits in a chipset slot that negotiates Gen4 | Move the library to the fastest CPU-attached NVMe **only for load time or models larger than VRAM+RAM**; never as a tok/s fix for a model that fits in VRAM | disk bus, PCIe link; 2026-11-28: 22 GB model loaded in 11.8 s (Kingston, CPU lanes) against 14.0 s (T500, chipset), generation identical. The 2026-11-26 DeepSeek offload A/B showed a prefill difference that disk, slot and run order cannot separate, so it carries low confidence |
| The model thinks (reasoning tokens in the result) and the user's task is extraction, classification or mechanical edits | Try thinking off; offer the on/off pair benchmark | `reasoning_seen` / hidden tokens in the result; 2026-11-28: 4.2 times faster on a real job at similar accuracy |
| Requests arrive concurrently (agent tools, batch jobs) and the engine serves one slot | Raise parallel slots on an engine that gains from them, or move the job to one | `parallel-4` against `chat`; 2026-11-28: LM Studio 1.7 times, Strata 0.2.21 none |
| The user's workload needs JSON output and the engine does not enforce schemas | Prefer an engine that does, or validate and retry in the caller | `schema` scenario; 2026-11-28: Strata 0 of 3 first answers fit, LM Studio 3 of 3 |
| User asks for a lighter quant or smaller context to go faster on a small-active MoE | Explain it will not help speed; suggest it only to free VRAM | 2026-11-28: IQ3_M saved 5 GB, not faster, six of twenty answers changed; 16K lost the longest inputs |
| Library drive nearly full | Larger SSD, with the size needed for the user's current plus wished-for models | library manifest sizes |
| Power plan not High/Ultimate, or laptop on battery | Change power plan / plug in before benchmarking | `power_plan`, `power_source` |
| Old GPU driver | Update driver, then rerun and compare | driver version vs a known-good minimum table |

Upgrade suggestions show price-free part classes in v1 ("a 4 TB PCIe 4.0 NVMe in slot M2_1"); live part prices and links are a later research item.

### 5.7 The 3D PC view

- **v1 (procedural):** a stylised case built from primitives in react-three-fiber: motherboard plane, CPU block with cooler, RAM sticks (count from `ram_modules`, empty slots shown as ghosts), GPU sized by class (length/slot count from a small lookup by model name, default "2.5-slot, 300 mm"), M.2 drives on the board, PSU box. Labels on hover show the detected part and live numbers (VRAM in use, temperature). Parts that the advisor flags glow subtly. Orbit controls, soft studio lighting, no textures needed.
- Materials: brushed aluminium (`MeshPhysicalMaterial`, metalness 1, roughness 0.35–0.45, anisotropy), white powder-coat panels, glass side panel with low opacity. One HDRI environment map (studio, small, bundled).
- Fallback: a 2D annotated diagram if WebGL is unavailable.
- **Later: BuildCores.** BuildCores has a partner API and a React component (`@buildcores/render-client`, `BuildRender`) that shows a 360° sprite viewer from part IDs or a build share code, rendered in their cloud. It needs a BuildCores API licence and a session token minted server-side from a long-lived key, so it cannot ship the key inside the desktop app. Plan: let the user paste a BuildCores share link; show the render through a tiny token-minting proxy, or open it in the browser until a licence is arranged. See open questions.

### 5.8 UI design: minimalist, white and metal

- **Palette (light, default):** background `#F7F8FA` (paper white), surface `#FFFFFF`, raised metal `#E9ECEF → #D5D9DE` gradient, hairlines `#D0D5DB`, text `#1B1F24`, secondary text `#5B6470`, accent steel blue `#3D6A8A`, success `#2F7D5B`, caution `#B7791F`, danger `#B4413C`. **Dark ("graphite") theme:** `#121417` / `#1A1D21`, metal `#2A2E33 → #3A3F45`, text `#E6E8EB`.
- Type: Inter or IBM Plex Sans for UI, IBM Plex Mono / JetBrains Mono for numbers (tabular figures for tok/s).
- Feel: lots of whitespace, 1 px hairlines instead of boxes, subtle brushed-metal gradient only on the sidebar and primary buttons, 8 px radius, motion under 200 ms.
- Components: Radix primitives (or shadcn/ui on Tailwind) for accessibility; Tailwind design tokens hold the palette so both themes come from one file.
- Layout: left sidebar (Home, Engines, Models, Profiles, Benchmarks, Hardware, Settings); Home shows the 3D PC on the right and "engines running / last benchmark / top suggestion" cards on the left.

### 5.9 Security and trust

- Download engines only from their official URLs; verify checksums or signatures where published; show the URL before running any installer script. Running a `irm … | iex` style installer is shown to the user as exactly that, with an option to open the script first.
- Never elevate silently. Installs go to per-user locations; when an engine's installer needs admin, the OS prompt is the user's choice.
- Tauri capability files restrict which commands the UI can call; no remote content is loaded into the webview except the optional BuildCores viewer in an isolated frame.
- Secrets (HF token, BuildCores key if any) live in the OS keychain.
- Telemetry: none by default.

---

## 6. Repository layout (new `anvil` repo)

```
anvil/
  src-tauri/
    src/{main.rs, commands/, engines/{mod.rs,strata.rs,lmstudio.rs,llamacpp.rs,ollama.rs},
         library/, profiles/, hardware/, advisor/, jobs/, store/}
    binaries/llmbench-<target-triple>[.exe]   # sidecar, produced by CI
    capabilities/default.json
    tauri.conf.json
  src/                       # React + TS (Vite)
    pages/ components/ three/ (PcModel.tsx, parts/*.tsx) lib/ (bindings.ts generated)
    styles/tokens.css
  fixtures/                  # sample diagnose + result JSON copied from local-llm-benchmarks/results
  scripts/build-sidecar.(ps1|sh)
  .github/workflows/{ci.yml, release.yml}
  docs/{ARCHITECTURE.md, ENGINES.md, RELEASING.md}
  AGENTS.md / CLAUDE.md      # build, test and style rules for coding agents
```

Tooling: pnpm, Vite, Vitest + Testing Library (UI), Playwright for a smoke test of the built web UI, `cargo test` + `cargo clippy -D warnings`, `tauri-specta` to generate TS types for commands, Biome or ESLint + Prettier.

---

## 7. Phased roadmap

Each phase has a definition of done that can be checked without judgment calls.

### Phase 0: Skeleton and release pipeline (2–3 days)

Goal: a signed-or-unsigned "hello" app that builds on both OSes from one tag and updates itself.

1. `pnpm create tauri-app` (React + TS + Vite), add Tailwind tokens for both themes, sidebar layout with empty pages.
2. `ci.yml`: on PR, run lint, `vitest`, `cargo clippy`, `cargo test` on `windows-latest` and `macos-latest`.
3. `release.yml`: on tag `v*`, `tauri-action` matrix (windows-latest x64; macos-latest universal or arm64 + x64), creates a **draft** GitHub Release with installers and `latest.json`.
4. Updater plugin wired to `https://github.com/<owner>/anvil/releases/latest/download/latest.json`; generate the updater key pair (`tauri signer generate`), store private key + password as Actions secrets.
5. Build the `llmbench` sidecar in CI (PyInstaller from a pinned tag) and call `llmbench --version` from a Tauri command; show it in Settings → About.

Done when: tagging `v0.0.1` then `v0.0.2` produces installers for both OSes and a v0.0.1 install offers and applies the v0.0.2 update; About shows the llmbench version.

### Phase 1: Read-only dashboard (1 week)

1. Hardware page: run `llmbench diagnose`, render specs and live state; procedural 3D PC from the JSON (RAM stick count, GPU, drives).
2. Engines page: detect Strata, LM Studio (both desktop and llmster), llama.cpp, Ollama via `runtimes.detect` logic (call `llmbench doctor --json`, adding that flag to llmbench if missing) plus install-path detection in Rust; show version, running state, port, loaded model.
3. Benchmarks page: run `llmbench run --suite quick` against a detected engine with live progress (needs `--progress-json`), list results, open a result, compare two, export Markdown/CSV.
4. Load the repo's `results/` JSON as fixtures so the UI can be built without a GPU.

Done when: on the reference PC with Strata running, the app shows the 9950X3D / 5090 / 128 GB / two NVMe drives in 3D, lists Strata as running with its model, and a quick benchmark completes and appears in the list with a valid verdict.

### Phase 2: Engines install and update (1–2 weeks)

1. `EngineAdapter` trait, job system with progress, cancel, logs.
2. Strata adapter: install via official installer (version-pinned), detect versions, update with changelog from GitHub Releases, keep a previous version for rollback where the installer allows side-by-side.
3. LM Studio adapter: install llmster headless (or detect the desktop app), `lms daemon up/down`, `lms daemon update`, `lms load` with profile values.
4. Profiles: TOML read/write, editor UI, "start engine with profile", "benchmark this profile".

Done when: on a clean Windows VM and a clean Mac, the app installs Strata and LM Studio's llmster, starts each with a profile, and `llmbench` reaches both.

### Phase 3: Model library and sync (2 weeks)

1. Library root, manifest, hashing, adopt existing models (hard link back), broken-link repair.
2. Download queue from the curated catalog, then Hugging Face search (GGUF filter, file list with sizes, quant picker).
3. Expose-to-engine matrix (per model × engine), link-mode fallback chain, Ollama import as copy.
4. "Will it fit?" estimator from GGUF headers and detected VRAM/RAM.
5. llama.cpp and Ollama adapters.

Done when: Qwen3.6 UD-Q4_K_XL downloaded once is visible and loadable in Strata, LM Studio and llama.cpp, the library uses about 23 GB of disk for it, not 69 GB, and deleting it from one engine does not delete the library copy.

### Phase 4: Advisor and reports (1 week)

1. Native extra reads (motherboard, slots, PCIe link, max RAM).
2. Advisor rules from 5.6 with unit tests built from the repo's real result files.
3. Suggestions on the Hardware page and highlighted in 3D; "measure to confirm" buttons that start the right benchmark.
4. Report builder: one page per machine with specs, benchmark table, suggestions, export.

Done when: with the 2026-11-25 Qwen result loaded, the app flags VRAM pressure **and** that thinking was on; with the 2026-11-28 files loaded it suggests thinking off and parallel slots, marks Strata as not enforcing schemas, and says a drive change affects load time only; and comparing `lmstudio-thinking-default.json` with `lmstudio-thinking-off.json` shows the thinking warning instead of a winner.

### Phase 5: Polish and public beta

Signing on both platforms (if not already), crash reporting opt-in, onboarding flow, docs site, accessibility pass, dark theme, BuildCores share-link view, translations later (the owner's first language may be Spanish; the strings should be extractable from day one).

---

## 8. Releases and packaging across platforms

### 8.1 Pipeline

- **Versioning:** SemVer, tag `vX.Y.Z` on `main`. Changelog generated from Conventional Commits (release-please or git-cliff). Channels: `stable` and `beta` (beta reads `latest-beta.json`).
- **Build matrix (GitHub-hosted):** `windows-latest` → NSIS `.exe` (and optionally `.msi`); `macos-latest` (Apple Silicon) → `.dmg` + `.app.tar.gz` for the updater, built as `universal-apple-darwin` or two separate arch builds. Linux AppImage/deb can be added to the matrix later at no code cost.
- **Sidecar:** a job before the Tauri build freezes `llmbench` per target and places it at `src-tauri/binaries/llmbench-<triple>`. On macOS the sidecar must be signed with the same Developer ID and hardened runtime, or notarization fails; Tauri signs declared `externalBin` entries, but verify with `codesign -dv --verbose=4` and `spctl -a -vv` in CI.
- **Publish:** `tauri-action` creates a draft release with installers, signatures and `latest.json`; a human (or a manual approval step) publishes it, which is what makes the update visible to users.

### 8.2 Signing

| Platform | What | Cost / setup | CI secrets |
|---|---|---|---|
| macOS | Developer ID Application certificate + notarization (`notarytool`) + stapling | Apple Developer Program, US$99/year; create cert, export .p12; App Store Connect API key for notarization | `APPLE_CERTIFICATE` (base64 p12), `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_API_KEY`, `APPLE_API_ISSUER`, `APPLE_API_KEY_PATH` (or Apple ID + app-specific password + team ID) |
| Windows | Authenticode via **Azure Trusted Signing / Artifact Signing** (Microsoft-managed cert, no hardware token, builds SmartScreen reputation) using `trusted-signing-cli` as `bundle.windows.signCommand`; alternative: OV/EV cert on a cloud HSM | Low monthly fee; identity validation needed (individual or company; availability by country is an open question, see 12) | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, endpoint, account, profile |
| Updater | Tauri's own minisign-style signature over each update bundle (separate from OS signing; both are needed) | free | `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` |

Until certificates exist: ship private alphas unsigned (macOS: right-click → Open, or `xattr -dr com.apple.quarantine`; Windows: SmartScreen "More info → Run anyway") and say so on the download page. Keep the updater signature from day one; losing that key means users must reinstall manually, so back it up offline.

### 8.3 Auto-update behaviour

Check at startup and every 6 hours; show a non-blocking "Update ready" pill; download in background; install on user click or on quit. Never update while a job (download, install, benchmark) is running. Engines and the app update independently: engine updates are user-triggered per engine, with the changelog shown first.

### 8.4 Optional distribution later

winget manifest (auto-PR from release), Homebrew cask, Microsoft Store (MSIX) and Mac App Store are possible but the App Store sandbox conflicts with installing other engines, so skip it.

---

## 9. Day-one checklist

For Monday, in order. Each item is one commit or PR.

1. Create the `anvil` repo (owner action on GitHub), attach it, add `AGENTS.md`/`CLAUDE.md` with: package manager pnpm, `pnpm tauri dev`, test commands, "never run engines or downloads in tests; use fixtures", style rules.
2. Scaffold Tauri 2 + React + TS + Vite + Tailwind; tokens for the white/metal and graphite themes; sidebar with six empty pages.
3. `ci.yml` (lint, test, clippy on Windows + macOS).
4. `release.yml` with `tauri-action`, updater key generated and stored as secrets, draft releases.
5. In this repo: merge PR #3 (schema probe, thinking-aware `compare`, corrected conclusions), then add `llmbench doctor --json` (if not present) and `llmbench run --progress-json`; tag `v0.3.0`.
6. Sidecar build script + CI job freezing `llmbench` v0.3.0; About page shows its version.
7. Copy `results/2026-11-25/*.json`, `results/2026-11-28/*.json` (the thinking on/off and schema fixtures) and a `diagnose` sample into `fixtures/`; Hardware page renders specs from the fixture.
8. First cut of the procedural 3D PC (case, board, CPU, RAM ×N, GPU, M.2 ×N) driven by the fixture.
9. Tag `v0.0.1` and `v0.0.2` to prove install + update on both OSes (needs someone with a Mac to click through, or a macOS CI smoke test that launches the app).

---

## 10. Building it with a local model

The reference PC serves Qwen3.6-35B-A3B UD-Q4_K_XL at about 200 to 300 tok/s on one request with thinking off (Strata 194 to 305, LM Studio 197 to 226, measured 2026-11-28), and LM Studio reaches 383 tok/s in total across four requests. (The 2026-11-25 figures of 215 to 284 tok/s had thinking on and produced no answer text within their cap.) That is fast enough for an agent loop. **Use LM Studio on port 1235 for the agent:** its grammar holds tool-call JSON to the schema and it gains from parallel requests; Strata passes on schema-breaking JSON or refuses it, which costs retries in a tool loop. What it lacks compared with a frontier model is reliability over long multi-file tasks, so the work has to be cut finer and checked by machines, not by the model's own judgment.

### 10.1 Setup

- **Agent harness** that speaks the OpenAI-compatible API and can edit files and run commands: OpenCode, Aider, Cline/Roo (VS Code) or Continue, pointed at `http://127.0.0.1:8080/v1` (Strata) or `http://127.0.0.1:1235/v1` (LM Studio). Pick one and record the choice in `AGENTS.md`.
- **Context:** load at 64K to 128K. **Thinking off by default** (`reasoning_effort: none`); on a JSON task with thinking on Qwen3.6 often spent its whole output budget thinking and never answered. Turn it on only for planning tasks where a measured comparison shows it helps.
- **Guard rails:** run the agent in the repo only, with commands limited to `pnpm`, `cargo`, `git` (no push), and the test runners. A human or Claude reviews each PR.
- **Don't run it while a GPU benchmark is running** on the same machine: both numbers get worse and the benchmark becomes invalid.

### 10.2 Task breakdown rules

- One task = one file or one small module + its test, under ~300 changed lines, with a command that proves it works (`cargo test engines::strata::tests`, `pnpm vitest run src/three`).
- Give the model the interface first (the `EngineAdapter` trait, the TS types from `tauri-specta`, the fixture JSON), not the whole repo.
- Prefer tasks with a fixture: "parse this `diagnose` JSON into this struct", "render this result JSON as this table".
- Frontier-model (Claude) tasks: architecture changes, the job system, the link-mode fallback chain, signing/CI debugging, anything that touches two OSes at once, and reviewing the local model's PRs.
- Local-model tasks: UI components from a spec, adapter methods that wrap one CLI command, parsers, advisor rules (each rule is a pure function with a test), unit tests, docs, translations, 3D part meshes from a written description.

### 10.3 Prompt templates

Task prompt:

```
You are working in the anvil repo (Tauri 2, Rust core in src-tauri/, React+TS UI in src/).
Read AGENTS.md first. Do only this task:

TASK: <one sentence>
FILES YOU MAY CHANGE: <list>
INTERFACE (do not change): <paste trait / type>
INPUT EXAMPLE: fixtures/<file>.json
DONE WHEN: `<exact test command>` passes and `<lint command>` is clean.

Steps: 1) write the test from the example, 2) run it and see it fail, 3) implement,
4) run test + lint, 5) show the diff and the command output. Do not touch other files.
If something outside the listed files seems wrong, stop and describe it instead of fixing it.
```

Fix-loop prompt (after a failing run):

```
The command `<cmd>` failed. Output (last 80 lines):
<output>
Fix only the cause shown. Do not change tests unless the test itself is wrong; if so, say why first.
```

Review prompt (for Claude or a second local pass):

```
Review this diff against the task and AGENTS.md. List: bugs, missing tests, files touched outside scope,
platform-specific code without a Windows/macOS branch. Reply "LGTM" only if the list is empty.
```

### 10.4 Limits to expect

| Limit | Effect | Mitigation |
|---|---|---|
| Knowledge cutoff and API drift (Tauri 2 plugins, tauri-action inputs, LM Studio `lms` flags, Strata CLI) | Confident use of old APIs | Paste the current doc page or `--help` output into the task; pin versions in `Cargo.toml` / `package.json`. |
| Long-horizon coherence | Drifts after many steps, rewrites unrelated code | Small tasks, file allow-list, fresh context per task. |
| Rust borrow-checker / async errors | Many fix-loop iterations | Keep Rust tasks small; hand back to Claude after 3 failed loops. |
| Visual judgment (3D look, layout polish) | Cannot see the result | Playwright screenshots reviewed by a human or a multimodal model; fixed numeric specs (sizes, colours) in the prompt. |
| Platform work (signing, notarization, Windows symlink rights, macOS permissions) | Cannot test the other OS, cannot hold secrets | Human/Claude only; CI is the test. |
| Context size vs speed | Prefill at 100K+ tokens takes tens of seconds per turn | Keep prompts under ~30K tokens; summarise instead of pasting whole files. |
| Security-sensitive code (installers, downloads, keychain) | Subtle mistakes | Always reviewed by Claude or a human before merge. |

---

## 11. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Benchmarks or advice that compare different thinking states, files or timing sources, as this repository's own 2026-11-25 reading did | high (it already happened) | Profiles and results record thinking and parallel explicitly; `compare` warns; advisor rules require matching file, context and thinking. |
| Strata changes installer, model format or CLI often; drops models between versions | high | Version pinning, side-by-side installs, adapter contract tests against recorded `--help` / API responses, a compatibility table in-app. |
| LM Studio's licence or terms restrict automated installs or bundling | medium | Never bundle; install from official source with the user's action; read terms before phase 2. |
| WebKit (macOS) vs WebView2 rendering differences, especially WebGL | medium | Test the 3D scene on both from phase 1; keep to WebGL 2 basics; Electron as fallback. |
| Windows symlinks need admin / Developer Mode | high | Prefer hard links (same volume, no admin) and engine import; symlinks only as an opt-in. |
| Signing identity availability (Azure Trusted Signing region rules, Apple account) | medium | Start the Apple and Azure enrolment in week one; unsigned private alpha meanwhile. |
| Hardware advice that is wrong or sounds like guessing | medium | Rules only fire on measured evidence; each shows its source and a "confirm" measurement; no prices in v1. |
| Scope creep into a chat app | medium | Out of scope list in 3.2; link out to engines' own UIs. |

---

## 12. Open research questions

Each should end in a short note in `docs/research/` of the app repo.

1. **Strata automation:** Is there a non-interactive pack install (`strata launch` flags), a machine-readable version / model list, and a documented models directory? Can two Strata versions coexist (needed for DeepSeek on 0.2.13)? What does the desktop installer do differently from `install.ps1`?
2. **LM Studio:** Exact `lms import` link vs copy behaviour; whether llmster and the desktop app share `~/.lmstudio`; terms for programmatic install; how to read loaded-model settings (context, GPU offload) over REST.
3. **Hard links across engines:** Does any engine break on a hard-linked or symlinked GGUF (memory-mapping, file locks on Windows, LM Studio's index)? Test on NTFS, APFS and exFAT (external drives, where hard links don't exist).
4. **GGUF fit estimate accuracy:** Compare the estimator with measured VRAM on the reference PC for Qwen3.6 at 32K/128K and Inkling; target within 10%.
5. **Sidecar choice:** PyInstaller vs Nuitka vs python-build-standalone for size, startup time, antivirus false positives on Windows, and macOS notarization. Longer term, port the measurement core to Rust?
6. **Windows signing:** Is Azure Trusted Signing / Artifact Signing available to an individual in the owner's country? If not, which OV certificate on a cloud HSM, and its yearly cost?
7. **BuildCores:** Licence terms and price for `@buildcores/render-client`; whether a share code can be rendered without our own backend; whether they would map detected parts (by name) to their part IDs.
8. **Part-level data:** Sources for GPU dimensions/slot widths, motherboard M.2 slot topology (which slots are CPU vs chipset lanes), and max RAM per board, so the advisor can say "slot M2A_CPU" instead of "a faster slot".
9. **Apple Silicon:** Which engines matter on Mac (Strata macOS build, LM Studio MLX, llama.cpp Metal, Ollama); how unified memory changes the advisor (no VRAM/RAM split; suggest the next memory tier at purchase time only).
10. **Name and identity:** Final app name (check trademarks and domain), icon, and whether the app lives under the owner's GitHub account or an organisation.
11. **Community baselines:** Whether to host an opt-in results database, and how to keep it honest (validity verdicts, sanitized, same suites only).
12. **Strata behaviour to recheck per release:** whether thinking off fully stops hidden tokens (7 of 12 runs still counted unstreamed tokens, probably MTP bookkeeping), whether a later build gains from parallel slots, and whether installing `jsonschema` (or a grammar option) makes it enforce schemas.
13. **Task benchmarks:** a small, reviewed accuracy set per user task so "faster" is never reported without "as accurate"; the menu-reading job had no human-checked records and judged agreement only.

---

## 13. References

- Stability Matrix (C#/Avalonia, multi-package manager with shared models): https://github.com/LykosAI/StabilityMatrix
- Tauri 2 distribution and signing: https://v2.tauri.app/distribute/sign/macos/ · https://v2.tauri.app/distribute/sign/windows/ · updater plugin: https://v2.tauri.app/plugin/updater/ · tauri-action: https://github.com/tauri-apps/tauri-action
- LM Studio headless (llmster, `lms daemon`): https://lmstudio.ai/docs/developer/core/headless · CLI: https://lmstudio.ai/docs/cli
- Strata releases and installers: https://github.com/Niko1221/Strata/releases
- BuildCores render client docs: https://buildcores.github.io/buildcores-render-client/technical-documentation/
- This repo: [same-file engine runs, 2026-11-28](../results/2026-11-28/README.md), [llmbench guide](llmbench.md), [diagnostics schema](diagnostics.md), [model setup](model-setup.md), [benchmark design](benchmark-design.md), [storage A/B](../results/2026-11-26-storage/README.md)
