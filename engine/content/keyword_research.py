"""keyword_research.py — 시드 키워드 스코어링 (AUTOMATION.md §2 RESEARCH).

config/niches.yaml 의 scoring.weights 로 topics.yaml 시드를 점수화:
  score = niche_match·w1 + intent_value·w2 + geo_tier·w3 + competition·w4(음수)
- niche_match: 클러스터 우선순위(P1>P2>P3) — 고CPC 니치 적합도 프록시(F6)
- intent_value: 비교 > 거래 > 정보 (단가=의도, F7)
- geo_tier: 영어 Tier-1 타깃 전략(F5) → 상수 1.0
- competition: 키워드 휴리스틱(head term 높음, long-tail 낮음) — 가중치 음수라 패널티
있으면 Search Console 실수요(impressions)로 소폭 보정. 순위 내림차순 백로그 반환.
"""
from __future__ import annotations
import re

NICHE_BY_PRIO = {1: 1.0, 2: 0.66, 3: 0.33}
INTENT_VAL = {"comparison": 1.0, "transactional": 0.9, "informational": 0.5}


def classify_intent(kw: str) -> str:
    k = kw.lower()
    if re.search(r"\bvs\.?\b", k):
        return "comparison"
    if re.search(r"\b(best|alternatives?|pricing|price|worth it|review|cheap|top)\b", k):
        return "transactional"
    return "informational"


def estimate_competition(kw: str) -> float:
    """0..1 (1=경쟁 치열). head term 높음, long-tail 낮음."""
    k = kw.lower()
    base = 0.8 if re.search(r"\bbest\b", k) else (0.5 if re.search(r"\bvs\b", k) else 0.6)
    base -= max(0, len(kw.split()) - 3) * 0.08      # long-tail 일수록 경쟁↓
    return max(0.2, min(0.9, base))


def _sc_impressions(db, kw: str) -> int:
    try:
        rows = db.query(
            "SELECT SUM(value) FROM metrics WHERE source='search_console' AND metric='impressions' "
            "AND lower(dim_value) LIKE ?", (f"%{kw.lower()}%",))
        return int(rows[0][0]) if rows and rows[0][0] else 0
    except Exception:
        return 0


def score_seed(kw: str, priority: int, sc_impr: int, w: dict):
    niche = NICHE_BY_PRIO.get(priority, 0.33)
    intent = classify_intent(kw)
    comp = estimate_competition(kw)
    score = (niche * w.get("niche_match", 0.35)
             + INTENT_VAL[intent] * w.get("intent_value", 0.30)
             + 1.0 * w.get("geo_tier", 0.20)                 # 영어 Tier-1 상수
             + comp * w.get("competition", -0.15))
    if sc_impr:                                              # 실수요 보너스(최대 +0.1)
        score += min(0.1, sc_impr / 10000.0 * 0.1)
    return score, intent, comp


def run(topics: dict, niches: dict, db=None) -> list:
    """시드 전체를 스코어링해 순위 내림차순 백로그(list[dict]) 반환."""
    w = (niches.get("scoring", {}) or {}).get("weights", {}) or {}
    out = []
    for c in topics.get("clusters", []):
        prio = c.get("priority", 3)
        for kw in c.get("seeds", []):
            sc = _sc_impressions(db, kw) if db is not None else 0
            score, intent, comp = score_seed(kw, prio, sc, w)
            out.append({
                "keyword": kw, "cluster": c["id"], "priority": prio, "intent": intent,
                "competition": round(comp, 2), "sc_impressions": sc, "score": round(score, 4),
            })
    out.sort(key=lambda x: -x["score"])
    return out
