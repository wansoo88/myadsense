"""search_console.py — Google Search Console API v1 → 검색 성과 (AUTOMATION.md §2 INGEST).

오가닉 쿼리·페이지별 clicks/impressions/ctr/position 수집(F7 모니터링 근거).
인증: .env 의 GOOGLE_OAUTH_* 리프레시 토큰. 자격증명 없으면 스킵(0 반환).
필요: google-api-python-client, google-auth (requirements.txt).
"""
from __future__ import annotations
import datetime
import os

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


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


def ingest(cfg, db) -> int:
    creds = _credentials()
    site_url = os.environ.get("SEARCH_CONSOLE_SITE_URL")
    if not creds or not site_url:
        print("  search_console: 자격증명/SEARCH_CONSOLE_SITE_URL 없음 → 스킵")
        return 0
    from googleapiclient.discovery import build
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    end = datetime.date.today()
    start = end - datetime.timedelta(days=28)
    body = {
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "dimensions": ["query"], "rowLimit": 100,
    }
    resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    today = end.isoformat()
    rows = []
    for r in resp.get("rows", []):
        q = r["keys"][0]
        rows.append(("search_console", today, "query", q, "clicks", r.get("clicks", 0)))
        rows.append(("search_console", today, "query", q, "impressions", r.get("impressions", 0)))
        rows.append(("search_console", today, "query", q, "position", r.get("position", 0)))
    return db.record_metrics(rows, fetched_at=today)
