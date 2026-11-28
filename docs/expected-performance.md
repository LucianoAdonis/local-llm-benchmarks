# Reading benchmark results and setting expectations

> New here? [start-here.md](start-here.md) is the plain-language guide, with ceilings, tips and what to expect from each runtime. [community-baselines.md](community-baselines.md) has other people's numbers for comparison. This page covers the 2026-11-23 baseline and later PC iterations.

This file is a quick guide to what the speed numbers mean and what counts as a useful comparison. There is no universal “normal tok/s”: model architecture, quantization, active experts, runtime, prompt length, speculative decoding, context depth, and memory placement all change the result.

## The four numbers to read

- **Prefill tok/s**: speed reading the input prompt. This affects how long the model takes before it can answer. Prefer engine-reported prompt timing. A client proxy based on prompt tokens / time-to-first-content includes server, queue, and API overhead.
- **Decode tok/s**: speed generating output after it starts. Prefer engine-reported timing. A client stream rate is approximate and may be distorted by buffering.
- **TTFC**: time from request start until the first actual text content arrives. It includes prefill and service overhead.
- **End-to-end tok/s / wall time**: what a user experiences for a short request, including the time spent waiting for prompt processing. Keep this separate from decode speed.

Always distinguish **configured context capacity** from **actual prompt tokens**. A 256K profile with a 5K prompt is not a 256K-depth measurement.

## A rough human-facing decode guide

These are subjective reading-speed bands for ordinary text, not a benchmark standard or a quality score. Long reasoning pauses, tool calls, and the model's writing style can matter more than the average:

| Decode rate | Rough feel |
|---:|---|
| Under 10 tok/s | Noticeably slow for interactive chat |
| 10–20 tok/s | Usable, but long answers take time |
| 20–40 tok/s | Generally comfortable for a back-and-forth conversation |
| 40–80 tok/s | Quick response streaming |
| Over 80 tok/s | Very quick streaming; diminishing value if the model's answers are poor |

Treat these as a way to set expectations for visible output only. A model generating 20 tok/s after a 100-second prefill still feels slow for that request. This machine's table below is a stronger reference for comparisons on the same setup; compare only the same model, runtime, prompt depth, and timing method.

## Observed reference points for this PC

Machine: Ryzen 9 9950X3D, RTX 5090 32 GB, 128 GB RAM, Windows 11 Pro. These are measured results for these specific builds, not promised speeds for a different model or runtime.

| Model/build | Prompt depth | Prefill | Decode | What it indicates |
|---|---:|---:|---:|---|
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 4.5K | 838 tok/s | 26.9 tok/s | Small prompt, 32K profile |
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 15.1K | 1,510 tok/s | 27.2 tok/s | 32K profile; 3,982 of the tokens were reused from cache in every run |
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 27.6K | 1,427 tok/s | 11.6 tok/s | Unexplained outlier; not evidence of a near-full effect; needs a re-run |
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 50.1K | 2,319 tok/s | 23.1 tok/s | 128K profile; 20.9 on the first request, 25.3 on the second |
| DeepSeek V4.1 Flash IST-DAS 2.00 bpw | 250.1K | 2,506 tok/s | 20.9 tok/s | 256K profile; one run, the first after an engine start; 102.6 s to first content |
| Qwen3.6-35B-A3B UD-Q4_K_XL | 4.9K | 10,784 tok/s | 309.6 tok/s | 32K profile, engine timing |
| Qwen3.6-35B-A3B UD-Q4_K_XL | 27.5K | 7,328 tok/s | 163.1 tok/s | Near-full 32K prompt, one run |
| Qwen3.6-35B-A3B UD-Q4_K_XL | 54.9K | 4,158 tok/s | 92.6 tok/s | 128K profile |
| Inkling SQ-10 | 5.7K / 64.5K | client proxy | 170.2 / 64.9 tok/s | 32K / 128K profile; client stream measurements |
| Inkling UD-Q4_K_M, DSpark off | 5.7K / 64.5K | client proxy | 119.9 / 86.5 tok/s | 32K / 128K profile; client stream measurements |

The records and full per-run JSON are in [`results/2026-11-23/`](../results/2026-11-23/README.md). For model-specific comparisons, compare matching rows by build and prompt depth. Do not compare Inkling's client estimates to Qwen's engine timings as if they were measured identically.

Three cautions from the later review ([benchmark-design.md](benchmark-design.md)):

- **No effect of depth on DeepSeek's decode is resolved in this data.** The two requests that were first after an engine start wrote 20.9 tok/s (at 50K and at 250K). The second request at 50K wrote 25.3, and the six runs at 4.5K and 15.1K wrote 26.2 to 27.9. Depth, context profile and being a first request are tangled together, so the data cannot say which one matters.
- **DeepSeek's prefill rate rises with depth largely through amortisation.** The prompt read fits a per-request cost of roughly 2 to 4 seconds plus a steady rate near 2,600 tok/s, so 838 to 2,506 tok/s is not a speed-versus-depth curve.
- **The 27.6K row is an outlier.** Decode, and a step whose cost does not depend on prompt size, were 2.1 to 2.9 times slower than in every other DeepSeek run, while the 95.5%-full 256K run was normal. The cause is unknown.
- **The test prompt was repetitive.** For an engine that keeps the most-used experts in fast memory that is probably a best case. These files cannot say by how much.

## 2026-11-25 update

On the same PC, Strata 0.2.21.1 / engine 0.1.67's native suite measured Inkling SQ-10 at 168.8 tok/s around a 3.4K prompt (report marked nonconforming) and Qwen3.6 UD-Q4_K_XL at 186.1 tok/s around a 4.1K prompt (complete report). The diverse-corpus `llmbench` quick suite measured Inkling SQ-10 at **195 tok/s** around 3.5K and **168 tok/s** around 14.5K, with **7,121 tok/s** read speed at the larger depth. Qwen3.6 UD-Q4_K_XL measured **284 tok/s** around 3.4K and **215 tok/s** around 14.6K, reading at **9,626 tok/s** at the larger depth. Both reports say Strata emitted hidden thinking tokens; the Qwen run also reached 97% VRAM use. Treat its rate as generated tokens, not visible answer text, and use a lower-context follow-up to check memory pressure. See the [iteration record](../results/2026-11-25/README.md); the three methods and workloads should not be treated as one direct ranking.

## 2026-11-28 correction

Those Qwen and Inkling rates were measured with thinking on. Within each output cap the models wrote only thinking, so the numbers say how fast tokens are generated, not how soon an answer appears. On one Qwen3.6 UD-Q4_K_XL file with thinking off, Strata wrote 305 tok/s on a short chat and 194 at a 16K prompt; LM Studio wrote 226 and 197. Four requests at once gave LM Studio 383 tok/s in total and Strata 286. On a real JSON job, thinking off was 4.2 times faster and Strata was 15% slower than LM Studio. Earlier comparisons that put Strata at about twice LM Studio's speed mixed model files, timing sources and thinking states; see [results/2026-11-28](../results/2026-11-28/README.md).

## What counts as a meaningful change

- Compare medians from repeated runs and keep the range. A one-off long-context result is a data point, not a stable average.
- Look at TTFC and total wall time in addition to tok/s. A fast decode rate can still feel slow after a very long prompt.
- Track prompt tokens, output tokens, cache reuse, VRAM, RAM, GPU load, CPU load, disk activity, temperatures, and power limits when investigating a change.
- Treat a change as repeatable when it exceeds the run-to-run spread under the same setup. If the spread is 4%, a 1% change is not evidence of an improvement.
- Speed does not measure correctness. Use fixed coding tasks with expected outcomes for quality comparisons.

## SSD performance expectation for this machine

The current C: model drive is reported as a Kingston FURY Renegade G5 2 TB in the CPU-connected `M2A_CPU` slot. Kingston rates the 2 TB drive at up to 14,700 MB/s read and 14,000 MB/s write. The planned Crucial T500 4 TB is a PCIe 4.0 drive rated up to 7,000 MB/s read and 6,900 MB/s write, and the planned `M2D_SB` slot is chipset-connected PCIe 4.0 x4 on this motherboard.

So the T500 does **not** have a higher advertised sequential ceiling than the current drive: its read rating is about 48% of the Kingston's rated peak. Adding it may still help capacity or reduce I/O contention if files are split across drives, but do not expect a guaranteed token/s increase. For warm decoding with the working set already in RAM/VRAM, the expected change is near zero. If DeepSeek is waiting on SSD-backed pages or its Engram data, storage could affect cold starts and decode; the size and direction of the effect must be measured.

See [`storage-follow-up.md`](storage-follow-up.md) for the controlled before/after plan. The T500 was not installed during the published baseline.

## Machine-tuning order

To identify what actually helps, tune in this order and change one item per run:

1. **Stabilize the baseline:** close other GPU-heavy work, keep the same Windows power mode, Strata/engine build, model, context, cache procedure, and output cap. Record GPU temperature, clock, power, VRAM, system RAM, CPU load, and SSD activity.
2. **Check limits before changing settings:** look for GPU thermal/power throttling, RAM pressure/pagefile activity, SSD temperature/throttling, PCIe link generation/width, and background disk/GPU traffic.
3. **Measure storage separately:** run an SSD throughput check and the same cold/warm model tasks. A synthetic sequential SSD score does not predict model token speed by itself.
4. **Tune runtime settings:** only after the storage test, change one Strata option at a time (for example, context, prefill/batch, expert placement, or drafting). Save a separate profile and use `strata bench run` plus `python3 -m llmbench run`, then `python3 -m llmbench compare` on the two result files.
5. **Keep the best verified profile:** compare repeated medians and ranges, and restore the last known-good profile if a change causes instability or worse results.

Record BIOS memory profiles and GPU power settings before adjusting them. This benchmark project does not assume EXPO, overclocking, or undervolting is currently enabled.
