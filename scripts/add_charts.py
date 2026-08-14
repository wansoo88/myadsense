#!/usr/bin/env python3
"""dist/queue/*.html 에 인라인 SVG 차트를 주입한다 (재실행 가능).

왜 — 2026-08-11 AdSense "가치가 별로 없는 콘텐츠" 거절 대응. 발행분 전편에
본문 이미지·도해가 **0개**였다. 표만 스무 줄 이어지는 페이지는 훑어볼 수가 없다.

무엇을 그리나 (둘 다 **이미 그 페이지에 있는 데이터**로만 그린다):
  1. 기능 커버리지 — Feature matrix 의 ✓/△/✗ 를 도구별로 센 가로 누적 막대.
     10줄짜리 표를 다 읽지 않아도 "누가 더 채웠나"가 한눈에 보인다.
  2. 가격 비교     — price-card 의 금액 막대. **통화와 청구주기가 같은 카드만** 그린다.
     월 $20 옆에 연 $68 을 같은 축에 세우면 그건 도움이 아니라 거짓말이다.
     못 그린 카드가 있으면 몇 개를 왜 뺐는지 캡션에 밝힌다.

정직하게: 이건 페이지에 이미 있는 정보를 **다시 보여주는** 것이지 새 정보가 아니다.
실질 가치는 1차 데이터(관측·실측) 글이 담당한다.

⚠️ 사이트는 영어권 독자용이다 — 차트 안 문구도 전부 영어여야 한다.
색은 렌더러 CSS 변수(--good/--warn/--bad/--accent/--muted)를 쓰므로 다크모드가 따라온다.
새 CSS 는 추가하지 않는다 — 큐 HTML 은 이미 렌더된 상태라 renderer.py 를 고쳐도 안 먹는다.
가로 스크롤 컨테이너는 페이지에 이미 있는 `.tablewrap` 을 그대로 쓴다.

사용:
    python scripts/add_charts.py [--dry-run]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "dist", "queue")

VB_W = 520  # viewBox 폭. 데스크톱에서 원본 크기, 좁은 화면에서만 줄어든다.

SEC_RE_T = r'(<section class="blk" id="%s">)(.*?)(</section>)'
TH_RE = re.compile(r'<th class="ctr">(.*?)</th>', re.S)
TR_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
TD_CTR_RE = re.compile(r'<td class="ctr">(.*?)</td>', re.S)
PN_RE = re.compile(r'<div class="pn">(.*?)</div>', re.S)
PP_RE = re.compile(r'<div class="pp">(.*?)</div>', re.S)
SUB_RE = re.compile(r'(<p class="sub">.*?</p>)', re.S)
H2_RE = re.compile(r"(<h2[^>]*>.*?</h2>)", re.S)
CHART_RE = re.compile(r'<figure data-chart="[^"]*">.*?</figure>', re.S)

# 이 말이 붙은 숫자는 "그 플랜의 확정 가격"이 아니다 — 축에 세우지 않는다.
# ⚠️ "from $7.53" 은 여기 없다. 그건 벤더가 공표한 **하한**이라 검증 가능하고,
#    막대에 'from $7.53' 이라고 그대로 적으면 독자를 속이지 않는다.
#    반면 "About $4" · "~$20" 은 우리가 어림한 값이라 축에 올리면 안 된다.
VAGUE = ("confirm", "custom", "contact", "usage", "varies", "quote",
         "about $", "around", "approx", "roughly", "~$")

CUR_NAME = {"$": "USD", "€": "EUR", "₩": "KRW", "£": "GBP"}


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def wrap(kind: str, svg: str, caption: str) -> str:
    return (
        '<figure data-chart="%s" style="margin:0 0 20px">'
        '<div class="tablewrap">%s</div>'
        '<figcaption style="font-size:13px;color:var(--muted);margin-top:8px">%s</figcaption>'
        "</figure>" % (kind, svg, esc(caption))
    )


def svg_open(height: int, aria: str) -> str:
    return (
        '<svg viewBox="0 0 %d %d" role="img" aria-label="%s" '
        'style="width:%dpx;max-width:100%%;height:auto;display:block">'
        % (VB_W, height, esc(aria), VB_W)
    )


def txt(x: float, y: float, s: str, fill: str, font: str, anchor: str = "") -> str:
    a = ' text-anchor="%s"' % anchor if anchor else ""
    return '<text x="%.1f" y="%.1f" fill="%s"%s style="font:%s system-ui,-apple-system,sans-serif">%s</text>' % (
        x, y, fill, a, font, esc(s))


# ─────────────────────────────────────────────── 기능 커버리지

def feature_chart(body: str) -> str | None:
    heads = [strip_tags(h) for h in TH_RE.findall(body)]
    if len(heads) < 2:
        return None
    tally = [[0, 0, 0] for _ in heads]  # full, partial, none
    counted = 0
    for r in TR_RE.findall(body):
        cells = TD_CTR_RE.findall(r)
        if len(cells) != len(heads):
            continue
        counted += 1
        for n, c in enumerate(cells):
            tally[n][0 if "mk-good" in c else 1 if "mk-warn" in c else 2] += 1
    if counted < 4:
        return None  # 네 줄도 안 되는 표는 그냥 읽는 게 빠르다

    x0, row_h = 116, 30
    width = VB_W - x0 - 4
    height = len(heads) * row_h + 26
    unit = width / counted

    aria = "; ".join(
        "%s: %d full, %d partial, %d not supported" % (h, t[0], t[1], t[2])
        for h, t in zip(heads, tally))
    out = [svg_open(height, aria)]
    for n, (head, t) in enumerate(zip(heads, tally)):
        y = n * row_h + 4
        out.append(txt(0, y + 15, clip(head, 15), "var(--ink-soft)", "600 14px"))
        x = float(x0)
        for count, color in ((t[0], "var(--good)"), (t[1], "var(--warn)"), (t[2], "var(--bad)")):
            if count <= 0:
                continue
            w = count * unit
            out.append('<rect x="%.1f" y="%d" width="%.1f" height="21" rx="3" fill="%s" opacity=".88"/>'
                       % (x, y, w, color))
            if w >= 20:
                out.append(txt(x + w / 2, y + 16, str(count), "var(--bg)", "700 13px", "middle"))
            x += w

    # 범례 — ■ 를 rect 로 그린다(폰트에 없는 글리프로 네모가 깨지는 걸 피한다).
    ly = height - 8
    lx = float(x0)
    for color, label in (("var(--good)", "full"), ("var(--warn)", "partial / paid"),
                         ("var(--bad)", "not supported")):
        out.append('<rect x="%.1f" y="%.1f" width="9" height="9" rx="2" fill="%s"/>' % (lx, ly - 8, color))
        out.append(txt(lx + 13, ly, label, "var(--muted)", "12px"))
        lx += 13 + len(label) * 6.4 + 14
    out.append(txt(0, ly, "%d rows" % counted, "var(--muted)", "12px"))
    out.append("</svg>")

    return wrap("features", "".join(out),
                "Coverage summary of the table below — counted from the same rows.")


# ─────────────────────────────────────────────── 가격

AMT_RE = re.compile(r"(?P<cur>[$€₩£])\s?(?P<amt>\d[\d,]*(?:\.\d+)?)\s*(?P<k>[KkMm])?")
MONTH_RE = re.compile(r"\b(?:per\s+)?(?:month|mo)\b|/\s*mo\b", re.I)
YEAR_RE = re.compile(r"\b(?:per\s+)?(?:year|yr|annual(?:ly)?)\b|/\s*yr\b", re.I)
SEAT_RE = re.compile(r"\b(?:per\s+)?(?:user|seat|member|developer)\b", re.I)
LEAD_RE = re.compile(r"^(?:from|starting at|starts at|paid|included from)\s+", re.I)
TRAIL_RE = re.compile(r"\s+(?:from|starting at|starts at)$", re.I)


def vendor_of(card_name: str) -> str:
    """'Postman — Paid (Basic / Pro)' → 'Postman'. 복합 카드의 조각에 붙일 접두사."""
    return re.split(r"\s*[—–-]\s+", card_name, 1)[0].strip()


def vendor_key(card_name: str) -> str:
    """차트가 **양쪽**을 그리고 있는지 세는 열쇠. 'Bitwarden Free' 와 'Bitwarden Premium' 은 한 표다.

    한쪽 벤더만 남은 막대 그래프는 정보가 아니라 오해다 — Fireflies 가격이
    "confirm on vendor site" 라 빠지면 Otter 3줄만 그려지고, 독자는
    Fireflies 가 무료인 줄 안다.
    """
    return re.split(r"[\s(—–-]", card_name.strip(), 1)[0].lower().strip(".,")


def parse_card(card_name: str, raw: str) -> list[dict]:
    """가격 카드 하나 → 축에 세울 수 있는 점들. 못 세우면 빈 목록.

    `pp` 는 한 값만 있는 게 아니다. 'Basic $10 · Business $16 per user/mo' 처럼
    한 카드가 여러 플랜을 담는 경우가 절반쯤 된다 — 가운뎃점으로 쪼개 각각 세운다.
    """
    text = " ".join(strip_tags(raw).split())
    low = text.lower()
    if any(v in low for v in VAGUE):
        return []  # 'around $20 … confirm' 류 — 확정값이 아니니 축에 세우지 않는다

    has_m, has_y = bool(MONTH_RE.search(text)), bool(YEAR_RE.search(text))
    if has_m and has_y:
        # '$2.49/mo (billed upfront, auto-renews ~$99.95/yr)' — 한 문장에 두 주기가 섞여 있다.
        # 어느 숫자가 어느 축의 값인지 기계가 고를 수 없다. 통째로 뺀다.
        return []
    period = "month" if has_m else "year" if has_y else None
    seat = bool(SEAT_RE.search(text))
    free = {"amount": 0.0, "cur": None, "period": None, "seat": False, "disp": "Free"}

    if not AMT_RE.search(text):
        # 숫자가 아예 없다 — 'Free …' 로 시작할 때만 0 으로 인정한다.
        return [dict(free, label=card_name)] if low.startswith("free") else []
    if period is None:
        return []  # 금액은 있는데 청구주기를 모른다 — 같은 축에 세울 수 없다

    # ⚠️ 세미콜론으로는 쪼개지 않는다. '·' 는 플랜 구분자지만 ';' 는 문장 구분자다.
    segs = [s.strip() for s in text.split("·") if s.strip()]
    if len(segs) > 4:
        return []
    vendor = vendor_of(card_name)
    pts = []
    for seg in segs:
        m = AMT_RE.search(seg)
        if not m:
            if seg.lower().startswith("free"):
                pts.append(dict(free, label=card_name if len(segs) == 1 else "%s Free" % vendor))
            continue
        amt = float(m.group("amt").replace(",", ""))
        if m.group("k"):
            amt *= 1000 if m.group("k").lower() == "k" else 1_000_000
        head = seg[: m.start()]
        name = TRAIL_RE.sub("", LEAD_RE.sub("", head.strip(" ([")).strip()).strip()
        label = card_name if len(segs) == 1 or not name else "%s %s" % (vendor, name)
        if amt == 0:                       # '$0' · '₩0' 은 무료 플랜이다
            pts.append(dict(free, label=label))
            continue
        if amt >= 1_000_000 or "," in name or len(name) > 24:
            continue                       # 이름이 문장 조각이면 쪼개기가 틀린 것이다
        floor = bool(re.search(r"\bfrom\b|\bstarting at\b", head, re.I))
        pts.append({"label": label, "amount": amt, "cur": m.group("cur"), "period": period,
                    "seat": seat, "vendor": vendor_key(card_name),
                    "disp": ("from " if floor else "") + m.group(0).strip()})
    return pts


def price_chart(body: str) -> str | None:
    cards, points = 0, []
    for c in body.split('<div class="price-card">')[1:]:
        pn, pp = PN_RE.search(c), PP_RE.search(c)
        if not (pn and pp):
            continue
        cards += 1
        points.append(parse_card(strip_tags(pn.group(1)), pp.group(1)))
    if cards < 3:
        return None

    # 통화·주기가 같은 무리 중 가장 큰 것만 그린다. Free 는 어느 무리에나 0 으로 얹힌다.
    flat = [p for ps in points for p in ps]
    groups: dict[tuple[str, str], int] = {}
    for p in flat:
        if p["cur"]:
            groups[(p["cur"], p["period"])] = groups.get((p["cur"], p["period"]), 0) + 1
    if not groups:
        return None
    cur, period = max(groups, key=lambda k: groups[k])

    picked, dropped = [], 0
    for ps in points:
        keep = [p for p in ps if p["cur"] is None or (p["cur"] == cur and p["period"] == period)]
        if keep:
            picked.extend(keep)
        else:
            dropped += 1
    paid = [p for p in picked if p["amount"] > 0]
    if len(picked) < 3 or len({p["amount"] for p in paid}) < 2 or len(picked) > 12:
        return None
    # 유료 막대가 한 벤더에서만 나오면 그 그림은 "상대는 공짜"라는 거짓말이 된다.
    if len({p["vendor"] for p in paid}) < 2:
        return None
    # 카드의 3분의 1 넘게 못 그렸으면 남은 것만으로 그린 그림은 이 페이지의 가격이 아니다.
    if dropped * 3 > cards:
        return None

    top = max(p["amount"] for p in paid)
    x0, row_h = 146, 28
    width = VB_W - x0 - 78
    height = len(picked) * row_h + 24

    aria = "; ".join("%s: %s" % (p["label"], p["disp"]) for p in picked)
    out = [svg_open(height, aria)]
    for n, p in enumerate(picked):
        y = n * row_h + 3
        out.append(txt(0, y + 14, clip(p["label"], 21), "var(--ink-soft)", "13px"))
        w = max((p["amount"] / top) * width if p["amount"] > 0 else 3.0, 3.0)
        fill = "var(--accent)" if p["amount"] > 0 else "var(--line-strong)"
        out.append('<rect x="%d" y="%d" width="%.1f" height="19" rx="3" fill="%s" opacity=".9"/>'
                   % (x0, y, w, fill))
        out.append(txt(x0 + w + 6, y + 14, clip(p["disp"], 12), "var(--ink)", "600 12px"))

    unit = "per year" if period == "year" else "per month"
    axis = "%s, %s" % (CUR_NAME.get(cur, cur), unit)
    if any(p["seat"] for p in picked):
        axis += " — some tiers are per user"
    out.append(txt(0, height - 5, axis, "var(--muted)", "12px"))
    out.append("</svg>")

    cap = "Plans on one axis — only tiers billed in %s %s are plotted." % (CUR_NAME.get(cur, cur), unit)
    if dropped:
        cap += (" %d other card%s on this page (different billing period, or no published number) "
                "%s not plotted." % (dropped, "s" if dropped > 1 else "",
                                     "are" if dropped > 1 else "is"))
    return wrap("pricing", "".join(out), cap)


# ─────────────────────────────────────────────── 주입

def inject(section: str, chart: str) -> str:
    """h2(있으면 sub) 바로 뒤에 넣는다 — 요약이 표보다 먼저 와야 훑어진다."""
    m = SUB_RE.search(section) or H2_RE.search(section)
    if not m:
        return section
    return section[: m.end()] + chart + section[m.end():]


def process(path: str, dry: bool) -> str:
    slug = os.path.splitext(os.path.basename(path))[0]
    text = original = open(path, encoding="utf-8").read()
    text = CHART_RE.sub("", text)  # 재실행: 이전 차트를 걷어내고 다시 그린다

    made = []
    for sid, maker in (("features", feature_chart), ("pricing", price_chart)):
        m = re.search(SEC_RE_T % sid, text, re.S)
        if not m:
            continue
        chart = maker(m.group(2))
        if not chart:
            continue
        text = text[: m.start()] + m.group(1) + inject(m.group(2), chart) + m.group(3) + text[m.end():]
        made.append(sid)

    if text == original:
        return "none   %s" % slug
    if not dry:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return "chart  %s  (%s)" % (slug, ", ".join(made) or "제거만")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--queue", default=QUEUE)
    a = ap.parse_args()

    files = sorted(f for f in os.listdir(a.queue) if f.endswith(".html"))
    n = 0
    for f in files:
        line = process(os.path.join(a.queue, f), a.dry_run)
        if line.startswith("chart"):
            n += 1
        print(line)
    print("\n%d/%d 편에 차트%s" % (n, len(files), " (dry-run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
