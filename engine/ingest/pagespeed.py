"""pagespeed.py — PageSpeed Insights API v5 → Core Web Vitals (AUTOMATION.md §2 INGEST).

필드(CrUX) LCP/CLS/INP 우선, 없으면 랩(Lighthouse) 지표. API 키는 선택(.env PAGESPEED_API_KEY).
httpx 만 사용 — OAuth 불필요라 어댑터 중 유일하게 키 없이도 동작(저쿼터).
"""
from __future__ import annotations
import os

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_FIELD = {  # CrUX loadingExperience.metrics 키 → 우리 지표명
    "LARGEST_CONTENTFUL_PAINT_MS": "LCP",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "CLS",
    "INTERACTION_TO_NEXT_PAINT": "INP",
}


def fetch(url: str, strategy: str = "mobile", api_key: str | None = None) -> dict:
    import httpx
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if api_key:
        params["key"] = api_key
    r = httpx.get(ENDPOINT, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    out = {"url": url, "strategy": strategy}
    # 필드 데이터(실사용자, CrUX)
    le = data.get("loadingExperience", {}).get("metrics", {})
    for k, name in _FIELD.items():
        if k in le and "percentile" in le[k]:
            out[name] = le[k]["percentile"]
    # 랩 데이터(Lighthouse) — 점수
    audits = data.get("lighthouseResult", {}).get("audits", {})
    if "largest-contentful-paint" in audits:
        out.setdefault("LCP", audits["largest-contentful-paint"].get("numericValue"))
    if "cumulative-layout-shift" in audits:
        out.setdefault("CLS", audits["cumulative-layout-shift"].get("numericValue"))
    score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
    if score is not None:
        out["PERF_SCORE"] = score * 100
    return out


def ingest(urls, cfg, db) -> int:
    """대상 URL들의 CWV 수집 → db.metrics. 반환: 적재 행 수."""
    import datetime
    api_key = os.environ.get("PAGESPEED_API_KEY")
    today = datetime.date.today().isoformat()
    rows = []
    for url in urls:
        try:
            m = fetch(url, api_key=api_key)
        except Exception as e:
            print(f"  pagespeed {url}: {e}")
            continue
        for metric in ("LCP", "CLS", "INP", "PERF_SCORE"):
            if metric in m and m[metric] is not None:
                rows.append(("pagespeed", today, "url", url, metric, m[metric]))
    return db.record_metrics(rows, fetched_at=today)
