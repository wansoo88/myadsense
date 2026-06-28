# pjt12-adsense — AdSense 가성비 자동화 엔진

콘텐츠 사이트를 **풀스택 자동화 + 대량 프로그래매틱 SEO**로 AdSense 수익화하되,
**계정 정지 리스크(무효 트래픽·저품질)를 코드 가드레일로 차단**한 시스템.

## 문서 지도
- **전략 규칙(항상 로드)**: [CLAUDE.md](CLAUDE.md)
- **자동화 아키텍처 + 자동화 맵**: [AUTOMATION.md](AUTOMATION.md)  ← 핵심 검토 결과
- **단계별 실행 계획**: [PLAN.md](PLAN.md)
- **토픽 클러스터·콘텐츠 전략**: [docs/CONTENT-PLAN.md](docs/CONTENT-PLAN.md) ([config/topics.yaml](config/topics.yaml))
- **디자인 시스템(생성기 적용)**: [design/design.md](design/design.md) — 구현 `engine/content/renderer.py`, 목업 `design/*.dc.html`
- **리서치 근거(검증/반증)**: [docs/RESEARCH.md](docs/RESEARCH.md)
- **보고서(로컬 HTML)**: [보고서.html](보고서.html)

## ⛔ 절대 금지 (config/guardrails.yaml `forbidden`)
트래픽/클릭 생성, 클릭·노출 부풀리기, 유료 클릭, 다계정 — **구현 안 함**. = 무효 트래픽 = 영구 정지.

## 구조
```
config/      sites·niches·content(품질게이트)·guardrails(킬스위치)·schedule
engine/      ingest · content(quality_gate) · optimize · monitor(killswitch) · store · orchestrator
.claude/skills/  adsense-{audit,content,optimize,pipeline,monitor}
docs/        RESEARCH.md
```

## 셋업
1. `git init` (예약 클라우드 에이전트·버전관리·생성 콘텐츠 추적 활성화).
2. `pip install -r requirements.txt`
3. `.env.example` → `.env` 채우기 (Google/Claude/CMS/알림 키).
4. `config/sites.yaml` 도메인·CMS 어댑터 설정.
5. 니치 1개 확정: `/adsense-content`.

## 운영 (스킬로 구동)
- `/adsense-audit` — 승인 전·정기 정책 점검
- `/adsense-content` — 니치·키워드·콘텐츠 기획
- `/adsense-pipeline` — 자동 파이프라인 운영(수집→생성→게이트→발행)
- `/adsense-optimize` — RPM·Auto ads 실험·전환 판단
- `/adsense-monitor` — 정책·품질 감시 + 킬스위치

## 수동 실행 (스케줄 전 검증)
```bash
python engine/orchestrator.py --stage ingest
python engine/orchestrator.py --stage monitor
python engine/orchestrator.py --stage generate   # 초안→품질게이트→큐
python engine/orchestrator.py --stage publish     # 킬스위치·cap 준수
```
스케줄은 `config/schedule.yaml` (cron / Claude Code 예약 에이전트).

> ⚠️ 자동화로 못 채우는 것: AdSense 승인 신청, 정책 위반 이의제기, 품질 게이트 캘리브레이션, 전환 최종 결정 — **사람 필수**(AUTOMATION.md §7).
