"""Runtime detection and engine-side timing adapters.

The benchmark itself only needs the OpenAI-compatible chat endpoint. This module adds what
each runtime exposes beyond that: its name and version, the loaded context window, model
metadata, and engine-reported timings.

Engine timings arrive in three ways:
* llama.cpp-style ``timings`` in the stream (read by client.py, normalised in metrics.py);
* nothing at all (LM Studio and Ollama on their OpenAI-compatible endpoints): the client
  estimate is used and labelled "client";
* a log file the engine writes (Strata): pass ``--engine-log`` and the timing rows written
  during each request are parsed here.
"""
from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from .client import get_json, post_json, EndpointError

EMBEDDING_HINT = re.compile(r"(?i)embed|rerank|bge-|e5-|nomic")

DISPLAY_NAMES = {"lmstudio": "LM Studio", "ollama": "Ollama", "llama.cpp": "llama.cpp", "strata": "Strata", "openai-compatible": "OpenAI-compatible server"}
LOADS_ON_FIRST_REQUEST = ("lmstudio", "ollama")


def display_name(name: Any) -> str:
    """The runtime's name as its users write it. Result files keep the short form."""
    return DISPLAY_NAMES.get(str(name), str(name or "unknown runtime"))


_MODEL_FILE_SUFFIXES = (".gguf", ".bin", ".safetensors", ".strata", ".mlx")


def public_model_id(model_id: Any) -> str:
    """The model name that is safe to print and store.

    llama-server uses the model's file path as its id unless ``--alias`` is set, and a file
    path names the user's home folder. Keep only the file name. Ids such as
    ``unsloth/Qwen3.6-35B-A3B-GGUF`` or ``qwen/qwen3.5-9b`` are names, not paths, and stay.
    """
    text = str(model_id or "")
    if "/" not in text and "\\" not in text:
        return text
    flat = text.replace("\\", "/").rstrip("/")
    base = os.path.basename(flat)
    untagged = flat.rsplit(":", 1)[0] if ":" in base else flat  # "dir/q.gguf:Q4_K_M" is still a file
    is_path = (
        text.startswith(("/", "\\", ".", "~")) or "://" in text or bool(re.match(r"^[A-Za-z]:[\\/]", text))
        or untagged.lower().endswith(_MODEL_FILE_SUFFIXES)
    )
    return base if is_path else text


def endpoint_class(root: str) -> str:
    """Describe where the server is without recording its address."""
    host = urlsplit(root).hostname or ""
    port = urlsplit(root).port
    kind = "remote"
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        kind = "loopback"
    else:
        try:
            address = ipaddress.ip_address(host)
            kind = "loopback" if address.is_loopback else ("lan" if address.is_private else "remote")
        except ValueError:
            if host.endswith((".local", ".lan", ".home", ".internal")):
                kind = "lan"
    return "%s:%s" % (kind, port) if port else kind


def _model_ids(body: Any) -> List[str]:
    if not isinstance(body, dict):
        return []
    return [str(m["id"]) for m in body.get("data") or [] if isinstance(m, dict) and m.get("id")]


# Fields of /props and /health that say what is running. Exact names only: a key that merely
# contains "device" or "build" may hold a serial number or a host name.
_PROVENANCE_KEYS = {
    "build_info", "version", "engine_version", "total_slots", "n_ctx", "n_ctx_train", "n_parallel", "model_alias", "backend", "family",
    "service", "status", "loaded", "max_context", "context_length", "quantization", "quant", "ftype", "spec_type", "drafting", "draft",
    "mtp", "kv_type", "cache_type_k", "cache_type_v", "flash_attn", "n_gpu_layers", "n_batch", "n_ubatch", "expert_cache", "modalities",
}


def _provenance(obj: Any, limit: int = 24) -> Dict[str, Any]:
    """Keep the known short scalar fields. A value that looks like a path is cut to its file name."""
    kept: Dict[str, Any] = {}
    if not isinstance(obj, dict):
        return kept
    for key, value in obj.items():
        if len(kept) >= limit or str(key) not in _PROVENANCE_KEYS:
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            kept[str(key)] = value
        elif isinstance(value, str) and 0 < len(value) <= 120:
            kept[str(key)] = public_model_id(value)
    return kept


def detect(root: str, api_key: Optional[str] = None, timeout: float = 4.0) -> Dict[str, Any]:
    """Identify the runtime behind an OpenAI-compatible root URL."""
    info: Dict[str, Any] = {"name": "openai-compatible", "version": None, "reachable": False, "models": [], "loaded_models": [], "context_tokens": None, "models_status": 0}
    status, body = get_json(root + "/v1/models", timeout=timeout, api_key=api_key)
    info["models_status"] = status
    if status == 0:
        return info  # nothing is listening: one failed connection is enough to know
    if status == 200:
        info["reachable"] = True
        info["models"] = _model_ids(body)

    # LM Studio: native REST lists every downloaded model with its load state.
    status, native = get_json(root + "/api/v0/models", timeout=timeout, api_key=api_key)
    if status == 200 and isinstance(native, dict) and isinstance(native.get("data"), list) and any(isinstance(m, dict) and ("compatibility_type" in m or "state" in m) for m in native["data"]):
        info.update({"name": "lmstudio", "reachable": True})
        entries = [m for m in native["data"] if isinstance(m, dict)]
        info["lmstudio_models"] = entries
        info["models"] = [str(m.get("id")) for m in entries if m.get("type") not in ("embeddings", "embedding")]
        info["loaded_models"] = [str(m.get("id")) for m in entries if m.get("state") == "loaded" and m.get("type") not in ("embeddings", "embedding")]
        return info

    # Ollama
    status, version = get_json(root + "/api/version", timeout=timeout, api_key=api_key)
    if status == 200 and isinstance(version, dict) and version.get("version"):
        info.update({"name": "ollama", "version": str(version["version"]), "reachable": True})
        status, running = get_json(root + "/api/ps", timeout=timeout, api_key=api_key)
        if status == 200 and isinstance(running, dict):
            loaded = [m for m in running.get("models") or [] if isinstance(m, dict)]
            info["ollama_running"] = loaded
            info["loaded_models"] = [str(m.get("name") or m.get("model")) for m in loaded]
        return info

    # Strata and llama.cpp's llama-server both answer /props. Strata identifies itself in
    # /health ("service": "strata") and in /props ("build_info": "Strata <version>").
    status, props = get_json(root + "/props", timeout=timeout, api_key=api_key)
    health_status, health = get_json(root + "/health", timeout=timeout, api_key=api_key)
    props = props if (status == 200 and isinstance(props, dict)) else {}
    health = health if (health_status == 200 and isinstance(health, dict)) else {}
    is_strata = str(health.get("service", "")).lower() == "strata" or str(props.get("build_info", "")).lower().startswith("strata")
    if is_strata or "default_generation_settings" in props or "build_info" in props or "total_slots" in props:
        info.update({"name": "strata" if is_strata else "llama.cpp", "reachable": True})
        for key in ("build_info", "engine_version", "version"):
            if props.get(key):
                info["version"] = str(props[key])
                break
        settings = props.get("default_generation_settings") or {}
        candidates = [
            settings.get("n_ctx") if isinstance(settings, dict) else None,  # llama.cpp
            props.get("n_ctx"),                                              # Strata /props
            health.get("max_context"),                                       # Strata /health
        ]
        for value in candidates:
            if isinstance(value, int) and value > 0:
                info["context_tokens"] = value
                break
        if isinstance(props.get("total_slots"), int):
            info["slots"] = props["total_slots"]
        if props.get("model_path"):
            info["model_file"] = os.path.basename(str(props["model_path"]).replace("\\", "/"))
        provenance = _provenance(props)
        if is_strata:
            provenance.update({"health." + key: value for key, value in _provenance(health, limit=8).items()})
            if health.get("family"):
                provenance["health.family"] = str(health["family"])[:80]
        if provenance:
            info["server_props"] = provenance
        info["loaded_models"] = list(info["models"])
        return info
    return info


def refresh(root: str, runtime: Dict[str, Any], api_key: Optional[str] = None) -> None:
    """Re-read load state after the warm-up request.

    LM Studio and Ollama load a model on first use, so the context window it was loaded
    with is only visible afterwards.
    """
    fresh = detect(root, api_key=api_key)
    for key in ("lmstudio_models", "ollama_running", "loaded_models", "context_tokens", "server_props", "slots", "model_file", "version"):
        if fresh.get(key) is not None:
            runtime[key] = fresh[key]


def chat_models(runtime: Dict[str, Any], key: str = "models") -> List[str]:
    """Listed (or, with key="loaded_models", loaded) models that are not embedding models."""
    return [str(m) for m in runtime.get(key) or [] if not EMBEDDING_HINT.search(str(m))]


def resolve_model(runtime: Dict[str, Any], wanted: str) -> str:
    """Turn the name a user typed into the id the server expects.

    ``doctor`` prints file-path ids as bare file names. Typing that name must still work,
    so a name that matches exactly one listed model by its public form is mapped back.
    """
    listed = [str(m) for m in list(runtime.get("models") or []) + list(runtime.get("loaded_models") or [])]
    if wanted in listed or not listed:
        return wanted
    matches = sorted({m for m in listed if public_model_id(m) == wanted})
    return matches[0] if len(matches) == 1 else wanted


def choose_model(runtime: Dict[str, Any]) -> Optional[str]:
    """Pick the model when the choice is unambiguous."""
    loaded = chat_models(runtime, "loaded_models")
    if len(loaded) == 1:
        return loaded[0]
    candidates = chat_models(runtime)
    if len(candidates) == 1:
        return candidates[0]
    return None


NO_MODEL_HINTS = {
    "lmstudio": "download one in LM Studio (Discover tab, or `lms get <model>`)",
    "ollama": "download one with `ollama pull <model>`",
    "llama.cpp": "start llama-server with -m <model file>",
    "strata": "install a model in Strata and start its profile",
}


def model_choice_problem(runtime: Dict[str, Any]) -> str:
    """Why no model could be chosen automatically, in words that say what to do next."""
    loaded, candidates = chat_models(runtime, "loaded_models"), chat_models(runtime)
    if not candidates and not loaded:
        hint = NO_MODEL_HINTS.get(str(runtime.get("name")), "load one in the runtime")
        only = " (it lists only embedding models)" if runtime.get("models") else ""
        return "the server lists no chat model%s: %s, or pass --model with the name the server expects" % (only, hint)
    several = loaded if len(loaded) > 1 else candidates
    names = ", ".join(public_model_id(m) for m in several[:12]) + (" ..." if len(several) > 12 else "")
    return "more than one model is %s; pass --model with one of: %s" % ("loaded" if len(loaded) > 1 else "available", names)


def enrich_model(root: str, runtime: Dict[str, Any], model: str, api_key: Optional[str] = None, timeout: float = 6.0) -> None:
    """Add model metadata and the loaded context window when the runtime exposes them."""
    details: Dict[str, Any] = {}
    name = runtime.get("name")
    if name == "lmstudio":
        for entry in runtime.pop("lmstudio_models", []) or []:
            if entry.get("id") == model:
                for key in ("arch", "quantization", "compatibility_type", "publisher", "state", "max_context_length", "loaded_context_length", "type"):
                    if entry.get(key) is not None:
                        details[key] = entry[key]
                if isinstance(entry.get("loaded_context_length"), int):
                    runtime["context_tokens"] = entry["loaded_context_length"]
        if details.get("compatibility_type"):
            runtime["engine"] = {"gguf": "llama.cpp", "mlx": "mlx"}.get(str(details["compatibility_type"]).lower(), details["compatibility_type"])
        # /api/v1/models lists each loaded instance with the settings it was loaded with.
        status, listing = get_json(root + "/api/v1/models", timeout=timeout, api_key=api_key)
        if status == 200 and isinstance(listing, dict):
            for entry in listing.get("models") or []:
                if not isinstance(entry, dict):
                    continue
                instances = [i for i in entry.get("loaded_instances") or [] if isinstance(i, dict)]
                if entry.get("key") != model and model not in [i.get("id") for i in instances]:
                    continue
                quant = entry.get("quantization")
                if isinstance(quant, dict):
                    details["quantization"] = quant.get("name") or details.get("quantization")
                    if quant.get("bits_per_weight") is not None:
                        details["bits_per_weight"] = quant["bits_per_weight"]
                for key in ("params_string", "format", "architecture", "size_bytes", "max_context_length"):
                    if entry.get(key) is not None:
                        details.setdefault(key, entry[key])
                chosen = next((i for i in instances if i.get("id") == model), instances[0] if instances else None)
                config = (chosen or {}).get("config") or {}
                if isinstance(config.get("context_length"), int):
                    runtime["context_tokens"] = config["context_length"]
                for key in ("parallel", "flash_attention", "eval_batch_size", "offload_kv_cache_to_gpu"):
                    if config.get(key) is not None:
                        details["loaded_" + key] = config[key]
        # The app version says little: the engine is a separately updated runtime pack whose
        # name and version LM Studio reports only inside a native chat response.
        try:
            status, reply, _ = post_json(root + "/api/v0/chat/completions", {"model": model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 2, "temperature": 0}, timeout=120.0, api_key=api_key)
        except EndpointError:
            status, reply = 0, None
        if status == 200 and isinstance(reply, dict):
            engine = reply.get("runtime")
            if isinstance(engine, dict) and engine.get("name"):
                runtime["engine"] = str(engine["name"])
                runtime["engine_version"] = str(engine.get("version") or "") or None
            info_block = reply.get("model_info")
            if isinstance(info_block, dict):
                for key in ("arch", "quant", "format", "context_length"):
                    if info_block.get(key) is not None:
                        details.setdefault(key, info_block[key])
                if not runtime.get("context_tokens") and isinstance(info_block.get("context_length"), int):
                    runtime["context_tokens"] = info_block["context_length"]
    elif name == "ollama":
        for entry in runtime.pop("ollama_running", []) or []:
            if model in (entry.get("name"), entry.get("model")):
                if isinstance(entry.get("context_length"), int):
                    runtime["context_tokens"] = entry["context_length"]
                size, vram = entry.get("size"), entry.get("size_vram")
                if isinstance(size, int) and size > 0 and isinstance(vram, int):
                    details["gpu_fraction"] = round(vram / size, 3)
                for key in ("parameter_size", "quantization_level", "family", "format"):
                    value = (entry.get("details") or {}).get(key)
                    if value:
                        details[key] = value
        if not details:
            try:
                status, shown, _ = post_json(root + "/api/show", {"model": model}, timeout=timeout, api_key=api_key)
            except EndpointError:
                status, shown = 0, None
            if status == 200 and isinstance(shown, dict):
                for key in ("parameter_size", "quantization_level", "family", "format"):
                    value = (shown.get("details") or {}).get(key)
                    if value:
                        details[key] = value
    elif name == "llama.cpp":
        status, body = get_json(root + "/v1/models", timeout=timeout, api_key=api_key)
        if status == 200 and isinstance(body, dict):
            for entry in body.get("data") or []:
                meta = entry.get("meta") if isinstance(entry, dict) else None
                if isinstance(meta, dict):
                    for key in ("n_params", "size", "n_ctx_train", "n_vocab"):
                        if meta.get(key) is not None:
                            details[key] = meta[key]
        if runtime.get("model_file"):
            details["file"] = runtime["model_file"]
    runtime["model_details"] = details or None


USUAL_PORTS = ((8080, "Strata or older llama.cpp"), (9931, "llama.cpp"), (1234, "LM Studio or Bionic"), (11434, "Ollama"), (8000, "vLLM"), (8081, "MLX-LM"))


def probe_ports(api_key: Optional[str] = None, timeout: float = 1.0) -> List[Dict[str, Any]]:
    """Look for local runtimes on their usual ports (used by ``doctor`` and by ``run`` without --url).

    The ports are asked at the same time, because a closed port takes about two seconds to
    say no on Windows. The key is not sent while looking: whatever happens to listen on
    8000 or 8080 has no business seeing it. A port that answers "key required" is asked
    again with the key.
    """
    # llama-server moved its default port from 8080 to 9931 in October 2026; Strata and
    # llama.cpp's Docker images still use 8080.
    results: Dict[int, Dict[str, Any]] = {}

    def look(port: int, hint: str) -> None:
        root = "http://127.0.0.1:%d" % port
        info = detect(root, timeout=timeout)
        if api_key and info.get("models_status") in (401, 403):
            info = detect(root, api_key=api_key, timeout=timeout)
        info["root"], info["usual_owner"] = root, hint
        results[port] = info

    threads = [threading.Thread(target=look, args=item, daemon=True) for item in USUAL_PORTS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=6 * timeout + 5)
    return [results[port] for port, _ in USUAL_PORTS if port in results and (results[port].get("reachable") or results[port].get("models_status"))]


# ------------------------------------------------------------- Strata engine log

# Timing rows written by the Strata engine once a generation pass finishes, for example:
#   prompt 4494 tokens = 0 reused + 4494 read in 5202 ms (863.8 tok/s), 50 generated in 1875 ms (26.66 tok/s)
ENGINE_ROW = re.compile(
    r"prompt\s+(?P<prompt>\d+)\s+tokens\s+=\s+(?P<reused>\d+)\s+reused\s+\+\s+(?P<read>\d+)\s+read\s+in\s+(?P<prefill_ms>\d+)\s+ms"
    r"\s+\([\d.]+\s+tok/s\),\s+(?P<generated>\d+)\s+generated\s+in\s+(?P<decode_ms>\d+)\s+ms"
)


def engine_log_mark(path: Optional[str]) -> Optional[int]:
    """Remember where the log ends before a request is sent."""
    if not path:
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def parse_engine_rows(text: str) -> List[Dict[str, int]]:
    return [{key: int(value) for key, value in match.groupdict().items()} for match in ENGINE_ROW.finditer(text)]


def chain_rows(rows: List[Dict[str, int]], prompt_tokens: Optional[int]) -> List[Dict[str, int]]:
    """Keep only the rows that belong to one request.

    The first row must describe the prompt the API reported. Each later row must continue
    it: its prompt is the previous prompt plus what was generated and read since. A row
    from any other client breaks the chain and is dropped along with everything after it.
    """
    kept: List[Dict[str, int]] = []
    for row in rows:
        if not kept:
            if prompt_tokens and abs(row["prompt"] - prompt_tokens) > max(8, 0.01 * prompt_tokens):
                continue  # not ours; keep looking for the row that starts this request
            kept.append(row)
        elif row["prompt"] == kept[-1]["prompt"] + kept[-1]["generated"] + row["read"]:
            kept.append(row)
        else:
            break
    return kept


def engine_log_timings(path: Optional[str], mark: Optional[int], prompt_tokens: Optional[int], completion_tokens: Optional[int] = None, wait_s: float = 6.0) -> Optional[Dict[str, Any]]:
    """Read the timing rows the engine wrote for the request that just finished.

    Returns a ``timings`` dict in the llama.cpp shape so the rest of the tool treats it like
    any other engine report. Differences from the v1 parser:

    * Prefill uses the FIRST pass only. The engine may run a second internal pass that reads
      a handful of tokens in a few hundred milliseconds; folding that into the rate (as v1
      did) understates prefill by 0.3 to 5%.
    * Rows are tied to the request: the first must match the prompt size the API reported
      and later ones must chain from it, so another client's request is never summed in.
    * It waits until the rows account for every token the API billed (generated tokens plus
      tokens re-read between passes), not for a fixed quiet period.
    """
    if not path or mark is None:
        return None
    deadline = time.monotonic() + wait_s
    rows: List[Dict[str, int]] = []
    last_change = time.monotonic()
    seen = 0
    while time.monotonic() < deadline:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(mark)
                rows = chain_rows(parse_engine_rows(handle.read()), prompt_tokens)
        except OSError:
            return None
        accounted = sum(row["generated"] for row in rows) + sum(row["read"] for row in rows[1:])
        if rows and completion_tokens and accounted >= completion_tokens:
            break
        if len(rows) != seen:
            seen, last_change = len(rows), time.monotonic()
        elif rows and not completion_tokens and time.monotonic() - last_change >= 0.5:
            break
        time.sleep(0.1)
    if not rows:
        return None
    first = rows[0]
    generated = sum(row["generated"] for row in rows)
    decode_ms = sum(row["decode_ms"] for row in rows)
    return {
        "source": "strata-engine-log",
        "passes": len(rows),
        "cache_n": first["reused"],
        "prompt_n": first["read"],
        "prompt_ms": float(first["prefill_ms"]),
        "predicted_n": generated,
        "predicted_ms": float(decode_ms),
        "all_passes_read": sum(row["read"] for row in rows),
        "all_passes_prefill_ms": sum(row["prefill_ms"] for row in rows),
        "between_pass_tokens": sum(row["read"] for row in rows[1:]),
        # Time the engine spent re-reading between generation passes. The reader of the
        # answer waits through it, but it is in neither the reading nor the writing rate.
        "between_pass_ms": float(sum(row["prefill_ms"] for row in rows[1:])),
    }
