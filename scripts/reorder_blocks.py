#!/usr/bin/env python3
"""dist/queue/*.html 의 본문 블록 순서를 글 유형에 맞게 재배치한다 (재실행 가능).

왜 필요한가 — 2026-08-11 AdSense "가치가 별로 없는 콘텐츠" 거절 대응.
발행분 전부가 `summary > comparison > features > pricing > proscons` 라는
**동일한 4개 자동생성 블록**으로 시작한 뒤에야 산문이 나왔다. 독자가 처음 보는
화면이 24편 모두 같았고, how-to 가이드와 "best N" 목록글까지 비교표 골격을
그대로 입고 있었다(가이드에 head-to-head 표가 먼저 나온다).

generator 는 page_type 별로 다른 순서를 낼 수 있지만(renderer._ORDERS),
이미 렌더된 큐 HTML 에는 spec 이 남아있지 않아 재렌더가 불가능하다.
그래서 렌더 결과물에서 블록을 직접 옮긴다. 산문 블록의 상대 순서는 건드리지 않는다.

한계(정직하게): 이건 **읽는 순서**를 고치는 것이지 정보를 더하는 게 아니다.
head-to-head 24편이 서로 다른 골격을 갖게 되지도 않는다 — 같은 종류의 글이니
같은 순서인 게 맞다. 실질 가치는 B(시각자료)·D(1차 데이터)가 담당한다.

사용:
    python scripts/reorder_blocks.py            # dist/queue 전체
    python scripts/reorder_blocks.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "dist", "queue")

BLK_OPEN = '<section class="blk" id="'
# 본문 블록 뒤에 오는 고정 꼬리들 — 여기서부터는 건드리지 않는다.
TAIL_MARKERS = ('<section class="sources"', '<section class="related"')

# 생성기가 만드는 정형 블록. 이 밖의 id 는 전부 "산문"으로 본다.
GENERATED = {"summary", "comparison", "features", "pricing", "proscons", "verdict", "faq"}

ANCHOR_RE = re.compile(r'<a href="#(?P<id>[^"]+)">.*?</a>', re.S)


def classify(slug: str) -> str:
    """슬러그로 글 유형을 판정한다. 제목이 곧 약속이므로 슬러그가 가장 정직한 신호다."""
    if slug.startswith("how-to-"):
        return "guide"
    if slug.startswith("best-") or slug.startswith("the-best-") or "-best-" in slug:
        return "listicle"
    return "comparison"


def plan(kind: str, ids: list[str]) -> list[str]:
    """현재 블록 id 목록 → 새 순서. 없는 블록은 알아서 빠진다."""
    prose = [i for i in ids if i not in GENERATED]
    have = set(ids)

    def g(name: str) -> list[str]:
        return [name] if name in have else []

    if kind == "guide":
        # 가이드는 "무엇이 필요한가"부터 읽어야 한다. 가격은 첫 산문 직후 —
        # 자체 호스팅 글의 첫 문단은 대개 "직접 vs 관리형" 판단이라 가격이 붙어야 산다.
        head = prose[:1]
        rest = prose[1:]
        order = g("summary") + head + g("pricing") + rest + g("proscons")
    elif kind == "listicle":
        # 목록글은 "무엇을 볼 것인가" → 비교표 → 각 후보 → 가격 순이 자연스럽다.
        head = prose[:1]
        rest = prose[1:]
        order = g("summary") + head + g("features") + rest + g("pricing") + g("proscons")
    else:
        # 비교글: 요약 → 정면 비교 → 산문 2개 → 기능표 → 나머지 산문 → 가격 → 장단점.
        # 표가 산문 사이에 끼면서 "표 4개 먼저, 글은 나중" 인상이 사라진다.
        head = prose[:2]
        rest = prose[2:]
        order = (g("summary") + g("comparison") + head + g("features")
                 + rest + g("pricing") + g("proscons"))

    order += g("verdict") + g("faq")

    # 안전망: 계획에서 누락된 블록이 있으면 원래 자리 순서대로 뒤에 붙인다(정보 손실 0).
    missing = [i for i in ids if i not in order]
    return order + missing


def split_blocks(text: str) -> tuple[int, int, list[tuple[str, str]]] | None:
    """(본문 시작, 본문 끝, [(id, html)…]) 을 돌려준다. 구조가 예상과 다르면 None."""
    start = text.find(BLK_OPEN)
    if start < 0:
        return None
    end = len(text)
    for mark in TAIL_MARKERS:
        pos = text.find(mark, start)
        if 0 <= pos < end:
            end = pos
    span = text[start:end]

    cuts = [m.start() for m in re.finditer(re.escape(BLK_OPEN), span)]
    blocks: list[tuple[str, str]] = []
    for n, c in enumerate(cuts):
        stop = cuts[n + 1] if n + 1 < len(cuts) else len(span)
        chunk = span[c:stop]
        m = re.match(r'<section class="blk" id="([^"]+)"', chunk)
        if not m:
            return None
        # 균형 검사 — 열고 닫은 <section> 수가 다르면 자르는 위치가 틀린 것이다.
        if chunk.count("<section") != chunk.count("</section>"):
            return None
        blocks.append((m.group(1), chunk))
    return (start, end, blocks) if blocks else None


def reorder_toc(text: str, order: list[str], known: set[str]) -> str:
    """TOC 앵커도 같은 순서로 맞춘다. known 에 없는 앵커(#overview·#sources)는 제자리 유지."""
    anchors = list(ANCHOR_RE.finditer(text))
    if not anchors:
        return text
    seq = [a for a in anchors if a.group("id") in known]
    if not seq:
        return text

    by_id = {a.group("id"): a.group(0) for a in seq}
    new_html = [by_id[i] for i in order if i in by_id]
    if len(new_html) != len(seq):
        return text  # 앵커와 섹션이 1:1 이 아니면 손대지 않는다

    out, prev, k = [], 0, 0
    for a in seq:
        out.append(text[prev:a.start()])
        out.append(new_html[k])
        k += 1
        prev = a.end()
    out.append(text[prev:])
    return "".join(out)


def process(path: str, dry: bool) -> str:
    slug = os.path.splitext(os.path.basename(path))[0]
    text = open(path, encoding="utf-8").read()
    parsed = split_blocks(text)
    if not parsed:
        return f"skip   {slug}  (블록 구조를 못 읽음)"

    start, end, blocks = parsed
    ids = [i for i, _ in blocks]
    kind = classify(slug)
    order = plan(kind, ids)
    if order == ids:
        return f"same   {slug}  [{kind}]"

    body = {i: h for i, h in blocks}
    new_text = text[:start] + "".join(body[i] for i in order) + text[end:]
    new_text = reorder_toc(new_text, order, set(ids))

    # 손실 검사: 길이가 변하면 안 된다(순서만 바꿨으므로).
    if len(new_text) != len(text):
        return f"ABORT  {slug}  (길이 변화 {len(text)}→{len(new_text)} — 적용 안 함)"

    if not dry:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
    return f"moved  {slug}  [{kind}]  {' > '.join(ids)}\n              →  {' > '.join(order)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--queue", default=QUEUE)
    a = ap.parse_args()

    files = sorted(f for f in os.listdir(a.queue) if f.endswith(".html"))
    if not files:
        print(f"큐가 비었다: {a.queue}")
        return 1
    changed = 0
    for f in files:
        line = process(os.path.join(a.queue, f), a.dry_run)
        if line.startswith("moved"):
            changed += 1
        print(line)
    print(f"\n{changed}/{len(files)} 편 재배치{' (dry-run)' if a.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
