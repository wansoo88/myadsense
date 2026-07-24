"""generation_watch.py — "신규 생성 0편 N일 연속" 침묵 실패 경보 (AUTOMATION.md §4 보조).

왜: 2026-07-03~07-24 서버 생성이 21일간 0편이었는데 아무도 몰랐다. 전 편 실패해도 generate 단계는
    rc=0 을 반환해 cron·모니터가 이상을 못 봤다(team/reports/2026-07-24-03-ops.md 이슈 2).
무엇: 마지막 '성공 생성일' 마커(engine/store/last_publish_date.txt — stage_generate 가 passed>0 일 때만 기록)
    로부터 임계 일수를 넘기면 **기존 알림 경로(monitor.alerts)** 로 하루 1회 통보한다.

⚠️ 킬스위치가 아니다 — 발행을 중단하지 않는다. 생성 0편은 정지 사유가 아니라 고장 신호다(지시 07-ops).
어떤 트래픽/클릭도 만들지 않는다(F3).
"""
from __future__ import annotations
import datetime as dt
import json
import os

MARKER_FILE = "engine/store/last_publish_date.txt"       # stage_generate 가 passed>0 일 때 기록
STATE_FILE = "engine/store/generation_alert_state.json"  # 하루 1회 중복 알림 방지
DEFAULT_THRESHOLD_DAYS = 2


def _threshold(cfg) -> int:
    """임계 일수는 config 값(하드코딩 금지) — guardrails.rollout.zero_generation_alert_days."""
    try:
        v = int((cfg["guardrails"].get("rollout", {}) or {}).get(
            "zero_generation_alert_days", DEFAULT_THRESHOLD_DAYS))
        return v if v > 0 else DEFAULT_THRESHOLD_DAYS
    except Exception:
        return DEFAULT_THRESHOLD_DAYS


def last_success_date() -> dt.date | None:
    """마지막으로 신규 생성이 1편 이상 성공한 날. 기록이 없으면 None."""
    if not os.path.exists(MARKER_FILE):
        return None
    try:
        with open(MARKER_FILE, encoding="utf-8") as f:
            return dt.date.fromisoformat(f.read().strip())
    except Exception:
        return None


def _state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _remember_alert(today: dt.date, days: int | None) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_alert_date": today.isoformat(), "zero_days": days}, f,
                  ensure_ascii=False, indent=2)


def check(cfg, *, today: dt.date | None = None, notify: bool = True) -> dict:
    """신규 생성 침묵을 평가하고 임계 초과 시 알림(하루 1회). 발행에는 영향 없음.

    반환: {"days": 경과일|None, "threshold": N, "alert": bool, "sent": bool, "message": str}
    """
    today = today or dt.date.today()
    threshold = _threshold(cfg)
    last = last_success_date()
    days = (today - last).days if last else None

    if last is None:
        alert = True                                   # 성공 기록 자체가 없음 = 한 번도 생성 못 함
        detail = f"성공 기록 없음({MARKER_FILE} 없음)"
    else:
        alert = days >= threshold
        detail = f"마지막 성공 생성 {last.isoformat()} ({days}일 경과)"

    msg = (f"[stack. 생성정지] 신규 생성 0편 — {detail}, 임계 {threshold}일. "
           f"generate 단계 실패 여부 확인(로그의 'claude CLI 실패(rc=...)' 사유). "
           f"⚠️ 발행 중단 아님 — 킬스위치와 무관.")

    sent = False
    if alert and notify:
        if _state().get("last_alert_date") == today.isoformat():
            print(f"generation_watch: 임계 초과({detail}) — 오늘 이미 알림 발송, 중복 생략")
        else:
            from monitor import alerts
            sent = alerts.send(msg, cfg)               # 기존 채널 재사용(텔레그램·슬랙·콘솔 폴백)
            _remember_alert(today, days)
            print("generation_watch:", msg)
    elif not alert:
        print(f"generation_watch: 정상 ({detail}, 임계 {threshold}일)")

    return {"days": days, "threshold": threshold, "alert": alert, "sent": sent, "message": msg}
