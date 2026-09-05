# -*- coding: utf-8 -*-
"""공통: 호스트 프로필(무엇으로 쟀나), 시각, 통계, 결과 파일 I/O."""
from __future__ import annotations
import datetime
import json
import os
import platform
import statistics
import subprocess

DATA_DIR = "data/measurements"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.date.today().isoformat()


def median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 1) if xs else None


def _linux_cpu_ram():
    cpu, ram_gb = "", None
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="replace"):
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
        for line in open("/proc/meminfo", encoding="utf-8", errors="replace"):
            if line.startswith("MemTotal"):
                ram_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
                break
    except OSError:
        pass
    return cpu, ram_gb


def _windows_cpu_ram():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$c=Get-CimInstance Win32_Processor; $o=Get-CimInstance Win32_OperatingSystem; "
             "Write-Output ($c.Name.Trim() + '|' + [math]::Round($o.TotalVisibleMemorySize/1MB,1))"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        cpu, ram = out.split("|")
        return cpu, float(ram)
    except Exception:
        return platform.processor(), None


def host_profile(role: str) -> dict:
    """role: config/measure.yaml hosts 의 키(seoul-vps · windows-laptop). 값은 사실만 — 프로필 문장은 config 가 든다."""
    if os.name == "nt":
        cpu, ram = _windows_cpu_ram()
        osname = f"{platform.system()} {platform.release()} ({platform.version()})"
    else:
        cpu, ram = _linux_cpu_ram()
        osname = platform.platform()
    return {"role": role, "os": osname, "cpu": cpu, "ram_gb": ram, "cores": os.cpu_count(),
            "python": platform.python_version(), "measured_at": now_iso(), "date": today()}


def result_path(suite: str, role: str) -> str:
    return os.path.join(DATA_DIR, f"{suite}.{role}.json")


def save(suite: str, role: str, payload: dict) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    p = result_path(suite, role)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return p


def load_all() -> dict:
    """{suite: {role: payload}} — 있는 파일만."""
    out: dict = {}
    if not os.path.isdir(DATA_DIR):
        return out
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".json") or fn.count(".") < 2:
            continue
        suite, role = fn[:-5].split(".", 1)
        try:
            with open(os.path.join(DATA_DIR, fn), encoding="utf-8") as f:
                out.setdefault(suite, {})[role] = json.load(f)
        except (OSError, ValueError):
            continue
    return out
