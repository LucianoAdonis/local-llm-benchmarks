# Methodology

## Questions measured

This suite answers two different questions:

1. **Prompt ingestion:** how quickly the server processes a known amount of coding context before useful output starts.
2. **Token generation:** how quickly it produces the answer after output begins.

It also records time to first content and full request wall time because a fast decode rate does not compensate for a long prefill wait in real use.

## Workload

The harness builds a deterministic synthetic Python repository from repeated worker modules. Each run includes a unique identifier and asks for a concise, evidence-based engineering review. The exact template is in `scripts/strata_coding_context_benchmark.py` (`make_prompt`). It is designed to scale by section count and avoid leaking real project code.

Default controlled settings for the recorded runs:

- Temperature: `0`
- Output cap: `100` tokens
- Single request at a time
- Configured context: 32K, 128K, or 256K depending on the run
- Prompt sizes: actual token counts returned by the model server, not section count or a character estimate
- Repetitions: usually three for short/medium runs, two for long runs, one for the expensive near-full 256K prompt

## Metrics

- **Prefill tok/s:** engine-reported prompt tokens read divided by prefill time when engine logs expose it. Otherwise the repository records a *client proxy*: prompt tokens divided by time to first streamed content. The proxy includes queueing and API overhead and is labeled as such.
- **Decode tok/s:** engine-reported generated tokens divided by engine decode time when available. Otherwise output tokens divided by the client-observed stream window after first content; this is not a kernel-only decode rate and can be distorted by server buffering.
- **TTFC:** request start to first streamed text content (not simply the first SSE frame).
- **Wall time:** request start through stream completion.
- **Actual context depth:** prompt tokens reported in API usage. Context capacity and actual prompt length are reported separately.

The first 82.3 tok/s DeepSeek client-stream estimate on this machine was inflated by buffering. This repository marks it superseded and uses the engine-log decode result instead.

## Repeat and cache policy

1. Start a fresh runtime before a model/depth group when possible.
2. Give each request a unique marker and never reuse the same long prompt as a “fresh” run.
3. Save per-run values and engine-reported reused-token counts. A unique tail does not guarantee that an engine will not reuse a shared prefix.
4. Record whether the engine was freshly loaded, whether other GPU work ran, and whether any requests were cached or queued.
5. Use medians and ranges for repeated runs. Mark single-run near-capacity results as a single observation.

The logs from this DeepSeek engine showed internal prompt-prefix reuse in some 32K runs even though the request marker changed. Those records retain both API prompt size and engine tokens actually read; use the engine read count for prefill calculations.

## Comparison rules

Compare one change at a time. Keep model revision, quantization, engine/Strata version, context capacity, actual prompt depth, output cap, temperature, cache state, GPU power settings, and background load constant. Storage comparisons require moving the same model files to the new drive and repeating the same test; merely adding an SSD does not change an already resident decode workload.

Speed is not quality. Use a separate fixed set of real coding tasks with expected outcomes if comparing code correctness, tool use, repository understanding, or retrieval quality.

## Influences

- [Strata Community Benchmarks](https://github.com/Niko1221/Strata/blob/main/docs/COMMUNITY_BENCHMARKS.md): per-run JSON, hardware/settings metadata, medians/ranges, privacy redaction, and old/new comparison checks.
- [llama-benchy](https://github.com/eugr/llama-benchy): prompt-processing and generation throughput at different context depths through an OpenAI-compatible API.
- [llama.cpp `llama-bench`](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench): the established distinction between prompt-processing and token-generation benchmarks.

This project borrows these methodology conventions; its harness code is original and no upstream benchmark code is vendored.
