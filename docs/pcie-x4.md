# What PCIe ×4 means for an SSD

PCIe connects your NVMe SSD to the computer. **×4 means the link uses four lanes in parallel.** The PCIe generation determines the speed of each lane. The link negotiates a generation and lane count that both the drive and the slot support.

| Link | Theoretical bandwidth in one direction |
|---|---:|
| PCIe 4.0 ×2 | 3.94 GB/s |
| PCIe 4.0 ×4 | 7.88 GB/s |
| PCIe 5.0 ×4 | 15.75 GB/s |

These are link ceilings after PCIe encoding overhead, before protocol overhead. Actual SSD throughput also depends on the drive controller, flash, temperature, and read pattern.

## What that means on this PC

- **Kingston G5 on C:** negotiates PCIe 5.0 ×4 in the CPU-connected slot.
- **Crucial T500 on E:** negotiates PCIe 4.0 ×4 through the chipset, consistent with the board's M2D_SB slot. Other chipset devices can share the upstream connection.
- **A Gen 5 SSD in M2D_SB** would still negotiate at most Gen 4 ×4. On this board, populating M2B_CPU or M2C_CPU can reduce the main GPU slot to ×8. Check the slot map before moving drives. [Gigabyte specifications](https://www.gigabyte.com/Motherboard/X870E-AORUS-PRO-ICE-rev-10/sp)

## What to measure with a local model

A wider or faster link can help when a run reads heavily from the SSD, such as during model preload or disk-backed expert access. Once the relevant weights are in RAM or VRAM, warm generation can depend more on memory bandwidth and compute. Small or scattered reads can also hit latency limits well before the link reaches its sequential bandwidth ceiling.

Record the drive, physical slot, negotiated link, and cache conditions. Measure preload, first-token latency, and warm generation separately. In this PC's DeepSeek comparison, the Kingston preloaded experts faster, while the T500 reached the first token sooner on the longer prompt in one pass. Warm generation was within run-to-run variation. [DeepSeek storage comparison](../results/2026-11-26-storage/README.md)
