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
import datetime
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


def _guess_cluster(query: str, topics: dict) -> tuple[str | None, int]:
    """트렌드 후보를 기존 클러스터 어휘와의 겹침으로 배정(카테고리 허브 그룹핑 유지 목적).
    겹침이 전혀 없으면 최우선순위(P1) 클러스터로 폴백."""
    q_words = set(re.findall(r"[a-z0-9]+", query.lower()))
    best_id, best_prio, best_overlap = None, 3, 0
    fallback_id, fallback_prio = None, 99
    for c in topics.get("clusters", []):
        prio = c.get("priority", 3)
        if fallback_id is None or prio < fallback_prio:
            fallback_id, fallback_prio = c["id"], prio
        vocab = set(re.findall(r"[a-z0-9]+", (c.get("hub", "") + " " + " ".join(c.get("seeds", []))).lower()))
        overlap = len(q_words & vocab)
        if overlap > best_overlap:
            best_id, best_prio, best_overlap = c["id"], prio, overlap
    return (best_id, best_prio) if best_id else (fallback_id, fallback_prio)


def _days_before(date_str: str, days: int) -> str:
    return (datetime.date.fromisoformat(date_str) - datetime.timedelta(days=days)).isoformat()


def find_rising_queries(db, known_keywords: list, *, min_impressions: int = 15,
                         lookback_days: int = 7) -> list:
    """자체 Search Console 데이터에서 '아직 시드에 없는' 떠오르는 검색어를 탐지(외부 트렌드 API 불필요).
    이번 스냅샷 대비 lookback_days 전 스냅샷과 비교 — 신규 등장(is_new) 또는 노출 급증을 잡는다.
    자격증명 미설정·스냅샷 1일치뿐이면 안전하게 빈 리스트(no-op) — GOOGLE_OAUTH_* 발급 후 자동 활성화."""
    if db is None:
        return []
    try:
        dates = [r[0] for r in db.query(
            "SELECT DISTINCT date FROM metrics WHERE source='search_console' AND dimension='query' "
            "AND metric='impressions' ORDER BY date DESC LIMIT 60")]
    except Exception:
        return []
    if not dates:
        return []
    latest = dates[0]
    cutoff = _days_before(latest, lookback_days)
    prior = next((d for d in dates[1:] if d <= cutoff), None)

    def _snapshot(date):
        rows = db.query(
            "SELECT dim_value, value FROM metrics WHERE source='search_console' AND dimension='query' "
            "AND metric='impressions' AND date=?", (date,))
        return {r[0]: r[1] for r in rows}

    now_map = _snapshot(latest)
    prior_map = _snapshot(prior) if prior else {}
    known_lower = [k.lower() for k in known_keywords]
    out = []
    for q, impr in now_map.items():
        if impr < min_impressions:
            continue
        ql = q.lower()
        if any(k in ql or ql in k for k in known_lower):
            continue                                   # 이미 시드로 다루는 주제 — 신규 아님
        before = prior_map.get(q, 0)
        out.append({
            "keyword": q, "impressions": round(impr),
            "growth_pct": None if before == 0 else round((impr - before) / before * 100, 1),
            "is_new": before == 0,
        })
    out.sort(key=lambda e: -e["impressions"])
    return out


def run(topics: dict, niches: dict, db=None) -> list:
    """시드 전체를 스코어링 + (SC 데이터 있으면) 신규 트렌드 후보를 병합해 순위 내림차순 백로그 반환."""
    w = (niches.get("scoring", {}) or {}).get("weights", {}) or {}
    out = []
    known = []
    for c in topics.get("clusters", []):
        known.extend(c.get("seeds", []))
        prio = c.get("priority", 3)
        for kw in c.get("seeds", []):
            sc = _sc_impressions(db, kw) if db is not None else 0
            score, intent, comp = score_seed(kw, prio, sc, w)
            out.append({
                "keyword": kw, "cluster": c["id"], "priority": prio, "intent": intent,
                "competition": round(comp, 2), "sc_impressions": sc, "score": round(score, 4),
                "source": "seed",
            })
    for e in find_rising_queries(db, known):            # 자격증명·데이터 없으면 빈 리스트(no-op)
        cid, prio = _guess_cluster(e["keyword"], topics)
        # 검증 안 된 신규 후보라 상한 있는 보수적 점수 — 기존 코너스톤 시드를 밀어내지 않도록.
        score = 0.4 + min(0.35, e["impressions"] / 200.0)
        out.append({
            "keyword": e["keyword"], "cluster": cid, "priority": prio, "intent": classify_intent(e["keyword"]),
            "competition": None, "sc_impressions": e["impressions"], "score": round(score, 4),
            "source": "sc_trend", "is_new": e["is_new"], "growth_pct": e["growth_pct"],
        })
    out.sort(key=lambda x: -x["score"])
    return out
