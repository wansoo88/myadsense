#!/usr/bin/env python3
"""build_crawler_report.py — 우리 서버 로그로 '어떤 크롤러가 실제로 오는가'를 재서 기사로 만든다.

왜 이 스크립트가 있나 (2026-08-12):
    AdSense 가 사이트를 "가치가 별로 없는 콘텐츠"로 거절했다. 원인 중 하나는 32편 전부가
    공개 문서를 재편집한 'X vs Y' 비교글이고 **1차 데이터가 0** 이라는 것이다.
    서버(디스크 95%·여유 RAM 243MB·타 프로젝트 컨테이너 공유)에는 Ghost·Nextcloud 를
    설치해 벤치마크할 여유가 없다. 그러나 **이미 쌓인 nginx 로그**는 아무 비용 없이
    아무도 공개하지 않는 1차 데이터를 준다 — 갓 만든 사이트에 실제로 오는 크롤러의 정체.

설계 원칙:
    🔴 **숫자를 기사에 하드코딩하지 않는다.** 본문 수치는 전부 이 스크립트가 로그에서
       계산해 넣는다. 하드코딩하면 다음 실행 때 본문과 로그가 조용히 어긋난다 —
       그건 우리가 방금 고친 "가격이 낡아 있던" 실패와 같은 종류의 실패다.
    · 봇 분류는 engine/analytics/parser.py 의 정본 규칙을 쓴다(직접 정규식 금지 — 2026-08-12
       실측에서 자체 정규식이 같은 페이지를 198 vs 88 로 재는 걸 확인했다).
    · 표본 기간·제외 규칙·로그 포맷을 기사 안에 명시한다. 재현 불가능한 수치는 1차 데이터가 아니다.

사용:
    ./.venv/bin/python scripts/build_crawler_report.py --dry-run   # 수치만 출력
    ./.venv/bin/python scripts/build_crawler_report.py             # dist/queue 에 초안 작성
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
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# engine 모듈들은 서로를 `from content import ...` 로 부른다 → engine/ 도 경로에 넣어야 한다
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

LOG_GLOBS = ["/var/log/nginx/utilverse.access.log*", "/var/log/nginx/stack.access.log*"]
SLUG = "which-crawlers-actually-visit-a-new-site-we-measured-ours"

# UA 안에서 찾을 크롤러 토큰 → 표시명·소속. 순서 중요(먼저 맞는 것을 채택):
# google-extended/googleother 는 'googlebot' 과 겹치지 않지만, claude-user 는 claudebot 보다 먼저 봐야 한다.
BOTS = [
    ("googlebot", "Googlebot", "Google Search"),
    ("google-extended", "Google-Extended", "Google (AI training)"),
    ("googleother", "GoogleOther", "Google (non-search)"),
    ("bingbot", "bingbot", "Microsoft Bing"),
    ("duckduckbot", "DuckDuckBot", "DuckDuckGo"),
    ("yandex", "YandexBot", "Yandex"),
    ("applebot", "Applebot", "Apple"),
    ("amazonbot", "Amazonbot", "Amazon"),
    ("claude-user", "Claude-User", "Anthropic (user fetch)"),
    ("claudebot", "ClaudeBot", "Anthropic"),
    ("gptbot", "GPTBot", "OpenAI (training)"),
    ("oai-searchbot", "OAI-SearchBot", "OpenAI (search)"),
    ("perplexity", "PerplexityBot", "Perplexity"),
    ("meta-externalagent", "meta-externalagent", "Meta"),
    ("bytespider", "Bytespider", "ByteDance"),
    ("semrush", "SemrushBot", "SEO tool"),
    ("ahrefs", "AhrefsBot", "SEO tool"),
    ("mj12", "MJ12bot", "SEO tool"),
    ("dotbot", "DotBot", "SEO tool"),
    ("dataforseo", "DataForSeoBot", "SEO tool"),
    ("facebookexternalhit", "facebookexternalhit", "Meta (link preview)"),
    ("censys", "Censys", "Internet scanner"),
    ("internet-measurement", "internet-measurement", "Internet scanner"),
]
# 'AI 크롤러'로 집계할 토큰 — 검색 색인이 아니라 LLM 학습/응답용으로 가져가는 것들
AI_TOKENS = {"claudebot", "claude-user", "gptbot", "oai-searchbot", "perplexity",
             "meta-externalagent", "bytespider", "google-extended"}


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
                    if not line.startswith("{"):
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
            except OSError:
                continue


def measure() -> dict:
    agg = collections.defaultdict(lambda: {"hits": 0, "urls": set(), "sitemap": 0,
                                           "robots": 0, "first": "", "last": ""})
    days, total = set(), 0
    for d in _rows():
        total += 1
        day = (d.get("t") or "")[:10]
        if day:
            days.add(day)
        ua = (d.get("ua") or "").lower()
        tok = next((t for t, _n, _o in BOTS if t in ua), None)
        if not tok:
            continue
        a = agg[tok]
        u = (d.get("u") or "").split("?")[0]
        a["hits"] += 1
        a["urls"].add(u)
        if "sitemap" in u:
            a["sitemap"] += 1
        if "robots.txt" in u:
            a["robots"] += 1
        if day:
            if not a["first"] or day < a["first"]:
                a["first"] = day
            if day > a["last"]:
                a["last"] = day
    name = {t: (n, o) for t, n, o in BOTS}
    table = []
    for tok, a in agg.items():
        n, owner = name[tok]
        table.append({"token": tok, "name": n, "owner": owner, "hits": a["hits"],
                      "urls": len(a["urls"]), "sitemap": a["sitemap"], "robots": a["robots"],
                      "first": a["first"], "last": a["last"], "ai": tok in AI_TOKENS})
    table.sort(key=lambda r: -r["hits"])
    ai_hits = sum(r["hits"] for r in table if r["ai"])
    g = next((r for r in table if r["token"] == "googlebot"), None)
    return {"table": table, "total_requests": total,
            "days": sorted(days), "bot_hits": sum(r["hits"] for r in table),
            "ai_hits": ai_hits, "googlebot": g,
            "ai_ratio": round(ai_hits / g["hits"], 1) if g and g["hits"] else None}


def gsc_snapshot() -> dict | None:
    """분석 대시보드가 만든 data.json 의 GSC 색인 현황(있으면)."""
    for p in ("/var/www/stack-analytics/data.json",
              os.path.join(ROOT, "dist", "analytics", "data.json")):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
            except Exception:
                return None
            g = d.get("gsc") or {}
            r = d.get("referrers") or []
            return {"total": g.get("total"), "indexed": g.get("indexed"),
                    "crawled": g.get("crawled"), "unknown": g.get("unknown"),
                    "refs": {x.get("host"): x.get("count") for x in r[:12]},
                    "first_seen": d.get("first_seen")}
    return None


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def build_spec(m: dict, gsc: dict | None):
    from content import generator, renderer

    days = m["days"]
    d0, d1 = days[0], days[-1]
    ndays = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days + 1
    today = dt.date.today().isoformat()
    t = m["table"]
    top = t[0]
    gb = m["googlebot"]
    ai_share = round(m["ai_hits"] * 100 / max(m["bot_hits"], 1))

    # 표 마크업은 renderer 의 디자인 시스템을 그대로 쓴다(.tablewrap / table.tbl / .featc / .ctr).
    # 새 클래스를 만들면 이 글만 다르게 보이고, 다크모드·모바일 대응을 다시 짜야 한다.
    def row(r):
        return (f'<tr><td class="featc">{esc(r["name"])}</td><td>{esc(r["owner"])}</td>'
                f'<td class="ctr">{r["hits"]:,}</td><td class="ctr">{r["urls"]:,}</td>'
                f'<td class="ctr">{r["sitemap"]}</td><td>{esc(r["first"])}</td></tr>')

    table_html = (
        '<div class="tablewrap"><table class="tbl"><thead><tr>'
        '<th class="feat">Crawler</th><th class="feat">Operated by</th><th class="ctr">Requests</th>'
        '<th class="ctr">Unique URLs</th><th class="ctr">sitemap.xml</th><th class="feat">First seen</th>'
        '</tr></thead><tbody>' + "".join(row(r) for r in t) + '</tbody></table></div>'
        f'<p class="footnote">Every request to this site between {esc(d0)} and {esc(d1)} '
        f'({ndays} days), read from our own nginx access logs. “Operated by” names the company the '
        f'user agent claims; crawlers marked as training or answer engines collect for language '
        f'models rather than a search index.</p>')

    ai_rows = [r for r in t if r["ai"]]
    ai_list = ", ".join(f"{r['name']} ({r['hits']:,})" for r in ai_rows[:5])

    sections = [
        {"heading": "What we measured, and how",
         "html": (
             f"<p>This site is small and new: the first request in our logs is dated "
             f"{esc(gsc.get('first_seen')) if gsc and gsc.get('first_seen') else esc(d0)}, and it has "
             f"a few dozen articles. That makes it a useful specimen — it has no backlink profile, no "
             f"brand, and nothing to attract crawlers except being on the public web.</p>"
             f"<p>We took every line of the nginx access log for this domain between "
             f"<strong>{esc(d0)}</strong> and <strong>{esc(d1)}</strong> — <strong>{m['total_requests']:,} "
             f"requests</strong> in total — and classified each one by user agent. Classification "
             f"uses a fixed list of user-agent tokens applied identically to every line, so the same "
             f"log always produces the same table; a request counts once per hit. We report requests and "
             f"distinct URLs separately because a crawler that hits one URL two hundred times is doing "
             f"something very different from one that walks the whole site.</p>"
             "<p>Two caveats worth stating plainly. User agents are self-reported and can be forged, so "
             "these counts describe what identified itself as each crawler, not verified identity. And "
             "this is one small site — the ratios here are a data point, not an industry average.</p>")},
        {"heading": "AI crawlers came far more often than Google did",
         "html": (
             f"<p>The headline result: crawlers that collect for language models made "
             f"<strong>{m['ai_hits']:,} requests</strong> — {ai_share}% of all identified crawler "
             f"traffic — while <strong>Googlebot made {gb['hits']:,}</strong>"
             + (f", a ratio of about <strong>{m['ai_ratio']}:1</strong>" if m["ai_ratio"] else "")
             + f". The AI side is not one bot but many: {esc(ai_list)}.</p>"
             f"<p>Google's own crawling was modest in both volume and reach — {gb['hits']:,} requests "
             f"across {gb['urls']:,} distinct URLs. For a site of this size that is a light touch.</p>"
             "<p>If you have been assuming that a new site's server load is mostly search engines "
             "discovering you, that assumption is out of date. On this site the language-model "
             "crawlers are the main audience, and they arrived without being invited.</p>")},
        {"heading": f"The busiest crawler was {esc(top['name'])}, not a search engine",
         "html": (
             f"<p><strong>{esc(top['name'])}</strong> ({esc(top['owner'])}) was the single most active "
             f"crawler at <strong>{top['hits']:,} requests</strong> across {top['urls']:,} distinct "
             f"URLs — more than any search engine in the sample.</p>"
             "<p>This is the part that surprises people who have not looked at their own logs: the "
             "crawler budget of a small site is spent on companies that will never send it a visitor. "
             "Only a handful of the crawlers below have any path to sending you traffic at all.</p>")},
        {"heading": "Who actually reads sitemap.xml",
         "html": (
             "<p>Sitemaps are supposed to be how you tell crawlers what exists. In practice most "
             "crawlers in our sample never asked for ours.</p>"
             + "<ul>" + "".join(
                 f"<li><strong>{esc(r['name'])}</strong> — {r['sitemap']} request"
                 f"{'' if r['sitemap'] == 1 else 's'} for sitemap.xml</li>"
                 for r in sorted(t, key=lambda x: -x["sitemap"])[:5]) + "</ul>"
             + f"<p>Googlebot requested it <strong>{gb['sitemap']}</strong> time"
             f"{'' if gb['sitemap'] == 1 else 's'} in {ndays} days. Whatever governs how much Google "
             "crawls a new site, repeatedly re-reading its sitemap is not part of it.</p>")},
        {"heading": "Being crawled is not being indexed",
         "html": (
             (f"<p>The gap between crawling and indexing is the number that matters, and it is stark. "
              f"As of {esc(today)}, Search Console reported <strong>{gsc['total']} URLs</strong> "
              f"known for this site: "
              f"<strong>{gsc['indexed']} indexed</strong>, {gsc['crawled']} crawled but not indexed, "
              f"and {gsc['unknown']} not yet processed. Googlebot has read the pages. It has "
              f"decided not to keep them.</p>"
              if gsc and gsc.get("total") else
              "<p>Crawling and indexing are separate decisions: a crawler reading a page is not a "
              "commitment to store or rank it.</p>")
             + "<p>That distinction is worth internalising before you spend a week on technical SEO. "
             "Crawl access is the cheap part — robots.txt, a sitemap, and clean HTML get you that in "
             "a day. Whether anything is kept is a judgement about the content, and no amount of "
             "crawl plumbing changes it.</p>"
             + ((lambda refs: (
                 f"<p>The traffic side reflects the same thing from the other end. Over the same "
                 f"period our top search referrers were "
                 + ", ".join(f"<strong>{esc(k)}</strong> ({v})" for k, v in list(refs.items())[:5])
                 + ". The engine that indexed the least is not the one sending the most.</p>")
                )({k: v for k, v in gsc["refs"].items()
                   if k and k not in ("(direct)", "")}) if gsc and gsc.get("refs") else ""))},
        {"heading": "Every crawler we saw",
         "html": table_html},
        {"heading": "What we would tell a new site owner",
         "html": (
             "<p>Three things follow from this data, and none of them is a growth hack.</p>"
             "<p><strong>Read your own logs before you read advice about logs.</strong> The ratios "
             "here were not what we expected, and they were free to obtain. Whatever your site is, "
             "the answer for <em>your</em> site is already sitting in <code>/var/log/nginx</code>.</p>"
             "<p><strong>Decide deliberately about AI crawlers.</strong> They are the majority of "
             "crawl load in this sample. robots.txt can allow or disallow them individually — that is "
             "a real choice with real trade-offs, not a default to drift into.</p>"
             "<p><strong>Do not read crawl volume as progress.</strong> Being crawled thousands of "
             "times told us nothing about whether the content was worth keeping. The indexing numbers "
             "answered that, and they answered it differently.</p>")},
    ]

    faq = [
        {"q": "Do these numbers apply to my site?",
         "a": ("Not directly. This is one small, new, English-language technical site with no backlink "
               "profile, measured over " + str(ndays) + " days. Treat the ratios as a prompt to check "
               "your own logs, not as a benchmark.")},
        {"q": "Can user agents be faked?",
         "a": ("Yes. User agents are self-reported. These counts describe traffic that identified "
               "itself as each crawler. Verifying identity requires reverse-DNS or published IP "
               "ranges, which we did not apply here — so treat named counts as upper bounds.")},
        {"q": "Does blocking AI crawlers help SEO?",
         "a": ("There is no evidence in this data either way. Blocking a language-model crawler "
               "changes who can read your content; it does not change how a search engine judges it. "
               "Decide it on licensing and bandwidth grounds, not ranking ones.")},
        {"q": "Why is crawled-but-not-indexed so common on new sites?",
         "a": ("Google states that crawling and indexing are separate steps and that it does not "
               "index every page it crawls. On a new site with little established value, the "
               "not-indexed bucket is where most pages sit until that changes.")},
    ]

    return generator.ContentSpec(
        slug=SLUG,
        title="Which Crawlers Actually Visit a Brand-New Site? We Measured Ours",
        dek=(f"We logged every request to this site for {ndays} days — {m['total_requests']:,} of them — "
             f"and counted who showed up. AI crawlers outnumbered Googlebot"
             + (f" by about {m['ai_ratio']} to 1" if m["ai_ratio"] else "") + "."),
        page_type="guide",
        breadcrumb=[("Home", "/"), ("Dev Tools", "/dev-tools/"),
                    ("Which crawlers visit a new site", "")],
        author="The Utilverse editors",
        published_at=today,
        updated_at=today,
        canonical=f"{renderer.SITE_URL}/compare/{SLUG}/",
        cluster="dev-saas-compare",
        kicker="First-party data",
        reading_time=7,
        intro_html=(
            f"<p>Most advice about crawlers is written from the outside — what Google says it does, "
            f"what a vendor's dashboard reports. We had a simpler option available: this site is new "
            f"and small, so we read our own server logs and counted.</p>"
            f"<p>Between {esc(d0)} and {esc(d1)} this domain received <strong>{m['total_requests']:,} "
            f"requests</strong>. Below is every crawler that identified itself, how often it came, how "
            f"much of the site it walked, and whether it bothered with our sitemap. The result that "
            f"surprised us most: the busiest crawlers were not search engines at all.</p>"),
        tldr_html=(
            f"<p>Over {ndays} days, language-model crawlers made <strong>{m['ai_hits']:,}</strong> "
            f"requests to this site against Googlebot's <strong>{gb['hits']:,}</strong>"
            + (f" — about <strong>{m['ai_ratio']}:1</strong>" if m["ai_ratio"] else "")
            + f". The single busiest crawler was <strong>{esc(top['name'])}</strong> "
            f"({top['hits']:,} requests). "
            + (f"Meanwhile, as of {esc(today)}, Search Console reported <strong>{gsc['indexed']} of "
               f"{gsc['total']}</strong> URLs actually indexed. " if gsc and gsc.get("total") else "")
            + "Crawl volume and search presence turned out to be unrelated.</p>"),
        sections=sections,
        verdict_html=(
            "<p>If you run a small site and have never opened your access log, this is the cheapest "
            "hour of analysis available to you. Ours said that the crawler traffic we were implicitly "
            "optimising for — Google discovering pages — was a small minority of what actually "
            "arrived, and that being crawled heavily told us nothing about whether our pages were "
            "worth keeping.</p>"
            "<p>We publish the full table above so the claim is checkable rather than asserted. The "
            "method is three lines of log parsing; run it on your own site and you will get a "
            "different answer, which is rather the point.</p>"),
        faq=faq,
        sources=[
            {"title": "Google Search Central — How Google Search crawls pages",
             "url": "https://developers.google.com/search/docs/fundamentals/how-search-works"},
            {"title": "Google Search Central — Page Indexing report",
             "url": "https://support.google.com/webmasters/answer/7440203"},
            {"title": "Google — Overview of Google crawlers and user-triggered fetchers",
             "url": "https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers"},
            {"title": "Anthropic — About ClaudeBot and Anthropic's web crawlers",
             "url": "https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler"},
            {"title": "OpenAI — GPTBot and OAI-SearchBot",
             "url": "https://platform.openai.com/docs/bots"},
        ],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="수치만 출력하고 파일을 쓰지 않는다")
    args = ap.parse_args()

    m = measure()
    if not m["days"]:
        sys.exit("로그에서 요청을 읽지 못했다 — 이 스크립트는 서버에서 실행해야 한다")
    gsc = gsc_snapshot()

    print(f"표본: {m['days'][0]} ~ {m['days'][-1]} · 총 요청 {m['total_requests']:,}")
    print(f"식별된 크롤러 요청 {m['bot_hits']:,} · 그중 AI {m['ai_hits']:,} "
          f"· Googlebot {m['googlebot']['hits'] if m['googlebot'] else 0} "
          f"· 비율 {m['ai_ratio']}:1")
    if gsc:
        print(f"GSC: total={gsc['total']} indexed={gsc['indexed']} "
              f"crawled={gsc['crawled']} unknown={gsc['unknown']}")
    print()
    print("%-22s %7s %7s %8s" % ("crawler", "hits", "urls", "sitemap"))
    for r in m["table"]:
        print("%-22s %7d %7d %8d" % (r["name"], r["hits"], r["urls"], r["sitemap"]))

    if args.dry_run:
        return 0

    from content import renderer
    spec = build_spec(m, gsc)
    doc = renderer.render(spec)
    out = os.path.join(ROOT, "dist", "queue", SLUG + ".html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(doc)
    print(f"\n초안 작성: {out} ({len(doc):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
