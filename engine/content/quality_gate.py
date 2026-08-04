"""quality_gate.py — 프로그래매틱 SEO 발행 전 품질 게이트 (AUTOMATION.md §3).

게이트 없는 대량 발행 = 저품질 색인 제외·AdSense 정지의 1순위 원인.
모든 페이지는 발행 큐 진입 전 여기를 전부 PASS 해야 한다.
config/content.yaml 의 quality_gate 임계값을 따른다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class Page:
    slug: str
    title: str
    html: str
    blocks: list[str]            # 본문 섹션들
    unique_blocks: list[str]     # 템플릿 외 고유 데이터/계산/표
    sources: list[str]
    author: str | None
    published_at: str | None
    updated_at: str | None
    has_schema_org: bool


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)   # 거부 사유

    def fail(self, why: str) -> None:
        self.passed = False
        self.reasons.append(why)


PROHIBITED = ("adult", "weapon", "casino-spam", "copyrighted-dump")
AD_CLICKBAIT = re.compile(r"(click\s+the\s+ad|광고를?\s*클릭)", re.I)


def _shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def jaccard(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


_ABSENCE_MARK = "Not covered on the pages we read"


def lopsided_columns(html_text: str) -> tuple[int, int, int]:
    """비교표의 **제품별** 데이터 칸 중 '확인 못 함' 칸 수. (a 부재, b 부재, 행 수)

    왜 행 전체가 아니라 **열**로 세나(실측 2026-08-04): 9행 중 5행이 한쪽만 비었을 때
    전체 칸 기준으로는 18칸 중 5칸(28%)이라 낮아 보이지만, 독자가 보는 것은
    **한 제품 칸의 56%가 비어 있는 표**다. 비교글의 값은 양쪽이 채워질 때만 생긴다.

    ⚠️ **표별로** 판정하고 가장 나쁜 표를 돌려준다. 페이지의 모든 표를 합치면
       빈 칸 없는 관측표(3행)가 섞여 비율이 희석된다 — 실측: 합산 5/19(26%)로 통과했지만
       독자가 보는 head-to-head 표만 보면 5/9(56%)였다.
    """
    worst = (0, 0, 0)
    for tbl in re.findall(r"<table.*?</table>", html_text, re.S):
        a = b = rows = 0
        for tr in re.findall(r"<tr.*?</tr>", tbl, re.S):
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
            if len(tds) < 3:                     # 항목명 + 제품 2칸 형태만 센다
                continue
            rows += 1
            a += _ABSENCE_MARK in tds[1]
            b += _ABSENCE_MARK in tds[2]
        if rows and max(a, b) / rows > (max(worst[0], worst[1]) / worst[2] if worst[2] else -1):
            worst = (a, b, rows)
    return worst


def check(page: Page, cfg: dict, existing_corpus: list[str]) -> GateResult:
    """페이지를 config 임계값으로 검사. 통과해야 발행 큐로."""
    g = cfg["quality_gate"]
    r = GateResult(passed=True)

    # 0. 한쪽이 비어 있는 비교표 — 비교글인데 비교가 성립하지 않는다.
    #    실측(2026-08-04): 발행된 글의 표 9행 중 5행이 한 제품만 "확인 못 함"이었고,
    #    원인은 소스에 없어서가 아니라 **소스를 24%만 읽어서**였다(source_fetch 참조).
    #    수집을 고쳐도 진짜로 자료가 없는 조합은 남으므로, 그건 발행하지 않고 버린다.
    _lop = (g.get("comparison") or {}).get("max_absent_column_ratio", 0)
    if _lop:
        a, b, rows = lopsided_columns(page.html)
        if rows >= int((g.get("comparison") or {}).get("min_rows_to_judge", 5)):
            worst = max(a, b) / rows
            if worst > float(_lop):
                r.fail(f"comparison: 한쪽 열 공백 과다({max(a, b)}/{rows} = {worst:.0%} "
                       f"> {float(_lop):.0%}) — 비교가 성립하지 않는다")

    # 1. 고유 가치 — 순수 템플릿 치환만이면 거부
    if g["unique_value"]["require_unique_block"] and not page.unique_blocks:
        r.fail("no unique_block: 템플릿 외 고유 데이터/계산/표 없음")

    # 2. 근접 중복
    max_sim = g["near_duplicate"]["max_similarity"]
    body = " ".join(page.blocks)
    if any(jaccard(body, other) > max_sim for other in existing_corpus):
        r.fail(f"near_duplicate > {max_sim}")

    # 3. 구조 — 빈 골격 거부 (단어수 아님, 의도 충족 블록 수)
    if g["structure"]["require_intent_sections"]:
        if len([b for b in page.blocks if b.strip()]) < g["structure"]["min_substantive_blocks"]:
            r.fail("structure: 실질 섹션 부족(빈 골격)")

    # 3.5 실질 산문 최소량 — 표/헤드라인만 있는 thin·auto-generated 페이지는 AdSense 거절 1순위 트리거
    #     (Google answer/81904: "complete sentences and paragraphs, not only headlines" / "little to no
    #     original content"). page.blocks = 태그 제거된 intro+섹션+verdict 산문(비교표는 unique_blocks 별도).
    min_words = g["structure"].get("min_prose_words", 0)
    if min_words:
        prose_words = sum(len(b.split()) for b in page.blocks)
        if prose_words < min_words:
            r.fail(f"structure: 산문 부족({prose_words} < {min_words} words) — 표/헤드라인만은 승인 거절 트리거")

    # 4. E-E-A-T 신호
    e = g["eeat"]
    if e["require_sources"] and not page.sources:
        r.fail("eeat: 출처 없음")
    if e["require_dates"] and not (page.published_at or page.updated_at):
        r.fail("eeat: 작성/갱신일 없음")
    if e["require_author"] and not page.author:
        r.fail("eeat: 저자 없음")
    if e["require_schema_org"] and not page.has_schema_org:
        r.fail("eeat: schema.org 구조화 데이터 없음")

    # 5. 정책 스크리닝
    p = g["policy_screen"]
    text = (page.title + " " + body).lower()
    if p["block_prohibited_topics"] and any(t in text for t in PROHIBITED):
        r.fail("policy: 금지 주제")
    if p["block_ad_clickbait"] and AD_CLICKBAIT.search(text):
        r.fail("policy: 광고 클릭 유도 문구")

    return r


# 6. 휴먼 샘플 게이트는 publisher 단계에서 sample_pct 만큼 승인 큐로 분기.
