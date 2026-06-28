# 프로젝트 컨텍스트 (CLAUDE.md) — pjt12-adsense (AdSense 가성비 운영)
# ⚠️ 150줄 이내 유지 — 상세는 PLAN.md / docs/RESEARCH.md 로 분리

## 프로젝트 개요
- **목적**: 콘텐츠 웹사이트/블로그를 **가성비(최소 비용·노력 대비 최대 수익 ROI)** 로 Google AdSense 수익화.
- **사용자**: 개인·소규모 퍼블리셔 1인.
- **핵심 전략 (리서치 검증)**: 글 수가 아니라 **품질·권위(E-E-A-T)** + **고CPC 니치(금융·보험·기술·건강)** + **Tier-1 영어권·검색 SEO 오가닉 트래픽** + **Auto ads experiments로 RPM 자체 최적화**. 유료·조작 트래픽 금지.
- **자동화**: 풀스택 + 대량 프로그래매틱 SEO. 단, **품질 게이트·점진 롤아웃·킬스위치**로 생존 가능하게. 아키텍처·자동화 맵 @AUTOMATION.md
- **배포**: 보유 Ubuntu 자체호스팅 `ssh -i ~/.ssh/autobtc_iwinv root@115.68.230.40`, `utilverse.info` 서브도메인, Caddy, **서버 cron 24/7**(pjt11 컨벤션).
- **전체 계획**: @PLAN.md · **리서치 근거(검증/반증)**: @docs/RESEARCH.md (모든 주장은 여기에 근거를 둔다)

## 🚨 절대 규칙 (가드레일 — 위반 시 계정 영구 정지 = 모든 ROI 소멸)
> 근거: docs/RESEARCH.md F2~F4. 광고 코드/전략보다 우선.

1. **무효 트래픽 절대 금지 (F3).** 자기 클릭·지인 클릭 요청·수동 반복 클릭·봇·자동화 도구·클릭 교환 — 어떤 수단으로든 노출/클릭 인위적 부풀리기 금지. 위반 = **영구 비활성화, 재참여 불가.** "테스트 클릭"조차 금지.
2. **Privacy Policy 필수 (F2).** 데이터 수집·제3자(Google) 쿠키·벤더 링크·맞춤광고 옵트아웃(aboutads.info) 고지 포함. 누락 시 광고 중단.
3. **유료 트래픽은 기본 회피.** 부득이 통제된(유료) 트래픽 사용 시 **referrerAdCreative(RAC) 파라미터 필수**(2025-11-01 발효, RSoC 한정). 컴플라이언스 부담·정지 리스크 > 단기 수익 → 기본은 오가닉.
4. **저작권·콘텐츠 정책 준수.** 스크래핑·복제·AI 대량 양산 저품질 콘텐츠 금지(helpful-content 집행 강화). 독창적·유용한 콘텐츠만.
5. **자동화 천장 (AUTOMATION.md §0).** ⛔ 트래픽/클릭 생성·부풀리기·유료클릭·다계정은 **코드/스케줄 어디에도 구현 금지**(=무효 트래픽=정지). 🟡 발행은 **품질 게이트 통과분만** + 킬스위치 + 일일 cap. 🟢 수집·분석·생성·모니터·리포트는 자유 자동화. **"대량"은 분량이지 게이트 우회가 아니다.**

## ❌ 따르지 말 것 (흔한 통념 — 리서치에서 반증됨, docs/RESEARCH.md R1~R12)
- ❌ "글 30~40개·1000단어 이상 채우고 신청" → **공식 최소 기준 없음.** 품질 우선.
- ❌ "About/Contact 페이지 필수" → Google 1차 강제는 **Privacy Policy만.** (About/Contact는 신뢰 신호로 권장이지 필수 아님)
- ❌ 블로그가 인용하는 **CPC/RPM 절대 수치**(미국 $0.61, 한국 6배 낮음, 50배 클릭 등) → 반증됨. **순위·방향성만** 신뢰, 절대값은 자체 리포트로 검증.
- ❌ "Mediavine $5,000 매출 모델 / Ezoic 무최소 트래픽" → 반증됨. **신뢰 가능한 상향 수치는 Raptive 25k PV/월(F9)뿐.**

## 핵심 의사결정 원칙 (가성비 레버 — docs/RESEARCH.md F1·F5~F9)
- **승인**: 글 수 ↓, **품질·권위·Privacy Policy** ↑. (F1, F2)
- **니치**: 금융·보험·기술·건강 우선. 여행은 중간 단가(고CPC 아님). (F6)
- **지역/언어**: Tier-1 영어권(미·영·캐) 트래픽이 Tier-3 대비 ~5–30배 RPM. 영어권 검색 의도 콘텐츠가 최고 ROI. (F5, F7)
- **트래픽**: 오가닉 검색 SEO ≫ 소셜 ≫ 유료. 유료는 손익·정지 리스크상 비권장. (F7)
- **광고 최적화**: 코드 수정 없이 **Auto ads experiments** A/B로 RPM 측정·개선. (F8)
- **상향 전환**: 25,000 PV/월 도달 시 Raptive 등 프리미엄 네트워크 ROI 검토. 그 전엔 AdSense. (F9)
- **지표**: CPC가 아니라 **RPM/CPM** 기준으로 판단(2024-03 CPM 전환). (Caveat 2)

## 프로젝트 구조 (요약 — 상세 @AUTOMATION.md §2)
- `config/` sites·niches·**topics(클러스터·시드)**·content(품질게이트)·guardrails(킬스위치)·schedule (하드코딩 금지 → 값으로 관리)
- `engine/` ingest·content(`quality_gate.py`)·optimize·monitor(`killswitch.py`)·store·`orchestrator.py`
- `docs/RESEARCH.md` 근거 · `docs/CONTENT-PLAN.md` 토픽전략 · `AUTOMATION.md` 아키텍처 · `PLAN.md` 단계 · **`design.md` 디자인 시스템(생성기가 모든 페이지에 적용)**

## 실행 스킬 (.claude/skills — 필요 시 /로 호출)
- **/adsense-audit** — 승인 준비도 + 정책 위반 점검 (신청 전·재신청·정기 점검)
- **/adsense-content** — 고ROI 니치/지역/SEO 콘텐츠 기획·키워드 선정
- **/adsense-pipeline** — 자동 파이프라인 운영(수집→생성→품질게이트→발행, 점진 롤아웃)
- **/adsense-optimize** — 광고 배치·Auto ads experiments·RPM 개선·상향 전환 판단
- **/adsense-monitor** — 정책·품질 감시 + 킬스위치(이상 시 발행 자동 중단)

## 작업 규칙
- 모든 권고는 **docs/RESEARCH.md의 검증된 발견(✅)에만** 근거. 반증된 통념(❌)을 재유포하지 말 것.
- 절대 수치(RPM·CPC)가 필요하면 블로그 인용 대신 **사용자의 AdSense 리포트 데이터를 요청**해 검증.
- 정책 관련 조언은 **시간 민감** → 운영 직전 Google 1차 문서(support.google.com/adsense) 재확인 권고.
- 새 사실을 검증·반증하면 docs/RESEARCH.md에 출처와 함께 추가/수정.

## 산출물 보고
- 보고는 **로컬 HTML 파일**(예: `보고서.html`)로. **Artifact로 만들지 않는다**(프로젝트 정책).
