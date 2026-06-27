"""killswitch.py — 자동 발행 안전벨트 (AUTOMATION.md §4).

트리거 발생 시 발행을 즉시 중단하고 알림. 해제는 사람이 원인 확인 후 수동.
자동 발행 규모가 클수록 자동 차단이 필수다. config/guardrails.yaml 의 killswitch 를 따른다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os

STATE_FILE = "engine/store/killswitch_state.json"


@dataclass
class Metrics:
    """monitor 단계가 API에서 수집한 현재 신호."""
    policy_center_warning: bool = False
    invalid_traffic_alert: bool = False          # 최우선 — F3
    manual_action: bool = False
    indexing_drop_pct: float = 0.0
    cwv_status_poor: bool = False
    rpm_drop_pct: float = 0.0
    new_page_deindex_rate_pct: float = 0.0


@dataclass
class Decision:
    halt: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(m: Metrics, cfg: dict) -> Decision:
    """현재 신호를 임계값과 비교해 발행 중단 여부 결정."""
    ks = cfg["killswitch"]
    if not ks.get("enabled", True):
        return Decision(halt=False)
    t = ks["triggers"]
    d = Decision(halt=False)

    def trip(reason: str):
        d.halt = True
        d.reasons.append(reason)

    if t.get("invalid_traffic_alert") and m.invalid_traffic_alert:
        trip("INVALID TRAFFIC 알림 — 최우선 정지 (F3)")
    if t.get("policy_center_warning") and m.policy_center_warning:
        trip("정책센터 경고")
    if t.get("manual_action") and m.manual_action:
        trip("Search Console 수동 조치")
    if m.indexing_drop_pct >= t.get("indexing_drop_pct", 101):
        trip(f"색인률 급락 {m.indexing_drop_pct}%")
    if t.get("cwv_status_poor") and m.cwv_status_poor:
        trip("Core Web Vitals 불량 전환")
    if m.rpm_drop_pct >= t.get("rpm_drop_pct", 101):
        trip(f"RPM 이상 급락 {m.rpm_drop_pct}%")
    if m.new_page_deindex_rate_pct >= t.get("new_page_deindex_rate_pct", 101):
        trip(f"신규 페이지 색인 거부율 {m.new_page_deindex_rate_pct}% (저품질 신호)")
    return d


def is_halted() -> bool:
    if not os.path.exists(STATE_FILE):
        return False
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f).get("halted", False)


def engage(decision: Decision) -> None:
    """발행 중단 상태를 영속화. auto_resume=false 이므로 사람이 clear() 해야 재개."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"halted": True, "reasons": decision.reasons}, f, ensure_ascii=False, indent=2)


def clear() -> None:
    """사람이 원인 확인 후 수동 재개 (자동 호출 금지)."""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
