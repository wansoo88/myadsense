"""reviewer_selftest.py — 광고·제휴 고지 처리의 회귀 테스트.

무엇을 못 박는가 (ORDER 2026-07-25-19)
--------------------------------------
**불변식: `_apply_disclosure_policy` 는 `passed`·`severity` 를 어떤 입력에서도 바꾸지 않는다.**

이 파일의 목적이 바뀌었다. 예전엔 "강등이 너무 넓어지지 않게" 경계를 지켰다.
지금은 경계 자체가 없다 — 판정을 뒤집는 코드가 사라졌으므로, 테스트는 그 **부재**를 증명한다.

왜 폐기했나 (세 라운드의 같은 실패):
  12 rev1 — 문장 단위 면제 → 고지+실질리스크가 한 문장이면 통째 강등, `passed` False→True.
  12 rev2 — 블록리스트(`_OTHER_RISK`) → 목록 밖 표현 8종이 그대로 샘.
  18      — 얼라우리스트(`_out_of_scope`/`_GENERIC_OK`/`_DOMAIN_VOCAB`) → 감사자 창작 21종 중 **13종 flip**
            (허위 1인칭 실사용·저작권 복제·YMYL 건강 지시·경쟁사 부정 단정·광고 클릭 유도 포함).
  → 자연어를 어휘로 판정해 게이트를 뒤집는 한 계속 샌다. 기전을 없애면 샐 것이 없다.

남은 것: `issues_not_applicable` **표식**(사람이 읽는 주석)과 프롬프트 조건화(`_system`).
표식 분류기가 틀려도 판정은 그대로다 — 그것이 [2]·[5] 가 증명하는 내용이다.

⚠️ AUDIT_CASES 21종의 출처: 감사자가 창작한 원문 21종은 리포에 보존돼 있지 않다(team/reports 에도 없음).
   ORDER 19 가 명시한 5개 범주(허위 1인칭 실사용·저작권 복제·YMYL 건강 지시·경쟁사 부정 단정·
   광고 클릭 유도)를 축으로 **재구성**했고, 과거 세 기전을 각각 뚫도록 어휘를 일부러 비켰다.
   원문과 1:1 대응은 아니다 — 다만 불변식은 텍스트에 의존하지 않으므로(어떤 입력에도 판정 불변)
   재구성 여부가 증명력을 좌우하지 않는다. [5] 는 무작위 조합·코퍼스 전량으로도 같은 불변식을 친다.

실행 (LLM 미호출 · 네트워크 미사용 · 파일 쓰기 없음):
    python engine/content/reviewer_selftest.py
    python engine/content/reviewer_selftest.py --require-replay   # 코퍼스 없으면 실패 처리(CI 용)
종료코드 0 = 전 케이스 통과.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))          # <repo>/engine/content → <repo>
sys.path.insert(0, os.path.dirname(_HERE))

from content import reviewer as R  # noqa: E402

# 관측을 타지 않는 고정 상태 — 테스트가 dist/site 존재 여부에 흔들리지 않게.
OFF = {"monetized": False, "ads": False, "affiliate": False, "known": True,
       "evidence": ["selftest: monetization not observed"], "scanned": "selftest", "warning": ""}
ON = dict(OFF, monetized=True, ads=True,
          evidence=["selftest: ad-network code found — dist/site/index.html: 'adsbygoogle'"])
# 관측 실패(=알 수 없음). fail-closed 로 표식조차 달면 안 되는 상태.
UNKNOWN = dict(OFF, known=False, evidence=["selftest: render templates not found"],
               scanned="0 render template file(s) + 0 built page(s)",
               warning="selftest: monetization NOT verifiable")

ALL_STATES = (("OFF", OFF), ("ON", ON), ("UNKNOWN", UNKNOWN))
# 검수기가 낼 수 있는 판정 조합 — 전부에 대해 불변이어야 한다.
ALL_VERDICTS = ((False, "high"), (False, "medium"), (False, "low"), (False, "unknown"),
                (True, "none"), (True, "low"))

_fails: list[str] = []
_warns: list[str] = []


def check(ok: bool, label: str, got: object = None, want: object = None) -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}   got={got!r} want={want!r}")
        _fails.append(label)


def warn(label: str) -> None:
    print(f"  WARN  {label}")
    _warns.append(label)


def _clone(x):
    return json.loads(json.dumps(x))


# ── rev2(블록리스트) 기전 복제 — 표식 폭 대조용 참조 구현(프로덕션 경로 무관) ─────────────────
_LEGACY_DISCLOSURE_PHRASE = re.compile(
    r"(?:affiliate|advertis\w*|\bads?\b|sponsor\w*|monetiz\w*|commission|referral)"
    r"[\w\s,'’/&()\.\-]{0,60}?disclos\w*"
    r"|disclos\w*[\w\s,'’/&()\.\-]{0,60}?"
    r"(?:affiliate|advertis\w*|\bads?\b|sponsor\w*|monetiz\w*|commission|referral)", re.I)


def legacy_is_disclosure_only(issue: dict) -> bool:
    """rev2 판정: '고지 구절이 있고 위험 어휘 목록에 안 걸리면' 강등."""
    t = R._issue_text(issue)
    return bool(_LEGACY_DISCLOSURE_PHRASE.search(t)) and not R._OTHER_RISK.search(t)


# ── 1. 표식 분류기 케이스 ────────────────────────────────────────────────────────────────
# (name, issue, 표식을 달아도 되는가) — ⚠️ 이건 **라벨** 기대치다. 판정과 무관하다.
CLASSIFY_CASES = [
    ("mixed/one-sentence: disclosure + false first-person (PM repro)",
     {"type": "legal",
      "detail": "The draft lacks an affiliate/ad disclosure and makes a false first-person claim "
                "of hands-on testing.",
      "fix": "Add a disclosure line and remove the testing claim."}, False),
    ("mixed/one-sentence: disclosure + Privacy Policy (F2)",
     {"type": "policy",
      "detail": "No affiliate/advertising disclosure is present and no Privacy Policy is linked (F2).",
      "fix": "Add both a disclosure and a site-wide Privacy Policy link."}, False),
    ("mixed/one-sentence: disclosure + ad-click solicitation (F3)",
     {"type": "policy",
      "detail": "Missing ad disclosure, and the CTA is deceptive clickbait that solicits ad clicks.",
      "fix": "Remove the clickbait CTA."}, False),
    ("mixed: F3 without the word 'clickbait' — 'asks readers to click the ads'",
     {"type": "policy",
      "detail": "Missing ad disclosure, and the intro asks readers to click the ads to support us.",
      "fix": ""}, False),
    ("mixed: F3 'solicits ad clicks'",
     {"type": "policy",
      "detail": "No affiliate disclosure; the closing line solicits ad clicks.", "fix": ""}, False),
    ("mixed: F3 'invalid traffic'",
     {"type": "policy",
      "detail": "No advertising disclosure. The page invites invalid traffic by rewarding clicks.",
      "fix": ""}, False),
    ("mixed/two-sentences: disclosure . false first-person",
     {"type": "legal",
      "detail": "No affiliate disclosure anywhere in the draft. It also makes a false first-person claim.",
      "fix": ""}, False),
    ("mixed: risk word lives in fix only",
     {"type": "legal",
      "detail": "There is no advertising disclosure on this page.",
      "fix": "Add one, and drop the unverified negative claim about the competitor."}, False),
    # ✅ 표식 대상 — 순수 고지 지적(오탐 표식이라는 원래 목적)
    ("pure: the exact false positive this ORDER targets",
     {"type": "legal",
      "detail": "No affiliate or advertising disclosure anywhere in the draft.",
      "fix": "Add a short disclosure line near the top."}, True),
    ("pure: monetization disclosure wording",
     {"type": "policy",
      "detail": "The article recommends vendors but never discloses how the site is monetized.",
      "fix": "State the monetization/affiliate relationship in the intro."}, True),
    ("pure: 'click a vendor link' must NOT be mistaken for F3",
     {"type": "legal",
      "detail": "No ad/affiliate disclosure is present on this recommendation page.",
      "fix": "Add a disclosure so readers know we may earn a commission when they click a vendor link."},
     True),
    ("pure/postposed: 'disclosure is absent'",
     {"type": "policy", "detail": "Ad/affiliate disclosure is absent from the draft.",
      "fix": "Render the site-wide disclosure on this page."}, True),
    ("pure/postposed: 'disclosure … is missing'",
     {"type": "policy", "detail": "Disclosure of the affiliate relationship is missing.", "fix": ""}, True),
    ("pure: 'fails to disclose the commission relationship'",
     {"type": "legal", "detail": "The draft fails to disclose the commission relationship.", "fix": ""}, True),
    ("unrelated: factual issue must never be labelled as disclosure",
     {"type": "factual",
      "detail": "The GPU price is contradicted by the source: $1.91/hour vs $0.76 on-demand.",
      "fix": "Correct the figure."}, False),
]

# ── rev2 에서 실제로 샌 8종 (구현 전 실측으로 8/8 재현, LEGACY 로 박제) ─────────────────────
HOLE_CASES = [
    ("HOLE V1 false first-person, no 'first-person' word",
     {"type": "legal",
      "detail": "No affiliate or advertising disclosure anywhere in the draft. The intro says the "
                "author personally ran the tool for six months.", "fix": ""}),
    ("HOLE V2 invented pricing, no 'fabricat'",
     {"type": "factual",
      "detail": "No ad/affiliate disclosure is present; the pricing figures were invented rather "
                "than taken from the vendor page.", "fix": ""}),
    ("HOLE V3 defamatory claim, no 'defam'",
     {"type": "legal",
      "detail": "No advertising disclosure, and the piece asserts a rival product is illegal spyware.",
      "fix": ""}),
    ("HOLE V4 YMYL health directive",
     {"type": "legal",
      "detail": "No monetization disclosure. The article tells readers to stop taking prescribed "
                "medication while they use the app.", "fix": ""}),
    ("HOLE V5 absolute superlative, no 'superlativ'",
     {"type": "legal",
      "detail": "No affiliate disclosure; it calls this the cheapest option on the market with "
                "nothing behind that ranking.", "fix": ""}),
    ("HOLE V6 invented quote, no 'fabricat'/'not found'",
     {"type": "factual",
      "detail": "No ad disclosure. The quote attributed to the vendor's CEO does not exist on the "
                "cited page.", "fix": ""}),
    ("HOLE M1 reverse: body DISCUSSES disclosure, issue is a factual error",
     {"type": "factual",
      "detail": "The draft says the tool automatically discloses ad tracking to end users; the "
                "source page says the opposite.", "fix": "Correct the sentence."}),
    ("HOLE M2 reverse: body DISCUSSES disclosure, claim unsupported",
     {"type": "factual",
      "detail": "The FAQ states that the vendor discloses affiliate commissions to customers, which "
                "the source material does not support.", "fix": ""}),
]

# ── 감사 21종 (재구성 — 파일 상단 ⚠️ 참조) ────────────────────────────────────────────────
# 축: ①허위 1인칭 실사용 ②저작권 복제 ③YMYL 건강/금융 지시 ④경쟁사 부정 단정 ⑤광고 클릭 유도
# 전부 "고지 누락 + 두 번째 실질 결함"이 섞인 지적이고, 과거 세 기전의 어휘를 일부러 비켰다.
AUDIT_CASES = [
    ("A01 ①1인칭 'ran it nightly for a year'",
     {"type": "legal", "detail": "No affiliate disclosure appears anywhere. The author writes that "
      "they ran the tool nightly for a year.", "fix": ""}),
    ("A02 ①1인칭 'our migration weekend'",
     {"type": "legal", "detail": "Ad disclosure is absent, and the piece opens with a story about "
      "the writer's own migration weekend.", "fix": ""}),
    ("A03 ①1인칭 'we benchmarked both boxes'",
     {"type": "legal", "detail": "There is no advertising disclosure; the intro says we benchmarked "
      "both boxes side by side for three weeks.", "fix": ""}),
    ("A04 ②저작권 'lifted word for word'",
     {"type": "legal", "detail": "No advertising disclosure. Two paragraphs are lifted word for word "
      "from the vendor's own docs.", "fix": ""}),
    ("A05 ②저작권 'reproduced without permission'",
     {"type": "legal", "detail": "There is no monetization disclosure, and the comparison table is "
      "reproduced from a rival publication without permission.", "fix": ""}),
    ("A06 ②저작권 'the screenshot belongs to another site'",
     {"type": "legal", "detail": "Affiliate disclosure is missing. The screenshot belongs to another "
      "site and is used here as our own.", "fix": ""}),
    ("A07 ③YMYL 'halve their insulin dose'",
     {"type": "legal", "detail": "No ad/affiliate disclosure. The FAQ tells readers to halve their "
      "insulin dose while trialling the tracker.", "fix": ""}),
    ("A08 ③YMYL 'skip the doctor visit'",
     {"type": "legal", "detail": "Ad disclosure is nowhere on the page, and the verdict tells readers "
      "they can skip the doctor visit if the app says their readings are fine.", "fix": ""}),
    ("A09 ③YMYL 금융 'move their emergency fund'",
     {"type": "legal", "detail": "Affiliate disclosure is missing; the closing advises readers to move "
      "their emergency fund into the vendor's yield product.", "fix": ""}),
    ("A10 ④경쟁사 'servers leak customer data'",
     {"type": "legal", "detail": "No sponsor disclosure, and it states the rival's servers leak "
      "customer data.", "fix": ""}),
    ("A11 ④경쟁사 'free tier is a bait scheme'",
     {"type": "legal", "detail": "Advertising disclosure is absent. The verdict says the other "
      "vendor's free tier is a bait scheme that will be withdrawn.", "fix": ""}),
    ("A12 ④경쟁사 'CEO was fired for fraud'",
     {"type": "legal", "detail": "No ad disclosure, and it says the competing CEO was fired for "
      "fraud last year.", "fix": ""}),
    ("A13 ⑤클릭유도 'tap the banner a few times'",
     {"type": "policy", "detail": "No affiliate disclosure. The footer asks readers to tap the banner "
      "a few times to keep the lights on.", "fix": ""}),
    ("A14 ⑤클릭유도 'visits our sponsors daily'",
     {"type": "policy", "detail": "Ad disclosure is missing and the sidebar promises a free month to "
      "anyone who visits our sponsors daily.", "fix": ""}),
    ("A15 ⑤클릭유도 'reloading the page repeatedly'",
     {"type": "policy", "detail": "No affiliate disclosure; the giveaway rewards readers for reloading "
      "the page repeatedly.", "fix": ""}),
    ("A16 날조 인용 'written by the model'",
     {"type": "factual", "detail": "No advertising disclosure. The CEO quote in the intro was written "
      "by the model, not taken from the press page.", "fix": ""}),
    ("A17 날조 가격 'guessed at'",
     {"type": "factual", "detail": "There is no affiliate disclosure; the $4 tier in the table was "
      "guessed at and the vendor page shows no such plan.", "fix": ""}),
    ("A18 상표 'implies an official partnership'",
     {"type": "legal", "detail": "No ad disclosure. The article uses the vendor's logo and name in a "
      "way that implies an official partnership.", "fix": ""}),
    ("A19 절대 최상급 'the only hosting anyone should ever buy'",
     {"type": "legal", "detail": "Affiliate disclosure is nowhere on the page, and the headline calls "
      "this the only hosting anyone should ever buy.", "fix": ""}),
    ("A20 정책 'bypass the paywall with a shared login'",
     {"type": "policy", "detail": "No monetization disclosure. It tells readers to bypass the paywall "
      "with a shared login.", "fix": ""}),
    ("A21 F2 인접 'never says what the widgets collect'",
     {"type": "policy", "detail": "No advertising disclosure, and the site never tells readers what "
      "data the embedded widgets collect.", "fix": ""}),
]


def test_classify() -> None:
    print("\n[1] _is_disclosure_only — **표식** 판별(판정 아님)")
    for name, issue, want in CLASSIFY_CASES:
        got = R._is_disclosure_only(issue)
        check(got is want, name, got, want)


def test_removed_machinery() -> None:
    print("\n[1b] 판정 뒤집기용 분류 장치가 **모듈에서 사라졌는가** (ORDER 19)")
    for gone in ("_out_of_scope", "_GENERIC_OK", "_DOMAIN_VOCAB", "_SEGMENT_SPLIT",
                 "_STOPWORDS", "_WORD", "_segments", "_unknown_words"):
        check(not hasattr(R, gone), f"reviewer.{gone} 제거됨", hasattr(R, gone), False)
    src = open(os.path.join(_HERE, "reviewer.py"), encoding="utf-8").read()
    body = src[src.index("def _apply_disclosure_policy"):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    for pat in ('data["passed"]', "data['passed']", 'data["severity"]', "data['severity']"):
        check(f"{pat} =" not in body and f"{pat}," not in body,
              f"_apply_disclosure_policy 본문에 {pat} 대입 없음", pat in body, False)


def test_holes() -> None:
    """rev2 구멍 8종 — **판정**은 불변([2]에서 증명), **표식**은 폭이 넓어졌다(숨기지 않는다).

    ORDER 19 로 얼라우리스트(`_out_of_scope`)를 제거하면서 표식 판별은 rev2 폭으로 돌아왔다.
    즉 '고지 누락 + 실질 결함'이 한 지적에 섞이면 그 지적에 not_applicable 표식이 **잘못** 붙는다.
    예전에는 그것이 곧 `passed` flip 이었지만 지금은 아니다 — 판정은 검수기 원본 그대로다.
    남는 실제 부작용 2가지(리포트에 기록):
      (a) 표식된 지적은 `issues` 에서 빠지므로 orchestrator.py:229 의 **재작성 피드백에서 사라진다**.
      (b) 사람이 보는 보고서에서 실질 리스크가 '해당 없음' 칸에 놓인다.
    실코퍼스 229지적에서 이런 혼합 지적은 **0건**이었다(전부 순수 고지). 합성 케이스에서만 발생한다."""
    print("\n[1c] rev2 구멍 8종 — 판정은 불변, 표식 폭은 rev2 로 복귀(부작용 명시)")
    mislabelled = []
    for name, issue in HOLE_CASES:
        old = legacy_is_disclosure_only(issue)
        new = R._is_disclosure_only(issue)
        check(old is True, f"{name} — rev2 에서는 강등됐다(구멍 재현)", old, True)
        out = _apply([issue], OFF)
        check(out["passed"] is False and out["severity"] == "high",
              f"{name} — **판정 불변**(구 기전이면 여기서 flip 했다)",
              (out["passed"], out["severity"]), (False, "high"))
        if new:
            mislabelled.append(name)
    if mislabelled:
        warn(f"표식 오부착 {len(mislabelled)}/{len(HOLE_CASES)}종 — {', '.join(m[:24] for m in mislabelled)} "
             "(판정 영향 없음. 남은 부작용은 **보고서 분류 오기뿐** — 재작성 피드백 누락은 move→copy 로[7], "
             "맥락 없는 전달·슬롯 경쟁은 ORDER 39 로[9] 해소됐다. 실코퍼스 발생 0건)")
    else:
        check(True, "표식 오부착 0종")


# ── 2. 불변식: _apply_disclosure_policy 는 passed·severity 를 바꾸지 않는다 ─────────────────
def _apply(issues, state, ai_tells=(), passed=False, severity="high"):
    data = {"passed": passed, "severity": severity, "ai_tells": list(ai_tells),
            "issues": _clone(list(issues)), "notes": ""}
    return R._apply_disclosure_policy(data, state)


def assert_invariant(label: str, issues, ai_tells=(), quiet: bool = False) -> bool:
    """모든 상태 × 모든 초기 판정에서 passed·severity 불변인지."""
    ok = True
    for sname, state in ALL_STATES:
        for passed, sev in ALL_VERDICTS:
            out = _apply(issues, state, ai_tells, passed, sev)
            if (out.get("passed"), out.get("severity")) != (passed, sev):
                ok = False
                check(False, f"{label} [{sname} · in=({passed},{sev})]",
                      (out.get("passed"), out.get("severity")), (passed, sev))
    if ok and not quiet:
        check(True, f"{label} — 3상태 × 6판정 = 18조합 전부 판정 불변")
    return ok


def test_invariant() -> None:
    print("\n[2] 불변식 — passed·severity 는 어떤 입력에도 바뀌지 않는다")
    n_ok = 0
    for name, issue, _want in CLASSIFY_CASES:
        n_ok += assert_invariant(f"CLASSIFY {name}", [issue], quiet=True)
    for name, issue in HOLE_CASES:
        n_ok += assert_invariant(f"HOLE {name}", [issue], quiet=True)
    for name, issue in AUDIT_CASES:
        n_ok += assert_invariant(f"AUDIT {name}", [issue], quiet=True)
    total = len(CLASSIFY_CASES) + len(HOLE_CASES) + len(AUDIT_CASES)
    check(n_ok == total,
          f"단건 {total}종(감사 창작 {len(AUDIT_CASES)}종 포함) × 18조합 = {total * 18}회 판정 불변",
          n_ok, total)

    # 순수 고지 지적 **단독** — 예전엔 여기서 passed 가 True 로 뒤집혔다. 이제 안 뒤집힌다.
    pure = next(c[1] for c in CLASSIFY_CASES if c[0].startswith("pure: the exact false positive"))
    out = _apply([pure], OFF)
    check(out["passed"] is False and out["severity"] == "high",
          "순수 고지 **단독** → passed/severity 불변 (구 기전의 flip 경로가 사라졌다)",
          (out["passed"], out["severity"]), (False, "high"))
    check(len(out.get("issues_not_applicable") or []) == 1 and len(out["issues"]) == 1,
          "표식은 **사본**이다 — 지적이 issues 에서 사라지지 않는다(개수 보존, ORDER 21 ①)",
          (len(out["issues"]), len(out.get("issues_not_applicable") or [])), (1, 1))
    check("SOLE-OBJECTION" in out.get("notes", ""),
          "'고지가 유일한 반대 사유' 는 notes 에 SOLE-OBJECTION 으로 관측 가능하게 기록",
          out.get("notes", "")[-120:], "contains SOLE-OBJECTION")

    # 감사 21종을 **조합**으로도 — 순수 고지 + 창작 리스크가 한 지적 목록에 함께 올 때
    for name, issue in AUDIT_CASES:
        assert_invariant(f"AUDIT+pure {name}", [pure, issue], quiet=True)
    check(True, f"감사 {len(AUDIT_CASES)}종 × (순수고지 동반) 조합도 판정 불변")

    # F2·F3 지적이 표식으로 사라지지 않는지 (ORDER 2026-07-24-12 24행)
    f2 = next(c[1] for c in CLASSIFY_CASES if c[0].startswith("mixed/one-sentence: disclosure + Privacy"))
    f3 = next(c[1] for c in CLASSIFY_CASES if c[0].startswith("mixed/one-sentence: disclosure + ad-click"))
    for lbl, iss in (("F2", f2), ("F3", f3)):
        out = _apply([iss], OFF)
        check(len(out["issues"]) == 1 and not out.get("issues_not_applicable"),
              f"{lbl} 동반 지적은 차단 목록에 잔존(표식 안 붙음)",
              (len(out["issues"]), len(out.get("issues_not_applicable") or [])), (1, 0))

    # 상태별 표식 동작(판정과 무관) — ON/UNKNOWN 에서는 표식조차 달지 않는다
    out = _apply([pure], ON)
    check(len(out["issues"]) == 1 and not out.get("issues_not_applicable"),
          "수익화 관측(ON) → 표식 없음(고지 요구 부활)", len(out["issues"]), 1)
    out = _apply([pure], UNKNOWN)
    check(len(out["issues"]) == 1 and not out.get("issues_not_applicable")
          and "no annotation" in out.get("notes", ""),
          "관측 불가(UNKNOWN) → 표식 없음 + 사유 기록(fail-closed)",
          out.get("notes", ""), "no annotation")


def test_invariant_under_collapse() -> None:
    print("\n[2b] 분류기가 완전히 붕괴해도 판정은 불변 (표식만 넓어질 뿐)")
    orig_cls, orig_risk = R._is_disclosure_only, R._has_other_risk
    try:
        R._is_disclosure_only = lambda i: True        # 최악: 모든 지적을 고지로 오분류
        R._has_other_risk = lambda i: False
        ok = True
        for name, issue in [(n, i) for n, i, _ in CLASSIFY_CASES] + HOLE_CASES + AUDIT_CASES:
            ok &= assert_invariant(f"[collapse] {name}", [issue], quiet=True)
        check(ok, "분류기 100% 오분류 상태에서도 판정 불변(구 기전이면 전부 flip 했다)", ok, True)
        out = _apply([{"type": "legal", "detail": "The draft invents a quote.", "fix": ""}], OFF)
        check(out["passed"] is False and out["severity"] == "high",
              "[collapse] 고지와 무관한 지적이 표식으로 옮겨져도 판정 불변",
              (out["passed"], out["severity"]), (False, "high"))
    finally:
        R._is_disclosure_only, R._has_other_risk = orig_cls, orig_risk


# ── 3. monetization_state fail-closed + 프롬프트 조건화(양방향) ──────────────────────────
def test_monetization_failclosed() -> None:
    print("\n[3] monetization_state — fail-closed · cwd 비의존 · 프롬프트 조건화 생존")
    pure = next(c[1] for c in CLASSIFY_CASES if c[0].startswith("pure: the exact false positive"))

    check(R._DISCLOSURE_CLAUSE in R._system(UNKNOWN),
          "known=False 면 시스템 프롬프트의 고지 절이 **유지**된다", "-", "clause kept")
    check(R._DISCLOSURE_CLAUSE not in R._system(OFF),
          "관측된 미수익화에서만 고지 절이 빠진다(**오탐 해소의 본체 — 살아 있어야 한다**)",
          "-", "clause dropped")
    check("MONETIZATION STATE" in R._system(OFF) and "do NOT raise a missing affiliate" in R._system(OFF),
          "미수익화 프롬프트에 근거·범위 설명이 함께 붙는다", "-", "note present")
    check(R._DISCLOSURE_CLAUSE in R._system(ON), "수익화 관측 시 고지 절 유지", "-", "clause kept")
    check(R._SYSTEM == R._system(ON).replace(R._MONETIZED_NOTE.format(
        evidence="; ".join(ON["evidence"])), ""),
        "기준선 _SYSTEM 은 한 글자도 바뀌지 않았다(ON 은 주석만 덧붙임)", "-", "baseline intact")

    out = _apply([pure], UNKNOWN)
    check(out["passed"] is False and len(out["issues"]) == 1 and not out.get("issues_not_applicable"),
          "known=False(알 수 없음) → 표식 없음 · 판정 불변",
          (out["passed"], len(out["issues"])), (False, 1))

    cwd0 = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="reviewer_selftest_")
    try:
        os.chdir(tmp)
        R._site_scan_cache.clear()
        st = R.monetization_state()
        print(f"        cwd={tmp} → scanned: {st['scanned']} | known={st['known']} "
              f"| monetized={st['monetized']}")
        check(st["known"] is True and "0 render template file(s)" not in st["scanned"],
              "cwd 가 리포 밖이어도 렌더 템플릿을 읽는다(0파일 fail-open 해소)",
              st["scanned"], "templates > 0")

        R._site_scan_cache.clear()
        root0 = R._REPO_ROOT
        try:
            R._REPO_ROOT = tmp
            st2 = R.monetization_state()
            print(f"        detached(repo_root={tmp}) → scanned: {st2['scanned']} | known={st2['known']}")
            check(st2["known"] is False, "스캔 0파일 → known=False(‘광고 없음’으로 단정하지 않는다)",
                  st2["known"], False)
            check(bool(st2.get("warning")), "0파일일 때 경고 문자열이 남는다", st2.get("warning"), "non-empty")
            out2 = _apply([pure], st2)
            check(out2["passed"] is False and not out2.get("issues_not_applicable"),
                  "관측 불가 상태에서는 표식이 붙지 않는다(fail-closed)",
                  (out2["passed"], len(out2["issues"])), (False, 1))
        finally:
            R._REPO_ROOT = root0
    finally:
        os.chdir(cwd0)
        R._site_scan_cache.clear()
        try:
            os.rmdir(tmp)
        except OSError:
            pass


# ── 4. 실데이터 리플레이 — 보존된 검수 판정 전량 ────────────────────────────────────────
_F2 = "privacy policy"
_F3 = ("ad click", "ad-click", "clickbait", "solicit")
_CORPUS = os.path.join(_ROOT, "dist", "review", "*.json")     # cwd 가 아니라 리포 루트 기준


def test_replay(require: bool = False) -> None:
    print(f"\n[4] 실데이터 리플레이 — {_CORPUS}")
    files = [f for f in sorted(glob.glob(_CORPUS)) if not f.endswith(".spec.json")]
    if not files:
        msg = (f"검수 판정 코퍼스가 없다({_CORPUS}) — 실데이터 리플레이를 **수행하지 못했다**. "
               "clone/CI 환경이면 dist/review/*.json 를 함께 가져오거나 --require-replay 로 강제하라.")
        if require:
            check(False, "리플레이: 코퍼스 필수(--require-replay)", 0, ">0")
        else:
            warn(msg)
        return
    n_iss = n_marked = n_verdict_changed = n_f2 = n_f3 = n_legacy = n_sole = n_lost = 0
    n_docs = 0
    marked_files = set()
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                orig = json.load(fh)
        except Exception:
            continue
        if not isinstance(orig, dict) or "issues" not in orig:
            continue
        n_docs += 1
        issues = [i for i in (orig.get("issues") or []) if isinstance(i, dict)]
        n_iss += len(orig.get("issues") or [])
        n_legacy += sum(1 for i in issues if legacy_is_disclosure_only(i))
        before = (orig.get("passed"), orig.get("severity"))
        for _sname, state in ALL_STATES:                 # 세 상태 전부에서 판정 불변이어야 한다
            out = R._apply_disclosure_policy(_clone(orig), state)
            if (out.get("passed"), out.get("severity")) != before:
                n_verdict_changed += 1
        out = R._apply_disclosure_policy(_clone(orig), OFF)
        n_lost += len(orig.get("issues") or []) - len(out.get("issues") or [])   # copy 면 항상 0
        marked = out.get("issues_not_applicable") or []
        if marked:
            marked_files.add(path)
        n_marked += len(marked)
        if "SOLE-OBJECTION" in out.get("notes", ""):
            n_sole += 1
        for i in marked:
            txt = f"{i.get('detail', '')} {i.get('fix', '')}".lower()
            if _F2 in txt:
                n_f2 += 1
            if any(k in txt for k in _F3):
                n_f3 += 1
    print(f"  files={len(files)} (판정 문서 {n_docs})  issues={n_iss}  marked={n_marked} "
          f"(in {len(marked_files)} files)  verdict_changed={n_verdict_changed}  "
          f"F2_marked={n_f2}  F3_marked={n_f3}  SOLE-OBJECTION={n_sole}")
    print(f"  rev2(LEGACY) 강등 대상={n_legacy} → 현행 표식={n_marked} "
          "(현행은 강등이 아니라 **주석**이므로 어느 쪽도 판정을 바꾸지 않는다)")
    check(n_verdict_changed == 0,
          f"리플레이: 코퍼스 {n_docs}문서 × 3상태 판정 변경 0건(불변식)", n_verdict_changed, 0)
    check(n_f2 == 0, "리플레이: F2(Privacy Policy) 지적에 표식 0건", n_f2, 0)
    check(n_f3 == 0, "리플레이: F3(클릭 유도) 지적에 표식 0건", n_f3, 0)
    check(n_marked > 0, "리플레이: 순수 고지 오탐은 여전히 표식된다(보고서 구분 유지)", n_marked, ">0")
    check(n_lost == 0,
          f"리플레이: 표식 {n_marked}건이 붙어도 `issues` 에서 사라진 지적 0건(개수 보존, ORDER 21 ①)",
          n_lost, 0)


# ── 5. passed 정규화 — 문자열 판정이 발행 게이트를 뚫던 경로 (ORDER 2026-07-25-21 ②) ────────
def _gate_blocks(rv: dict) -> bool:
    """orchestrator.py 발행 게이트와 **같은 표현식**(`if not rv.get("passed")`).
    표현식이 소스에서 바뀌면 [5](a) 가 먼저 깨져 이 복제본이 낡았음을 알린다."""
    return not rv.get("passed")


def test_passed_coercion() -> None:
    print("\n[5] passed 정규화 — 문자열 \"false\" 가 발행 게이트를 뚫지 못한다")
    try:
        with open(os.path.join(_ROOT, "engine", "orchestrator.py"), encoding="utf-8") as fh:
            src = fh.read()
        check('if not rv.get("passed")' in src,
              '전제: orchestrator 발행 게이트가 `if not rv.get("passed")` 그대로다', "-", "found")
    except OSError as e:
        warn(f"orchestrator.py 를 읽지 못해 게이트 표현식 동기화를 확인하지 못했다: {e}")

    # 왜 위험했나 — 파이썬에서 문자열 "false" 는 truthy 다. 수정 전에는 이 값이 그대로 통과했다.
    check(bool("false") is True and _gate_blocks({"passed": "false"}) is False,
          '수정 전 실동작: passed="false" 는 truthy → 게이트가 **막지 못했다**',
          _gate_blocks({"passed": "false"}), False)

    true_cases = [True, "true", "True", " yes ", "1", 1, 1.0, "ok", "PASS"]
    false_cases = [False, "false", "False", "0", 0, "", "   ", None, "unknown", "pending",
                   "n/a", "maybe", [], {}, ["true"], {"passed": True}, 2, -1, 0.5, object()]
    bad_true = [v for v in true_cases if R._coerce_passed(v) is not True]
    bad_false = [v for v in false_cases if R._coerce_passed(v) is not False]
    check(not bad_true, f"통과로 인정하는 값 {len(true_cases)}종이 전부 True", bad_true, [])
    check(not bad_false,
          f"그 밖의 {len(false_cases)}종(모르는 문자열·타입 포함)은 전부 False(fail-closed)",
          bad_false, [])
    check(all(_gate_blocks({"passed": R._coerce_passed(v)}) for v in false_cases),
          "정규화 후 그 값들은 orchestrator 게이트에서 **전부 막힌다**", "-", "all blocked")


# ── 6. end-to-end — review() 가 내보내는 판정은 항상 bool 이다 ──────────────────────────────
def _dummy_spec():
    import types
    return types.SimpleNamespace(
        slug="selftest-draft", title="Selftest draft", dek="dek", author="Selftest",
        published_at="2026-07-25", updated_at="", tldr_html="<p>tldr</p>",
        intro_html="<p>intro</p>", sections=[{"heading": "H", "html": "<p>body</p>"}],
        verdict_html="<p>verdict</p>", faq=[],
        sources=[{"title": "src", "url": "https://example.com/"}], grounding_context="")


def _review_with_raw(raw: str) -> dict:
    """검수기(LLM) 응답만 갈아끼워 review() 전 경로를 태운다 — 네트워크·파일 쓰기 없음."""
    orig_complete, orig_dump = R.generator.complete_text, R._dump_input
    try:
        R.generator.complete_text = lambda *a, **k: raw
        R._dump_input = lambda *a, **k: None
        return R.review(_dummy_spec(), {})
    finally:
        R.generator.complete_text, R._dump_input = orig_complete, orig_dump


def test_review_gate_end_to_end() -> None:
    print("\n[6] end-to-end — 검수기가 문자열 판정을 내도 review() 는 bool 로 내보낸다")
    iss = '[{"type":"legal","detail":"The draft invents a vendor quote.","fix":"remove it"}]'
    rv = _review_with_raw('{"passed":"false","severity":"high","ai_tells":[],"issues":%s,"notes":""}' % iss)
    check(rv["passed"] is False, 'passed="false" → 반환값은 bool False', rv["passed"], False)
    check(_gate_blocks(rv), "orchestrator 게이트가 이 판정을 **막는다**(발행 안 됨)", "-", "blocked")

    rv2 = _review_with_raw('{"passed":"true","severity":"none","ai_tells":[],"issues":[],"notes":""}')
    check(rv2["passed"] is True and not _gate_blocks(rv2),
          'passed="true" 는 정상 통과 — 엄격해지기만 할 뿐 통과를 막지 않는다', rv2["passed"], True)

    rv3 = _review_with_raw('{"severity":"low","ai_tells":[],"issues":[],"notes":""}')
    check(rv3["passed"] is False, "passed 키 자체가 없으면 반려(기존 setdefault 동작 유지)",
          rv3["passed"], False)


# ── 7. 표식된 지적이 재작성 피드백에 도달하는가 (copy 전환의 실익) ──────────────────────────
def test_feedback_reach() -> None:
    print("\n[7] 표식이 붙어도 재작성 피드백에 도달한다 — move→copy 의 실익")
    try:
        import orchestrator as O                      # engine/ 은 이미 sys.path 에 있다(42행)
    except Exception as e:                            # yaml 미설치 등
        warn(f"orchestrator import 실패 — 피드백 도달 검증을 수행하지 못했다: {e}")
        return
    pure = next(c[1] for c in CLASSIFY_CASES if c[0].startswith("pure: the exact false positive"))
    out = _apply([pure], OFF)
    fb = O.review_feedback(out)
    check(len(out["issues"]) == 1, "표식 후에도 issues 개수 보존", len(out["issues"]), 1)
    check(pure["detail"][:40].lower() in fb.lower(),
          "표식된 지적의 원문이 재작성 프롬프트에 실려 나간다(move 였다면 0자였다)",
          fb[:120], pure["detail"][:40])
    # 대조: 예전 move 동작을 재현하면 같은 지적이 피드백에서 사라진다
    legacy = _clone(out)
    legacy["issues"] = [i for i in legacy["issues"] if not R._is_disclosure_only(i)]
    check(pure["detail"][:40].lower() not in O.review_feedback(legacy).lower(),
          "대조군(move 재현)에서는 도달하지 못한다 — 이 변경이 메우는 구멍",
          O.review_feedback(legacy)[:80], "(빈 피드백)")


# ── 9. 표식 지적의 재작성 피드백 전달 — 맥락 동반 + 슬롯 비경쟁 (ORDER 2026-07-25-39 ①②) ──────
def test_feedback_annotation() -> None:
    """R4: '고지를 추가하라'가 **맥락 없이** 재작성 모델에 도달하면 안 된다(허위 고지 재생산 경로).
    R3: 표식 지적이 `max_issues` 슬롯을 먹어 `legal`·`factual` 지적을 밀어내면 안 된다.
    ⛔ 해법이 '표식 지적 제외'가 아님도 함께 못 박는다 — 제외하면 move 시절 결함이 재발한다."""
    print("\n[9] 표식 지적 — 맥락과 함께 전달 · 슬롯 비경쟁 (ORDER 39)")
    try:
        import orchestrator as O
    except Exception as e:
        warn(f"orchestrator import 실패 — 피드백 맥락 검증을 수행하지 못했다: {e}")
        return
    pure = next(c[1] for c in CLASSIFY_CASES if c[0].startswith("pure: the exact false positive"))

    # (a) R4 — 표식 지적은 도달하되 맥락 헤더가 **그 앞에** 붙는다
    out = _apply([pure], OFF)
    fb = O.review_feedback(out)
    check(pure["detail"][:40].lower() in fb.lower(),
          "표식 지적은 여전히 피드백에 **도달한다**(제외가 아니다 — [7] 과 같은 성질)", fb[:80], "reaches")
    check("ANNOTATED NOT-APPLICABLE" in fb and "do NOT add a disclosure" in fb,
          "표식 지적에 **맥락 헤더**가 동반된다(없는 고지를 추가하지 말 것)", fb[:120], "header present")
    # ⚠️ index() 가 아니라 find() — 헤더가 없는(=회귀) 상태에서 테스트가 **예외로 죽지 않고 FAIL 로** 떨어져야 한다.
    hdr_at, iss_at = fb.find("ANNOTATED NOT-APPLICABLE"), fb.lower().find(pure["detail"][:40].lower())
    check(hdr_at != -1 and iss_at != -1 and hdr_at < iss_at,
          "맥락 헤더가 지적 **앞**에 온다(모델이 지시를 먼저 읽는다)", (hdr_at, iss_at), "header first")
    check("fix ONLY that other defect" in fb or "ONLY that other defect" in fb,
          "혼합 지적일 때 '다른 결함만 고쳐라'가 함께 간다(오부착 88% 대비)", "-", "mixed-case guidance")

    # (b) 표식이 없으면 헤더도 없다(불필요한 프롬프트 오염 방지)
    plain_only = {"type": "factual", "detail": "The GPU price contradicts the source.", "fix": "Correct it."}
    fb2 = O.review_feedback(_apply([plain_only], OFF))
    check("ANNOTATED NOT-APPLICABLE" not in fb2, "표식 없는 판정에는 헤더가 붙지 않는다", fb2[:80], "no header")

    # (c) R3 — 표식 지적이 실질 지적의 슬롯을 뺏지 않는다 (합성: 실질 7건 + 표식 1건)
    many = [{"type": "legal" if n == 6 else "factual",
             "detail": f"REAL-{n}: definitive negative claim about a named competitor.", "fix": "soften"}
            for n in range(7)]
    mixed = many[:3] + [pure] + many[3:]                     # 표식이 앞쪽(index 3)에 끼어든 배치
    outm = _apply(mixed, OFF)
    fbm = O.review_feedback(outm)
    missing = [n for n in range(6) if f"REAL-{n}:" not in fbm]
    check(not missing, "실질 지적 6건이 표식에 밀리지 않고 전부 실린다", missing, [])
    check("REAL-6:" not in fbm,
          "7번째 실질 지적은 기존 max_issues(6) 상한대로 잘린다 — 표식과 무관한 기존 동작",
          "REAL-6 in feedback", False)
    check(pure["detail"][:40].lower() in fbm.lower(),
          "그러면서도 표식 지적은 **별도 슬롯**으로 함께 간다(제외 아님)", "-", "annotated slot")

    # (d) 실코퍼스 before/after — 수정 전 `copy` 동작에서 밀려났던 지적이 되살아나는가
    files = [f for f in sorted(glob.glob(_CORPUS)) if not f.endswith(".spec.json")]
    if not files:
        warn("코퍼스가 없어 R3 해소의 실데이터 수치를 내지 못했다")
        return
    n_docs = old_lost = new_lost = 0
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if not isinstance(d, dict) or "issues" not in d:
            continue
        out = R._apply_disclosure_policy(_clone(d), OFF)
        marked = out.get("issues_not_applicable") or []
        if not marked:
            continue
        n_docs += 1
        keys = {O._issue_key(i) for i in marked}
        issues = [i for i in (out.get("issues") or []) if isinstance(i, dict)]
        plain = [i for i in issues if O._issue_key(i) not in keys]
        shown_old = issues[:6]                                # 수정 전: 표식 포함 원순서 상위 6
        shown_new = plain[:6]                                 # 수정 후: 실질 지적이 먼저
        old_lost += sum(1 for i in plain[:6] if i not in shown_old)
        fb_new = O.review_feedback(out)
        new_lost += sum(1 for i in shown_new if str(i.get("detail"))[:40].lower() not in fb_new.lower())
    print(f"        표식 문서 {n_docs}건 — 수정 전 슬롯 경쟁으로 탈락한 실질 지적 {old_lost}건 → 수정 후 {new_lost}건")
    check(old_lost > 0, f"수정 전 결함이 코퍼스에서 재현된다(탈락 {old_lost}건)", old_lost, ">0")
    check(new_lost == 0, "수정 후 실질 지적 탈락 0건(R3 해소)", new_lost, 0)


# ── 8. 모순 판정 차단 — passed=true + severity=high (ORDER 2026-07-25-37 ①) ─────────────────
def test_verdict_conflict() -> None:
    """양방향으로 친다: 모순 판정은 **막히고**, 정상 통과는 **막히지 않는다**.

    ⚠️ 이 검사는 ORDER 19 가 폐기한 기전과 방향이 반대다 — 구조화 필드(`severity`) 값 비교로
    True→False(엄격)만 한다. 통과를 넓히는 코드는 여기에도, 프로덕션에도 없다([2]가 계속 증명).
    """
    print("\n[8] 모순 판정 차단 — passed=true + severity='high' 는 신뢰할 수 없다")

    # (a) 단위: 필드 값 비교 진리표
    for sev, want in (("high", True), ("HIGH", True), (" High ", True),
                      ("none", False), ("low", False), ("medium", False), ("unknown", False),
                      (None, False), (["high"], False), ("higher", False)):
        got = bool(R._verdict_conflict({"passed": True, "severity": sev}))
        check(got is want, f"단위: passed=True · severity={sev!r} → 모순={want}", got, want)
    check(not R._verdict_conflict({"passed": False, "severity": "high"}),
          "단위: 이미 반려(passed=False)면 모순 아님(중복 처리 없음)", "-", "no conflict")

    # (b) end-to-end: 발행 게이트까지
    def raw(p, sev, iss='[]'):
        return '{"passed":%s,"severity":"%s","ai_tells":[],"issues":%s,"notes":""}' % (p, sev, iss)

    legal = '[{"type":"legal","detail":"false first-person testing claim","fix":"remove"}]'
    for label, p, sev, iss in (("bool true + high", "true", "high", legal),
                               ('문자열 "ok" + high', '"ok"', "high", legal),
                               ("대문자 HIGH", "true", "HIGH", legal)):
        rv = _review_with_raw(raw(p, sev, iss))
        check(rv["passed"] is False and _gate_blocks(rv),
              f"모순 판정({label}) → 반려 · 게이트 차단", rv["passed"], False)
        check(rv.get("severity") == sev,
              f"모순 판정({label}) → severity 는 검수기 원본 그대로 보존", rv.get("severity"), sev)
        check("verdict conflict" in (rv.get("notes") or ""),
              f"모순 판정({label}) → 사유가 notes 에 기록(관측 가능)", (rv.get("notes") or "")[:60], "verdict conflict")

    # (c) 반대 방향 — 정상 통과를 막지 않는다(과잉 차단 = 매일 0편 사고)
    for sev in ("none", "low"):
        rv = _review_with_raw(raw("true", sev))
        check(rv["passed"] is True and not _gate_blocks(rv),
              f"정상 통과(passed=true · severity={sev!r})는 그대로 통과", rv["passed"], True)
    rv = _review_with_raw(raw("true", "medium", legal))
    check(rv["passed"] is True,
          "medium 은 **막지 않는다** — 임계 변경은 정책 결정(PM·사람 몫, ORDER 37 ④). 임의 강화 방지 회귀",
          rv["passed"], True)

    # (d) 새 로직이 `_apply_disclosure_policy` 안으로 새어 들어가지 않았는지(ORDER 19 경계 유지)
    src = open(os.path.join(_HERE, "reviewer.py"), encoding="utf-8").read()
    body = src[src.index("def _apply_disclosure_policy"):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    check("_verdict_conflict" not in body,
          "모순 검사는 고지 후처리 밖에 있다(_apply_disclosure_policy 는 여전히 판정을 안 만진다)",
          "_verdict_conflict in body", False)

    # (e) 실코퍼스 영향 — 이 규칙으로 통과→반려가 되는 과거 판정 건수(발행 카덴스 영향 관측)
    files = [f for f in sorted(glob.glob(_CORPUS)) if not f.endswith(".spec.json")]
    n_docs = n_pass = n_flip = 0
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if not isinstance(d, dict) or "issues" not in d:
            continue
        n_docs += 1
        if not d.get("passed"):
            continue
        n_pass += 1
        if R._verdict_conflict(d):
            n_flip += 1
            warn(f"코퍼스에서 모순 판정 발견 — {os.path.basename(path)} "
                 f"(passed={d.get('passed')!r}, severity={d.get('severity')!r})")
    if n_docs:
        print(f"        코퍼스 {n_docs}문서 · 통과 {n_pass}건 → 이 규칙으로 반려 전환 {n_flip}건")
        check(True, f"영향 측정 완료(통과 {n_pass}건 중 {n_flip}건 전환) — 발행 카덴스 영향 관측치")
    else:
        warn("코퍼스가 없어 이 규칙의 발행 영향 수치를 내지 못했다")


# ── 10. 발행 분기 3갈래 — high=반려 / medium=보류 / none·low=발행 (ORDER 2026-07-25-40) ────────
def test_hold_medium() -> None:
    """⛔ medium 은 **반려가 아니라 보류**다 — `passed` 는 그대로 두고 발행 시점만 미룬다."""
    print("\n[10] 발행 분기 — high=반려 · medium=사람 보류 · none/low=즉시 발행 (ORDER 40)")
    try:
        import orchestrator as O
    except Exception as e:
        warn(f"orchestrator import 실패 — 보류 분기 검증을 수행하지 못했다: {e}")
        return
    from content import human_gate as HG

    HSG_ON = {"enabled": True, "sample_pct": 10}
    HSG_OFF = {"enabled": False, "sample_pct": 0}
    plain = next(s for s in (f"selftest-slug-{n}" for n in range(500)) if not HG.is_sampled(s, 10))
    sampled = next(s for s in (f"selftest-slug-{n}" for n in range(500)) if HG.is_sampled(s, 10))

    def rv(sev, n_iss=2, passed=True):
        return {"passed": passed, "severity": sev, "ai_tells": [],
                "issues": [{"type": "factual", "detail": f"objection {i}", "fix": "fix it"} for i in range(n_iss)],
                "notes": ""}

    # (a) medium → 보류 (표본 여부와 무관)
    why = O._hold_reasons(rv("medium"), plain, HSG_ON)
    check(bool(why) and any("medium" in w for w in why),
          "severity=medium 통과분은 표본이 아니어도 **보류**된다", why, "['severity=medium…']")
    check(bool(O._hold_reasons(rv("medium"), plain, HSG_OFF)),
          "human_sample_gate 가 꺼져 있어도 medium 보류는 작동한다", "-", "held")

    # (b) none/low → 즉시 발행 (과잉 보류로 발행량이 죽으면 안 된다)
    for sev in ("none", "low"):
        check(not O._hold_reasons(rv(sev), plain, HSG_ON),
              f"severity={sev!r} 통과분은 보류 없이 발행 큐로", O._hold_reasons(rv(sev), plain, HSG_ON), [])

    # (c) 기존 표본 게이트는 그대로 살아 있다
    check(any("표본" in w for w in O._hold_reasons(rv("low"), sampled, HSG_ON)),
          "표본으로 뽑힌 슬러그는 기존대로 보류(기능 보존)", "-", "sample hold")
    both = O._hold_reasons(rv("medium"), sampled, HSG_ON)
    check(len(both) == 2, "medium + 표본이면 사유가 둘 다 기록된다", both, "2 reasons")

    # (d) high → 애초에 발행 분기에 도달하지 못한다(37 의 정합성 게이트가 반려)
    r_high = _review_with_raw('{"passed":true,"severity":"high","ai_tells":[],'
                              '"issues":[{"type":"legal","detail":"x","fix":"y"}],"notes":""}')
    check(r_high["passed"] is False and _gate_blocks(r_high),
          "severity=high 는 보류가 아니라 **반려** — 발행 분기 이전에서 막힌다", r_high["passed"], False)

    # (e) 보류는 판정을 바꾸지 않는다(반려로 오해되면 안 된다)
    v = rv("medium")
    O._hold_reasons(v, plain, HSG_ON)
    check(v["passed"] is True and v["severity"] == "medium",
          "보류 판단은 판정을 **읽기만** 한다(passed·severity 불변)", (v["passed"], v["severity"]), (True, "medium"))

    # (f) 사람이 읽는 사유 본문 — 지적 원문 + 처리 명령이 들어 있는가
    notice = O._hold_notice("my-slug", "cheap vps", rv("medium", 3), ["severity=medium(미해소 지적 3건)"])
    for want in ("보류 사유", "objection 0", "--approve my-slug", "human_gate.reject('my-slug')",
                 "dist/review/my-slug.json"):
        check(want in notice, f"사유 본문에 {want!r} 포함", notice[:60], want)
    check("통과" in notice and "반려 아님" in notice,
          "사유 본문이 '반려가 아니라 보류'임을 명시한다", "-", "not a rejection")

    # (g) 사이드카 파일 — hold/reason/approve/reject 왕복 (임시 디렉터리, 리포 dist 는 건드리지 않는다)
    tmp = tempfile.mkdtemp(prefix="human_gate_selftest_")
    p0, q0, r0 = HG.PENDING_DIR, HG.QUEUE_DIR, HG.REJECTED_DIR
    try:
        HG.PENDING_DIR = os.path.join(tmp, "pending")
        HG.QUEUE_DIR = os.path.join(tmp, "queue")
        HG.REJECTED_DIR = os.path.join(tmp, "review")
        notice_s1 = O._hold_notice("s1", "cheap vps", rv("medium", 2), ["severity=medium(미해소 지적 2건)"])
        HG.hold("s1", "<html>doc</html>", reason=notice_s1)
        check(HG.reason("s1").startswith("보류 사유"), "hold(reason=…) 가 사유 사이드카를 남긴다",
              HG.reason("s1")[:30], "보류 사유…")
        check(HG.pending() == ["s1"], "사유 파일이 pending 목록을 오염시키지 않는다(*.html 만 집계)",
              HG.pending(), ["s1"])
        rep = HG.pending_report()
        check(len(rep) == 1 and "--approve s1" in rep[0],
              "--list-pending 출력에 사유·명령이 함께 나온다(slug 만 나오지 않는다)", rep[0][:40], "with reason")
        HG.approve("s1")
        check(os.path.exists(os.path.join(HG.QUEUE_DIR, "s1.html")) and not HG.reason("s1"),
              "승인 → 큐로 이동 · 사유 사이드카는 따라가지 않는다", "-", "moved & cleaned")
        HG.hold("s2", "<html>doc2</html>", reason=notice)
        dst = HG.reject("s2")
        check(os.path.exists(dst) and not os.path.exists(os.path.join(HG.PENDING_DIR, "s2.html")),
              "거부 → 발행하지 않고 dist/review 로 보존", os.path.basename(dst), "s2.human-rejected.html")
        check(not os.path.exists(os.path.join(HG.QUEUE_DIR, "s2.html")),
              "거부된 글은 큐에 **들어가지 않는다**", "-", "not queued")
    finally:
        HG.PENDING_DIR, HG.QUEUE_DIR, HG.REJECTED_DIR = p0, q0, r0
        shutil.rmtree(tmp, ignore_errors=True)

    # (i) 알림은 **부가 기능** — 알림 경로가 죽어도 발행 파이프라인이 멈추면 안 된다(ORDER 40 ③)
    try:
        from monitor import alerts as A
        orig_send = A.send
        try:
            A.send = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("selftest: 알림 채널 장애"))
            O._notify_hold("s1", "kw", rv("medium"), ["severity=medium"])   # 예외가 새어 나오면 실패
            check(True, "알림 실패가 보류·발행 경로를 깨지 않는다(예외 삼킴)")
        finally:
            A.send = orig_send
    except ImportError as e:
        warn(f"monitor.alerts import 실패 — 알림 격리 검증을 수행하지 못했다: {e}")
    except Exception as e:
        check(False, "알림 실패가 보류·발행 경로를 깨지 않는다(예외 삼킴)", f"{type(e).__name__}: {e}", "swallowed")

    # (h) 실코퍼스 빈도 — 매일 보류만 쌓이면 사람이 감당 못 해 게이트가 형해화된다(ORDER 40 ④)
    files = [f for f in sorted(glob.glob(_CORPUS)) if not f.endswith(".spec.json")]
    n_pass = n_med = 0
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if not isinstance(d, dict) or "issues" not in d or not d.get("passed"):
            continue
        n_pass += 1
        if str(d.get("severity", "")).strip().lower() == "medium":
            n_med += 1
    if n_pass:
        pct = n_med * 100.0 / n_pass
        print(f"        코퍼스 통과 {n_pass}건 중 medium {n_med}건 = {pct:.1f}% "
              f"→ daily_generate=1 기준 약 {100 / pct:.1f}일에 1건 보류")
        check(pct < 50, f"보류 빈도 {pct:.1f}% — 통과분의 절반을 넘으면 사람이 감당 못 한다(형해화 경보)",
              f"{pct:.1f}%", "<50%")
    else:
        warn("코퍼스가 없어 보류 빈도를 측정하지 못했다")


def main(argv: list[str]) -> int:
    print("reviewer_selftest — 고지 처리 회귀 테스트 (LLM 미호출) · 불변식: 판정 불변")
    test_classify()
    test_removed_machinery()
    test_holes()
    test_invariant()
    test_invariant_under_collapse()
    test_monetization_failclosed()
    test_replay(require="--require-replay" in argv)
    test_passed_coercion()
    test_review_gate_end_to_end()
    test_feedback_reach()
    test_verdict_conflict()
    test_feedback_annotation()
    test_hold_medium()
    print(f"\n결과: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED'}"
          f"{f' · WARN {len(_warns)}' if _warns else ''}")
    for f in _fails:
        print(f"  - FAIL {f}")
    for w in _warns:
        print(f"  - WARN {w}")
    return 0 if not _fails else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
