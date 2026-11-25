"""Small, explicit starter catalog of downloadable GGUF checkpoints."""
from __future__ import annotations

from typing import Any, Dict, List

# Hugging Face GGUF download activity was checked on 2026-11-25. These are
# examples across practical sizes, not a quality ranking. Recheck upstream before
# publishing a new release; model publishers can replace files at any time.
MODELS: List[Dict[str, Any]] = [
    {
        "id": "qwen9b-q4",
        "name": "Qwen3.5 9B Q4_K_M",
        "params": "9B dense",
        "size": "5.68 GB",
        "bytes": 5680522464,
        "downloads": 2198606,
        "repo": "unsloth/Qwen3.5-9B-GGUF",
        "files": ["Qwen3.5-9B-Q4_K_M.gguf"],
        "tier": "starter",
        "note": "Good first download; fits many Apple Silicon Macs with room for context.",
        "url": "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF",
    },
    {
        "id": "qwen27b-q4",
        "name": "Qwen3.5 27B Q4_K_M",
        "params": "27B dense",
        "size": "16.74 GB",
        "bytes": 16740812704,
        "downloads": 405686,
        "repo": "unsloth/Qwen3.5-27B-GGUF",
        "files": ["Qwen3.5-27B-Q4_K_M.gguf"],
        "tier": "workstation",
        "note": "Popular larger dense model; check unified memory/VRAM plus context headroom.",
        "url": "https://huggingface.co/unsloth/Qwen3.5-27B-GGUF",
    },
    {
        "id": "qwen35b-a3b-q4xl",
        "name": "Qwen3.6 35B-A3B UD-Q4_K_XL",
        "params": "35B total / 3B active MoE",
        "size": "22.85 GB",
        "bytes": 22853663008,
        "downloads": 3049815,
        "repo": "unsloth/Qwen3.6-35B-A3B-MTP-GGUF",
        "files": ["Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"],
        "tier": "workstation",
        "note": "Existing PC reference model; MoE active count does not equal memory required.",
        "url": "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF",
    },
    {
        "id": "qwen177b-iq2xs",
        "name": "Qwen3.8 Flash Next 177B UD-IQ2_XS",
        "params": "177B total MoE",
        "size": "75.82 GB (3 shards)",
        "bytes": 75832093338,
        "downloads": 4051762,
        "repo": "unsloth/Qwen3.8-Flash-Next-GGUF",
        "files": ["UD-IQ2_XS/*.gguf"],
        "tier": "large-offload",
        "note": "Large-model/offload trial. Keep free RAM for OS and KV cache; SSD paging can be very slow.",
        "url": "https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF",
    },
]


def find_model(model_id: str) -> Dict[str, Any]:
    for item in MODELS:
        if item["id"] == model_id:
            return item
    raise KeyError(model_id)
