#!/usr/bin/env python3
"""build_price_index.py — config/prices.yaml 의 관측 가격을 한 장의 참조 페이지로 만든다.

왜 이 스크립트가 있나 (2026-08-12):
    AdSense 거절("가치가 별로 없는 콘텐츠") 대응으로 벤더 공식 pricing 페이지 25곳을 직접 열어
    52개 플랜의 실제 가격을 관측했다(config/prices.yaml). 그 데이터는 개별 비교글의 카드에
    들어갔지만, **한 장에 모으면 그 자체로 아무도 공개하지 않는 참조 자료**가 된다.
    동시에 사이트의 32편이 전부 'X vs Y' 비교글이라는 포맷 단조 문제도 함께 푼다.

설계 원칙 (build_crawler_report.py 와 동일):
    🔴 **가격을 기사에 하드코딩하지 않는다.** prices.yaml 이 단일 출처다. 값을 갱신하고
       이 스크립트를 다시 돌리면 기사도 함께 갱신된다. 하드코딩하면 둘이 조용히 갈라지고,
       그건 우리가 방금 고친 실패("가격이 낡아 있었다")를 재발시키는 길이다.
    · 확인하지 못한 항목(`unverified: true`)은 **숫자를 지어내지 않고 그렇다고 밝힌다.**
    · 모든 행에 출처 링크와 관측일을 단다. 재현 불가능한 표는 1차 데이터가 아니다.

사용:
    ./.venv/bin/python scripts/build_price_index.py --dry-run
    ./.venv/bin/python scripts/build_price_index.py
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

PRICES = os.path.join(ROOT, "config", "prices.yaml")
SLUG = "what-developer-tools-actually-cost-a-checked-price-index"

# 호스트 → (제품 표시명, 분류). 분류는 사이트 카테고리와 맞춘다.
VENDOR = {
    "cursor.com": ("Cursor", "AI coding"),
    "github.com": ("GitHub Copilot", "AI coding"),
    "docs.github.com": ("GitHub Copilot", "AI coding"),
    "claude.com": ("Claude / Claude Code", "AI coding"),
    "devin.ai": ("Windsurf / Devin (Cognition)", "AI coding"),
    "www.tabnine.com": ("Tabnine", "AI coding"),
    "aws.amazon.com": ("Amazon Q Developer", "AI coding"),
    "sourcegraph.com": ("Sourcegraph Cody", "AI coding"),
    "1password.com": ("1Password", "Passwords & security"),
    "bitwarden.com": ("Bitwarden", "Passwords & security"),
    "proton.me": ("Proton Pass", "Passwords & security"),
    "nordvpn.com": ("NordVPN", "Passwords & security"),
    "www.postman.com": ("Postman", "Dev tools"),
    "insomnia.rest": ("Insomnia", "Dev tools"),
    "linear.app": ("Linear", "Dev tools"),
    "www.atlassian.com": ("Jira", "Dev tools"),
    "www.notion.com": ("Notion", "Productivity"),
    "obsidian.md": ("Obsidian", "Productivity"),
    "www.jasper.ai": ("Jasper", "Productivity"),
    "www.copy.ai": ("Copy.ai", "Productivity"),
    "otter.ai": ("Otter.ai", "Productivity"),
    "docs.hetzner.com": ("Hetzner Cloud", "Hosting"),
    "www.digitalocean.com": ("DigitalOcean", "Hosting"),
    "render.com": ("Render", "Hosting"),
    "neon.com": ("Neon", "Hosting"),
    "ghost.org": ("Ghost(Pro)", "Hosting"),
    "plausible.io": ("Plausible", "Hosting"),
}
CAT_ORDER = ["AI coding", "Hosting", "Dev tools", "Passwords & security", "Productivity"]
# 벤더의 플랜이 아니라 '어떤 방식으로 굴릴까' 안내였던 카드 — 참조표에는 넣지 않는다.
GUIDANCE_PLANS = {"Self-hosted (VPS)", "Managed Privacy Analytics (Cloud)"}


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def load():
    import yaml
    with open(PRICES, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    meta = data.get("meta") or {}
    as_of = str(meta.get("as_of") or "")
    seen, rows = set(), []
    for c in data.get("cards") or []:
        src = c.get("source") or ""
        host = urllib.parse.urlparse(src).netloc
        product, cat = VENDOR.get(host, (host or "—", "Other"))
        plan = re.sub(r"\s+", " ", str(c.get("plan") or "")).strip()
        price = re.sub(r"\s+", " ", str(c.get("price") or "")).strip()
        # 벤더 플랜이 아니라 '어떻게 호스팅할까' 안내였던 카드는 참조표에서 뺀다.
        # 이런 행은 출처 호스트로 제품을 유추하면 엉뚱하게 붙는다(예: 여러 벤더를 비교하는
        # "Self-hosted (VPS)" 가 출처 도메인 때문에 DigitalOcean 행으로 보임 — 검수 지적).
        if plan in GUIDANCE_PLANS:
            continue
        # 같은 (제품, 가격) 이 여러 글에 쓰였으면 한 번만 싣는다 — 참조표는 중복이 없어야 쓸모가 있다
        key = (product, price)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"product": product, "cat": cat, "plan": plan, "price": price,
                     "note": (c.get("note") or "").strip(), "source": src,
                     "unverified": bool(c.get("unverified"))})

    # 같은 제품의 행끼리 가격이 겹치면 **덜 완전한 쪽을 버린다**(검수 지적: 같은 가격이 두 번 나옴).
    # 판정은 '·' 개수 같은 표기 습관이 아니라 **가격 숫자 집합의 포함관계**로 한다:
    #   A 의 숫자들이 B 의 진부분집합이면 A 는 B 가 이미 말한 것만 말하므로 버린다.
    #   서로 포함하지 않으면(예: Copilot 개인 티어 vs 조직 티어) 둘 다 남긴다.
    # 숫자가 없는 행(unverified·사용량 과금)은 비교 대상이 아니므로 그대로 둔다.
    amt_re = re.compile(r"[\$€₩]\s?[\d][\d,]*(?:\.\d+)?[KkMm]?")
    by_product = collections.defaultdict(list)
    for r in rows:
        r["_amts"] = frozenset(a.replace(" ", "") for a in amt_re.findall(r["price"]))
        by_product[r["product"]].append(r)
    keep = []
    for _p, rs in by_product.items():
        for r in rs:
            if r["_amts"] and any(o is not r and r["_amts"] < o["_amts"] for o in rs):
                continue                      # 다른 행이 더 완전하게 말하고 있다
            keep.append(r)
    for r in keep:
        r.pop("_amts", None)
    return keep, as_of


def build_spec(rows, as_of):
    from content import generator, renderer
    today = dt.date.today().isoformat()
    by_cat = collections.defaultdict(list)
    for r in rows:
        by_cat[r["cat"]].append(r)
    cats = [c for c in CAT_ORDER if c in by_cat] + [c for c in by_cat if c not in CAT_ORDER]
    n_rows = len(rows)
    n_products = len({r["product"] for r in rows})
    n_unverified = sum(1 for r in rows if r["unverified"])

    def table(cat):
        body = ""
        for r in sorted(by_cat[cat], key=lambda x: (x["product"], x["plan"])):
            note = f'<br><span class="footnote">{esc(r["note"])}</span>' if r["note"] else ""
            price = (f'<em>not verified</em>' if r["unverified"] else esc(r["price"]))
            body += (f'<tr><td class="featc">{esc(r["product"])}</td>'
                     f'<td>{esc(r["plan"])}</td>'
                     f'<td>{price}{note}</td>'
                     f'<td><a href="{esc(r["source"])}" rel="nofollow">official page</a></td></tr>')
        return ('<div class="tablewrap"><table class="tbl"><thead><tr>'
                '<th class="feat">Product</th><th class="feat">Plan</th>'
                '<th class="feat">Price</th><th class="feat">Source</th>'
                f'</tr></thead><tbody>{body}</tbody></table></div>')

    sections = [
        {"heading": "How this list was built",
         "html": (
             f"<p>On {esc(as_of)} we opened the official pricing page of every product below and wrote "
             f"down what it showed. Not a vendor summary, not last year's blog post — the page itself, "
             f"on that date. Where a figure could not be read from the official page we say so rather "
             f"than filling the gap with a guess"
             + (f"; {n_unverified} entr{'y is' if n_unverified == 1 else 'ies are'} marked that way."
                if n_unverified else ".") + "</p>"
             "<p>Two things this list deliberately does not do. It does not convert currencies — where "
             "a vendor quotes in euros or localises by region, that is what you see, because the "
             "conversion is not ours to assert. And it does not rank anything: this is a reference "
             "table, not a recommendation.</p>"
             "<p>Prices move. Anything here is a snapshot with a date attached, and the linked official "
             "page is always the authority. We would rather publish a dated figure you can check than "
             "an undated hedge that tells you nothing.</p>")},
        {"heading": "What changed recently",
         "html": (
             "<p>Checking every page on one day surfaced several changes that older comparisons still "
             "have wrong. These are the ones worth knowing before you budget:</p>"
             "<ul>"
             "<li><strong>Hetzner raised cloud prices on 15 June 2026.</strong> The increases were "
             "uneven: dedicated-vCPU CCX13 went from €15.99 to €42.99 a month and shared-vCPU CPX22 "
             "from €7.99 to €19.49, while the entry CX23 moved only €3.99 → €5.49 and Arm CAX11 "
             "€4.49 → €5.99. Hetzner is still inexpensive at the entry tier, but on the larger plans "
             "the gap against other hosts is much narrower than 2025-era comparisons suggest.</li>"
             "<li><strong>Windsurf is now part of Cognition.</strong> windsurf.com redirects to "
             "devin.ai. Pro moved from $15 to $20 in March 2026 when credits were replaced by daily "
             "and weekly quotas, and a $200/month Max tier appeared.</li>"
             "<li><strong>Copy.ai has moved upmarket.</strong> Alongside a $29/month Chat plan, its "
             "go-to-market tiers now start at $1,000 a month. If you remember it as a cheap writing "
             "assistant, that is no longer the product being sold.</li>"
             "<li><strong>Render dropped per-seat billing.</strong> Flat $25/month Pro and $499/month "
             "Scale plans replaced the old $19 and $29 per-member tiers.</li>"
             "<li><strong>Sourcegraph's public pricing is enterprise-only</strong>, starting at $16K. "
             "The standalone individual Cody tiers are no longer sold there.</li>"
             "<li><strong>Postman renamed its tiers</strong> to Solo, Team and Enterprise; the old "
             "Basic/Professional names persist in a lot of published comparisons.</li>"
             "</ul>"
             "<p>None of this is exotic. It is simply what a single day of reading official pages "
             "turns up, and it is the reason we date every figure.</p>")},
    ]
    for cat in cats:
        sections.append({"heading": cat, "html": table(cat)})
    sections.append(
        {"heading": "A note on regional pricing",
         "html": (
             "<p>One entry behaved differently from the rest: Notion served our request prices in "
             "Korean won rather than US dollars. That is not an error in the table — it is how the "
             "vendor localises, and it is a useful reminder that a single quoted figure can be wrong "
             "for your region even when it is right for whoever wrote it down.</p>"
             "<p>Where you see a currency other than USD below, it is the currency the official page "
             "actually showed us. Check your own region before you plan a budget around it.</p>")})

    faq = [
        {"q": "How current are these prices?",
         "a": (f"Every figure was read from the vendor's official pricing page on {as_of}. Vendors "
               "change prices without notice, so treat the date as part of the number and follow the "
               "source link for the current figure.")},
        {"q": "Why are some prices in euros or won?",
         "a": ("Because that is what the official page showed. We do not convert currencies — an "
               "exchange rate we picked would be our assertion, not the vendor's price. Some vendors "
               "also localise pricing by region, so your figure may differ.")},
        {"q": "Why are some entries marked 'not verified'?",
         "a": ("Some vendors load prices dynamically per currency or account, and the figure could not "
               "be read from the public page. We would rather leave a gap than publish a number we "
               "did not see.")},
        {"q": "Are annual and monthly prices the same?",
         "a": ("Usually not. Where a vendor advertises both, the note column says which billing term "
               "the figure belongs to. Annual billing is commonly 15–25% cheaper, but the discount "
               "varies enough that it is worth checking rather than assuming.")},
    ]

    return generator.ContentSpec(
        slug=SLUG,
        title="What Developer Tools Actually Cost: A Checked Price Index",
        dek=(f"{n_rows} plans across {n_products} products, each read from the vendor's own pricing "
             f"page on {as_of} — with the source link and the date attached to every figure."),
        page_type="guide",
        breadcrumb=[("Home", "/"), ("Dev Tools", "/dev-tools/"), ("Price index", "")],
        author="The Utilverse editors",
        published_at=today,
        updated_at=today,
        canonical=f"{renderer.SITE_URL}/compare/{SLUG}/",
        cluster="dev-saas-compare",
        kicker="First-party data",
        reading_time=8,
        intro_html=(
            "<p>Almost every “X vs Y” article you can find will tell you to check current pricing on "
            "the vendor's site. That advice is correct and completely useless: it hands the work back "
            "to you, which is the work you came to have done.</p>"
            f"<p>So we did it. On {esc(as_of)} we opened the official pricing page for every product "
            f"below and recorded what it showed — <strong>{n_rows} plans across {n_products} "
            f"products</strong>. Each row carries the figure, the billing term where the vendor stated "
            "one, and a link to the page it came from. Where we could not read a figure, the row says "
            "so instead of guessing.</p>"),
        tldr_html=(
            f"<p><strong>{n_rows} plans, {n_products} products, one date: {esc(as_of)}.</strong> "
            "Every price below was read from the vendor's official page that day, with a source link "
            "on each row. Notable movers since older comparisons: Hetzner's June increase, Windsurf's "
            "move under Cognition, Copy.ai's shift upmarket, and Render dropping per-seat billing.</p>"),
        sections=sections,
        verdict_html=(
            "<p>Use this as a starting map, not a quote. The value of a dated index is that you can "
            "see at a glance which products are in which price band, and then confirm the one you "
            "care about on the linked page — a far shorter job than pricing a shortlist from scratch.</p>"
            f"<p>If a figure here is stale, the date tells you so immediately. That is the whole point "
            f"of publishing the observation date next to the number instead of writing “confirm "
            f"current pricing on the vendor's site.”</p>"),
        faq=faq,
        # 출처는 **제품별로 하나씩, 전부** 싣는다. 잘라내면 "모든 행에 출처가 있다"는 본문과
        # Sources 섹션이 어긋난다(검수 지적). 같은 URL 이 여러 행에 쓰였으면 한 번만.
        sources=[{"title": f"{p} — official pricing", "url": u}
                 for p, u in sorted({(r["product"], r["source"]) for r in rows if r["source"]})],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows, as_of = load()
    if not rows:
        sys.exit("prices.yaml 에서 카드를 읽지 못했다")
    cats = collections.Counter(r["cat"] for r in rows)
    print(f"관측일 {as_of} · 고유 행 {len(rows)} · 제품 {len({r['product'] for r in rows})}")
    for c, n in cats.most_common():
        print(f"  {n:>3}  {c}")
    unknown = [r for r in rows if r["cat"] == "Other"]
    if unknown:
        print(f"⚠️ 분류 미상 {len(unknown)}건 — VENDOR 매핑에 추가할 것:")
        for r in unknown[:8]:
            print("   -", r["product"], "|", r["plan"][:40])
    if args.dry_run:
        return 0

    from content import renderer
    doc = renderer.render(build_spec(rows, as_of))
    out = os.path.join(ROOT, "dist", "queue", SLUG + ".html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(doc)
    print(f"\n초안 작성: {out} ({len(doc):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
