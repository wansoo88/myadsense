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
        pages.append({"slug": slug, "title": _title_of(doc, slug), "url": f"/compare/{slug}/"})

    # 2) 필수/정적 페이지 (Privacy 필수 — F2)
    static_pages = {
        "privacy": ("Privacy Policy", _privacy_body(domain)),
        "about": ("About", "<p>We publish independent, hands-on comparisons and guides for SaaS, developer, and AI tools.</p>"),
        "contact": ("Contact", f'<p>Reach us at <a href="mailto:contact@{esc(domain)}">contact@{esc(domain)}</a>.</p>'),
    }
    for path, (title, body) in static_pages.items():
        _write(os.path.join(SITE_DIR, path, "index.html"),
               renderer.render_static_page(title, body, description=f"{title} — {domain}"))

    # 3) 인덱스
    items = "".join(f'<li><a href="{esc(p["url"])}">{esc(p["title"])}</a></li>' for p in pages) \
        or "<li>No articles published yet.</li>"
    index_body = (f'<p class="dek">Independent, hands-on comparisons and guides for SaaS, developer, and AI tools.</p>'
                  f'<h3>Latest comparisons</h3><ul>{items}</ul>')
    _write(os.path.join(SITE_DIR, "index.html"),
           renderer.render_static_page("stack. — software comparisons & guides", index_body,
                                       description="Independent SaaS, dev, and AI tool comparisons."))

    # 4) sitemap.xml + robots.txt
    urls = [f"{base}/"] + [f"{base}{p['url']}" for p in pages] + \
           [f"{base}/{p}/" for p in static_pages]
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{esc(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    _write(os.path.join(SITE_DIR, "sitemap.xml"), sitemap)
    _write(os.path.join(SITE_DIR, "robots.txt"),
           f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")

    print(f"build: {len(pages)} 콘텐츠 + {len(static_pages)} 필수 페이지 + sitemap/robots → {SITE_DIR}/")
    return SITE_DIR
