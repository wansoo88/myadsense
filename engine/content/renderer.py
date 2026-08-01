"""renderer.py — design.md 디자인 시스템 구현 (design/ 목업 완성도 반영).

생성기가 모든 페이지에 입히는 디자인. 자체완결(인라인 CSS/JS·시스템 폰트·외부 fetch 0),
CWV 안전(치수 예약·JS 최소), E-E-A-T(저자·날짜·출처·JSON-LD), 광고 슬롯 CLS 예약.
spec 은 속성만 읽으므로 generator 와 순환 import 없음.
"""
from __future__ import annotations
import html
import json
import os
import re

# AdSense 승인 전에는 광고 슬롯 비노출(빈 플레이스홀더가 심사에 불리). 승인 후 ADSENSE_ADS=1 로 켬.
ADS_ENABLED = os.environ.get("ADSENSE_ADS", "0") == "1"

# AdSense **사이트 소유권 확인**용 퍼블리셔 ID — config/sites.yaml `adsense.publisher_id` 를
# 빌드(site_builder.build)가 set_adsense_publisher_id() 로 주입한다.
# ⛔ 이건 소유권 확인 메타태그일 뿐 **광고 게재 코드가 아니다.** 광고 로더 스크립트는 승인 이후 별건이며
#    지금 넣으면 CWV 만 나빠지고 얻는 게 없다(ORDER 2026-08-01-46-ops §2-②).
# 빈 값이거나 형식이 틀리면 아무것도 출력하지 않는다 = 현재 산출물 바이트와 완전히 동일.
ADSENSE_PUBLISHER_ID = ""

# 형식: 'ca-pub-' + 숫자 16자리. 오타가 전 페이지에 박히면 소유권 확인이 **조용히** 실패하고
# 심사 1회전(며칠~4주)을 잃는다 → 애매하면 출력하지 않고 경고를 남기는 쪽(fail-closed)을 택한다.
_PUB_ID_RE = re.compile(r"ca-pub-\d{16}")
_PUB_META_RE = re.compile(r'[ \t]*<meta name="google-adsense-account"[^>]*>\n?')

# E-E-A-T: "누가 사이트/콘텐츠를 책임지는지 명확히"(SQRG) — publisher/author 엔티티가 /about/(편집 기준·방법론)로 연결.
# ⚠️ 이 상수들이 사이트 이름·주소의 **단일 출처**다. 화면 표기·og·JSON-LD·RSS 가 전부 여기서 파생된다
#    (ORDER 2026-08-01-47-ops ③: 주소가 11곳에 흩어져 있어 config 만 바꾸면 반쪽 이전이 되던 문제).
SITE_NAME = "Utilverse"                  # og:site_name · JSON-LD publisher.name — 발행 주체 이름(F10 Trust)
SITE_DOMAIN = "utilverse.info"           # 화면에 표기되는 주소(사실 표기)
SITE_URL = f"https://{SITE_DOMAIN}"
ABOUT_URL = "/about/"

# 구 주소 — `stack.utilverse.info` 로 **생성 시점에 구워진** 큐 문서의 절대 URL(canonical·og:url·og:image·
# feed·JSON-LD)을 빌드에서 현행 주소로 교정한다(refresh_chrome). 이게 없으면 기존 글의 head 가
# 통째로 구 주소로 남는다 — 실측 226건. 301 이 받아주더라도 canonical 이 구 주소면 정본이 흐려진다.
LEGACY_SITE_URLS = ("https://stack.utilverse.info",)

# 브랜드 마크(배지·파비콘·og 카드의 한 글자)와 헤더 주소 표기 — 전부 위 상수에서 파생.
# 마크를 되돌리려면 BRAND_MARK 한 줄만 고치면 된다(파비콘 글리프는 site_builder._inside_mark).
BRAND_MARK = SITE_NAME[0].upper()
_BRAND_HEAD, _, _rest = SITE_DOMAIN.partition(".")
_BRAND_TLD = "." + _rest

esc = html.escape


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_KICKER = {"comparison": "Comparison", "listicle": "Best of",
           "guide": "Guide", "alternatives": "Alternatives"}

# ── 글 유형별 섹션 라벨·배치 (2026-07-25-26-content) ──────────────────────────────────
# 진단: 발행 28편 전체가 동일 골격으로 렌더된다 —
#   At a glance → Head to head → Feature matrix → Pricing → Pros&cons → body → Verdict → FAQ.
# 섹션 종류·순서·헤딩 문자열·콜아웃 라벨이 100% 동일 → Google 이 '템플릿·thin'으로 보고 색인 보류(F12).
# 대책: page_type 에 따라 (1) 섹션 순서 (2) 헤딩/콜아웃 라벨 (3) 유형 고유 내비게이션을 실제로 달리한다.
#   비교글  = 결정 먼저(표·판정) → 딥다이브
#   가이드  = 절차 먼저(단계 본문) → 비용/트레이드오프는 뒤 → "Bottom line"
#   리스트글 = 픽 점프목록 + 픽 교차비교(표) 먼저 → 항목 본문 → "Our pick"
# 겉치레(색·여백)가 아니라 **정보 배치**의 차이다. 기존 스키마·바이라인·내부링크·CWV 는 보존.
_TYPE_LABELS = {
    "comparison": {
        "summary": "At a glance", "summary_lbl": "In short",
        "headtohead": "Head to head",
        "headtohead_sub": "Key differences side by side; the stronger option is tinted green.",
        "matrix": "Feature matrix", "pricing": "Pricing",
        "pricing_sub": "Confirm current pricing on each vendor's site.",
        "proscons": "Pros & cons", "verdict": "Verdict", "verdict_lbl": "Verdict",
    },
    "guide": {
        "summary": "The short version", "summary_lbl": "Before you start",
        "headtohead": "How the options compare",
        "headtohead_sub": "The managed option vs doing it yourself, side by side.",
        "matrix": "Feature comparison", "pricing": "Cost & hosting options",
        "pricing_sub": "Managed vs self-hosted — confirm current pricing on the vendor's site.",
        "proscons": "Is it worth it?", "verdict": "Bottom line", "verdict_lbl": "Bottom line",
    },
    "listicle": {
        "summary": "The short list", "summary_lbl": "Top picks",
        "picks": "The picks",
        "headtohead": "The picks compared",
        "headtohead_sub": "Key differences side by side; the stronger option is tinted green.",
        "matrix": "How the picks compare", "pricing": "Pricing at a glance",
        "pricing_sub": "Confirm current pricing on each vendor's site.",
        "proscons": "Strengths & trade-offs", "verdict": "Our pick", "verdict_lbl": "Our pick",
    },
}
_TYPE_LABELS["alternatives"] = _TYPE_LABELS["listicle"]


def _labels(page_type: str) -> dict:
    return _TYPE_LABELS.get(page_type, _TYPE_LABELS["comparison"])


# 리스트글의 '픽' 헤딩 감지 — "1. Name — …" / "7–9. …" / "Name — tagline" 형태.
# 메타 섹션("How we chose", "What to look for", "Honorable mentions" …)은 픽이 아니다.
_ITEM_HEAD_RE = re.compile(r"^\s*\d+\s*[.)]|^\s*\d+\s*[–-]\s*\d+|\s[—–]\s")
_META_HEAD_RE = re.compile(
    r"^\s*(how|what|why|can|which|when|where|honou?rable|other|self-hosting|frequently|the\s+picks)\b", re.I)
_ITEM_NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*[.)–-]\s*")


def _pick_headings(sections) -> list:
    """리스트글 본문 섹션에서 '픽' 헤딩만 뽑아 [(sid, heading)]. b_body 와 동일한 slugify 로 앵커 일치."""
    picks = []
    for i, s in enumerate(sections or []):
        h = (s.get("heading") or "").strip()
        if h and _ITEM_HEAD_RE.search(h) and not _META_HEAD_RE.match(h):
            picks.append((slugify(h) or f"s{i}", h))
    return picks


def _picklist(picks) -> str:
    """픽 점프 목록(정적 HTML·JS 없음·치수 안정). 각 링크는 해당 본문 섹션 앵커로 이동."""
    lis = ""
    for n, (sid, h) in enumerate(picks, 1):
        label = _ITEM_NUM_PREFIX_RE.sub("", h).strip() or h
        lis += (f'<li><a href="#{sid}"><span class="n">{n:02d}</span>'
                f'<span>{esc(label)}</span></a></li>')
    return f'<ol class="picklist">{lis}</ol>'

CSS = r"""
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
:root{
  --bg:#ffffff;--surface:#f7f8fa;--surface-2:#eef1f6;
  --ink:#1a1f2b;--ink-soft:#3d4654;--muted:#5b6573;
  --line:#e5e8ee;--line-strong:#d3d8e2;
  --accent:#2f6df6;--accent-ink:#1b4fd1;
  --good:#0d7d55;--warn:#96660f;--bad:#c2392f;
  --good-tint:#e7f5ee;--bad-tint:#fbeceb;
  --code-bg:#0f1320;--code-ink:#e7ebf2;--ad-bg:#f4f6fa;--ad-label:#66707e;
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
.searchpill:focus-within{border-color:var(--accent)}
.searchpill input{border:0;background:transparent;outline:none;color:var(--ink);font:13px var(--font-sans);width:100%;min-width:0}
.tbtn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:8px;border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);cursor:pointer}
.tbtn:hover{border-color:var(--line-strong);color:var(--ink)}
.tbtn .ic-sun{display:none}[data-theme=dark] .tbtn .ic-sun{display:inline-flex}[data-theme=dark] .tbtn .ic-moon{display:none}
@media(max-width:639px){.hide-sm{display:none!important}}  /* !important: nav.cats(0-1-1) 등 더 특이적인 display 선언을 확실히 이김 */
@media(max-width:639px){body{font-size:16px}h1{font-size:28px}.dek{font-size:17px}.hero{padding:56px 0 48px}}
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
article[id]{scroll-margin-top:80px}
section.blk{margin-top:44px;scroll-margin-top:80px}
h2.bar2{font-size:24px;letter-spacing:-.01em;font-weight:700;margin:0 0 16px;color:var(--ink);display:flex;align-items:center;gap:10px;scroll-margin-top:80px}
h2.bar2::before{content:"";width:4px;height:22px;background:var(--accent);border-radius:2px;display:inline-block;flex:none}
.sub{color:var(--muted);font-size:15px;margin:-10px 0 18px}
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
.note{display:block;vertical-align:baseline;font-size:12.5px;font-weight:400;line-height:1.5;color:var(--muted);margin:3px 0 0}
.footnote{font-size:13px;color:var(--muted);margin:10px 2px 0}
/* pricing */
.pricing{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.price-card{border:1px solid var(--line);border-radius:14px;background:var(--surface);padding:18px;display:flex;flex-direction:column;gap:4px}
.price-card .pn{font-size:16px;font-weight:700;color:var(--ink)}
.price-card .pp{font-size:20px;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.01em;line-height:1.35;margin-top:2px}
.price-card .pnote{font-size:13px;color:var(--muted);margin-top:2px}
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
.authorbox .nm a,.metabar .who a{color:inherit}.authorbox .nm a:hover,.metabar .who a:hover{color:var(--accent)}
.sources{margin-top:36px;scroll-margin-top:80px}.sources h2{font-size:17px;font-weight:700;color:var(--ink);margin:0 0 10px}
.sources ol{margin:0;padding-left:20px;color:var(--muted);font-size:14px;line-height:1.8}
.related{margin-top:36px;border-top:1px solid var(--line);padding-top:24px}
.related .hd{font-size:13px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
.related .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.related .card{display:block;border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.related .card:hover{border-color:var(--accent);text-decoration:none}
.related .cat{font-size:12px;color:var(--accent);font-weight:600;margin-bottom:4px}
.related .ttl{color:var(--ink);font-weight:600;font-size:15px;line-height:1.4}
/* pick list (listicle jump nav — 유형 고유 내비게이션, 정적·치수안정) */
ol.picklist{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px}
ol.picklist li{margin:0}
ol.picklist a{display:flex;align-items:baseline;gap:9px;border:1px solid var(--line);border-radius:10px;padding:10px 14px;color:var(--ink-soft);font-size:15px;font-weight:600;line-height:1.4}
ol.picklist a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
ol.picklist .n{font-family:var(--font-mono);font-size:12px;font-weight:700;color:var(--accent);flex:none}
/* search */
.searchpage .sbar{display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line-strong);border-radius:12px;padding:12px 16px;max-width:560px;margin:8px 0 8px}
.searchpage .sbar:focus-within{border-color:var(--accent)}
.searchpage .sbar input{flex:1;border:0;background:transparent;outline:none;color:var(--ink);font:16px var(--font-sans)}
.searchpage .cnt{font-size:13px;color:var(--muted);margin:6px 0 18px}
.sres{display:block;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}
.sres:hover{border-color:var(--accent);text-decoration:none}
.sres .scat{display:block;font-size:12px;color:var(--accent);font-weight:600}
.sres .stt{display:block;font-weight:700;color:var(--ink);font-size:16px;margin-top:3px}
.sres .sds{display:block;color:var(--muted);font-size:14px;margin-top:4px}
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
/* home */
.hero{padding:88px 0 76px;text-align:center}
.hero .pill{display:inline-flex;align-items:center;gap:8px;font-family:var(--font-mono);font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);border:1px solid var(--line);border-radius:999px;padding:6px 14px;background:var(--surface)}
.hero .pill .dot{width:7px;height:7px;border-radius:50%;background:var(--good);display:inline-block}
.hero h1{font-size:clamp(40px,6.4vw,68px);line-height:1.04;letter-spacing:-.03em;margin:24px auto 0;font-weight:800;color:var(--ink);max-width:18ch;text-wrap:balance}
.hero h1 .ac{color:var(--accent)}
.hero .dek{font-size:clamp(17px,2.2vw,20px);line-height:1.55;color:var(--ink-soft);margin:22px auto 0;max-width:58ch;text-wrap:pretty}
.searchbox{margin:34px auto 0;max-width:560px;display:flex;gap:10px}
.searchbox .field{flex:1;display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line-strong);border-radius:12px;padding:14px 16px}
.searchbox .field:focus-within{border-color:var(--accent)}
.searchbox input{flex:1;border:0;background:transparent;outline:none;color:var(--ink);font-size:16px;font-family:var(--font-sans)}
.searchbox button{flex:none;border:0;background:var(--accent);color:#fff;font-weight:700;font-size:16px;border-radius:12px;padding:0 22px;cursor:pointer}
.searchbox button:hover{background:var(--accent-ink)}
.pills{margin:18px auto 0;display:flex;flex-wrap:wrap;gap:8px;justify-content:center;font-size:13px}
.pills .lab{color:var(--muted);font-family:var(--font-mono);font-size:12px;align-self:center}
.pills a{border:1px solid var(--line);border-radius:999px;padding:5px 12px;color:var(--ink-soft);background:var(--bg)}
.pills a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
.trustbar{border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--surface)}
.trustbar .in{max-width:1120px;margin:0 auto;display:flex;flex-wrap:wrap;gap:14px 48px;padding:26px 24px;justify-content:center}
.trustbar .item{display:flex;align-items:center;gap:10px;color:var(--ink-soft);font-size:14px}
.trustbar strong{color:var(--ink);font-weight:700}
.home-sec{padding:64px 0}.home-sec.alt{background:var(--surface);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.sechead{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:28px}
.sechead h2{font-size:clamp(26px,3.4vw,34px);font-weight:800;letter-spacing:-.02em;margin:0;color:var(--ink);display:flex;align-items:baseline;gap:12px}
.sechead h2 .num{font-family:var(--font-mono);font-size:14px;font-weight:600;color:var(--accent)}
.seemore{font-size:14px;color:var(--accent);font-weight:600;white-space:nowrap}
.feat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.feat-card{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--bg)}
.feat-card:hover{border-color:var(--accent);text-decoration:none}
.feat-thumb{height:140px;display:flex;align-items:center;justify-content:center;gap:14px;font-family:var(--font-mono);font-weight:700;color:var(--ink-soft);background:var(--surface-2);padding:0 16px;text-align:center}
.feat-thumb.grad{background:linear-gradient(135deg,var(--accent),var(--accent-ink));color:#fff}
.feat-thumb .vs{opacity:.65;font-size:13px}
.feat-card .bd{padding:18px 20px 22px;flex:1;display:flex;flex-direction:column}
.feat-card .ey{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;color:var(--accent);text-transform:uppercase}
.feat-card .tt{font-size:18px;font-weight:700;color:var(--ink);margin:8px 0 6px;line-height:1.35}
.feat-card .ds{font-size:14px;color:var(--muted);line-height:1.5}
.feat-card .mt{margin-top:14px;font-size:13px;color:var(--muted);font-family:var(--font-mono)}
.cat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.cat-card{display:flex;align-items:center;gap:16px;border:1px solid var(--line);border-radius:14px;padding:20px;background:var(--bg)}
.cat-card:hover{border-color:var(--accent);background:var(--surface);text-decoration:none}
.cat-ic{flex:none;display:inline-flex;width:44px;height:44px;border-radius:11px;background:var(--surface-2);color:var(--accent);align-items:center;justify-content:center}
.cat-card .nm{display:block;font-weight:700;color:var(--ink);font-size:16px}
.cat-card .tg{display:block;font-size:13px;color:var(--muted);margin-top:2px;font-family:var(--font-mono)}
.latest a.row{display:flex;align-items:center;gap:18px;padding:18px 4px;border-top:1px solid var(--line)}
.latest a.row:hover{background:var(--surface-2);text-decoration:none}
.latest .num{font-family:var(--font-mono);font-size:13px;color:var(--muted);flex:none;width:46px}
.latest .tt{display:block;font-weight:700;color:var(--ink);font-size:17px;line-height:1.4}
.latest .mt{display:block;font-size:13.5px;color:var(--muted);margin-top:3px}
.latest .ar{flex:none;color:var(--muted)}
.ctasec{padding:80px 0}
.nl-card{border:1px solid var(--line);border-radius:20px;background:var(--surface);padding:clamp(28px,5vw,52px);text-align:center}
.nl-card .ey{font-family:var(--font-mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.nl-card h2{font-size:clamp(24px,3.2vw,32px);font-weight:800;letter-spacing:-.02em;margin:12px auto 0;color:var(--ink);max-width:22ch;text-wrap:balance}
.nl-card p{color:var(--ink-soft);margin:14px auto 0;max-width:44ch}
.nl-cta{display:inline-block;margin-top:26px;background:var(--accent);color:#fff;border-radius:11px;padding:13px 26px;font-size:15px;font-weight:700}
.nl-cta:hover{background:var(--accent-ink);text-decoration:none}
@media(max-width:860px){.feat-grid{grid-template-columns:1fr}.cat-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:520px){.cat-grid{grid-template-columns:1fr}}
"""

THEME_INIT = ("<script>(function(){try{var t=localStorage.getItem('uv-theme')||"
              "(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"
              "document.documentElement.setAttribute('data-theme',t)}catch(e){}})()</script>")

_SCRIPTS = ("<script>"
            "var tb=document.querySelector('.tbtn');if(tb)tb.addEventListener('click',function(){"
            "var d=document.documentElement,n=d.getAttribute('data-theme')==='dark'?'light':'dark';"
            "d.setAttribute('data-theme',n);try{localStorage.setItem('uv-theme',n)}catch(e){}"
            "var c=n==='dark'?'#0f1115':'#ffffff';"
            "[].forEach.call(document.querySelectorAll('meta[name=theme-color]'),function(m){m.setAttribute('content',c)})});"
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
            " fill='white' text-anchor='middle' font-family='monospace' font-weight='700'%3E"
            f"{BRAND_MARK}%3C/text%3E%3C/svg%3E")


def valid_publisher_id(v) -> str:
    """유효한 퍼블리셔 ID면 정규화해 돌려주고, 아니면 ""(= 아무것도 출력하지 않는다)."""
    v = str(v or "").strip()
    return v if _PUB_ID_RE.fullmatch(v) else ""


def set_adsense_publisher_id(v) -> str:
    """빌드가 config 값을 주입한다 — 검증 통과분만 저장한다. 반환값 = 실제로 적용된 값(""=무동작)."""
    global ADSENSE_PUBLISHER_ID
    ADSENSE_PUBLISHER_ID = valid_publisher_id(v)
    return ADSENSE_PUBLISHER_ID


def _adsense_meta() -> str:
    """소유권 확인 메타태그 한 줄(끝 개행 포함). 값이 없으면 "" → head 바이트가 변하지 않는다."""
    return (f'<meta name="google-adsense-account" content="{ADSENSE_PUBLISHER_ID}">\n'
            if ADSENSE_PUBLISHER_ID else "")


def _head(title, description, canonical="", og_type="article", extra=""):
    return f"""<meta charset="utf-8">
{_adsense_meta()}<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''}
<link rel="icon" href="{_FAVICON}">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1115" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
{f'<meta property="og:url" content="{esc(canonical)}">' if canonical else ''}
<meta property="og:image" content="{SITE_URL}/og.svg">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE_URL}/og.svg">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME} — latest" href="{SITE_URL}/feed.xml">
{THEME_INIT}
<style>{CSS}</style>
{extra}"""


def _header():
    return ('<header class="site"><div class="bar">'
            f'<a class="brand" href="/"><span class="badge">{BRAND_MARK}</span>'
            f'<span>{_BRAND_HEAD}<span class="tld">{_BRAND_TLD}</span></span></a>'
            '<nav class="cats hide-sm"><a href="/ai-coding/">AI Coding</a><a href="/hosting/">Hosting</a>'
            '<a href="/dev-tools/">Dev Tools</a><a href="/ai-tools/">AI Tools</a></nav>'
            '<div class="right">'
            '<form class="searchpill hide-sm" action="/search/" method="get" role="search">'
            + _ic('<circle cx="11" cy="11" r="7"></circle><path d="m20 20-3-3"></path>', 15, "var(--muted)")
            + '<input name="q" placeholder="Search tools…" aria-label="Search tools">'
            '</form>'
            f'<button class="tbtn" aria-label="Toggle theme">{_SUN}{_MOON}</button></div>'
            '</div></header>')


def _footer():
    return ('<footer class="site"><div class="inner">'
            f'<span class="fb">{SITE_DOMAIN}</span>'
            '<nav><a href="/about/">About</a><a href="/contact/">Contact</a>'
            '<a class="priv" href="/privacy/">Privacy Policy</a>'
            '<a href="/ai-coding/">AI Coding</a><a href="/hosting/">Hosting</a>'
            '<a href="/dev-tools/">Dev Tools</a><a href="/ai-tools/">AI Tools</a></nav>'
            f'<span class="cp">© 2026 {SITE_DOMAIN}</span>'
            '</div></footer>')


def _ad(name, cls):
    if not ADS_ENABLED:
        return ""                       # 승인 전: 광고 영역 비노출. 승인 후 ADSENSE_ADS=1 → 슬롯 복원
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


def split_price(price: str) -> tuple[str, str]:
    """서술형 가격("Paid (…) — confirm current price")의 대시 뒤 단서를 노트로 분리.
    대시가 괄호 안이면(잘리면 괄호가 깨짐) 분리하지 않는다."""
    main, sep, note = price.partition("—")
    if sep and main.count("(") == main.count(")") and note.strip():
        return main.strip(), note.strip()
    return price.strip(), ""


def _pricing(plans):
    cards = ""
    for p in plans:
        feats = "".join(f"<li>{esc(f)}</li>" for f in p.get("features", []))
        cta = p.get("cta")
        cta_html = f'<a class="cta" href="{esc(cta["url"])}" rel="nofollow sponsored">{esc(cta["label"])}</a>' if cta else ""
        price, note = split_price(p["price"])
        note_html = f'<div class="pnote">{esc(note)}</div>' if note else ""
        cards += (f'<div class="price-card"><div class="pn">{esc(p["name"])}</div>'
                  f'<div class="pp">{esc(price)}</div>{note_html}<ul>{feats}</ul>{cta_html}</div>')
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


def _breadcrumb_jsonld_dict(items):
    els = [{"@type": "ListItem", "position": i + 1, "name": n,
            **({"item": u} if u else {})} for i, (n, u) in enumerate(items)]
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": els}


def _jsonld(spec):
    # author = 편집 주체(팀 별칭 — SQRG 상 alias 허용), publisher = 사이트 운영 주체.
    # 둘 다 /about/(편집 기준·방법론)로 연결해 "누가 책임지고 누가 작성했는지"를 기계가독으로 명시(E-E-A-T).
    org = {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL}
    blocks = [{
        "@context": "https://schema.org", "@type": "Article",
        "headline": spec.title, "description": spec.dek,
        "author": {"@type": "Organization", "name": spec.author, "url": SITE_URL + ABOUT_URL},
        "publisher": org,
        "datePublished": spec.published_at, "dateModified": spec.updated_at or spec.published_at,
        "mainEntityOfPage": spec.canonical or "",
    }]
    if spec.breadcrumb:
        blocks.append(_breadcrumb_jsonld_dict(spec.breadcrumb))
    faq = getattr(spec, "faq", None)
    if faq:                                     # FAQPage (F14) — 데이터 있는 것만, 유효 스키마
        blocks.append({"@context": "https://schema.org", "@type": "FAQPage",
                       "mainEntity": [{"@type": "Question", "name": f["q"],
                                       "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                                      for f in faq if f.get("q") and f.get("a")]})
    return "".join('<script type="application/ld+json">' + json.dumps(b, ensure_ascii=False) + "</script>"
                   for b in blocks)


def _related_cards(items) -> str:
    """Related reading 섹션 HTML. items: [{url, title, cat}]. 빈 목록이면 빈 문자열."""
    if not items:
        return ""
    cards = "".join(f'<a class="card" href="{esc(r["url"])}"><div class="cat">{esc(r.get("cat") or "Related")}</div>'
                    f'<div class="ttl">{esc(r["title"])}</div></a>' for r in items)
    return ('<section class="related"><div class="hd">Related reading</div>'
            f'<div class="cards">{cards}</div></section>')


def render(spec, draft: bool = False) -> str:
    toc, body = [], []

    def add(label, sid):
        toc.append((label, sid))

    add("Overview", "overview")

    # page_type 별 섹션 라벨·순서 (진단 2026-07-25-26: 28편 골격 100% 동일 → 색인 보류).
    # ⚠️ 아래 각 블록 빌더는 스펙 필드가 없으면 no-op → 어떤 순서를 골라도 콘텐츠 유실 없음.
    pt = (getattr(spec, "page_type", "") or "comparison").lower()
    if pt not in _TYPE_LABELS:
        pt = "comparison"
    L = _labels(pt)

    def b_summary():                                # 상단 한 줄 결론(콜아웃) — 라벨만 유형별
        if getattr(spec, "tldr_html", None):
            body.append(_section(L["summary"], "summary",
                                 f'<div class="callout"><div class="lbl">{esc(L["summary_lbl"])}</div>'
                                 f'{spec.tldr_html}</div>'))
            add(L["summary"], "summary")

    def b_picks():                                  # 리스트글 전용: 픽 점프 목록(유형 고유 내비게이션)
        if pt not in ("listicle", "alternatives"):
            return
        picks = _pick_headings(spec.sections)
        if len(picks) < 3:                          # 2-way 'best of' 등은 목록 만들지 않음(형해화 방지)
            return
        body.append(_section(L.get("picks", "The picks"), "picks", _picklist(picks),
                             sub="Jump straight to any pick below."))
        add(L.get("picks", "The picks"), "picks")

    def b_headtohead():
        if getattr(spec, "comparison", None):
            body.append(_section(L["headtohead"], "comparison", _comparison(spec.comparison),
                                 sub=L["headtohead_sub"]))
            add(L["headtohead"], "comparison")

    def b_matrix():
        if getattr(spec, "feature_matrix", None):
            fm = _matrix(spec.feature_matrix)
            note = '<p class="footnote">✓ full · △ partial/paid · ✗ not supported</p>'
            body.append(_section(L["matrix"], "features", fm + note))
            add(L["matrix"], "features")

    def b_pricing():
        if getattr(spec, "pricing", None):
            body.append(_section(L["pricing"], "pricing", _pricing(spec.pricing), sub=L["pricing_sub"]))
            add(L["pricing"], "pricing")

    def b_proscons():
        if getattr(spec, "pros_cons", None):
            body.append(_section(L["proscons"], "proscons", _proscons(spec.pros_cons)))
            add(L["proscons"], "proscons")

    def b_ad():
        body.append(_ad("in-content-1", "in-content"))

    def b_body():                                   # 본문(딥다이브/단계/항목) 섹션
        for i, s in enumerate(spec.sections):
            sid = slugify(s["heading"]) or f"s{i}"
            body.append(_section(s["heading"], sid, s["html"]))
            add(s["heading"], sid)

    def b_verdict():
        if getattr(spec, "verdict_html", None):
            body.append('<section class="blk" id="verdict"><div class="callout good">'
                        f'<div class="lbl">{esc(L["verdict_lbl"])}</div>{spec.verdict_html}</div></section>')
            add(L["verdict"], "verdict")

    def b_faq():                                    # People-Also-Ask 대응 + FAQPage 스키마(_jsonld)
        if getattr(spec, "faq", None):
            qa = "".join(f'<h3>{esc(f["q"])}</h3><p>{esc(f["a"])}</p>'
                         for f in spec.faq if f.get("q") and f.get("a"))
            if qa:
                body.append(_section("FAQ", "faq", qa))
                add("FAQ", "faq")

    # 유형별 정보 흐름. 모든 필드 빌더가 각 순서에 포함되므로(누락 시 no-op) 콘텐츠 유실은 없다.
    _ORDERS = {
        # 비교: 결정(표·판정) 먼저 → 딥다이브
        "comparison": [b_summary, b_headtohead, b_matrix, b_pricing, b_proscons,
                       b_ad, b_body, b_verdict, b_faq],
        # 가이드: 절차(단계 본문) 먼저 → 비용·트레이드오프는 뒤 → "Bottom line"
        "guide": [b_summary, b_ad, b_headtohead, b_matrix, b_body,
                  b_pricing, b_proscons, b_verdict, b_faq],
        # 리스트: 픽 점프목록 + 픽 교차비교(표) 먼저 → 항목 본문 → 강점/약점 → "Our pick"
        "listicle": [b_summary, b_picks, b_headtohead, b_matrix, b_pricing,
                     b_ad, b_body, b_proscons, b_verdict, b_faq],
    }
    _ORDERS["alternatives"] = _ORDERS["listicle"]
    for builder in _ORDERS[pt]:
        builder()

    # 저자 박스
    body.append(f'<div class="authorbox"><span class="av lg">{esc(spec.author[:1].upper())}</span><div>'
                f'<div class="nm"><a href="{ABOUT_URL}">{esc(spec.author)}</a></div>'
                f'<div class="bio">{esc(getattr(spec, "author_bio", "") or "Independent software comparisons from official docs and public data.")} '
                f'<a href="{ABOUT_URL}">How we compare &amp; who we are &rarr;</a></div>'
                f'<div class="upd">Updated {esc(spec.updated_at or spec.published_at)}</div></div></div>')

    if spec.sources:
        items = "".join(f'<li><a href="{esc(s["url"])}" rel="noopener" target="_blank">{esc(s["title"])}</a></li>'
                        for s in spec.sources)
        body.append(f'<section class="sources" id="sources"><h2>Sources</h2><ol>{items}</ol></section>')
        add("Sources", "sources")

    rel_html = _related_cards(getattr(spec, "related", None) or [])
    if rel_html:                                    # 생성 시점 값(빌드가 실제 페이지로 재작성 — refresh_internal_links)
        body.append(rel_html)

    # 목차(데스크톱 사이드바 + 모바일 접이식)
    toc_links = "".join(f'<a href="#{sid}">{esc(label)}</a>' for (label, sid) in toc)
    mobile_toc = (f'<div class="tocm"><details><summary>Contents</summary>{toc_links}</details></div>')
    sidebar = (f'<aside class="aside"><div class="sticky"><div class="hd">Contents</div>'
               f'<nav class="toc">{toc_links}</nav>{_ad("sidebar", "sidebar")}</div></aside>')

    kicker = getattr(spec, "kicker", "") or _KICKER.get(spec.page_type, "Guide")
    metabar = (f'<div class="metabar"><span class="who"><span class="av sm">{esc(spec.author[:1].upper())}</span>'
               f'<span><a href="{ABOUT_URL}"><strong>{esc(spec.author)}</strong></a> · reviews</span></span>'
               f'<span class="sep">•</span><span>Published {esc(spec.published_at)}</span>'
               f'<span class="sep">•</span><span>Updated <time>{esc(spec.updated_at or spec.published_at)}</time></span>'
               f'<span class="sep">•</span><span>{esc(str(getattr(spec, "reading_time", 6)))} min read</span></div>')
    draft_banner = '<div class="draft">DRY-RUN PREVIEW · 샘플 초안(미발행) · 자동 생성</div>' if draft else ""

    extra = _jsonld(spec)
    if getattr(spec, "cluster", None):
        extra += f'<meta name="cluster" content="{esc(spec.cluster)}">'

    return f"""<!doctype html>
<html lang="en">
<head>
{_head(spec.title, spec.dek, getattr(spec, "canonical", ""), "article", extra)}
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


def refresh_chrome(doc: str) -> str:
    """이미 렌더된 문서(발행 큐)의 공통 chrome을 현재 디자인으로 갱신.

    큐 페이지는 생성 시점의 CSS·헤더·푸터·스크립트가 구워져 있어, 렌더러의 디자인
    수정이 신규 글에만 반영되고 기존 글과 갈라진다. 빌드 시 이 함수로 동기화한다.
    본문(article)은 건드리지 않는다 — 게이트/검수를 통과한 콘텐츠 그대로.
    """
    doc = re.sub(r"<style>.*?</style>", lambda m: f"<style>{CSS}</style>", doc, count=1, flags=re.S)
    doc = re.sub(r'<header class="site">.*?</header>', lambda m: _header(), doc, count=1, flags=re.S)
    doc = re.sub(r'<footer class="site">.*?</footer>', lambda m: _footer(), doc, count=1, flags=re.S)
    doc = re.sub(r"<script>var tb=.*?</script>", lambda m: _SCRIPTS, doc, count=1, flags=re.S)
    # og:image/twitter:image 소급(구 문서 head 에 없으면 og:type 뒤에 삽입) + 구 twitter:card 업그레이드. 멱등.
    if "og:image" not in doc:
        og = (f'<meta property="og:image" content="{SITE_URL}/og.svg">'
              f'<meta name="twitter:image" content="{SITE_URL}/og.svg">')
        doc = re.sub(r'(<meta property="og:type"[^>]*>)', lambda m: m.group(1) + og, doc, count=1)
    doc = doc.replace('<meta name="twitter:card" content="summary">',
                      '<meta name="twitter:card" content="summary_large_image">')
    # AdSense 소유권 확인 메타 소급 — 큐 문서는 **생성 시점** head 가 구워져 있어 _head() 변경이 닿지 않는다
    # (기존 발행분이 전부 빠지면 소유권 확인 자체가 성립하지 않는다). 기존 태그를 걷어낸 뒤 현재 값만
    # 다시 넣는다: 멱등이고, 값이 바뀌거나 비워지면 그것도 그대로 반영된다.
    doc = _PUB_META_RE.sub("", doc, count=1)
    meta = _adsense_meta()
    if meta:
        doc = doc.replace('<meta charset="utf-8">\n', '<meta charset="utf-8">\n' + meta, 1)
    # 구 주소 교정 — 큐 문서는 **생성 시점** 절대 URL(canonical·og:url·og:image·feed·JSON-LD)이 구워져 있다.
    # 도메인 이전(ORDER 47) 후에도 이걸 두면 head 가 통째로 구 주소로 남는다(실측 226건).
    # 301 이 받아주더라도 canonical 이 구 주소를 가리키면 정본이 흐려진다 → 빌드에서 현행 주소로 확정한다.
    for old in LEGACY_SITE_URLS:
        if old != SITE_URL:
            doc = doc.replace(old, SITE_URL)
    return doc


def _refresh_article_jsonld(doc: str) -> str:
    """빌드 시 Article JSON-LD 보강 — author 를 Organization+/about/ URL 로, publisher(Organization) 추가.
    기존 큐 문서(생성 시점 베이크)에도 소급. JSON 파싱으로 안전하게(파싱 실패 시 원문 유지)·멱등."""
    def repl(m):
        raw = m.group(1)
        try:
            data = json.loads(raw)
        except Exception:
            return m.group(0)
        if not isinstance(data, dict) or data.get("@type") != "Article":
            return m.group(0)
        prev = data.get("author")
        name = prev.get("name") if isinstance(prev, dict) else (prev if isinstance(prev, str) else SITE_NAME)
        data["author"] = {"@type": "Organization", "name": name or SITE_NAME, "url": SITE_URL + ABOUT_URL}
        data["publisher"] = {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL}
        return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"
    return re.sub(r'<script type="application/ld\+json">(.*?)</script>', repl, doc, flags=re.S)


def refresh_internal_links(doc: str, *, crumb_items=None, related_items=None) -> str:
    """빌드 시 내부 링크·E-E-A-T 메타데이터 교정 — 생성 시점 베이크된 큐 문서에 소급 적용(멱등).

    - 바이라인(메타바·저자박스) → /about/(누가 작성·책임지는지) 링크. E-E-A-T "책임 주체 명시".
    - Article JSON-LD author(Organization)/publisher 보강(_refresh_article_jsonld).
    - crumb_items: [(name, url)] → 가시 브레드크럼 + BreadcrumbList JSON-LD 동시 갱신
      (기존 하드코딩 'Home › Compare(/compare/ = 404)' → 'Home › 실제 카테고리 허브 › 글').
    - related_items: [{url, title, cat}] → Related reading 섹션을 실제 클러스터 이웃 글로 교체.
    본문(article) 콘텐츠는 건드리지 않는다 — 게이트/검수 통과분 그대로.
    """
    # 바이라인 → /about/ 링크(이미 링크된 신규 문서엔 매칭 안 됨 → 멱등)
    doc = re.sub(r'<span><strong>([^<]+)</strong> · reviews</span>',
                 lambda m: f'<span><a href="{ABOUT_URL}"><strong>{m.group(1)}</strong></a> · reviews</span>',
                 doc, count=1)
    doc = re.sub(r'<div class="nm">([^<]+)</div>',
                 lambda m: f'<div class="nm"><a href="{ABOUT_URL}">{m.group(1)}</a></div>', doc, count=1)
    doc = _refresh_article_jsonld(doc)
    if crumb_items:
        crumb_html = _crumb(crumb_items)
        doc = re.sub(r'<nav class="crumb"[^>]*>.*?</nav>', lambda m: crumb_html, doc, count=1, flags=re.S)
        new_bc = ('<script type="application/ld+json">'
                  + json.dumps(_breadcrumb_jsonld_dict(crumb_items), ensure_ascii=False) + "</script>")
        doc = re.sub(r'<script type="application/ld\+json">.*?</script>',
                     lambda m: new_bc if '"BreadcrumbList"' in m.group(0) else m.group(0),
                     doc, flags=re.S)
    if related_items is not None:
        rel_html = _related_cards(related_items)
        if re.search(r'<section class="related".*?</section>', doc, flags=re.S):
            doc = re.sub(r'<section class="related".*?</section>', lambda m: rel_html, doc, count=1, flags=re.S)
        elif rel_html:
            doc = doc.replace("</article>", rel_html + "</article>", 1)
    return doc


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


_SEARCH_JS = ("<script>(function(){"
              "var q=(new URLSearchParams(location.search).get('q'))||'';"
              "var box=document.getElementById('sq'),out=document.getElementById('sr'),cnt=document.getElementById('scnt');"
              "if(box)box.value=q;"
              "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,function(c){"
              "return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]})}"
              "fetch('/search-index.json',{cache:'no-store'}).then(function(r){return r.json()}).then(function(idx){"
              "function run(t){t=(t||'').trim().toLowerCase();"
              "var res=!t?idx:idx.filter(function(x){return (x.title+' '+(x.desc||'')+' '+(x.cat||'')).toLowerCase().indexOf(t)>=0});"
              "if(cnt)cnt.textContent=t?(res.length+' result'+(res.length===1?'':'s')+' for \\u201c'+t+'\\u201d'):(idx.length+' comparisons & guides');"
              "out.innerHTML=res.length?res.map(function(x){return '<a class=\"sres\" href=\"'+esc(x.url)+'\">"
              "<span class=\"scat\">'+esc(x.cat||'')+'</span><span class=\"stt\">'+esc(x.title)+'</span>'"
              "+(x.desc?'<span class=\"sds\">'+esc(x.desc)+'</span>':'')+'</a>'}).join(''):"
              "'<p class=\"cnt\">No matches. Try a tool name like Cursor or Notion.</p>';}"
              "run(q);if(box)box.addEventListener('input',function(){run(box.value);"
              "var u=new URL(location.href);box.value?u.searchParams.set('q',box.value):u.searchParams.delete('q');"
              "history.replaceState(0,'',u)});"
              "}).catch(function(){out.innerHTML='<p class=\"cnt\">Search is unavailable right now.</p>'});"
              "})()</script>")


def render_search_page(*, canonical: str = "") -> str:
    """온사이트 검색 페이지 — 프리빌트 search-index.json 을 인라인 JS로 필터(외부 오프로드 제거).
    검색 결과 페이지는 색인 대상 아님 → noindex,follow."""
    body = ('<div class="searchpage"><h1>Search</h1>'
            '<div class="sbar">'
            + _ic('<circle cx="11" cy="11" r="7"></circle><path d="m20 20-3-3"></path>', 19, "var(--muted)")
            + '<input id="sq" name="q" placeholder="Search tools, comparisons, guides…" aria-label="Search" autofocus></div>'
            '<div class="cnt" id="scnt"></div><div id="sr"></div></div>')
    return f"""<!doctype html>
<html lang="en">
<head>
{_head("Search — " + SITE_NAME, "Search independent tool comparisons and guides.", canonical, "website", '<meta name="robots" content="noindex, follow">')}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{_header()}
<div class="container" style="padding-top:32px;padding-bottom:64px"><main id="main">
{body}
</main></div>
{_footer()}
{_SCRIPTS}
{_SEARCH_JS}
</body>
</html>"""


# 홈 카테고리 (정직성: 가짜 도구 수 대신 태그라인)
_HOME_CATS = [
    ("AI Coding", "/ai-coding/", "Editors & assistants",
     '<path d="m8 6-6 6 6 6M16 6l6 6-6 6"></path>'),
    ("Hosting & Self-host", "/hosting/", "VPS, cloud, self-hosting",
     '<rect x="2" y="3" width="20" height="7" rx="2"></rect><rect x="2" y="14" width="20" height="7" rx="2"></rect><path d="M6 6.5h.01M6 17.5h.01"></path>'),
    ("Dev Tools", "/dev-tools/", "SaaS & developer tools",
     '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>'),
    ("AI Tools", "/ai-tools/", "Productivity & creative AI",
     '<path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.4L12 3z"></path>'),
    ("VPN & Security", "/vpn-security/", "Privacy & security",
     '<path d="M12 2 4 6v6c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V6z"></path>'),
]
_TRUST = [
    ('<path d="M20 6 9 17l-5-5"></path>', "Fact-checked", " against official docs"),
    ('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6M9 13h6M9 17h6"></path>', "Sources cited", " on every claim"),
    ('<path d="M3 12a9 9 0 1 0 9-9 9.7 9.7 0 0 0-6.7 2.7L3 8"></path><path d="M3 3v5h5"></path>', "Regularly updated", " pricing & features"),
]


def _vs_pair(title: str):
    base = title.split(":")[0]
    parts = re.split(r"\s+vs\.?\s+", base, flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else None


def _ic(path, w=18, stroke="currentColor"):
    return (f'<svg width="{w}" height="{w}" viewBox="0 0 24 24" fill="none" stroke="{stroke}" '
            f'stroke-width="2">{path}</svg>')


def _feat_card(p, grad=False):
    """글 카드 (홈 '이번 주' + 카테고리 허브 공용). 라벨은 페이지 kicker(Comparison/Guide/Best of…)."""
    pair = _vs_pair(p["title"])
    thumb = (f'<span>{esc(pair[0])}</span><span class="vs">vs</span><span>{esc(pair[1])}</span>'
             if pair else f'<span>{esc(p["title"].split(":")[0])}</span>')
    meta = " · ".join([x for x in [p.get("read"),
                                   (f'updated {p["updated"]}' if p.get("updated") else None)] if x])
    return (f'<a class="feat-card" href="{esc(p["url"])}">'
            f'<div class="feat-thumb{" grad" if grad else ""}">{thumb}</div>'
            f'<div class="bd"><div class="ey">{esc(p.get("kicker") or "Comparison")}</div>'
            f'<div class="tt">{esc(p["title"].split(":")[0])}</div>'
            f'<div class="ds">{esc(p.get("desc") or "A comparison of pricing, features, and fit.")}</div>'
            f'<div class="mt">{esc(meta)}</div></div></a>')


def render_home(pages, *, domain: str = SITE_DOMAIN, canonical: str = "", active_cat_urls=None) -> str:
    pages = list(pages)
    featured = pages[:3]
    base = f"https://{domain}"

    # 히어로 인기 핀 (상위 비교글)
    pills = "".join(f'<a href="{esc(p["url"])}">{esc((_vs_pair(p["title"]) and " vs ".join(_vs_pair(p["title"]))) or p["title"][:28])}</a>'
                    for p in featured) or '<span class="lab">coming soon</span>'

    # 이번 주 비교 카드 (첫 카드만 그라디언트 썸네일)
    cards = [_feat_card(p, grad=(i == 0)) for i, p in enumerate(featured)]
    featured_html = (f'<section class="home-sec" id="featured"><div class="container">'
                     f'<div class="sechead"><h2><span class="num">01</span>This week\'s comparisons</h2></div>'
                     f'<div class="feat-grid">{"".join(cards)}</div></div></section>') if cards else ""

    # 카테고리 (활성 목록이 주어지면 그것만 — 빈 허브 링크 방지)
    cats = _HOME_CATS if active_cat_urls is None else [c for c in _HOME_CATS if c[1] in set(active_cat_urls)]
    cat_cards = "".join(
        f'<a class="cat-card" href="{esc(url)}"><span class="cat-ic">{_ic(path, 22)}</span>'
        f'<span><span class="nm">{esc(name)}</span><span class="tg">{esc(tag)}</span></span></a>'
        for (name, url, tag, path) in cats)
    categories_html = (f'<section class="home-sec" id="categories"><div class="container">'
                       f'<div class="sechead"><h2><span class="num">02</span>Categories</h2></div>'
                       f'<div class="cat-grid">{cat_cards}</div></div></section>')

    # 최신 (전체)
    rows = "".join(
        f'<a class="row" href="{esc(p["url"])}"><span class="num">{i + 1:02d}</span>'
        f'<span style="flex:1;min-width:0"><span class="tt">{esc(p["title"].split(":")[0])}</span>'
        f'<span class="mt">{esc(p.get("kicker") or "Comparison")}{(" · " + p["read"]) if p.get("read") else ""}</span></span>'
        f'<span class="ar hide-sm">→</span></a>' for i, p in enumerate(pages)) or \
        '<p style="color:var(--muted);padding:18px 4px">No articles published yet.</p>'
    latest_html = (f'<section class="home-sec alt latest" id="latest"><div class="container">'
                   f'<div class="sechead"><h2><span class="num">03</span>Latest</h2></div>'
                   f'<div>{rows}</div></div></section>')

    # 트러스트바
    trust = "".join(f'<div class="item">{_ic(p, 18, "var(--good)")}'
                    f'<span><strong>{esc(t)}</strong>{esc(rest)}</span></div>' for (p, t, rest) in _TRUST)
    trustbar = f'<section class="trustbar"><div class="in">{trust}</div></section>'

    # 비교 요청 CTA (뉴스레터 백엔드가 없으므로 가짜 구독 폼 대신 실제 동작하는 요청 링크 — 정직성)
    request_cta = ('<section class="ctasec"><div class="container"><div class="nl-card">'
                   '<div class="ey">Request</div>'
                   '<h2>Deciding between two tools? Ask us to compare them.</h2>'
                   '<p>Tell us which tools you are weighing — good requests become full comparisons.</p>'
                   '<a class="nl-cta" href="/contact/">Request a comparison</a></div></div></section>')

    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "WebSite", "name": "stack.",
        "url": base + "/", "description": "Independent SaaS, developer, and AI tool comparisons and guides.",
    }, ensure_ascii=False) + "</script>")

    return f"""<!doctype html>
<html lang="en">
<head>
{_head("stack. — independent software comparisons & guides", "We compare SaaS, developer, and AI tools using official docs and public data — pricing, features, and data ownership.", canonical or base + "/", "website", jsonld)}
</head>
<body>
<a class="skip" href="#featured">Skip to content</a>
{_header()}
<section class="hero"><div class="container">
<span class="pill"><span class="dot"></span>{esc(domain)}</span>
<h1>Tool choices, backed by <span class="ac">data</span> — not vibes.</h1>
<p class="dek">We compare SaaS, developer, and AI tools using official docs and public data — pricing, features, and data ownership, distilled to what your decision needs.</p>
<form class="searchbox" action="/search/" method="get" role="search">
<div class="field">{_ic('<circle cx="11" cy="11" r="7"></circle><path d="m20 20-3-3"></path>', 19, "var(--muted)")}
<input name="q" placeholder="Search tools to compare…  e.g. Cursor, Notion" aria-label="Search tools"></div>
<button type="submit">Search</button>
</form>
<div class="pills"><span class="lab">Popular:</span>{pills}</div>
</div></section>
{trustbar}
{featured_html}
{categories_html}
{latest_html}
{request_cta}
{_footer()}
{_SCRIPTS}
</body>
</html>"""


def render_hub(name: str, dek: str, pages, *, domain: str = SITE_DOMAIN, canonical: str = "") -> str:
    """카테고리 허브 페이지 — 해당 카테고리의 비교글 카드 그리드."""
    cards = "".join(_feat_card(p) for p in pages) or \
        '<p style="color:var(--muted);padding:18px 0">No articles in this category yet — check back soon.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
{_head(name + " — stack.", dek, canonical, "website")}
</head>
<body>
<a class="skip" href="#hub">Skip to content</a>
{_header()}
<div class="container" style="padding-top:32px;padding-bottom:64px"><main id="hub">
<nav class="crumb"><a href="/">Home</a><span class="s">/</span><span class="cur">{esc(name)}</span></nav>
<div class="kicker">Category</div>
<h1>{esc(name)}</h1>
<p class="dek">{esc(dek)}</p>
{_ad("hub-top", "leaderboard")}
<div class="feat-grid" style="margin-top:24px">{cards}</div>
</main></div>
{_footer()}
{_SCRIPTS}
</body>
</html>"""
