"""renderer.py — design.md 디자인 시스템을 HTML로 구현 (생성기가 모든 페이지에 적용).

CWV 내장: 시스템 폰트(웹폰트 fetch 0), 인라인 critical CSS, 광고 슬롯 치수 예약(CLS 0),
JS 최소(테마 토글·없음). spec 은 속성만 읽으므로 generator 와 순환 import 없음.
"""
from __future__ import annotations
import html
import json
import re

esc = html.escape


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


CSS = r"""
*{box-sizing:border-box}
:root{--bg:#fff;--surface:#f7f8fa;--surface-2:#eef1f6;--ink:#1a1f2b;--ink-soft:#3d4654;--muted:#5b6573;--line:#e5e8ee;--line-strong:#d3d8e2;--accent:#2f6df6;--accent-ink:#1b4fd1;--good:#0f8a5f;--bad:#c2392f;--code-bg:#0f1320;--code-ink:#e7ebf2;--ad-bg:#f4f6fa;--ad-label:#9aa4b2;--maxw:1120px;--art:720px}
:root[data-theme=dark]{--bg:#0f1115;--surface:#171a21;--surface-2:#1d212b;--ink:#e7ebf2;--ink-soft:#c4ccd8;--muted:#9aa4b2;--line:#2a2f3a;--line-strong:#3a4150;--accent:#5b9cff;--accent-ink:#8bb6ff;--good:#2ecc71;--bad:#ff6b6b;--code-bg:#0c0e13;--ad-bg:#141821;--ad-label:#6b7585}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Malgun Gothic",sans-serif}
img{max-width:100%;height:auto}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.container{max-width:var(--maxw);margin:0 auto;padding:0 20px}
header.site{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line)}
header.site .row{display:flex;align-items:center;gap:18px;height:56px}
.brand{font-weight:800;font-size:18px;color:var(--ink)}.brand .dot{color:var(--accent)}
nav.cats{display:flex;gap:14px;font-size:14px;flex-wrap:wrap}nav.cats a{color:var(--muted)}
.spacer{flex:1}
.tbtn{border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);border-radius:8px;padding:6px 10px;font-size:13px;cursor:pointer}
.layout{display:block}
@media(min-width:1024px){.layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:40px;align-items:start}}
main{min-width:0}article{max-width:var(--art)}
.crumb{font-size:12.5px;color:var(--muted);margin:18px 0 6px}.crumb a{color:var(--muted)}
h1{font-size:32px;line-height:1.2;margin:6px 0 10px}
.dek{font-size:18px;color:var(--ink-soft);margin:0 0 14px}
.metabar{display:flex;flex-wrap:wrap;gap:10px 16px;font-size:13px;color:var(--muted);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:10px 0}
.metabar b{color:var(--ink-soft);font-weight:600}
.toc{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:18px 0;font-size:14px}
.toc strong{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:6px}
.toc a{display:block;padding:2px 0;color:var(--ink-soft)}
article h2{font-size:24px;margin:34px 0 10px;padding-left:12px;border-left:3px solid var(--accent);scroll-margin-top:64px}
article h3{font-size:19px;margin:22px 0 8px}article p{margin:12px 0;color:var(--ink-soft)}
.scroll{overflow-x:auto;margin:16px 0}
table.cmp{width:100%;border-collapse:collapse;font-size:14px;min-width:520px}
table.cmp th,table.cmp td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
table.cmp thead th{position:sticky;top:56px;background:var(--surface-2);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
table.cmp tbody tr:nth-child(even){background:var(--surface)}
table.cmp .win{color:var(--good);font-weight:700}.feat{color:var(--ink);font-weight:600}
.pricing,.pc{display:grid;gap:14px;margin:16px 0}
@media(min-width:560px){.pricing,.pc{grid-template-columns:1fr 1fr}}
.price-card,.pc .box{border:1px solid var(--line);border-radius:12px;padding:16px 18px;background:var(--surface)}
.price-card .pn{font-weight:700}.price-card .pp{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums;margin:6px 0}
.price-card ul,.pc ul{margin:8px 0 12px;padding-left:18px;color:var(--ink-soft);font-size:14px}
.cta{display:inline-block;background:var(--accent);color:#fff;border-radius:8px;padding:8px 14px;font-size:14px;font-weight:600}.cta:hover{text-decoration:none;background:var(--accent-ink)}
.pc h4{margin:0 0 8px;font-size:15px}.pc .pros li::marker{color:var(--good)}.pc .cons li::marker{color:var(--bad)}
.verdict{border:1px solid var(--line);border-left:4px solid var(--accent);background:var(--surface);border-radius:10px;padding:14px 18px;margin:20px 0}
.verdict h2{border:0;padding:0;margin:0 0 8px}
.author{display:flex;gap:12px;align-items:flex-start;border-top:1px solid var(--line);margin-top:30px;padding-top:16px;font-size:14px;color:var(--muted)}
.author .av{width:42px;height:42px;border-radius:50%;background:var(--surface-2);flex:none;display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--accent)}
.author b{color:var(--ink-soft)}
.sources{font-size:13px;color:var(--muted);margin-top:20px}.sources ol{padding-left:18px}
.related{border-top:1px solid var(--line);margin-top:24px;padding-top:14px}.related h3{font-size:15px;margin:0 0 8px}.related a{display:block;padding:4px 0}
.ad-slot{display:flex;align-items:center;justify-content:center;background:var(--ad-bg);border:1px dashed var(--line-strong);border-radius:8px;color:var(--ad-label);font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin:22px 0}
.ad-slot.leaderboard{min-height:90px}.ad-slot.in-content{min-height:280px}.ad-slot.sidebar{min-height:600px;position:sticky;top:72px}
footer.site{border-top:1px solid var(--line);margin-top:48px;padding:24px 0;font-size:13px;color:var(--muted)}footer.site a{color:var(--muted);margin-right:14px}
.draft{background:#f5b942;color:#1a1f2b;text-align:center;font-size:13px;font-weight:700;padding:8px 12px}
code,pre{font-family:ui-monospace,SFMono-Regular,"Cascadia Code",Consolas,monospace}
pre{background:var(--code-bg);color:var(--code-ink);padding:14px 16px;border-radius:10px;overflow-x:auto;font-size:13.5px}
code{background:var(--surface-2);padding:1px 6px;border-radius:5px;font-size:13.5px}
"""

THEME_INIT = "<script>try{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}</script>"
THEME_TOGGLE = "<script>document.querySelector('.tbtn').addEventListener('click',function(){var d=document.documentElement,n=d.getAttribute('data-theme')==='dark'?'':'dark';if(n)d.setAttribute('data-theme',n);else d.removeAttribute('data-theme');try{localStorage.setItem('theme',n)}catch(e){}})</script>"

AD = '<div class="ad-slot {cls}" data-ad-slot="{name}">Advertisement</div>'  # 치수 예약(CLS 0) — 실서비스 시 AdSense ins 삽입


def _ad(name, cls):
    return AD.format(name=name, cls=cls)


def _crumb(items):
    out = []
    for i, (name, url) in enumerate(items):
        if i == len(items) - 1:
            out.append(esc(name))
        else:
            out.append(f'<a href="{esc(url)}">{esc(name)}</a>')
    return '<div class="crumb">' + " › ".join(out) + "</div>"


def _comparison(c):
    a, b = esc(c["a"]), esc(c["b"])
    rows = ""
    for r in c["rows"]:
        wa = ' class="win"' if r.get("winner") == "a" else ""
        wb = ' class="win"' if r.get("winner") == "b" else ""
        rows += (f'<tr><td class="feat">{esc(r["feature"])}</td>'
                 f'<td{wa}>{esc(r["a"])}</td><td{wb}>{esc(r["b"])}</td></tr>')
    return ('<div class="scroll"><table class="cmp"><thead><tr><th>Feature</th>'
            f'<th>{a}</th><th>{b}</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _pricing(plans):
    cards = ""
    for p in plans:
        feats = "".join(f"<li>{esc(f)}</li>" for f in p.get("features", []))
        cta = p.get("cta")
        cta_html = f'<a class="cta" href="{esc(cta["url"])}" rel="nofollow sponsored">{esc(cta["label"])}</a>' if cta else ""
        cards += (f'<div class="price-card"><div class="pn">{esc(p["name"])}</div>'
                  f'<div class="pp">{esc(p["price"])}</div><ul>{feats}</ul>{cta_html}</div>')
    return f'<div class="pricing">{cards}</div>'


def _proscons(items):
    boxes = ""
    for it in items:
        pros = "".join(f"<li>{esc(x)}</li>" for x in it.get("pros", []))
        cons = "".join(f"<li>{esc(x)}</li>" for x in it.get("cons", []))
        boxes += (f'<div class="box"><h4>{esc(it["name"])}</h4>'
                  f'<ul class="pros">{pros}</ul><ul class="cons">{cons}</ul></div>')
    return f'<div class="pc">{boxes}</div>'


def _jsonld(spec):
    data = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": spec.title, "description": spec.dek,
        "author": {"@type": "Person", "name": spec.author},
        "datePublished": spec.published_at, "dateModified": spec.updated_at or spec.published_at,
    }
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"


def render(spec, draft: bool = False) -> str:
    # 섹션 + TOC + 본문 사이 인-콘텐츠 광고(치수 예약)
    toc, body = [], []
    for i, s in enumerate(spec.sections):
        sid = slugify(s["heading"])
        toc.append(f'<a href="#{sid}">{esc(s["heading"])}</a>')
        body.append(f'<h2 id="{sid}">{esc(s["heading"])}</h2>{s["html"]}')
        if i == 1:  # 2번째 섹션 뒤 인-콘텐츠 광고
            body.append(_ad("in-content-1", "in-content"))
        if i == 1 and getattr(spec, "comparison", None):
            body.append(_comparison(spec.comparison))
        if i == 2 and getattr(spec, "pricing", None):
            body.append("<h2 id=\"pricing\">Pricing compared</h2>" + _pricing(spec.pricing))
            toc.append('<a href="#pricing">Pricing compared</a>')
        if i == 2 and getattr(spec, "pros_cons", None):
            body.append("<h2 id=\"pros-cons\">Pros &amp; cons</h2>" + _proscons(spec.pros_cons))
            toc.append('<a href="#pros-cons">Pros &amp; cons</a>')

    verdict = ""
    if getattr(spec, "verdict_html", None):
        verdict = f'<div class="verdict"><h2 id="verdict">Verdict</h2>{spec.verdict_html}</div>'
        toc.append('<a href="#verdict">Verdict</a>')

    sources = ""
    if spec.sources:
        items = "".join(f'<li><a href="{esc(s["url"])}" rel="noopener" target="_blank">{esc(s["title"])}</a></li>' for s in spec.sources)
        sources = f'<div class="sources"><strong>Sources</strong><ol>{items}</ol></div>'

    related = ""
    if getattr(spec, "related", None):
        links = "".join(f'<a href="{esc(r["url"])}">{esc(r["title"])}</a>' for r in spec.related)
        related = f'<div class="related"><h3>Related</h3>{links}</div>'

    author = (f'<div class="author"><div class="av">{esc(spec.author[:1].upper())}</div>'
              f'<div>By <b>{esc(spec.author)}</b>{(" · " + esc(spec.author_bio)) if getattr(spec, "author_bio", None) else ""}'
              f'<br>Published {esc(spec.published_at)}{(" · Updated " + esc(spec.updated_at)) if spec.updated_at else ""}</div></div>')

    metabar = (f'<div class="metabar"><span>By <b>{esc(spec.author)}</b></span>'
               f'<span>Updated <b>{esc(spec.updated_at or spec.published_at)}</b></span>'
               f'<span><b>{esc(str(getattr(spec, "reading_time", 6)))}</b> min read</span></div>')

    draft_banner = '<div class="draft">DRY-RUN PREVIEW · 샘플 초안 (미발행) · 자동 생성 콘텐츠</div>' if draft else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(spec.title)}</title>
<meta name="description" content="{esc(spec.dek)}">
<link rel="canonical" href="{esc(getattr(spec, 'canonical', ''))}">
{THEME_INIT}
<style>{CSS}</style>
{_jsonld(spec)}
</head>
<body>
{draft_banner}
<header class="site"><div class="container row">
<span class="brand">stack<span class="dot">.</span></span>
<nav class="cats"><a href="/ai-coding/">AI Coding</a><a href="/hosting/">Hosting</a><a href="/dev-tools/">Dev Tools</a><a href="/ai-tools/">AI Tools</a></nav>
<span class="spacer"></span><button class="tbtn" aria-label="Toggle theme">◐ Theme</button>
</div></header>

<div class="container layout">
<main><article>
{_crumb(spec.breadcrumb)}
<h1>{esc(spec.title)}</h1>
<p class="dek">{esc(spec.dek)}</p>
{metabar}
{_ad("below-hero", "leaderboard")}
<nav class="toc"><strong>Contents</strong>{''.join(toc)}</nav>
{spec.intro_html}
{''.join(body)}
{verdict}
{author}
{sources}
{related}
</article></main>
<aside>{_ad("sidebar", "sidebar")}</aside>
</div>

<footer class="site"><div class="container">
<a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy Policy</a>
<p>© 2026 stack.utilverse.info · Independent software comparisons &amp; guides.</p>
</div></footer>
{THEME_TOGGLE}
</body>
</html>"""


def render_static_page(title: str, body_html: str, *, description: str = "") -> str:
    """필수/정적 페이지(Privacy·About·Contact·index) — 광고 없는 단순 본문, 동일 디자인 셸."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description or title)}">
{THEME_INIT}
<style>{CSS}</style>
</head>
<body>
<header class="site"><div class="container row">
<a class="brand" href="/">stack<span class="dot">.</span></a>
<nav class="cats"><a href="/ai-coding/">AI Coding</a><a href="/hosting/">Hosting</a><a href="/dev-tools/">Dev Tools</a><a href="/ai-tools/">AI Tools</a></nav>
<span class="spacer"></span><button class="tbtn" aria-label="Toggle theme">◐ Theme</button>
</div></header>
<div class="container"><main><article>
<h1>{esc(title)}</h1>
{body_html}
</article></main></div>
<footer class="site"><div class="container">
<a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy Policy</a>
<p>© 2026 stack.utilverse.info · Independent software comparisons &amp; guides.</p>
</div></footer>
{THEME_TOGGLE}
</body>
</html>"""
