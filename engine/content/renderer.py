"""renderer.py — design.md 디자인 시스템 구현 (design/ 목업 완성도 반영).

생성기가 모든 페이지에 입히는 디자인. 자체완결(인라인 CSS/JS·시스템 폰트·외부 fetch 0),
CWV 안전(치수 예약·JS 최소), E-E-A-T(저자·날짜·출처·JSON-LD), 광고 슬롯 CLS 예약.
spec 은 속성만 읽으므로 generator 와 순환 import 없음.
"""
from __future__ import annotations
import html
import json
import re

esc = html.escape


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_KICKER = {"comparison": "Comparison", "listicle": "Best of",
           "guide": "Guide", "alternatives": "Alternatives"}

CSS = r"""
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
:root{
  --bg:#ffffff;--surface:#f7f8fa;--surface-2:#eef1f6;
  --ink:#1a1f2b;--ink-soft:#3d4654;--muted:#5b6573;
  --line:#e5e8ee;--line-strong:#d3d8e2;
  --accent:#2f6df6;--accent-ink:#1b4fd1;
  --good:#0f8a5f;--warn:#b5791a;--bad:#c2392f;
  --good-tint:#e7f5ee;--bad-tint:#fbeceb;
  --code-bg:#0f1320;--code-ink:#e7ebf2;--ad-bg:#f4f6fa;--ad-label:#9aa4b2;
  --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Malgun Gothic",sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,"Cascadia Code",Consolas,monospace;
}
:root[data-theme=dark]{
  --bg:#0f1115;--surface:#171a21;--surface-2:#1d212b;
  --ink:#e7ebf2;--ink-soft:#c4ccd8;--muted:#9aa4b2;
  --line:#2a2f3a;--line-strong:#3a4150;
  --accent:#5b9cff;--accent-ink:#8bb6ff;
  --good:#2ecc71;--warn:#f5b942;--bad:#ff6b6b;
  --good-tint:#13241c;--bad-tint:#2a1816;
  --code-bg:#0c0e13;--code-ink:#e7ebf2;--ad-bg:#141821;--ad-label:#6b7585;
}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.7 var(--font-sans)}
img{max-width:100%;height:auto}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.skip{position:absolute;left:-9999px}.skip:focus{left:16px;top:8px;background:var(--accent);color:#fff;padding:8px 12px;border-radius:8px;z-index:100}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
/* header */
header.site{position:sticky;top:0;z-index:50;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:saturate(140%) blur(8px);border-bottom:1px solid var(--line)}
.bar{max-width:1120px;margin:0 auto;padding:11px 24px;display:flex;align-items:center;gap:20px}
.brand{display:flex;align-items:center;gap:9px;color:var(--ink);font-weight:700;font-size:16px;letter-spacing:-.01em}
.brand:hover{text-decoration:none}
.brand .badge{display:inline-flex;width:26px;height:26px;border-radius:7px;background:var(--accent);color:#fff;align-items:center;justify-content:center;font-family:var(--font-mono);font-size:14px;font-weight:700}
.brand .tld{color:var(--muted);font-weight:500}
nav.cats{display:flex;gap:18px;font-size:14px;font-weight:500}nav.cats a{color:var(--ink-soft)}
.right{margin-left:auto;display:flex;align-items:center;gap:10px}
.searchpill{display:flex;align-items:center;gap:7px;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 10px;color:var(--muted);font-size:13px;min-width:170px}
.tbtn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:8px;border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);cursor:pointer}
.tbtn:hover{border-color:var(--line-strong);color:var(--ink)}
.tbtn .ic-sun{display:none}[data-theme=dark] .tbtn .ic-sun{display:inline-flex}[data-theme=dark] .tbtn .ic-moon{display:none}
@media(max-width:639px){.hide-sm{display:none}}
/* layout */
.uv-grid{display:grid;grid-template-columns:minmax(0,720px) 300px;gap:48px;max-width:1120px;margin:0 auto;padding:32px 24px 64px}
@media(max-width:1023px){.uv-grid{grid-template-columns:1fr;gap:0}.aside{display:none}}
@media(min-width:1024px){.tocm{display:none}}
main{min-width:0}
.container{max-width:1120px;margin:0 auto;padding:0 24px}
.crumb{font-size:13px;color:var(--muted);margin-bottom:20px;display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.crumb a{color:var(--muted)}.crumb .s{opacity:.5}.crumb .cur{color:var(--ink-soft)}
.kicker{font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--accent)}
h1{font-size:33px;line-height:1.2;letter-spacing:-.02em;margin:10px 0 0;font-weight:800;color:var(--ink);text-wrap:balance}
.dek{font-size:19px;line-height:1.55;color:var(--ink-soft);margin:14px 0 0;max-width:60ch;text-wrap:pretty}
.metabar{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-top:20px;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:13.5px;color:var(--muted)}
.metabar .who{display:flex;align-items:center;gap:9px}.metabar strong{color:var(--ink);font-weight:600}.metabar .sep{opacity:.4}
.av{display:inline-flex;border-radius:50%;background:var(--surface-2);color:var(--ink-soft);align-items:center;justify-content:center;font-weight:700}
.av.sm{width:30px;height:30px;font-size:13px}.av.lg{width:46px;height:46px;font-size:17px;flex:none}
/* mobile toc */
.tocm{margin-top:24px;border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:6px 16px}
.tocm summary{cursor:pointer;font-weight:600;font-size:14px;padding:10px 0;color:var(--ink-soft)}
.tocm a{display:block;padding:6px 0;font-size:14px;color:var(--ink-soft)}
/* sections */
section.blk{margin-top:44px;scroll-margin-top:80px}
h2.bar2{font-size:24px;letter-spacing:-.01em;font-weight:700;margin:0 0 6px;color:var(--ink);display:flex;align-items:center;gap:10px;scroll-margin-top:80px}
h2.bar2::before{content:"";width:4px;height:22px;background:var(--accent);border-radius:2px;display:inline-block;flex:none}
.sub{color:var(--muted);font-size:15px;margin:0 0 18px}
article h3{font-size:19px;font-weight:700;color:var(--ink);margin:24px 0 8px}
article p{color:var(--ink-soft);margin:12px 0;max-width:68ch}
article ul,article ol{color:var(--ink-soft);max-width:68ch}
/* callouts */
.callout{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:0 12px 12px 0;background:var(--surface);padding:20px 22px}
.callout.good{border-left-color:var(--good)}
.callout .lbl{font-size:13px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}
.callout.good .lbl{color:var(--good)}
.callout p{margin:0 0 10px;color:var(--ink-soft)}.callout p:last-child{margin:0}.callout strong{color:var(--ink)}
/* tables */
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin:0}
table.tbl{width:100%;border-collapse:collapse;font-size:15px;min-width:540px}
table.tbl th{position:sticky;top:0;text-align:left;padding:13px 16px;background:var(--surface-2);font-weight:700;color:var(--ink);white-space:nowrap}
table.tbl th.feat{color:var(--muted);font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.03em}
table.tbl th.ctr{text-align:center;width:120px}
table.tbl td{padding:13px 16px;border-top:1px solid var(--line);color:var(--ink-soft)}
table.tbl td.featc{font-weight:600}
table.tbl tbody tr:nth-child(even) td{background:var(--surface)}
table.tbl td.win{background:var(--good-tint)!important;color:var(--ink)}
table.tbl td.ctr{text-align:center;font-weight:700}
.mk-good{color:var(--good)}.mk-warn{color:var(--warn)}.mk-bad{color:var(--bad)}
.note{vertical-align:super;font-size:12px;color:var(--muted);margin-left:2px}
.footnote{font-size:13px;color:var(--muted);margin:10px 2px 0}
/* pricing */
.pricing{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.price-card{border:1px solid var(--line);border-radius:14px;background:var(--surface);padding:18px;display:flex;flex-direction:column;gap:4px}
.price-card .pn{font-size:16px;font-weight:700;color:var(--ink)}
.price-card .pp{font-size:26px;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.02em;margin-top:2px}
.price-card ul{margin:6px 0 12px;padding-left:18px;color:var(--ink-soft);font-size:14px;line-height:1.6}
.cta{display:inline-block;margin-top:auto;background:var(--accent);color:#fff;border-radius:8px;padding:8px 14px;font-size:14px;font-weight:600;text-align:center}
.cta:hover{text-decoration:none;background:var(--accent-ink)}
/* pros/cons */
.pc{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.pc .box{border:1px solid var(--line);border-radius:14px;overflow:hidden}
.pc .hd{padding:13px 18px;background:var(--surface-2);font-weight:700;color:var(--ink)}
.pc .bd{padding:16px 18px}
.pc .lp{font-size:13px;font-weight:700;color:var(--good);margin-bottom:8px}
.pc .lc{font-size:13px;font-weight:700;color:var(--bad);margin:16px 0 8px}
.pc ul{margin:0;padding-left:20px;color:var(--ink-soft);font-size:15px;line-height:1.6}
/* author / sources / related */
.authorbox{margin-top:36px;border:1px solid var(--line);border-radius:14px;background:var(--surface);padding:18px 20px;display:flex;gap:16px;align-items:flex-start}
.authorbox .nm{font-weight:700;color:var(--ink)}.authorbox .bio{font-size:14px;color:var(--muted);margin:2px 0 8px}.authorbox .upd{font-size:13px;color:var(--muted)}
.sources{margin-top:36px;scroll-margin-top:80px}.sources h2{font-size:17px;font-weight:700;color:var(--ink);margin:0 0 10px}
.sources ol{margin:0;padding-left:20px;color:var(--muted);font-size:14px;line-height:1.8}
.related{margin-top:36px;border-top:1px solid var(--line);padding-top:24px}
.related .hd{font-size:13px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
.related .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.related .card{display:block;border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.related .card:hover{border-color:var(--accent);text-decoration:none}
.related .cat{font-size:12px;color:var(--accent);font-weight:600;margin-bottom:4px}
.related .ttl{color:var(--ink);font-weight:600;font-size:15px;line-height:1.4}
/* sidebar toc */
.aside{min-width:0}.aside .sticky{position:sticky;top:80px}
.aside .hd{font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
.toc{display:flex;flex-direction:column;gap:2px;border-left:1px solid var(--line)}
.toc a{padding:6px 0 6px 14px;margin-left:-1px;font-size:14px;border-left:2px solid transparent;color:var(--muted);line-height:1.4}
.toc a.active{border-left-color:var(--accent);color:var(--accent);font-weight:600}
/* ad slots — CLS 예약(치수 미리 확보) */
.ad-slot{display:flex;align-items:center;justify-content:center;background:var(--ad-bg);border:1px dashed var(--line-strong);border-radius:12px;color:var(--ad-label);font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.ad-slot.leaderboard{min-height:90px;margin:24px 0}.ad-slot.in-content{min-height:280px;margin:32px 0}.ad-slot.sidebar{min-height:600px;margin-top:24px}
/* code */
pre,.codeblock{background:var(--code-bg);color:var(--code-ink);border-radius:12px;padding:16px 18px;font-family:var(--font-mono);font-size:13.5px;line-height:1.7;overflow-x:auto;margin:14px 0}
code{font-family:var(--font-mono);font-size:.9em;background:var(--code-bg);color:var(--code-ink);padding:2px 6px;border-radius:5px}
/* footer */
footer.site{border-top:1px solid var(--line);background:var(--surface)}
footer.site .inner{max-width:1120px;margin:0 auto;padding:28px 24px;display:flex;flex-wrap:wrap;gap:20px;align-items:center;font-size:13.5px;color:var(--muted)}
footer.site .fb{font-weight:700;color:var(--ink-soft)}footer.site nav{display:flex;flex-wrap:wrap;gap:16px}footer.site a{color:var(--muted)}footer.site .priv{font-weight:600}footer.site .cp{margin-left:auto}
.draft{background:#f5b942;color:#1a1f2b;text-align:center;font-size:13px;font-weight:700;padding:8px 12px}
"""

THEME_INIT = ("<script>(function(){try{var t=localStorage.getItem('uv-theme')||"
              "(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"
              "document.documentElement.setAttribute('data-theme',t)}catch(e){}})()</script>")

_SCRIPTS = ("<script>"
            "var tb=document.querySelector('.tbtn');if(tb)tb.addEventListener('click',function(){"
            "var d=document.documentElement,n=d.getAttribute('data-theme')==='dark'?'light':'dark';"
            "d.setAttribute('data-theme',n);try{localStorage.setItem('uv-theme',n)}catch(e){}});"
            "var ls=[].slice.call(document.querySelectorAll('.toc a'));"
            "if(ls.length&&'IntersectionObserver'in window){"
            "var io=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){"
            "ls.forEach(function(a){a.classList.toggle('active',a.getAttribute('href')==='#'+en.target.id)})}})},"
            "{rootMargin:'-15% 0px -75% 0px',threshold:0});"
            "ls.forEach(function(a){var el=document.getElementById(a.getAttribute('href').slice(1));if(el)io.observe(el)})}"
            "</script>")

_SUN = '<svg class="ic-sun" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>'
_MOON = '<svg class="ic-moon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"></path></svg>'
_FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
            "%3Crect width='32' height='32' rx='7' fill='%232f6df6'/%3E%3Ctext x='16' y='22' font-size='17'"
            " fill='white' text-anchor='middle' font-family='monospace' font-weight='700'%3ES%3C/text%3E%3C/svg%3E")


def _head(title, description, canonical="", og_type="article", extra=""):
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''}
<link rel="icon" href="{_FAVICON}">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1115" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
{f'<meta property="og:url" content="{esc(canonical)}">' if canonical else ''}
<meta name="twitter:card" content="summary_large_image">
{THEME_INIT}
<style>{CSS}</style>
{extra}"""


def _header():
    return ('<header class="site"><div class="bar">'
            '<a class="brand" href="/"><span class="badge">S</span><span>stack<span class="tld">.utilverse.info</span></span></a>'
            '<nav class="cats hide-sm"><a href="/ai-coding/">AI Coding</a><a href="/hosting/">Hosting</a>'
            '<a href="/dev-tools/">Dev Tools</a><a href="/ai-tools/">AI Tools</a></nav>'
            '<div class="right"><span class="searchpill hide-sm">Search tools…</span>'
            f'<button class="tbtn" aria-label="Toggle theme">{_SUN}{_MOON}</button></div>'
            '</div></header>')


def _footer():
    return ('<footer class="site"><div class="inner">'
            '<span class="fb">stack.utilverse.info</span>'
            '<nav><a href="/about/">About</a><a href="/contact/">Contact</a>'
            '<a class="priv" href="/privacy/">Privacy Policy</a>'
            '<a href="/ai-coding/">AI Coding</a><a href="/hosting/">Hosting</a></nav>'
            '<span class="cp">© 2026 stack.utilverse.info</span>'
            '</div></footer>')


def _ad(name, cls):
    return f'<div class="ad-slot {cls}" data-ad-slot="{name}">Advertisement</div>'


def _crumb(items):
    out = []
    for i, (name, url) in enumerate(items):
        if i == len(items) - 1:
            out.append(f'<span class="cur">{esc(name)}</span>')
        else:
            out.append(f'<a href="{esc(url)}">{esc(name)}</a>')
    return '<nav class="crumb" aria-label="breadcrumb">' + '<span class="s">/</span>'.join(out) + '</nav>'


def _comparison(c):
    rows = ""
    for r in c["rows"]:
        wa = " win" if r.get("winner") == "a" else ""
        wb = " win" if r.get("winner") == "b" else ""
        rows += (f'<tr><td class="featc">{esc(r["feature"])}</td>'
                 f'<td class="{wa.strip()}">{esc(r["a"])}</td><td class="{wb.strip()}">{esc(r["b"])}</td></tr>')
    return ('<div class="tablewrap"><table class="tbl"><thead><tr>'
            f'<th class="feat">Feature</th><th>{esc(c["a"])}</th><th>{esc(c["b"])}</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


def _mark(v):
    cls = {"✓": "mk-good", "△": "mk-warn", "✗": "mk-bad"}.get(str(v).strip(), "")
    return f'<span class="{cls}">{esc(str(v))}</span>' if cls else esc(str(v))


def _matrix(m):
    rows = ""
    for r in m["rows"]:
        note = f'<sup class="note">{esc(str(r["note"]))}</sup>' if r.get("note") else ""
        rows += (f'<tr><td>{esc(r["label"])}{note}</td>'
                 f'<td class="ctr">{_mark(r["a"])}</td><td class="ctr">{_mark(r["b"])}</td></tr>')
    return ('<div class="tablewrap"><table class="tbl"><thead><tr>'
            f'<th class="feat">Feature</th><th class="ctr">{esc(m["a"])}</th><th class="ctr">{esc(m["b"])}</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


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
        boxes += (f'<div class="box"><div class="hd">{esc(it["name"])}</div><div class="bd">'
                  f'<div class="lp">Pros</div><ul>{pros}</ul>'
                  f'<div class="lc">Cons</div><ul>{cons}</ul></div></div>')
    return f'<div class="pc">{boxes}</div>'


def _section(label, sid, inner, sub=""):
    sub_html = f'<p class="sub">{esc(sub)}</p>' if sub else ""
    return f'<section class="blk" id="{sid}"><h2 class="bar2">{esc(label)}</h2>{sub_html}{inner}</section>'


def _jsonld(spec):
    blocks = [{
        "@context": "https://schema.org", "@type": "Article",
        "headline": spec.title, "description": spec.dek,
        "author": {"@type": "Person", "name": spec.author},
        "datePublished": spec.published_at, "dateModified": spec.updated_at or spec.published_at,
        "mainEntityOfPage": spec.canonical or "",
    }]
    if spec.breadcrumb:
        items = [{"@type": "ListItem", "position": i + 1, "name": n,
                  **({"item": u} if u else {})} for i, (n, u) in enumerate(spec.breadcrumb)]
        blocks.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})
    return "".join('<script type="application/ld+json">' + json.dumps(b, ensure_ascii=False) + "</script>"
                   for b in blocks)


def render(spec, draft: bool = False) -> str:
    toc, body = [], []

    def add(label, sid):
        toc.append((label, sid))

    add("Overview", "overview")
    if getattr(spec, "tldr_html", None):
        body.append(_section("At a glance", "summary",
                             f'<div class="callout"><div class="lbl">In short</div>{spec.tldr_html}</div>'))
        add("At a glance", "summary")
    if getattr(spec, "comparison", None):
        body.append(_section("Head to head", "comparison", _comparison(spec.comparison),
                             sub="Key differences side by side; the stronger option is tinted green."))
        add("Head to head", "comparison")
    if getattr(spec, "feature_matrix", None):
        fm = _matrix(spec.feature_matrix)
        note = '<p class="footnote">✓ full · △ partial/paid · ✗ not supported</p>'
        body.append(_section("Feature matrix", "features", fm + note))
        add("Feature matrix", "features")
    if getattr(spec, "pricing", None):
        body.append(_section("Pricing", "pricing", _pricing(spec.pricing),
                             sub="Confirm current pricing on each vendor's site."))
        add("Pricing", "pricing")
    if getattr(spec, "pros_cons", None):
        body.append(_section("Pros & cons", "proscons", _proscons(spec.pros_cons)))
        add("Pros & cons", "proscons")

    body.append(_ad("in-content-1", "in-content"))

    for i, s in enumerate(spec.sections):           # 본문(딥다이브) 섹션
        sid = slugify(s["heading"]) or f"s{i}"
        body.append(_section(s["heading"], sid, s["html"]))
        add(s["heading"], sid)

    if getattr(spec, "verdict_html", None):
        body.append('<section class="blk" id="verdict"><div class="callout good">'
                    f'<div class="lbl">Verdict</div>{spec.verdict_html}</div></section>')
        add("Verdict", "verdict")

    # 저자 박스
    body.append(f'<div class="authorbox"><span class="av lg">{esc(spec.author[:1].upper())}</span><div>'
                f'<div class="nm">{esc(spec.author)}</div>'
                f'<div class="bio">{esc(getattr(spec, "author_bio", "") or "Independent, hands-on software reviews.")}</div>'
                f'<div class="upd">Updated {esc(spec.updated_at or spec.published_at)}</div></div></div>')

    if spec.sources:
        items = "".join(f'<li><a href="{esc(s["url"])}" rel="noopener" target="_blank">{esc(s["title"])}</a></li>'
                        for s in spec.sources)
        body.append(f'<section class="sources" id="sources"><h2>Sources</h2><ol>{items}</ol></section>')
        add("Sources", "sources")

    if getattr(spec, "related", None):
        cards = "".join(f'<a class="card" href="{esc(r["url"])}"><div class="cat">Related</div>'
                        f'<div class="ttl">{esc(r["title"])}</div></a>' for r in spec.related)
        body.append(f'<section class="related"><div class="hd">Related reading</div><div class="cards">{cards}</div></section>')

    # 목차(데스크톱 사이드바 + 모바일 접이식)
    toc_links = "".join(f'<a href="#{sid}">{esc(label)}</a>' for (label, sid) in toc)
    mobile_toc = (f'<div class="tocm"><details><summary>Contents</summary>{toc_links}</details></div>')
    sidebar = (f'<aside class="aside"><div class="sticky"><div class="hd">Contents</div>'
               f'<nav class="toc">{toc_links}</nav>{_ad("sidebar", "sidebar")}</div></aside>')

    kicker = getattr(spec, "kicker", "") or _KICKER.get(spec.page_type, "Guide")
    metabar = (f'<div class="metabar"><span class="who"><span class="av sm">{esc(spec.author[:1].upper())}</span>'
               f'<span><strong>{esc(spec.author)}</strong> · reviews</span></span>'
               f'<span class="sep">•</span><span>Published {esc(spec.published_at)}</span>'
               f'<span class="sep">•</span><span>Updated <time>{esc(spec.updated_at or spec.published_at)}</time></span>'
               f'<span class="sep">•</span><span>{esc(str(getattr(spec, "reading_time", 6)))} min read</span></div>')
    draft_banner = '<div class="draft">DRY-RUN PREVIEW · 샘플 초안(미발행) · 자동 생성</div>' if draft else ""

    return f"""<!doctype html>
<html lang="en">
<head>
{_head(spec.title, spec.dek, getattr(spec, "canonical", ""), "article", _jsonld(spec))}
</head>
<body>
<a class="skip" href="#overview">Skip to content</a>
{draft_banner}
{_header()}
<div class="uv-grid">
<main><article id="overview">
{_crumb(spec.breadcrumb)}
<div class="kicker">{esc(kicker)}</div>
<h1>{esc(spec.title)}</h1>
<p class="dek">{esc(spec.dek)}</p>
{metabar}
{mobile_toc}
{_ad("below-hero", "leaderboard")}
{spec.intro_html}
{''.join(body)}
</article></main>
{sidebar}
</div>
{_footer()}
{_SCRIPTS}
</body>
</html>"""


def render_static_page(title: str, body_html: str, *, description: str = "", canonical: str = "") -> str:
    """필수/정적 페이지(Privacy·About·Contact·index) — 동일 셸, 광고 없음."""
    return f"""<!doctype html>
<html lang="en">
<head>
{_head(title, description or title, canonical, "website")}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{_header()}
<div class="container" style="padding-top:32px;padding-bottom:64px"><main id="main"><article>
<h1>{esc(title)}</h1>
{body_html}
</article></main></div>
{_footer()}
{_SCRIPTS}
</body>
</html>"""
