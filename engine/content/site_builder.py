"""site_builder.py — 정적 사이트 빌드 (AUTOMATION.md §2 PUBLISH, static_ssg).

dist/queue 의 게이트 통과 페이지 + 필수 페이지(Privacy 필수 F2·About·Contact) + 인덱스
+ sitemap.xml + robots.txt → dist/site/ (Caddy 서빙 대상). Pretty URL(/compare/<slug>/).
"""
from __future__ import annotations
import glob
import html
import os
import re

from content import renderer

SITE_DIR = "dist/site"
QUEUE_DIR = "dist/queue"


def _domain(cfg) -> str:
    try:
        return cfg["sites"]["sites"][0]["domain"]
    except Exception:
        return "stack.utilverse.info"


def _title_of(html_doc: str, fallback: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html_doc, re.S)
    return html.unescape(m.group(1).strip()) if m else fallback


def _meta_of(doc: str) -> dict:
    """렌더된 페이지에서 홈 카드용 메타 추출(읽는 시간·갱신일·설명)."""
    read = re.search(r"(\d+)\s*min read", doc)
    upd = re.search(r"Updated <time>([^<]+)</time>", doc)
    desc = re.search(r'<meta name="description" content="([^"]*)">', doc)
    cl = re.search(r'<meta name="cluster" content="([^"]*)">', doc)
    return {
        "read": f"{read.group(1)} min read" if read else None,
        "updated": upd.group(1).strip() if upd else None,
        "desc": html.unescape(desc.group(1)) if desc else None,
        "cluster": cl.group(1) if cl else None,
    }


# 카테고리 허브 (헤더·홈 nav 가 링크하는 URL) — topics.yaml 클러스터 id 매핑
CATEGORIES = [
    ("ai-coding", "AI Coding", "Editors, assistants, and AI coding tools — compared hands-on.", {"ai-coding-tools"}),
    ("hosting", "Hosting & Self-host", "VPS, cloud hosting, and self-hosting — compared hands-on.", {"hosting-selfhost"}),
    ("dev-tools", "Dev Tools", "SaaS and developer tools — compared hands-on.", {"dev-saas-compare"}),
    ("ai-tools", "AI Tools", "Productivity and creative AI tools — compared hands-on.", {"ai-productivity"}),
    ("vpn-security", "VPN & Security", "VPNs, password managers, and security tools — compared hands-on.", {"vpn-security"}),
]


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _privacy_body(domain: str) -> str:
    # AdSense 필수(F2): 데이터 수집·제3자 쿠키·벤더 링크·맞춤광고 옵트아웃·법 준수.
    # ⚠️ 실서비스 전 법률 검토·연락 이메일 채우기.
    return f"""<p><em>Last updated: 2026-06-28. Review with counsel before launch; replace contact email.</em></p>
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
<h3>Your rights</h3>
<p>Depending on your location, you may have rights under laws such as the GDPR and CCPA, including access, correction, and deletion. We comply with applicable data-protection laws.</p>
<h3>Contact</h3>
<p>Questions about this policy: <a href="mailto:contact@{esc(domain)}">contact@{esc(domain)}</a>.</p>"""


esc = html.escape


def build(cfg) -> str:
    domain = _domain(cfg)
    base = f"https://{domain}"
    # 기존 산출물 정리
    if os.path.isdir(SITE_DIR):
        import shutil
        shutil.rmtree(SITE_DIR)
    os.makedirs(SITE_DIR, exist_ok=True)

    # 1) 콘텐츠 페이지 (dist/queue → /compare/<slug>/)
    pages = []
    for qf in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.html"))):
        slug = os.path.splitext(os.path.basename(qf))[0]
        with open(qf, encoding="utf-8") as f:
            doc = f.read()
        _write(os.path.join(SITE_DIR, "compare", slug, "index.html"), doc)
        pages.append({"slug": slug, "title": _title_of(doc, slug),
                      "url": f"/compare/{slug}/", **_meta_of(doc)})

    # 2) 필수/정적 페이지 (Privacy 필수 — F2)
    static_pages = {
        "privacy": ("Privacy Policy", _privacy_body(domain)),
        "about": ("About", "<p>We publish independent, hands-on comparisons and guides for SaaS, developer, and AI tools.</p>"),
        "contact": ("Contact", f'<p>Reach us at <a href="mailto:contact@{esc(domain)}">contact@{esc(domain)}</a>.</p>'),
    }
    for path, (title, body) in static_pages.items():
        _write(os.path.join(SITE_DIR, path, "index.html"),
               renderer.render_static_page(title, body, description=f"{title} — {domain}"))

    # 3) 홈 (Home 목업 수준 — 히어로·이번 주 비교·카테고리·최신·뉴스레터)
    _write(os.path.join(SITE_DIR, "index.html"),
           renderer.render_home(pages, domain=domain, canonical=f"{base}/"))

    # 3.5) 카테고리 허브 (nav·홈이 링크하는 URL — 항상 5개 생성, 빈 카테고리는 안내)
    cat_urls = []
    for slug, name, dek, cluster_ids in CATEGORIES:
        cat_pages = [p for p in pages if p.get("cluster") in cluster_ids]
        _write(os.path.join(SITE_DIR, slug, "index.html"),
               renderer.render_hub(name, dek, cat_pages, domain=domain, canonical=f"{base}/{slug}/"))
        cat_urls.append(f"{base}/{slug}/")

    # 4) sitemap.xml + robots.txt
    urls = [f"{base}/"] + cat_urls + [f"{base}{p['url']}" for p in pages] + \
           [f"{base}/{p}/" for p in static_pages]
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{esc(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    _write(os.path.join(SITE_DIR, "sitemap.xml"), sitemap)
    _write(os.path.join(SITE_DIR, "robots.txt"),
           f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")

    print(f"build: {len(pages)} 콘텐츠 + {len(CATEGORIES)} 카테고리 허브 + {len(static_pages)} 필수 페이지 "
          f"+ sitemap/robots → {SITE_DIR}/")
    return SITE_DIR
