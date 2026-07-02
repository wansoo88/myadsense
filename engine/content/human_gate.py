"""human_gate.py — 품질 게이트 6번: 샘플 % 는 사람 승인 전엔 발행 큐 제외 (AUTOMATION.md §3, content.yaml human_sample_gate).

site_builder.build() 는 dist/queue/*.html 을 그대로 라이브에 반영하므로(글마다 스킵 로직 없음),
샘플로 뽑힌 글은 dist/queue 대신 dist/pending_approval 에 대기시켜 라이브에서 제외한다.
approve() 로 dist/queue 로 옮겨야 다음 build/deploy 부터 반영된다.
"""
from __future__ import annotations
import glob
import hashlib
import os
import shutil

PENDING_DIR = "dist/pending_approval"
QUEUE_DIR = "dist/queue"


def is_sampled(slug: str, sample_pct: int) -> bool:
    """슬러그 해시 기반 결정적 샘플링(같은 슬러그는 재실행해도 항상 같은 결과)."""
    if not sample_pct:
        return False
    h = int(hashlib.sha256(slug.encode("utf-8")).hexdigest(), 16)
    return (h % 100) < sample_pct


def hold(slug: str, html_doc: str) -> str:
    os.makedirs(PENDING_DIR, exist_ok=True)
    path = os.path.join(PENDING_DIR, f"{slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return path


def pending() -> list[str]:
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(f"{PENDING_DIR}/*.html"))


def approve(slug: str) -> str:
    src = os.path.join(PENDING_DIR, f"{slug}.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"승인 대기 중 아님: {src}")
    os.makedirs(QUEUE_DIR, exist_ok=True)
    dst = os.path.join(QUEUE_DIR, f"{slug}.html")
    shutil.move(src, dst)
    return dst
