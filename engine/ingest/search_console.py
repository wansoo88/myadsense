"""search_console.py — Google Search Console API v1 → 검색 성과 + 색인 상태 (AUTOMATION.md §2 INGEST).

수집 항목:
  1) 쿼리 성과 (query 차원): clicks/impressions/position — F7 오가닉 모니터링.
  2) 페이지 성과 (page 차원): 페이지별 clicks/impressions — 어떤 글이 유입되나.
  3) 색인 상태 (URL Inspection API): 사이트맵 URL별 verdict·coverageState — "색인 됐나" 자동 점검.
인증: .env 의 GOOGLE_OAUTH_* 리프레시 토큰 + SEARCH_CONSOLE_SITE_URL. 없으면 스킵(0 반환).
SEARCH_CONSOLE_SITE_URL 은 GSC 속성 문자열과 정확히 일치해야 함(URL 접두어: https://도메인/).
필요: google-api-python-client, google-auth (requirements.txt).
"""
from __future__ import annotations
import datetime
import glob
import os
import re

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_MAX_INSPECT = 50   # URL Inspection 1일 쿼리(사이트 URL 수 < 이 값이면 전량, 초과 시 앞에서 자르고 경고)


def _credentials():
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")
    if not (cid and secret and refresh):
        return None
    from google.oauth2.credentials import Credentials
    return Credentials(
        None, refresh_token=refresh, client_id=cid, client_secret=secret,
        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES,
    )


def _sitemap_urls(site_url: str, limit: int = _MAX_INSPECT):
    """색인 점검 대상 URL — 빌드 산출물 dist/site/sitemap.xml 에서 <loc> 추출.
    없으면 빈 리스트(→ 색인 점검 스킵). 앞에서 limit 개까지만(초과분은 호출부에서 경고)."""
    for path in ("dist/site/sitemap.xml",):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                locs = re.findall(r"<loc>([^<]+)</loc>", f.read())
            return locs
    return []


def _ingest_performance(service, site_url, db, today) -> int:
    """쿼리·페이지 차원 검색 성과 → metrics."""
    start = (datetime.date.fromisoformat(today) - datetime.timedelta(days=28)).isoformat()
    rows = []
    for dim in ("query", "page"):
        body = {"startDate": start, "endDate": today, "dimensions": [dim], "rowLimit": 200}
        resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        for r in resp.get("rows", []):
            key = r["keys"][0]
            for metric in ("clicks", "impressions", "position"):
                rows.append(("search_console", today, dim, key, metric, r.get(metric, 0)))
    return db.record_metrics(rows, fetched_at=today)


def _ingest_index_status(service, site_url, db, today) -> int:
    """URL Inspection API → 사이트맵 URL별 색인 verdict·coverageState → index_status.
    verdict PASS=색인됨(indexed=1). API 실패한 URL 은 건너뛰고 계속(부분 성공 허용)."""
    urls = _sitemap_urls(site_url)
    if not urls:
        print("  search_console(index): dist/site/sitemap.xml 없음 → 색인 점검 스킵")
        return 0
    if len(urls) > _MAX_INSPECT:
        print(f"  search_console(index): URL {len(urls)}개 중 {_MAX_INSPECT}개만 점검(일일 쿼터 보호)")
        urls = urls[:_MAX_INSPECT]
    statuses, failed = [], 0
    for u in urls:
        try:
            resp = service.urlInspection().index().inspect(
                body={"inspectionUrl": u, "siteUrl": site_url}).execute()
            r = resp.get("inspectionResult", {}).get("indexStatusResult", {})
            verdict = r.get("verdict", "")           # PASS / NEUTRAL / FAIL / VERDICT_UNSPECIFIED
            coverage = r.get("coverageState", "")     # 예: "Submitted and indexed"
            last_crawl = r.get("lastCrawlTime", "")
            statuses.append((u, today, verdict, coverage, last_crawl, 1 if verdict == "PASS" else 0))
        except Exception as e:                        # 개별 URL 실패는 전체를 막지 않음
            failed += 1
            print(f"  search_console(index) {u}: {e}")
    if failed:
        print(f"  search_console(index): {failed}개 URL 점검 실패(건너뜀)")
    return db.record_index_status(statuses, fetched_at=today)


def ingest(cfg, db) -> int:
    creds = _credentials()
    site_url = os.environ.get("SEARCH_CONSOLE_SITE_URL")
    if not creds or not site_url:
        print("  search_console: 자격증명/SEARCH_CONSOLE_SITE_URL 없음 → 스킵")
        return 0
    from googleapiclient.discovery import build
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    today = datetime.date.today().isoformat()
    n = _ingest_performance(service, site_url, db, today)
    n += _ingest_index_status(service, site_url, db, today)
    return n
