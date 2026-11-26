# DeepSeek storage A/B, 2026-11-26

Ryzen 9 9950X3D, RTX 5090 32 GB, 128 GB RAM, Windows 11. C: Kingston Fury Renegade G5 on CPU PCIe 5.0 x4. E: Crucial T500 4 TB on chipset PCIe 4.0 x4. Tested C then E with the same copied 256.8 GB DeepSeek V4.1 Flash 1017 ISTA-DAS 2.00 bpw pack, Strata legacy engine 0.1.59, llmbench 0.2.0, 32,768 context and fixed seed. The engine reported no retained conversations at each restart. The OS file cache was uncontrolled. Actual token counts differ slightly despite matching scenarios and seed.

| Scenario | Drive | Median prompt tokens | TTFT (s) | Prefill (tok/s) | Decode (tok/s) |
|---|---|---:|---:|---:|---:|
| 4K | Kingston | 3,437 | 9.10 | 373 | 26.73 |
| 4K | T500 | 3,439 | 10.17 | 334 | 26.67 |
| 16K | Kingston | 14,535 | 13.89 | 1,038 | 28.20 |
| 16K | T500 | 14,533 | 11.19 | 1,288 | 29.22 |

Three measured runs per row plus warm-up. The T500's 16K prefill was 24.1% faster and TTFT 19.4% lower in this pass. Both exceeded the within-session noise thresholds. Decode differences and short-prompt differences fell within those thresholds. The threshold does not account for between-session effects, and disk model, slot and run order changed together. Repeat in alternating order with disk read telemetry to attribute the effect.

The Kingston preloaded 75.4 GB into the engine RAM store in 11.6 s. The T500 preloaded 75.9 GB in 16.0 s during this pass, and 73.2 GB in 22.1 s in an earlier exploratory run. These are preload stages, not total cold startup times. A Gen 5 SSD installed in M2D_SB would still negotiate Gen 4. This test provides no basis to replace the T500 solely to improve decode speed.

[Kingston JSON](kingston.json) / [CSV](kingston.csv) · [T500 JSON](t500.json) / [CSV](t500.csv) · [Comparison](compare.txt) · [Reporting procedure](../../docs/storage-reporting.md)
