#!/usr/bin/env python3
"""build_index_gap_report.py — "구글은 1개만 색인했고, 첫 검색 방문자는 DuckDuckGo 가 보냈다".

왜 이 스크립트가 있나 (2026-08-15):
    AdSense 가 "가치가 별로 없는 콘텐츠"로 거절한 뒤, 남은 글의 대부분은 여전히
    공개 문서를 정리한 비교글이다. 아무도 공개하지 않는 데이터는 우리 것뿐이다 —
    갓 만든 사이트의 **색인 현황과 실제 유입 출처**.

    build_crawler_report.py 는 "누가 기어오는가"를 다뤘다. 이 글은 다른 질문이다:
    **기어온 뒤에 무슨 일이 일어났는가.** 크롤은 많았는데 색인은 1건이고,
    그런데도 검색 방문자는 왔다 — 구글이 아니라 DuckDuckGo 에서.

설계 원칙 (crawler 리포트와 동일):
    🔴 **숫자를 본문에 하드코딩하지 않는다.** 전부 data.json 에서 읽어 넣는다.
       하드코딩하면 다음 실행 때 본문과 데이터가 조용히 어긋난다.
    · data.json 은 서버 cron 이 engine/analytics/parser.py 의 3겹 봇 제외를 적용해 만든다.
      로그를 직접 세지 않는다 — 자체 정규식은 같은 페이지를 198 vs 88 로 잰 전력이 있다.
    · 표본 기간·집계 방법을 본문에 명시한다. 재현 불가능한 수치는 1차 데이터가 아니다.

사용:
    ./.venv/bin/python scripts/build_index_gap_report.py --dry-run
    ./.venv/bin/python scripts/build_index_gap_report.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

SLUG = "google-indexed-one-page-duckduckgo-sent-the-visitors"
DATA_PATHS = ("/var/www/stack-analytics/data.json",
              os.path.join(ROOT, "dist", "analytics", "data.json"))

# 검색엔진/답변엔진으로 셀 리퍼러 호스트 → 표시명. (direct) 와 잡음은 제외한다.
SEARCH_HOSTS = {
    "duckduckgo.com": ("DuckDuckGo", "Bing index + own crawler"),
    "google.com": ("Google", "Google index"),
    "bing.com": ("Bing", "Bing index"),
    "kagi.com": ("Kagi", "Blended, incl. Bing"),
    "search.brave.com": ("Brave Search", "Own index"),
    "ecosia.org": ("Ecosia", "Mixed sources"),
    "startpage.com": ("Startpage", "Google index"),
    "search.marginalia.nu": ("Marginalia", "Own index"),
    "yandex.com": ("Yandex", "Own index"),
    "chatgpt.com": ("ChatGPT", "Answer engine"),
    "perplexity.ai": ("Perplexity", "Answer engine"),
    "claude.ai": ("Claude", "Answer engine"),
    "copilot.microsoft.com": ("Microsoft Copilot", "Answer engine"),
}


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def load() -> dict:
    for p in DATA_PATHS:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
    sys.exit("data.json 을 찾지 못했다 — 이 스크립트는 서버에서 실행해야 한다")


def measure(d: dict) -> dict:
    g = d.get("gsc") or {}
    if not g.get("total"):
        sys.exit("GSC 데이터가 없다 — 색인 격차를 잴 수 없다")
    s = d.get("summary") or {}

    refs = {r.get("host"): r.get("count", 0) for r in (d.get("referrers") or [])}
    search = []
    for host, count in refs.items():
        if host in SEARCH_HOSTS and count:
            name, note = SEARCH_HOSTS[host]
            search.append({"host": host, "name": name, "note": note, "count": count})
    search.sort(key=lambda r: -r["count"])

    direct = refs.get("(direct)", 0)
    known = {r["host"] for r in search} | {"(direct)"}
    other = sum(c for h, c in refs.items() if h not in known)

    # 버킷 이동 — 지난 스냅샷 대비. "크롤됐지만 색인 안 됨"이 어떻게 불어났는지가 핵심이다.
    buckets = {b["key"]: b for b in (g.get("buckets") or [])}
    pages = g.get("pages") or []
    coverage = {}
    for p in pages:
        coverage[p.get("coverage") or "(unknown)"] = coverage.get(p.get("coverage") or "(unknown)", 0) + 1

    # ⚠️ first_seen 은 **로그의 첫 줄**이지 "검색에 열린 날"이 아니다.
    #    실콘텐츠 배포는 그 이틀 뒤였고 noindex 해제는 또 며칠 뒤였다.
    #    "사이트가 X일에 열렸다"고 쓰면 검수기가 잡는다(실제로 잡혔다). 나이는
    #    Search Console 이 이 속성을 보기 시작한 날부터 센다.
    first_seen = d.get("first_seen")
    search_since = g.get("first_date") or first_seen
    today = dt.date.today()
    age_days = ((today - dt.date.fromisoformat(search_since)).days
                if search_since else None)

    return {
        "gsc": g, "buckets": buckets, "coverage": coverage, "pages": pages,
        "search": search, "direct": direct, "other_refs": other,
        "summary": s, "first_seen": first_seen, "search_since": search_since,
        "age_days": age_days,
        "today": today.isoformat(),
        "search_total": sum(r["count"] for r in search),
        "generated_at": d.get("generated_at"),
    }


def build_spec(m: dict):
    from content import generator, renderer

    g, s = m["gsc"], m["summary"]
    today, age = m["today"], m["age_days"]
    weeks = round(age / 7) if age else None
    top = m["search"][0] if m["search"] else None
    goog = next((r for r in m["search"] if r["host"] == "google.com"), None)
    pv_all = s.get("all_time_pv") or 0
    bots7, pv7 = s.get("bots_7d") or 0, s.get("pv_7d") or 0
    bot_ratio = round(bots7 / pv7, 1) if pv7 else None
    crawled_prev = (m["buckets"].get("crawled") or {}).get("prev")
    crawled_now = g.get("crawled") or 0

    def srow(r):
        return (f'<tr><td class="featc">{esc(r["name"])}</td><td>{esc(r["note"])}</td>'
                f'<td class="ctr">{r["count"]:,}</td></tr>')

    search_table = (
        '<div class="tablewrap"><table class="tbl"><thead><tr>'
        '<th class="feat">Referrer</th><th class="feat">Where its results come from</th>'
        '<th class="ctr">Visits sent</th></tr></thead><tbody>'
        + "".join(srow(r) for r in m["search"]) + "</tbody></table></div>"
        f'<p class="footnote">Referrer hosts recorded in our own access logs across the life of the '
        f'site, after the same bot-exclusion rules used everywhere on this dashboard. '
        f'{m["direct"]:,} visits arrived with no referrer at all and {m["other_refs"]:,} came from '
        f'hosts that are not search engines; neither is counted above.</p>')

    def crow(cov, n):
        return f'<tr><td class="featc">{esc(cov)}</td><td class="ctr">{n}</td></tr>'

    cov_table = (
        '<div class="tablewrap"><table class="tbl"><thead><tr>'
        '<th class="feat">Search Console status</th><th class="ctr">URLs</th>'
        '</tr></thead><tbody>'
        + "".join(crow(c, n) for c, n in sorted(m["coverage"].items(), key=lambda kv: -kv[1]))
        + "</tbody></table></div>"
        f'<p class="footnote">Every URL Search Console currently reports for this property, as of '
        f'{esc(g.get("latest_date") or today)}. Statuses are Google\'s own wording.</p>')

    sections = [
        {"heading": "What we measured, and how",
         "html": (
             f"<p>The first request in our access log is dated "
             f"<strong>{esc(m['first_seen'])}</strong> — infrastructure and setup traffic, before "
             f"any article existed. Content went up in the days that followed, "
             f"and Search Console has data for this property from "
             f"<strong>{esc(m['search_since'])}</strong>"
             + (f" — {age} days ago" if age else "") + ". It is a small English-language "
             "technical site with no backlink campaign, no social push, and no paid promotion. "
             "That makes it a clean specimen for one question: what happens to a new site's pages "
             "after search engines find them?</p>"
             f"<p>Two sources, both first-party. Indexing status comes from Google Search Console "
             f"for this property, covering {esc(g.get('first_date') or '')} to "
             f"{esc(g.get('latest_date') or '')}. Traffic comes from our own nginx access logs, "
             "processed by the same bot-exclusion rules we use for every number on this site — a "
             "user-agent filter, a probe filter, and a behavioural filter, applied identically to "
             "every request. Numbers below were generated on "
             f"{esc((m.get('generated_at') or today)[:16])}.</p>"
             "<p>One caveat stated up front: these are small numbers. A few dozen search visits is "
             "not a sample you should generalise from. What it is good for is showing the "
             "<em>shape</em> of a new site's first months, which is rarely published because it is "
             "not flattering.</p>")},
        {"heading": f"{g.get('total')} URLs checked in Search Console. {g.get('indexed')} indexed.",
         "html": (
             f"<p>Search Console has <strong>{g.get('total')} URLs</strong> on record for this "
             f"property — every page we have published, plus a few that have since been retired. "
             f"<strong>{g.get('indexed')}</strong> "
             f"{'is' if (g.get('indexed') or 0) == 1 else 'are'} indexed. "
             f"<strong>{crawled_now}</strong> were crawled and then not indexed. For the remaining "
             f"<strong>{g.get('unknown')}</strong>, Google's own answer is “URL is unknown to "
             f"Google” — it has not reached them yet. They are all in a submitted sitemap; "
             f"submitting a sitemap asks Google to discover URLs, it does not oblige it to, and "
             f"working through one takes as long as it takes.</p>"
             + (f"<p>The direction of travel is the interesting part. In the previous snapshot the "
                f"crawled-but-not-indexed bucket held <strong>{crawled_prev}</strong> URL"
                f"{'' if crawled_prev == 1 else 's'}; it now holds <strong>{crawled_now}</strong>. "
                "Google is working through the site steadily — reading pages, then declining to "
                "keep them. Crawling is not the bottleneck. Judgement is.</p>"
                if crawled_prev is not None else "")
             + "<p>This is worth separating from the usual advice, because the usual advice is about "
             "the wrong step. Sitemaps, internal links, clean HTML and fast responses all buy you "
             "<em>crawling</em>. We have crawling. What we do not have is a verdict in our favour, "
             "and there is no technical lever for that.</p>")},
        {"heading": "Every URL, and what Google says about it",
         "html": cov_table},
        {"heading": ("Our first search visitors came from "
                     + (top["name"] if top else "elsewhere") + ", not Google"),
         "html": (
             ((f"<p>Here is the result we did not expect. Across the life of the site, "
               f"<strong>{esc(top['name'])}</strong> has sent <strong>{top['count']:,} visits</strong>"
               + (f", against <strong>{goog['count']:,}</strong> from Google"
                  if goog else ", while Google has sent none we can attribute")
               + ". "
               + (f"That is roughly <strong>{round(top['count'] / goog['count'], 1)}×</strong>. "
                  if goog and goog["count"] else "")
               + "</p>")
              if top else "<p>No search referrers have been recorded yet.</p>")
             + f"<p>The likely mechanism is visible in the table below: "
             f"{esc(top['name']) if top else 'several engines'} and several of the other referrers "
             "draw wholly or partly on Bing's index rather than Google's. We cannot see inside "
             "either index, so we are not claiming Bing indexed more of this site — only that "
             "these visits arrived through a different index with a different threshold, while "
             "Google's verdict on the same pages was the one shown above.</p>"
             "<p>It also means the standard framing — <em>get indexed by Google, then traffic "
             "follows</em> — describes only one of several doors. The others are smaller, but on a "
             "new site they open first.</p>")},
        {"heading": "Where the visits actually came from",
         "html": search_table},
        {"heading": "The traffic is mostly not human",
         "html": (
             ((f"<p>Over the last seven days this site served <strong>{pv7:,}</strong> human "
               f"pageviews and <strong>{bots7:,}</strong> requests we classified as bots"
               + (f" — about <strong>{bot_ratio}×</strong> more machine than human" if bot_ratio else "")
               + f". Lifetime human pageviews stand at <strong>{pv_all:,}</strong>.</p>")
              if pv7 else "")
             + "<p>We mention it because it is the single easiest way to fool yourself with "
             "analytics. Raw log lines, or any counter with a weak bot filter, will show a new site "
             "growing nicely while the humans stay flat. We learned this the hard way: an earlier "
             "count on this site put one article at 198 views; the same article measured with the "
             "proper filter was 88. Same log, same day, different filter.</p>"
             "<p>If your traffic graph is going up and your search referrers are not, check what is "
             "in the number before you celebrate it.</p>")},
        {"heading": "What we take from this",
         "html": (
             "<p><strong>Crawled-but-not-indexed is the normal state of a new site, not a bug to "
             "fix.</strong> Google documents that it does not index every page it crawls. Our "
             "numbers are what that policy looks like from underneath.</p>"
             "<p><strong>Do not measure progress in crawl volume.</strong> This site is crawled "
             "constantly and indexed once. The two numbers are barely related, and only one of them "
             "sends visitors.</p>"
             "<p><strong>Check the other engines.</strong> Most of our search visits came from "
             "engines other than Google. That is a channel most new-site advice does not mention, "
             "and it costs nothing to verify in your own referrer log.</p>"
             "<p><strong>Publish the shape of your own data.</strong> Everything above came from a "
             "log file and a free Search Console property. The reason this data is rare is not that "
             "it is hard to collect — it is that it looks like failure, so people keep it private.</p>")},
    ]

    faq = [
        {"q": "Why would Google crawl a page and then not index it?",
         "a": ("Google states that crawling and indexing are separate steps and that it does not "
               "index every page it crawls. 'Crawled - currently not indexed' means the page was "
               "fetched and assessed, and Google chose not to store it. It can change later "
               "without any action from you.")},
        {"q": "Does submitting a URL for indexing help?",
         "a": ("It can get a page crawled sooner. It does not commit Google to indexing it — "
               "the URL Inspection tool's own wording is that submission requests a crawl, not "
               "an index entry. On this site, requesting indexing reliably produced a crawl and "
               "did not produce an index entry.")},
        {"q": "Is DuckDuckGo traffic worth anything?",
         "a": ("It is real search traffic with real intent, and on this site it arrived earlier "
               "than Google's. Its volume is much smaller than Google's would be at scale, so "
               "treat it as an early signal that your content is findable, not as a substitute "
               "for Google.")},
        {"q": "How do you separate bots from humans in these counts?",
         "a": ("Three layers, applied to every log line the same way: a user-agent list, a "
               "known-probe path filter, and a behavioural check on request patterns. No filter "
               "is perfect — a determined crawler with a browser user agent will be counted as "
               "human — so read these as best-effort, not exact.")},
    ]

    dek = (f"Search Console has {g.get('total')} of our URLs on record. {g.get('indexed')} is indexed. "
           + (f"Meanwhile {esc(top['name'])} has sent {top['count']:,} visits"
              + (f" to Google's {goog['count']:,}" if goog else "") + "."
              if top else "Here is what that looks like from the inside."))

    return generator.ContentSpec(
        slug=SLUG,
        title=(f"Google Indexed {g.get('indexed')} of Our {g.get('total')} Pages. "
               + (f"{top['name']} Sent More Visitors." if top else "Here Is the Data.")),
        dek=dek,
        page_type="guide",
        breadcrumb=[("Home", "/"), ("Dev Tools", "/dev-tools/"),
                    ("Google indexed one page", "")],
        author="The Utilverse editors",
        published_at=today,
        updated_at=today,
        canonical=f"{renderer.SITE_URL}/compare/{SLUG}/",
        cluster="dev-saas-compare",
        kicker="First-party data",
        reading_time=7,
        intro_html=(
            f"<p>Almost every article about getting indexed is written by someone whose site is "
            f"already indexed. This one is not. This site has been visible to search since "
            f"<strong>{esc(m['search_since'])}</strong>"
            + (f" — {age} days, about {weeks} weeks" if age else "")
            + f". Google Search Console has <strong>{g.get('total')} of our URLs</strong> on record: "
            f"<strong>{g.get('indexed')}</strong> is in the index.</p>"
            "<p>We are publishing the numbers anyway, because the interesting part is not the "
            "failure — it is what happened around it. The pages <em>were</em> crawled. Search "
            "visitors <em>did</em> arrive. They just did not arrive from where the advice says "
            "they will.</p>"),
        tldr_html=(
            f"<p>Search Console, {g.get('total')} URLs checked: <strong>{g.get('indexed')} indexed, "
            f"{crawled_now} crawled and not indexed, {g.get('unknown')} still unknown to "
            f"Google</strong>. "
            + (f"Referrers: <strong>{esc(top['name'])} {top['count']:,} visits</strong>"
               + (f" vs Google {goog['count']:,}" if goog else "") + ". " if top else "")
            + (f"Bot requests outnumbered human pageviews by about {bot_ratio}× last week. "
               if bot_ratio else "")
            + "Crawl access and search presence are separate problems, and only one of them has a "
            "technical fix.</p>"),
        sections=sections,
        verdict_html=(
            "<p>If you launched a site recently and Search Console is showing you a wall of "
            "“Crawled - currently not indexed”, this is what that looks like on another site with "
            "the same problem. It is not a misconfiguration, and no sitemap tweak resolves it.</p>"
            "<p>What we would do differently with hindsight is spend less time on crawl plumbing — "
            "which was working from week one — and more time checking referrers from engines other "
            "than Google, because those were sending visitors while we were staring at the "
            "indexing report.</p>"),
        faq=faq,
        sources=[
            {"title": "Google Search Central — Page Indexing report",
             "url": "https://support.google.com/webmasters/answer/7440203"},
            {"title": "Google Search Central — How Google Search works",
             "url": "https://developers.google.com/search/docs/fundamentals/how-search-works"},
            {"title": "Google Search Central — URL Inspection tool",
             "url": "https://support.google.com/webmasters/answer/9012289"},
            {"title": "DuckDuckGo — Sources for our results",
             "url": "https://duckduckgo.com/duckduckgo-help-pages/results/sources/"},
            {"title": "Google Search Central — Creating helpful, reliable, people-first content",
             "url": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content"},
        ],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    m = measure(load())
    g = m["gsc"]
    print(f"사이트 개시 {m['first_seen']} · 나이 {m['age_days']}일 · 오늘 {m['today']}")
    print(f"GSC {g.get('first_date')}~{g.get('latest_date')}: total={g.get('total')} "
          f"indexed={g.get('indexed')} crawled={g.get('crawled')} unknown={g.get('unknown')}")
    print(f"검색 리퍼러 합계 {m['search_total']} · 직접유입 {m['direct']} · 기타 {m['other_refs']}")
    for r in m["search"]:
        print("   %-18s %5d  (%s)" % (r["name"], r["count"], r["note"]))
    print("커버리지 상태:", m["coverage"])
    if a.dry_run:
        return 0

    from content import renderer
    doc = renderer.render(build_spec(m))
    out = os.path.join(ROOT, "dist", "queue", SLUG + ".html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(doc)
    print(f"\n초안 작성: {out} ({len(doc):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
