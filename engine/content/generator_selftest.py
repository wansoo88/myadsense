"""generator_selftest.py — 생성기 측 회귀 셀프테스트 (CONTENT 소관).

⚠️ 소관 분리 (51-review §4-(i)): 이 파일은 **생성기 로직**만 고정한다.
   `reviewer_selftest.py`(REVIEW 소관)에 CONTENT 로직을 넣지 않는다.

현재 고정 대상: **미페치 인용 가드**(51-review R0~R4)
    R0  인용 목록은 "우리가 읽은 페이지"의 부분집합 — 누가 적었는지와 무관
    R1  동일 페이지 판정에 프래그먼트 제거(쿼리는 유지) → 오탈락 방지
    R2  미페치 모델 인용은 제거. **사후 페치 성공을 자격으로 인정하지 않는다**
    R3  '인용 0건이면 아무거나 하나 붙인다' 폴백 삭제 → require_sources 가 반려
    R4  관측 API 호출분은 "읽은 페이지" 집합에 포함(자체 측정 인용은 잘리면 안 된다)

    python engine/content/generator_selftest.py
"""
from __future__ import annotations

import os
import sys

_ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from content import generator                      # noqa: E402
from content.generator import ContentSpec, _finalize_sources, _norm_url  # noqa: E402

FAILS: list = []


def ck(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" :: {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


CFG = {"grounding": {"enabled": True, "validate_source_urls": False, "fetch_timeout": 5}}


def spec_with(sources, observed=None, prose="Body text mentioning 42 percent and Widget Pro X9."):
    return ContentSpec(
        slug="t", title="T", dek="d", page_type="comparison",
        breadcrumb=[("Home", "/")], author="The stack. editors",
        published_at="2026-08-01", updated_at="2026-08-01",
        intro_html=f"<p>{prose}</p>", sections=[{"heading": "S", "html": f"<p>{prose}</p>"}],
        sources=list(sources), observed=observed)


def grounding_for(urls, text="Body text mentioning 42 percent and Widget Pro X9."):
    return "\n\n".join(f"[SOURCE {i + 1}] {u}\n{text}" for i, u in enumerate(urls))


FETCHED = ["https://smtg-ai.github.io/claude-squad/",
           "https://github.com/smtg-ai/claude-squad#readme"]
GROUND = grounding_for(FETCHED)

print("\n[R1/(a)] 프래그먼트만 다른 모델 인용 → 유지 (오탈락 0)")
s = spec_with([{"title": "cs", "url": "https://github.com/smtg-ai/claude-squad"}])
_finalize_sources(s, CFG, FETCHED, GROUND)
ck("run8 실물 케이스가 살아남는다", any("claude-squad" in x["url"] for x in s.sources),
   f"{[x['url'] for x in s.sources]}")

print("\n[R2/(b)] 미페치 모델 인용 → 제거")
s = spec_with([{"title": "rel", "url": "https://github.com/smtg-ai/claude-squad/releases"},
               {"title": "cs", "url": "https://smtg-ai.github.io/claude-squad/"}])
_finalize_sources(s, CFG, FETCHED, GROUND)
urls = [x["url"] for x in s.sources]
ck("미페치 /releases 가 제거된다", not any("/releases" in u for u in urls), str(urls))
ck("페치된 인용은 남는다", any("claude-squad/" in u for u in urls), str(urls))

print("\n[R2/(b')] 미페치 URL 이 '사후 페치하면 200' 이어도 → 여전히 제거 (완화 분기점)")
s = spec_with([{"title": "live", "url": "https://example.com/"}])   # 실재하는 살아있는 페이지
_finalize_sources(s, CFG, FETCHED, GROUND)
ck("살아있어도 안 읽었으면 제거", not s.sources, str([x["url"] for x in s.sources]))

print("\n[R4/(f)] 관측 API 호출분은 읽은 페이지 집합에 포함 → 자체 측정 인용 유지")
obs = {"calls": [{"url": "https://api.github.com/repos/smtg-ai/claude-squad/releases?per_page=15",
                  "status": 200}]}
s = spec_with([{"title": "api", "url": "https://api.github.com/repos/smtg-ai/claude-squad/releases?per_page=15"}],
              observed=obs)
_finalize_sources(s, CFG, [], "")
ck("관측 엔드포인트 인용이 잘리지 않는다", len(s.sources) == 1, str([x["url"] for x in s.sources]))

print("\n[R4] 관측 호출이 200 이 아니면 읽은 것으로 치지 않는다")
obs_bad = {"calls": [{"url": "https://api.github.com/repos/a/b", "status": 403}]}
s = spec_with([{"title": "api", "url": "https://api.github.com/repos/a/b"}], observed=obs_bad)
_finalize_sources(s, CFG, [], "")
ck("403 호출은 자격 없음", not s.sources, str([x["url"] for x in s.sources]))

print("\n[(c)] 페치했고 본문이 쓴 소스 → 추가 (기존 _source_used_in 동작 보존)")
s = spec_with([])
_finalize_sources(s, CFG, ["https://vendor.example/pricing"],
                  grounding_for(["https://vendor.example/pricing"],
                                "Plan costs 42 percent less on Widget Pro X9."))
ck("본문 근거가 있으면 인용에 추가된다", len(s.sources) == 1, str([x["url"] for x in s.sources]))

print("\n[(d)] 페치했으나 본문 미사용 → 제외 (기존 동작 보존)")
s = spec_with([])
_finalize_sources(s, CFG, ["https://vendor.example/unrelated"],
                  grounding_for(["https://vendor.example/unrelated"],
                                "Totally unrelated content about zebras and 9999 balloons."))
ck("근거 없으면 추가하지 않는다", not s.sources, str([x["url"] for x in s.sources]))

print("\n[R3/(e)] 전부 제거되어 sources=0 → 폴백 없이 0건 유지 → require_sources 가 반려")
s = spec_with([{"title": "x", "url": "https://never-fetched.example/"}])
_finalize_sources(s, CFG, FETCHED, grounding_for(FETCHED, "Unrelated zebras 9999."))
ck("폴백이 임의 인용을 붙이지 않는다", not s.sources, str([x["url"] for x in s.sources]))
from content.quality_gate import Page, check                      # noqa: E402
qcfg = {"quality_gate": {"unique_value": {"require_unique_block": True},
                         "near_duplicate": {"max_similarity": 0.7},
                         "structure": {"require_intent_sections": True, "min_substantive_blocks": 1,
                                       "min_prose_words": 0},
                         "eeat": {"require_sources": True, "require_dates": True,
                                  "require_author": True, "require_schema_org": True},
                         "policy_screen": {"block_prohibited_topics": True, "block_ad_clickbait": True,
                                           "block_copyright_risk": True}}}
pg = Page(slug="t", title="T", html="<html></html>", blocks=["b"], unique_blocks=["comparison-table"],
          sources=[], author="The stack. editors", published_at="2026-08-01",
          updated_at="2026-08-01", has_schema_org=True)
r = check(pg, qcfg, existing_corpus=[])
ck("인용 0건은 게이트에서 실제로 반려된다",
   not r.passed and any(("출처" in x) or ("source" in x.lower()) for x in r.reasons),
   "; ".join(r.reasons))

print("\n[(g)] 멱등성 — 같은 spec 을 연속 3회 처리해도 결과 동일")
s = spec_with([{"title": "cs", "url": "https://github.com/smtg-ai/claude-squad"},
               {"title": "rel", "url": "https://github.com/smtg-ai/claude-squad/releases"}])
seen = []
for _ in range(3):
    _finalize_sources(s, CFG, FETCHED, GROUND)
    seen.append(tuple(sorted(x["url"] for x in s.sources)))
ck("3회 연속 결과 동일", len(set(seen)) == 1, str(seen[0]))

print("\n[(j)] 완화 아님 — 새 규칙 생존분이 기존 규칙에서 못 살아남았을 경우 0건")
# 기존 규칙 = 모델 인용은 무조건 유지(url_ok 만). 즉 기존 생존집합 ⊇ 새 생존집합 이어야 한다.
CASES = [
    ["https://github.com/smtg-ai/claude-squad"],
    ["https://github.com/smtg-ai/claude-squad/releases"],
    ["https://smtg-ai.github.io/claude-squad/", "https://example.com/"],
    ["https://api.github.com/repos/x/y"],
]
viol, frag_only = 0, 0
for urls in CASES:
    obs = {"calls": [{"url": "https://api.github.com/repos/x/y", "status": 200}]}
    s = spec_with([{"title": "t", "url": u} for u in urls], observed=obs)
    before = {_norm_url(u) for u in urls}            # 기존 규칙 생존집합(모델 인용 전부)
    _finalize_sources(s, CFG, FETCHED, GROUND)
    after = {_norm_url(x["url"]) for x in s.sources}
    extra = after - before
    if extra:
        # R1 프래그먼트 흡수로 '더 살린' 경우만 예외로 계수한다(51-review §4-(j))
        frag_only += len(extra)
    viol += len(extra)
ck("새 규칙에서만 살아남는 인용 0건", viol == 0, f"위반 {viol}건 (프래그먼트 예외 {frag_only})")


# ══ 인용 0건 계측 + 트립와이어 (R0~R4 채택 조건 2·3, PM 2026-08-01) ══════════════════════
# 🔴 R0~R4 는 **측정으로 채택된 것이 아니다** — 리플레이 표본이 실초안 6편뿐이라 0.0%도 14.3%도
#    판단 근거가 못 된다. PM 이 실패 모드의 비대칭으로 채택했고, 진짜 수치는 **운영에서** 나온다.
#    아래는 그 수치를 만들 계측이 실제로 작동하는지 고정한다.
import datetime as _dt                                            # noqa: E402
import tempfile                                                   # noqa: E402
from monitor import sources_watch                                 # noqa: E402

print("\n[계측] '인용 0건' 반려만 구분해 세는가")
_tmp = tempfile.mkdtemp()
sources_watch.STATE_FILE = os.path.join(_tmp, "sources_zero.json")
CFG_G = {"guardrails": {"rollout": {"sources_zero_alert_total": 3, "sources_zero_alert_days": 2}}}

ck("다른 사유의 반려는 세지 않는다",
   sources_watch.record("kw", "s", ["near_duplicate > 0.7"], CFG_G) is None)
ck("인용 0건 사유는 잡아낸다", sources_watch.is_sources_zero(["eeat: 출처 없음"]))
ck("사유가 섞여 있어도 잡아낸다", sources_watch.is_sources_zero(["structure: 산문 부족", "eeat: 출처 없음"]))

print("\n[트립와이어] 누적 3건에서 발동")
d0 = _dt.date(2026, 8, 10)
st1 = sources_watch.record("k1", "s1", ["eeat: 출처 없음"], CFG_G, today=d0)
st2 = sources_watch.record("k2", "s2", ["eeat: 출처 없음"], CFG_G, today=d0)
ck("2건까지는 발동 안 함", not st2["tripped"], f"누적 {st2['total']}")
st3 = sources_watch.record("k3", "s3", ["eeat: 출처 없음"], CFG_G, today=d0)
ck("3건째에 발동", st3["tripped"] and st3.get("notify"), st3["why"])
ck("같은 날 같은 사유로 재알림 안 함(알림 피로 방지)",
   not (sources_watch.record("k4", "s4", ["eeat: 출처 없음"], CFG_G, today=d0) or {}).get("notify"))

print("\n[트립와이어] 연속 2일에서 발동")
sources_watch.STATE_FILE = os.path.join(_tmp, "sources_zero2.json")
a = sources_watch.record("k1", "s1", ["eeat: 출처 없음"], CFG_G, today=_dt.date(2026, 8, 10))
ck("1일차는 연속 1 (미발동)", a["consecutive"] == 1 and not a["tripped"], str(a))
b = sources_watch.record("k2", "s2", ["eeat: 출처 없음"], CFG_G, today=_dt.date(2026, 8, 11))
ck("2일 연속에서 발동", b["consecutive"] == 2 and b["tripped"], b["why"])

print("\n[분리] zero_generation_alert_days 와 별개 경로인가")
ck("sources_watch 는 자체 상태파일을 쓴다", "sources_zero" in sources_watch.STATE_FILE)
from monitor import generation_watch                              # noqa: E402
ck("generation_watch 와 상태파일이 다르다",
   generation_watch.STATE_FILE != sources_watch.STATE_FILE)
ck("임계는 config 값이다(하드코딩 아님)",
   sources_watch._thresholds({"guardrails": {"rollout": {"sources_zero_alert_total": 9,
                                                         "sources_zero_alert_days": 7}}}) == (9, 7))
ck("알림 문구가 '측정 아님'을 명시한다",
   "측정으로 채택된 것이 아니다" in sources_watch.notice("k", {"why": "x", "total": 3, "consecutive": 2}))

print("\n" + ("실패: " + ", ".join(FAILS) if FAILS else "생성기 셀프테스트 전 항목 통과"))
sys.exit(1 if FAILS else 0)
