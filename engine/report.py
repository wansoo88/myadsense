"""report.py — 주간 운영 리포트 (AUTOMATION.md §5). 로컬 HTML, Artifact 아님(CLAUDE.md).

db.metrics(AdSense RPM·CWV·검색) + 빌드 산출물(발행/큐 수)을 요약 → reports/weekly_{date}.html.
지표는 자체 데이터 기준(블로그 수치 신뢰 금지 — RESEARCH.md Caveat 3).
"""
from __future__ import annotations
import datetime
import glob
import html
import json
import os

esc = html.escape


def _published_keywords() -> list:
    try:
        with open("engine/store/published.json", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else list(d.keys())
    except Exception:
        return []


def _coverage_section(cfg) -> str:
    """클러스터별 커버리지(발행/전체) + 남은 시드 — 콘텐츠 갭 가시화(기획)."""
    try:
        from content import keyword_research
        rows = keyword_research.coverage_report(cfg.get("topics", {}) or {}, _published_keywords())
    except Exception:
        return ""
    if not rows:
        return ""
    body = ""
    for r in rows:
        rem = ", ".join(r["remaining"][:4]) + (f" 외 {len(r['remaining']) - 4}건" if len(r["remaining"]) > 4 else "")
        body += (f"<tr><td>{esc(r['cluster'])} <span style='color:#6b7280'>(P{r['priority']})</span></td>"
                 f"<td class='n'>{r['covered']}/{r['total']}</td>"
                 f"<td style='color:#9aa4b2'>{esc(rem) or '—'}</td></tr>")
    return ('<h2>콘텐츠 커버리지 (클러스터별 발행/시드)</h2>'
            '<table><thead><tr><th>클러스터</th><th>발행/전체</th><th>남은 시드(갭)</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')


def _striking_section(db, cfg) -> str:
    """GSC striking distance(8~30위) — '거의 1페이지' 실수요 기회(신규/보강 구분)."""
    try:
        from content import keyword_research
        known = []
        for c in (cfg.get("topics", {}) or {}).get("clusters", []):
            known.extend(c.get("seeds", []))
        rows = keyword_research.find_striking_distance(db, known, limit=15)
    except Exception:
        return ""
    if not rows:
        return ('<h2>Striking distance (거의 1페이지)</h2>'
                '<p class="empty">GSC 데이터 없음 — 색인·노출이 쌓이면 여기에 상위 진입 임박 쿼리가 표시됩니다.</p>')
    body = ""
    for e in rows:
        action = "기존 글 보강" if e["in_backlog"] else "신규 타깃"
        body += (f"<tr><td>{esc(e['keyword'])}</td><td class='n'>{e['position']}</td>"
                 f"<td class='n'>{e['impressions']}</td><td>{action}</td></tr>")
    return ('<h2>Striking distance (거의 1페이지 · 최고 ROI)</h2>'
            '<table><thead><tr><th>쿼리</th><th>평균순위</th><th>노출</th><th>액션</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')

def _epoch_utc(v) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(v), datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    except Exception:
        return "—"


def _analytics_paths() -> tuple:
    """config/analytics.yaml 의 (롤업 DB 경로, data.json 경로). 설정이 없으면 기본값·None."""
    db_path, data_json = "engine/store/analytics.db", None
    try:
        import yaml
        with open("config/analytics.yaml", encoding="utf-8") as f:
            out = (yaml.safe_load(f) or {}).get("output") or {}
        db_path = out.get("db") or db_path
        if out.get("dir"):
            data_json = os.path.join(out["dir"], "data.json")
    except Exception:
        pass
    return db_path, data_json


def _googlebot_rows(db_path: str):
    """analytics.db 의 googlebot_path_daily → [(창, 요청, 200/304, distinct 기사)]. 없으면 []."""
    import sqlite3
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return []
    try:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                            "AND name='googlebot_path_daily'").fetchone():
            return []
        out = []
        for label, days in (("7일", 7), ("30일", 30)):
            cut = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
            r = conn.execute("SELECT COALESCE(SUM(requests),0), COALESCE(SUM(ok),0), COUNT(DISTINCT path) "
                             "FROM googlebot_path_daily WHERE date>=?", (cut,)).fetchone()
            out.append((label, int(r[0]), int(r[1]), int(r[2])))
        return out
    except Exception:
        return []
    finally:
        conn.close()


def _referrer_rows(data_json):
    """방문 분석 data.json 의 리퍼러(30일·사람만·봇 3겹 제외) 상위 5. 없으면 []."""
    if not data_json or not os.path.exists(data_json):
        return []
    try:
        with open(data_json, encoding="utf-8") as f:
            refs = (json.load(f) or {}).get("referrers") or []
        return [(r.get("host", "—"), int(r.get("count", 0))) for r in refs[:5]]
    except Exception:
        return []


def _discovery_section(db) -> str:
    """'발견 신호' — F16 재신청 게이트(사이트맵 다운로드 · 기사 색인 ≥ 10 · 구글 클릭 > 0)를 자체 데이터로 판정.
    입력은 전부 읽기 전용 수집분(GSC sitemaps.list · URL Inspection · 검색성과 · nginx 로그 롤업)."""
    # 1) 사이트맵 — 최신 수집일의 경로별 상태
    r = _rows(db, "SELECT MAX(date) FROM metrics WHERE source='search_console' AND dimension='sitemap'")
    sm_date = r[0][0] if r and r[0] else None
    sitemaps: dict = {}
    if sm_date:
        for path, metric, value in _rows(db, "SELECT dim_value,metric,value FROM metrics WHERE "
                                             "source='search_console' AND dimension='sitemap' AND date=?", (sm_date,)):
            sitemaps.setdefault(path, {})[metric] = value
    any_downloaded = any(v.get("downloaded") for v in sitemaps.values())
    sm_rows = []
    for path, v in sorted(sitemaps.items()):
        sm_rows.append((
            path,
            "예" if v.get("downloaded") else "아니오 (lastDownloaded 없음)",
            _epoch_utc(v["last_downloaded_epoch"]) if "last_downloaded_epoch" in v else "—",
            _epoch_utc(v["last_submitted_epoch"]) if "last_submitted_epoch" in v else "—",
            "대기(isPending)" if v.get("pending") else "처리됨",
            int(v.get("errors", 0)), int(v.get("warnings", 0)),
            int(v.get("submitted", 0)), int(v.get("indexed", 0)),
        ))
    # 2) 기사 색인 — 최신 URL Inspection 스냅샷, /compare/ 만
    r = _rows(db, "SELECT MAX(date) FROM index_status")
    ix_date = r[0][0] if r and r[0] else None
    articles_total = articles_indexed = articles_crawled = 0
    if ix_date:
        r = _rows(db, "SELECT COUNT(*), COALESCE(SUM(indexed),0), "
                      "COALESCE(SUM(CASE WHEN indexed=0 AND lower(coverage_state) LIKE '%crawled%' "
                      "AND lower(coverage_state) LIKE '%not indexed%' THEN 1 ELSE 0 END),0) "
                      "FROM index_status WHERE date=? AND url LIKE '%/compare/%'", (ix_date,))
        if r:
            articles_total, articles_indexed, articles_crawled = int(r[0][0]), int(r[0][1]), int(r[0][2])
    # 3) 구글 클릭 — 최신 수집일의 query 차원 합(28일 창)
    r = _rows(db, "SELECT date, COALESCE(SUM(value),0) FROM metrics WHERE source='search_console' "
                  "AND dimension='query' AND metric='clicks' AND date=(SELECT MAX(date) FROM metrics "
                  "WHERE source='search_console' AND dimension='query')")
    clicks_date, clicks = (r[0][0], int(r[0][1])) if r and r[0] and r[0][0] else (None, 0)
    # 4) Googlebot 기사 요청 · 5) 리퍼러 — 방문 분석(서버 로그) 산출물
    db_path, data_json = _analytics_paths()
    gb_rows = _googlebot_rows(db_path)
    ref_rows = _referrer_rows(data_json)

    conds = [any_downloaded, articles_indexed >= 10, clicks > 0]
    mark = lambda ok: "✓" if ok else "✗"
    gate = (f"재신청 게이트 <b>{sum(conds)}/3</b> 충족 — "
            f"사이트맵 다운로드 {mark(conds[0])} · 기사 색인 {articles_indexed}/10 {mark(conds[1])} · "
            f"구글 클릭 {clicks} {mark(conds[2])}")
    cls = "ok" if all(conds) else "warn"
    return (
        '<h2>발견 신호 (F16 재신청 게이트 — 구글이 읽고 클릭을 보내는가)</h2>'
        f'<p class="{cls}">{gate}</p>'
        f'<h3>사이트맵 (GSC sitemaps.list · 수집 {esc(sm_date or "없음")})</h3>'
        + _table(["경로", "다운로드됨", "lastDownloaded", "lastSubmitted", "상태", "오류", "경고", "제출 URL", "색인 URL"],
                 sm_rows, numcols=(5, 6, 7, 8))
        + f'<h3>기사 색인 (URL Inspection · {esc(ix_date or "없음")} · /compare/ 한정)</h3>'
        + _table(["기사 전체", "색인 완료", "크롤됐으나 미색인"],
                 [(articles_total, articles_indexed, articles_crawled)] if ix_date else [], numcols=(0, 1, 2))
        + f'<h3>구글 클릭 (28일 창 · {esc(clicks_date or "없음")})</h3>'
        + _table(["클릭 합계"], [(clicks,)] if clicks_date else [], numcols=(0,))
        + '<h3>Googlebot 기사 요청 (nginx 로그 롤업 · UA 자칭 기준 상한값)</h3>'
        + _table(["창", "요청", "200/304", "distinct 기사"], gb_rows, numcols=(1, 2, 3))
        + '<h3>리퍼러 상위 5 (30일 · 사람만)</h3>'
        + _table(["호스트", "방문"], ref_rows, numcols=(1,))
    )


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
    "h3{font-size:13.5px;margin:16px 0 4px;color:#c9d1dc}"
    ".ok{background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.3);color:#bdf0cf;border-radius:8px;padding:10px 14px;font-size:13px}"
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
{_discovery_section(db)}
<h2>국가별 RPM (상위 10, 최신)</h2>
{_table(["국가", "RPM"], rpm, numcols=(1,))}
<h2>Core Web Vitals (페이지별 최신)</h2>
{_table(["URL", "지표", "값"], cwv, numcols=(2,))}
<h2>검색 쿼리 (클릭 상위 10)</h2>
{_table(["쿼리", "클릭"], queries, numcols=(1,))}
{_striking_section(db, cfg)}
{_coverage_section(cfg)}
<p class="sub" style="margin-top:30px">생성: engine/report.py · 근거 docs/RESEARCH.md · 절대 수치는 자체 AdSense 리포트로 검증</p>
</div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"report: {path} (발행 {published} · 큐 {queued} · 킬스위치 {'중단' if halted else '정상'})")
    return path
