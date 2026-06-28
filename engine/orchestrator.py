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
    for name in ("guardrails", "content", "niches", "topics", "schedule", "sites"):
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
    """초안 생성 → 품질 게이트 → 발행 큐(dist/queue). 통과분만.

    현재 fixture 모드(오프라인 드래프트). ANTHROPIC_API_KEY 기반 실생성은 generator._via_api 구현 후.
    """
    from content import generator, quality_gate
    seeds = []
    for c in cfg["topics"]["clusters"]:
        if c.get("priority") == 1:                       # 승인 전: P1 코너스톤부터
            seeds += [(s, c["id"]) for s in c.get("seeds", [])[:3]]
    os.makedirs("dist/queue", exist_ok=True)
    corpus, passed = [], 0
    for kw, cid in seeds:
        spec, page = generator.generate(kw, cfg["content"], force_fixture=True)
        r = quality_gate.check(page, cfg["content"], existing_corpus=corpus)
        if r.passed:
            with open(f"dist/queue/{spec.slug}.html", "w", encoding="utf-8") as f:
                f.write(page.html)
            corpus.append(" ".join(page.blocks))
            passed += 1
        else:
            print(f"REJECT {kw}: {r.reasons}")
    print(f"generate(fixture): {passed}/{len(seeds)} 게이트 통과 → dist/queue")
    return passed


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
