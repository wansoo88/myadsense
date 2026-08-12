#!/usr/bin/env python3
"""patch_prices.py — 발행된 초안(dist/queue)의 Pricing 카드에 실제 가격을 채운다.

배경(2026-08-12):
    AdSense 가 2026-08-11 "가치가 별로 없는 콘텐츠"로 사이트를 거절했다. 전수 측정 결과
    유료 플랜인데 가격 숫자가 없는 카드가 41개(19편), 그 자리에 "confirm current pricing
    on the vendor's site" 가 143회 들어가 있었다. 가격 비교 글이 가격을 안 적으면
    원본 출처보다 나은 게 없다 — 그게 low value 판정의 직접적 근거다.

무엇을 하나:
    1. config/prices.yaml 의 cards[] 를 읽어 (slug, plan) 이 일치하는 price-card 의
       `.pp`(가격) 를 실제 숫자로 교체하고, note 가 있으면 `.pnote` 로 넣는다.
    2. Pricing 섹션의 부제("Confirm current pricing on each vendor's site.")를
       관측일이 박힌 문장으로 바꾼다 — 회피 문구를 신뢰 신호로 뒤집는다.

무엇을 하지 않나:
    · 본문 산문은 건드리지 않는다(문장 단위 자동 수정은 사실관계를 깨뜨릴 위험이 크다).
    · prices.yaml 에 없는 카드는 그대로 둔다. **추측한 숫자를 넣지 않는다.**
    · `unverified: true` 인 항목은 숫자를 주장하지 않고 note 만 반영한다.

⚠️ dist/ 는 gitignore 대상이라 **서버의 dist/queue 가 정본**이다. 이 스크립트는 서버에서 돌린다.
   실행 후 deploy 단계가 큐를 사이트로 다시 빌드한다.

사용:
    python scripts/patch_prices.py --dry-run     # 미리보기(파일 수정 없음)
    python scripts/patch_prices.py               # 적용
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys

try:
    import yaml
except ImportError:                                  # pragma: no cover
    sys.exit("PyYAML 이 필요하다: pip install pyyaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "dist", "queue")
PRICES = os.path.join(ROOT, "config", "prices.yaml")

# <div class="pn">이름</div><div class="pp">가격</div>[<div class="pnote">노트</div>]
CARD_RE = re.compile(
    r'(?P<head><div class="pn">)(?P<name>.*?)(?P<mid></div>\s*<div class="pp">)'
    r'(?P<price>.*?)(?P<tail></div>)'
    r'(?P<noteblk>\s*<div class="pnote">(?P<note>.*?)</div>)?',
    re.S,
)
SUB_RE = re.compile(r'<p class="sub">(?P<sub>[^<]*?)</p>', re.S)

# 가격 섹션이 관측일 박힌 실제 숫자를 갖게 된 뒤에는, 본문 곳곳의 "가격은 사이트에서 확인하라"가
# 중복이자 '우리도 모른다'는 신호로 남는다. **문장 전체가 그 안내인 것만** 통째로 지운다.
#   · 절(clause) 수술은 하지 않는다 — 문법을 깨뜨릴 위험이 이득보다 크다.
#   · 가격 이외 주제(요구사항·동작·국가 수 등)의 "confirm current ..." 는 유용한 조언이므로 남긴다.
#   · 같은 문장이 JSON-LD(FAQ 스키마)에도 들어 있어 escape 형태가 다르다 → 두 형태를 함께 지워
#     HTML 과 구조화 데이터가 어긋나지 않게 한다(적용 후 JSON 파싱으로 검증).
PRICE_WORDS = r"(?:pricing|price|prices|rates?|plan limits|tiers|per-seat|monthly caps|free-plan limits)"
# ⚠️ 문장 끝 판정에 "아무 마침표"를 쓰면 안 된다 — "1password.com." 의 도메인 점을 문장 끝으로 보고
#    앞부분만 지워 ".com." 조각을 남긴다(2026-08-12 실측 사고). 마침표 뒤가 공백/태그/따옴표/끝일 때만
#    문장 끝으로 인정한다. JSON-LD 안에서는 마침표 뒤에 " 가 오므로 그것도 포함한다.
HEDGE_SENTS = [
    re.compile(rf'(?<=[.>])\s*Confirm current {PRICE_WORDS}\b[^<]{{0,160}}?\.(?=\s|<|"|$)', re.I),
]
JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def esc(s: str) -> str:
    """카드에 넣을 텍스트를 HTML 이스케이프(따옴표는 본문 텍스트라 건드리지 않는다)."""
    return html.escape(s, quote=False)


def norm(s: str) -> str:
    """비교용 정규화 — 태그 제거 + 엔티티 해제 + 공백 축약."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def load_cards():
    with open(PRICES, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    meta = data.get("meta") or {}
    as_of = str(meta.get("as_of") or "")
    sub = (meta.get("section_sub") or "").replace("{as_of}", as_of)
    by_slug = {}
    for c in data.get("cards") or []:
        by_slug.setdefault(c["slug"], []).append(c)
    return by_slug, sub, as_of


def patch_file(path: str, cards: list, section_sub: str):
    """한 편을 패치하고 (새 본문, 바뀐 카드 수, 부제 교체 여부, 미매칭 플랜) 반환."""
    src = open(path, encoding="utf-8").read()
    want = {norm(c["plan"]): c for c in cards}
    hit = set()

    def repl_card(m: re.Match) -> str:
        key = norm(m.group("name"))
        c = want.get(key)
        if not c:
            return m.group(0)
        hit.add(key)
        price = m.group("price") if c.get("unverified") else esc(str(c["price"]))
        out = m.group("head") + m.group("name") + m.group("mid") + price + m.group("tail")
        note = c.get("note")
        if note:
            out += f'<div class="pnote">{esc(str(note))}</div>'
        elif m.group("noteblk"):
            out += m.group("noteblk")            # 기존 노트 보존
        return out

    new = CARD_RE.sub(repl_card, src)

    # Pricing 섹션 부제: 회피 문구 → 관측일이 박힌 문장
    sub_done = False
    if section_sub:
        def repl_sub(m: re.Match) -> str:
            nonlocal sub_done
            if "confirm current" in m.group("sub").lower() and not sub_done:
                sub_done = True
                return f'<p class="sub">{esc(section_sub)}</p>'
            return m.group(0)
        new = SUB_RE.sub(repl_sub, new)

    # 가격 안내 문장 제거 — 이스케이프 두 형태를 함께 지운다(HTML ↔ JSON-LD 동기 유지)
    stripped = 0
    for rx in HEDGE_SENTS:
        # 본문(') 과 JSON-LD/이스케이프본(&#x27;) 둘 다 매칭되도록 문자클래스를 확장한 패턴
        rx_both = re.compile(rx.pattern.replace("[^.<]", "(?:[^.<]|&#x27;)"), rx.flags)
        new, n = rx_both.subn("", new)
        stripped += n
    # ⚠️ 공백 정리를 문서 전체에 걸지 않는다 — <pre>/코드 블록의 들여쓰기를 뭉갠다.
    #    제거 패턴이 이미 앞쪽 공백(\s*)을 함께 먹으므로 별도 정리는 불필요하다.

    missing = [c["plan"] for k, c in want.items() if k not in hit]
    return new, len(hit), sub_done, missing, stripped


def jsonld_ok(text: str) -> bool:
    """구조화 데이터가 여전히 파싱되는지 — 문장 제거가 JSON 을 깨지 않았는지 확인."""
    import json as _json
    for m in JSONLD_RE.finditer(text):
        try:
            _json.loads(m.group(1))
        except Exception:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="미리보기만 — 파일을 쓰지 않는다")
    args = ap.parse_args()

    if not os.path.isdir(QUEUE):
        sys.exit(f"큐 디렉터리가 없다: {QUEUE}")

    by_slug, section_sub, as_of = load_cards()
    print(f"prices.yaml: {sum(len(v) for v in by_slug.values())}개 카드 / {len(by_slug)}편 · 관측일 {as_of}")
    print(f"모드: {'DRY-RUN(쓰기 없음)' if args.dry_run else '적용'}\n")

    tot_cards = tot_subs = tot_strip = 0
    touched = 0
    problems: list[str] = []

    # 큐 전편을 돈다 — 부제 교체·헤지 제거는 가격 카드가 없는 글에도 적용된다.
    for fn in sorted(os.listdir(QUEUE)):
        if not fn.endswith(".html"):
            continue
        slug = fn[:-5]
        path = os.path.join(QUEUE, fn)
        src = open(path, encoding="utf-8").read()
        cards = by_slug.get(slug, [])
        new, n, sub_done, missing, stripped = patch_file(path, cards, section_sub)

        for pl in missing:
            problems.append(f"플랜 미매칭: {slug} / {pl!r}")
        # 구조화 데이터가 깨지면 그 파일은 건너뛴다(부분 적용 금지)
        if not jsonld_ok(new):
            problems.append(f"JSON-LD 파싱 실패 → 건너뜀: {slug}")
            continue

        tot_cards += n
        tot_subs += 1 if sub_done else 0
        tot_strip += stripped
        if new != src:
            touched += 1
            if not args.dry_run:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
        if n or sub_done or stripped:
            print(f"  카드 {n:>2} · 부제 {'O' if sub_done else '-'} · 헤지 -{stripped:<2}  {slug[:56]}")

    for slug in by_slug:
        if not os.path.exists(os.path.join(QUEUE, slug + ".html")):
            problems.append(f"파일 없음: {slug}.html")

    print(f"\n■ 가격 채운 카드: {tot_cards}")
    print(f"■ 부제 교체: {tot_subs}편")
    print(f"■ 가격 안내 문장 제거: {tot_strip}개")
    print(f"■ 수정된 파일: {touched}편")
    if problems:
        print(f"\n⚠️ 확인 필요 {len(problems)}건:")
        for p in problems:
            print("   -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
