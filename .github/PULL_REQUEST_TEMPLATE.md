## Benchmark report checklist

- [ ] Hardware, operating system, driver, runtime, engine, model source/revision, quantization, and settings are recorded.
- [ ] Configured context and actual prompt token count are both reported.
- [ ] Prefill and decode metrics are separate and labeled as engine or client measurements.
- [ ] Repeats, per-run values, cache policy, and background load are documented.
- [ ] Public JSON and logs are sanitized; no model weights, secrets, private code, or local paths are included.
- [ ] A speed result is not presented as a quality result.
