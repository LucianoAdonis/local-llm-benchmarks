"""Cross-platform system information and light telemetry, without admin rights.

Everything here is best-effort: a missing tool or a slow command yields a missing field,
never a crash. Nothing identifying is collected: no hostname, user name, serial number,
MAC address or file path.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

_TIMEOUT_S = 12


# Absolute paths for the macOS tools: a PATH that puts another sysctl or pmset first (a
# Homebrew or Nix shell) must not change what is read.
_MAC_TOOLS = {"sysctl": "/usr/sbin/sysctl", "pmset": "/usr/bin/pmset", "system_profiler": "/usr/sbin/system_profiler", "vm_stat": "/usr/bin/vm_stat"}


def _run(command: List[str], timeout: float = _TIMEOUT_S, encoding: Optional[str] = None) -> Optional[str]:
    """Run a command and return its output, or None. Output is parsed, so it is asked for
    in English with plain number formats (LC_ALL=C): a German macOS would otherwise print
    decimal commas and translated words."""
    env = None
    if os.name != "nt":
        env = dict(os.environ, LC_ALL="C", LANG="C")
        tool = _MAC_TOOLS.get(command[0]) if sys.platform == "darwin" else None
        if tool and os.path.exists(tool):
            command = [tool] + list(command[1:])
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, errors="replace", env=env, encoding=encoding)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def _to_float(text: Optional[str]) -> Optional[float]:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------- NVIDIA

_NVIDIA_FIELDS = ["name", "driver_version", "memory.total", "memory.used", "temperature.gpu", "power.draw", "power.limit", "utilization.gpu"]
_NVIDIA_SAMPLE_FIELDS = ["temperature.gpu", "power.draw", "utilization.gpu", "memory.used"]


def nvidia_gpus() -> List[Dict[str, Any]]:
    if not shutil.which("nvidia-smi"):
        return []
    out = _run(["nvidia-smi", "--query-gpu=" + ",".join(_NVIDIA_FIELDS), "--format=csv,noheader,nounits"])
    gpus = []
    for line in (out or "").strip().splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) != len(_NVIDIA_FIELDS):
            continue
        gpus.append(
            {
                "name": cells[0],
                "driver": cells[1],
                "vram_total_mb": _to_float(cells[2]),
                "vram_used_mb": _to_float(cells[3]),
                "temperature_c": _to_float(cells[4]),
                "power_w": _to_float(cells[5]),
                "power_limit_w": _to_float(cells[6]),
                "utilization_pct": _to_float(cells[7]),
            }
        )
    return gpus


def nvidia_compute_apps() -> Optional[int]:
    """How many processes currently hold GPU memory (names are not recorded)."""
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"])
    if out is None:
        return None
    return len([line for line in out.splitlines() if line.strip()])


class GpuSampler:
    """Samples the first NVIDIA GPU once a second while a scenario runs.

    Reports min/mean/max so a result can show thermal or power throttling and a full VRAM
    (the usual sign that Windows has spilled the model into shared system memory).
    """

    def __init__(self) -> None:
        self.available = bool(shutil.which("nvidia-smi"))
        self.samples: List[List[Optional[float]]] = []
        self.proc: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.available:
            return
        self.samples = []
        try:
            self.proc = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=" + ",".join(_NVIDIA_SAMPLE_FIELDS), "--format=csv,noheader,nounits", "-i", "0", "-l", "1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace",
            )
        except OSError:
            self.proc = None
            return
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            cells = [c.strip() for c in line.split(",")]
            if len(cells) == len(_NVIDIA_SAMPLE_FIELDS):
                self.samples.append([_to_float(c) for c in cells])

    def stop(self) -> Optional[Dict[str, Any]]:
        if self.proc is None:
            return None
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        if self.thread:
            self.thread.join(timeout=2)
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc = None
        if not self.samples:
            return None
        summary: Dict[str, Any] = {"samples": len(self.samples)}
        for index, field in enumerate(("temperature_c", "power_w", "utilization_pct", "vram_used_mb")):
            values = [row[index] for row in self.samples if row[index] is not None]
            if values:
                summary[field] = {"min": min(values), "mean": round(sum(values) / len(values), 1), "max": max(values)}
        return summary


# -------------------------------------------------------------------------- macOS


def _sysctl(*keys: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for key in keys:
        out = _run(["sysctl", "-n", key], timeout=4)
        if out is not None and out.strip():
            values[key] = out.strip()
    return values


def _mac_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    ctl = _sysctl("machdep.cpu.brand_string", "hw.memsize", "hw.physicalcpu", "hw.perflevel0.physicalcpu", "hw.perflevel1.physicalcpu", "hw.model")
    info["cpu"] = ctl.get("machdep.cpu.brand_string")
    if ctl.get("hw.memsize"):
        info["ram_gb"] = round(int(ctl["hw.memsize"]) / 1024**3, 1)
    info["cpu_cores"] = _to_float(ctl.get("hw.physicalcpu"))
    info["performance_cores"] = _to_float(ctl.get("hw.perflevel0.physicalcpu"))
    info["efficiency_cores"] = _to_float(ctl.get("hw.perflevel1.physicalcpu"))
    info["machine_model"] = ctl.get("hw.model")
    version = _run(["sw_vers", "-productVersion"], timeout=4)
    info["os"] = "macOS %s" % version.strip() if version else "macOS"
    displays = _run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=20)
    gpus = []
    try:
        for entry in json.loads(displays or "{}").get("SPDisplaysDataType", []):
            gpus.append({"name": entry.get("sppci_model") or entry.get("_name"), "cores": entry.get("sppci_cores"), "metal": str(entry.get("spdisplays_mtlgpufamilysupport") or "").replace("spdisplays_metal", "Metal ") or None})
    except ValueError:
        pass
    info["gpus"] = gpus
    # Apple Silicon shares one memory pool between CPU and GPU.
    info["unified_memory"] = platform.machine() == "arm64"
    return info


def _mac_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    battery = _run(["pmset", "-g", "batt"], timeout=4) or ""
    if "AC Power" in battery:
        state["power_source"] = "ac"
    elif "Battery Power" in battery:
        state["power_source"] = "battery"
    settings = _run(["pmset", "-g"], timeout=4) or ""
    match = re.search(r"lowpowermode\s+(\d)", settings)
    if match:
        state["low_power_mode"] = match.group(1) == "1"
    match = re.search(r"\bpowermode\s+(\d)", settings)  # 0 automatic, 1 low power, 2 high power
    if match:
        state["power_mode"] = {"0": "automatic", "1": "low", "2": "high"}.get(match.group(1), match.group(1))
        if match.group(1) == "1":
            state["low_power_mode"] = True
    # 0 means macOS applies its default GPU memory budget (roughly 70 to 75% of RAM).
    limit = _run(["sysctl", "-n", "iogpu.wired_limit_mb"], timeout=4)
    if limit and limit.strip().isdigit():
        state["gpu_wired_limit_mb"] = int(limit.strip())
    therm = _run(["pmset", "-g", "therm"], timeout=4) or ""
    match = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", therm)
    if match:
        state["cpu_speed_limit_pct"] = int(match.group(1))
    swap = _run(["sysctl", "-n", "vm.swapusage"], timeout=4) or ""
    match = re.search(r"used = ([\d.]+)M", swap)
    if match:
        state["swap_used_mb"] = float(match.group(1))
    # The kernel's own verdict on memory pressure: 1 normal, 2 warning, 4 critical.
    level = _run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], timeout=4)
    if level and level.strip().isdigit():
        state["memory_pressure"] = {"1": "normal", "2": "warning", "4": "critical"}.get(level.strip(), level.strip())
    return state


# ------------------------------------------------------------------------ Windows


def _powershell(script: str, timeout: float = 25) -> Optional[str]:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    # Ask for UTF-8 explicitly: Windows PowerShell 5.1 otherwise writes in the console's
    # code page, and a GPU or disk name with a non-ASCII character comes out garbled.
    prefix = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    return _run([exe, "-NoProfile", "-NonInteractive", "-Command", prefix + script], timeout=timeout, encoding="utf-8")


def _windows_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors;"
        "$os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber;"
        "$cs=Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory;"
        "$mem=@(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed);"
        "$gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion);"
        "$disk=@(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size);"
        "[pscustomobject]@{cpu=$cpu;os=$os;cs=$cs;mem=$mem;gpu=$gpu;disk=$disk} | ConvertTo-Json -Depth 4 -Compress"
    )
    try:
        data = json.loads(_powershell(script) or "{}")
    except ValueError:
        data = {}
    cpu, os_info = data.get("cpu") or {}, data.get("os") or {}
    info["cpu"] = (cpu.get("Name") or "").strip() or None
    info["cpu_cores"] = cpu.get("NumberOfCores")
    info["cpu_threads"] = cpu.get("NumberOfLogicalProcessors")
    info["os"] = ("%s (build %s)" % (os_info.get("Caption"), os_info.get("BuildNumber"))) if os_info.get("Caption") else "Windows"
    total = (data.get("cs") or {}).get("TotalPhysicalMemory")
    if total:
        info["ram_gb"] = round(int(total) / 1024**3, 1)
    modules = [m for m in (data.get("mem") or []) if isinstance(m, dict)]
    if modules:
        info["ram_modules"] = len(modules)
        info["ram_speed_mhz"] = max((m.get("ConfiguredClockSpeed") or m.get("Speed") or 0) for m in modules) or None
    info["gpus"] = [{"name": g.get("Name"), "driver": g.get("DriverVersion")} for g in (data.get("gpu") or []) if isinstance(g, dict)]
    info["disks"] = [
        {"name": d.get("FriendlyName"), "media": d.get("MediaType"), "bus": d.get("BusType"), "size_gb": round(int(d["Size"]) / 1000**3) if d.get("Size") else None}
        for d in (data.get("disk") or []) if isinstance(d, dict)
    ]
    return info


WINDOWS_POWER_PLANS = {
    "381b4222-f694-41f0-9685-ff5bb260df2e": "Balanced",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "High performance",
    "a1841308-3541-4fab-bc81-f71556f20b4a": "Power saver",
    "e9a42b02-d5df-448d-aa00-03f14749eb61": "Ultimate Performance",
}


def _windows_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    scheme = _run(["powercfg", "/getactivescheme"], timeout=6) or ""
    # The plan's name is translated on non-English Windows; its GUID is not.
    guid = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", scheme)
    match = re.search(r"\(([^)]+)\)\s*$", scheme.strip())
    if guid and guid.group(0).lower() in WINDOWS_POWER_PLANS:
        state["power_plan"] = WINDOWS_POWER_PLANS[guid.group(0).lower()]
    elif match:
        state["power_plan"] = "custom: %s" % match.group(1)[:40]
    battery = _powershell("(Get-CimInstance Win32_Battery | Select-Object -First 1).BatteryStatus", timeout=10)
    if battery and battery.strip().isdigit():
        # 1 discharging, 4 low, 5 critical: running on the battery. 2, 3 and 6 to 11 are on mains.
        state["power_source"] = "battery" if battery.strip() in ("1", "4", "5") else "ac"
    # When VRAM overflows, the NVIDIA driver on Windows moves the excess into "shared GPU
    # memory" (ordinary RAM) instead of failing. Growth here during a run is the tell.
    # Read through the performance-counter class, not Get-Counter: counter paths are
    # translated on non-English Windows ("GPU-Adapterspeicher" on German systems).
    shared = _powershell(
        "$ErrorActionPreference='SilentlyContinue';"
        "(@(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory) | Measure-Object -Property SharedUsage -Maximum).Maximum",
        timeout=15,
    )
    value = _to_float(shared)
    if value is not None:
        state["gpu_shared_memory_mb"] = round(value / 1024**2)
    return state


# -------------------------------------------------------------------------- Linux


def _linux_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {"os": platform.platform(terse=True)}
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    info["ram_gb"] = round(int(line.split()[1]) / 1024**2, 1)
                    break
    except OSError:
        pass
    info["cpu_threads"] = os.cpu_count()
    return info


def _linux_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as handle:
            fields = dict((line.split(":")[0], line.split()[1]) for line in handle if ":" in line)
        state["swap_used_mb"] = round((int(fields.get("SwapTotal", 0)) - int(fields.get("SwapFree", 0))) / 1024, 1)
        state["memory_available_mb"] = round(int(fields.get("MemAvailable", 0)) / 1024)
    except (OSError, ValueError, IndexError):
        pass
    return state


# --------------------------------------------------------------------------- public


def capture_system() -> Dict[str, Any]:
    """Static description of the machine. Safe to publish."""
    system = platform.system()
    info: Dict[str, Any] = {"platform": system, "arch": platform.machine(), "python": platform.python_version()}
    if system == "Darwin":
        info.update(_mac_info())
    elif system == "Windows":
        info.update(_windows_info())
    else:
        info.update(_linux_info())
    nvidia = nvidia_gpus()
    if nvidia:
        info["gpus"] = [{"name": g["name"], "driver": g["driver"], "vram_gb": round((g["vram_total_mb"] or 0) / 1024, 1)} for g in nvidia]
    info.setdefault("cpu_threads", os.cpu_count())
    return {key: value for key, value in info.items() if value not in (None, [], "")}


def capture_state() -> Dict[str, Any]:
    """Things that change between runs: power, thermals, memory pressure, GPU load."""
    system = platform.system()
    if system == "Darwin":
        state = _mac_state()
    elif system == "Windows":
        state = _windows_state()
    else:
        state = _linux_state()
    nvidia = nvidia_gpus()
    if nvidia:
        gpu = nvidia[0]
        state["gpu"] = {key: gpu[key] for key in ("vram_used_mb", "vram_total_mb", "temperature_c", "power_w", "power_limit_w", "utilization_pct")}
        apps = nvidia_compute_apps()
        if apps is not None:
            state["gpu_compute_processes"] = apps
    return state


def preflight_warnings(system: Dict[str, Any], state: Dict[str, Any]) -> List[str]:
    """Conditions that make a result unrepresentative. Shown before a run and stored."""
    warnings: List[str] = []
    if state.get("power_source") == "battery":
        warnings.append("Running on battery: most laptops limit CPU and GPU power. Plug in for comparable numbers.")
    if state.get("low_power_mode"):
        warnings.append("Low Power Mode is on: speeds will be lower than normal.")
    plan = str(state.get("power_plan") or "")
    if "saver" in plan.lower():
        warnings.append("Windows power plan is '%s': switch to Balanced or High performance." % plan)
    limit = state.get("cpu_speed_limit_pct")
    if isinstance(limit, int) and limit < 100:
        warnings.append("macOS is thermally limiting the CPU to %d%%: let the machine cool first." % limit)
    swap = state.get("swap_used_mb")
    if isinstance(swap, (int, float)) and swap > 1024:
        warnings.append("%.1f GB of swap is already in use: close apps, memory pressure slows inference badly." % (swap / 1024))
    pressure = state.get("memory_pressure")
    if pressure in ("warning", "critical"):
        warnings.append("macOS reports memory pressure '%s': close apps, or the model will be pushed into swap." % pressure)
    gpu = state.get("gpu") or {}
    if gpu.get("temperature_c") and gpu["temperature_c"] >= 80:
        warnings.append("GPU is already at %.0f C before the run." % gpu["temperature_c"])
    if gpu.get("vram_total_mb") and gpu.get("vram_used_mb") and gpu["vram_used_mb"] >= 0.97 * gpu["vram_total_mb"]:
        warnings.append("VRAM is %.0f%% full: on Windows the driver may be spilling into slower shared memory." % (100.0 * gpu["vram_used_mb"] / gpu["vram_total_mb"]))
    return warnings


def describe(system: Dict[str, Any]) -> str:
    """One line for terminal output and reports."""
    parts = [str(system.get("os") or system.get("platform") or sys.platform)]
    cpu = str(system.get("cpu") or "")
    for gpu in system.get("gpus") or []:
        name = gpu.get("name")
        if name and name == cpu and gpu.get("cores"):  # Apple Silicon: the GPU is part of the chip
            cpu = "%s (%s-core GPU)" % (cpu, gpu["cores"])
    if cpu:
        parts.append(cpu)
    for gpu in system.get("gpus") or []:
        name = gpu.get("name")
        if name and name != system.get("cpu"):
            parts.append("%s%s" % (name, (" %.0f GB" % gpu["vram_gb"]) if gpu.get("vram_gb") else ""))
    if system.get("ram_gb"):
        parts.append("%.0f GB RAM%s" % (system["ram_gb"], " (unified)" if system.get("unified_memory") else ""))
    return " | ".join(parts)
