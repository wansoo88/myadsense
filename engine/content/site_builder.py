"""site_builder.py — 정적 사이트 빌드 (AUTOMATION.md §2 PUBLISH, static_ssg).

dist/queue 의 게이트 통과 페이지 + 필수 페이지(Privacy 필수 F2·About·Contact) + 인덱스
+ sitemap.xml + robots.txt → dist/site/ (Caddy 서빙 대상). Pretty URL(/compare/<slug>/).
"""
from __future__ import annotations
import datetime
import glob
import html
import json
import os
import re
import struct

from content import renderer

SITE_DIR = "dist/site"
QUEUE_DIR = "dist/queue"
PRIVACY_LAST_UPDATED = "2026-07-25"   # Privacy Policy 본문 갱신일 — 정책 텍스트 변경 시 함께 수정


def _domain(cfg) -> str:
    try:
        return cfg["sites"]["sites"][0]["domain"]
    except Exception:
        return renderer.SITE_DOMAIN


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


def _adsense_publisher_id(cfg) -> str:
    """AdSense **사이트 소유권 확인**용 퍼블리셔 ID(config/sites.yaml `adsense.publisher_id`).

    유효할 때만 (a) 전 페이지 <head> 메타태그 (b) /ads.txt 를 만든다. 빈 값이면 둘 다 미생성 = 현행 유지.
    형식 검증은 renderer 가 소유(같은 판정을 두 곳에서 다르게 하지 않는다) — 여기서는 경고만 찍는다.
    ⛔ 광고 게재와 무관하다. 승인 전이므로 광고 로더 스크립트는 어디에도 넣지 않는다.
    """
    try:
        raw = (cfg["sites"].get("adsense") or {}).get("publisher_id")
    except Exception:
        return ""
    v = str(raw or "").strip()
    if not v:
        if raw not in (None, ""):     # 공백만 넣은 경우 — 값을 넣었다고 믿는 사람에게 조용한 미생성은 최악
            print(f"build: ⚠️ adsense.publisher_id 가 공백뿐({raw!r}) — 무시(메타태그·ads.txt 미생성)")
        return ""
    ok = renderer.valid_publisher_id(v)
    if not ok:
        print(f"build: ⚠️ adsense.publisher_id 형식 이상({v!r}) — 무시"
              "(ca-pub- + 숫자 16자리여야 함. 메타태그·ads.txt 미생성)")
    return ok


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


def _write_bytes(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


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


def _monetization_observed(cfg) -> dict:
    """이 사이트가 **지금 실제로** 광고/제휴로 수익화돼 있는가 — 추측이 아니라 관측값.

    판정 로직은 REVIEW 소유의 `reviewer.monetization_state()` 를 **호출만** 한다(재구현 금지 —
    같은 사실을 두 곳에서 다르게 판단하면 그게 다음 버그다). 관측 대상:
      ① 렌더 템플릿 소스(renderer.py·site_builder.py)의 광고 네트워크 코드
      ② 직전 빌드 산출물 dist/site/**/*.html   ③ config/content.yaml `monetization.*` 선언
      ④ 환경변수 `ADSENSE_MONETIZED=1`
    ⚠️ **build() 가 dist/site 를 지우기 전에** 불러야 ②가 관측 대상에 들어간다.

    관측 자체가 실패하면 **고지를 켜는 쪽**(= 광고 게재 중)으로 판정한다 — fail-closed. 광고가 도는데
    고지가 빠지는 것(F2 위반 → 광고 중단·계정 리스크)이 그 반대보다 훨씬 비싸다. reviewer 의
    "override 는 켜는 방향으로만" 원칙과 같은 방향이다. 실패로 보는 경우는 둘이다:
      · 예외(import·스캔 실패)
      · `known=False` — 스캔 대상 0파일 등으로 **관측이 성립하지 않은 경우**. 이때 `monetized=False` 는
        "광고 없음"이 아니라 "확인 못 함"이므로 그대로 믿으면 0파일을 읽고 "광고 없다"고 쓰게 된다
        (reviewer 가 ORDER 2026-07-25-18 ③ 에서 막은 것과 같은 fail-open).
    """
    try:
        from content import reviewer
        st = reviewer.monetization_state(content_cfg=(cfg.get("content") or {}))
    except Exception as e:                       # import·스캔 실패 등 — 빌드를 멈추지 않고 안전측으로
        print(f"build: ⚠️ 수익화 관측 실패({type(e).__name__}: {e}) — 안전측(광고 게재 중)으로 고지 작성")
        return {"monetized": True, "ads": True, "affiliate": True, "known": False,
                "evidence": [f"observation failed: {type(e).__name__}: {e}"], "scanned": "n/a"}
    # known 키가 없는 구버전 reviewer 는 '관측 성립'이 기본 계약이었으므로 True 로 본다.
    if not st.get("known", True):
        print("build: ⚠️ 수익화 관측 불성립(known=False) — 안전측(광고 게재 중)으로 고지 작성 / "
              + (st.get("warning") or "; ".join(st.get("evidence") or []))[:220])
        return dict(st, monetized=True, ads=True, affiliate=True)
    return st


def _privacy_body(domain: str, email: str, mon: dict) -> str:
    """AdSense 필수(F2): 데이터 수집·제3자 쿠키·벤더 링크·맞춤광고 옵트아웃·법 준수.

    ⚠️ 고지는 **어떤 상태에서도 삭제하지 않는다**(F2 = 강제 필수). 관측 상태에 따라 바뀌는 것은
    **시제뿐**이다 — 광고가 관측되면 현재형("We use Google AdSense to display ads"), 관측되지 않으면
    "지금은 게재하지 않는다 + 게재하게 되면 이렇게 된다"는 조건형. 벤더 링크·옵트아웃 안내·권리·연락처는
    양쪽 모두 그대로 남는다.

    왜 고쳤나(실측 2026-07-25, ORDER 2026-07-25-17-ops ①): 렌더 템플릿 2개 + 빌드 산출물 전수에서
    광고 코드 0건인데 이 페이지가 "We use Google AdSense to display ads" 를 현재형으로 단정했다
    → 개인정보처리방침 자체가 사실과 다른 문서가 된다(승인 심사 리스크). 광고 코드가 들어오는 순간
    관측이 잡아내 문장이 자동으로 현재형으로 돌아온다(사람이 잊어도 켜진다).
    ⚠️ 실서비스 전 법률 검토·연락 이메일 채우기.
    """
    ads = bool(mon.get("ads"))
    aff = bool(mon.get("affiliate"))
    # ① 수집 항목 — '광고 쿠키'는 광고가 실제로 돌 때만 사실이다.
    collect = ("<p>We collect standard log data (IP address, browser type, pages visited) and use cookies "
               "and similar technologies to operate the site and serve advertising.</p>") if ads else (
        "<p>We collect standard log data — IP address, browser type, and the pages you visit — which our web "
        "server records for every request. In your browser the site itself stores only your light/dark theme "
        "preference. It sets no advertising cookies of its own; the third-party advertising cookies described "
        "below apply once advertising is running on this site.</p>")
    # ② 광고·제3자 쿠키 — 고지 본문(벤더·옵트아웃)은 유지하고 시제만 바꾼다.
    advertising = ("<p>We use Google AdSense to display ads. Third-party vendors, including Google, use cookies "
                   "to serve ads based on your prior visits to this and other websites. Google's use of "
                   "advertising cookies enables it and its partners to serve ads based on your visits.</p>") if ads else (
        "<p>This site does not currently display advertising: there is no ad-network code in our page templates "
        "or in the pages we publish, so no advertising cookies are set through this site today. This section "
        "describes what applies once advertising is enabled, and the choices below are available to you either "
        "way. The status stated here is re-checked automatically every time this site is built.</p>\n"
        "<p>We intend to serve advertising through Google AdSense. Once ads are running, third-party vendors, "
        "including Google, use cookies to serve ads based on your prior visits to this and other websites. "
        "Google's use of advertising cookies enables it and its partners to serve ads based on your visits.</p>")
    # ③ 광고·제휴 고지 — 광고/제휴를 독립적으로 서술(둘 중 하나만 켜져도 정확하게).
    ad_line = ("This site is supported by advertising." if ads else
               "This site does not currently carry advertising.")
    aff_line = ("It may also contain affiliate links: if you click certain links and make a qualifying purchase, "
                "we may earn a commission at no additional cost to you." if aff else
                "The vendor links in our articles are plain informational citations — they are not affiliate "
                "links and earn us no commission.")
    verdict_line = ("Our comparisons and verdicts are based on documented product features and publicly available "
                    "information; commissions do not influence our assessments." if (ads or aff) else
                    "Our comparisons and verdicts are based on documented product features and publicly available "
                    "information. If we add advertising or affiliate links, this disclosure is updated to say so, "
                    "and neither would influence our assessments.")
    return f"""<p><em>Last updated: {PRIVACY_LAST_UPDATED}.</em></p>
<p>This Privacy Policy explains how {esc(domain)} ("we") collects, uses, and shares information when you visit our site.</p>
<h3>Information we collect</h3>
{collect}
<h3>Advertising &amp; third-party cookies</h3>
{advertising}
<ul>
<li>You may opt out of personalized advertising by visiting <a href="https://www.google.com/settings/ads" rel="noopener" target="_blank">Google Ads Settings</a>.</li>
<li>You may opt out of some third-party vendors' use of cookies for personalized advertising at <a href="https://www.aboutads.info/choices/" rel="noopener" target="_blank">aboutads.info/choices</a>.</li>
<li>See <a href="https://policies.google.com/technologies/partner-sites" rel="noopener" target="_blank">how Google uses data</a> from sites that use its services.</li>
</ul>
<h3>Advertising &amp; affiliate disclosure</h3>
<p>{ad_line} {aff_line} {verdict_line}</p>
<h3>Your rights</h3>
<p>Depending on your location, you may have rights under laws such as the GDPR and CCPA, including access, correction, and deletion. We comply with applicable data-protection laws.</p>
<h3>Contact</h3>
<p>Questions about this policy: <a href="mailto:{esc(email)}">{esc(email)}</a>.</p>"""


esc = html.escape


def _about_body(domain: str, email: str, mon: dict) -> str:
    # E-E-A-T(F: SQRG "누가 책임지고 누가 작성했는지 명확히" + helpful-content who/how/why):
    # 사실만 기술 — 허위 저자·경험 주장 금지(reviewer 루브릭). 편집팀 별칭은 Google 상 허용.
    # 자금 조달(아래 'how we are funded') 도 사실만 — 광고·제휴 여부는 _monetization_observed() 관측값.
    ads, aff = bool(mon.get("ads")), bool(mon.get("affiliate"))
    funding = ("<p>This site is supported by advertising and may include affiliate links. Commissions, when they "
               "exist, do <strong>not</strong> influence our assessments — verdicts are based on documented "
               "product features and publicly available information. See our "
               '<a href="/privacy/">Privacy Policy</a> for the full advertising and affiliate disclosure.</p>'
               ) if (ads or aff) else (
        "<p>This site does not currently carry advertising, and the vendor links in our articles are plain "
        "informational citations rather than affiliate links. We intend to fund the site with advertising; if "
        "we add advertising or affiliate links, our <a href=\"/privacy/\">Privacy Policy</a> is updated to "
        "disclose it. Either way, verdicts are based on documented product features and publicly available "
        "information and are <strong>not</strong> influenced by how the site is funded.</p>")
    return f"""<p><strong>{esc(domain)}</strong> is an independent editorial project that publishes
in-depth comparisons and buying guides for SaaS, developer, and AI tools. Our goal is a single, honest
answer to "which of these tools should I choose, and why" — backed by documented features and public data,
not marketing copy.</p>

<h3>Who is responsible for this site</h3>
<p>Content is researched, written, and maintained by <strong>{esc(renderer.EDITOR_BYLINE)}</strong>, the editorial
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
{funding}

<h3>Corrections</h3>
<p>We aim to be accurate and will fix mistakes promptly. If a figure looks wrong or a price is stale,
<a href="/contact/">let us know</a> and we will verify against the source and update the page.</p>"""


def _og_svg(domain: str) -> str:
    """소셜 공유용 브랜디드 OG 카드(1200×630 정적 SVG). head 의 og:image/twitter:image 가 가리킴.
    ⚠️ 일부 플랫폼은 SVG og:image 미지원 — 오가닉 중심이라 후순위 보강(래스터 필요 시 별도)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" '
        'font-family="Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0f1115"/><stop offset="1" stop-color="#1b2233"/></linearGradient></defs>'
        '<rect width="1200" height="630" fill="url(#bg)"/>'
        '<rect x="80" y="86" width="64" height="64" rx="15" fill="#2f6df6"/>'
        '<text x="112" y="132" font-size="38" font-weight="700" fill="#fff" text-anchor="middle" '
        f'font-family="Consolas,monospace">{esc(renderer.BRAND_MARK)}</text>'
        f'<text x="164" y="134" font-size="40" font-weight="700" fill="#e7ebf2">{esc(renderer.SITE_NAME)}'
        f'<tspan fill="#9aa4b2" font-weight="500">   {esc(domain)}</tspan></text>'
        '<text x="80" y="330" font-size="72" font-weight="800" fill="#e7ebf2">Tool choices, backed'
        '<tspan x="80" dy="86">by <tspan fill="#5b9cff">data</tspan> — not vibes.</tspan></text>'
        '<text x="80" y="548" font-size="30" fill="#9aa4b2">Independent SaaS, developer &amp; AI tool comparisons '
        'from official docs.</text>'
        '</svg>\n')


def _favicon_ico() -> bytes:
    """브랜드 파비콘(/favicon.ico — 16·32px 2엔트리). og.svg 마크와 동일한 시각언어:
    액센트 블루(#2f6df6, design.md) 라운드 사각형 + 흰 브랜드 마크(renderer.BRAND_MARK).

    외부 에셋·폰트·라이브러리 없이 픽셀을 직접 합성한다(자립적, 표준 라이브러리만).
    4× 수퍼샘플링으로 모서리·글자에 안티에일리어싱을 준다. 형식은 ICO 안의 32bpp BGRA 비트맵.
    ⚠️ web_root 수동 업로드는 다음 재빌드에서 지워진다 → 반드시 이 빌드 경로에서 생성한다.
    """
    ACCENT = (0x2F, 0x6D, 0xF6)      # design.md --accent (테크 블루)
    SS = 4                            # 수퍼샘플링 배율

    def _inside_rrect(x, y, r=0.22):  # 정규화 좌표(0~1) 라운드 사각형
        cx = min(max(x, r), 1 - r)
        cy = min(max(y, r), 1 - r)
        dx, dy = x - cx, y - cy
        return (dx * dx + dy * dy) <= r * r if (dx or dy) else True

    # 브랜드 마크 글리프 — `renderer.BRAND_MARK` 를 그린다(ORDER 47 (a): 사이트명 Utilverse → 'U').
    # 블록형 모노스페이스로 단순화해 16px 에서도 형태가 뭉개지지 않게 한다. 마크를 되돌리려면
    # renderer.BRAND_MARK 를 바꾸고, 해당 글자의 획 정의를 아래에 추가하면 된다(모르는 글자는 'S' 로 폴백).
    GX0, GX1, GY0, GY1, T = 0.28, 0.72, 0.17, 0.83, 0.11     # 글리프 박스·획 두께
    GMID = (GY0 + GY1) / 2

    def _inside_u(x, y):                                      # 좌·우 세로획 + 아래 가로획
        if not (GX0 <= x <= GX1 and GY0 <= y <= GY1):
            return False
        if y >= GY1 - T:                                      # 아래 가로획
            return True
        return x <= GX0 + T or x >= GX1 - T                   # 좌·우 세로획

    def _inside_s(x, y):
        if not (GX0 <= x <= GX1 and GY0 <= y <= GY1):
            return False
        if y <= GY0 + T or y >= GY1 - T:                      # 위·아래 가로획
            return True
        if GMID - T / 2 <= y <= GMID + T / 2:                 # 가운데 가로획
            return True
        if y < GMID and x <= GX0 + T:                         # 좌상 세로획
            return True
        if y > GMID and x >= GX1 - T:                         # 우하 세로획
            return True
        return False

    _inside_mark = {"U": _inside_u, "S": _inside_s}.get(renderer.BRAND_MARK, _inside_s)

    def _bitmap(size: int) -> bytes:
        rows = []
        for py in range(size - 1, -1, -1):                    # BMP 는 bottom-up
            row = bytearray()
            for px in range(size):
                n_rect = n_s = 0
                for sy in range(SS):
                    for sx in range(SS):
                        x = (px + (sx + 0.5) / SS) / size
                        y = (py + (sy + 0.5) / SS) / size
                        if _inside_rrect(x, y):
                            n_rect += 1
                            if _inside_mark(x, y):
                                n_s += 1
                total = SS * SS
                alpha = round(255 * n_rect / total)
                if n_rect:
                    t = n_s / n_rect                          # 흰 글자 비율로 블루↔화이트 혼합
                    b = round(ACCENT[2] + (255 - ACCENT[2]) * t)
                    g = round(ACCENT[1] + (255 - ACCENT[1]) * t)
                    r = round(ACCENT[0] + (255 - ACCENT[0]) * t)
                else:
                    b = g = r = 0
                row += bytes((b, g, r, alpha))                # BGRA
            rows.append(bytes(row))
        xor = b"".join(rows)
        mask_row = ((size + 31) // 32) * 4                    # AND 마스크(전부 0 = 불투명, 알파로 처리)
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                             len(xor), 0, 0, 0, 0)
        return header + xor + b"\x00" * (mask_row * size)

    sizes = (16, 32)
    images = [_bitmap(s) for s in sizes]
    offset = 6 + 16 * len(sizes)
    out = struct.pack("<HHH", 0, 1, len(sizes))               # ICONDIR
    for s, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    return out + b"".join(images)


def build(cfg) -> str:
    domain = _domain(cfg)
    base = f"https://{domain}"
    # AdSense 소유권 확인 — 렌더 시작 **전에** 주입해야 모든 페이지 head 에 실린다(빈 값이면 무동작).
    pub_id = _adsense_publisher_id(cfg)
    renderer.set_adsense_publisher_id(pub_id)
    # 수익화 관측(/privacy/·/about/ 문구가 여기에 연동된다) — ⚠️ dist/site 를 지우기 **전에** 해야
    # 직전 빌드 산출물까지 스캔 대상에 들어간다(_monetization_observed docstring ②).
    mon = _monetization_observed(cfg)
    print(f"build: 수익화 관측 — ads={mon.get('ads')} affiliate={mon.get('affiliate')} "
          f"(스캔: {mon.get('scanned')}) / 근거: " + "; ".join(mon.get("evidence") or [])[:220])
    # 기존 산출물 정리 — Windows 파일 잠금(AV·열린 핸들 등) 일시적 대비 재시도 후 최후 ignore_errors.
    # (배포 크래시 방지: 잠금으로 rmtree 실패 시 그날 배포 전체가 rc=1 로 죽던 문제 — 2026-07 재발 방지)
    if os.path.isdir(SITE_DIR):
        import shutil
        import time
        for _i in range(5):
            try:
                shutil.rmtree(SITE_DIR)
                break
            except PermissionError as e:
                print(f"build: dist/site 정리 재시도({_i + 1}/5) — {e}")
                time.sleep(0.6)
        else:
            shutil.rmtree(SITE_DIR, ignore_errors=True)   # 최후: 가능한 만큼 제거(빌드가 덮어씀)
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
        "privacy": ("Privacy Policy", _privacy_body(domain, email, mon)),
        "about": ("About & editorial standards", _about_body(domain, email, mon)),
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

    # 4.5) ads.txt — AdSense 사이트 소유권 확인(광고 게재 코드가 아니다). 유효한 ID 가 있을 때만 생성,
    #      없으면 파일 자체를 만들지 않는다(= 지금처럼 404).
    #      ⚠️ 두 가지가 틀리면 파일이 무효다: (1) 'ca-' 없는 `pub-` 로 시작한다  (2) 개행은 LF —
    #      Windows 텍스트 모드 쓰기는 CRLF 가 되므로 바이트로 직접 쓴다(cron 셰방을 깨먹은 전례).
    if pub_id:
        _write_bytes(os.path.join(SITE_DIR, "ads.txt"),
                     f"google.com, {pub_id[len('ca-'):]}, DIRECT, f08c47fec0942fa0\n".encode())

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

    # 8) 온사이트 검색 — 프리빌트 인덱스(JSON) + /search/ (인라인 JS 필터). Google 오프로드 제거 → 리텐션.
    search_index = [{"title": _short(p["title"]), "url": p["url"],
                     "cat": _cat_label(p), "desc": p.get("desc") or ""} for p in pages]
    for cslug, cname, dek, _cids in CATEGORIES:
        if f"/{cslug}/" in active_cat_paths:
            search_index.append({"title": cname, "url": f"/{cslug}/", "cat": "Category", "desc": dek})
    _write(os.path.join(SITE_DIR, "search-index.json"),
           json.dumps(search_index, ensure_ascii=False, separators=(",", ":")))
    _write(os.path.join(SITE_DIR, "search", "index.html"),
           renderer.render_search_page(canonical=f"{base}/search/"))

    # 9) og:image 소셜 카드 — 브랜디드 정적 SVG (head 의 og:image/twitter:image 가 가리킴)
    _write(os.path.join(SITE_DIR, "og.svg"), _og_svg(domain))

    # 10) /favicon.ico — 브라우저·Googlebot-Image 의 관례 경로(태그 없이도 요청됨).
    #     매 빌드 재생성: cron 이 web_root 를 재빌드로 갈아끼우므로 수동 업로드는 살아남지 못한다.
    _write_bytes(os.path.join(SITE_DIR, "favicon.ico"), _favicon_ico())

    print(f"build: {len(pages)} 콘텐츠 + {len(cat_urls)} 카테고리 허브 + {len(static_pages)} 필수 페이지 "
          f"+ sitemap/robots{' + GSC(' + gsc + ')' if gsc else ''}{' + IndexNow-key' if inkey else ''}"
          f"{' + ads.txt(' + pub_id + ')' if pub_id else ''} "
          f"+ feed.xml + search({len(search_index)}) + og.svg + favicon.ico → {SITE_DIR}/")
    print(f"build: 내부 링크 교정: Related {fixed_related}개 링크 + 브레드크럼 {fixed_crumb}개 페이지 "
          f"(실제 발행 페이지로 재작성)")
    return SITE_DIR
