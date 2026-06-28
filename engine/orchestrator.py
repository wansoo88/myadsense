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
    """키워드·니치·지역 스코어 (config/niches.yaml weights)."""
    raise NotImplementedError("keyword_research 구현")


def stage_generate(cfg):
    """초안 생성 → 품질 게이트 → 발행 큐(dist/queue). 통과분만.

    ANTHROPIC_API_KEY 있으면 Claude(claude-opus-4-8) 실생성, 없으면 fixture(오프라인 드래프트).
    개별 생성 실패(거절·오류)는 스킵하고 계속.
    """
    from content import generator, quality_gate
    seeds = []
    for c in cfg["topics"]["clusters"]:
        if c.get("priority") == 1:                       # 승인 전: P1 코너스톤부터
            seeds += [(s, c["id"]) for s in c.get("seeds", [])[:3]]
    os.makedirs("dist/queue", exist_ok=True)
    corpus, passed = [], 0
    for kw, cid in seeds:
        try:
            spec, page = generator.generate(kw, cfg["content"], cluster=cid)  # 키 있으면 API, 없으면 fixture
        except Exception as e:
            print(f"SKIP {kw}: 생성 실패 {e}")
            continue
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
    from store import db
    from monitor import health, alerts
    db.init()
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
    """dist/site → 보유 서버(rsync). 기본 DRY-RUN, ADSENSE_DEPLOY=1 일 때만 실제 배포."""
    from content import site_builder
    import deploy as deployer
    site_builder.build(cfg)                       # 항상 최신 빌드 후 배포
    return deployer.deploy(cfg, dry_run=os.environ.get("ADSENSE_DEPLOY") != "1")


def stage_report(cfg):
    """로컬 HTML 리포트(RPM·CWV·검색·발행/큐·킬스위치). Artifact 아님(CLAUDE.md)."""
    from store import db
    import report as reporter
    db.init()
    return reporter.build(cfg, db)


STAGES = {
    "ingest": stage_ingest, "research": stage_research, "generate": stage_generate,
    "monitor": stage_monitor, "publish": stage_publish, "build": stage_build,
    "deploy": stage_deploy, "report": stage_report,
}


def main(argv=None):
    try:                                  # .env 의 ANTHROPIC_API_KEY 등 로드(있으면)
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True, choices=list(STAGES))
    args = p.parse_args(argv)
    cfg = load_config()
    STAGES[args.stage](cfg)             # 반환값은 종료코드로 쓰지 않음(예외 시에만 비0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
