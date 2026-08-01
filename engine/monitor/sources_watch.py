"""sources_watch.py — **'인용 0건' 반려 계측 + 트립와이어** (R0~R4 채택 조건 2·3, PM 2026-08-01).

왜 이게 있나
------------
R0~R4(미페치 인용 가드)는 **측정으로 채택된 것이 아니다.** 코퍼스 리플레이 표본이 실초안 6편뿐이라
`sources=0` 비율 0.0% 도 14.3% 도 통계적 힘이 없었다(실초안 1편만 걸려도 16.7%).
PM 이 채택한 근거는 **실패 모드의 비대칭**이다:

  · 채택했는데 틀리면 → 글이 **적어진다**. 관측 가능하고 복구 가능하며 **아무것도 잘못 발행되지 않는다.**
  · 미채택인데 틀리면 → **읽지 않은 페이지를 인용한 글이 발행된다.** 가정이 아니라 **라이브 5편으로 이미 실현**돼 있다.

즉 진짜 숫자는 **운영에서** 나온다. 이 모듈이 그 숫자를 만든다.

무엇을 하나
-----------
① **계측**: 반려 사유가 '인용 0건'인 건만 따로 기록한다(다른 반려와 섞이면 나중에 셀 수 없다).
② **트립와이어**: 누적 `sources_zero_alert_total` 건 **또는** 연속 `sources_zero_alert_days` 일이면
   알림 + PM 보고. 그 시점에 PM 이 가드를 재평가한다.

⚠️ `zero_generation_alert_days` 와 **별개다.** 그건 '0편'이라는 결과만 잡고 **원인을 가리지 않는다.**
   이 모듈은 "인용을 못 만들어서 떨어졌다"만 센다.
⚠️ 킬스위치가 아니다 — 발행을 중단하지 않는다. 트래픽/클릭을 만들지 않는다(F3).
"""
from __future__ import annotations

import datetime as dt
import json
import os

STATE_FILE = "engine/store/sources_zero.json"
DEFAULT_TOTAL = 3
DEFAULT_DAYS = 2

# quality_gate.check() 가 인용 0건일 때 남기는 사유(quality_gate.py:84). 다른 반려와 구분하는 유일한 키.
SOURCES_ZERO_REASON = "eeat: 출처 없음"


def is_sources_zero(reasons) -> bool:
    """이 반려가 **인용 0건 때문인가**. 다른 사유가 함께 있어도 인용 0건이면 True."""
    return any(SOURCES_ZERO_REASON in str(x) for x in (reasons or []))


def _thresholds(cfg) -> tuple:
    """임계는 config 값(하드코딩 금지) — guardrails.rollout.sources_zero_alert_{total,days}."""
    roll = {}
    try:
        roll = (cfg["guardrails"].get("rollout", {}) or {})
    except Exception:
        pass

    def _pos(key, default):
        try:
            v = int(roll.get(key, default))
            return v if v > 0 else default
        except Exception:
            return default

    return _pos("sources_zero_alert_total", DEFAULT_TOTAL), _pos("sources_zero_alert_days", DEFAULT_DAYS)


def _load() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("events"), list):
            return d
    except Exception:
        pass
    return {"events": [], "alerted": []}


def _save(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)      # 먼저 직렬화 → 부분 파일 방지
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(payload)
    except Exception as e:                                             # 계측 실패가 생성을 막지 않는다
        print(f"  (인용0건 계측 기록 실패 — 파이프라인은 계속) {type(e).__name__}: {e}")


def consecutive_days(events: list, today: dt.date | None = None) -> int:
    """오늘부터 거꾸로 **연속으로** 발생한 날 수. 오늘 발생이 없으면 0."""
    days = {str(e.get("date")) for e in events if e.get("date")}
    today = today or dt.date.today()
    n = 0
    while today.isoformat() in days:
        n += 1
        today -= dt.timedelta(days=1)
    return n


def record(keyword: str, slug: str, reasons, cfg, *, attempt: int = 0, today: dt.date | None = None) -> dict | None:
    """인용 0건 반려면 기록하고 트립와이어를 평가한다. 아니면 None.

    반환: {"total", "consecutive", "tripped", "why"} — 호출부는 로그에만 쓴다(발행 판단과 무관).
    """
    if not is_sources_zero(reasons):
        return None
    today = today or dt.date.today()
    st = _load()
    st["events"].append({"date": today.isoformat(),
                         "at": dt.datetime.now().isoformat(timespec="seconds"),
                         "keyword": keyword, "slug": slug, "attempt": attempt})
    total_thr, days_thr = _thresholds(cfg)
    total = len(st["events"])
    consec = consecutive_days(st["events"], today)
    why, kinds = [], []
    if total >= total_thr:
        why.append(f"누적 {total}건 ≥ {total_thr}")
        kinds.append("total")
    if consec >= days_thr:
        why.append(f"연속 {consec}일 ≥ {days_thr}")
        kinds.append("days")
    out = {"total": total, "consecutive": consec, "tripped": bool(why), "why": "; ".join(why)}
    # 같은 날 같은 **트리거 종류**로는 다시 알리지 않는다(하루 1회) — 알림 피로가 트립와이어를 무력화한다.
    # ⚠️ 키에 건수를 넣으면 안 된다: 같은 날 4건째·5건째마다 사유 문자열이 달라져 **매번 재알림**된다
    #    (셀프테스트가 실제로 잡아낸 결함). 종류로만 묶고, 새 종류가 추가로 걸리면 그때 한 번 더 알린다.
    key = f"{today.isoformat()}|{','.join(kinds)}"
    if out["tripped"] and key not in st.get("alerted", []):
        st.setdefault("alerted", []).append(key)
        out["notify"] = True
    _save(st)
    return out


def notice(keyword: str, state: dict) -> str:
    return ("[stack. 인용0건 트립와이어] 미페치 인용 가드(R0~R4) 재평가 시점\n"
            f"사유: {state.get('why')}\n"
            f"최근 반려 키워드: {keyword}\n"
            f"누적 {state.get('total')}건 · 연속 {state.get('consecutive')}일 "
            f"(기록: {STATE_FILE})\n"
            "이 가드는 **측정으로 채택된 것이 아니다**(리플레이 표본 실초안 6편 = 판단 불가).\n"
            "운영 수치가 임계에 닿았으니 PM 이 가드를 재평가할 시점이다.\n"
            "⚠️ 발행 중단 아님 — 킬스위치와 무관하고, 0편은 정지 사유가 아니다.")
