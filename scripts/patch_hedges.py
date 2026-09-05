# -*- coding: utf-8 -*-
"""patch_hedges.py — 발행 큐(dist/queue)의 회피 문구("confirm current pricing on the vendor's site" 류)를
관측일이 박힌 사실 문장 또는 1차 출처에서 읽은 실제 숫자로 바꾼다.

배경(reports/adsense-승인연구-2026-09-06.html §3·§6): 2026-08-11 AdSense '가치 없는 콘텐츠' 거절의 직접 근거가
이 문구였고(당시 143회), 08-12 가격 패치 후에도 유지 글 11편에 37회 남아 있었다. 독자에게 "우리도 모른다"만
말하는 문장은 페이지의 존재 이유를 지운다.

원칙
- 큐 원본을 **정확 문자열**로만 바꾼다(정규식 아님). 앵커가 기대 횟수와 다르면 그 글은 건드리지 않고 실패로 보고.
- 숫자는 전부 1차 출처 + 관측일: cursor.com/pricing · postman.com/pricing · obsidian.md/pricing · railway.com/pricing ·
  render.com/pricing · api.vultr.com/v2/plans · GitHub 저장소 license 파일 (모두 2026-09-06 관측).
  Windsurf 는 pricing 페이지가 devin.ai/pricing 으로 308 리다이렉트되고 그 페이지가 429 를 돌려줘 숫자를 못 얻었다 → 그 사실만 적는다.
- 아포스트로피는 생성 시점에 `'`·`&#x27;` 두 표기가 섞여 있다 → 변형을 순서대로 시도한다.
- 재실행 멱등: 이미 바뀐 글은 앵커가 0회라 "이미 적용"으로 건너뛴다.

사용:  python scripts/patch_hedges.py [--dry-run] [--check]   (리포 루트에서)
"""
from __future__ import annotations
import argparse
import glob
import html
import os
import re
import sys

QUEUE = "dist/queue"
D = "2026-09-06"   # 관측일(1차 출처 조회일)

# slug → [(old, new, expected_count), ...]
PATCHES: dict[str, list[tuple[str, str, int]]] = {
    "best-self-hosted-alternatives-to-notion-8-open-source-picks": [
        ("always confirm current cloud pricing and license terms on each vendor's own site.",
         f"licenses were read from each project's GitHub repository on {D} and are noted per tool below.", 1),
        ("Confirm the current license on each project's repository before relying on it.",
         f"As read from each project's GitHub license file on {D}: AppFlowy, Docmost, SiYuan and TriliumNext are AGPL-3.0; "
         "AFFiNE, Outline and Anytype ship custom or source-available license files rather than a standard OSI identifier.", 1),
        ("AppFlowy ships iOS/Android apps; AFFiNE mobile support is more limited — confirm current status.",
         f"AppFlowy ships iOS/Android apps (its README links the Play Store listing as of {D}); AFFiNE's README mentions no mobile app on the same date.", 1),
        ("The code is open source (AGPL); confirm current license and plan details on the official site.",
         f"The code is licensed AGPL-3.0 (GitHub license file, checked {D}).", 1),
        ("It is open source; confirm the current repository and license terms.",
         f"It is licensed AGPL-3.0 (TriliumNext/Trilium license file on GitHub, checked {D}).", 1),
        ("and confirm current features, licenses, and pricing on each official site before standardizing on one.",
         f"and weigh the result against the license and maintenance notes above (checked {D}) before standardizing on one.", 1),
    ],
    "bitwarden-vs-1password-which-password-manager-should-you-use": [
        ("Pricing and promotions change often, so treat the tiers below as a guide and confirm current numbers on each vendor's site before subscribing.",
         "The pricing section below shows the date each figure was checked; vendors change prices and run promotions, so a figure is only as current as its date.", 1),
        ("Because both vendors adjust pricing and run promotions, confirm the current figures on each pricing page before you commit.",
         "Both vendors adjust pricing and run promotions; the figures in the pricing section carry the date we checked them.", 1),
    ],
    "bruno-vs-postman-git-native-client-vs-cloud-platform-2026": [
        ("Confirm current pricing and limits on the vendor site",
         f"Free $0 · Solo $9/mo · Team $19/user/mo · Enterprise $49/user/mo, billed annually (postman.com/pricing, checked {D})", 1),
        ("Its pricing page was not part of the source material used for this article, so confirm the current numbers and plan limits directly on postman.com before budgeting.",
         f"As of {D} its pricing page lists Free ($0), Solo ($9/month), Team ($19 per user/month) and Enterprise ($49 per user/month), all billed annually; monthly billing costs more.", 1),
        ("Pricing and plan limits were not in the source material — confirm on the vendor site",
         f"Paid plans start at $9/month (Solo) and $19 per user/month (Team) on annual billing (checked {D})", 1),
    ],
    "cheap-vps-in-2026-digitalocean-and-vultr-compared-with-our-value-picks": [
        ("always confirm current pricing on the provider's site before you buy, since plans change.",
         f"Vultr's per-plan prices below were read from its public plans API on {D}; every number carries the date it was observed.", 1),
        ("Per-plan prices not listed on the pages checked; confirm on vultr.com",
         f"Cloud Compute from $2.50/mo (IPv6-only, 512 MB) · $3.50/mo (512 MB, 10 GB SSD) · $5/mo (1 vCPU, 1 GB, 25 GB SSD, 1 TB transfer) — api.vultr.com/v2/plans, {D}", 1),
        ("Confirm current pricing on digitalocean.com",
         "Basic Droplets from $4.00/mo (observed 2026-07-25 on digitalocean.com)", 2),
        ("Confirm current Cloud Compute rates on vultr.com",
         f"Cloud Compute from $5/mo for 1 vCPU / 1 GB / 25 GB SSD (plans API, {D})", 1),
        ("Vultr's per-plan VPS prices are not listed on the documentation pages checked on 2026-07-25, so confirm current Cloud Compute rates and included transfer directly on vultr.com before comparing them dollar-for-dollar against DigitalOcean's published tiers.",
         f"Vultr's per-plan prices were not on the documentation pages we checked on 2026-07-25, so on {D} we read them from Vultr's public plans API instead: "
         "the 1 vCPU / 1 GB Cloud Compute plan is $5/mo with 25 GB SSD and 1 TB transfer, the 512 MB plan is $3.50/mo (or $2.50/mo IPv6-only), "
         "and High Performance starts at $6/mo for 1 vCPU / 1 GB. That puts Vultr's 1 GB tier $1 above DigitalOcean's $4 Basic Droplet, with twice the RAM.", 1),
        ("Per-plan VPS pricing not on the documentation pages checked (2026-07-25) — must confirm on vultr.com",
         f"The $2.50/mo headline plan is IPv6-only; the cheapest plan with an IPv4 address is $3.50/mo (plans API, {D})", 1),
        ("Because per-plan VPS prices were not on the pages checked, confirm current Cloud Compute rates on vultr.com before deciding on price alone.",
         f"Its entry Cloud Compute plans are $3.50/mo (512 MB) and $5/mo (1 GB) as read from the plans API on {D}, so on list price it sits within a dollar of DigitalOcean at each tier.", 1),
    ],
    "cursor-vs-windsurf-which-ai-code-editor-should-you-use-in-2026": [
        ("Pricing for both has shifted toward usage- and credit-based models, so always confirm current numbers on the vendors' own pages before you commit.",
         f"Pricing for both has shifted toward usage- and credit-based models; the figures in this article carry the date we checked them "
         f"(Cursor's pricing page on {D}; Windsurf's pricing page now redirects to devin.ai/pricing after the Cognition acquisition).", 1),
        ("Both have free tiers — trial both on your own codebase, and confirm current pricing on each vendor's site.",
         f"Both have free tiers — trial both on your own codebase; Cursor Pro is $20/month and Teams $40 per user/month as of {D}.", 1),
        ("Moved toward usage/credit-based pricing (confirm current)",
         f"Usage/credit-based; Pro $20/mo, Teams $40/user/mo ({D})", 1),
        ("Credit-based plans (confirm current)",
         f"Credit-based plans; pricing page redirects to devin.ai/pricing ({D})", 1),
        ("Windsurf inherits Codeium's hybrid/self-hosted options; confirm current Cursor enterprise terms.",
         f"Windsurf inherits Codeium's hybrid/self-hosted options; Cursor lists an Enterprise tier with custom pricing ({D}).", 1),
        ("Per-user, per-month + custom Enterprise (confirm current price)",
         f"Per-user, per-month + custom Enterprise (pricing page redirected to devin.ai/pricing on {D}; figure not captured)", 1),
        ("Confirm the current price and credit/usage limits on each vendor's pricing page before subscribing.",
         f"Cursor's page ({D}) lists Hobby free, Pro $20/month, Teams $40 per user/month and a custom Enterprise tier; Windsurf's page redirected to devin.ai/pricing on the same date.", 1),
        ("Confirm the current Cursor and Windsurf enterprise terms directly, as offerings evolve.",
         f"Cursor's Enterprise tier (custom pricing) adds pooled usage, SCIM seat management, audit logs and invoice billing on top of Teams, per its pricing page on {D}.", 1),
        ("Usage/credit-based pricing has drawn criticism for unpredictable costs (confirm current plan)",
         f"Usage/credit-based pricing has drawn criticism for unpredictable costs; the flat part is $20/mo (Pro) or $40/user/mo (Teams) as of {D}", 1),
        ("so model your real usage and confirm current limits before subscribing.",
         "so model your real usage against the plan limits dated in this article before subscribing.", 1),
    ],
    "fly-io-vs-railway-which-cloud-platform-should-you-deploy-on": [
        ("Plan details and prices change often, so treat the figures here as a snapshot and confirm the current terms on each site before you commit.",
         "Plan details and prices change often, so every figure here carries its observation date (2026-07-29) and is a snapshot of that day.", 1),
        ("Terms for both can change, so confirm the current limits before you rely on them.",
         f"On {D} Railway's pricing page still listed a Free plan at $0 alongside Hobby ($5/month with $5 of included usage) and Pro ($20/month with $20 included).", 2),   # 본문 + FAQPage JSON-LD
    ],
    "how-to-self-host-nextcloud-a-complete-setup-guide": [
        ("Confirm current requirements in Nextcloud's official documentation for the version you install.",
         "The per-release system requirements are in the Administration Manual linked under Sources.", 1),
        ("Because security requirements change between versions, confirm the current recommendations in the official Administration Manual before you expose the server publicly.",
         "Security recommendations change between releases; the hardening chapter of the Administration Manual (linked under Sources) is the reference this guide follows.", 1),
    ],
    "notion-vs-obsidian-which-note-taking-app-should-you-use-in-2026": [
        ("and confirm the current add-on prices on obsidian.md/pricing.",
         f"as of {D} its pricing page lists Sync at $4 per user/month billed annually ($5 monthly), Publish at $8 per site/month annually ($10 monthly), and a $50 per user/year commercial license.", 1),
        ("so confirm current team features on obsidian.md.",
         f"so for teams Obsidian offers Sync's vault collaboration plus a $50 per user/year commercial license rather than a Notion-style workspace (obsidian.md/pricing, {D}).", 2),   # 본문 + FAQPage JSON-LD
    ],
    "orca-vs-herdr-agent-ide-or-terminal-multiplexer-for-coding-agents": [
        ("Confirm on vendor site; Enterprise option",
         "Not stated on the pages we checked (2026-07-19); an Enterprise option is listed", 1),
        ("Confirm current platform support, licensing, and any paid or Enterprise tiers on each vendor's site before committing, since these projects move quickly.",
         "Platform support, licensing and tiers are as stated on each project's pages on 2026-07-19; both projects move quickly, which is why every observation here is dated.", 1),
        ("Confirm current licensing and any paid tiers on each vendor's site, since details can change.",
         "Licensing and tiers are as observed on 2026-07-19; details can change, so the date matters more than the label.", 2),   # 본문(&#x27;) + FAQPage JSON-LD(')
    ],
    "railway-vs-render-which-cloud-platform-should-you-deploy-on": [
        ("Confirm current pricing on the vendor sites",
         f"As of {D}, Railway lists Hobby at $5/month and Pro at $20/month (each with matching included usage), while Render's workspaces are Hobby $0, "
         "Pro $25/month and Scale $499/month plus compute, with web service instances from $7/month (0.5 CPU, 512 MB) to $85/month (2 CPU, 4 GB); sources:", 1),
    ],
    "the-best-ai-code-review-tools-in-2026-8-options-compared": [
        ("so treat the tiers below as a starting point and confirm current details on each vendor's site;",
         "so every tier below carries the date we checked it, and where a vendor publishes no number we say so;", 1),
        ("And because plans and limits in this category shift often, confirm current pricing and data-handling terms on the vendor's official site.",
         "Plans and limits in this category shift often, which is why each figure in this guide is dated rather than presented as permanent.", 1),
    ],
}

HEDGE_RE = re.compile(r"[Cc]onfirm (?:current|pricing|on |the current|exact|with)")


def _variants(s: str):
    yield s
    if "'" in s:
        yield s.replace("'", "&#x27;")
        yield s.replace("'", "&#39;")


def _heading_before(doc: str, pos: int) -> str:
    m = None
    for m in re.finditer(r"<h[23][^>]*>(.*?)</h[23]>", doc[:pos], flags=re.S):
        pass
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else "(none)"


def apply(slug: str, pairs, *, dry: bool) -> tuple[int, list[str]]:
    path = os.path.join(QUEUE, slug + ".html")
    if not os.path.isfile(path):
        return 0, [f"{slug}: 파일 없음(내려갔거나 서버 큐가 아님) — 건너뜀"]
    doc = open(path, encoding="utf-8").read()
    errors, done, already = [], 0, 0
    for old, new, want in pairs:
        # 같은 문장이 본문(&#x27;)과 FAQPage JSON-LD(') 에 표기만 다르게 두 번 있을 수 있다 → 변형 전부를 세고 전부 바꾼다
        hits = [(v, doc.count(v)) for v in _variants(old)]
        hits = [(v, n) for v, n in hits if n]
        n_total = sum(n for _v, n in hits)
        if not n_total:
            if new in doc or html.escape(new, quote=False) in doc:
                already += 1
                continue
            errors.append(f"{slug}: 앵커 0회 — {old[:80]!r}")
            continue
        if n_total != want:
            errors.append(f"{slug}: 앵커 {n_total}회(기대 {want}) — {old[:80]!r}")
            continue
        for v, n in hits:
            # new 의 아포스트로피 표기는 매치된 변형을 따른다(같은 문장 안에서 표기가 섞이지 않게)
            rep = new if v == old else new.replace("'", v[v.find("&#"):v.find(";") + 1] if "&#" in v else "'")
            if dry:
                print(f"  [{slug[:40]}] §{_heading_before(doc, doc.find(v))!r} ×{n}
     - {v[:110]}
     + {rep[:110]}")
            doc = doc.replace(v, rep)
            done += n
    if errors:
        return 0, errors                          # 한 글이라도 앵커가 어긋나면 그 글은 쓰지 않는다
    if not dry and done:
        open(path, "w", encoding="utf-8", newline="").write(doc)
    return done, [f"{slug}: {done} 치환" + (f" (+{already} 기적용)" if already else "")]


def check() -> int:
    total = 0
    for f in sorted(glob.glob(os.path.join(QUEUE, "*.html"))):
        raw = open(f, encoding="utf-8").read()
        i, j = raw.find("<article"), raw.find("</article>")
        body = raw[i:j] if i >= 0 and j > i else raw
        # 인용 부호 뒤의 언급(예: 가격 지수 글이 그 문구를 "쓰지 않는 이유"로 인용)은 회피가 아니다
        n = sum(1 for m in HEDGE_RE.finditer(body) if body[max(0, m.start() - 1):m.start()] not in ("“", '"'))
        if n:
            print(f"  잔존 {n:2d}  {os.path.basename(f)}")
        total += n
    print(f"잔존 회피 문구 합계: {total}")
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="치환 없이 잔존 회피 문구만 센다")
    a = ap.parse_args(argv)
    if a.check:
        return 1 if check() else 0
    total, failed = 0, 0
    for slug, pairs in PATCHES.items():
        n, msgs = apply(slug, pairs, dry=a.dry_run)
        for m in msgs:
            print(("  " if n or "건너뜀" in m else "  ✗ ") + m)
        total += n
        failed += 0 if (n or any("건너뜀" in m for m in msgs)) else 1
    print(f"{'DRY-RUN ' if a.dry_run else ''}치환 {total}건 · 실패 글 {failed}")
    if not a.dry_run:
        check()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
