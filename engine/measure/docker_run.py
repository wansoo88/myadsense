# -*- coding: utf-8 -*-
"""docker_run — 공식 이미지를 실제로 pull 하고 띄워서 잰다: pull 시간, 디스크 전개 크기, 첫 HTTP 응답까지의 시간,
settle 뒤 컨테이너 메모리. 끝나면 컨테이너와 이미지를 지운다(디스크가 빠듯한 호스트에서 돌리기 때문).

정의(캡션 인용용):
- pull_s        : `docker pull` 완료까지(초). 네트워크·레지스트리 상태에 좌우된다.
- image_mb      : `docker image inspect .Size` (전개 크기, 10^6).
- first_200_s   : `docker run` 직후부터 health 경로가 200/302/401 등 응답을 주기까지(초).
- idle_mem_mb   : first_200 후 settle 초 뒤 `docker stats` 의 메모리 사용량(MB).
"""
from __future__ import annotations
import json
import subprocess
import time
import urllib.error
import urllib.request


def _sh(args, timeout=1800):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _wait_http(url: str, deadline_s: int = 300):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "utilverse-measure/1.0"}), timeout=5)
            return round(time.perf_counter() - t0, 1), r.status
        except urllib.error.HTTPError as e:
            if e.code < 500:                          # 401/403/404 도 '서버가 응답했다'
                return round(time.perf_counter() - t0, 1), e.code
        except Exception:
            pass
        time.sleep(0.5)
    return None, None


def measure(t: dict, settle: int, host_port: int = 18080, keep_image: bool = False) -> dict:
    name = f"measure-{t['key']}"
    row = {"key": t["key"], "label": t["label"], "image": t["image"]}
    _sh(["docker", "rm", "-f", name])
    t0 = time.perf_counter()
    p = _sh(["docker", "pull", t["image"]])
    if p.returncode != 0:
        row["error"] = "pull failed: " + p.stderr.strip()[-200:]
        print(f"  {t['label']:<12} {row['error']}")
        return row
    row["pull_s"] = round(time.perf_counter() - t0, 1)
    ins = _sh(["docker", "image", "inspect", "--format", "{{.Size}}|{{index .RepoDigests 0}}|{{.Created}}", t["image"]]).stdout.strip()
    size, digest, created = (ins.split("|") + ["", "", ""])[:3]
    row["image_mb"] = round(int(size) / 1e6, 0) if size.isdigit() else None
    row["digest"] = digest.split("@")[-1][:19] if digest else ""
    row["image_created"] = created[:10]
    cmd = ["docker", "run", "-d", "--name", name, "-p", f"{host_port}:{t['port']}", t["image"], *t.get("args", [])]
    t1 = time.perf_counter()
    r = _sh(cmd)
    if r.returncode != 0:
        row["error"] = "run failed: " + r.stderr.strip()[-200:]
    else:
        row["first_200_s"], row["http_status"] = _wait_http(f"http://127.0.0.1:{host_port}{t.get('health', '/')}")
        if row["first_200_s"] is not None:
            time.sleep(settle)
            st = _sh(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}|{{.CPUPerc}}", name]).stdout.strip()
            mem = st.split("|")[0].split("/")[0].strip() if st else ""
            row["idle_mem_mb"] = _to_mb(mem)
            row["idle_cpu_pct"] = st.split("|")[1].strip() if "|" in st else None
        else:
            row["error"] = "no HTTP response within 300 s: " + _sh(["docker", "logs", "--tail", "5", name]).stdout[-300:]
    _sh(["docker", "rm", "-f", name])
    if not keep_image:
        _sh(["docker", "rmi", t["image"]])
    print(f"  {t['label']:<12} pull={row.get('pull_s')}s image={row.get('image_mb')}MB first_200={row.get('first_200_s')}s "
          f"idle_mem={row.get('idle_mem_mb')}MB {row.get('error', '')}")
    return row


def _to_mb(s: str):
    s = s.strip()
    try:
        if s.endswith("GiB"):
            return round(float(s[:-3]) * 1073.74, 0)
        if s.endswith("MiB"):
            return round(float(s[:-3]) * 1.048576, 0)
        if s.endswith("KiB"):
            return round(float(s[:-3]) / 976.6, 1)
        if s.endswith("MB"):
            return round(float(s[:-2]), 0)
    except ValueError:
        pass
    return None


def run(cfg: dict, only=None, keep_image: bool = False) -> dict:
    v = _sh(["docker", "version", "--format", "{{.Server.Version}}"])
    if v.returncode != 0:
        raise SystemExit("docker 데몬에 연결할 수 없다: " + v.stderr.strip()[:200])
    settle = int(cfg.get("settle_seconds", 45))
    rows = []
    for t in cfg.get("targets", []):
        if only and t["key"] not in only:
            continue
        rows.append(measure(t, settle, keep_image=keep_image))
    return {"docker_server": v.stdout.strip(), "settle_seconds": settle, "rows": rows}
