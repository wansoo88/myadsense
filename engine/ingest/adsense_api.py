"""adsense_api.py — AdSense Management API v2 → RPM·수익 (AUTOMATION.md §2 INGEST).

국가별 PAGE_VIEWS_RPM·ESTIMATED_EARNINGS·IMPRESSIONS 수집(F5 지역 레버·계정 건강 근거).
읽기 전용. 인증: .env GOOGLE_OAUTH_* + ADSENSE_ACCOUNT_ID. 없으면 스킵(0 반환).
⚠️ 무효 트래픽 금지(F3) — 이 어댑터는 보고서 조회만, 트래픽/클릭은 절대 생성하지 않는다.
"""
from __future__ import annotations
import datetime
import os

SCOPES = ["https://www.googleapis.com/auth/adsense.readonly"]


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
    account = os.environ.get("ADSENSE_ACCOUNT_ID")  # "accounts/pub-XXXX" 또는 "pub-XXXX"
    if not creds or not account:
        print("  adsense: 자격증명/ADSENSE_ACCOUNT_ID 없음 → 스킵")
        return 0
    if not account.startswith("accounts/"):
        account = f"accounts/{account}"
    from googleapiclient.discovery import build
    service = build("adsense", "v2", credentials=creds, cache_discovery=False)

    today = datetime.date.today()
    report = service.accounts().reports().generate(
        account=account,
        dateRange="LAST_30_DAYS",
        metrics=["ESTIMATED_EARNINGS", "PAGE_VIEWS_RPM", "IMPRESSIONS", "CLICKS"],
        dimensions=["COUNTRY_NAME"],
        orderBy=["-ESTIMATED_EARNINGS"],
    ).execute()

    headers = [h["name"] for h in report.get("headers", [])]
    stamp = today.isoformat()
    rows = []
    for row in report.get("rows", []):
        cells = [c.get("value") for c in row.get("cells", [])]
        rec = dict(zip(headers, cells))
        country = rec.get("COUNTRY_NAME", "(unknown)")
        for metric in ("ESTIMATED_EARNINGS", "PAGE_VIEWS_RPM", "IMPRESSIONS", "CLICKS"):
            if metric in rec and rec[metric] not in (None, ""):
                try:
                    rows.append(("adsense", stamp, "country", country, metric, float(rec[metric])))
                except ValueError:
                    pass
    return db.record_metrics(rows, fetched_at=stamp)
