"""Command-line interface: ``python -m llmbench <command>``.

Output is plain ASCII so it renders the same in Windows PowerShell, cmd and macOS Terminal.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import PROTOCOL_VERSION, WORKLOAD_VERSION, __version__
from . import report, runtimes, sysinfo
from .bench import DEPTH_CLASSES, SUITE_NAMES, Bench, build_suite, default_output_path, depth_target, followup_target
from .catalog import MODELS, find_model
from .client import EndpointError, clean_api_key, split_base_url
from .sanitize import clean, read_json, register_secret, residue, sanitize_file, write_json

START_HINTS = (
    "No local runtime answered on the usual ports. Start one, then retry:",
    "  LM Studio : open the app (Developer tab > Start server) or run: lms server start      -> http://127.0.0.1:1234",
    "  Ollama    : ollama serve                                                              -> http://127.0.0.1:11434",
    "  llama.cpp : llama-server -m model.gguf -c 32768 -np 1                                 -> http://127.0.0.1:9931 (8080 on builds before October 2026)",
    "  Strata    : strata launch (or start a saved profile)                                  -> http://127.0.0.1:8080",
    "Or pass the address yourself with --url, e.g. --url http://127.0.0.1:1234",
)


class CliError(Exception):
    """A problem with what the user passed: printed as one line, exit status 2."""


def _load(path: str, what: str = "file") -> Any:
    try:
        return read_json(Path(path))
    except FileNotFoundError:
        raise CliError("%s not found: %s" % (what, path)) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError("cannot read %s %s: %s" % (what, path, getattr(exc, "strerror", None) or exc)) from None
    except ValueError as exc:
        raise CliError("%s %s is not valid JSON: %s" % (what, path, exc)) from None


def _load_result(path: str) -> Dict[str, Any]:
    result = _load(path, "result file")
    if not isinstance(result, dict) or not str(result.get("schema", "")).startswith("llmbench-result/"):
        raise CliError("%s is not an llmbench result file." % path)
    return result


def _api_key(args: argparse.Namespace) -> Optional[str]:
    """The key from the named environment variable, cleaned, and remembered for redaction."""
    if not args.api_key_env:
        return None
    raw = os.environ.get(args.api_key_env)
    if raw is None:
        raise CliError("the environment variable %s is not set" % args.api_key_env)
    try:
        key = clean_api_key(raw, "the environment variable %s" % args.api_key_env)
    except EndpointError as exc:
        raise CliError(str(exc)) from None
    register_secret(key)
    return key


def _root(url: str) -> str:
    try:
        return split_base_url(url)[0]
    except EndpointError as exc:
        raise CliError("--url %s" % exc) from None


def _resolve_url(args: argparse.Namespace, api_key: Optional[str]) -> Optional[str]:
    if args.url:
        return _root(args.url)
    found = runtimes.probe_ports(api_key=api_key)
    if len(found) == 1:
        print("Found %s at %s" % (runtimes.display_name(found[0]["name"]), found[0]["root"]))
        return found[0]["root"]
    if not found:
        print("\n".join(START_HINTS))
        return None
    print("More than one runtime is running. Pick one with --url:")
    for item in found:
        print("  %-22s %s" % (item["root"], runtimes.display_name(item["name"])))
    return None


def _command() -> str:
    """How this tool is started on this system, for the hints it prints."""
    return "%s -m llmbench" % ("py" if os.name == "nt" else "python3")


def _megabytes(value: Any) -> str:
    return "{:,.0f} MB".format(value)


# What `doctor` prints about the machine's current state, in words instead of field names.
STATE_LINES = (
    ("power_source", "Power source", lambda v: {"ac": "mains", "battery": "battery"}.get(v, str(v))),
    ("power_plan", "Windows power plan", str),
    ("power_mode", "macOS power mode", str),
    ("low_power_mode", "Low Power Mode", lambda v: "on" if v else "off"),
    ("cpu_speed_limit_pct", "CPU speed limit (heat)", lambda v: "%d%%" % v),
    ("memory_pressure", "Memory pressure", str),
    ("swap_used_mb", "Swap in use", _megabytes),
    ("memory_available_mb", "Memory available", _megabytes),
    ("gpu_wired_limit_mb", "GPU memory limit", lambda v: _megabytes(v) + " (set by hand)" if v else "macOS default (roughly two thirds to three quarters of memory)"),
    ("gpu_shared_memory_mb", "Shared GPU memory in use", _megabytes),
    ("gpu_compute_processes", "Programs using the GPU", str),
)


def cmd_doctor(args: argparse.Namespace) -> int:
    api_key = _api_key(args)
    root = _root(args.url) if args.url else None
    system = sysinfo.capture_system()
    state = sysinfo.capture_state()
    print("llmbench %s (protocol %s, workload %s)" % (__version__, PROTOCOL_VERSION, WORKLOAD_VERSION))
    print("System : %s" % sysinfo.describe(system))
    for key, label, show in STATE_LINES:
        if key in state:
            print("  %-26s %s" % (label, show(state[key])))
    gpu = state.get("gpu") or {}
    if gpu:
        print("  %-26s %s of %s in use, %s C, %s W" % ("GPU memory (VRAM)", _megabytes(gpu.get("vram_used_mb") or 0), _megabytes(gpu.get("vram_total_mb") or 0), gpu.get("temperature_c"), gpu.get("power_w")))
    elif not system.get("unified_memory"):
        print("  %-26s not readable here (only NVIDIA cards report it to this tool); use Task Manager or your GPU vendor's tool" % "GPU memory (VRAM)")
    warnings = sysinfo.preflight_warnings(system, state)
    for warning in warnings:
        print("WARNING: %s" % warning)
    if not warnings:
        print("No power, thermal or memory warnings.")
    print("")
    found = [dict(runtimes.detect(root, api_key=api_key), root=root)] if root else runtimes.probe_ports(api_key=api_key)
    found = [item for item in found if item.get("reachable")]
    if not found:
        print("\n".join(START_HINTS) if not root else "Nothing answered at %s." % root)
        return 1
    for item in found:
        print("Runtime: %s%s at %s" % (runtimes.display_name(item["name"]), (" " + str(item["version"])) if item.get("version") else "", item["root"]))
        models = [runtimes.public_model_id(m) for m in item.get("models") or []]
        loaded = [runtimes.public_model_id(m) for m in item.get("loaded_models") or []]
        print("  models : %s" % (", ".join(models[:12]) + (" ..." if len(models) > 12 else "") if models else "none listed"))
        print("  loaded : %s" % (", ".join(loaded) if loaded else "none (the runtime may load on first request)"))
        if item.get("context_tokens"):
            print("  context: {:,} tokens".format(item["context_tokens"]))
        else:
            print("  context: not reported by this runtime; pass --context to `llmbench run`")
    print("")
    ready = [item for item in found if runtimes.chat_models(item) or runtimes.chat_models(item, "loaded_models")]
    if not ready:
        for item in found:
            print("Not ready: %s at %s: %s." % (runtimes.display_name(item["name"]), item["root"], runtimes.model_choice_problem(item)))
        return 1
    print("Next: %s run --suite quick%s" % (_command(), "" if len(ready) == 1 and len(found) == 1 else " --url <one of the addresses above>"))
    return 0


def _extra_body(args: argparse.Namespace) -> Dict[str, Any]:
    extra: Dict[str, Any] = {}
    sources = []
    if args.extra_body_file:
        sources.append(("--extra-body-file", _load(args.extra_body_file, "--extra-body-file")))
    if args.extra_body:
        try:
            sources.append(("--extra-body", json.loads(args.extra_body)))
        except ValueError as exc:
            raise CliError("--extra-body is not valid JSON: %s" % exc) from None
    for name, value in sources:
        if not isinstance(value, dict):
            raise CliError("%s must be a JSON object, like {\"top_k\": 40}" % name)
        extra.update(value)
    return extra


def _writable_folder(folder: Path) -> None:
    """Fail before a 40-minute run, not after it, when results cannot be saved."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / (".llmbench-write-test-%d" % os.getpid())
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise CliError("cannot save results in %s: %s (pick another place with --output, or use --no-save)" % (folder, exc.strerror or exc)) from None


def cmd_run(args: argparse.Namespace) -> int:
    api_key = _api_key(args)
    extra = _extra_body(args)
    url = _resolve_url(args, api_key)
    if not url:
        return 2
    if args.output:
        partial_path = Path(args.output + ".partial.json")
    else:
        # One name per run, so two runs at once never overwrite each other's checkpoint.
        partial_path = Path("local-results", "in-progress-%s-%d.partial.json" % (dt.datetime.now().strftime("%Y%m%d-%H%M%S"), os.getpid()))
    if not args.no_save:
        _writable_folder(Path(args.output).parent if args.output else Path("local-results"))
    checkpoint_failed: List[str] = []

    def checkpoint(snapshot: Dict[str, Any]) -> None:
        if args.no_save:
            return
        try:
            write_json(partial_path, clean(snapshot))  # atomic: a reader never sees half a file
        except OSError as exc:
            # A full disk or an antivirus lock must not end the run; say so once.
            if not checkpoint_failed:
                print("note: could not save progress to %s (%s); the run continues" % (partial_path, exc.strerror or exc))
            checkpoint_failed.append(str(exc))

    try:
        bench = Bench(
            url=url, model=args.model, suite=args.suite, context=args.context, corpus=args.corpus, runs=args.runs,
            depths=[d.strip().lower() for d in args.depths.split(",")] if args.depths else None,
            only=[s.strip() for s in args.scenarios.split(",")] if args.scenarios else None,
            api_key=api_key, timeout=args.timeout, extra_body=extra, label=args.label, seed=args.seed,
            engine_log=args.engine_log, cold=args.cold, thinking=args.thinking, soak_minutes=args.soak_minutes,
            size_warmup=not args.no_size_warmup, checkpoint=checkpoint, fixed_text=args.fixed_text,
        )
        result = bench.run()
    except (EndpointError, ValueError) as exc:
        print("Cannot run: %s" % clean(str(exc)))
        return 2
    public = clean(result)  # what is saved is what is shown
    status = 0 if result["verdict"]["status"] != "invalid" else 1
    if args.no_save:
        print(report.terminal(public))
        return status
    output = Path(args.output or default_output_path(public))
    if output.exists() and not args.force:
        output = output.with_name("%s-%d%s" % (output.stem, int(time.time()), output.suffix))
    saved = True
    try:
        write_json(output, public)  # save first: printing can fail on a closed console
    except OSError as exc:
        saved = False
        print("Could not save %s (%s). The checkpoint %s holds the results up to the last finished scenario." % (output, exc.strerror or exc, partial_path))
    print(report.terminal(public))
    if not saved:
        return 2
    try:
        if partial_path.exists():
            partial_path.unlink()  # the complete file supersedes this run's checkpoint
    except OSError:
        pass
    print("\nSaved: %s" % output)
    print("Markdown summary: %s report --markdown %s" % (_command(), output))
    return status


def cmd_report(args: argparse.Namespace) -> int:
    for path in _expand(args.files):
        result = _load_result(path)
        print(report.markdown(result) if args.markdown else report.terminal(result))
    return 0


def _config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "llmbench" / "config.json"


def _config() -> Dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    data = _load(str(path), "llmbench config")
    if not isinstance(data, dict):
        raise CliError("llmbench config must be a JSON object: %s" % path)
    return data


def cmd_config(args: argparse.Namespace) -> int:
    path = _config_path()
    config = _config()
    if args.config_command == "show":
        print("Config: %s" % path)
        print(json.dumps(config or {"download_dir": "(not set; default: ./models)"}, indent=2))
        return 0
    if args.key != "download-dir":
        raise CliError("unknown setting %r (available: download-dir)" % args.key)
    folder = Path(args.value).expanduser().resolve()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / (".llmbench-write-test-%d" % os.getpid())
        probe.write_bytes(b"")
        probe.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        config["download_dir"] = str(folder)
        write_json(path, config)
    except OSError as exc:
        raise CliError("cannot use %s: %s" % (folder, exc.strerror or exc)) from None
    print("Model download directory set to: %s" % folder)
    print("Config saved at: %s" % path)
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Check dependencies and print targeted setup steps; never installs silently."""
    checks = [
        ("Python 3.9+", sys.version_info >= (3, 9), sys.executable),
        ("uv", shutil.which("uv") is not None, "brew install uv" if sys.platform == "darwin" else "https://docs.astral.sh/uv/getting-started/installation/"),
        ("Homebrew", shutil.which("brew") is not None, "https://brew.sh/" if sys.platform == "darwin" else "macOS only"),
        ("Strata", shutil.which("strata") is not None, "https://github.com/Niko1221/Strata/releases"),
        ("LM Studio CLI (lms)", shutil.which("lms") is not None, "Install/open LM Studio, then enable its CLI in the app"),
        ("Hugging Face downloader", shutil.which("hf") is not None, "uv tool install --force --with huggingface_hub git+https://github.com/LucianoAdonis/local-llm-benchmarks.git"),
    ]
    print("llmbench setup: dependency and runtime check\n")
    for label, found, action in checks:
        print("%-27s %s" % (label, "ready" if found else "not found"))
        if not found:
            print("  Next: %s" % action)
    print("\nOptional macOS installs:")
    print("  Strata: curl -fsSL --connect-timeout 15 --max-time 120 https://github.com/Niko1221/Strata/releases/latest/download/install.sh -o install.sh && sh install.sh; then `strata launch`.")
    print("  llama.cpp: brew install llama.cpp")
    print("  LM Studio/Bionic: https://lmstudio.ai/download ; choose its model folder in My Models.")
    print("\nModel files stay where you choose. Set the default destination with:")
    print("  llmbench config set download-dir /Volumes/ModelSSD/llm-models")
    print("Review model licences, free disk space and download size before pulling. Strata's managed packs should be installed through `strata launch`.")
    return 0 if sys.version_info >= (3, 9) else 1


def cmd_models(args: argparse.Namespace) -> int:
    if args.models_command == "list":
        print("Starter GGUF catalog (Hugging Face download snapshot: 2026-11-25; counts are popularity signals, not quality scores):")
        for model in MODELS:
            print("\n%-22s %s" % (model["id"], model["name"]))
            print("  Tier: %s | Parameters: %s | Download: %s | Hub downloads: %s (snapshot)" % (model["tier"], model["params"], model["size"], format(model["downloads"], ",")))
            print("  %s" % model["note"])
            print("  %s" % model["url"])
        print("\nPull an entry with `llmbench models pull ID`; choose a custom destination with --dir.")
        return 0
    try:
        model = find_model(args.model_id)
    except KeyError:
        raise CliError("unknown model id %r; run `llmbench models list`" % args.model_id) from None
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise CliError("model downloads need the optional Hugging Face client. Install it with `uv tool install --force --with huggingface_hub git+https://github.com/LucianoAdonis/local-llm-benchmarks.git` and reopen the terminal.") from None
    config = _config()
    folder = Path(args.directory or config.get("download_dir") or "models").expanduser().resolve()
    target = folder / model["id"]
    try:
        folder.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(folder).free
    except OSError as exc:
        raise CliError("cannot access download directory %s: %s" % (folder, exc.strerror or exc)) from None
    required_bytes = int(model["bytes"] * 1.10) + 2_000_000_000
    print("Free space on destination: %.1f GB" % (free_bytes / 1_000_000_000))
    if free_bytes < required_bytes:
        raise CliError("not enough free disk space for %s: allow at least %.1f GB here (including download headroom); choose another path with --dir or config set download-dir" % (model["name"], required_bytes / 1_000_000_000))
    print("Model: %s (%s)" % (model["name"], model["size"]))
    print("Source: %s" % model["url"])
    print("Destination: %s" % target)
    print("Hugging Face downloads use resumable cache and only the listed checkpoint file(s).")
    try:
        snapshot_download(
            repo_id=model["repo"],
            allow_patterns=model["files"],
            local_dir=str(target),
        )
    except Exception as exc:
        raise CliError("download failed: %s" % clean(str(exc))) from None
    print("\nDownload finished: %s" % target)
    print("For LM Studio/Bionic, import the GGUF file using `lms import PATH` or the app's import flow.")
    print("For Strata, use its guided model setup unless its current model catalog explicitly supports this GGUF.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    result = _load_result(args.result)
    formats = {
        "json": (".json", json.dumps(result, indent=2, ensure_ascii=False) + "\n"),
        "markdown": (".md", report.markdown(result)),
        "csv": (".csv", report.csv(result)),
    }
    suffix, contents = formats[args.format]
    output = Path(args.output) if args.output else Path(args.result).with_suffix(suffix)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(contents.encode("utf-8"))
    except OSError as exc:
        raise CliError("could not write %s: %s" % (output, exc.strerror or exc)) from None
    print("Exported %s" % output)
    if args.format == "json":
        print("Before sharing, review it and run `llmbench sanitize` if you want paths and local identifiers redacted.")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    text = report.compare(_load_result(args.base), _load_result(args.new))
    print(text)
    return 3 if "NOT COMPARABLE" in text else 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from .selftest import run_selftest

    return 0 if run_selftest() else 1


def cmd_mock(args: argparse.Namespace) -> int:
    from .mockserver import MockServer

    server = MockServer(
        port=args.port, prefill_tok_s=args.prefill, decode_tok_s=args.decode, overhead_ms=args.overhead_ms, chunk_tokens=args.chunk_tokens,
        reasoning_tokens=args.reasoning_tokens, reasoning_field=args.reasoning_field, reasoning_details=args.reasoning_details, cache=args.cache, cache_slots=args.cache_slots, n_ctx=args.n_ctx,
        include_timings=args.timings, include_usage=not args.no_usage,
    ).start()
    if args.announce:
        print("PORT %d" % server.port, flush=True)
    else:
        print("Mock OpenAI-compatible server on %s (read %.0f tok/s, write %.0f tok/s). Ctrl+C to stop." % (server.url, args.prefill, args.decode), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
    return 0


def cmd_sysinfo(args: argparse.Namespace) -> int:
    print(json.dumps({"system": sysinfo.capture_system(), "state": sysinfo.capture_state()}, indent=2))
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    from . import diagnostics

    results = [_load_result(path) for path in _expand(args.results)]
    diagnostic = diagnostics.build(sysinfo.capture_system(), sysinfo.capture_state(), results)
    if args.output:
        write_json(Path(args.output), diagnostic)
    else:
        print(json.dumps(diagnostic, indent=2))
    return 0


def _expand(patterns: List[str]) -> List[str]:
    """Expand wildcards here, because Windows shells pass them through unexpanded."""
    paths: List[str] = []
    for pattern in patterns:
        if any(char in pattern for char in "*?["):
            matches = sorted(glob.glob(pattern, recursive=True))
            if not matches:
                raise CliError("no file matches %s" % pattern)
            paths.extend(matches)
        else:
            paths.append(pattern)
    return paths


def cmd_sanitize(args: argparse.Namespace) -> int:
    if args.check:
        paths = _expand(args.paths)
        dirty = [path for path in paths if residue(_load(path))]
        for path in dirty:
            print("NOT CLEAN: %s still contains a path, address, identifier or key." % path)
        if not dirty:
            print("Clean: %d file(s), nothing the redactor recognises." % len(paths))
        return 1 if dirty else 0
    if len(args.paths) != 2:
        print("Usage: sanitize SOURCE DESTINATION, or sanitize --check FILE [FILE ...]")
        return 2
    _load(args.paths[0])  # a clear message for a missing or broken file
    sanitize_file(Path(args.paths[0]), Path(args.paths[1]))
    print("Wrote %s. Read it before sharing: no redactor knows every private detail." % args.paths[1])
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    for name in SUITE_NAMES if args.suite == "all" else (args.suite,):
        print("Suite %s" % name)
        for spec in build_suite(name):
            target = (followup_target if spec["kind"] == "followup" else depth_target)(spec["depth"]) if spec.get("depth") else None
            size = "about {:,} prompt tokens".format(target) if target else "short prompt"
            print("  %-14s x%d  %-74s %s, up to %d tokens out" % (spec["id"], spec["runs"], spec["title"], size, spec["max_tokens"]))
        print("")
    print("Optional, on any suite: --soak-minutes N adds 'soak' (loops a 4K read and 256-token answer, reports worst/best loop).")
    print("Depth classes: " + ", ".join("%s={:,}".format(depth_target(d)) % d for d in DEPTH_CLASSES))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    """Delegate an explicitly requested LM Studio model download to its native CLI."""
    lms = shutil.which("lms")
    if not lms:
        raise CliError("LM Studio's `lms` command was not found. Install/open LM Studio or use its Local Models screen; see docs/model-setup.md.")
    print("Starting the requested download through LM Studio's native model manager.")
    try:
        return subprocess.run([lms, "get", args.model], check=False).returncode
    except OSError as exc:
        raise CliError("could not start `lms get`: %s" % exc) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llmbench", description="Repeatable speed tests for local LLM runtimes (Strata, LM Studio, llama.cpp, Ollama and any OpenAI-compatible server).")
    parser.add_argument("--version", action="version", version="llmbench %s (protocol %s)" % (__version__, PROTOCOL_VERSION))
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="describe this machine and find running local runtimes")
    doctor.add_argument("--url", help="check one address instead of the usual local ports")
    doctor.add_argument("--api-key-env", metavar="VAR", help="environment variable that holds an API key, if your server needs one")
    doctor.set_defaults(func=cmd_doctor)

    pull = sub.add_parser("pull", help="download a Bionic/LM Studio model through its native `lms get` command")
    pull.add_argument("--backend", choices=("bionic",), default="bionic", help="model manager to use (currently LM Studio/Bionic)")
    pull.add_argument("--model", required=True, help="model name, optionally with quantization, e.g. llama-3.1-8b@q4_k_m")
    pull.set_defaults(func=cmd_pull)

    setup = sub.add_parser("setup", help="check setup prerequisites and show install steps for macOS/Windows/Linux")
    setup.set_defaults(func=cmd_setup)

    config = sub.add_parser("config", help="view or change llmbench preferences")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show", help="show saved preferences")
    config_show.set_defaults(func=cmd_config)
    config_set = config_sub.add_parser("set", help="save a preference")
    config_set.add_argument("key", help="currently: download-dir")
    config_set.add_argument("value", help="path, for example /Volumes/ModelSSD/llm-models")
    config_set.set_defaults(func=cmd_config)

    models = sub.add_parser("models", help="browse and download the curated GGUF starter models")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list", help="list small, midrange and large/offload model choices")
    models_list.set_defaults(func=cmd_models)
    model_pull = models_sub.add_parser("pull", help="download one catalog model from Hugging Face")
    model_pull.add_argument("model_id", help="id shown by `llmbench models list`")
    model_pull.add_argument("--dir", dest="directory", help="download directory (overrides saved download-dir)")
    model_pull.set_defaults(func=cmd_models)

    run = sub.add_parser("run", help="run a benchmark suite and save a result file")
    run.add_argument("--url", help="server address, e.g. http://127.0.0.1:1234 (found automatically when only one runtime is running)")
    run.add_argument("--model", help="model id as the server lists it (chosen automatically when unambiguous)")
    run.add_argument("--suite", choices=SUITE_NAMES, default="standard", help="quick (about 1 to 3 minutes), standard, or deep")
    run.add_argument("--context", type=int, help="context window the model was loaded with, in tokens (unlocks deeper scenarios)")
    run.add_argument("--depths", help="comma-separated context depths to run instead of the suite's, from: %s" % ", ".join(DEPTH_CLASSES))
    run.add_argument("--scenarios", help="comma-separated scenario ids to run (see `llmbench scenarios`)")
    run.add_argument("--runs", type=int, help="override the number of runs per scenario")
    run.add_argument("--corpus", default="diverse", help="diverse (default), repetitive (the v1 workload), or file:PATH for your own text or code")
    run.add_argument("--label", help="free text stored with the result, e.g. 'before driver update'")
    run.add_argument("--output", help="result path (default: local-results/<time>_<runtime>_<model>_<suite>.json)")
    run.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    run.add_argument("--no-save", action="store_true", help="print the result without writing a file")
    run.add_argument("--api-key-env", metavar="VAR", help="environment variable that holds an API key (never stored)")
    run.add_argument("--extra-body", help="JSON merged into every request, e.g. '{\"chat_template_kwargs\": {\"enable_thinking\": false}}'")
    run.add_argument("--extra-body-file", help="same as --extra-body but read from a JSON file (easier to quote on Windows)")
    run.add_argument("--thinking", choices=("default", "off"), default="default", help="off asks the runtime to disable model thinking (reasoning_effort none and enable_thinking false); the result shows whether it worked")
    run.add_argument("--soak-minutes", type=float, default=0.0, help="add a stability soak of this many minutes at the end (10 is a good start)")
    run.add_argument("--no-size-warmup", action="store_true", help="skip the uncounted first read made at each new prompt size (faster, but first-run effects then land in the results)")
    run.add_argument("--engine-log", help="engine log to read timings from, for engines that do not put them in the response (Strata's retired DeepSeek engine)")
    run.add_argument("--timeout", type=float, default=1800.0, help="seconds to wait for data before giving up on a request")
    run.add_argument("--cold", action="store_true", help="declare that the runtime was restarted just before this run (labels the warm-up as a cold start)")
    run.add_argument("--seed", default="llmbench", help="workload seed; keep the default to stay comparable with other machines")
    run.add_argument("--fixed-text", action="store_true", help="send exactly the same prompt text as every other run with this seed (restart the runtime first: a runtime that keeps a prompt cache would otherwise reuse the previous run's text)")
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="print a saved result")
    rep.add_argument("files", nargs="+")
    rep.add_argument("--markdown", action="store_true", help="Markdown for a README or an issue")
    rep.set_defaults(func=cmd_report)

    export = sub.add_parser("export", help="write one benchmark result as Markdown, CSV, or JSON")
    export.add_argument("result", help="saved llmbench result JSON")
    export.add_argument("--format", choices=("markdown", "csv", "json"), default="markdown")
    export.add_argument("--output", help="output path (default: same name with .md, .csv or .json)")
    export.set_defaults(func=cmd_export)

    cmp_parser = sub.add_parser("compare", help="A/B two saved results with a noise-aware verdict")
    cmp_parser.add_argument("base")
    cmp_parser.add_argument("new")
    cmp_parser.set_defaults(func=cmd_compare)

    selftest = sub.add_parser("selftest", help="verify the measuring code against a mock server with known speeds")
    selftest.set_defaults(func=cmd_selftest)

    mock = sub.add_parser("mock-server", help="run the deterministic mock server (for experiments and tests)")
    mock.add_argument("--port", type=int, default=8099)
    mock.add_argument("--prefill", type=float, default=2000.0, help="prompt tokens per second")
    mock.add_argument("--decode", type=float, default=100.0, help="generated tokens per second")
    mock.add_argument("--overhead-ms", type=float, default=20.0)
    mock.add_argument("--chunk-tokens", type=int, default=1, help="tokens per streamed event")
    mock.add_argument("--reasoning-tokens", type=int, default=0)
    mock.add_argument("--reasoning-field", default="reasoning_content", choices=("reasoning_content", "reasoning", "inline", "hidden"), help="where thinking goes; 'hidden' counts it without sending it")
    mock.add_argument("--reasoning-details", action="store_true", help="report reasoning tokens in the usage details")
    mock.add_argument("--cache", action="store_true", help="imitate a prefix cache")
    mock.add_argument("--cache-slots", type=int, default=1, help="earlier prompts remembered by the cache (slots or a RAM prompt cache)")
    mock.add_argument("--n-ctx", type=int, default=0, help="imitate a context window that silently truncates")
    mock.add_argument("--timings", action="store_true", help="attach llama.cpp-style engine timings")
    mock.add_argument("--no-usage", action="store_true")
    mock.add_argument("--announce", action="store_true", help=argparse.SUPPRESS)
    mock.set_defaults(func=cmd_mock)

    info = sub.add_parser("sysinfo", help="print the system information that would be stored with a result")
    info.set_defaults(func=cmd_sysinfo)

    diagnostic = sub.add_parser("diagnose", help="produce a machine and benchmark diagnostic as JSON")
    diagnostic.add_argument("results", nargs="*", help="optional saved benchmark JSON reports")
    diagnostic.add_argument("--output", help="write JSON to this path instead of stdout")
    diagnostic.set_defaults(func=cmd_diagnose)

    san = sub.add_parser("sanitize", help="redact paths, local addresses and secrets from a JSON file")
    san.add_argument("paths", nargs="+", metavar="FILE", help="SOURCE DESTINATION, or with --check any number of files")
    san.add_argument("--check", action="store_true", help="write nothing; exit with status 1 if any file still contains something the redactor would change")
    san.set_defaults(func=cmd_sanitize)

    scen = sub.add_parser("scenarios", help="list what each suite runs")
    scen.add_argument("--suite", default="all", choices=SUITE_NAMES + ("all",))
    scen.set_defaults(func=cmd_scenarios)
    return parser


def _tolerant_output() -> None:
    """Never let an unprintable character end a run.

    A model name, a label or a server's error message can hold characters the console's
    code page lacks. On Windows, with output redirected to a file, printing one raises
    UnicodeEncodeError; replace such characters instead.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _tolerant_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except CliError as exc:
        print("Error: %s" % exc)
        return 2
    except FileNotFoundError as exc:
        print("File not found: %s" % exc.filename)
        return 2


if __name__ == "__main__":
    sys.exit(main())
