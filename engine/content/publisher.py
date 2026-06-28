"""publisher.py — 발행 어댑터 (AUTOMATION.md §2 PUBLISH, 어댑터 패턴).

static_ssg: HTML 파일을 출력 디렉토리에 기록 → Caddy 서빙 / git push (운영).
dry_run=True: dist/preview 에만 기록, 실발행·킬스위치 영향 없음.
운영 발행은 킬스위치·일일 cap 준수(킬스위치 중단 시 거부).
"""
from __future__ import annotations
import os

from monitor import killswitch


class StaticSSGPublisher:
    def __init__(self, sites_cfg: dict | None = None):
        self.sites_cfg = sites_cfg or {}

    def _out_dir(self, dry_run: bool) -> str:
        if dry_run:
            return "dist/preview"
        try:
            return self.sites_cfg["sites"][0]["cms"].get("content_dir", "content").rstrip("/")
        except Exception:
            return "content"

    def publish(self, html_doc: str, slug: str, *, dry_run: bool = True) -> str:
        if not dry_run and killswitch.is_halted():
            raise RuntimeError("killswitch 중단 상태 — 발행 거부. 원인 확인 후 killswitch.clear() 필요.")
        out_dir = self._out_dir(dry_run)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{slug}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)
        return path


def get_publisher(sites_cfg: dict):
    adapter = "static_ssg"
    try:
        adapter = sites_cfg["sites"][0]["cms"]["adapter"]
    except Exception:
        pass
    if adapter == "static_ssg":
        return StaticSSGPublisher(sites_cfg)
    if adapter == "wordpress":
        raise NotImplementedError("wordpress 어댑터 — REST API(.env WP_USER/WP_APP_PASSWORD)로 구현 예정")
    raise ValueError(f"unknown CMS adapter: {adapter}")
