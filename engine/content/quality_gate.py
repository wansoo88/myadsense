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


def check(page: Page, cfg: dict, existing_corpus: list[str]) -> GateResult:
    """페이지를 config 임계값으로 검사. 통과해야 발행 큐로."""
    g = cfg["quality_gate"]
    r = GateResult(passed=True)

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
