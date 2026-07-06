"""builder.py — 방문 로그 집계 → SQLite 일자 롤업 영속화 → 관리자 대시보드 생성.

흐름:
  parser.collect()  →  일자별/페이지별 롤업 upsert(analytics.db)  →
  data.json(추세·상위페이지·리퍼러·디바이스·최근로그·봇·나제외) + index.html 를 output.dir 에 기록.

로그는 14일 회전 후 삭제되지만, 일자 롤업은 DB 에 남아 추세가 유지된다(로그가 있는 날은 재계산·덮어쓰기 = 멱등).
표준 라이브러리만 사용. Artifact 아님 — 서버가 nginx 로 서빙(HTTP Basic Auth 뒤).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta

try:
    import yaml
except Exception:                       # pragma: no cover
    yaml = None

from analytics import parser
from analytics.dashboard import DASHBOARD_HTML

CONFIG_PATH = "config/analytics.yaml"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS site_daily (
  date TEXT PRIMARY KEY, pv INTEGER, uniq INTEGER, bots INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS path_daily (
  date TEXT, path TEXT, pv INTEGER, uniq INTEGER,
  PRIMARY KEY (date, path)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@contextmanager
def _db(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _mask_ip(ip: str) -> str:
    if not ip or ip == "-":
        return "—"
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + ":…"
    p = ip.split(".")
    return ".".join(p[:3]) + ".x" if len(p) == 4 else ip


def _page_label(path: str) -> str:
    if path == "/" or path == "":
        return "홈 (/)"
    if path.startswith("/compare/"):
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        return slug.replace("-", " ")
    return path.rstrip("/") or path


def load_config() -> dict:
    if yaml is None:
        raise RuntimeError("pyyaml 필요")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- GSC 색인 현황 (ingest DB = metrics.db) --------------------------------
GSC_DB = "engine/store/metrics.db"

# 색인 파이프라인 버킷: 구글 verdict/coverageState → 사람이 읽는 단계
_BUCKET_META = [
    ("indexed",    "색인 완료",        "ok"),
    ("crawled",    "크롤됨·색인 보류",  "wn"),
    ("discovered", "발견·미크롤",      "mut"),
    ("duplicate",  "중복·정규화",      "mut"),
    ("unknown",    "미발견",           "mut"),
    ("other",      "기타",             "mut"),
]


def _url_path(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url or "") or "/"


def _cov_bucket(verdict: str, coverage: str) -> str:
    if (verdict or "").upper() == "PASS":
        return "indexed"
    c = (coverage or "").lower()
    if "unknown" in c:
        return "unknown"
    if "crawled" in c and "not indexed" in c:
        return "crawled"
    if "discovered" in c:
        return "discovered"
    if "duplicate" in c or "alternate" in c or "canonical" in c:
        return "duplicate"
    return "other"


def _gsc_payload():
    """ingest DB(metrics.db)의 색인 상태·검색 성과 → 대시보드 payload. DB/테이블/데이터 없으면 None."""
    if not os.path.exists(GSC_DB):
        return None
    try:
        conn = sqlite3.connect(f"file:{GSC_DB}?mode=ro", uri=True)
    except Exception:
        return None
    try:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                            "AND name='index_status'").fetchone():
            return None
        dates = [d for (d,) in conn.execute(
            "SELECT DISTINCT date FROM index_status ORDER BY date")]
        if not dates:
            return None
        latest, first = dates[-1], dates[0]

        def snap(day):
            return conn.execute(
                "SELECT url,verdict,coverage_state,last_crawl FROM index_status "
                "WHERE date=? ORDER BY url", (day,)).fetchall()

        def counts(rows):
            out = {}
            for _u, verdict, cov, _lc in rows:
                b = _cov_bucket(verdict, cov)
                out[b] = out.get(b, 0) + 1
            return out

        latest_rows, first_rows = snap(latest), snap(first)
        cl, cf = counts(latest_rows), counts(first_rows)
        buckets = [{"key": k, "label": lbl, "cls": cls,
                    "count": cl.get(k, 0), "prev": cf.get(k, 0)}
                   for k, lbl, cls in _BUCKET_META if cl.get(k, 0) or cf.get(k, 0)]
        pages = [{"label": _page_label(_url_path(u)), "bucket": _cov_bucket(v, cov),
                  "coverage": cov or "—", "last_crawl": (lc or "")[:10] or "—"}
                 for u, v, cov, lc in latest_rows]
        # 검색 성과: 최신 수집일의 query 차원 합계
        mdate = (conn.execute("SELECT MAX(date) FROM metrics "
                              "WHERE source='search_console'").fetchone() or [None])[0]
        clicks = impr = 0
        if mdate:
            clicks = (conn.execute(
                "SELECT COALESCE(SUM(value),0) FROM metrics WHERE source='search_console' "
                "AND dimension='query' AND metric='clicks' AND date=?", (mdate,)).fetchone() or [0])[0]
            impr = (conn.execute(
                "SELECT COALESCE(SUM(value),0) FROM metrics WHERE source='search_console' "
                "AND dimension='query' AND metric='impressions' AND date=?", (mdate,)).fetchone() or [0])[0]
        return {
            "first_date": first, "latest_date": latest, "total": len(latest_rows),
            "indexed": cl.get("indexed", 0), "crawled": cl.get("crawled", 0),
            "unknown": cl.get("unknown", 0), "buckets": buckets, "pages": pages,
            "search": {"clicks": int(clicks), "impressions": int(impr),
                       "has_data": (clicks or impr) > 0},
        }
    except Exception:
        return None
    finally:
        conn.close()


# --- 집계 ------------------------------------------------------------------
def _rollups(hits):
    """현재 로그에 있는 방문에서 (site_daily, path_daily) 롤업 계산."""
    site_pv = Counter()
    site_ip = defaultdict(set)
    site_bots = Counter()
    path_pv = Counter()
    path_ip = defaultdict(set)
    for h in hits:
        d = h.date
        if h.audience == "human" and h.category == "content":
            site_pv[d] += 1
            site_ip[d].add(h.ip)
            path_pv[(d, h.path)] += 1
            path_ip[(d, h.path)].add(h.ip)
        elif h.audience == "bot" and h.category != "asset":
            site_bots[d] += 1
    site = {d: (site_pv[d], len(site_ip[d]), site_bots.get(d, 0))
            for d in set(site_pv) | set(site_bots)}
    paths = {k: (path_pv[k], len(path_ip[k])) for k in path_pv}
    return site, paths


def _persist(conn, site, paths, hits, now_iso):
    for d, (pv, uniq, bots) in site.items():
        conn.execute(
            "INSERT INTO site_daily(date,pv,uniq,bots,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET pv=excluded.pv,uniq=excluded.uniq,"
            "bots=excluded.bots,updated_at=excluded.updated_at",
            (d, pv, uniq, bots, now_iso))
    for (d, path), (pv, uniq) in paths.items():
        conn.execute(
            "INSERT INTO path_daily(date,path,pv,uniq) VALUES(?,?,?,?) "
            "ON CONFLICT(date,path) DO UPDATE SET pv=excluded.pv,uniq=excluded.uniq",
            (d, path, pv, uniq))
    # first_seen(최초 집계일) 유지
    dates = [h.date for h in hits]
    if dates:
        first = min(dates)
        row = conn.execute("SELECT value FROM meta WHERE key='first_seen'").fetchone()
        if row is None or first < row[0]:
            conn.execute("INSERT INTO meta(key,value) VALUES('first_seen',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (first,))
    conn.execute("INSERT INTO meta(key,value) VALUES('last_run',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now_iso,))


def _trend(conn, days: int, today: date):
    rows = dict((d, (pv, uniq, bots)) for d, pv, uniq, bots in
                conn.execute("SELECT date,pv,uniq,bots FROM site_daily").fetchall())
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        pv, uniq, bots = rows.get(d, (0, 0, 0))
        out.append({"date": d, "pv": pv, "uniq": uniq, "bots": bots})
    return out


_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?")


def _read_tail(path: str, nbytes: int = 8192) -> str:
    with open(path, "rb") as f:
        f.seek(0, 2)
        sz = f.tell()
        f.seek(max(0, sz - nbytes))
        return f.read().decode("utf-8", "replace")


def _job_status(job: dict, now: datetime) -> dict:
    """잡 로그 tail 로 마지막 실행 시각 + 성공/실패/지연 판정(비침투 — 크론/스크립트 수정 없음)."""
    out = {"state": "unknown", "last_run": None, "stale": False}
    log = job.get("log")
    if not log or not os.path.exists(log):
        return out
    try:
        tail = _read_tail(log)
    except Exception:
        return out
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return out
    # 마지막 실행 시각: 로그의 마지막 타임스탬프, 없으면 파일 mtime
    ts = None
    for ln in reversed(lines):
        m = _TS_RE.search(ln)
        if m:
            ts = f"{m.group(1)} {m.group(2)}{m.group(3) or ':00'}"
            break
    if ts is None:
        ts = datetime.fromtimestamp(os.path.getmtime(log)).strftime("%Y-%m-%d %H:%M:%S")
    out["last_run"] = ts
    # 마지막 실행 구간 분리(멀티라인 잡은 start_marker 이후, 단일라인 잡은 최근 12줄)
    start = job.get("start_marker")
    if start and any(start in ln for ln in lines):
        idx = max(i for i, ln in enumerate(lines) if start in ln)
        seg = lines[idx:]
    else:
        seg = lines[-12:]
    segtext = "\n".join(seg)
    fail_marker = job.get("fail_marker")
    ok_marker = job.get("ok_marker", "")
    if ("Traceback (most recent call last)" in segtext) or (fail_marker and fail_marker in segtext):
        out["state"] = "fail"
    elif (not ok_marker) or any(ok_marker in ln for ln in seg):
        out["state"] = "ok"
    else:
        out["state"] = "unknown"
    # 지연: 예상 주기(max_stale_min)보다 오래 미실행이면 경고(크론 중단 감지)
    try:
        lr = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        mx = int(job.get("max_stale_min", 0) or 0)
        if mx and (now - lr).total_seconds() > mx * 60:
            out["stale"] = True
    except Exception:
        pass
    return out


def _batch_payload(cfg: dict, now: datetime) -> dict:
    """운영 배치 주기 + 최근 성공/실패 → 대시보드 payload(로그/마커 등 내부 필드는 클라이언트로 안 보냄)."""
    bj = cfg.get("batch_jobs") or {}
    jobs = []
    for j in (bj.get("jobs") or []):
        st = _job_status(j, now)
        jobs.append({"name": j.get("name"), "schedule": j.get("schedule"),
                     "cron": j.get("cron"), "detail": j.get("detail"), **st})
    return {"note": bj.get("note", ""), "jobs": jobs}


def _top_pages(conn, limit=40):
    rows = conn.execute(
        "SELECT path, SUM(pv) pv, SUM(uniq) vd, MAX(date) last "
        "FROM path_daily GROUP BY path ORDER BY pv DESC LIMIT ?", (limit,)).fetchall()
    return [{"path": p, "label": _page_label(p), "pv": int(pv),
             "visitor_days": int(vd), "last": last} for p, pv, vd, last in rows]


def run(cfg_all=None) -> str:
    """analytics 파이프라인 실행. 반환: 기록한 data.json 경로."""
    cfg = load_config()
    out_dir = cfg["output"]["dir"]
    db_path = cfg["output"].get("db", "engine/store/analytics.db")
    recent_limit = int(cfg["output"].get("recent_limit", 200))
    trend_days = int(cfg["output"].get("trend_days", 90))
    domain = cfg.get("site", {}).get("domain", "stack.utilverse.info")
    excl = cfg.get("exclude", {})

    hits = parser.collect(cfg)
    now = datetime.now()
    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
    today = now.date()

    site, paths = _rollups(hits)
    with _db(db_path) as conn:
        _persist(conn, site, paths, hits, now_iso)
        trend = _trend(conn, trend_days, today)
        top_pages = _top_pages(conn)
        first_seen = (conn.execute("SELECT value FROM meta WHERE key='first_seen'").fetchone() or [None])[0]
        all_time_pv = (conn.execute("SELECT COALESCE(SUM(pv),0) FROM site_daily").fetchone() or [0])[0]

    # --- 로그 보존 윈도우 기반 상세(리퍼러·디바이스·최근·봇) ---
    human = [h for h in hits if h.audience == "human" and h.category == "content"]
    bots = [h for h in hits if h.audience == "bot" and h.category != "asset"]
    self_hits = [h for h in hits if h.audience == "self"]

    def _win(items, days):
        cut = today - timedelta(days=days - 1)
        return [h for h in items if h.ts.date() >= cut]

    def _sum_pv(items):
        return len(items)

    def _uniq(items):
        return len({h.ip for h in items})

    h7, h30 = _win(human, 7), _win(human, 30)
    today_hits = [h for h in human if h.ts.date() == today]

    hourly = [0] * 24
    for h in h7:
        hourly[h.hour] += 1

    ref = Counter(h.ref_host for h in h30 if h.ref_host not in ("(internal)",))
    referrers = [{"host": k, "count": v} for k, v in ref.most_common(15)]

    dev = Counter(h.device for h in h30)
    devices = {k: dev.get(k, 0) for k in ("desktop", "mobile", "tablet", "other")}
    brw = Counter(h.browser for h in h30)
    browsers = [{"name": k, "count": v} for k, v in brw.most_common(8)]

    recent = [{
        "t": h.ts.strftime("%m-%d %H:%M"),
        "path": h.path, "label": _page_label(h.path),
        "status": h.status, "device": h.device, "browser": h.browser,
        "ref": h.ref_host, "ip": _mask_ip(h.ip),
    } for h in sorted(human, key=lambda x: x.ts, reverse=True)[:recent_limit]]

    def _bot_name(ua):
        u = (ua or "").lower()
        for key in ("googlebot", "bingbot", "adsbot", "mediapartners", "yandex", "duckduck",
                    "applebot", "petalbot", "semrush", "ahrefs", "mj12", "dotbot", "bytespider",
                    "gptbot", "claudebot", "ccbot", "amazonbot", "facebookexternalhit",
                    "censys", "zgrab", "python-requests", "curl", "wget", "go-http", "masscan", "nmap"):
            if key in u:
                return key
        return "기타봇/스캐너"
    bot_ct = Counter(_bot_name(h.ua) for h in _win(bots, 30))
    bot_top = [{"name": k, "count": v} for k, v in bot_ct.most_common(12)]

    data = {
        "generated_at": now_iso,
        "domain": domain,
        "first_seen": first_seen,
        "exclude": {"cookie": excl.get("cookie_name", "noana"),
                     "ips": excl.get("ips") or []},
        "summary": {
            "today_pv": _sum_pv(today_hits),
            "pv_7d": _sum_pv(h7), "uniq_7d": _uniq(h7),
            "pv_30d": _sum_pv(h30), "uniq_30d": _uniq(h30),
            "all_time_pv": int(all_time_pv),
            "bots_7d": len(_win(bots, 7)),
            "self_excluded": len(self_hits),
        },
        "trend": trend,
        "top_pages": top_pages,
        "hourly": hourly,
        "referrers": referrers,
        "devices": devices,
        "browsers": browsers,
        "recent": recent,
        "bots": bot_top,
        "batch": _batch_payload(cfg, now),   # 운영 배치 주기 + 최근 성공/실패/지연 — '데이터 수집 주기' 패널
        "gsc": _gsc_payload(),               # GSC 색인 현황(색인 파이프라인 단계·페이지별 상태·검색 성과)
    }

    os.makedirs(out_dir, exist_ok=True)
    data_path = os.path.join(out_dir, "data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(DASHBOARD_HTML)

    print(f"analytics: hits={len(hits)} human={len(human)} bot={len(bots)} self={len(self_hits)} "
          f"| pv_7d={data['summary']['pv_7d']} uniq_7d={data['summary']['uniq_7d']} "
          f"all_time_pv={all_time_pv} → {data_path}")
    return data_path


if __name__ == "__main__":
    run()
