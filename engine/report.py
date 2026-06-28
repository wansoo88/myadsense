"""report.py — 주간 운영 리포트 (AUTOMATION.md §5). 로컬 HTML, Artifact 아님(CLAUDE.md).

db.metrics(AdSense RPM·CWV·검색) + 빌드 산출물(발행/큐 수)을 요약 → reports/weekly_{date}.html.
지표는 자체 데이터 기준(블로그 수치 신뢰 금지 — RESEARCH.md Caveat 3).
"""
from __future__ import annotations
import datetime
import glob
import html
import os

esc = html.escape

CSS = (
    "body{margin:0;background:#0f1115;color:#e7ebf2;font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',sans-serif}"
    ".wrap{max-width:880px;margin:0 auto;padding:36px 22px 70px}"
    "h1{font-size:24px;margin:0 0 4px}.sub{color:#9aa4b2;font-size:13px;margin:0 0 24px}"
    "h2{font-size:16px;margin:28px 0 10px;border-bottom:1px solid #2a2f3a;padding-bottom:6px}"
    ".stat{display:flex;gap:12px;flex-wrap:wrap}.s{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:12px 16px;min-width:120px}"
    ".s b{display:block;font-size:22px}.s span{font-size:11.5px;color:#9aa4b2}"
    "table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}"
    "th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #2a2f3a}th{color:#9aa4b2;font-size:12px;text-transform:uppercase}"
    "td.n{text-align:right;font-variant-numeric:tabular-nums}"
    ".empty{color:#9aa4b2;font-size:13.5px}.warn{background:rgba(245,185,66,.1);border:1px solid rgba(245,185,66,.3);color:#f0d79a;border-radius:8px;padding:10px 14px;font-size:13px}"
)


def _rows(db, sql, params=()):
    try:
        return db.query(sql, params)
    except Exception:
        return []


def _table(headers, rows, numcols=()):
    if not rows:
        return '<p class="empty">데이터 없음 — API 자격증명 연결 후 ingest 실행.</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        tds = ""
        for i, v in enumerate(r):
            cls = ' class="n"' if i in numcols else ""
            val = f"{v:.2f}" if (i in numcols and isinstance(v, float)) else esc(str(v))
            tds += f"<td{cls}>{val}</td>"
        body += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build(cfg, db) -> str:
    today = datetime.date.today().isoformat()
    os.makedirs("reports", exist_ok=True)
    path = os.path.join("reports", f"weekly_{today}.html")

    rpm = _rows(db, "SELECT dim_value, value FROM metrics WHERE source='adsense' AND metric='PAGE_VIEWS_RPM' "
                    "AND date=(SELECT MAX(date) FROM metrics WHERE source='adsense') ORDER BY value DESC LIMIT 10")
    cwv = _rows(db, "SELECT dim_value, metric, value FROM metrics WHERE source='pagespeed' "
                    "AND date=(SELECT MAX(date) FROM metrics WHERE source='pagespeed') ORDER BY dim_value")
    queries = _rows(db, "SELECT dim_value, value FROM metrics WHERE source='search_console' AND metric='clicks' "
                        "AND date=(SELECT MAX(date) FROM metrics WHERE source='search_console') ORDER BY value DESC LIMIT 10")
    published = len(glob.glob("dist/site/compare/*/index.html"))
    queued = len(glob.glob("dist/queue/*.html"))
    halted = os.path.exists("engine/store/killswitch_state.json")

    ks_warn = '<p class="warn">⚠️ 킬스위치 발동 중 — 발행 중단 상태. 원인 확인 후 해제 필요.</p>' if halted else ""
    has_data = bool(rpm or cwv or queries)
    no_data = ('<p class="warn">아직 수집 데이터 없음. <code>.env</code>에 Google/PageSpeed 키 설정 후 '
               '<code>python engine/orchestrator.py --stage ingest</code> 실행.</p>') if not has_data else ""

    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stack. 주간 리포트 {today}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>stack. 주간 운영 리포트</h1>
<p class="sub">{today} · 자체 데이터 기준 · 로컬 전용(Artifact 아님)</p>
{ks_warn}{no_data}
<div class="stat">
  <div class="s"><b>{published}</b><span>발행 페이지</span></div>
  <div class="s"><b>{queued}</b><span>발행 큐(게이트 통과)</span></div>
  <div class="s"><b>{"중단" if halted else "정상"}</b><span>킬스위치</span></div>
</div>
<h2>국가별 RPM (상위 10, 최신)</h2>
{_table(["국가", "RPM"], rpm, numcols=(1,))}
<h2>Core Web Vitals (페이지별 최신)</h2>
{_table(["URL", "지표", "값"], cwv, numcols=(2,))}
<h2>검색 쿼리 (클릭 상위 10)</h2>
{_table(["쿼리", "클릭"], queries, numcols=(1,))}
<p class="sub" style="margin-top:30px">생성: engine/report.py · 근거 docs/RESEARCH.md · 절대 수치는 자체 AdSense 리포트로 검증</p>
</div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"report: {path} (발행 {published} · 큐 {queued} · 킬스위치 {'중단' if halted else '정상'})")
    return path
