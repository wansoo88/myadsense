# -*- coding: utf-8 -*-
"""repo — GitHub 저장소 활동. 최근 N일 커밋 수·릴리스 수(정식/프리릴리스 구분), 마지막 커밋일, 최신 정식 릴리스,
오픈 이슈·PR 수, 스타, 라이선스. 저장소를 클론하지 않는다 — GitHub REST API 만 읽는다.

호출 수를 아낀다(무인증 60회/시간): 커밋 수는 `per_page=1` 응답의 Link 헤더 `rel="last"` 페이지 번호로 센다(1회),
오픈 PR = 저장소의 open_issues_count(이슈+PR) − search 로 센 순수 이슈 수(1회). 저장소당 5회.
GITHUB_TOKEN 환경변수가 있으면 붙인다. 403/429 는 상태코드와 함께 error 로 남긴다(지어내지 않는다).

정의(캡션 인용용):
- commits_{N}d  : 기본 브랜치에서 측정일 기준 N일 이내 커밋 수 (GitHub `since`). `windows: [90, 365]` 로 창을 여럿 둘 수 있다.
- releases_{N}d : N일 이내 published 된 GitHub Release 수. `stable` 은 prerelease=false, `pre` 는 true.
                  `release_tag_prefix` 가 있으면 그 접두사의 태그만 센다(예: orca 의 mobile-android-* 제외).
- last_commit   : 기본 브랜치 최신 커밋의 committer date.
- commit_weekly_52 : `weekly: true` 인 저장소만. GitHub stats/participation 의 최근 52주 주간 커밋 수(전체 기여자). 시계열 글의 표와 같은 원자료.
- open_issues / open_prs : 측정 시각의 열린 이슈 / 열린 PR 수. has_issues=false 면 그 저장소는 이슈 기능을 꺼 둔 것(0 이 아니라 "off").
"""
from __future__ import annotations
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


def _p(msg: str):
    """콘솔 인코딩(cp949)에 없는 글자로 죽지 않게."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _headers():
    h = {"User-Agent": "utilverse-measure/1.0", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get(url: str, timeout: int = 30):
    """(status, json, headers). HTTP 에러도 상태코드를 돌려준다."""
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = {}
        return e.code, body, dict(e.headers or {})


def _last_page(headers: dict) -> int | None:
    link = headers.get("Link") or headers.get("link") or ""
    m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
    return int(m.group(1)) if m else None


def measure_repo(r: dict, windows: list, sinces: dict) -> dict:
    """windows: [90, 365] 같은 일수 목록. sinces: {days: ISO since}. 첫 창이 대표(days)."""
    days, since = windows[0], sinces[windows[0]]
    row = {"key": r["key"], "label": r["label"], "github": r["github"], "days": days, "windows": list(windows)}
    st, meta, _ = _get(f"{API}/repos/{r['github']}")
    if st != 200:
        row["error"] = f"repos: HTTP {st} {str(meta.get('message', ''))[:80]}"
        _p(f"  {r['label']:<22} {row['error']}")
        return row
    full = meta.get("full_name") or r["github"]
    row.update({"repo": full, "url": meta.get("html_url"), "stars": meta.get("stargazers_count"),
                "license": (meta.get("license") or {}).get("spdx_id"), "archived": meta.get("archived"),
                "default_branch": meta.get("default_branch"), "issues_and_prs_open": meta.get("open_issues_count"),
                "has_issues": meta.get("has_issues")})
    # 최신 커밋
    st, commits, _ = _get(f"{API}/repos/{full}/commits?per_page=1")
    if st == 200 and commits:
        row["last_commit"] = ((commits[0].get("commit") or {}).get("committer") or {}).get("date", "")[:10]
    else:
        row["last_commit"] = None
        row.setdefault("warnings", []).append(f"commits: HTTP {st}")
    # N일 커밋 수 — per_page=1 의 last 페이지 번호 (창마다 1회)
    for d in windows:
        st, cs, hdr = _get(f"{API}/repos/{full}/commits?since={sinces[d]}&per_page=1")
        if st == 200:
            n = _last_page(hdr)
            row[f"commits_{d}d"] = (n if n is not None else len(cs))
        else:
            row[f"commits_{d}d"] = None
            row.setdefault("warnings", []).append(f"commits since {d}d: HTTP {st}")
    # 릴리스
    st, rels, _ = _get(f"{API}/repos/{full}/releases?per_page=100")
    if st == 200:
        pref = r.get("release_tag_prefix") or ""
        rels = [x for x in rels if str(x.get("tag_name", "")).startswith(pref)]
        for d in windows:
            recent = [x for x in rels if (x.get("published_at") or "") >= sinces[d]]
            row[f"releases_{d}d_stable"] = sum(1 for x in recent if not x.get("prerelease"))
            row[f"releases_{d}d_pre"] = sum(1 for x in recent if x.get("prerelease"))
        stable = [x for x in rels if not x.get("prerelease") and not x.get("draft")]
        if stable:
            row["latest_release"] = stable[0].get("tag_name")
            row["latest_release_date"] = (stable[0].get("published_at") or "")[:10]
        row["releases_listed"] = len(rels)   # 100 이면 잘렸을 수 있다
    else:
        for d in windows:
            row[f"releases_{d}d_stable"] = row[f"releases_{d}d_pre"] = None
        row.setdefault("warnings", []).append(f"releases: HTTP {st}")
    # 52주 주간 커밋(stats/participation — 처음 호출은 202 "computing" 이 올 수 있어 잠깐 기다렸다 다시 읽는다)
    if r.get("weekly"):
        weekly = None
        for attempt in range(4):
            st, part, _ = _get(f"{API}/repos/{full}/stats/participation")
            if st == 200 and isinstance(part, dict) and isinstance(part.get("all"), list):
                weekly = part["all"]
                break
            if st != 202:
                row.setdefault("warnings", []).append(f"participation: HTTP {st}")
                break
            time.sleep(3)
        row["commit_weekly_52"] = weekly            # 오래된 주 → 최근 주 순, 52개
        row["commits_52w"] = sum(weekly) if weekly else None
    # 오픈 이슈(순수) — search 는 분당 10회 제한
    q = urllib.parse.quote(f"repo:{full} is:issue is:open")
    st, s, _ = _get(f"{API}/search/issues?q={q}&per_page=1")
    if st == 200 and "total_count" in s:
        row["open_issues"] = s["total_count"]
        if isinstance(row.get("issues_and_prs_open"), int):
            row["open_prs"] = max(row["issues_and_prs_open"] - s["total_count"], 0)
    else:
        row["open_issues"] = row["open_prs"] = None
        row.setdefault("warnings", []).append(f"search issues: HTTP {st}")
    _p(f"  {r['label']:<22} *{row.get('stars')} last={row.get('last_commit')} commits{days}d={row.get(f'commits_{days}d')} "
          f"rel{days}d={row.get(f'releases_{days}d_stable')}+{row.get(f'releases_{days}d_pre')}pre "
          f"latest={row.get('latest_release')} issues={row.get('open_issues')} prs={row.get('open_prs')} {row.get('warnings', '')}")
    return row


def run(cfg: dict, only=None) -> dict:
    windows = [int(d) for d in (cfg.get("windows") or [cfg.get("days", 90)])]
    now = datetime.datetime.now(datetime.timezone.utc)
    sinces = {d: (now - datetime.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ") for d in windows}
    rows = []
    for i, r in enumerate(cfg.get("repos", [])):
        if only and r["key"] not in only:
            continue
        if i:
            time.sleep(6.5)      # search API 무인증 10회/분
        try:
            rows.append(measure_repo(r, windows, sinces))
        except Exception as e:   # 한 저장소가 죽어도 나머지는 남긴다
            rows.append({"key": r["key"], "label": r["label"], "github": r["github"], "error": f"{type(e).__name__}: {str(e)[:120]}"})
            _p(f"  {r['label']:<22} ERROR {rows[-1]['error']}")
    return {"days": windows[0], "windows": windows, "since": {d: s[:10] for d, s in sinces.items()}, "rows": rows}
