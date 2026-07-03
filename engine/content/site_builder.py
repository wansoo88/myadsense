"""site_builder.py — 정적 사이트 빌드 (AUTOMATION.md §2 PUBLISH, static_ssg).

dist/queue 의 게이트 통과 페이지 + 필수 페이지(Privacy 필수 F2·About·Contact) + 인덱스
+ sitemap.xml + robots.txt → dist/site/ (Caddy 서빙 대상). Pretty URL(/compare/<slug>/).
"""
from __future__ import annotations
import datetime
import glob
import html
import os
import re

from content import renderer

SITE_DIR = "dist/site"
QUEUE_DIR = "dist/queue"
PRIVACY_LAST_UPDATED = "2026-06-30"   # Privacy Policy 본문 갱신일 — 정책 텍스트 변경 시 함께 수정


def _domain(cfg) -> str:
    try:
        return cfg["sites"]["sites"][0]["domain"]
    except Exception:
        return "stack.utilverse.info"


def _gsc_verify_file(cfg) -> str | None:
    """GSC URL-접두어 소유권 확인 파일명(googleXXXX.html). config 에 있으면 빌드가 SITE_DIR 에 생성.
    형식 검증(경로조작·오타 방지): 반드시 google<영숫자>.html."""
    try:
        v = (cfg["sites"]["sites"][0].get("google_site_verification") or "").strip()
    except Exception:
        return None
    if not v:
        return None
    if not re.fullmatch(r"google[A-Za-z0-9_-]+\.html", v):
        print(f"build: ⚠️ google_site_verification 형식 이상({v!r}) — 무시(google<영숫자>.html 이어야 함)")
        return None
    return v


def _indexnow_key(cfg) -> str | None:
    """IndexNow 색인 알림 키(공개용). 빌드가 SITE_DIR 에 /<key>.txt 를 생성(소유권 확인용).
    형식 검증(경로조작 방지): 영숫자·하이픈 8~128자만."""
    try:
        v = (cfg["sites"]["sites"][0].get("indexnow_key") or "").strip()
    except Exception:
        return None
    if not v:
        return None
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", v):
        print(f"build: ⚠️ indexnow_key 형식 이상({v!r}) — 무시(영숫자/하이픈 8~128자)")
        return None
    return v


def _rfc822(d: str) -> str | None:
    """YYYY-MM-DD → RSS pubDate(RFC-822, 서버 KST +0900). 형식 불량이면 None."""
    if not (d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)):
        return None
    try:
        return datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%a, %d %b %Y 00:00:00 +0900")
    except Exception:
        return None


def _build_feed(pages: list, base: str, domain: str, limit: int = 30) -> str:
    """RSS 2.0 피드 — 최신 콘텐츠(발행 순). 리더·애그리게이터 발견 통로(트래픽 생성 아님)."""
    latest = pages[:limit]
    build_date = _rfc822(max((p.get("updated") or "" for p in latest), default="")) \
        or datetime.datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0900")
    items = ""
    for p in latest:
        link = f"{base}{p['url']}"
        pub = _rfc822(p.get("updated"))
        desc = p.get("desc") or "An independent comparison of pricing, features, and fit."
        items += ("  <item>\n"
                  f"    <title>{esc(_short(p['title']))}</title>\n"
                  f"    <link>{esc(link)}</link>\n"
                  f'    <guid isPermaLink="true">{esc(link)}</guid>\n'
                  + (f"    <pubDate>{pub}</pubDate>\n" if pub else "")
                  + f"    <description>{esc(desc)}</description>\n"
                  "  </item>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"  <title>{esc(renderer.SITE_NAME)} — latest comparisons &amp; guides</title>\n"
            f"  <link>{esc(base)}/</link>\n"
            f'  <atom:link href="{esc(base)}/feed.xml" rel="self" type="application/rss+xml"/>\n'
            "  <description>Independent SaaS, developer, and AI tool comparisons and guides.</description>\n"
            "  <language>en</language>\n"
            f"  <lastBuildDate>{build_date}</lastBuildDate>\n"
            f"{items}</channel>\n</rss>\n")


def _contact_email(cfg) -> str:
    """Privacy/Contact 노출용 이메일. config 우선, 없으면 contact@도메인(포워딩 전제)."""
    try:
        e = cfg["sites"]["sites"][0].get("contact_email")
        if e:
            return e
    except Exception:
        pass
    return f"contact@{_domain(cfg)}"


def _title_of(html_doc: str, fallback: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html_doc, re.S)
    return html.unescape(m.group(1).strip()) if m else fallback


def _meta_of(doc: str) -> dict:
    """렌더된 페이지에서 홈 카드용 메타 추출(읽는 시간·갱신일·설명·kicker)."""
    read = re.search(r"(\d+)\s*min read", doc)
    upd = re.search(r"Updated <time>([^<]+)</time>", doc)
    desc = re.search(r'<meta name="description" content="([^"]*)">', doc)
    cl = re.search(r'<meta name="cluster" content="([^"]*)">', doc)
    kick = re.search(r'<div class="kicker">([^<]+)</div>', doc)
    return {
        "read": f"{read.group(1)} min read" if read else None,
        "updated": upd.group(1).strip() if upd else None,
        "desc": html.unescape(desc.group(1)) if desc else None,
        "cluster": cl.group(1) if cl else None,
        "kicker": html.unescape(kick.group(1)) if kick else None,
    }


# 카테고리 허브 (헤더·홈 nav 가 링크하는 URL) — topics.yaml 클러스터 id 매핑
CATEGORIES = [
    ("ai-coding", "AI Coding", "Editors, assistants, and AI coding tools — compared in depth.", {"ai-coding-tools"}),
    ("hosting", "Hosting & Self-host", "VPS, cloud hosting, and self-hosting — compared in depth.", {"hosting-selfhost"}),
    ("dev-tools", "Dev Tools", "SaaS and developer tools — compared in depth.", {"dev-saas-compare"}),
    ("ai-tools", "AI Tools", "Productivity and creative AI tools — compared in depth.", {"ai-productivity"}),
    ("vpn-security", "VPN & Security", "VPNs, password managers, and security tools — compared in depth.", {"vpn-security"}),
]


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# 클러스터 id → (카테고리 허브 slug, 표시명) — 내부 링크·브레드크럼 교정에 사용
_CLUSTER_CAT = {cid: (slug, name) for slug, name, _dek, cids in CATEGORIES for cid in cids}

# 제목 토큰화용 불용어(관련도 스코어) — 방향성만 남기고 흔한 연결어 제거
_STOP = {"vs", "the", "a", "an", "to", "for", "in", "of", "and", "or", "your", "you",
         "should", "use", "which", "is", "it", "are", "how", "by", "who", "can", "what",
         "when", "does", "do", "with", "on", "at", "be", "will", "step"}


def _short(title: str) -> str:
    return title.split(":")[0].strip()


def _tokens(title: str) -> set:
    toks = re.findall(r"[a-z0-9]+", _short(title).lower())
    return {t for t in toks if t not in _STOP and not t.isdigit() and len(t) > 1}


def _cat_label(page: dict) -> str:
    cat = _CLUSTER_CAT.get(page.get("cluster"))
    return cat[1] if cat else (page.get("kicker") or "Comparison")


def _pick_related(page: dict, pages: list, limit: int = 6) -> list:
    """실제 발행된 페이지 중 같은 클러스터·제목 겹침 기준 상위 N개를 Related 로 선정(자기 제외).
    같은 클러스터 우선(+100), 제목 토큰 공유마다 가점. 동점은 최신·slug 순으로 결정적.
    빌드마다 실제 발행 집합 기준으로 재계산 → 새 롱테일 발행 시 기존 글에 자동 상호 링크(404 없음)."""
    my_tok = _tokens(page["title"])
    my_cluster = page.get("cluster")
    scored = []
    for p in pages:
        if p["slug"] == page["slug"]:
            continue
        score = (100 if my_cluster and p.get("cluster") == my_cluster else 0)
        score += 5 * len(my_tok & _tokens(p["title"]))
        scored.append((score, p.get("updated") or "", p["slug"], p))
    # 정렬: score 내림 → updated 내림(최신) → slug 오름 (결정적)
    scored.sort(key=lambda t: (-t[0], _neg_date(t[1]), t[2]))
    return [{"url": p["url"], "title": _short(p["title"]), "cat": _cat_label(p)}
            for _s, _u, _sl, p in scored[:limit]]


def _neg_date(d: str):
    # updated(YYYY-MM-DD) 내림차순 정렬용 키(문자열 역순)
    return tuple(-int(x) for x in d.split("-")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or "") else (0,)


def _crumb_items(page: dict) -> list:
    """Home › (실제 카테고리 허브) › 글 제목. 카테고리 미상이면 2단(죽은 /compare/ 링크 제거)."""
    cat = _CLUSTER_CAT.get(page.get("cluster"))
    items = [("Home", "/")]
    if cat:
        items.append((cat[1], f"/{cat[0]}/"))
    items.append((_short(page["title"]), ""))
    return items


def _privacy_body(domain: str, email: str) -> str:
    # AdSense 필수(F2): 데이터 수집·제3자 쿠키·벤더 링크·맞춤광고 옵트아웃·법 준수.
    # ⚠️ 실서비스 전 법률 검토·연락 이메일 채우기.
    return f"""<p><em>Last updated: {PRIVACY_LAST_UPDATED}.</em></p>
<p>This Privacy Policy explains how {esc(domain)} ("we") collects, uses, and shares information when you visit our site.</p>
<h3>Information we collect</h3>
<p>We collect standard log data (IP address, browser type, pages visited) and use cookies and similar technologies to operate the site and serve advertising.</p>
<h3>Advertising &amp; third-party cookies</h3>
<p>We use Google AdSense to display ads. Third-party vendors, including Google, use cookies to serve ads based on your prior visits to this and other websites. Google's use of advertising cookies enables it and its partners to serve ads based on your visits.</p>
<ul>
<li>You may opt out of personalized advertising by visiting <a href="https://www.google.com/settings/ads" rel="noopener" target="_blank">Google Ads Settings</a>.</li>
<li>You may opt out of some third-party vendors' use of cookies for personalized advertising at <a href="https://www.aboutads.info/choices/" rel="noopener" target="_blank">aboutads.info/choices</a>.</li>
<li>See <a href="https://policies.google.com/technologies/partner-sites" rel="noopener" target="_blank">how Google uses data</a> from sites that use its services.</li>
</ul>
<h3>Advertising &amp; affiliate disclosure</h3>
<p>This site is supported by advertising and may contain affiliate links. If you click certain links and make a qualifying purchase, we may earn a commission at no additional cost to you. Our comparisons and verdicts are based on documented product features and publicly available information; commissions do not influence our assessments.</p>
<h3>Your rights</h3>
<p>Depending on your location, you may have rights under laws such as the GDPR and CCPA, including access, correction, and deletion. We comply with applicable data-protection laws.</p>
<h3>Contact</h3>
<p>Questions about this policy: <a href="mailto:{esc(email)}">{esc(email)}</a>.</p>"""


esc = html.escape


def _about_body(domain: str, email: str) -> str:
    # E-E-A-T(F: SQRG "누가 책임지고 누가 작성했는지 명확히" + helpful-content who/how/why):
    # 사실만 기술 — 허위 저자·경험 주장 금지(reviewer 루브릭). 편집팀 별칭은 Google 상 허용.
    return f"""<p><strong>{esc(domain)}</strong> is an independent editorial project that publishes
in-depth comparisons and buying guides for SaaS, developer, and AI tools. Our goal is a single, honest
answer to "which of these tools should I choose, and why" — backed by documented features and public data,
not marketing copy.</p>

<h3>Who is responsible for this site</h3>
<p>Content is researched, written, and maintained by <strong>The stack. editors</strong>, the editorial
team that operates this site. We are solely responsible for what is published here. Questions, corrections,
and feedback reach us directly at <a href="mailto:{esc(email)}">{esc(email)}</a> or via our
<a href="/contact/">contact page</a>.</p>

<h3>How we compare tools (methodology)</h3>
<ul>
<li><strong>Primary sources first.</strong> Pricing, limits, and features are taken from each vendor's
official documentation, pricing pages, and changelogs — every article cites the sources it relied on.</li>
<li><strong>Structured, like-for-like.</strong> Tools are compared on the same dimensions (pricing,
core features, data ownership, and fit) so the trade-offs are explicit rather than asserted.</li>
<li><strong>Dated and kept current.</strong> Each article shows its published and last-updated date;
pricing and features change often, so we revise pages and note the update date when we do.</li>
<li><strong>Verdicts, not hype.</strong> Recommendations follow from the documented differences and
clearly state who each option is best for — and who should skip it.</li>
</ul>

<h3>Editorial independence &amp; how we are funded</h3>
<p>This site is supported by advertising and may include affiliate links. Commissions, when they exist,
do <strong>not</strong> influence our assessments — verdicts are based on documented product features and
publicly available information. See our <a href="/privacy/">Privacy Policy</a> for the full advertising
and affiliate disclosure.</p>

<h3>Corrections</h3>
<p>We aim to be accurate and will fix mistakes promptly. If a figure looks wrong or a price is stale,
<a href="/contact/">let us know</a> and we will verify against the source and update the page.</p>"""


def build(cfg) -> str:
    domain = _domain(cfg)
    base = f"https://{domain}"
    # 기존 산출물 정리
    if os.path.isdir(SITE_DIR):
        import shutil
        shutil.rmtree(SITE_DIR)
    os.makedirs(SITE_DIR, exist_ok=True)

    # 1) 콘텐츠 페이지 (dist/queue → /compare/<slug>/)
    #    큐 문서는 생성 시점 디자인이 구워져 있음 → 빌드마다 chrome(CSS·헤더·푸터·JS)을 현행화.
    #    ⚠️ 2-pass: 먼저 실제 발행 페이지 집합을 확정한 뒤, 내부 링크(Related·브레드크럼)를
    #    실제 페이지로 교정해 기록한다(생성기가 지어낸 슬러그는 전부 404였음).
    built = []                                    # [(slug, doc), ...] 링크 교정 전 문서
    pages = []
    for qf in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.html"))):
        slug = os.path.splitext(os.path.basename(qf))[0]
        with open(qf, encoding="utf-8") as f:
            doc = renderer.refresh_chrome(f.read())
        built.append((slug, doc))
        pages.append({"slug": slug, "title": _title_of(doc, slug),
                      "url": f"/compare/{slug}/", **_meta_of(doc)})
    # 홈 '이번 주'·Latest가 실제 최신이 되도록 갱신일 내림차순(동률은 슬러그순 유지)
    pages.sort(key=lambda p: p.get("updated") or "", reverse=True)

    # 1.5) 내부 링크 교정 pass — 실제 페이지 집합(pages) 기준으로 Related·브레드크럼 재작성 후 기록
    related_n = int(((cfg.get("content") or {}).get("internal_links") or {}).get("related_count", 6))
    by_slug = {p["slug"]: p for p in pages}
    fixed_related = fixed_crumb = 0
    for slug, doc in built:
        page = by_slug[slug]
        related = _pick_related(page, pages, limit=related_n)
        crumb = _crumb_items(page)
        doc = renderer.refresh_internal_links(doc, crumb_items=crumb, related_items=related)
        fixed_related += len(related)
        fixed_crumb += 1
        _write(os.path.join(SITE_DIR, "compare", slug, "index.html"), doc)

    # 2) 필수/정적 페이지 (Privacy 필수 — F2)
    email = _contact_email(cfg)
    static_pages = {
        "privacy": ("Privacy Policy", _privacy_body(domain, email)),
        "about": ("About & editorial standards", _about_body(domain, email)),
        "contact": ("Contact", f'<p>Reach us at <a href="mailto:{esc(email)}">{esc(email)}</a>. '
                    f'Spot an error or an out-of-date price? Tell us and we will correct it.</p>'),
    }
    for path, (title, body) in static_pages.items():
        _write(os.path.join(SITE_DIR, path, "index.html"),
               renderer.render_static_page(title, body, description=f"{title} — {domain}"))

    # 3) 카테고리 허브 — 콘텐츠 1편 이상인 카테고리만 생성·링크·sitemap (빈 '공사중' 페이지 방지)
    cat_urls = []
    active_cat_paths = []
    for slug, name, dek, cluster_ids in CATEGORIES:
        cat_pages = [p for p in pages if p.get("cluster") in cluster_ids]
        if not cat_pages:                     # 빈 카테고리는 생성/링크 안 함(helpful-content·승인 리스크)
            continue
        _write(os.path.join(SITE_DIR, slug, "index.html"),
               renderer.render_hub(name, dek, cat_pages, domain=domain, canonical=f"{base}/{slug}/"))
        cat_urls.append((f"{base}/{slug}/", max((p.get("updated") or "" for p in cat_pages), default="")))
        active_cat_paths.append(f"/{slug}/")

    # 3.5) 홈 (활성 카테고리만 그리드에 노출 — 빈 허브 링크 방지)
    _write(os.path.join(SITE_DIR, "index.html"),
           renderer.render_home(pages, domain=domain, canonical=f"{base}/", active_cat_urls=active_cat_paths))

    # 4) sitemap.xml + robots.txt — lastmod 는 실제 갱신일만(부정확하면 Google 이 무시하므로 형식 검증)
    def _lm(d):
        return d if d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else None
    site_lastmod = max((p.get("updated") or "" for p in pages), default="")
    entries = ([(f"{base}/", _lm(site_lastmod))]
               + [(u, _lm(d)) for u, d in cat_urls]
               + [(f"{base}{p['url']}", _lm(p.get("updated"))) for p in pages]
               + [(f"{base}/{sp}/", _lm(PRIVACY_LAST_UPDATED) if sp == "privacy" else None)
                  for sp in static_pages])
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{esc(u)}</loc>"
                         + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>\n"
                         for u, d in entries) + "</urlset>\n")
    _write(os.path.join(SITE_DIR, "sitemap.xml"), sitemap)
    _write(os.path.join(SITE_DIR, "robots.txt"),
           f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")

    # 5) Google Search Console 소유권 확인 파일 (URL 접두어) — cron 이 web_root 를 비우므로 매 빌드 재생성
    gsc = _gsc_verify_file(cfg)
    if gsc:
        _write(os.path.join(SITE_DIR, gsc), f"google-site-verification: {gsc}\n")

    # 6) IndexNow 키 파일 (색인 알림 소유권 확인) — cron 이 web_root 를 비우므로 매 빌드 재생성
    inkey = _indexnow_key(cfg)
    if inkey:
        _write(os.path.join(SITE_DIR, f"{inkey}.txt"), f"{inkey}\n")

    # 7) RSS 피드 (발견 통로) + 홈 head 의 <link rel=alternate> 가 가리킴
    _write(os.path.join(SITE_DIR, "feed.xml"), _build_feed(pages, base, domain))

    print(f"build: {len(pages)} 콘텐츠 + {len(cat_urls)} 카테고리 허브 + {len(static_pages)} 필수 페이지 "
          f"+ sitemap/robots{' + GSC(' + gsc + ')' if gsc else ''}{' + IndexNow-key' if inkey else ''} + feed.xml → {SITE_DIR}/")
    print(f"build: 내부 링크 교정: Related {fixed_related}개 링크 + 브레드크럼 {fixed_crumb}개 페이지 "
          f"(실제 발행 페이지로 재작성)")
    return SITE_DIR
