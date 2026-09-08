# -*- coding: utf-8 -*-
"""add_measurements.py — data/measurements/*.json 을 발행 큐(dist/queue) 글에 "What we measured" 섹션으로 주입한다.

- 글 ↔ 측정 매핑은 config/measure.yaml `articles:`. 표는 데이터가 있는 것만 그린다(없으면 그 표 생략, 표가 0이면 섹션 생략).
- 멱등: 섹션은 `<!-- measured:v1 -->` 표식으로 찾아 통째로 교체한다. 재측정하면 다시 돌리면 된다.
- 본문 산문은 건드리지 않는다. Sources 섹션 바로 앞에 넣고, 목차(데스크톱·모바일 2벌)에 링크를 더한다.
- 숫자는 전부 우리 측정값 + 잰 기계 + 날짜. 캡션이 측정 정의를 그대로 말한다(engine/measure/*.py docstring 과 동일).

  python scripts/add_measurements.py [--dry-run] [--only slug ...]     (리포 루트에서, 서버 큐 = 정본)
  python scripts/add_measurements.py --src dist/queue_server --dst dist/queue_patched --only <slug>
      (서버 큐 사본을 읽어 별도 디렉터리에 쓴다 — 워커가 서버에 손대지 않고 OPS 에 반영을 요청할 때)
"""
from __future__ import annotations
import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import yaml                                              # noqa: E402
from engine.measure import common                        # noqa: E402

QUEUE = "dist/queue"
MARK = "<!-- measured:v1 -->"
esc = html.escape


def _fmt(v, unit=""):
    if v is None:
        return "—"
    if isinstance(v, float) and v != int(v):
        return f"{v:,.1f}{unit}"
    return f"{int(v):,}{unit}"


def _host_line(prof: dict) -> str:
    return f"{esc(prof.get('description') or prof.get('role', ''))}; measured {esc(prof.get('date', ''))}"


def _table(head: list, rows: list, caption: str) -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<div class="tablewrap"><table class="tbl"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'
            f'<p class="mcap">{caption}</p>')


def latency_table(data, blk, per_host):
    out = []
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r.get("provider") in blk.get("providers", []) and r.get("reachable")]
        rows.sort(key=lambda r: (r.get("connect_ms") is None, r.get("connect_ms") or 0))
        if not rows:
            continue
        body = [[esc(r["region"]), esc(r["provider"]), _fmt(r["connect_ms"]), _fmt(r["ttfb_ms"])] for r in rows]
        cap = (f"TCP connect = time to complete the TCP handshake to the provider's regional endpoint (≈ round trip); "
               f"TTFB = HTTPS request to first response byte. Median of {payload.get('rounds')} samples each, from "
               f"{_host_line(payload['host'])}. Endpoints: DigitalOcean regional Spaces hosts, Vultr regional ping hosts.")
        out.append(_table(["Region", "Provider", "TCP connect (ms)", "TTFB (ms)"], body, cap))
    return "".join(out)


def throughput_table(data, blk, per_host):
    out = []
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r.get("provider") in blk.get("providers", []) and r.get("mbps") is not None]
        rows.sort(key=lambda r: -(r.get("mbps") or 0))
        if not rows:
            continue
        mb = round(payload.get("throughput_bytes", 0) / 1e6)
        body = [[esc(r["region"]), esc(r["provider"]), _fmt(r["mbps"])] for r in rows]
        cap = (f"Single-stream download of the first {mb} MB of the provider's public test file, MB/s (10⁶ bytes), "
               f"median of {payload.get('throughput_rounds')} runs from {_host_line(payload['host'])}. This is the speed "
               f"of one connection on one path at that moment, not the provider's capacity — DigitalOcean no longer "
               f"publishes test files, so only Vultr is shown.")
        out.append(_table(["Region", "Provider", "Download (MB/s)"], body, cap))
    return "".join(out)


def image_table(data, blk, per_host):
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r["key"] in blk.get("keys", []) and r.get("compressed_mb") is not None]
        if not rows:
            continue
        body = [[esc(r["label"]), _fmt(r["compressed_mb"], " MB"), esc(r.get("last_pushed") or "—"), f'<code>{esc(r["ref"])}</code>'] for r in rows]
        cap = (f"Compressed size of the linux/amd64 image as reported by the registry (what you download), and the date "
               f"the tag was last pushed; ghcr.io does not expose a push date. Read from the registry APIs, "
               f"{_host_line(payload['host'])}.")
        return _table(["Image", "Compressed size", "Last pushed", "Reference"], body, cap)
    return ""


def run_table(data, blk, per_host):
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r["key"] in blk.get("keys", []) and not r.get("error")]
        if not rows:
            continue
        body = [[esc(r["label"]), _fmt(r.get("pull_s"), " s"), _fmt(r.get("image_mb"), " MB"),
                 _fmt(r.get("first_200_s"), " s"), _fmt(r.get("idle_mem_mb"), " MB")] for r in rows]
        cap = (f"We pulled the official image and started it with <code>docker run</code>: pull time, image size on disk, "
               f"seconds from start until the app answered HTTP, and container memory after {payload.get('settle_seconds')} s idle "
               f"(<code>docker stats</code>). Docker {esc(payload.get('docker_server', ''))} on {_host_line(payload['host'])}.")
        return _table(["App", "Pull", "Image on disk", "First HTTP response", "Idle memory"], body, cap)
    return ""


def release_table(data, blk, per_host):
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r["key"] in blk.get("keys", []) and r.get("mb") is not None]
        if not rows:
            continue
        body = []
        for r in rows:
            src = r.get("source") or ""
            body.append([esc(r["label"]), esc(str(r.get("version") or "—")), esc(r.get("published") or "—"),
                         _fmt(r["mb"], " MB"), f'<a href="{esc(src)}" rel="noopener" target="_blank">{esc(r.get("asset") or "download")}</a>' if src else esc(r.get("asset") or "")])
        cap = (f"Current Windows installer (or package) as published by each vendor — version, release date and file size "
               f"read from GitHub Releases, the vendor's download endpoint or PyPI on {esc(payload['host'].get('date', ''))}. "
               f"No file was downloaded; sizes are the published byte counts.")
        return _table(["App", "Version", "Released", "Installer size", "File"], body, cap)
    return ""


def desktop_table(data, blk, per_host):
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r["key"] in blk.get("keys", []) and r.get("installed")]
        if not rows:
            continue
        body = [[esc(r["label"]), esc(r.get("version") or "—"), _fmt(r.get("footprint_mb"), " MB"),
                 _fmt(r.get("cold_start_s"), " s"), (_fmt(r.get("idle_rss_mb"), " MB") + (f" ({r.get('process_count')} processes)" if r.get("process_count") else ""))]
                for r in rows]
        fresh = [r["label"] for r in rows if r.get("fresh_profile")]
        fresh_s = ("" if not fresh else
                   f" {esc(' and '.join(fresh))} {'was' if len(fresh) == 1 else 'were'} launched with an empty profile "
                   f"(<code>--user-data-dir</code>), no extensions and no folder open, so the numbers do not include any workspace.")
        cap = (f"Install footprint = size of the application directory (user data excluded). Cold start = seconds from "
               f"launching the executable until its first visible window, measured once after closing the app. Idle memory = "
               f"resident memory of the whole process tree {payload.get('settle_seconds')} s after the window appeared.{fresh_s} "
               f"{_host_line(payload['host'])}.")
        figs = ""
        for r in rows:
            if r.get("screenshot"):
                fn = os.path.basename(r["screenshot"])
                figs += (f'<figure class="mshot"><img src="/measure/{esc(fn)}" alt="{esc(r["label"])} on our laptop" loading="lazy">'
                         f'<figcaption>{esc(r["label"])} {esc(r.get("version") or "")} as it opened on our laptop, {esc(payload["host"].get("date", ""))}.</figcaption></figure>')
        return _table(["App", "Version", "Install footprint", "Cold start", "Idle memory"], body, cap) + figs
    return ""


def repo_table(data, blk, per_host):
    for role, payload in per_host.items():
        rows = [r for r in payload.get("rows", []) if r["key"] in blk.get("keys", []) and not r.get("error")]
        if not rows:
            continue
        d = blk.get("days") or payload.get("days") or 90
        with_tags = any(r.get("release_tag_commits") for r in rows)
        body = []
        for r in rows:
            rel = r.get(f"releases_{d}d_stable")
            pre = r.get(f"releases_{d}d_pre") or 0
            rel_s = "—" if rel is None else (f"{rel}" + (f" (+{pre} pre)" if pre else ""))
            latest = (esc(r.get("latest_release") or "—") + (f" · {esc(r.get('latest_release_date'))}" if r.get("latest_release_date") else ""))
            issues = ("—" if r.get("open_issues") is None else
                      (f"issues off / {_fmt(r.get('open_prs'))}" if r.get("has_issues") is False else f"{_fmt(r['open_issues'])} / {_fmt(r.get('open_prs'))}"))
            url = r.get("url") or f"https://github.com/{r.get('repo') or r.get('github')}"
            cells = [f'<a href="{esc(url)}" rel="noopener" target="_blank">{esc(r["label"])}</a>', _fmt(r.get("stars")),
                     esc(r.get("last_commit") or "—"), _fmt(r.get(f"commits_{d}d")), rel_s, latest, issues, esc(r.get("license") or "—")]
            if with_tags:
                tc = r.get("release_tag_commits") or []
                cells.append("<br>".join(f'{esc(t["tag"])} → <code>{esc(t["sha"] or "?")}</code> ({esc(t["commit_date"] or "?")})' for t in tc) or "—")
            body.append(cells)
        since = (payload.get("since") or {}).get(str(d)) or (payload.get("since") or {}).get(d) or ""
        cap = (f"Read from the GitHub API on {esc(payload['host'].get('date', ''))}: stars; the date of the newest commit on the default branch; "
               f"commits on that branch and releases published in the {d} days ending that day ({esc(since)} → {esc(payload['host'].get('date', ''))}), "
               f"pre-releases counted separately; open issues and open pull requests at that moment (\"issues off\" = the project does not use GitHub issues); and the license GitHub detects. "
               f"Commit counts are the repository's own history, so squash-merged projects show fewer commits than merge-heavy ones."
               + (" \"Newest release tags → commit\" resolves each of the newest stable release tags to the commit it points at and that commit's date, "
                  "read the same day — it shows whether releases are being cut from new code on the default branch." if with_tags else ""))
        head = ["Repository", "Stars", "Last commit", f"Commits ({d} d)", f"Releases ({d} d)", "Latest release", "Open issues / PRs", "License"]
        if with_tags:
            head.append("Newest release tags → commit")
        return _table(head, body, cap)
    return ""


def price_table(data, blk, per_host, slug=None):
    """config/prices.yaml observations[] (관측 가격 + 관측일 + 출처)를 그 글의 표로. 값이 없는 벤더는 'not published' 로 남긴다."""
    try:
        with open("config/prices.yaml", encoding="utf-8") as f:
            pr = yaml.safe_load(f) or {}
    except OSError:
        return ""
    meta = pr.get("meta") or {}
    cards = [c for c in (pr.get("observations") or []) if c.get("slug") == slug]   # cards[] 는 카드 패치용, observations[] 가 이 표의 출처
    if not cards:
        return ""
    body = []
    for c in cards:
        price = c.get("price") or ("not published" if c.get("unverified") else "—")
        note = f' <span class="mnote">({esc(c["note"])})</span>' if c.get("note") else ""
        src = c.get("source") or ""
        body.append([esc(c.get("plan", "")), esc(price) + note, esc(str(c.get("as_of") or meta.get("as_of") or "")),
                     f'<a href="{esc(src)}" rel="noopener" target="_blank">{esc(src.replace("https://", "").split("/")[0])}</a>' if src else "—"])
    dates = sorted({str(c.get("as_of") or meta.get("as_of") or "") for c in cards})
    cap = (f"Prices as shown on each vendor's own pricing page on the date in the third column ({', '.join(esc(x) for x in dates if x)}). "
           f"Where a vendor publishes no figure we say so rather than estimate. Vendors change prices without notice; the linked page is authoritative.")
    return _table(["Plan", "Observed price", "Checked", "Source"], body, cap)


def cli_table(data, blk, per_host):
    for role, payload in per_host.items():
        rows = [r for r in payload.get("cli", []) if r["key"] in blk.get("keys", []) and r.get("installed")]
        if not rows:
            continue
        body = [[esc(r["label"]), esc(r.get("version") or "—"), _fmt(r.get("footprint_mb"), " MB"),
                 ("—" if r.get("run_s") is None else f"{r['run_s']:.2f} s")] for r in rows]
        cap = (f"Install footprint = size of the install directory; run = fastest of 3 runs of <code>--version</code> "
               f"(process start to exit). {_host_line(payload['host'])}.")
        return _table(["Tool", "Version", "Install footprint", "Run (--version)"], body, cap)
    return ""


# 섹션 제목은 config 가 아니라 **실제로 그려진 표**에서 만든다(ORDER 55 B0, 2026-09-08 REVIEW 부수발견):
# config 의 title 이 "pulled and started"·"cold start" 를 말하는데 표는 레지스트리 크기뿐인 글이 4/5편이었다.
# 표가 없으면 그 문구도 없다 — 데이터가 늘면 제목도 그만큼만 늘어난다.
PHRASES = {"latency_table": "latency to each region", "throughput_table": "download speed",
           "image_table": "image size", "run_table": "cold start and idle memory",
           "release_table": "installer size", "desktop_table": "install footprint, cold start and idle memory",
           "cli_table": "install footprint and startup time", "repo_table": "repository activity",
           "price_table": "prices on the day we looked"}


def derive_title(kinds: list) -> str:
    """그려진 표 종류(순서 유지·중복 제거)로 'What we measured: a, b and c' 를 만든다.
    데스크톱 표가 있으면 CLI 표의 문구는 'startup time' 만(footprint 중복 방지). 문구 안에 쉼표가 있으면 세미콜론으로 잇는다."""
    seen, ph = set(), []
    has_desktop = "desktop_table" in kinds
    for k in kinds:
        p = "startup time" if (k == "cli_table" and has_desktop) else PHRASES.get(k, k)
        if p not in seen:
            seen.add(p)
            ph.append(p)
    if not ph:
        return "What we measured"
    sep = "; " if any("," in p for p in ph) else ", "
    if len(ph) == 1:
        body = ph[0]
    elif len(ph) == 2:
        body = f"{ph[0]}; {ph[1]}" if sep == "; " else f"{ph[0]} and {ph[1]}"
    else:
        body = sep.join(ph[:-1]) + f"{sep}and {ph[-1]}"
    return f"What we measured: {body}"


INTRO = ("<p>The figures below were collected by us on the dates shown, not taken from vendor marketing. "
         "Each table says what was read or measured, on which machine, and when.</p>")

KINDS = {"latency_table": latency_table, "throughput_table": throughput_table, "image_table": image_table,
         "run_table": run_table, "release_table": release_table, "desktop_table": desktop_table, "cli_table": cli_table,
         "repo_table": repo_table, "price_table": price_table}


def section_for(slug: str, art: dict, data: dict) -> str | None:
    parts, kinds = [], []
    for blk in art.get("blocks", []):
        if blk["kind"] == "price_table":                  # 측정 파일이 아니라 config/prices.yaml 이 출처
            h = price_table(data, blk, {}, slug=slug)
            if h:
                parts.append(h)
                kinds.append("price_table")
            continue
        per_host = data.get(blk["suite"]) or {}
        if not per_host:
            continue
        h = KINDS[blk["kind"]](data, blk, per_host)
        if h:
            parts.append(h)
            kinds.append(blk["kind"])
    if not parts:
        return None
    # config 의 title 은 더 이상 쓰지 않는다 — 표가 없는 것을 제목이 약속하던 결함(B0). 제목은 그려진 표에서만 나온다.
    return (f'<section class="blk" id="measured">{MARK}<h2>{esc(derive_title(kinds))}</h2>'
            f'{INTRO}{"".join(parts)}</section>')


def inject(doc: str, sec: str) -> tuple[str, str]:
    if MARK in doc:
        doc = re.sub(r'<section class="blk" id="measured">.*?</section>', lambda m: sec, doc, count=1, flags=re.S)
        how = "replaced"
    elif '<section class="sources"' in doc:
        doc = doc.replace('<section class="sources"', sec + '<section class="sources"', 1)
        how = "inserted before sources"
    else:
        doc = doc.replace('<div class="authorbox">', sec + '<div class="authorbox">', 1)
        how = "inserted before authorbox"
    if 'href="#measured"' not in doc:
        doc = doc.replace('<a href="#sources">', '<a href="#measured">What we measured</a><a href="#sources">')
    return doc, how


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--src", default=QUEUE, help="읽을 큐 디렉터리(기본 dist/queue)")
    ap.add_argument("--dst", default=None, help="쓸 디렉터리(기본 = --src 제자리)")
    a = ap.parse_args(argv)
    dst = a.dst or a.src
    os.makedirs(dst, exist_ok=True)
    with open("config/measure.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    data = common.load_all()
    print("measurements loaded:", {k: list(v) for k, v in data.items()})
    n = 0
    for slug, art in (cfg.get("articles") or {}).items():
        if a.only and slug not in a.only:
            continue
        path = os.path.join(a.src, slug + ".html")
        out_path = os.path.join(dst, slug + ".html")
        if os.path.isfile(out_path) and dst != a.src:      # 같은 글에 다른 패치가 먼저 쌓였으면 그 위에 쌓는다
            path = out_path
        if not os.path.isfile(path):
            print(f"  - {slug[:60]}: 큐에 없음(내려감?) — 건너뜀")
            continue
        sec = section_for(slug, art, data)
        if not sec:
            print(f"  - {slug[:60]}: 데이터 없음 — 섹션 없음")
            continue
        doc = open(path, encoding="utf-8").read()
        new, how = inject(doc, sec)
        if not a.dry_run and (new != doc or out_path != path):
            open(out_path, "w", encoding="utf-8", newline="").write(new)
        print(f"  ✓ {slug[:60]}: {how} ({len(sec):,} chars){' [dry]' if a.dry_run else ''}")
        n += 1
    print(f"{'DRY ' if a.dry_run else ''}sections: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
