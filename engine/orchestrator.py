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
    """시드 키워드 스코어링 → dist/research/backlog.json (generate 가 소비). 있으면 SC 실수요 보정."""
    import json
    from content import keyword_research
    from store import db
    db.init()
    backlog = keyword_research.run(cfg["topics"], cfg["niches"], db)
    os.makedirs("dist/research", exist_ok=True)
    with open("dist/research/backlog.json", "w", encoding="utf-8") as f:
        json.dump(backlog, f, ensure_ascii=False, indent=2)
    print(f"research: {len(backlog)} 시드 스코어 → dist/research/backlog.json")
    for e in backlog[:5]:
        print(f"  {e['score']:.3f} [{e['cluster']}/{e['intent']}] {e['keyword']}")
    return backlog


def stage_generate(cfg):
    """초안 생성 → 품질 게이트 → (샘플 일부는 사람 승인 대기) → 발행 큐(dist/queue). 통과분만.

    ANTHROPIC_API_KEY 있으면 Claude(claude-opus-4-8) 실생성, 없으면 fixture(오프라인 드래프트).
    거절(게이트/검수) 시 사유를 피드백으로 재생성 — 최대 content.yaml on_reject.max_regeneration_attempts 회.
    """
    import json
    from content import generator, human_gate, quality_gate
    backlog_path = "dist/research/backlog.json"
    if os.path.exists(backlog_path):                     # research 가 만든 순위 백로그 우선(시드 + SC 트렌드 후보)
        with open(backlog_path, encoding="utf-8") as f:
            ranked = json.load(f)
        seeds = [(e["keyword"], e["cluster"]) for e in ranked[:10]]
        print(f"generate: research 백로그 상위 {len(seeds)}개 사용")
    else:                                                # 없으면 P1 코너스톤 시드
        seeds = []
        for c in cfg["topics"]["clusters"]:
            if c.get("priority") == 1:
                seeds += [(s, c["id"]) for s in c.get("seeds", [])[:3]]
    os.makedirs("dist/queue", exist_ok=True)
    # 실콘텐츠(fixture 아님)는 발행 전 항상 검수(adsense-review 루브릭 — 사용자 방침)
    review_on = os.environ.get("ADSENSE_FIXTURE") != "1" and (
        bool(os.environ.get("ANTHROPIC_API_KEY")) or generator._claude_cli_available())
    # 일일 카덴스: 실콘텐츠는 이미 발행한 키워드 제외 + 하루 신규 상한(daily_generate)
    pub_path = "engine/store/published.json"
    published = set(json.load(open(pub_path, encoding="utf-8"))) if os.path.exists(pub_path) else set()
    daily = (cfg["guardrails"].get("rollout", {}) or {}).get("daily_generate", 4)
    if review_on:
        seeds = [s for s in seeds if s[0] not in published]
    max_attempts = 1 + int((cfg["content"].get("on_reject", {}) or {}).get("max_regeneration_attempts", 0))
    hsg = (cfg["content"].get("quality_gate", {}).get("human_sample_gate", {}) or {})
    corpus, passed, rejected = [], 0, 0
    for kw, cid in seeds:
        if review_on and passed >= daily:                # 하루 신규 상한 도달
            break
        feedback, accepted = None, False
        for attempt in range(1, max_attempts + 1):
            try:
                spec, page = generator.generate(kw, cfg["content"], cluster=cid, feedback=feedback)
            except Exception as e:
                print(f"SKIP {kw}: 생성 실패 {e}"); break         # 시스템 오류는 피드백으로 못 고침 — 재시도 안 함
            r = quality_gate.check(page, cfg["content"], existing_corpus=corpus)
            if not r.passed:
                print(f"GATE REJECT {kw} (시도 {attempt}/{max_attempts}): {r.reasons}")
                feedback = "; ".join(r.reasons); continue
            if review_on:                                # 검수 게이트
                from content import reviewer
                try:
                    rv = reviewer.review(spec, cfg["content"])
                except Exception as e:
                    print(f"REVIEW 실패→미발행 {kw}: {e}"); break  # 검수 자체 오류 — 재시도 무의미
                os.makedirs("dist/review", exist_ok=True)
                with open(f"dist/review/{spec.slug}.json", "w", encoding="utf-8") as f:
                    json.dump(rv, f, ensure_ascii=False, indent=2)
                if not rv.get("passed"):
                    tps = [i.get("type") for i in rv.get("issues", [])][:5]
                    print(f"REVIEW REJECT {kw} (시도 {attempt}/{max_attempts}): sev={rv.get('severity')} {tps} "
                          f"(상세 dist/review/{spec.slug}.json)")
                    fixes = [f"[{i.get('type')}] {i.get('detail', '')} → {i.get('fix', '')}"
                             for i in rv.get("issues", [])[:6]]
                    feedback = "; ".join(fixes) or "; ".join(rv.get("ai_tells", [])); continue
            # 게이트·검수 통과 — human_sample_gate 대상이면 발행 큐 대신 승인 대기로.
            if hsg.get("enabled") and human_gate.is_sampled(spec.slug, hsg.get("sample_pct", 0)):
                human_gate.hold(spec.slug, page.html)
                print(f"HUMAN GATE 대기(샘플 {hsg.get('sample_pct')}%): {kw} → dist/pending_approval/{spec.slug}.html "
                      f"(승인: python engine/orchestrator.py --approve {spec.slug})")
            else:
                with open(f"dist/queue/{spec.slug}.html", "w", encoding="utf-8") as f:
                    f.write(page.html)
            corpus.append(" ".join(page.blocks)); published.add(kw); passed += 1
            accepted = True; break
        if not accepted:
            rejected += 1
    if review_on:                                        # 발행 키워드 영속화(다음 날 중복 방지)
        os.makedirs("engine/store", exist_ok=True)
        json.dump(sorted(published), open(pub_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"generate({'검수ON·일일' if review_on else 'fixture'}): {passed} 신규 / {rejected} 탈락 → dist/queue (누적 발행 {len(published)})")
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
    p.add_argument("--stage", choices=list(STAGES))
    p.add_argument("--approve", metavar="SLUG", help="휴먼 샘플 게이트 대기 글 승인(dist/pending_approval → dist/queue)")
    p.add_argument("--list-pending", action="store_true", help="휴먼 샘플 게이트 대기 목록 출력")
    args = p.parse_args(argv)
    if args.list_pending:
        from content import human_gate
        for slug in human_gate.pending():
            print(slug)
        return 0
    if args.approve:
        from content import human_gate
        path = human_gate.approve(args.approve)
        print(f"승인 완료 → {path} (다음 build/deploy부터 라이브)")
        return 0
    if not args.stage:
        p.error("--stage 필요(또는 --approve/--list-pending)")
    cfg = load_config()
    STAGES[args.stage](cfg)             # 반환값은 종료코드로 쓰지 않음(예외 시에만 비0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
