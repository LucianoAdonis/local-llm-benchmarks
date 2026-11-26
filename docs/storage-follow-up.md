# Storage topology and follow-up benchmark

## Current baseline

The system board detected by Windows is a Gigabyte X870E AORUS PRO ICE. Windows reports the active 2 TB NVMe as `KINGSTON SFYR2S2T0`; the user reports it is installed in the first CPU-connected M.2 channel, labelled `M2A_CPU` in Gigabyte's manual. Kingston identifies part number `SFYR2S/2T0` as the FURY Renegade G5 PCIe 5.0 x4 drive and rates its 2 TB version at up to 14,700 MB/s read and 14,000 MB/s write.

The separate Crucial T500 4 TB (`CT4000T500SSD3`, with a possible `G` suffix as shown on the purchased drive) had not been installed when these benchmarks were captured. Crucial rates the 4 TB T500 at up to 7,000 MB/s read and 6,900 MB/s write.

## Slot map

| Board connector | Connection | Supported link on this system | Planned use |
|---|---|---|---|
| `M2A_CPU` | Direct to CPU | Ryzen 9 9950X3D supports PCIe 5.0 x4 | Current Kingston G5, per owner report |
| `M2D_SB` | Through the AMD chipset | PCIe 4.0 x4 | Planned Crucial T500 4 TB |

The board's other CPU M.2 slots (`M2B_CPU` and `M2C_CPU`) also connect to the CPU and can affect GPU-lane allocation when populated. This comparison is specifically about the current `M2A_CPU` drive versus adding the T500 at `M2D_SB`; follow the motherboard manual for the exact physical location and installation steps.

**Naming correction:** Gigabyte calls the first slot `M2A_CPU`; the chipset slot is `M2D_SB`. “M2A_SB” is not the connector name listed for this board.

## Expected result before measuring

The current Kingston is a faster-interface PCIe 5.0 drive. The T500 is PCIe 4.0 and has about half the advertised sequential read ceiling. That means the T500 should be treated as extra storage and an alternate I/O path, not as an assumed speed upgrade over the Kingston.

An added drive could still help if model files and other active reads are separated across devices. It may also have different sustained, random-read, thermal, and chipset-contention behavior. If the model's hot working set stays resident in VRAM/RAM, token decode may not use the SSD and may not change at all. DeepSeek's large pack and SSD-mapped support data make startup, paging, and cold-cache behavior worth measuring separately.

There is no defensible fixed percentage improvement to promise. The pre-registration expectation is:

- **Warm decode with no disk reads:** near 0% change.
- **Cold model load, cold prompt/paging, or disk-backed offload:** unknown; it may improve or regress. Measure it.
- **Sequential file transfer:** the T500's advertised maximum is lower than the Kingston G5's, so do not expect higher peak throughput from it.

## A/B procedure after installing the T500

1. Save the current `C:` results as the baseline; record both drive models, motherboard slot, firmware, free space, and temperatures.
2. Install the T500 in `M2D_SB`, confirm Windows sees the drive, check or prepare its NTFS volume, identify its assigned drive letter (here `E:`), and verify it operates at PCIe 4.0 x4. Do not move or delete the only copy of the model pack during setup.
3. Copy the same model package to `E:` and verify file count, sizes, and hashes. Keep Strata/engine version, profile, quantization, context, prompts, output limit, and GPU/background state fixed.
4. Run separate tests for:
   - model cold-start/load time;
   - a cold 4K prompt and a cold long prompt;
   - warm 4K and long-prompt runs after the same profile is already loaded;
   - long-context decode with the same DeepSeek model and output budget.
5. Record medians and ranges for prefill, decode, TTFC, wall time, peak RAM/VRAM, disk read MB/s, disk active time, and SSD temperature. Run at least three repeats for short tests; label a costly 256K run as one observation unless repeated.
6. Compare `C:` and `E:` only after confirming the model source and all required shared files are on the intended drive. A drive letter alone does not prove which physical disk supplied the data.

The warm/cold distinction matters: Windows file cache can make a second run look faster even when the SSD did not change. Rebooting or clearing caches changes the test condition; record which method was used and apply the same method to both drives.

Use varied text for this test. With a repetitive prompt the model keeps touching the same few experts and table pages, which stay in memory, so the drive is barely read and any difference between the two SSDs is hidden. `python3 -m llmbench run` uses varied text by default; `--scenarios ctx-16k,repeat-16k` shows how much repetition changes the result on this machine.

## Sources

- [Gigabyte X870E AORUS PRO ICE specifications](https://www.gigabyte.com/Motherboard/X870E-AORUS-PRO-ICE-rev-10/sp)
- [Gigabyte board manual and block diagram](https://download.gigabyte.com/FileList/Manual/mb_manual_x870e-aorus-pro-ice_1003_e.pdf)
- [Kingston FURY Renegade G5 specs](https://www.kingston.com/en/ssd/gaming/kingston-fury-renegade-g5-nvme-m2-ssd?partnum=sfyr2s%2F2t0)
- [Crucial T500 product flyer](https://uk.crucial.com/content/dam/crucial/ssd-products/t500/flyers/b2c/crucial-T500-b2c-product-flyer-en_combination.pdf)

See [reporting a storage benchmark](storage-reporting.md) and [runtime compatibility and model retirement](model-retirement.md).

The T500 is now installed as E:. D: is a separate hard drive. See the [November 26 DeepSeek comparison](../results/2026-11-26-storage/README.md). For replication, use the actual SSD drive letter in the procedure above.
