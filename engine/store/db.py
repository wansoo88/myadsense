"""db.py — SQLite 저장소 (AUTOMATION.md §2 store). ingest 가 수집한 지표를 적재.

테이블:
  metrics(source, date, dimension, dim_value, metric, value, fetched_at)  — 범용 지표
  pages(slug, url, title, cluster, status, published_at)                  — 콘텐츠 추적
표준 라이브러리만 사용(sqlite3) — 의존성 없음, 오프라인 테스트 가능.
"""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = "engine/store/metrics.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
  source TEXT, date TEXT, dimension TEXT, dim_value TEXT,
  metric TEXT, value REAL, fetched_at TEXT,
  PRIMARY KEY (source, date, dimension, dim_value, metric)
);
CREATE TABLE IF NOT EXISTS pages (
  slug TEXT PRIMARY KEY, url TEXT, title TEXT, cluster TEXT,
  status TEXT, published_at TEXT
);
CREATE TABLE IF NOT EXISTS index_status (
  url TEXT, date TEXT, verdict TEXT, coverage_state TEXT,
  last_crawl TEXT, indexed INTEGER, fetched_at TEXT,
  PRIMARY KEY (url, date)
);
CREATE INDEX IF NOT EXISTS idx_metrics_src_metric ON metrics(source, metric, date);
CREATE INDEX IF NOT EXISTS idx_index_status_date ON index_status(date);
"""


@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as c:
        c.executescript(_SCHEMA)


def record_metrics(rows, fetched_at: str):
    """rows: iterable of (source, date, dimension, dim_value, metric, value). UPSERT."""
    data = [(s, d, dim, dv, m, float(v), fetched_at) for (s, d, dim, dv, m, v) in rows]
    if not data:
        return 0
    with connect() as c:
        c.executemany(
            "INSERT INTO metrics(source,date,dimension,dim_value,metric,value,fetched_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,date,dimension,dim_value,metric) "
            "DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at",
            data,
        )
    return len(data)


def upsert_page(slug, url, title, cluster, status, published_at):
    with connect() as c:
        c.execute(
            "INSERT INTO pages(slug,url,title,cluster,status,published_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(slug) DO UPDATE SET url=excluded.url,title=excluded.title,"
            "cluster=excluded.cluster,status=excluded.status,published_at=excluded.published_at",
            (slug, url, title, cluster, status, published_at),
        )


def record_index_status(rows, fetched_at: str):
    """rows: iterable of (url, date, verdict, coverage_state, last_crawl, indexed). UPSERT (url,date)."""
    data = [(u, d, v, cov, lc, int(idx), fetched_at) for (u, d, v, cov, lc, idx) in rows]
    if not data:
        return 0
    with connect() as c:
        c.executemany(
            "INSERT INTO index_status(url,date,verdict,coverage_state,last_crawl,indexed,fetched_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(url,date) DO UPDATE SET "
            "verdict=excluded.verdict,coverage_state=excluded.coverage_state,"
            "last_crawl=excluded.last_crawl,indexed=excluded.indexed,fetched_at=excluded.fetched_at",
            data,
        )
    return len(data)


def index_snapshot(date: str | None = None):
    """지정일(없으면 최신일)의 색인 상태 스냅샷: (total, indexed, not_indexed, rows). health/report 용."""
    with connect() as c:
        if date is None:
            row = c.execute("SELECT MAX(date) FROM index_status").fetchone()
            date = row[0] if row else None
        if not date:
            return (0, 0, 0, [])
        rows = c.execute(
            "SELECT url,verdict,coverage_state,indexed FROM index_status WHERE date=? ORDER BY url",
            (date,)).fetchall()
    total = len(rows)
    indexed = sum(1 for r in rows if r[3])
    return (total, indexed, total - indexed, rows)


def latest(source: str, metric: str, limit: int = 20):
    with connect() as c:
        return c.execute(
            "SELECT date,dim_value,value FROM metrics WHERE source=? AND metric=? "
            "ORDER BY date DESC LIMIT ?", (source, metric, limit)).fetchall()


def query(sql: str, params=()):
    """임의 SELECT (health·report 용). 결과 행 리스트."""
    with connect() as c:
        return c.execute(sql, params).fetchall()
