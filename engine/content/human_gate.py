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


# 보류 사유 사이드카 (ORDER 2026-07-25-40 ②) — 사람이 slug 만 보고는 판단할 수 없다.
# 본문 HTML 에는 **손대지 않는다**(승인 시 그대로 발행되는 산출물이라 배너를 심으면 라이브로 나간다).
# 대신 같은 디렉터리에 사유 파일을 나란히 둔다 → 파일 목록만 열어도 읽힌다.
REASON_SUFFIX = ".reason.txt"
REJECTED_DIR = "dist/review"          # 사람이 거부한 초안 보존 위치(_keep_rejected_spec 와 같은 곳)


def _reason_path(slug: str) -> str:
    return os.path.join(PENDING_DIR, f"{slug}{REASON_SUFFIX}")


def hold(slug: str, html_doc: str, reason: str = "") -> str:
    os.makedirs(PENDING_DIR, exist_ok=True)
    path = os.path.join(PENDING_DIR, f"{slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    if reason:
        try:                                       # 사유 기록 실패가 보류 자체를 깨지 않게(부가 기능)
            with open(_reason_path(slug), "w", encoding="utf-8") as f:
                f.write(reason.rstrip() + "\n")
        except OSError:
            pass
    return path


def reason(slug: str) -> str:
    """보류 사유(없으면 빈 문자열)."""
    try:
        with open(_reason_path(slug), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def pending() -> list[str]:
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(f"{PENDING_DIR}/*.html"))


def pending_report() -> list[str]:
    """`--list-pending` 용 — slug + 보류 사유 + 처리 명령까지 한 화면에."""
    out = []
    for slug in pending():
        why = reason(slug) or "(사유 기록 없음 — 이 글은 사유 기록 도입 전에 보류됐다)"
        out.append(f"● {slug}\n" + "\n".join(f"    {ln}" for ln in why.splitlines()))
    return out


def approve(slug: str) -> str:
    src = os.path.join(PENDING_DIR, f"{slug}.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"승인 대기 중 아님: {src}")
    os.makedirs(QUEUE_DIR, exist_ok=True)
    dst = os.path.join(QUEUE_DIR, f"{slug}.html")
    shutil.move(src, dst)
    try:                                           # 사유 사이드카는 큐로 따라가지 않는다(발행 산출물 아님)
        os.remove(_reason_path(slug))
    except OSError:
        pass
    return dst


def reject(slug: str) -> str:
    """사람이 거부 — 발행하지 않고 보존만 한다(dist/review/<slug>.human-rejected.html).

    ⛔ 검수 판정(`passed`)을 바꾸지 않는다. 사람이 '이 글은 안 내보낸다'고 결정한 기록일 뿐이다."""
    src = os.path.join(PENDING_DIR, f"{slug}.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"승인 대기 중 아님: {src}")
    os.makedirs(REJECTED_DIR, exist_ok=True)
    dst = os.path.join(REJECTED_DIR, f"{slug}.human-rejected.html")
    shutil.move(src, dst)
    try:
        os.replace(_reason_path(slug), os.path.join(REJECTED_DIR, f"{slug}.human-rejected.reason.txt"))
    except OSError:
        pass
    return dst
