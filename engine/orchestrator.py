"""orchestrator.py — 자동화 파이프라인 스파인 (AUTOMATION.md §2).

스케줄러(cron / Claude Code 예약 에이전트)가 단계별로 호출한다.
    python engine/orchestrator.py --stage <ingest|monitor|research|generate|publish|report>

🟢 ingest/research/generate/monitor/report = 자유 자동화 (리스크 0)
🟡 publish = 게이트 자동화 (품질 게이트 통과분 + 킬스위치 + 일일 cap 준수)
⛔ 트래픽/클릭 생성은 어떤 단계에도 없다 (docs/RESEARCH.md F3).
"""
from __future__ import annotations
import argparse
import sys

import yaml  # pip install pyyaml

from monitor import killswitch
# 아래 모듈들은 AUTOMATION.md §2 의 레이어대로 채운다 (어댑터/구현 TODO):
#   ingest.adsense_api / ingest.search_console / ingest.pagespeed
#   content.keyword_research / content.generator / content.publisher
#   optimize.rpm_analyzer / optimize.experiment_advisor
#   monitor.health / monitor.alerts / store.db


def load_config() -> dict:
    cfg = {}
    for name in ("guardrails", "content", "niches", "schedule", "sites"):
        with open(f"config/{name}.yaml", encoding="utf-8") as f:
            cfg[name] = yaml.safe_load(f)
    return cfg


def stage_ingest(cfg):
    """AdSense/Search Console/PageSpeed → store(DB). 읽기 전용."""
    raise NotImplementedError("ingest 어댑터 구현 — AUTOMATION.md §2, 읽기 API")


def stage_research(cfg):
    """키워드·니치·지역 스코어 (config/niches.yaml weights)."""
    raise NotImplementedError("keyword_research 구현")


def stage_generate(cfg):
    """초안 생성 → 품질 게이트 → 발행 큐. 통과분만 큐로(quality_gate.check)."""
    raise NotImplementedError("generator + quality_gate.check 파이프라인 구현")


def stage_monitor(cfg):
    """정책·색인·CWV·RPM 신호 수집 → 킬스위치 평가. 이상 시 발행 중단 + 알림."""
    metrics = killswitch.Metrics()           # TODO: monitor.health 가 API에서 채움
    decision = killswitch.evaluate(metrics, cfg["guardrails"])
    if decision.halt:
        killswitch.engage(decision)
        # TODO: monitor.alerts.send(decision.reasons)
        print("KILLSWITCH ENGAGED:", "; ".join(decision.reasons))
    return decision


def stage_publish(cfg):
    """발행 큐 → CMS. 킬스위치·일일 cap 준수. 게이트 통과분만."""
    if killswitch.is_halted():
        print("발행 중단됨(killswitch). 사람이 원인 확인 후 clear() 필요.")
        return
    cap = cfg["guardrails"]["rollout"]["daily_publish_cap"]
    print(f"발행: 큐에서 최대 {cap}개 점진 발행 (publisher 어댑터 TODO)")
    raise NotImplementedError("publisher 어댑터(wordpress/static_ssg) 구현")


def stage_report(cfg):
    """로컬 HTML 리포트(RPM·세션·CWV·게이트 통과율). Artifact 아님(CLAUDE.md)."""
    raise NotImplementedError("report 렌더러 구현 → reports/weekly_{date}.html")


STAGES = {
    "ingest": stage_ingest, "research": stage_research, "generate": stage_generate,
    "monitor": stage_monitor, "publish": stage_publish, "report": stage_report,
}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True, choices=list(STAGES))
    args = p.parse_args(argv)
    cfg = load_config()
    return STAGES[args.stage](cfg)


if __name__ == "__main__":
    sys.exit(main())
