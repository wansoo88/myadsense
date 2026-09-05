# -*- coding: utf-8 -*-
"""netprobe — 리전별 엔드포인트까지 TCP 연결 지연·HTTP TTFB·단일 스트림 다운로드 속도.

측정 정의(본문 캡션이 그대로 인용한다):
- connect_ms : TCP 3-way handshake 완료까지(ms). 표본 N 회 중앙값. RTT 의 근사.
- ttfb_ms    : TLS 포함 GET 요청 후 응답 헤더 첫 바이트까지(ms). 중앙값.
- mbps       : Range 로 받은 N MB 를 전송 시간으로 나눈 값(MB/s, 10^6 바이트). 단일 스트림·단일 호스트라
               회선 상한이 아니라 '그 순간 그 경로'의 값이다. 표본 중앙값.
실패는 None 으로 남긴다(지어내지 않는다).
"""
from __future__ import annotations
import http.client
import socket
import ssl
import time

from .common import median


def tcp_connect_ms(host: str, port: int = 443, timeout: float = 10.0):
    t0 = time.perf_counter()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
    except OSError:
        return None
    return (time.perf_counter() - t0) * 1000.0


def http_ttfb_ms(host: str, path: str = "/", timeout: float = 20.0):
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        c = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
        c.request("GET", path, headers={"User-Agent": "utilverse-measure/1.0", "Range": "bytes=0-0"})
        r = c.getresponse()
        ms = (time.perf_counter() - t0) * 1000.0
        r.read(64)
        c.close()
        return ms, r.status
    except (OSError, http.client.HTTPException):
        return None, None


def download_mbps(host: str, path: str, nbytes: int, timeout: float = 120.0):
    ctx = ssl.create_default_context()
    try:
        c = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
        c.request("GET", path, headers={"User-Agent": "utilverse-measure/1.0", "Range": f"bytes=0-{nbytes - 1}"})
        r = c.getresponse()
        if r.status not in (200, 206):
            c.close()
            return None
        t0 = time.perf_counter()
        got = 0
        while got < nbytes:
            chunk = r.read(min(65536, nbytes - got))
            if not chunk:
                break
            got += len(chunk)
        dt = time.perf_counter() - t0
        c.close()
        return (got / 1e6) / dt if dt > 0 and got >= nbytes * 0.95 else None
    except (OSError, http.client.HTTPException):
        return None


def run(cfg: dict) -> dict:
    rounds = int(cfg.get("rounds", 5))
    tp_rounds = int(cfg.get("throughput_rounds", 3))
    nbytes = int(cfg.get("throughput_bytes", 10 * 1024 * 1024))
    rows = []
    for t in cfg.get("targets", []):
        host, path = t["host"], t.get("file") or "/"
        con = [tcp_connect_ms(host) for _ in range(rounds)]
        ttfb, status = [], None
        for _ in range(rounds):
            ms, st = http_ttfb_ms(host, path)
            ttfb.append(ms)
            status = st or status
        mbps = [download_mbps(host, path, nbytes) for _ in range(tp_rounds)] if t.get("file") else []
        rows.append({
            "provider": t["provider"], "region": t["region"], "host": host,
            "connect_ms": median(con), "ttfb_ms": median(ttfb), "http_status": status,
            "mbps": (round(median(mbps), 2) if median(mbps) is not None else None),
            "samples": {"connect_ms": [round(x, 1) if x else None for x in con],
                        "ttfb_ms": [round(x, 1) if x else None for x in ttfb],
                        "mbps": [round(x, 2) if x else None for x in mbps]},
            "reachable": any(x is not None for x in con),
        })
        print(f"  {t['provider']:<13} {t['region']:<22} connect={rows[-1]['connect_ms']} ttfb={rows[-1]['ttfb_ms']} mbps={rows[-1]['mbps']}")
    return {"rounds": rounds, "throughput_rounds": tp_rounds, "throughput_bytes": nbytes, "rows": rows}
