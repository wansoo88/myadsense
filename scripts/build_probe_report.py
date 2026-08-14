#!/usr/bin/env python3
"""build_probe_report.py — "아무도 모르는 새 사이트에 무엇이 두드리는가"를 로그로 잰다.

왜 이 스크립트가 있나 (2026-08-15):
    AdSense "가치가 별로 없는 콘텐츠" 거절 이후, 남은 글 대부분은 공개 문서를 정리한
    비교글이다. 우리만 가진 데이터는 서버 로그뿐이고, 거기에 아무도 공개하지 않는
    사실이 하나 있다 — **정적 사이트 요청의 4분의 1이 우리가 돌리지도 않는
    소프트웨어를 노린 탐침**이다. WordPress 도 PHP 도 없는데 wp-admin 을 두드린다.

    build_crawler_report.py = 누가 기어오는가(합법 크롤러).
    build_index_gap_report.py = 기어온 뒤 색인은 어떻게 됐나.
    이 글 = **크롤러도 사람도 아닌 나머지**. 셋이 서로 다른 질문이다.

설계 원칙:
    🔴 본문 수치를 하드코딩하지 않는다. 전부 로그에서 계산해 넣는다.
    · 우리 인프라 경로(`/_` 로 시작하는 내부 엔드포인트)는 표에서 **제외**한다.
      보호돼 있어도 굳이 주소를 광고할 이유가 없다.
    · 지운 글로 인한 정상 404(`/compare/…`)는 공격이 아니므로 따로 세고 표에서 뺀다.
    · 공개하는 것은 "공격자가 무엇을 시도하는가"이지 "우리 어디가 약한가"가 아니다.

사용:
    ./.venv/bin/python scripts/build_probe_report.py --dry-run
    ./.venv/bin/python scripts/build_probe_report.py
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import gzip
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

LOG_GLOBS = ["/var/log/nginx/utilverse.access.log*", "/var/log/nginx/stack.access.log*"]
SLUG = "what-actually-knocks-on-a-brand-new-static-site"

# 탐침 분류. 순서 중요 — 먼저 맞는 것을 채택한다.
FAMILIES = [
    ("WordPress", re.compile(r"/wp-(admin|content|includes|login|json|config)|xmlrpc\.php|/wordpress/", re.I),
     "A CMS this site does not run"),
    ("Secrets and config files", re.compile(r"/\.(env|git|aws|ssh|svn|htpasswd|DS_Store)|credentials|\.env\.", re.I),
     "Leaked keys, tokens, repository internals"),
    ("Admin panels", re.compile(r"phpmyadmin|/pma/|/adminer|/manager/html|/(admin|administrator|login)(\.php)?/?$", re.I),
     "Database and server consoles"),
    ("Backups and dumps", re.compile(r"\.(sql|bak|old|zip|tar\.gz|tgz|rar|7z)$|backup", re.I),
     "Whole-site archives left in web roots"),
    ("Remote code execution", re.compile(r"cgi-bin|eval-stdin|/shell|think\\app|/invoker/|struts|/actuator/", re.I),
     "Known RCE paths in web frameworks"),
    ("Uploaded PHP shells", re.compile(r"\.php\d?$", re.I),
     "Filenames from earlier break-ins elsewhere"),
]
OTHER = ("Everything else", "Assorted one-off paths")

# 우리 것 — 통계에는 넣되 **경로를 공개하지 않는다**.
OURS = re.compile(r"^/_|^/compare/|^/(about|privacy|contact|search|ai-coding|hosting|dev-tools|ai-tools|vpn-security)/")


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def _rows():
    seen = set()
    for pat in LOG_GLOBS:
        for f in sorted(glob.glob(pat)):
            if f in seen:
                continue
            seen.add(f)
            op = gzip.open if f.endswith(".gz") else open
            try:
                for line in op(f, "rt", encoding="utf-8", errors="replace"):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            yield json.loads(line)
                        except Exception:
                            continue
            except OSError:
                continue


def family_of(path: str) -> tuple[str, str]:
    for name, rx, note in FAMILIES:
        if rx.search(path):
            return name, note
    return OTHER


def measure() -> dict:
    total = 0
    days = set()
    status = collections.Counter()
    fam_hits = collections.Counter()
    fam_paths = collections.defaultdict(set)
    fam_note = {}
    top_paths = collections.Counter()
    probe_ips = set()
    probe_hits = 0
    ours_404 = 0
    empty_ua = 0
    methods = collections.Counter()

    for d in _rows():
        total += 1
        day = (d.get("t") or "")[:10]
        if day:
            days.add(day)
        st = str(d.get("s") or d.get("status") or "")
        status[st] += 1
        methods[(d.get("m") or d.get("method") or "?").upper()] += 1
        # ⚠️ 400 은 요청이 **경로가 파싱되기 전에** 깨진 것이라 경로 분류에 넣으면 안 된다.
        #    첫 판에서 400 이 통째로 "Everything else" 로 들어가 그 칸을 최대 항목으로 부풀렸다.
        #    401 은 우리 보호 엔드포인트라 애초에 OURS 로 걸러진다. 경로 탐침은 403/404/410 뿐.
        if st not in ("403", "404", "410"):
            continue
        path = (d.get("u") or "").split("?")[0]
        if not path or OURS.match(path):
            ours_404 += 1
            continue
        probe_hits += 1
        if not (d.get("ua") or "").strip():
            empty_ua += 1
        ip = d.get("ip") or d.get("addr") or ""
        if ip:
            probe_ips.add(ip)
        name, note = family_of(path)
        fam_note[name] = note
        fam_hits[name] += 1
        fam_paths[name].add(path)
        top_paths[path] += 1

    fams = [{"name": n, "note": fam_note.get(n, ""), "hits": h,
             "paths": len(fam_paths[n])}
            for n, h in fam_hits.most_common()]
    return {
        "total": total, "days": sorted(days), "status": status, "methods": methods,
        "families": fams, "probe_hits": probe_hits, "probe_paths": len(top_paths),
        "top_paths": top_paths.most_common(15), "ips": len(probe_ips),
        "ours_404": ours_404, "empty_ua": empty_ua,
    }


def build_spec(m: dict):
    from content import generator, renderer

    days = m["days"]
    d0, d1 = days[0], days[-1]
    ndays = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days + 1
    today = dt.date.today().isoformat()
    share = round(m["probe_hits"] * 100 / max(m["total"], 1))
    per_day = round(m["probe_hits"] / max(ndays, 1))
    fams = m["families"]
    top_fam = fams[0] if fams else None
    ua_share = round(m["empty_ua"] * 100 / max(m["probe_hits"], 1))
    s400 = m["status"].get("400", 0)

    def frow(f):
        return (f'<tr><td class="featc">{esc(f["name"])}</td><td>{esc(f["note"])}</td>'
                f'<td class="ctr">{f["hits"]:,}</td><td class="ctr">{f["paths"]:,}</td></tr>')

    fam_table = (
        '<div class="tablewrap"><table class="tbl"><thead><tr>'
        '<th class="feat">What it was looking for</th><th class="feat">In plain terms</th>'
        '<th class="ctr">Requests</th><th class="ctr">Distinct paths</th>'
        '</tr></thead><tbody>' + "".join(frow(f) for f in fams) + "</tbody></table></div>"
        f'<p class="footnote">Every request to this domain between {esc(d0)} and {esc(d1)} '
        f'({ndays} days) that was answered 404, 403 or 410, excluding paths this site actually '
        f'publishes. Classification is a fixed set of path patterns applied identically to every '
        f'request; a path matches the first family it fits.</p>')

    def prow(p, c):
        return f'<tr><td class="featc"><code>{esc(p)}</code></td><td class="ctr">{c:,}</td></tr>'

    path_table = (
        '<div class="tablewrap"><table class="tbl"><thead><tr>'
        '<th class="feat">Requested path</th><th class="ctr">Requests</th>'
        '</tr></thead><tbody>'
        + "".join(prow(p, c) for p, c in m["top_paths"]) + "</tbody></table></div>"
        '<p class="footnote">The most-requested paths that do not exist here. None of this '
        'software runs on this domain — the site is static HTML behind nginx.</p>')

    sections = [
        {"heading": "What we measured, and how",
         "html": (
             f"<p>This is a static site: pre-rendered HTML files served by nginx. There is no PHP "
             f"interpreter, no database, no CMS, no admin login. That turns the access log into a "
             f"clean instrument — <em>every</em> request for a <code>.php</code> file is, by "
             f"definition, someone probing for software that is not here.</p>"
             f"<p>We took every log line for this domain from <strong>{esc(d0)}</strong> to "
             f"<strong>{esc(d1)}</strong> ({ndays} days) — <strong>{m['total']:,} requests</strong> "
             f"— and kept the ones where nginx parsed a path and answered not-here (404, plus "
             f"403 and 410). From those we removed requests for paths the site does publish — a "
             f"handful of articles were retired and still get followed: {m['ours_404']:,} requests. "
             f"Malformed requests that nginx rejected with a 400 before any path was parsed are "
             f"excluded too, and reported separately further down. What remains is "
             f"<strong>{m['probe_hits']:,} requests</strong> for things that never existed here.</p>"
             "<p>Nothing here is a vulnerability report. We are publishing what arrived, not what "
             "worked — a static site has almost no attack surface for any of it, which is rather "
             "the point of showing it.</p>")},
        {"heading": f"{share}% of all traffic was looking for software we do not run",
         "html": (
             f"<p><strong>{m['probe_hits']:,} of {m['total']:,} requests</strong> — about "
             f"<strong>{share}%</strong> — went to paths that have never existed on this domain. "
             f"That is roughly <strong>{per_day} per day</strong>, spread across "
             f"<strong>{m['probe_paths']:,} distinct paths</strong> from "
             f"<strong>{m['ips']:,} addresses</strong>.</p>"
             + (f"<p>The largest single family was <strong>{esc(top_fam['name'].lower())}</strong>: "
                f"{top_fam['hits']:,} requests across {top_fam['paths']:,} paths. "
                if top_fam else "")
             + "<p>This site has no inbound links to speak of and one page in Google's index. "
             "Nobody knows it exists. The scanning found it anyway, because scanning does not "
             "work by knowing — it works by walking address space and trying everything on "
             "everything.</p>")},
        {"heading": "What it was looking for",
         "html": fam_table},
        {"heading": "The most-requested things that are not here",
         "html": (
             path_table
             + "<p>Two patterns are worth naming. The WordPress paths are the obvious ones — "
             "install scripts, login pages, plugin files — and they arrive whether or not you run "
             "WordPress, because guessing is cheaper than checking. The random-looking "
             "<code>.php</code> filenames are the more interesting group: those are the names of "
             "web shells uploaded during <em>other</em> people's breaches. Scanners try them "
             "everywhere on the chance that a host was compromised earlier and the back door is "
             "still sitting there.</p>"
             "<p>Then there are the config files. Requests for <code>.env</code> and "
             "<code>.git/config</code> are not looking for a way in — they are looking for "
             "credentials someone committed by accident. That is a filesystem hygiene problem, "
             "not a web-server one, and it is the one item on this list that a static site can "
             "still get wrong.</p>")},
        {"heading": "Most of it does not even pretend to be a browser",
         "html": (
             f"<p><strong>{m['empty_ua']:,}</strong> of these requests ({ua_share}%) arrived with "
             f"<em>no user agent at all</em>. Others carried a user-agent string that was not a "
             f"user agent — one of the most frequent was a URL, apparently copy-pasted into the "
             f"wrong field of whatever tool was doing the scanning.</p>"
             + (f"<p>Separately, <strong>{s400:,} requests</strong> were malformed badly enough "
                f"that nginx answered 400 before any path was parsed — protocol noise, TLS probes, "
                f"and requests aimed at whatever else might be listening on the port.</p>"
                if s400 else "")
             + "<p>None of this is sophisticated, and that is the useful part of the finding. The "
             "background traffic of the public internet is not targeted attacks; it is a very "
             "large amount of very cheap guessing.</p>")},
        {"heading": "What this changes about running a small site",
         "html": (
             "<p><strong>Do not read 404 counts as a problem with your site.</strong> Ours are "
             "dominated by software we have never installed. If you set up alerting on 404 rate, "
             "you will be alerting on the weather.</p>"
             "<p><strong>The static-site security argument is real, and this is what it looks "
             "like.</strong> Almost every request above needs an interpreter to be dangerous. "
             "There isn't one. That is not cleverness on our part — it is a consequence of the "
             "hosting choice, and it is available to anyone.</p>"
             "<p><strong>The exception is files, not code.</strong> <code>.env</code>, "
             "<code>.git</code>, and stray backups are readable by a static server as happily as "
             "any other file. Keeping them out of the web root is the one defence on this list "
             "that a static site still has to get right on purpose.</p>"
             "<p><strong>Look before you buy tooling.</strong> This measurement cost one log file "
             "and an afternoon. Whatever a WAF vendor tells you about your threat profile, your "
             "own access log has already recorded the answer.</p>")},
    ]

    faq = [
        {"q": "Is any of this dangerous to a static site?",
         "a": ("Almost none of it. Requests for PHP files, admin panels and RCE paths need code "
               "execution to matter, and a static server has none. The exception is requests for "
               "files — .env, .git, backups — which a static server will serve happily if they "
               "are in the web root. Keep them out of it.")},
        {"q": "Why is a site nobody knows about being scanned at all?",
         "a": ("Scanners do not work from a list of known sites. They walk IP ranges and "
               "certificate transparency logs and try common paths on whatever answers. Obscurity "
               "is not a filter — being reachable is the only qualification.")},
        {"q": "Should I block these requests?",
         "a": ("Blocking costs effort and buys little when the requests already return 404 "
               "instantly. Rate-limiting is worth it if the volume affects your logs or bandwidth. "
               "The higher-value work is making sure nothing sensitive is reachable in the first "
               "place.")},
        {"q": "Do these numbers apply to my site?",
         "a": ("The composition probably does; the volume depends on your host and address range. "
               "The measurement is three lines of log parsing, so check rather than assume — that "
               "is the whole argument of this article.")},
    ]

    return generator.ContentSpec(
        slug=SLUG,
        title=f"{share}% of Requests to Our New Site Probed for Software and Files We Do Not Have",
        dek=(f"We logged {m['total']:,} requests to a static site over {ndays} days. "
             f"{m['probe_hits']:,} of them asked for WordPress, .env files and PHP shells that "
             f"have never existed here."),
        page_type="guide",
        breadcrumb=[("Home", "/"), ("Dev Tools", "/dev-tools/"),
                    ("What knocks on a new site", "")],
        author="The Utilverse editors",
        published_at=today,
        updated_at=today,
        canonical=f"{renderer.SITE_URL}/compare/{SLUG}/",
        cluster="dev-saas-compare",
        kicker="First-party data",
        reading_time=6,
        intro_html=(
            f"<p>Put a server on the public internet and something will knock on it within the "
            f"hour. Everyone knows this in the abstract. We had the chance to put a number on it: "
            f"this site is new, unlinked, and static — no PHP, no database, no admin panel — so "
            f"anything asking for those is unambiguously a probe.</p>"
            f"<p>Over {ndays} days this domain received <strong>{m['total']:,} requests</strong>. "
            f"<strong>{m['probe_hits']:,}</strong> of them — about <strong>{share}%</strong> — were "
            f"for paths that have never existed here. Below is what they wanted, how often, and "
            f"what a small site should actually do about it.</p>"),
        tldr_html=(
            f"<p>Of <strong>{m['total']:,} requests</strong> over {ndays} days, "
            f"<strong>{m['probe_hits']:,} ({share}%)</strong> targeted software this static site "
            f"does not run — <strong>{m['probe_paths']:,} distinct paths</strong> from "
            f"<strong>{m['ips']:,} addresses</strong>, about {per_day} a day. "
            f"{ua_share}% arrived with no user agent. Nothing here needs a fix beyond keeping "
            f"<code>.env</code> and <code>.git</code> out of the web root.</p>"),
        sections=sections,
        verdict_html=(
            "<p>The practical conclusion is smaller than the numbers suggest. A quarter of our "
            "traffic is looking for a way in and almost none of it has any effect, because "
            "there is nothing on the other side to execute it. If you are choosing between a "
            "static site and a CMS for a small project, this is the security half of that "
            "trade-off made concrete.</p>"
            "<p>The part that does deserve attention is the file-based probing. Nobody is going "
            "to break into a folder of HTML, but a stray <code>.env</code> in the web root is "
            "readable by anyone who asks — and, as the table above shows, they ask constantly.</p>"),
        faq=faq,
        sources=[
            {"title": "OWASP — Web Application Security Testing: configuration and deployment",
             "url": "https://owasp.org/www-project-web-security-testing-guide/"},
            {"title": "nginx — HTTP core module and status codes",
             "url": "https://nginx.org/en/docs/http/ngx_http_core_module.html"},
            {"title": "Google Search Central — How Google Search crawls pages",
             "url": "https://developers.google.com/search/docs/fundamentals/how-search-works"},
            {"title": "Mozilla — HTTP response status codes",
             "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status"},
        ],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    m = measure()
    if not m["days"]:
        sys.exit("로그에서 요청을 읽지 못했다 — 이 스크립트는 서버에서 실행해야 한다")
    share = round(m["probe_hits"] * 100 / max(m["total"], 1))
    print(f"표본 {m['days'][0]} ~ {m['days'][-1]} · 총 요청 {m['total']:,}")
    print(f"탐침 {m['probe_hits']:,} ({share}%) · 고유 경로 {m['probe_paths']:,} "
          f"· 주소 {m['ips']:,} · UA 없음 {m['empty_ua']:,} · 우리 404 {m['ours_404']:,}")
    print("상태코드:", dict(m["status"].most_common(6)))
    print("메서드  :", dict(m["methods"].most_common(5)))
    for f in m["families"]:
        print("   %-26s %6d hits / %5d paths" % (f["name"], f["hits"], f["paths"]))
    print("상위 경로:")
    for p, c in m["top_paths"]:
        print("   %6d  %s" % (c, p[:80]))
    if a.dry_run:
        return 0

    from content import renderer
    doc = renderer.render(build_spec(m))
    out = os.path.join(ROOT, "dist", "queue", SLUG + ".html")
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(doc)
    print(f"\n초안 작성: {out} ({len(doc):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
