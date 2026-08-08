"""orchestrator.py — 자동화 파이프라인 스파인 (AUTOMATION.md §2).

스케줄러(cron / Claude Code 예약 에이전트)가 단계별로 호출한다.
    python engine/orchestrator.py --stage <ingest|monitor|research|generate|publish|report>

🟢 ingest/research/generate/monitor/report = 자유 자동화 (리스크 0)
🟡 publish = 게이트 자동화 (품질 게이트 통과분 + 킬스위치 + 일일 cap 준수)
⛔ 트래픽/클릭 생성은 어떤 단계에도 없다 (docs/RESEARCH.md F3).
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import sys

# stdout/stderr 를 UTF-8 로 강제 — Windows cp949 콘솔에서 '—'(—) 등 출력 시 UnicodeEncodeError 로
# generate 전체가 죽던 문제 방지(20:00 배치는 PYTHONIOENCODING 미설정 → 매일 0편이었음, 2026-07-09).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import yaml  # pip install pyyaml

from monitor import killswitch
# 아래 모듈들은 AUTOMATION.md §2 의 레이어대로 채운다 (어댑터/구현 TODO):
#   ingest.adsense_api / ingest.search_console / ingest.pagespeed
#   content.keyword_research / content.generator / content.publisher
#   optimize.rpm_analyzer / optimize.experiment_advisor
#   monitor.health / monitor.alerts / store.db


def load_config() -> dict:
    cfg = {}
    for name in ("guardrails", "content", "niches", "topics", "schedule", "sites"):
        with open(f"config/{name}.yaml", encoding="utf-8") as f:
            cfg[name] = yaml.safe_load(f)
    return cfg


def stage_ingest(cfg):
    """AdSense/Search Console/PageSpeed → store(DB). 읽기 전용(F3: 트래픽/클릭 생성 없음).

    각 어댑터는 자격증명 없으면 스스로 스킵(0 반환). 개별 오류도 스킵하고 계속.
    """
    from store import db
    db.init()
    urls = [s.get("cms", {}).get("base_url") or f"https://{s['domain']}"
            for s in cfg["sites"]["sites"]]
    n = 0
    try:
        from ingest import pagespeed
        c = pagespeed.ingest(urls, cfg, db); n += c; print(f"  pagespeed: {c} rows")
    except Exception as e:
        print(f"  pagespeed skip: {e}")
    try:
        from ingest import search_console
        c = search_console.ingest(cfg, db); n += c; print(f"  search_console: {c} rows")
    except Exception as e:
        print(f"  search_console skip: {e}")
    try:
        from ingest import adsense_api
        c = adsense_api.ingest(cfg, db); n += c; print(f"  adsense: {c} rows")
    except Exception as e:
        print(f"  adsense skip: {e}")
    print(f"ingest: {n} metric rows → {db.DB_PATH}")
    return n


def stage_research(cfg):
    """시드 키워드 스코어링 → dist/research/backlog.json (generate 가 소비). 있으면 SC 실수요 보정."""
    import json
    from content import keyword_research
    from store import db
    db.init()
    backlog = keyword_research.run(cfg["topics"], cfg["niches"], db)
    # 콜드스타트 우선순위: topics.sequencing.next_batch_priority 에 명시한 '이길 수 있는' 키워드를
    # 점수와 무관하게 앞으로 끌어올린다(신생 사이트가 경쟁 센 헤드텀보다 롱테일을 먼저 쓰도록).
    prio = ((cfg["topics"].get("sequencing") or {}).get("next_batch_priority") or [])
    if prio:
        rank = {k: i for i, k in enumerate(prio)}
        backlog.sort(key=lambda e: (rank.get(e["keyword"], len(prio)), -e.get("score", 0)))
    os.makedirs("dist/research", exist_ok=True)
    with open("dist/research/backlog.json", "w", encoding="utf-8") as f:
        json.dump(backlog, f, ensure_ascii=False, indent=2)
    print(f"research: {len(backlog)} 시드 스코어 (우선 {len(prio)}개 선순위) → dist/research/backlog.json")
    for e in backlog[:5]:
        print(f"  {e['score']:.3f} [{e['cluster']}/{e['intent']}] {e['keyword']}")
    return backlog


# ── 반려 초안 보존 (사후 재검수·감사) ───────────────────────────────────────────────
# 반려된 초안은 지금까지 어디에도 남지 않았다 — 판정 JSON 만 저장하고 통과분만 dist/queue 로 갔다.
# 그래서 "반려가 글 탓인가 도구 탓인가"를 사후에 검증할 수 없었다(2026-07-24: 4건 원본 소실,
# team/reports/2026-07-24-11-review.md ③). 판정 JSON(dist/review/<slug>.json)과 **같은 slug** 로
# 짝을 맞춰 초안 spec 자체를 남긴다 → load_rejected_spec()/--rereview 로 같은 초안 재검수 가능.
# 저장 대상은 ContentSpec 필드뿐이다(자격증명·.env·환경변수는 spec 에 존재하지 않는다).
def _keep_rejected_spec(spec, *, stage: str, keyword: str, attempt: int, reasons) -> str:
    """반려된 초안 spec → dist/review/<slug>.spec.json. 실패해도 파이프라인을 멈추지 않는다(부가 기능)."""
    import dataclasses
    import datetime as _dt
    import json
    try:
        data = dataclasses.asdict(spec)          # ContentSpec 전 필드(재검수에 필요한 grounding_context 포함)
        data["_reject"] = {"stage": stage, "keyword": keyword, "attempt": attempt,
                           "at": _dt.datetime.now().isoformat(timespec="seconds"),
                           "reasons": [str(x) for x in (reasons or [])]}
        payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)  # 문자열로 먼저 → 부분 파일 방지
        os.makedirs("dist/review", exist_ok=True)
        path = f"dist/review/{spec.slug}.spec.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
        return path
    except Exception as e:                       # 디스크·권한·직렬화 실패 등 — 보존 실패는 로그만 남기고 계속
        print(f"  (초안 보존 실패 — 파이프라인은 계속) {type(e).__name__}: {e}")
        return ""


def load_rejected_spec(slug: str):
    """보존된 반려 초안(dist/review/<slug>.spec.json) → ContentSpec 복원. 재검수 입력으로 그대로 쓴다."""
    import dataclasses
    import json
    from content.generator import ContentSpec
    with open(f"dist/review/{slug}.spec.json", encoding="utf-8") as f:
        data = json.load(f)
    names = {f.name for f in dataclasses.fields(ContentSpec)}
    kw = {k: v for k, v in data.items() if k in names}                    # _reject 등 메타는 버림
    kw["breadcrumb"] = [tuple(b) if isinstance(b, list) else b            # JSON 은 튜플을 잃는다 → 원형 복구
                        for b in (kw.get("breadcrumb") or [])]            # (renderer 가 (name, url) 로 언팩)
    return ContentSpec(**kw)


def rereview(slug: str, cfg) -> dict:
    """(감사 전용) 보존된 초안으로 검수를 다시 돌린다 → dist/review/<slug>.rereview.json.

    발행 경로와 무관하다 — 통과해도 큐에 넣지 않는다(G1: 발행은 REVIEW pass + 사람 승인 + OPS 실행)."""
    import json
    from content import reviewer
    if not os.path.exists(f"dist/review/{slug}.spec.json"):          # 보존 목록을 알려주고 종료(트레이스백 대신)
        kept = [os.path.basename(p)[:-len(".spec.json")] for p in sorted(glob.glob("dist/review/*.spec.json"))]
        raise SystemExit(f"보존된 초안 없음: dist/review/{slug}.spec.json / 보존된 slug: {', '.join(kept) or '(없음)'}")
    rv = reviewer.review(load_rejected_spec(slug), cfg["content"])
    with open(f"dist/review/{slug}.rereview.json", "w", encoding="utf-8") as f:
        json.dump(rv, f, ensure_ascii=False, indent=2)
    print(f"rereview {slug}: passed={rv.get('passed')} severity={rv.get('severity')} "
          f"issues={len(rv.get('issues', []))} → dist/review/{slug}.rereview.json (발행 큐에는 넣지 않음)")
    return rv


# ── 표식(not_applicable) 지적을 재작성 모델에 넘길 때 반드시 함께 가는 맥락 (ORDER 2026-07-25-39 ①) ──
# 왜: `_apply_disclosure_policy` 가 move→copy 로 바뀌면서(커밋 7492102) 표식된 고지 지적이 `issues` 에
#   남아 재작성 프롬프트로 **그대로** 흘러갔다. 그 지적의 fix 는 대개 "Add a disclosure line…" 이라,
#   광고도 제휴도 없는 이 사이트에서 그대로 따르면 **없는 상업관계를 선언하는 허위 진술**이 만들어진다.
#   실제로 라이브 2편이 그런 문장을 달고 있었다(원인 시기는 조건부화 이전이지만, copy 전환이 재발 경로를 열었다).
# ⛔ 해법은 '표식 지적을 빼는 것'이 **아니다** — 표식은 어휘 추측이라 88%가 오부착이고, 빼면 그 안의
#   진짜 결함(허위 1인칭·경쟁사 부정 단정 등)까지 사라진다(= move 시절 결함의 재발).
# → 지적은 **그대로 보내되 맥락을 붙인다.** 아래 헤더가 표식 지적 묶음 **바로 앞**에 놓인다.
_NA_FEEDBACK_HEADER = (
    "ANNOTATED NOT-APPLICABLE by the review harness — read this before the objection(s) that follow: "
    "the ad/affiliate/sponsorship DISCLOSURE part of them does NOT apply. This site serves no advertising "
    "and this draft carries no affiliate or referral links, so do NOT add a disclosure, affiliate, "
    "sponsorship or 'we may earn a commission' line, and ignore any instruction below telling you to add "
    "one — writing such a line would itself be a false statement. This label is a lexical guess and is "
    "known to over-match: if an objection below ALSO states any OTHER defect, fix ONLY that other defect")

# 표식 지적에 배정하는 **별도 슬롯**(ORDER 39 ②). max_issues 를 놓고 경쟁시키지 않는다 —
# 실측(36-review R3): 지적 12건 문서에서 표식 1건이 슬롯을 먹어 `legal` 지적(경쟁사 부정 단정)이 밀려났다.
_MAX_ANNOTATED_ISSUES = 2


def _issue_key(i: dict) -> tuple:
    """지적 동일성 키 — `issues_not_applicable` 의 **사본**을 원본과 맞추기 위한 것.
    사본은 `dict(원본, status=…, reason=…)` 이므로 세 필드가 같으면 같은 지적이다.
    (여기서 어휘 재분류를 하지 않는다 — 분류는 reviewer 소관이고 orchestrator 는 그 결과만 읽는다.)"""
    return (str(i.get("type")), str(i.get("detail")), str(i.get("fix")))


def review_feedback(rv: dict, *, max_issues: int = 6, max_tells: int = 6, max_chars: int = 400) -> str:
    """검수 판정(rv) → 재생성 프롬프트에 넣을 피드백 문자열. **ai_tells 원문을 반드시 포함한다.**

    reviewer.review() 는 두 종류를 돌려준다:
      - `issues[]`  : {type, detail, fix} — 무엇이 문제인지 **설명**
      - `ai_tells[]`: 검수기가 "이 문장이 AI 티다"라고 **지목한 문장·구절 원문**
        (예: '"for the price of a coffee or two each month" — stock cliché/filler')

    예전 판(2026-07-25 이전)은 `"; ".join(fixes) or "; ".join(ai_tells)` 였다 — `or` 는 앞이
    비었을 때만 뒤를 쓴다. 실측: dist/review 판정 55건 중 반려 26건, 그중 ai_tells 를 가진 22건이
    **전부** issues 도 갖고 있었다 → ai_tells 가 재작성 프롬프트에 도달한 건 **0/22**.
    즉 검수기가 지목한 문장을 재작성 모델은 한 번도 보지 못한 채 다시 썼다(ORDER 2026-07-25-20 ②).
    → 이제 **둘 다** 넣는다. 지목 문장을 먼저(모델이 가장 확실히 고칠 수 있는 지시라서), 설명을 뒤에.

    ⚠️ 재작성 '횟수'는 늘리지 않는다(비용) — 같은 1회 재작성에 정보를 더 주는 변경일 뿐이다.

    표식(`issues_not_applicable`) 처리 (ORDER 2026-07-25-39, 위 `_NA_FEEDBACK_HEADER` 주석):
      · 표식된 지적도 **보낸다**(빼면 그 안의 진짜 결함까지 사라진다) — 단 **맥락 헤더와 함께**.
      · 표식된 지적은 **별도 슬롯**(`_MAX_ANNOTATED_ISSUES`)을 쓴다 → 표식 없는 지적의 자리를 뺏지 않는다.
    """
    def _clip(s) -> str:
        s = " ".join(str(s or "").split())
        return s[:max_chars] + ("…" if len(s) > max_chars else "")

    def _line(i: dict, tag: str = "") -> str:
        return f"[{tag}{i.get('type')}] {_clip(i.get('detail'))} → {_clip(i.get('fix'))}"

    parts = []
    tells = [t for t in (_clip(x) for x in (rv.get("ai_tells") or [])) if t][:max_tells]
    if tells:
        parts.append("AI-TELL SENTENCES the reviewer flagged — rewrite each of these in a different, "
                     "plainer voice (do not merely delete the words): " + " | ".join(tells))
    issues = [i for i in (rv.get("issues") or []) if isinstance(i, dict)]   # 비정형 항목은 건너뛴다(크래시 방지)
    annotated_keys = {_issue_key(i) for i in (rv.get("issues_not_applicable") or [])
                      if isinstance(i, dict)}
    plain = [i for i in issues if _issue_key(i) not in annotated_keys]
    annotated = [i for i in issues if _issue_key(i) in annotated_keys]
    parts += [_line(i) for i in plain[:max_issues]]                        # 실질 지적이 슬롯을 먼저 가져간다
    if annotated:
        parts.append(_NA_FEEDBACK_HEADER + ": "
                     + " | ".join(_line(i, "not_applicable · ")
                                  for i in annotated[:_MAX_ANNOTATED_ISSUES]))
    return "; ".join(parts)


# ── 사람 승인 보류(human_gate) 판단 — 발행 분기 전용 (ORDER 2026-07-25-40) ────────────────────
# 무엇: `severity == "medium"` 으로 **통과한** 글은 큐로 바로 보내지 않고 사람 승인 대기로 **보류**한다.
# ⛔ 반려가 아니다 — `passed` 는 검수기 원본 그대로다. **발행 시점만 미룬다**(사람이 승인하면 그대로 나간다).
# 왜 medium 인가(37-review ④, 사람 결정 = 권고 A): 문제의 본질이 "medium 임계가 느슨하다"가 아니라
#   **검수기의 severity 부여가 흔들린다**는 것이었다(프롬프트상 high 여야 할 날조 인용을 medium 으로 낮춘 실측).
#   흔들리는 자동 판정을 또 다른 자동 규칙으로 덮으면 오탐이 하나 더 생긴다 → 그 자리에 **사람**을 놓는다.
# 실측 빈도(코퍼스 실측): 통과 30건 중 medium 7건 = **23.3%** → daily_generate=1 기준 **약 4.3일에 1건** 보류.
#   (이 수치는 reviewer_selftest.py `[10](h)` 가 매 실행 재측정한다 — 50% 를 넘으면 사람이 감당 못 해
#    게이트가 형해화되므로 그때는 정책을 다시 봐야 한다.)
_HOLD_SEVERITY = "medium"


def _factual_open(rv) -> list:
    """미해소 factual 지적 목록. **type 필드만** 읽는다 — 판정 텍스트를 해석하지 않는다.

    ⛔ '양성 factual' 을 가려내는 텍스트 분류기를 만들지 않는다: ORDER 19 가 세 라운드 폐기했고
       감사에서 21종 중 13종이 뚫린 기전이다. 있으면 있는 것으로 센다.
    """
    return [i for i in ((rv or {}).get("issues") or [])
            if isinstance(i, dict) and str(i.get("type", "")).strip().lower() == "factual"]


def _hold_reasons(rv, slug: str, hsg: dict, *, trend_axis: bool = False) -> list[str]:
    """보류 사유 목록(비어 있으면 즉시 발행 큐). 판정을 **읽기만** 한다.

    `trend_axis=True` 면 factual 지적이 하나라도 남으면 severity 와 무관하게 보류한다(아래).
    기본값 False = 기존 경로 동작 무변화.
    """
    from content import human_gate
    reasons = []
    sev = str((rv or {}).get("severity", "")).strip().lower()
    if sev == _HOLD_SEVERITY:
        n = len([i for i in ((rv or {}).get("issues") or []) if isinstance(i, dict)])
        reasons.append(f"severity=medium(미해소 지적 {n}건)")
    # 트렌드 축 한정 — factual 이 하나라도 남으면 severity 와 무관하게 사람 보류.
    # 왜 축 한정인가(49·50-review 실측): 통과 39건 중 28건(71.8%)이 미해소 factual 을 안고 통과했고
    #   그중 18편은 low/none 이라 사람 눈에 닿은 적이 없다 — 탐지가 아니라 탐지 이후 처리가 문제였다.
    #   전 축에 걸면 통과분 71.8% 가 보류 큐로 가 selftest [10] 의 50% 임계를 넘겨 게이트가 형해화된다.
    #   트렌드 축은 하루 1편이라 비용이 **1건/일**로 갇힌다.
    # ⛔ severity 임계는 건드리지 않는다. 이건 축 한정 **라우팅**이지 임계 조정이 아니다.
    if trend_axis:
        fx = _factual_open(rv)
        if fx:
            reasons.append(f"트렌드 축 factual 미해소 {len(fx)}건(축 한정 정책)")
    if hsg.get("enabled") and human_gate.is_sampled(slug, hsg.get("sample_pct", 0)):
        reasons.append(f"품질 캘리브레이션 표본({hsg.get('sample_pct')}%)")
    return reasons


def _hold_notice(slug: str, keyword: str, rv, reasons: list[str]) -> str:
    """사람이 승인 화면·파일에서 **바로 읽는** 보류 사유 본문(ORDER 40 ②)."""
    lines = [f"보류 사유: {' + '.join(reasons)}",
             f"키워드: {keyword} · slug: {slug}",
             f"검수 판정: passed={(rv or {}).get('passed')!r} severity={(rv or {}).get('severity')!r} "
             f"(상세: dist/review/{slug}.json)",
             "",
             "⚠️ 이 글은 검수를 **통과**했다(반려 아님). 검수기가 스스로 medium 을 붙였다는 뜻은",
             "   '내보내도 되지만 지적이 남아 있다'이고, 그 판단이 흔들린 사례가 실측돼 사람이 한 번 본다.",
             "아래 지적이 실제로 남아 있는지 본문에서 확인하라:"]
    for n, i in enumerate([x for x in ((rv or {}).get("issues") or []) if isinstance(x, dict)][:8]):
        detail = " ".join(str(i.get("detail") or "").split())[:400]
        fix = " ".join(str(i.get("fix") or "").split())[:200]
        lines.append(f"  [{n + 1}] ({i.get('type')}) {detail}")
        if fix:
            lines.append(f"       → 제안: {fix}")
    tells = [" ".join(str(t).split())[:200] for t in ((rv or {}).get("ai_tells") or [])][:6]
    if tells:
        lines.append("  AI 티로 지목된 문장: " + " | ".join(tells))
    lines += ["",
              f"승인(발행): python engine/orchestrator.py --approve {slug}",
              f"거부(미발행·보존): python -c \"import sys;sys.path.insert(0,'engine');"
              f"from content import human_gate;print(human_gate.reject('{slug}'))\"",
              "미리보기: dist/pending_approval/%s.html 을 브라우저로 열어라" % slug]
    return "\n".join(lines)


def _notify_hold(slug: str, keyword: str, rv, reasons: list[str]) -> None:
    """보류 발생 알림(ORDER 40 ③). ⚠️ 부가 기능 — 어떤 실패도 파이프라인을 멈추지 않는다.
    `alerts.send` 만 호출한다(daily.sh 는 건드리지 않는다 — 34-ops 와 충돌 방지)."""
    try:
        from monitor import alerts
        n = len([i for i in ((rv or {}).get("issues") or []) if isinstance(i, dict)])
        alerts.send(
            f"[stack. 승인 대기] {keyword}\n"
            f"사유: {' + '.join(reasons)} · 미해소 지적 {n}건\n"
            f"검수는 통과했으나 발행을 보류했다(반려 아님). 사람이 확인해야 나간다.\n"
            f"사유 전문: dist/pending_approval/{slug}.reason.txt\n"
            f"승인: python engine/orchestrator.py --approve {slug}")
    except Exception as e:                      # 알림 경로 장애가 발행 파이프라인을 깨면 안 된다
        print(f"  (보류 알림 실패 — 파이프라인은 계속) {type(e).__name__}: {e}")


# ══ 트렌드 전용 축 (ORDER 2026-08-01-45) ═══════════════════════════════════════════════════
# 왜 '정렬'이 아니라 '필터'인가: `stage_research` 는 `next_batch_priority` 로 백로그를 **정렬만** 하고
# `stage_generate` 는 그 상위 10개를 시드로 쓴다. 그 상위 10에는 비트렌드 토픽이 섞이므로
# 정렬만으로는 "전용"이 되지 않는다 → 트렌드 모드에서는 `trend_axis.candidates` **만** 시드가 된다.
#
# 🔴 후보가 소진되면 **기존 백로그로 폴백하지 않는다** — 그날은 0편으로 끝낸다.
#    0편은 정지 사유가 아니다(`guardrails.zero_generation_alert_days` 는 알림만 낸다).
#    폴백을 허용하면 "트렌드 전용"이 첫날부터 이름뿐인 장식이 된다.
#    (config `trend_axis.fallback_to_backlog: true` 로 사람이 명시적으로 켤 수는 있다 — 기본은 false.)
def _trend_axis(cfg) -> dict:
    t = cfg.get("topics")
    return (t.get("trend_axis") or {}) if isinstance(t, dict) else {}


def _trend_seeds(cfg) -> tuple[list, dict]:
    """trend_axis.candidates → ([(keyword, cluster)…], {keyword: 후보}). config 기재 순 = 우선순위."""
    seeds, by_kw = [], {}
    for c in (_trend_axis(cfg).get("candidates") or []):
        kw = str((c or {}).get("keyword") or "").strip()
        if not kw or kw in by_kw:
            continue
        seeds.append((kw, str(c.get("cluster") or "ai-coding-tools")))
        by_kw[kw] = c
    return seeds, by_kw


def _trend_hints(cand: dict) -> dict:
    """후보의 **사람이 미리 확정한** 식별자 → generator hints (ORDER 45 ③).

    `official_url` → 그라운딩 페치 대상(모델 URL 발견을 아예 건너뛴다),
    `github`/`npm`/`kind`/`why` → 관측 대상(모델 식별자 발견을 아예 건너뛴다).
    이 두 발견 단계가 07-08 반려 루프의 원인이었으므로, 트렌드 축에서는 경로 자체를 제거한다.
    """
    targets, per_entity = [], []
    for e in (cand.get("entities") or []):
        if not isinstance(e, dict):
            continue
        t = {"name": e.get("name")}
        for k in ("kind", "why", "github", "npm", "statuspage", "dockerhub"):
            if e.get(k):
                t[k] = e[k]
        targets.append(t)
        per_entity.append([u for u in ([e.get("official_url")] + list(e.get("extra_urls") or [])) if u])
    # URL 순서는 **제품별 라운드로빈**이다. 그냥 이어 붙이면 `grounding.max_sources`(기본 5)에서 잘릴 때
    # 뒤쪽 제품의 1순위 소스가 통째로 날아가 **한쪽만 근거가 있는 비대칭 비교**가 된다
    # (30-content 반려 2건의 사유가 정확히 비대칭 비교였다).
    urls = []
    for i in range(max((len(p) for p in per_entity), default=0)):
        for p in per_entity:
            if i < len(p) and p[i] not in urls:
                urls.append(p[i])
    return {"targets": targets, "source_urls": urls}


def trend_preflight(cand: dict, cfg) -> tuple[bool, str, dict | None]:
    """생성 **전에** 관측표가 실제로 서는지 확인한다 (ORDER 45 ②·④). (통과?, 사유, 관측결과)

    LLM 호출 **앞**에 둔 이유: 여기서 걸리는 후보는 어차피 표 없이 글만 나오므로, 비싼 생성을 한 뒤
    버리는 것보다 공개 API GET 몇 번으로 먼저 떨어뜨리는 편이 싸다(실패해도 토큰 비용 0).
      ④ 등가성 — 선언된 `kind` 가 서로 다르면 비교 자체가 성립하지 않는다 → 후보를 **버린다**.
      ② 관측표 — `observed.usable()` 을 못 넘으면 그 토픽을 **버린다**(표 없는 트렌드 글은 큐에 넣지 않는다).
    ⚠️ 관측은 **1회**다. 수치가 마음에 안 든다고 짝을 바꿔 다시 재지 않는다(43c-review ③ · ORDER 45 ④).
    """
    from content import observed
    o = (cfg["content"].get("observed_data") or {})
    targets = _trend_hints(cand)["targets"]
    need = int(o.get("min_entities", 2))
    if len(targets) < need:
        return False, f"식별자 {len(targets)}개 — 비교에 필요한 최소 {need}개 미만", None
    if not observed.equivalent_kinds(targets):
        kinds = ", ".join(f'{t.get("name")}={t.get("kind") or "(미선언)"}' for t in targets)
        return False, f"비교 등가성 불충족 — kind 가 엇갈린다({kinds})", None
    res = observed.collect(targets, timeout=int(o.get("timeout", 10)),
                           max_entities=int(o.get("max_entities", 5)), sources=o.get("sources"))
    ents = res.get("entities") or []
    rows, diff = observed.live_rows(ents), observed.distinct_rows(ents)
    if not observed.usable(res, min_entities=need, min_rows=int(o.get("min_rows", 3)),
                           min_distinct_rows=int(o.get("min_distinct_rows", 2))):
        return False, (f"관측표 불가 — 제품 {len(ents)}개 · 양쪽 다 값이 있는 행 {len(rows)} · "
                       f"값이 갈리는 행 {len(diff)} · API {res.get('ok_calls')}/{res.get('total_calls')} 성공"), res
    return True, (f"관측표 {len(rows)}행(값이 갈리는 행 {len(diff)}) · "
                  f"API {res.get('ok_calls')}/{res.get('total_calls')} 성공 · 관측일 {res.get('observed_date')}"), res


# ── 근접중복 코퍼스 (ORDER 45 PM 회신 7 — 플립 선행조건) ──────────────────────────────────
# 🔴 무엇이 문제였나: `quality_gate.check(existing_corpus=corpus)` 의 `corpus` 는 **그 실행 안에서만** 쌓인다.
#    하루 1편 카덴스에서는 매 실행이 `corpus=[]` 로 시작하므로 **어제 발행분과의 유사도를 아무도 보지 않는다.**
#    트렌드 축에서 특히 치명적이다 — 후보 7개에 herdr 3회·ccmanager 3회·sculptor 2회·catnip 2회·
#    container-use 2회가 겹쳐 등장하므로, 같은 제품쌍을 매일 다른 각도로 쓰다 보면 누적 유사도가 올라간다.
# → 이미 게이트를 통과한 산출물(`dist/queue`)과 승인 대기분(`dist/pending_approval`)을 코퍼스로 **먼저 적재**한다.
#   ⚠️ 비교 대상은 산문이다: 렌더된 HTML 에서 chrome(nav/header/footer/script/style)과 **표**를 걷어낸다.
#     표를 남기면 사이트 공통 문구·수치가 섞여 유사도가 왜곡된다(생성 중 corpus 는 표를 제외한 산문이다).
_CORPUS_STRIP_RE = re.compile(r"(?is)<(script|style|nav|header|footer|table|form)\b.*?</\1>")
_CORPUS_MAIN_RE = re.compile(r"(?is)<main\b.*?</main>")


def _html_prose(doc: str) -> str:
    """렌더된 문서 → 근접중복 비교용 산문 텍스트(생성 중 corpus 와 같은 성격으로 맞춘다)."""
    m = _CORPUS_MAIN_RE.search(doc or "")
    body = m.group(0) if m else (doc or "")
    body = _CORPUS_STRIP_RE.sub(" ", body)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()


def published_corpus(dirs=("dist/queue", "dist/pending_approval")) -> list:
    """이미 통과한 산출물의 산문 목록. 읽기 실패는 그 파일만 건너뛴다(가드가 아예 없는 것보다 낫다)."""
    out = []
    for d in dirs:
        for p in sorted(glob.glob(os.path.join(d, "*.html"))):
            try:
                with open(p, encoding="utf-8") as f:
                    t = _html_prose(f.read())
                if t:
                    out.append(t)
            except Exception as e:
                print(f"  (코퍼스 적재 건너뜀 {p}: {type(e).__name__})")
    return out


def _backlog_seeds(cfg) -> list:
    """기존 경로의 시드 — research 백로그 상위 10, 없으면 P1 코너스톤. (트렌드 모드에서는 쓰지 않는다.)"""
    import json
    if os.path.exists("dist/research/backlog.json"):
        with open("dist/research/backlog.json", encoding="utf-8") as f:
            ranked = json.load(f)
        seeds = [(e["keyword"], e["cluster"]) for e in ranked[:10]]
        print(f"generate: research 백로그 상위 {len(seeds)}개 사용")
        return seeds
    seeds = []
    for c in cfg["topics"]["clusters"]:
        if c.get("priority") == 1:
            seeds += [(s, c["id"]) for s in c.get("seeds", [])[:3]]
    return seeds


def stage_generate(cfg, *, limit: int | None = None, only: str | None = None):
    """초안 생성 → 품질 게이트 → (샘플·medium 은 사람 승인 대기) → 발행 큐(dist/queue). 통과분만.

    ANTHROPIC_API_KEY 있으면 Claude(claude-opus-4-8) 실생성, 없으면 fixture(오프라인 드래프트).
    거절(게이트/검수) 시 사유를 피드백으로 재생성 — 최대 content.yaml on_reject.max_regeneration_attempts 회.

    limit: 이번 실행에 한해 **일일 상한만** 대체한다(시범 생성용 `--trend-pilot`).
           ⛔ 게이트·검수·킬스위치·보류는 무엇도 우회하지 않는다. `config/guardrails.yaml` 은 건드리지 않는다.
    only:  이 키워드 하나만 시도한다(시범 대상 지정).
    """
    import json
    from content import generator, human_gate, quality_gate
    trend_on = bool(_trend_axis(cfg).get("enabled"))
    trend_by_kw = {}
    if trend_on:                                         # 🔴 트렌드 전용: trend_axis 후보만 시드가 된다
        seeds, trend_by_kw = _trend_seeds(cfg)
        print(f"generate: 트렌드 전용 축 ON — 후보 {len(seeds)}개만 시드로 사용"
              f"(백로그 미사용{'' if not os.path.exists('dist/research/backlog.json') else ' — backlog.json 존재하나 읽지 않는다'})")
    else:
        seeds = _backlog_seeds(cfg)
    if only:
        seeds = [s for s in seeds if s[0] == only]
        if not seeds:
            print(f"generate: 지정 키워드 '{only}' 가 시드에 없다 — 0편")
    os.makedirs("dist/queue", exist_ok=True)
    # 실콘텐츠(fixture 아님)는 발행 전 항상 검수(adsense-review 루브릭 — 사용자 방침)
    review_on = os.environ.get("ADSENSE_FIXTURE") != "1" and (
        bool(os.environ.get("ANTHROPIC_API_KEY")) or generator._claude_cli_available())
    # 일일 카덴스: 실콘텐츠는 이미 발행한 키워드 제외 + 하루 신규 상한(daily_generate)
    pub_path = "engine/store/published.json"
    published = set(json.load(open(pub_path, encoding="utf-8"))) if os.path.exists(pub_path) else set()
    daily = (cfg["guardrails"].get("rollout", {}) or {}).get("daily_generate", 4)
    if limit is not None:                                # 시범 생성(--trend-pilot) — 상한 **하나만** 대체한다
        print(f"generate: ⚠️ 일일 상한을 이번 실행에 한해 {daily} → {limit} 로 대체(시범 생성). "
              f"config/guardrails.yaml 은 수정하지 않았다. 품질게이트·검수·보류·킬스위치는 전부 그대로다.")
        daily = int(limit)
    # 하루 1편 멱등 가드 — 수동 발행 ↔ 20:00 로컬 배치 중복/경합 방지. 오늘 이미 발행 성공했으면 스킵.
    # 먼저 도는 쪽이 그날을 '선점'하고 나중 쪽은 자동 스킵(published.json·배포 경합 없음). review_on 일 때만.
    import datetime as _dt
    marker_path = "engine/store/last_publish_date.txt"
    today_str = _dt.date.today().isoformat()
    if review_on and os.path.exists(marker_path):
        try:
            if open(marker_path, encoding="utf-8").read().strip() == today_str:
                print(f"generate: 오늘({today_str}) 이미 발행됨 → 중복 방지 스킵 (수동↔20:00 배치 가드)")
                return 0
        except Exception:
            pass
    if review_on:
        seeds = [s for s in seeds if s[0] not in published]
    if trend_on and not seeds:
        # 🔴 후보 소진 = **0편으로 끝낸다**. 백로그 폴백 금지(ORDER 45 ①).
        # ⚠️ `fallback_to_backlog` 는 **실제로 동작하는 값**이다(기본 false). 코드가 읽지 않는 config 키는
        #    "값을 바꿔도 동작이 안 바뀌는 장식"이 되고, 이 저장소는 그 사고를 이미 겪었다(title_policy rev1).
        if _trend_axis(cfg).get("fallback_to_backlog"):
            print("generate: ⚠️ trend_axis.fallback_to_backlog=true — 사람이 명시적으로 켠 폴백. 백로그로 내려간다")
            seeds = [s for s in _backlog_seeds(cfg) if not review_on or s[0] not in published]
        if not seeds:
            print("generate: 트렌드 후보 소진(미발행 후보 0) — "
                  + ("폴백 백로그에도 미발행 시드가 없다" if _trend_axis(cfg).get("fallback_to_backlog")
                     else "백로그로 폴백하지 않는다") + ". 오늘은 0편.")
            print("generate(트렌드 전용): 0 신규 / 0 탈락 → dist/queue "
                  f"(누적 발행 {len(published)}) — 0편은 정지 사유가 아니다(알림만)")
            return 0
    max_attempts = 1 + int((cfg["content"].get("on_reject", {}) or {}).get("max_regeneration_attempts", 0))
    hsg = (cfg["content"].get("quality_gate", {}).get("human_sample_gate", {}) or {})
    # 🔴 발행분·승인대기분을 **먼저** 코퍼스에 적재한다(PM 회신 7). 이게 없으면 하루 1편 카덴스에서
    #    어제 발행분과의 유사도가 한 번도 검사되지 않는다.
    corpus = published_corpus()
    print(f"generate: 근접중복 코퍼스 {len(corpus)}편 적재(dist/queue + dist/pending_approval) — "
          f"임계 {cfg['content']['quality_gate']['near_duplicate']['max_similarity']}")
    passed, rejected, dropped = 0, 0, 0
    queued = 0            # 실제로 dist/queue 에 들어간 편수(보류는 세지 않는다 — 아래 마커 참조)
    for kw, cid in seeds:
        if review_on and passed >= daily:                # 하루 신규 상한 도달
            break
        hints = None
        is_trend = kw in trend_by_kw          # 폴백으로 내려온 백로그 시드에는 트렌드 규칙을 적용하지 않는다
        if is_trend:
            # ②④ 생성 **전** 판정 — 관측표가 안 서거나 등가 짝이 아니면 그 토픽은 버리고 다음 후보로.
            ok, why, _res = trend_preflight(trend_by_kw.get(kw) or {}, cfg)
            if not ok:
                print(f"TREND DROP {kw}: {why} → 이 후보를 버리고 다음 후보로(생성 호출 없음)")
                dropped += 1
                continue
            hints = _trend_hints(trend_by_kw.get(kw) or {})
            print(f"TREND OK {kw}: {why}")
            print(f"  식별자(사람 확정): "
                  + " | ".join(f'{t.get("name")} kind={t.get("kind")} '
                               f'{t.get("github") or t.get("npm")}' for t in hints["targets"])
                  + f" · 그라운딩 URL {len(hints['source_urls'])}개")
        feedback, accepted, rv = None, False, None   # rv: 검수 판정(fixture 모드에선 None — 보류 판단이 읽는다)
        trend_dropped = False                        # '표가 없어 버림'은 게이트 탈락과 다른 사건이다(집계 분리)
        for attempt in range(1, max_attempts + 1):
            try:
                spec, page = generator.generate(kw, cfg["content"], cluster=cid, feedback=feedback,
                                                hints=hints)
            except Exception as e:
                print(f"SKIP {kw}: 생성 실패 {e}"); break         # 시스템 오류는 피드백으로 못 고침 — 재시도 안 함
            if is_trend and not getattr(spec, "observed", None):
                # 사전 판정을 통과했어도 최종 spec 에 표가 없으면(해석 단락 확보 실패 등) 큐에 넣지 않는다.
                # ②의 이중 방어 — 트렌드 축의 존재 이유가 관측표이므로 표 없는 글은 이 축의 산출물이 아니다.
                print(f"TREND DROP {kw}: 최종 초안에 관측표가 붙지 않았다 — 표 없는 트렌드 글은 큐에 넣지 않는다")
                dropped += 1
                trend_dropped = True
                break
            r = quality_gate.check(page, cfg["content"], existing_corpus=corpus)
            if not r.passed:
                kept = _keep_rejected_spec(spec, stage="quality_gate", keyword=kw,
                                           attempt=attempt, reasons=r.reasons)
                print(f"GATE REJECT {kw} (시도 {attempt}/{max_attempts}): {r.reasons}"
                      + (f" (초안 보존 {kept})" if kept else ""))
                feedback = "; ".join(r.reasons); continue
            if review_on:                                # 검수 게이트
                from content import reviewer
                try:
                    rv = reviewer.review(spec, cfg["content"])
                except Exception as e:
                    _keep_rejected_spec(spec, stage="review_error", keyword=kw,   # 검수기 오류로도 초안이 사라지지 않게
                                        attempt=attempt, reasons=[f"{type(e).__name__}: {e}"])
                    print(f"REVIEW 실패→미발행 {kw}: {e}"); break  # 검수 자체 오류 — 재시도 무의미
                os.makedirs("dist/review", exist_ok=True)
                with open(f"dist/review/{spec.slug}.json", "w", encoding="utf-8") as f:
                    json.dump(rv, f, ensure_ascii=False, indent=2)
                if not rv.get("passed"):
                    tps = [i.get("type") for i in rv.get("issues", [])][:5]
                    kept = _keep_rejected_spec(spec, stage="review", keyword=kw, attempt=attempt,
                                               reasons=[f"severity={rv.get('severity')}"] + [str(t) for t in tps])
                    print(f"REVIEW REJECT {kw} (시도 {attempt}/{max_attempts}): sev={rv.get('severity')} {tps} "
                          f"(상세 dist/review/{spec.slug}.json"
                          + (f", 초안 {kept}" if kept else "") + ")")
                    feedback = review_feedback(rv)      # ai_tells 원문 + issues 설명 (review_feedback 주석)
                    print(f"  재생성 피드백: ai_tells {len(rv.get('ai_tells') or [])}건 + "
                          f"issues {len(rv.get('issues') or [])}건 → {len(feedback)}자 전달")
                    continue
            # 게이트·검수 통과 — 보류 사유(표본 / severity=medium)가 있으면 발행 큐 대신 승인 대기로.
            hold_why = _hold_reasons(rv, spec.slug, hsg, trend_axis=trend_on)
            if hold_why:
                human_gate.hold(spec.slug, page.html,
                                reason=_hold_notice(spec.slug, kw, rv, hold_why))
                print(f"HUMAN GATE 보류: {kw} → dist/pending_approval/{spec.slug}.html "
                      f"[{' + '.join(hold_why)}] (사유: {spec.slug}.reason.txt · "
                      f"승인: python engine/orchestrator.py --approve {spec.slug})")
                _notify_hold(spec.slug, kw, rv, hold_why)
            else:
                with open(f"dist/queue/{spec.slug}.html", "w", encoding="utf-8") as f:
                    f.write(page.html)
                queued += 1                              # 보류가 아니라 **실제 발행 큐 진입**만 센다
            corpus.append(" ".join(page.blocks)); published.add(kw); passed += 1
            accepted = True; break
        if not accepted and not trend_dropped:
            rejected += 1
    if review_on:                                        # 발행 키워드 영속화(다음 날 중복 방지)
        os.makedirs("engine/store", exist_ok=True)
        json.dump(sorted(published), open(pub_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        # 🔴 `passed` 가 아니라 `queued` 다(2026-08-08 실측). `passed` 는 보류분도 세므로, 그날 생성분이
        #    전부 사람 보류로 갔는데도 '오늘 발행함' 마커가 찍혔다. 그러면 위 멱등 가드가 그날 남은
        #    모든 생성을 막아 **하루 카덴스가 통째로 날아간다**(그날 라이브에 나간 글은 0편인데도).
        #    실제 사고: 08-08 09:00 에 ccmanager vs claude squad 가 3회 시도 끝에 보류 → 마커 설정 →
        #    확정된 신규 후보(clawk vs sculptor)를 그날 생성할 수 없었다.
        #    마커의 계약은 '오늘 발행 성공'이므로 큐 진입분만 세는 것이 맞다.
        if queued:                                       # 오늘 발행 성공 마커 — 멱등 가드용(수동↔20:00 배치)
            try:
                open(marker_path, "w", encoding="utf-8").write(today_str)
            except Exception:
                pass
    mode = ("트렌드 전용·" if trend_on else "") + ("검수ON·일일" if review_on else "fixture")
    print(f"generate({mode}): {passed} 신규 / {rejected} 탈락"
          + (f" / {dropped} 버림(관측표·등가성 불충족)" if trend_on else "")
          + f" → dist/queue (누적 발행 {len(published)})")
    if trend_on and passed == 0:
        print("generate: 오늘 0편 — 트렌드 축에서 조건을 채운 후보가 없었다. "
              "0편은 정지 사유가 아니다(zero_generation_alert_days 알림만).")
    return passed


def stage_monitor(cfg):
    """정책·색인·CWV·RPM 신호 수집 → 킬스위치 평가. 이상 시 발행 중단 + 알림."""
    from store import db
    from monitor import generation_watch, health, alerts
    db.init()
    # 침묵 실패 경보: 신규 생성 0편이 임계일 이상 지속되면 알림(하루 1회). 발행 중단 아님 — 킬스위치와 별개.
    generation_watch.check(cfg)
    metrics = health.collect(cfg, db)        # CWV·RPM은 DB, 그 외는 signals.json 오버라이드
    decision = killswitch.evaluate(metrics, cfg["guardrails"])
    if decision.halt:
        killswitch.engage(decision)
        alerts.send("[stack. KILLSWITCH] 발행 자동 중단 — " + "; ".join(decision.reasons)
                    + " (원인 확인 후 killswitch.clear() 로 해제)", cfg)
        print("KILLSWITCH ENGAGED:", "; ".join(decision.reasons))
    else:
        print("monitor: 정상 (killswitch 미발동)")
    return decision


def stage_publish(cfg):
    """발행 큐(dist/queue) → CMS. 킬스위치·일일 cap 준수. 게이트 통과분만."""
    from content import publisher
    if killswitch.is_halted():
        print("발행 중단됨(killswitch). 사람이 원인 확인 후 clear() 필요.")
        return 0
    cap = cfg["guardrails"]["rollout"]["daily_publish_cap"]
    queued = sorted(glob.glob("dist/queue/*.html"))[:cap]
    pub = publisher.get_publisher(cfg["sites"])
    for q in queued:
        slug = os.path.splitext(os.path.basename(q))[0]
        with open(q, encoding="utf-8") as f:
            url = pub.publish(f.read(), slug, dry_run=False)
        print(f"published → {url}")
    print(f"publish: {len(queued)} (cap {cap})")
    return len(queued)


def stage_build(cfg):
    """dist/queue(게이트 통과분) → dist/site (정적 사이트 + 필수 페이지 + sitemap/robots)."""
    from content import site_builder
    return site_builder.build(cfg)


def stage_deploy(cfg):
    """dist/site → 보유 서버(rsync). 기본 DRY-RUN, ADSENSE_DEPLOY=1 일 때만 실제 배포.

    실배포 성공 시 IndexNow 로 변경 URL 을 Bing·Yandex 등에 통보(색인 알림, 트래픽 생성 아님)."""
    from content import site_builder
    import deploy as deployer
    site_builder.build(cfg)                       # 항상 최신 빌드 후 배포
    result = deployer.deploy(cfg, dry_run=os.environ.get("ADSENSE_DEPLOY") != "1")
    if result:                                    # dry-run 이 아니라 실제 배포된 경우만
        try:
            from optimize import indexnow
            indexnow.run(cfg)
        except Exception as e:
            print(f"  indexnow skip: {e}")
    return result


def stage_indexnow(cfg):
    """(수동) 현재 빌드의 변경 URL 을 IndexNow 에 제출. deploy 훅과 별개로 단독 실행용."""
    from content import site_builder
    from optimize import indexnow
    site_builder.build(cfg)
    return indexnow.run(cfg)


def stage_syndicate(cfg):
    """발행된 라이브 글을 dev.to 에 canonical 신디케이션(earned backlink·유입).

    기본 DRY-RUN — 실제 발행은 ADSENSE_SYNDICATE=1 + .env 의 DEVTO_API_KEY. per_run 캡으로 속도 제한.
    ⚠️ Reddit/HN 등 커뮤니티 자동 게시는 금지(F3) — 이건 '공식 발행 API + canonical'인 dev.to 한정."""
    from content import site_builder
    from optimize import devto
    site_builder.build(cfg)                       # 최신 sitemap/site 기준으로 대상 산정
    return devto.run(cfg)


def stage_report(cfg):
    """로컬 HTML 리포트(RPM·CWV·검색·발행/큐·킬스위치). Artifact 아님(CLAUDE.md)."""
    from store import db
    import report as reporter
    db.init()
    return reporter.build(cfg, db)


def stage_analytics(cfg):
    """자체 사이트 방문 분석 — nginx 로그 → 관리자 대시보드(data.json·index.html) 갱신.

    나(쿠키 noana·지정 IP)·봇 제외. 읽기 전용(트래픽/클릭 생성과 무관, F3 리스크 0).
    설정은 config/analytics.yaml 을 모듈이 직접 로드(서버에서 로그 경로·출력 위치를 관리)."""
    from analytics import builder
    return builder.run(cfg)


STAGES = {
    "ingest": stage_ingest, "research": stage_research, "generate": stage_generate,
    "monitor": stage_monitor, "publish": stage_publish, "build": stage_build,
    "deploy": stage_deploy, "report": stage_report, "analytics": stage_analytics,
    "indexnow": stage_indexnow, "syndicate": stage_syndicate,
}


def main(argv=None):
    try:                                  # .env 의 ANTHROPIC_API_KEY 등 로드(있으면)
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=list(STAGES))
    p.add_argument("--approve", metavar="SLUG", help="휴먼 샘플 게이트 대기 글 승인(dist/pending_approval → dist/queue)")
    p.add_argument("--list-pending", action="store_true", help="휴먼 샘플 게이트 대기 목록 출력")
    p.add_argument("--rereview", metavar="SLUG",
                   help="보존된 반려 초안 재검수(dist/review/<slug>.spec.json → <slug>.rereview.json, 발행 안 함)")
    p.add_argument("--trend-pilot", nargs="?", const="", metavar="KEYWORD",
                   help="트렌드 축 시범 생성 1편(큐까지, 발행·배포 없음). 키워드 생략 시 첫 적격 후보. "
                        "⚠️ 일일 상한만 1로 대체하고 guardrails.yaml 은 수정하지 않는다 — 게이트·검수·보류는 그대로.")
    p.add_argument("--trend-plan", action="store_true",
                   help="트렌드 후보 사전판정만 출력(생성 호출 없음) — 관측표·등가성 통과 여부 점검용")
    args = p.parse_args(argv)
    if args.rereview:
        rereview(args.rereview, load_config())
        return 0
    if args.trend_plan:
        cfg = load_config()
        seeds, by_kw = _trend_seeds(cfg)
        pub = "engine/store/published.json"
        import json as _json
        done = set(_json.load(open(pub, encoding="utf-8"))) if os.path.exists(pub) else set()
        ok_n = 0
        for kw, cid in seeds:
            if kw in done:
                print(f"  - {kw}: 발행됨(스킵)")
                continue
            ok, why, _r = trend_preflight(by_kw.get(kw) or {}, cfg)
            ok_n += bool(ok)
            print(f"  {'OK  ' if ok else 'DROP'} {kw} [{cid}]: {why}")
        print(f"trend-plan: 후보 {len(seeds)}개 중 미발행·적격 {ok_n}개")
        return 0
    if args.trend_pilot is not None:
        cfg = load_config()
        if not _trend_axis(cfg).get("enabled"):
            print("trend-pilot: config/topics.yaml 의 trend_axis.enabled 가 꺼져 있다 — 아무것도 하지 않는다")
            return 0
        stage_generate(cfg, limit=1, only=(args.trend_pilot or None))
        return 0
    if args.list_pending:
        from content import human_gate
        # 보류 사유까지 함께 출력한다 — slug 만으로는 승인/거부를 판단할 수 없다(ORDER 2026-07-25-40 ②).
        for block in human_gate.pending_report():
            print(block)
        return 0
    if args.approve:
        from content import human_gate
        path = human_gate.approve(args.approve)
        print(f"승인 완료 → {path} (다음 build/deploy부터 라이브)")
        return 0
    if not args.stage:
        p.error("--stage 필요(또는 --approve/--list-pending/--rereview/--trend-pilot/--trend-plan)")
    cfg = load_config()
    STAGES[args.stage](cfg)             # 반환값은 종료코드로 쓰지 않음(예외 시에만 비0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
