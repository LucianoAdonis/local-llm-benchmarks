# llmbench: a repeatable speed test for local LLMs

`llmbench` measures how fast your local runtime reads and writes. It sends a fixed set of test prompts (scenarios), records the machine it ran on, checks that the result is valid, and lets you compare two runs. It is meant to do for a local model what a graphics benchmark does for a PC build.

- **One tool for Windows, macOS and Linux.** It is plain Python (3.9 or newer) with no packages to install.
- **Any runtime.** It talks to the local web address that Strata, LM Studio (and Bionic), llama.cpp and Ollama all serve for other apps (the "OpenAI-compatible" API).
- **It does not download models or change settings.** Load your model the way you normally do first. If none is loaded, LM Studio and Ollama load one on the tool's first request, with their default context window, and the tool tells you so.

**Status:** so far `llmbench` has been run on macOS only, against its built-in test server, not yet against a loaded model. Windows and Linux use the same code and have automated tests that have not run there yet. If a number looks wrong, please open an issue.

If the words below are new, read [start-here.md](start-here.md) first. The reasoning behind each design choice is in [benchmark-design.md](benchmark-design.md).

For packaged installation and model downloads through the native runtime tools, see [model-setup.md](model-setup.md). `llmbench` never downloads large model files or changes a runtime configuration on its own.

## Quick start

**Commands on this page are written `python3 -m llmbench`. On Windows, type `py` instead of `python3`.**

1. Check for Python 3.9 or newer: `python3 --version` on macOS and Linux, `py --version` on Windows (if `py` is not found, try `python --version`). If a Mac offers to install developer tools, accept: they include Python. Otherwise install it from python.org.
2. Get this repository: on its GitHub page choose Code, then Download ZIP, and unpack it (or clone it). Open a terminal in the unpacked folder, the one that contains `llmbench`. Windows: right-click the folder and choose "Open in Terminal". macOS: type `cd ` in Terminal, drag the folder into the window, press Return.
3. Start your runtime and load a model with a context window of 16,384 tokens (see [Starting each runtime](#starting-each-runtime)).
4. Run the three commands below.

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

Windows (PowerShell or Command Prompt):

```powershell
py -m llmbench selftest
```

```powershell
py -m llmbench doctor
```

```powershell
py -m llmbench run --suite quick
```

- `selftest` takes about a minute and needs no model. It checks that the stopwatch code measures correctly on your machine, against a built-in fake server whose speeds are known.
- `doctor` describes your machine, warns about battery power or memory pressure, finds running runtimes and says whether one has a model to test.
- `run` measures. Results print to the screen and are saved under `local-results/`, which Git ignores. The file name is printed after `Saved:`.

The `quick` suite should take under a minute on a fast PC when the model fits in VRAM, up to about three minutes with a very large model, and about 8 minutes on a base M4 Mac (estimates from published speeds, not timings).

## What a run looks like

This is the `standard` suite on the built-in fake server, set to read 8,000 tok/s after a fixed 0.15 s and to write 120 tok/s. It shows the layout, not a real model's result. On a machine with warnings (battery power, swap in use) those are printed above the table and listed again as cautions under the result. A `quick` run shows only the `chat`, `ctx-4k` and `ctx-16k` rows.

```text
llmbench 0.1.0 | suite standard | protocol 2.0
System : macOS 27.0.1 | Apple M4 (10-core GPU) | 24 GB RAM (unified)
Runtime: OpenAI-compatible server | model mock-model | context 70,000 (argument)
Warm-up: first token after 0.17 s
Workload: diverse corpus, 4.00 characters per token for this model (probe)
Estimated time: about 2 minutes (Ctrl+C keeps the runs finished so far)
chat           run 1/5  prompt 97 tok  first token 0.18 s  write 120.1 tok/s
...
ctx-16k        first read at this size (not counted)  prompt 14,496 tok  first token 1.97 s  read 7,385 tok/s  write 120.0 tok/s
ctx-16k        run 1/3  prompt 14,496 tok  first token 1.97 s  read 7,384 tok/s  write 120.0 tok/s
...
followup-16k   run 1/3  prompt 14,671 tok  cached 14,593  first token 0.20 s  write 120.3 tok/s
...
sanity         needle      passed  prompt 2,734 tok  first token 0.50 s  read 5,513 tok/s  write 120.3 tok/s

Scenario      Prompt tok  First token s  Read tok/s  Write tok/s  Runs   Spread  Notes
------------  ----------  -------------  ----------  -----------  ----  -------  ----------------------------------
chat                  97           0.17           -          120   5/5  +/-0.0%
gen-long              98           0.17           -          120   3/3  +/-0.2%
ctx-4k             3,451           0.59       5,929          120   3/3  +/-0.1%
ctx-16k           14,496           1.97       7,385          120   3/3  +/-0.0%
followup-16k      14,671           0.17           -          120   3/3  +/-0.1%  first token x11 sooner, 99% cached
ctx-64k           58,746           7.50       7,839          120   3/3  +/-0.0%
sanity                 -              -           -            -   3/3        -  3 of 3 checks passed
control              100           0.18           -          120   2/2  +/-0.4%

What this means
  Writing speed        120 tok/s, about 90 words per second (client-timed)
  Reading speed        5,929 tok/s at 4K | 7,385 tok/s at 16K | 7,839 tok/s at 64K
  Reading, as text     23,612 chars/s at 4K | 29,511 chars/s at 16K | 31,349 chars/s at 64K (use this line, not tok/s, to compare different models)
  Reading, as a rule   about 0.16 s per request, then 8,000 tok/s (from 3 prompt sizes; the smaller ones predict the largest within 1%)
  Reading, in steps    4K to 16K: 7,997 tok/s | 16K to 64K: 8,001 tok/s (extra tokens over extra seconds)
  Short chat           first token after 0.17 s
  Quick question       2.7 s to finish a 300-token answer
  Code review          6.1 s to read a 16K context and write 500 tokens
  Follow-up question   4.3 s on the same context for 500 tokens
  Big read             15.8 s to read a 64K context and write 1,000 tokens
  Follow-up cache      99% of the follow-up prompt came from the cache, first token x11 sooner
  Start versus end     writing speed at the end was 100% of the start

Result quality: clean
```

How to read the table:

| Column | Meaning |
|---|---|
| Prompt tok | Tokens the server says it received. This is the real prompt size, not the configured window. |
| First token s | Wait from sending the request to the first token of any kind, thinking included. |
| Read tok/s | Prompt tokens actually processed per second. Cached tokens are not counted. A dash means fewer than 512 new tokens were read, too few to time. |
| Write tok/s | Tokens generated per second after the first one. |
| Runs | Usable runs out of counted runs. Each new prompt size also gets one extra read first, shown on its own line and not counted. |
| Spread | How far apart the runs were. +/-2% means the slowest and fastest run were each about 2% from the middle one. |
| Notes | Flags and, for follow-ups, how much of the prompt was served from cache. |

How to read the summary:

- **The lines to quote to a friend** are "Quick question", "Code review", "Follow-up question" and "Big read": seconds to finish a typical job, built from the measured wait and the measured writing speed. A `quick` run prints only the first two.
- **Reading speed looks higher for bigger prompts** because every request pays the same fixed wait first (0.15 s here). Two lines take it out. "In steps" divides the extra tokens by the extra seconds between two sizes, so the fixed wait cancels. "As a rule" fits the fixed wait and the rate together; it appears only when three or more prompt sizes were run (so not in `quick`), every size lies within 10% of the line, and the smaller sizes predict the largest one within 10%. Real engines often fail that test, and then no rule is claimed.
- **"Reading, as text"** is the same speed in characters. A token is a different amount of text for each model, so this is the line to use when you compare two different models.
- **`sanity`** checks that the model really received the whole prompt and can answer it. **`control`** repeats `chat` at the end, and "Start versus end" should stay near 100%.

`client-timed` means the numbers came from this tool's stopwatch. `engine-timed` means the runtime reported its own timings, which is more exact. Strata and llama.cpp report them, and so do newer Ollama builds. LM Studio does not, so its results are client-timed.

## Starting each runtime

`llmbench` needs the address, the model, and the context window the model was loaded with. It finds the address by itself when only one runtime is running, and it reads the model and context from the runtime when the runtime tells it. When it cannot, pass `--url`, `--model` and `--context`.

**Set the context window on purpose before a run.** `quick` needs 16,384 tokens and `standard` needs 65,536. Use 16,384 for a first `quick` run, and stay there on a Mac or a card with 12 GB or less: a larger window reserves memory and can push the model out of fast memory. A scenario that does not fit the window is skipped with a reason (for example `ctx-16k` on LM Studio's default 8,000), never silently shortened.

The commands below load a 16,384-token window for `quick`. For `standard`, load 65,536 and replace `quick` with `standard`.

### LM Studio

`lms` is the command-line tool that comes with LM Studio. `lms ls` lists the model names. If a model is already loaded, unload it first, or the new context is ignored:

```bash
lms unload --all
```

```bash
lms server start
```

```bash
lms load <model-name> --context-length 16384 --gpu max
```

```bash
python3 -m llmbench run --url http://127.0.0.1:1234 --suite quick
```

`--gpu max` puts the whole model on the GPU. `lms ps` shows what is loaded and with which context. In the app, the same steps are: load the model with its context length set by hand, then switch the server on in the Developer tab.

### LM Studio Bionic

Bionic is an agent app that runs local models on LM Studio's engine. Benchmark that engine exactly as above. If LM Studio is open, Bionic uses LM Studio's loaded model, so note in `--label` whether it was. Bionic's automatic context sizing can choose a window far larger than you need; load the model yourself with `lms load` as above for a fair run.

### Ollama

Ollama picks its context window from your VRAM (4K below 24 GiB, 32K up to 48 GiB), and this tool cannot change it per request. Set it when the server starts. If the Ollama app is already running (menu bar or system tray), quit it first, or `ollama serve` fails because the port is in use. `ollama list` shows the names to pass as `--model`.

macOS and Linux:

```bash
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
```

Windows (PowerShell):

```powershell
$env:OLLAMA_CONTEXT_LENGTH = "16384"; ollama serve
```

Then, in another terminal:

```bash
python3 -m llmbench run --url http://127.0.0.1:11434 --model <model:tag> --suite quick
```

Run `ollama ps` during the run. The PROCESSOR column should say `100% GPU`. Anything else means part of the model is on the CPU.

### llama.cpp

Pin the settings that recent builds otherwise choose for you: context, one slot, and the port.

```bash
llama-server -m <model.gguf> -c 16384 -np 1 --port 9931
```

```bash
python3 -m llmbench run --url http://127.0.0.1:9931 --suite quick
```

Builds from before October 2026 listen on 8080. The engine's timings come back with every reply and are used automatically.

### Strata

Start Strata the way you normally do (`strata launch`, or a saved profile). It serves `http://127.0.0.1:8080` and reports engine timings in each reply.

```bash
python3 -m llmbench run --url http://127.0.0.1:8080 --context 131072 --suite standard --label "Strata 0.2.20 engine 0.1.66, MTP 2"
```

Pass `--context` with the value your profile was started with, and put the Strata and engine versions in `--label`. Strata releases almost daily and both change results. For the retired DeepSeek engine (Strata 0.2.13), which did not put timings in its replies, add `--engine-log <path to the profile's engine log>`.

Strata's own `strata bench run` is worth running too. It is Strata's draft standard for one model family; `llmbench` is the cross-runtime view. The two answer different questions.

## Suites

| Suite | What it runs | Context window it needs | Time |
|---|---|---|---|
| `quick` | short chat, 4K read, 16K read | 16,384 | under a minute to about 3 on a fast PC; about 8 on a base M4 Mac |
| `standard` | adds a long answer, a cached follow-up, a 64K read, the sanity checks and the end-of-run control | 65,536 | 2 to 10 minutes on a fast PC; 35 minutes or more on a base M4 Mac |
| `deep` | adds 32K, 128K and 256K reads, the repetitive-text probe and four parallel requests | 262,144 for all of it | much longer; the big reads dominate |

The Mac times are arithmetic from one measured base M4 (230 tok/s reading, 20 writing): a 64K prompt takes four to six minutes per run there. Start with `quick`. The tool prints its own time estimate once it has seen your speeds.

| Scenario | The question it answers |
|---|---|
| `chat` | How long until a short question starts answering, and how fast does it write? |
| `gen-long` | Does writing speed hold over a 1,024-token answer? |
| `ctx-4k` to `ctx-256k` | How long does a fresh prompt of that size take to read, and how fast is writing after it? |
| `followup-16k` | After that first read, how quick is the next question on the same material? |
| `repeat-16k` | Does this runtime speed up on repetitive text? If so, benchmarks built on repeated prompts overstate it. |
| `parallel-4` | What is the total output with four requests at once? |
| `sanity` | Three exact-answer checks. Is the model actually receiving the whole prompt? |
| `control` | The first scenario again at the end. Did the machine or runtime drift during the run? |
| `soak` | Does speed hold for ten minutes, or does heat pull it down? Add with `--soak-minutes 10`. |

`python3 -m llmbench scenarios` prints the exact sizes.

Useful options:

| Option | Use |
|---|---|
| `--context N` | The window your model was loaded with, when the runtime does not report it. |
| `--output PATH` | Where to save the result, when you want to choose the name. |
| `--depths 4k,32k,128k` | Run these read sizes instead of the suite's. |
| `--scenarios chat,ctx-16k` | Run only these. |
| `--runs N` | More repeats for a tighter result. |
| `--thinking off` | Ask the runtime to switch model thinking off. The result shows whether it did. |
| `--soak-minutes 10` | Add the stability soak. |
| `--corpus file:PATH` | Use your own code or text as the reading material. Only its size and a hash are stored. |
| `--label "text"` | A note stored with the result: versions, settings, what you changed. |
| `--cold` | Say that you restarted the runtime just before this run, so the warm-up is recorded as a cold start. |
| `--no-size-warmup` | Skip the uncounted first read at each size. Faster, but first-run effects then land in the result. |
| `--fixed-text` | Send exactly the same prompt text as every other run with the same seed. Restart the runtime first, or its prompt cache may serve the text from the previous run. |

## Result quality and flags

Every result ends with one of three verdicts.

| Verdict | Meaning |
|---|---|
| `clean` | Nothing to report. |
| `usable with cautions` | The numbers stand, but something listed may explain a difference. |
| `invalid` | A scenario that was attempted produced no usable run, nothing was measured at all, or the run was interrupted. Do not compare this result. |
| `unfinished` | Only in the progress file (`.partial.json`) of a run that has not ended. |

A depth the server refuses (a "context size exceeded" error) or cannot answer in time, before any run at that size worked, is listed as skipped with the reason, and deeper ones are not attempted. That is a caution, not a failure: the smaller depths still stand.

| Flag in Notes | What happened | What to do |
|---|---|---|
| CACHE HIT | The runtime reused cached prompt tokens in a run meant to be fresh. That run is excluded. | Restart the runtime and run again. |
| PROMPT TRUNCATED | The server received far fewer tokens than were sent. That run is excluded. | The loaded context is too small. Load the model with a larger one. |
| no cache reuse | The follow-up re-read everything. | A finding, not an error. Some runtime and model combinations do not reuse the prefix. |
| stopped early | The model ended before the output cap. | Usually harmless. Speeds are per token. |
| thinking only | Everything within the cap was model thinking. | Harmless for speed. Use `--thinking off` if you want answer text. |
| hidden tokens | The server counted tokens that never appeared in the stream, usually thinking it does not show. | The wait for the first token includes writing them. Trust the engine-timed figure if there is one. |
| buffered stream | Text arrived several tokens at a time, and the runtime gave no engine figure to check against. | Client-timed writing speed is an estimate. |
| client/engine differ | The stopwatch and the engine disagree by more than 15%. | The engine figure is the one reported. |
| estimated counts | The server sent no usage numbers. | Token counts are estimated from the stream. Update the runtime. |
| no token counts | Neither usage numbers nor a usable stream. That run is excluded. | Check the runtime's log. |
| counts too low | The server counted fewer tokens than it streamed (often thinking it did not count). | The streamed count is used. |
| stream cut | The reply ended without a finish marker. That run is excluded. | The connection dropped or the server stopped. Check its log. |
| cache size unknown | The runtime does not say how much of the follow-up prompt came from its cache. | No reading speed is given for that turn; first-token time still is. |
| size off target | The prompt missed its target size by more than 5%. | Harmless for speed. Expected with `file:` corpora. |
| over context | Prompt plus output were larger than the stated context window. | Pass the real window with `--context`. |
| no stream timing | The whole reply arrived at once. | No client writing speed for that run. |
| unreadable events | Some stream events could not be parsed. | A token may be missing from the timings. Update the runtime. |
| slow connect | Opening each connection took more than 50 ms (not counted in the timings). | Use `127.0.0.1` instead of `localhost`. |
| first turn failed | The first turn of a follow-up pair did not work, so the pair was not measured. | See that run's error. |

`compare` exits with status 3 when the two files cannot be compared, and `run` exits with status 1 when the verdict is `invalid`, so scripts can stop early.

Pre-run warnings (battery power, Low Power Mode, memory pressure, a hot or nearly full GPU) are stored with the result and listed as cautions.

## Comparing two runs

Give each run a name with `--output`, change one thing between them (a driver, a runtime version, one setting), then compare:

```bash
python3 -m llmbench run --suite standard --output local-results/before.json
```

```bash
python3 -m llmbench run --suite standard --output local-results/after.json
```

```bash
python3 -m llmbench compare local-results/before.json local-results/after.json
```

```text
Scenario             Metric      A      B  Change  Counts above    Runs  Verdict
------------  -------------  -----  -----  ------  ------------  ------  ------------
ctx-16k       first token s   1.97   1.97   +0.1%          2.0%  3 vs 3  within noise
ctx-16k          read tok/s  7,385  7,377   -0.1%          2.0%  3 vs 3  within noise
ctx-16k         write tok/s    120    150  +25.0%          2.0%  3 vs 3  better
...

In short (B against A): first token s: no change that counts in 6 scenarios; write tok/s: better in 6 of 6 scenarios; read tok/s: no change that counts in 3 scenarios.
```

A change counts only when it is larger than the "Counts above" column. That is the gap run-to-run variation alone would produce less than about one time in twenty, and it is never under 2%. With two or three runs the bar is high when the runs vary: three runs that differ by 5% among themselves cannot show a 5% improvement. Add `--runs 6` or more to both results when the difference you care about is small.

`compare` also lists any other differences it can see between the two files (context window, corpus, model name), and refuses files from different protocol versions.

## Recipes

**Before and after an update.** Run `--suite standard --output local-results/before.json`, update, restart the runtime, load the model with the same context, run again with `after.json`, then `compare`.

**Is drafting worth it on my text?** Run once with drafting on and once with it off (llama.cpp `--spec-type`, LM Studio's speculative decoding setting, Strata `--drafting off`), with `--corpus file:<your project>` so the text is yours, then `compare`.

**Does my runtime flatter repeated text?**

```bash
python3 -m llmbench run --scenarios ctx-16k,repeat-16k
```

The report prints a "Repetitive text" line. A ratio above about 1.15 means repeated prompts overstate this runtime's real speed.

**Heat and stability.**

```bash
python3 -m llmbench run --suite quick --soak-minutes 10
```

The soak reports the worst loop as a share of the best. Under 97% suggests throttling or background load.

**Cold start.** Quit and restart the runtime, then run with `--cold`. The warm-up line is the time to first token including model load.

**Two machines.** Pick one model file that both can hold fully in memory, load it with the same context on both, and run the same suite. Large PC-only models belong in their own comparison.

## Sharing a result

Result files are written without your user name, host name, home folder, the server's address or any key. A redaction pass runs before saving as a second check, and you can test any file with it:

```bash
python3 -m llmbench sanitize --check local-results/<file>.json
```

```bash
python3 -m llmbench report --markdown local-results/<file>.json
```

The second command prints a table for a README or an issue. To publish in this repository, copy the JSON to `results/YYYY-MM-DD/` and follow [CONTRIBUTING.md](../CONTRIBUTING.md). Read the file once before sharing: no redactor knows every private detail, and `--label` is stored exactly as you typed it.

What is recorded: operating system, CPU, GPU, memory size, GPU driver, power source, the runtime's name and version, the model name and what the runtime reports about it, every run's timings and flags, and the workload's seed and hash.

## What it does on your computer

- It talks only to the address you give it. Without `--url` it looks for a runtime on six usual ports of your own machine.
- It reads facts about the machine with the system's own tools (`nvidia-smi`, PowerShell, `sysctl`, `pmset`, `system_profiler`).
- It writes result files under `local-results/`, or where `--output` says. A standard result is about 100 KB.
- It changes no setting, installs nothing and sends nothing to the internet.
- Close or leave idle any other program that uses the model or the GPU during a run. The run uses the model you loaded and does not unload it.

## How it measures, in short

- **Different text for every run and every invocation**, generated from a seed plus a random salt, so no cache can reuse an earlier run, not even a prompt cache that outlives the run. The text is different but built the same way each time, so the number of characters per token stays steady (within about 5% at 4K). `--fixed-text` drops the salt: the same seed then gives the same text on every machine and operating system, which suits runtimes restarted before each run.
- **Varied, code-like text** by default. It compresses about as well as real source code (ratio near 4.5), where the repeated class used by the v1 scripts compressed 23 to 74 to 1 depending on length.
- **Sized in tokens, not characters.** A short probe learns how this model counts, so every model receives the same number of tokens.
- **First token means first token of any kind.** Thinking tokens are tokens.
- **Engine timings first**, the stopwatch second, and the report says which was used.
- **Medians of several runs**, with the spread shown. Finished scenarios are saved as they complete (`<output>.partial.json`), so an interrupted deep run keeps what it measured.

## Troubleshooting

| Message | Likely cause |
|---|---|
| `No module named llmbench` | The terminal is not in this repository's folder. Open it in the folder that contains `llmbench`. |
| `python3` or `py` is not found | Python is not installed, or it has another name on your system. Try `python`. |
| `No local runtime answered on the usual ports` | The runtime's server is not started, or it uses another port. Pass `--url`. |
| `the server lists no chat model` | The runtime is running but has nothing to benchmark. Download or load a model in it first. |
| `more than one model is available; pass --model with one of: ...` | Copy one of the listed names. |
| `skipped: needs a context window of about N tokens` | Load the model with a larger context, or accept the skip. |
| `skipped: context window unknown` | Pass `--context N`. |
| `warm-up request failed: HTTP 400` | Often an unsupported option. Remove `--thinking off` or `--extra-body`. |
| `Note: the model was not loaded when the run started` | The runtime loaded it with default settings. Load it yourself with the context you want, then run again. |
| `PROMPT TRUNCATED` on every deep scenario | The runtime loaded a smaller context than you think. Check `lms ps` or `ollama ps`. |
| Self-test fails | Close heavy background work and retry. A loaded machine cannot keep time. |

## Limits

- It measures speed. It does not rank answer quality. The sanity checks only confirm that the model is reading the prompt and answering.
- One request at a time is the focus. `parallel-4` is a single optional probe, not a load test.
- Without engine timings the reading speed still includes a few milliseconds of request overhead, which matters for prompts under about 1,000 tokens.
- It reads VRAM use and GPU temperature through `nvidia-smi` only. On AMD, Intel and Apple graphics it still measures speed, but it cannot warn about a full card.
- It was developed on macOS and checked there against its own fake server. When this page was written it had not yet been run against a loaded model, and had not been run on Windows or Linux at all. Those systems use the same code, and a CI workflow that runs the tests on all three is included but has not run yet.
- The v1 scripts in `scripts/` produced the 2026-11-23 baseline and are kept for the record. New measurements should use `llmbench`. The two are not comparable; see [benchmark-design.md](benchmark-design.md).
