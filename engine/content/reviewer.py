"""reviewer.py — 발행 전 콘텐츠 검수 게이트 (사용자 방침: 항상 리뷰 스킬로 QC).

.claude/skills/adsense-review 루브릭 자동화: AI 티·사실/맥락·법적(허위 1인칭 경험·명예훼손·
과장 단정·상표·YMYL)·AdSense 정책·논리 일관성. provider(claude_cli/api)로 비평 → JSON 판정.
high(법적·허위·정책) → REJECT. 통과분만 발행 큐로.
"""
from __future__ import annotations
import re

from content import generator

_SYSTEM = (
    "You are a strict editorial AND legal reviewer for an independent software-comparison site. "
    "Catch: (1) AI-tells/cliches and unnatural filler — flag on sight if present (case-insensitive): "
    "\"in today's fast-paced world\", \"whether you're X or Y\", \"it's worth noting\", \"look no further\", "
    "\"delve\", \"elevate\", \"robust\", \"seamless\", \"game-changer\", plus any other unnatural filler/cliche "
    "even if not in this list, and all-paragraphs-same-rhythm writing; (2) factual or contextual errors and internal "
    "contradictions (table vs prose vs verdict), and unhedged volatile specifics (exact prices/benchmarks) "
    "stated as fact; (3) LEGAL risk — especially FALSE first-person experience claims (e.g. 'after working "
    "with both', 'I tested for 8 weeks', 'a joy to use') when the text was AI-generated without real testing; "
    "defamation/unverified negative claims about products; absolute superlatives ('best/cheapest/#1') stated "
    "as fact; trademark misuse; copyright; YMYL overreach; missing affiliate/ad disclosure; "
    "(4) AdSense policy (prohibited topics, deceptive, ad-clickbait); (5) coherence/usefulness. "
    "Be conservative: when in doubt, fail."
)


def _flatten(spec) -> str:
    def strip(h):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h or "")).strip()
    parts = [f"TITLE: {spec.title}", f"DEK: {spec.dek}", f"TLDR: {strip(spec.tldr_html)}",
             f"INTRO: {strip(spec.intro_html)}"]
    for s in spec.sections:
        parts.append(f"## {s['heading']}\n{strip(s['html'])}")
    parts.append(f"VERDICT: {strip(spec.verdict_html)}")
    parts.append("SOURCES: " + "; ".join(s.get("url", "") for s in (spec.sources or [])))
    return "\n\n".join(parts)[:12000]


def review(spec, content_cfg: dict) -> dict:
    """검수 → {passed, severity, ai_tells, issues:[{type,detail,fix}], notes}.

    먼저 블록리스트를 정규식으로 스캔(generator.scan_ai_cliches) — 확정 위반이면
    LLM 호출 없이 즉시 반려(비용 절감). 없으면 전체 루브릭으로 LLM 검수.
    """
    flat = _flatten(spec)
    hits = generator.scan_ai_cliches(flat)
    if hits:
        return {
            "passed": False, "severity": "medium", "ai_tells": hits,
            "issues": [{"type": "ai_tone", "detail": f"banned cliché phrase(s) found: {', '.join(hits)}",
                        "fix": "rewrite the affected sentence(s) without these words/phrases"}],
            "notes": "규칙 기반 사전 필터에서 확정 검출 — LLM 미호출",
        }
    user = (
        "Review this article draft against the rubric and return ONLY JSON "
        '{"passed":bool,"severity":"none|low|medium|high","ai_tells":[str],'
        '"issues":[{"type":"factual|legal|policy|coherence|ai_tone","detail":str,"fix":str}],"notes":str}. '
        "passed=false if any high-severity legal/factual/policy issue (esp. false first-person testing claims).\n\n"
        + flat)
    raw = generator.complete_text(_SYSTEM, user, content_cfg, max_tokens=4000)
    data = generator._extract_json(raw)
    data.setdefault("passed", False)
    data.setdefault("severity", "unknown")
    data.setdefault("issues", [])
    data.setdefault("ai_tells", [])
    return data
