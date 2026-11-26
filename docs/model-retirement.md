# When a runtime retires a local model

Local weights and runtime support have separate lifecycles. A runtime update can stop recognizing an architecture, quantization, or pack format that an older version loaded. Strata marks DeepSeek V4.1 Flash as retired and rejects its saved launch configuration. The rejection does not delete the weights. [Strata retirement handling](https://github.com/Niko1221/Strata/blob/main/strata_control/retired.py)

On the benchmark PC, DeepSeek V4.1 Flash 1017 (ISTA-DAS 2.00 bpw) still generated offline with the installed Strata 0.2.13 compatibility bundle and Windows CUDA engine 0.1.59. This establishes a working version on this machine. Future driver or OS changes can affect that combination. Keep the known working server and engine together. [Strata 0.2.13 release](https://github.com/Niko1221/Strata/releases/tag/v0.2.13)

To reproduce a run later, keep the four backbone shards, shared Engram and DSpark files, pack manifest and tensor index, tokenizer and chat template, and the working run configuration. Record checksums, engine version, GPU driver, and launch flags. The pack metadata contains storage paths. When copying the pack to another disk, verify the index and configuration point to the intended copies. A different runtime needs explicit support for this architecture and artifact layout. Check compatibility before downloading another large conversion.

For benchmarks, record a retired configuration as a versioned result. If a newer runtime cannot load it, record that as a compatibility outcome with the error and runtime version. A failed load has no throughput measurement.
