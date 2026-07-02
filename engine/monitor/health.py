"""health.py — 모니터 신호 수집 → killswitch.Metrics (AUTOMATION.md §4).

- API로 얻는 신호(CWV·RPM)는 db.metrics 에서 계산.
- 공개 API가 없는 신호(정책센터 경고·무효 트래픽·수동 조치·색인 급락)는
  engine/store/signals.json 오버라이드로 수용 — 운영자/외부 연동(웹훅 등)이 기록한다.
어떤 트래픽/클릭도 생성하지 않는다(F3).
"""
from __future__ import annotations
import json
import os

from monitor import killswitch

SIGNALS_FILE = "engine/store/signals.json"
LCP_BUDGET_MS = 2500.0   # design.md §8
CLS_BUDGET = 0.10


def _override() -> dict:
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _cwv_poor(db) -> bool:
    rows = db.query(
        "SELECT metric, value FROM metrics WHERE source='pagespeed' AND metric IN ('LCP','CLS') "
        "AND date=(SELECT MAX(date) FROM metrics WHERE source='pagespeed')")
    for metric, value in rows:
        if value is None:
            continue
        if metric == "LCP" and value > LCP_BUDGET_MS:
            return True
        if metric == "CLS" and value > CLS_BUDGET:
            return True
    return False


def _rpm_drop_pct(db) -> float:
    dates = db.query("SELECT DISTINCT date FROM metrics WHERE source='adsense' "
                     "AND metric='PAGE_VIEWS_RPM' ORDER BY date DESC LIMIT 2")
    if len(dates) < 2:
        return 0.0

    def avg(d):
        r = db.query("SELECT AVG(value) FROM metrics WHERE source='adsense' "
                     "AND metric='PAGE_VIEWS_RPM' AND date=?", (d,))
        return (r[0][0] or 0.0) if r else 0.0

    cur, prev = avg(dates[0][0]), avg(dates[1][0])
    return max(0.0, (prev - cur) / prev * 100.0) if prev > 0 else 0.0


def _deindex_rate_pct(db) -> float:
    """실제 색인 회귀율만 계산: 직전 스냅샷에서 색인(PASS)였다가 최신 스냅샷에서 빠진 URL 비율.
    신규 사이트의 '아직 미크롤' 페이지는 세지 않는다 → 정상 상태에서 오탐 방지.
    스냅샷이 2개 미만이면 0(비교 불가). 데이터 없으면 0."""
    try:
        dates = db.query("SELECT DISTINCT date FROM index_status ORDER BY date DESC LIMIT 2")
    except Exception:
        return 0.0
    if len(dates) < 2:
        return 0.0
    cur = dict(db.query("SELECT url, indexed FROM index_status WHERE date=?", (dates[0][0],)))
    prev = dict(db.query("SELECT url, indexed FROM index_status WHERE date=?", (dates[1][0],)))
    prev_indexed = [u for u, idx in prev.items() if idx]
    if not prev_indexed:
        return 0.0
    # 최신 스냅샷에도 존재하면서 indexed=0 이 된 것만 회귀로 카운트(사이트맵에서 빠진 URL 은 제외)
    regressed = sum(1 for u in prev_indexed if cur.get(u, 1) == 0)
    return regressed / len(prev_indexed) * 100.0


def collect(cfg, db) -> "killswitch.Metrics":
    ov = _override()
    return killswitch.Metrics(
        policy_center_warning=bool(ov.get("policy_center_warning", False)),
        invalid_traffic_alert=bool(ov.get("invalid_traffic_alert", False)),
        manual_action=bool(ov.get("manual_action", False)),
        indexing_drop_pct=float(ov.get("indexing_drop_pct", 0.0)),
        cwv_status_poor=_cwv_poor(db) or bool(ov.get("cwv_status_poor", False)),
        rpm_drop_pct=_rpm_drop_pct(db),
        # 자동(실제 색인 회귀) 과 수동 오버라이드 중 큰 값 — API 미연동 시엔 override 만.
        new_page_deindex_rate_pct=max(_deindex_rate_pct(db),
                                      float(ov.get("new_page_deindex_rate_pct", 0.0))),
    )
