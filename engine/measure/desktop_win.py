# -*- coding: utf-8 -*-
"""desktop_win — Windows 데스크톱 앱: 설치 용량·파일 버전·콜드 스타트(창이 보일 때까지)·유휴 메모리·스크린샷.

정의(캡션 인용용):
- footprint_mb : 설치 디렉터리 전체 용량(MB, 10^6). 사용자 데이터 디렉터리는 제외.
- cold_start_s : 프로세스 시작 → 그 프로세스 트리의 첫 가시 최상위 창까지(초). 측정 직전 같은 앱의 프로세스를 전부 종료하고
                 한 번만 잰다(디스크 캐시가 따뜻할 수 있어 '재기동' 에 가깝다 — 캡션에 그렇게 적는다).
- idle_rss_mb  : 창이 뜨고 settle 초 뒤, 프로세스 트리 RSS 합(MB). Electron 앱은 보조 프로세스가 여럿이라 트리로 센다.
- screenshot   : 창 영역만 잘라 assets/measure/<key>.webp (폭 1200 이하).
- args / fresh_profile : 앱에 넘길 인자(예: VS Code 계열의 --user-data-dir 로 빈 프로필). fresh_profile=true 면 캡션이
                 "빈 프로필·작업공간 없음" 조건임을 밝힌다 — 기존 설치본이 사용자의 작업공간을 복원하는 것을 막기 위한 것.
CLI 는 `--version` 실행 시간과 설치 디렉터리 용량만 잰다.
"""
from __future__ import annotations
import ctypes
import os
import subprocess
import time

try:
    import psutil
except ImportError:                                   # 서버(리눅스)에서 import 만 돼도 죽지 않게
    psutil = None

user32 = ctypes.windll.user32 if os.name == "nt" else None


def expand(p: str) -> str:
    return os.path.expandvars(p)


def dir_size_bytes(path: str) -> int:
    total = 0
    for root, _d, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def file_version(exe: str) -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


def _tree_pids(root_pid: int) -> set:
    try:
        p = psutil.Process(root_pid)
        return {p.pid} | {c.pid for c in p.children(recursive=True)}
    except psutil.Error:
        return set()


def _visible_window_of(pids: set):
    """pids 중 하나가 소유한 가시 최상위 창 핸들(없으면 0)."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _l):
        if user32.IsWindowVisible(hwnd) and not user32.GetParent(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                rect = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
                found.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    # 가장 큰 창(스플래시가 아니라 메인 창)을 고른다
    best, area = 0, 0
    for h in found:
        r = _rect(h)
        a = (r[2] - r[0]) * (r[3] - r[1])
        if a > area:
            best, area = h, a
    return best


def _rect(hwnd):
    import ctypes.wintypes as wt
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def kill_by_exe(exe: str) -> int:
    n = 0
    name = os.path.basename(exe).lower()
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info.get("name") or "").lower() == name or (p.info.get("exe") or "").lower() == exe.lower():
                p.kill()
                n += 1
        except psutil.Error:
            pass
    if n:
        time.sleep(2)
    return n


def screenshot(hwnd, out_path: str, max_w: int = 1200) -> str | None:
    try:
        from PIL import ImageGrab
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.8)
        l, t, r, b = _rect(hwnd)
        img = ImageGrab.grab(bbox=(max(l, 0), max(t, 0), r, b))
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path, "WEBP", quality=82, method=6)
        return out_path
    except Exception as e:
        print(f"  screenshot 실패: {type(e).__name__}: {e}")
        return None


def measure_app(app: dict, settle: int, shots_dir: str) -> dict:
    exe = expand(app["exe"])
    row = {"key": app["key"], "label": app["label"], "exe": exe}
    if not os.path.isfile(exe):
        row["installed"] = False
        print(f"  {app['label']:<12} 미설치 — 건너뜀")
        return row
    row["installed"] = True
    inst_dir = os.path.dirname(exe)
    # 설치 루트: exe 가 app-x.y.z 하위에 있으면(Squirrel) 한 단계 위
    if os.path.basename(inst_dir).lower().startswith("app-"):
        inst_dir = os.path.dirname(inst_dir)
    row["footprint_mb"] = round(dir_size_bytes(inst_dir) / 1e6, 0)
    row["version"] = file_version(exe)
    already = kill_by_exe(exe)
    row["killed_before"] = already
    args = [expand(x) for x in (app.get("args") or [])]
    if args:
        row["launch_args"] = args
    if app.get("fresh_profile"):
        row["fresh_profile"] = True
    t0 = time.perf_counter()
    proc = subprocess.Popen([exe, *args], cwd=inst_dir)
    hwnd, deadline = 0, time.perf_counter() + 90
    while time.perf_counter() < deadline:
        pids = _tree_pids(proc.pid)
        # Squirrel/Electron 은 런처가 진짜 앱을 띄우고 빠지기도 한다 → 같은 exe 이름의 모든 프로세스도 후보
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == os.path.basename(exe).lower():
                pids.add(p.pid)
        hwnd = _visible_window_of(pids)
        if hwnd:
            break
        time.sleep(0.2)
    row["cold_start_s"] = round(time.perf_counter() - t0, 2) if hwnd else None
    if hwnd:
        time.sleep(settle)
        pids = set()
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == os.path.basename(exe).lower():
                pids |= _tree_pids(p.pid)
        rss = 0
        for pid in pids:
            try:
                rss += psutil.Process(pid).memory_info().rss
            except psutil.Error:
                pass
        row["idle_rss_mb"] = round(rss / 1e6, 0)
        row["process_count"] = len(pids)
        # 스크린샷은 기본 꺼짐(config desktop.screenshots: true 로만 켠다). ImageGrab 은 창이 아니라 **화면 영역**을 찍으므로
        # SetForegroundWindow 가 거부되면(백그라운드 프로세스에서 흔함) 그 자리에 떠 있던 다른 창 — 2026-09-08 에는 편집자의
        # 브라우저 — 가 찍힌다. 창 내용 자체를 뜨는 PrintWindow 로 바꾸기 전에는 켜지 말 것.
        row["screenshot"] = (screenshot(hwnd, os.path.join(shots_dir, f"{app['key']}.webp")) if shots_dir else None)
    kill_by_exe(exe)
    print(f"  {app['label']:<12} v{row.get('version')} footprint={row.get('footprint_mb')}MB "
          f"cold_start={row.get('cold_start_s')}s idle_rss={row.get('idle_rss_mb')}MB procs={row.get('process_count')}")
    return row


def measure_cli(c: dict) -> dict:
    exe = expand(c["exe"])
    row = {"key": c["key"], "label": c["label"], "exe": exe, "installed": os.path.isfile(exe)}
    if not row["installed"]:
        print(f"  {c['label']:<12} 미설치 — 건너뜀")
        return row
    row["footprint_mb"] = round(dir_size_bytes(expand(c.get("dir") or os.path.dirname(exe))) / 1e6, 0)
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        out = subprocess.run([exe, *c.get("args", [])], capture_output=True, text=True, timeout=60)
        ts.append(time.perf_counter() - t0)
        row["version"] = (out.stdout or out.stderr).strip().splitlines()[0][:80] if (out.stdout or out.stderr) else ""
    row["run_s"] = round(min(ts), 2)
    print(f"  {c['label']:<12} {row['version']} footprint={row['footprint_mb']}MB run={row['run_s']}s")
    return row


def run(cfg: dict, shots_dir: str = "assets/measure", only=None) -> dict:
    if os.name != "nt" or psutil is None:
        raise SystemExit("desktop suite 는 Windows + psutil 에서만 돈다")
    settle = int(cfg.get("settle_seconds", 25))
    if not cfg.get("screenshots"):
        shots_dir = None
    rows = [measure_app(a, settle, shots_dir) for a in cfg.get("apps", []) if not only or a["key"] in only]
    clis = [measure_cli(c) for c in cfg.get("cli", []) if not only or c["key"] in only]
    return {"settle_seconds": settle, "rows": rows, "cli": clis}
