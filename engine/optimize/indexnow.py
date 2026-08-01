"""indexnow.py — 발행/변경된 URL 을 IndexNow(Bing·Yandex·Seznam 등)에 자동 통보.

색인 '알림' 프로토콜이다 — ⛔ 트래픽/클릭 생성이 아님(docs/RESEARCH.md F3 무관, 리스크 0).
Google 은 IndexNow 미참여 → 구글은 사이트맵·GSC 로 커버(별도).

동작: stage_deploy 성공(실배포) 후 dist/site 를 스캔 → 내용이 바뀐 URL 만 제출(상태파일로 변경 감지).
  - 매번 전체 재제출하지 않는다(불필요·스팸성 회피) — 신규/변경분만.
  - 네트워크 실패는 무해(배포에 영향 없음) + 상태 미갱신 → 다음 배포에서 자동 재시도.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request

SITE_DIR = "dist/site"
STATE = "engine/store/indexnow_state.json"
ENDPOINT = "https://api.indexnow.org/indexnow"   # 참여 엔진에 공유(중립 애그리게이터)
TIMEOUT = 15


def _key_and_domain(cfg):
    site = cfg["sites"]["sites"][0]
    key = (site.get("indexnow_key") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key or ""):
        return None, None
    return key, site.get("domain", "utilverse.info")


def _sitemap_urls():
    """dist/site/sitemap.xml 의 <loc> URL 목록(빌드가 만든 정본)."""
    p = os.path.join(SITE_DIR, "sitemap.xml")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return re.findall(r"<loc>([^<]+)</loc>", f.read())


def _url_to_file(url: str, base: str) -> str | None:
    """canonical URL → 로컬 산출물 파일 경로(해시 대상)."""
    if not url.startswith(base):
        return None
    rel = url[len(base):]
    if rel in ("", "/"):
        return os.path.join(SITE_DIR, "index.html")
    rel = rel.strip("/")
    cand = os.path.join(SITE_DIR, rel, "index.html")   # pretty URL(디렉토리)
    if os.path.exists(cand):
        return cand
    alt = os.path.join(SITE_DIR, rel)                   # 파일형(sitemap 엔 없지만 방어)
    return alt if os.path.exists(alt) else None


def _hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _load_state() -> dict:
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(d: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _submit(urls, key, key_location, host) -> int:
    payload = json.dumps({
        "host": host, "key": key, "keyLocation": key_location, "urlList": urls,
    }).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=payload, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status


def run(cfg) -> int:
    """변경된 URL 을 IndexNow 에 제출. 반환: 제출한 URL 수(0=스킵/변경없음)."""
    key, domain = _key_and_domain(cfg)
    if not key:
        print("  indexnow: indexnow_key 없음/형식오류 — 스킵")
        return 0
    base = f"https://{domain}"
    urls = _sitemap_urls()
    if not urls:
        print("  indexnow: dist/site/sitemap.xml 없음 — 먼저 build 필요")
        return 0

    cur = {}
    for u in urls:
        fp = _url_to_file(u, base)
        if fp:
            cur[u] = _hash(fp)
    state = _load_state()
    changed = [u for u in cur if cur[u] != state.get(u)]
    if not changed:
        print(f"  indexnow: 변경 URL 없음(전체 {len(cur)}) — 제출 스킵")
        return 0

    key_location = f"{base}/{key}.txt"
    try:
        status = _submit(changed, key, key_location, domain)
    except Exception as e:
        print(f"  indexnow: 제출 실패({e}) — 상태 미갱신(다음 배포에서 재시도)")
        return 0
    if status in (200, 202):
        state.update(cur)                     # 성공분만 상태 반영(변경 없던 URL 도 현행 해시로 정리)
        _save_state(state)
        print(f"  indexnow: {len(changed)}개 URL 제출 → HTTP {status} (Bing·Yandex 등)")
        return len(changed)
    print(f"  indexnow: 예상외 응답 HTTP {status} — 상태 미갱신")
    return 0


if __name__ == "__main__":
    import yaml
    with open("config/sites.yaml", encoding="utf-8") as f:
        run({"sites": yaml.safe_load(f)})
