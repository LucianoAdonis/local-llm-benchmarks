# Benchmark design: what the first version got wrong, and what protocol 2 does

This page is the logic review. Part 1 lists what two independent audits found in the v1 scripts and in the numbers published on 2026-11-23. Part 2 is the design that replaces them, implemented in [`llmbench`](llmbench.md). Part 3 compares existing tools and explains why a small utility was still worth writing.

For plain-language background see [start-here.md](start-here.md).

## In one paragraph

The v1 scripts recorded real measurements, and every published number reproduces from the stored files. But several rows cannot be read the way their labels invite, one explanation in the old docs went further than the data, and the workload, one Python class repeated hundreds of times, is probably close to a best case for engines whose speed depends on content. Protocol 2 keeps the good habits (reading and writing measured separately, engine timings preferred, per-run JSON) and fixes the measurement core: every token is timed by what it is, caches are defeated and checked, the text is varied, runs are repeated after a warm-up, the machine is recorded, and every result carries a verdict on its own validity.

## Part 1. What the audits found

Two reviewers read every script line and recomputed every published number from the 20 result files (47 runs). A third pass then tried to refute each finding. Of the 20 findings about the scripts it confirmed 17 as stated, narrowed 3, and added 6 of its own; the tables below use the corrected wording. This section separates **what the files show** from **what is only the likely explanation**, because the first version of these docs published a cause the data did not establish.

### What holds up

- All 511 derived fields in the JSON and every value in the published tables reproduce. There are no transcription errors. (One figure is rounded twice: 1,510.0 is 1,509.95.)
- The engine-timed DeepSeek and Qwen rows are internally consistent. For Qwen the client's wall clock agrees with the engine's own prefill plus decode time to within 19 to 56 ms.
- Within one model and one method, the trends are real: Qwen and Inkling both write more slowly as the prompt grows, and the Inkling SQ-10 versus UD-Q4_K_M difference at equal token counts is far larger than the spread.
- Keeping engine timings and client timings in separate, labelled columns was the right call.
- The published DeepSeek rates are engine figures, so the token-accounting problem below touches only one published DeepSeek number: the 102.6 s to first text, by about 3%.

### What the files show, row by row

| Published as | What the files show | What remains unknown |
|---|---|---|
| "The first 82.3 tok/s DeepSeek estimate was inflated by stream buffering" | The run behind 82.3 was not kept, but the engine-timed files reproduce it. In all 11 DeepSeek runs the engine made two passes (50 tokens generated, then 17 re-read and 33 generated) while the API billed 100. No text reached the client before the second pass, and the client's timed window matches the engine's second pass to within 1 ms. 100 ÷ 1.2148 s = 82.3: the script divided all billed tokens by the time in which 33 were generated, 3.03 times the engine's rate for that window. | Whether the first 50 tokens were hidden thinking or text held back until the second pass. So "buffering" is neither confirmed nor ruled out. |
| DeepSeek at 15.1K tokens: read 1,510 tok/s | Every run reused 3,982 of 15,119 tokens from the 4.5K runs, which used the same run markers 1 to 3. The rate is computed over the tokens actually read. | How it compares with an uncached read: estimates run from 15% lower to 17% higher. Time to first content was about 1.2 to 2.5 s shorter than uncached. |
| DeepSeek at 27.6K: write 11.6 tok/s, "near-full 32K prompt" | Decode, and a step whose cost does not depend on prompt size (768 to 885 ms against 286 to 324 ms in all nine other runs), were 2.1 to 2.9 times slower. The 95.5%-full 256K run was normal. The engine's own log lines, stored with each run, indicate it had been restarted shortly before: one conversation in memory, where the earlier files show four. | The cause. Two runs in one session cannot tell machine or engine state from a real effect of that profile at that depth. |
| DeepSeek writing falls with depth: 26.9, 23.1, 20.9 tok/s | The engine log lines stored with each run indicate three engine starts inside the DeepSeek series: the count of conversations it holds in memory drops back to none or one. The two requests that were first after a start wrote 20.9 (at 50K and at 250K). The second request at 50K wrote 25.3. The six runs at 4.5K and 15.1K, on an engine that had already served at least four conversations, wrote 26.2 to 27.9. | Whether depth matters at all. Depth, profile and how long the engine had been running are confounded. |
| DeepSeek reading rises with depth: 838 to 2,506 tok/s | First-pass time fits 3,100 ms + 0.384 ms per token over nine runs (R² 0.9993): a per-request cost of roughly 2 to 4 seconds plus a rate near 2,600 tok/s. | Whether that cost is a constant or a slow start inside each request, and whether the per-token rate is steady. Only four depths back the fit, and the 250K point dominates it; between neighbouring depths the rate runs from about 3,400 down to 2,560 tok/s. |
| Qwen: 100-token output | No answer text arrived in any of the 9 runs. Time to first content is empty in every file. | What the 100 tokens were. Thinking is the likely answer; the script did not record other fields. |
| "128K" comparison of four models | Prompts of 50,119, 54,901 and 64,513 tokens, timed two different ways, with a different number of characters per token for each model (4.15, 3.79, 3.12). | Any ranking. At equal token counts Qwen's lead disappears; for the same text Qwen was fastest. |
| Inkling writing speeds | Stopwatch figures from the same formula. Characters per billed token are 3.0 to 4.2, and time to first content scales with prompt size, which leaves room for at most 10 to 15 unseen tokens. | The exact error. It is probably small. |
| Single-run rows | The first run reads the prompt most slowly in all 16 files that have more than one (median 5.8%, up to 23%), including inside an engine that was already warm. Every single-run row is such a first request. | Whether the penalty comes from the new prompt size, the idle gap, or both. |

None of this means the hardware is slower than reported. It means the rows cannot be compared with each other, or with other people's numbers, the way the tables invite.

### Findings in the measurement logic

| # | Finding | Size of the error | Protocol 2 |
|---|---|---|---|
| 1 | **Writing speed divided every billed token by the time the answer text took.** Tokens produced before the first answer text were counted but their time was not. | 3.1 to 3.3 times on DeepSeek's two-pass output. 2 times for any model that thinks for half its output. | The stopwatch starts at the first token of any kind. Thinking and answer are counted separately. |
| 2 | **"Time to first content" waited for answer text only.** | Missing for Qwen. 2.2 to 5.8 s longer than the first engine token for DeepSeek, which made the reading-speed estimate 27 to 30% low at 4.5K. | Two latencies: first token of any kind, and first answer text. |
| 3 | **Caches were not controlled.** The run marker was the run number, so every invocation sent byte-identical prompts, and a short prompt was a 99.6% prefix of a longer one with the same marker. The DeepSeek engine also keeps conversations on disk across restarts. Reported cached-token counts were ignored. | Shown for one published row (26% of the 15.1K DeepSeek prompts). The larger problem is repeatability: re-running the published commands on the same PC can reuse earlier prompts. | A random marker leads the first message. Every run gets different text. Cached tokens are read from the runtime and a fresh run with a cache hit is excluded. |
| 4 | **The prompt had almost no information in it.** | It compresses between 23 and 74 to 1 depending on length, where real code compresses about 4.5 to 1. Community tests of the same model measured repeated content 1.2 to 4 times faster than new content ([baselines](community-baselines.md#deepseek-v41-flash-200-bpw-far-larger-than-vram)). The effect on these numbers cannot be measured from the files. | Varied, code-like text by default. The repetitive prompt is kept as an explicit probe (`repeat-16k`) that measures the effect. |
| 5 | **Tokens divided by time was published as a speed although part of the time does not depend on tokens.** | 838 tok/s at 4.5K against a marginal rate near 2,600. | Time to first token is the primary reading result. Two corrections are printed beside it: the rate between neighbouring sizes (extra tokens over extra seconds), and a fixed-plus-marginal rule only when every size lies within 10% of the line and the smaller sizes predict the largest within 10%. The v1 DeepSeek medians would not pass: the 4.5K read sits about 12% above the line. |
| 6 | **No warm-up, one to three runs, and a different statistic depending on the run count.** A median of three drops the slow first run, a "median" of two keeps half of it, and a single run is that run. | Median 5.8%, up to 23% at short prompts. | One uncounted first read at each new size, then at least two counted runs, the same median everywhere, spread printed. |
| 7 | **Engine log rows were summed.** A 17-token step of about 300 ms was folded into the reading rate. The writing rate, summed the same way, leaves that pause out. | Reading 5.2% low at 4.5K, 0.3% at 250K. Counting the pause, the answer arrived 7.5 to 10.7% more slowly than the published writing rate. | Reading speed uses the first pass only. The pause between passes is stored with the run. |
| 8 | **A 100-token output cap.** Writing was timed over 0.3 to 1.5 seconds. | Spread from 0.1% to 13% inside one file, depending on the configuration. | 256 tokens at depth, 1,024 in the long-answer scenario. |
| 9 | **Depth was set by counting sections, not tokens.** | Rows presented as one depth were 28% apart. | A short probe learns how each model counts, and every model receives the same number of tokens within a few percent. Prompt characters are stored too, because tokens are not a common unit between different models. |
| 10 | **The stream was timed blind.** N tokens over N−1 gaps, no check for buffered output. | +1% per-token, +9% and +19% with 8- and 16-token chunks, and a fully buffered reply was accepted. | Each event is timestamped. Tokens that arrived in the first event are excluded. Buffered streams are flagged. |
| 11 | **Nothing about the machine or runtime was captured**, so the 27.6K outlier cannot be explained after the fact. | | System, power state, GPU telemetry and runtime details are stored with every result. |
| 12 | **Runs were not validated.** A stream cut halfway or a prompt silently truncated by the server was saved as a normal run. | A "64K" test on a server that truncates to 4K looks ten times faster. | Truncation, early stops, cut streams and context overflow are detected and flagged. |
| 13 | **Engine log rows were not tied to the request.** Any other client's row in the time window was summed in; a late row was missed. | 11% low in a simulated stray request. Not seen in the published files. | Engine timings are read from the reply where the runtime sends them. For log-only engines, rows must match the request and chain. |
| 14 | **Four copies of the request loop had drifted**: two prompt texts and three file layouts under one protocol name. | Inkling was measured with a different prompt text from the other two models. | One client, one workload, one result layout, one protocol version. |
| 15 | **The redactor covered one path style and two key formats**, and a personal Windows path was the default of a script option. | 36 of 43 test strings passed through, including macOS and Linux home folders and LAN addresses. The published files themselves were clean. | Results are built from known fields. The redactor was rewritten and tested. |
| 16 | **Results were written only at the end.** Any error lost every finished run. | | Finished scenarios are checkpointed to disk as they complete. |
| 17 | **Which server answered, and when, was not recorded.** The engine-log files store no address, and the only timestamp is the moment the file was written. | Working backwards from those times, 20 invocations across three models and nine profiles ran in 41 minutes, with switches as short as 32 seconds, on two Strata installs. Whether an earlier model was still loaded cannot be told. | Start time, seconds since the start for every run, runtime name and version, and the kind of address and port are stored. |
| 18 | **Requests went through the system proxy settings.** Python's default opener honours proxy variables, and on Windows the usual local bypass does not cover `127.0.0.1`. | No effect on the published numbers. On a PC with a proxy tool, a relayed stream can be buffered without a trace. | The client connects straight to the address it is given. |
| 19 | **Labels lived in hand-typed file names.** | A file named `coding-64k` holds 50,119-token prompts; two named `coding-50k` hold 54,901 and 64,513; two named `fresh-engine` show four conversations already in memory. | File names are built from the detected runtime, model and suite. Sizes are read from the runs. |

### The same faults, reproduced on purpose

To confirm the mechanisms, the v1 client and `llmbench` were both pointed at a fake server whose true speeds are known: it reads 2,000 tok/s and writes 50 tok/s.

| What the server does | v1 read | v1 write | llmbench read | llmbench write |
|---|---:|---:|---:|---:|
| Plain stream, one token per event | 1,964 | 50.5 | 1,978 | 50.0 |
| Thinks for 60 tokens, then answers | 1,292 | **128.2** | 1,978 | 50.0 |
| Sends 16 tokens per event | 1,738 | **59.5** | 1,964 | 50.1 |
| Only thinking fits in the output cap | fails | fails | 1,978 | 50.0 |
| Keeps 8 earlier prompts cached, benchmark run twice | **75,104** | 50.5 | 1,975 | 50.0 |

True values: read 2,000, write 50. The remaining 1% gap in the llmbench reading column is the fake server's 20 ms of fixed overhead, which a stopwatch cannot separate from reading. The fake server ships with the tool (`python3 -m llmbench selftest` and `python3 -m llmbench mock-server`), so the measuring code can be checked on any machine.

## Part 2. Protocol 2

### Principles, borrowed from PC benchmarks

| Principle | Where it comes from | Here |
|---|---|---|
| A fixed, versioned workload. Never compare across versions. | Cinebench, CrystalDiskMark | Protocol and workload versions are stored in every file. `compare` refuses mixed versions. |
| Warm up, then repeat, and show the spread. | MLPerf Client, `llama-bench` | One uncounted read per size, two to five counted runs, median and spread. |
| Record the machine automatically. | 3DMark SystemInfo | OS, CPU, GPU, driver, memory, power state, runtime and model details. |
| A result is valid, valid with remarks, or invalid. | 3DMark, Strata's protocol | `clean`, `usable with cautions`, `invalid`. |
| Stability under load is a ratio. | 3DMark stress test (97%) | `soak`: worst loop as a share of the best. |
| Report scenes separately before any combined score. | Strata's protocol | No combined score. Seconds per typical request instead. |

### What is measured

| Name | Starts | Ends | Notes |
|---|---|---|---|
| Time to first token | request sent | first generated token of any kind arrives | Thinking counts. This is the one comparable across models. |
| Time to first answer | request sent | first answer text arrives | Equal to the above when the model does not think. |
| Reading speed | | | Fresh prompt tokens ÷ reading time. Cached tokens are excluded. Engine-reported when available. Otherwise the stopwatch time to first token minus the time spent writing the first event's tokens. |
| Writing speed | first token | last token | Tokens after the first event ÷ that window. Engine-reported when available. |
| Request time | | | Time to first token + N ÷ writing speed, for four fixed jobs. |

Engine timings are used when the runtime puts them in its reply: Strata and llama.cpp send a `timings` object, and Ollama's newer builds do on this address. LM Studio does not, so its numbers are stopwatch figures and are labelled `client-timed`. When both exist and differ by more than 15%, the result says so.

Runtimes do not agree on whether the first token counts in their own writing speed. llama.cpp divides n−1 tokens by the time since August 2026; Strata and Ollama divide n. `llmbench` follows each runtime's own convention and stores the raw token count and milliseconds so either can be recomputed. The difference is under 1% at these output lengths.

### The workload

- **Varied by construction.** A seeded generator writes a mixed repository: Python, TypeScript, Go, Rust, SQL, YAML, Markdown, JSON, shell and logs, with varied names, numbers and prose. At 400,000 characters its compression ratio is 4.5, the same as real Python source of that size. The v1 text was 73.
- **Identical everywhere.** The generator is a few lines of integer arithmetic, not Python's `random`, so the same seed gives the same bytes on every operating system and Python version. A test pins the hash.
- **Different for every run.** Each run has its own seed, so no cache can reuse an earlier run, even one that matches shifted chunks. A random marker leads the first message of every request.
- **Sized in tokens.** Two tiny probe requests teach the tool how this model counts this text, and the estimate is refined after every run. Against the fake server prompts landed within 0.1% of target. Real tokenizers will be less exact; a miss of more than 5% is flagged.
- **Yours if you want.** `--corpus file:PATH` uses your own code or text. Only its size and hash are stored.

A depth class is named after the window it fills. `ctx-32k` sends about 29,260 tokens: 90% of what is left of a 32,768-token window after 256 tokens are set aside for the answer. The margin absorbs the chat template and tokenizer differences, so the prompt plus its answer fits a window of exactly that size. `ctx-4k` sends about 3,456 and `ctx-16k` about 14,515; `llmbench scenarios` lists them all.

### Scenarios

| Scenario | Sends | Reports | Catches |
|---|---|---|---|
| `chat` | a short question, 256-token answer, 5 runs | time to first token, writing speed | fixed overheads, slow first token |
| `gen-long` | a short question, 1,024-token answer, 3 runs | sustained writing speed | bursty drafting, early throttling |
| `ctx-4k` … `ctx-256k` | fresh varied text filling about 90% of that window, 256-token answer; one uncounted read, then 3 runs | time to first token, reading speed, writing speed at that depth, first-read penalty | truncation, context too small, depth-dependent slowdowns |
| `followup-16k` | the 16K read, then a second question on the same conversation, 3 pairs | time to first token of the second turn, tokens served from cache, speed-up | runtimes that do not reuse the prefix |
| `repeat-16k` | the v1 repetitive text at 16K | ratio against `ctx-16k` | engines that are flattered by repeated content |
| `parallel-4` | four short requests at once, 2 rounds | total tokens per second, worst first token | servers that queue instead of batching |
| `schema` | a six-entry catalogue to copy into a JSON form whose descriptions allow 80 characters, 3 runs; asked again up to twice when the answer does not fit | answers that fit on the first try and after retries, server refusals (HTTP 502 `structured_output_failed`) | servers that only prompt with the schema instead of constraining decoding to it, and thinking that never reaches an answer |
| `sanity` | three exact-answer checks: echo a word, return a small JSON, find two markers hidden near the start and end of a 4K prompt | passed out of three | a model that is not seeing the whole prompt |
| `control` | the `chat` scenario again at the very end | writing speed against the start | drift from heat, background load or a runtime that changed state |
| `soak` (opt-in) | a 4K read and 256-token answer in a loop for N minutes | worst loop ÷ best loop | thermal throttling |

Suites: `quick` (chat, 4K, 16K), `standard` (adds the long answer, follow-up, 64K, sanity and control), `deep` (adds 32K, 128K, 256K, the repetition probe, parallel requests and the schema probe).

Two scenarios the tool cannot run for you, and how to do them by hand:

- **Cold start.** Quit the runtime, start it, and run with `--cold`. The warm-up line is then the first-request time including model load.
- **Drafting on against off.** Run the suite twice with the runtime's drafting setting changed and use `compare`. Use your own text (`--corpus file:PATH`), because how often a draft is accepted depends on the text.

### Repeats and noise

- One warm-up request loads the model and is never counted.
- The first read at each new prompt size is made once and reported on its own. In the v1 data the first request of an invocation was the slowest in 16 of 16 files, even inside an engine that was already warm, so one warm-up per model load is not enough.
- Counted runs: 5 for chat, 3 for reads up to 64K, 2 above.
- Every summary is a median with minimum, maximum and spread (half the range over the median).
- `compare` calls two results different only when the gap is larger than run-to-run variation would produce by chance about one time in twenty (a Welch test on the runs of both results), with a 2% floor. For durations there is also a 25 ms floor, because a 30 ms wait that wobbles by 10 ms is not a finding. The first version of this rule compared the gap with half the range of the runs. In a simulation with no real difference it reported one about one time in four with three runs per side; the current rule stayed under one in twenty at every run count tried, from 2 to 12.
- The `control` scenario repeats the first one at the end. A difference of more than 10% is reported as drift.

With three runs and 5% run-to-run variation, even a 10% difference is found less than one time in five. Use `--runs 6` or more when the question is that fine. Noise also differs widely between setups: in the v1 data, writing speed varied by 0.6% between runs with drafting off and by up to 12% with drafting on. The Spread column is the guide to how many runs a setup needs.

### Cache rules

A read is "fresh" only if the runtime did not reuse earlier work. The tool:

1. puts a random marker at the very start of the first message, so two requests share nothing but the chat template's opening tokens;
2. gives every run different text;
3. reads the cached-token count from the runtime (`usage.prompt_tokens_details.cached_tokens`, or `timings.cache_n`);
4. excludes a fresh run from the medians when more than 2% of its prompt (and more than 64 tokens) was cached, and says so.

The cached follow-up is a separate scenario with its own numbers. LM Studio does not report cached tokens on this address; there the tool relies on rules 1 and 2.

### Result quality

| Verdict | Meaning |
|---|---|
| `clean` | Nothing to report. |
| `usable with cautions` | Numbers stand. The listed remarks may explain a difference: an early stop, a buffered stream, a noisy scenario, battery power, drift. |
| `invalid` | A scenario produced no usable run, or the run was interrupted. |

Flags are listed in [llmbench.md](llmbench.md#result-quality-and-flags).

### How the tool itself is checked

- `python3 -m llmbench selftest` runs the client against the fake server in a separate process and fails if writing speed is off by more than 4% or the first token by more than 40 ms. On a quiet machine the errors were under 0.5% and about 1 ms.
- 160 unit tests cover the workload hashes, every metric formula, the schema probe against servers that enforce, ignore or refuse the schema, the stream classifier (separate thinking fields, inline think tags, tags split across events), runtime detection, the engine-log parser, the redactor, model-pull delegation, and full suite runs. They pass locally on Windows Python 3.14; CI has also passed on Windows, macOS, and Linux with Python 3.9 and 3.13.
- The CLI has been benchmarked against loaded Strata Inkling and Qwen models on one Windows PC. The new diverse-corpus measurements are documented separately from the older repeated-text baseline.

### Known limits

- Without engine timings, reading speed still includes a few milliseconds of request overhead. It matters below about 1,000 prompt tokens.
- Fewer stream events than tokens can mean two things that need opposite corrections: a buffered stream, or tokens the server counted and never streamed. The tool uses what the server declares (reasoning tokens in its usage report), then the engine's own rate, and only then the size of the events. Without an engine figure the writing speed is flagged as an estimate either way.
- Summary rows hold the median of each metric separately, so a row may describe no single run. Every run is stored in the file.
- The tool cannot see how long the engine process has been running. A first request after an engine start can be slower for reasons the warm-up does not remove; restart, then use `--cold`, when that is the question.
- Engines that adapt while they run (Strata's expert cache) are not repeatable to better than about 10% without their own determinism settings. Results on them should be repeated across sessions.
- Model files are not hashed, because the tool only sees the server. Note the exact file in `--label`.
- Prompts are matched in tokens. That is the right comparison for one model file on different runtimes, where tokens are identical. Between different models a token is a different amount of text, so compare seconds for the same job, or characters per second: the result stores how many characters this model counts per token.
- The number of runs is fixed. A rule that keeps running until the median is known to a target width would suit noisy setups better.
- Real-model validation is currently from one Windows PC with Strata. Model runs on macOS and Linux remain open follow-up work; unit and package CI passes on all three operating systems.

## Part 3. Existing tools, and why this one

| Tool | Good for | Why it is not enough alone |
|---|---|---|
| [MLPerf Client](https://mlcommons.org/benchmarks/client/) 2.0 | A vetted, comparable score on Windows and macOS. | It runs its own models through its own bundled engines. It cannot measure your Strata, LM Studio or Ollama install. Its standard prompts top out near 7,600 tokens, with experimental tasks near 28,000. |
| [LocalScore](https://github.com/cjpais/LocalScore) | One number per machine. | Own runtime, prompts up to 4,096 tokens. Its public site was offline when checked. |
| UL Procyon AI Text Generation | A commercial, supported benchmark. | Licensed, fixed models, own engines. |
| [`llama-bench`](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md) | The raw speed of the llama.cpp engine, comparable with public scoreboards. | llama.cpp only. Random tokens and no server, so it is an upper bound and cannot exercise drafting or caching. |
| [llama-benchy](https://github.com/eugr/llama-benchy) | The closest match: reading and writing speed at a chosen depth against any OpenAI-compatible address. | Stopwatch only. A report against Strata showed 156,393 tok/s for a prompt truly read at about 260, because keep-alive chunks counted as the first response. No commits since July 2026, random prompt slices without a seed, needs a Hugging Face tokenizer. |
| [`strata bench run`](https://github.com/Niko1221/Strata/blob/main/docs/BENCHMARK_PROTOCOL.md) | The best-specified protocol found: frozen prompts, warm-up, cache ceilings, validity status. | A draft, for one model family, on Strata only, with prompts up to 16K. |
| AIPerf, vLLM bench, inference-benchmarker | Load testing a server with many clients. | A different question from "how does my PC feel with one user". |
| [llamaperf.com](https://llamaperf.com/about) | Seeing what others report. | An aggregator of posts, by its own description not a controlled benchmark. |

**Verdict: build, but small.** No existing tool covers the combination this repository needs: Strata, LM Studio, llama.cpp and Ollama; engine timings where they exist; prompts from 4K to 256K tokens; cached follow-ups; Windows and macOS. The pieces already existed here, so one dependency-free package was the cheap part. What was deliberately left out: a graphical app, packaged executables, a result database and a single headline score. Each of those needs upkeep that a small project cannot promise.

Run these alongside it, because they answer questions it does not:

- `llama-bench`, to compare your engine with the public scoreboards.
- `strata bench run`, for Strata's own standard record.
- MLPerf Client, for one externally defined number per machine.

Borrowed ideas: the unique marker and cached-token ceiling (Strata's protocol), prompts measured at context depth and the two-step cache test (llama-benchy), warm-up plus repeated runs (MLPerf Client, `llama-bench`), engine timings from the reply (llama.cpp's own bench client), the stability ratio (3DMark), and version discipline (Cinebench).

## Part 4. Re-measuring the 2026-11-23 baseline

The v1 files stay in the repository as a record. They should not be mixed with protocol 2 results. A re-run that would settle the open questions:

1. **Qwen3.6 and Inkling on Strata 0.2.20**, `--suite deep`, once per context profile. Engine timings now come from the reply, so the Inkling rows get engine figures for the first time.
2. **The repetition question**: `--scenarios ctx-16k,repeat-16k` on each model. The ratio says how much the v1 numbers were flattered.
3. **DeepSeek on Strata 0.2.13** with `--engine-log`, same two steps. Expect lower numbers on varied text. Clear or move the engine's on-disk conversation folder first, or accept that `llmbench` will flag any reuse.
4. **The 27.6K anomaly**: `--depths 32k` three times in one session, with a `chat` control before and after (the standard suite does this). Slow controls mean session state; a slow 32K alone means a real capacity effect.
5. **The same model file on llama.cpp and LM Studio**, to place Strata's numbers against the reference engine on the same card.
6. **A soak**, `--soak-minutes 10`, once per machine.
