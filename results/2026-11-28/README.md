# Same file, two engines, thinking on and off: 2026-11-28

This record corrects how the earlier Strata and LM Studio numbers in this repository were read. The short version: **hidden thinking, not the engine, decided how long a job took.** With thinking off and the same model file, Strata and LM Studio are close; LM Studio pulls ahead as soon as several requests run at once, and it is the only one of the two that holds a JSON answer to its schema.

## What was run

- **Machine:** the reference PC (Ryzen 9 9950X3D, RTX 5090 32 GB, 128 GB RAM, Windows 11 Pro build 26300, NVIDIA driver 621.01). The model file sat on the Kingston Gen 5 drive (C:, CPU lanes).
- **Model:** one file, `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` (22.85 GB), served by both engines. It was hard-linked into LM Studio's models folder for the test and the link removed afterwards, so both engines read the same bytes.
- **Engines:** Strata 0.2.21.1 / engine 0.1.67, profile `qwen36-q4-32k` (32K context, MTP drafting 2, one slot); LM Studio server with its llama.cpp CUDA runtime 2.83.0, loaded with `--context-length 32768 --gpu max` (LM Studio's default of 4 parallel slots).
- **Tool:** `llmbench` from this branch (still reporting version 0.2.0), suite `quick` plus the new `schema` probe and `parallel-4`, three runs per scenario, `--thinking default` and `--thinking off`.
- **Timing sources differ.** Strata puts engine timings in its reply; LM Studio's OpenAI endpoint does not, so its rates are client-timed. Client timing includes stream overhead and reads a few percent low, so small gaps in Strata's favour below are within that error.

## Results with thinking off

| Scenario | Strata | LM Studio | Notes |
|---|---:|---:|---|
| Short chat, writing | 305 tok/s | 226 tok/s | Strata drafts ahead (MTP 2); LM Studio does not |
| 4K prompt, reading / writing | 11,791 / 267 tok/s | 7,181 / 215 tok/s | |
| 16K prompt, reading / writing | 9,214 / 194 tok/s | 8,183 / 197 tok/s | the writing gap is gone at 16K |
| Four requests at once, total writing | 286 tok/s (one slot) | **383 tok/s** | LM Studio: 1.7 times its single-request rate. Strata queues them |
| Same, Strata with 4 slots | 234 tok/s | | single-request writing also fell to 164 tok/s, so 4 slots is worse on this build |
| JSON schema held on the first try | 0 of 3 | **3 of 3** | Strata wrote descriptions longer than `maxLength`; 1 of 3 fit after two retries |

Strata still counted tokens it never streamed in 7 of 12 runs with thinking off, but its answer text began with the first token, so these are most likely its drafting bookkeeping rather than thinking. LM Studio with thinking off showed neither.

## Results with thinking on (the default for Qwen3.6)

| Scenario | Strata | LM Studio |
|---|---|---|
| Answer text within the 256-token cap (chat, 4K, 16K) | none, all thinking | none, all thinking |
| Schema probe, 2,048-token cap | refused 3 of 3 (HTTP 502 `structured_output_failed`); 1 of 3 fit after retries; 5.6 s to first token | **no answer at all**: the model thought through 2,048 tokens in every one of 9 attempts |

Writing speed in tok/s looks the same or better with thinking on (Strata 338 against 305 for a short chat), because thinking tokens are tokens. It is the time to an answer that changes, and tok/s does not show it.

## What this corrects

1. **"Strata is about twice as fast as LM Studio."** That impression came from setting Strata's 168.8 tok/s (Inkling SQ-10, 10.5 GB native pack, engine-timed) beside Bionic's 74.5 tok/s (Inkling Q4_K_M, 18.1 GB GGUF, LM Studio stats) in [2026-11-25](../2026-11-25/README.md): different files, different timing sources, and thinking left on. On one file with thinking off, Strata writes 0 to 35% faster and reads 13 to 64% faster depending on prompt size, the order reverses with parallel requests, and on a whole JSON job Strata was 15% slower.
2. **The 2026-11-25 Qwen figures (284 and 215 tok/s) were measured with thinking on.** Every one of those runs produced only thinking within the cap. The rates are valid as generated tokens; they are not the speed at which answers appear.
3. **Parallel requests.** The guide's figure (2.8 to 3.9 times at eight requests) was from Strata's own test on a Radeon card. On this PC: LM Studio 1.7 times at four, Strata none.

## The same finding on a real job

A menu-reading pipeline on this PC (20 restaurant web pages, two model stages that return JSON, same model family) measured the whole job, not tok/s:

| Run | Model time for 20 pages |
|---|---:|
| LM Studio, fine-tuned Q4_K_M, thinking on (its default) | 57 min |
| LM Studio, same file, thinking off | 13.5 min (4.2 times faster) |
| LM Studio, UD-Q4_K_XL, thinking off | 9.5 min |
| Strata, UD-Q4_K_XL, thinking off | 11 min, one format retry |
| LM Studio, Q4_K_M, thinking off, 4 requests at once | 8.2 min (1.7 times) |

The readings were about as accurate with thinking off (it fixed two of the thinking run's mistakes and made one of its own). In the same job: a 16K context instead of 32K lost the longest menus and was slower through retries; the 3.5-bit IQ3_M quant saved 5 GB of VRAM but was not faster and read six of twenty totals differently; loading from the chipset-attached T500 took 14.0 s against 11.8 s from the CPU-attached Kingston, with identical generation speed (230 to 241 tok/s) once loaded.

## Files

Sanitized result JSON, one per run set: [`strata-thinking-default`](strata-thinking-default.json), [`strata-thinking-off`](strata-thinking-off.json), [`lmstudio-thinking-default`](lmstudio-thinking-default.json), [`lmstudio-thinking-off`](lmstudio-thinking-off.json), [`strata-schema-thinking-default`](strata-schema-thinking-default.json), [`lmstudio-schema-thinking-default`](lmstudio-schema-thinking-default.json), [`strata-schema-parallel-thinking-off`](strata-schema-parallel-thinking-off.json), [`lmstudio-schema-parallel-thinking-off`](lmstudio-schema-parallel-thinking-off.json), [`strata-4slots-parallel-thinking-off`](strata-4slots-parallel-thinking-off.json).

The first four files ran the schema probe with a 768-token cap, before it was raised to 2,048; the two `schema-*` files supersede their schema rows. `strata-thinking-default.json` is marked invalid because the earlier probe code counted a server refusing every answer as a failed request; the current code records it as the finding it is.

To repeat on another machine:

```powershell
py -m llmbench run --suite quick --scenarios chat,ctx-4k,ctx-16k,schema,parallel-4 --thinking off --output local-results/off.json
py -m llmbench run --suite quick --scenarios chat,ctx-4k,ctx-16k,schema,parallel-4 --output local-results/default.json
py -m llmbench compare local-results/default.json local-results/off.json
```
