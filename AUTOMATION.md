# AUTOMATION.md — 풀스택 자동화 아키텍처 & 자동화 맵

> 목표: **최대한 자동화** (사용자 결정: 풀스택 + 대량 프로그래매틱 SEO).
> 근거: @docs/RESEARCH.md · 가드레일: @CLAUDE.md · 단계: @PLAN.md.
> 원칙: **자동화 천장을 인정한다** — 콘텐츠·SEO·데이터·모니터링·리포팅은 풀 자동화, 발행은 품질 게이트, **트래픽/클릭은 자동화 불가(계정 영구 정지)**.

---

## 0. 자동화 천장 (먼저 읽을 것)

리서치 검증 결과 자동화는 3개 층으로 나뉜다. **이 경계를 넘으면 ROI가 0이 된다.**

- 🟢 **자유 자동화** — 데이터 수집·분석·키워드 리서치·콘텐츠 초안 생성·모니터링·리포팅·알림. 리스크 0.
- 🟡 **게이트 자동화** — 콘텐츠 발행(품질 게이트 통과분만), Auto ads 실험 결정, 네트워크 전환 결정. 리스크는 품질·정책.
- ⛔ **금지 자동화** — 트래픽 생성, 클릭/노출 부풀리기, 봇 방문, 자기/지인 클릭, 유료 클릭, 다계정. **= 무효 트래픽(F3) = 영구 정지.** 코드·스케줄 어디에도 구현하지 않는다.

> "대량 프로그래매틱 SEO"는 **발행 분량**의 대량이지, 품질 게이트를 건너뛴 대량이 아니다. 게이트 없는 대량 = 저품질 색인 제외·정지의 1순위 원인.

---

## 1. 자동화 맵 (전략 요소 → 자동화 등급)

| 전략 요소 (리서치) | 등급 | 자동화 방법 | 리스크 |
|---|---|---|---|
| 키워드·니치 리서치 (F5·F6) | 🟢 풀 | Search Console API + Claude로 니치/지역/의도 스코어링 | 없음 |
| 콘텐츠 초안 생성 (프로그래매틱) | 🟢 풀(생성) | Claude API + 템플릿 + **페이지별 고유 데이터 주입** | 게이트 전엔 미발행 |
| 품질 게이트 (중복·가치·E-E-A-T) | 🟢 풀 | 자동 검사 → 통과분만 발행 큐 | 리스크 **완화** 장치 |
| 콘텐츠 발행 | 🟡 게이트 | CMS API, **배치·점진 롤아웃**, 색인/품질 모니터 | 저품질·대량 → 정지 |
| Privacy Policy·필수 페이지 (F2) | 🟢 풀 | 템플릿 1회 자동 생성·발행 | 없음 |
| AdSense 승인 신청 (F1) | 🔴 수동 | **승인 API 없음** — 사람이 신청 | — |
| 광고 게재 / Auto ads (F8) | 🟢 구글-자동 | Auto ads가 자동 게재 | 없음 |
| Auto ads experiments (F8) | 🟡 보조 | 데이터 기반 결정, 셋업 반자동 | 없음 |
| RPM·지역 분석 (F5·F7) | 🟢 풀 | AdSense Management API + 분석기 | 없음 |
| Core Web Vitals 모니터 | 🟢 풀 | PageSpeed Insights / Search Console API | 없음 |
| 색인·SEO 모니터 | 🟢 풀 | Search Console API | 없음 |
| 정책·무효 트래픽 감지 (F3) | 🟢 풀(감지) | 정책센터 폴링 → 알림 → **킬스위치** | 치명적 → 자동 감지 필수 |
| 네트워크 전환 판단 (F9) | 🟡 보조 | net RPM 계산, 사람이 결정 | 없음 |
| **트래픽/클릭 생성, 유료클릭, 다계정** | ⛔ **금지** | **구현 안 함** | **영구 정지·사기** |

---

## 2. 풀스택 아키텍처 (config 주도 + 어댑터 패턴, 형제 프로젝트 컨벤션)

```
[스케줄러: cron / Claude Code 예약 에이전트]
        │  (일·주·상시 케이던스 = config/schedule.yaml)
        ▼
┌──────────────────────── orchestrator.py ────────────────────────┐
│ 1. INGEST   adsense_api · search_console · pagespeed → store(DB) │  🟢
│ 2. RESEARCH keyword_research (니치·지역·의도 스코어)            │  🟢
│ 3. GENERATE generator (Claude + 템플릿 + 고유 데이터)          │  🟢
│ 4. GATE     quality_gate (중복·가치·E-E-A-T·구조 검사)         │  🟢 ← 발행 전 강제
│ 5. PUBLISH  publisher (CMS 어댑터, 배치·점진 롤아웃)            │  🟡 ← 게이트 통과분만
│ 6. OPTIMIZE rpm_analyzer · experiment_advisor (권고)           │  🟡
│ 7. MONITOR  health · killswitch · alerts (상시)                │  🟢 ← 정책·품질 이상 시 발행 중단
└──────────────────────────────────────────────────────────────────┘
        │
        ▼  알림(텔레그램/슬랙/메일) + 로컬 HTML 리포트
```

### 레이어별 책임
- **ingest/** (읽기전용, 리스크0): `adsense_api.py`(RPM·수익 by country/page), `search_console.py`(쿼리·색인·CWV), `pagespeed.py`(LCP/CLS/INP). → `store/db.py`(SQLite).
- **content/**: `keyword_research.py`(키워드 스코어), `generator.py`(초안), **`quality_gate.py`(핵심)**, `publisher.py`(CMS 어댑터).
- **optimize/**: `rpm_analyzer.py`(지역·페이지 RPM 추세), `experiment_advisor.py`(Auto ads 실험·전환 권고).
- **monitor/**: `health.py`(정책센터·색인·CWV·RPM 이상 감지), **`killswitch.py`(발행 자동 중단)**, `alerts.py`.
- **orchestrator.py**: 위 단계 와이어링, config 케이던스대로 실행.

---

## 3. 프로그래매틱 SEO를 "생존 가능"하게 — 품질 게이트 (config/content.yaml)

게이트 없는 대량 = 정지. 모든 페이지는 발행 전 **전부 통과**해야 한다(`quality_gate.py`):

1. **고유 가치(unique value)**: 페이지마다 템플릿 외 **고유 데이터/계산/비교/표** 1개 이상. 순수 템플릿 치환만 = 거부.
2. **근접 중복 차단**: 기존·신규 페이지 간 유사도(예: MinHash/Jaccard) 임계 초과 = 거부.
3. **구조·분량**: 검색 의도 충족 섹션 구비, 최소 실질 본문(빈 골격 거부). ⚠️ "1000단어" 같은 숫자는 목표 아님(R1) — **의도 충족**이 기준.
4. **E-E-A-T 신호**: 출처·작성/갱신일·저자·구조화 데이터(schema.org).
5. **정책 스크리닝**: 금지 주제·클릭 유도 문구·저작권 침해 자동 필터.
6. **샘플 휴먼 게이트**: 배치의 N%는 사람 승인 큐(품질 캘리브레이션).

→ **통과분만** 발행 큐로. 거부분은 사유 로깅 후 재생성 대상.

---

## 4. 점진 롤아웃 & 킬스위치 (config/guardrails.yaml)

대량을 한 번에 쏟지 않는다 — **램프업 + 자동 차단**:

- **배치 발행**: 하루 N개 상한(`daily_publish_cap`)으로 점진 발행. 색인·품질 추세 정상일 때만 다음 배치.
- **킬스위치 트리거(`killswitch.py`) → 발행 즉시 중단 + 알림**:
  - 정책센터 경고 / **무효 트래픽 알림** 발생
  - 색인률 급락 / 수동 조치(manual action)
  - CWV "불량" 전환 / RPM 이상 급락
  - 신규 페이지 색인 거부율 임계 초과(저품질 신호)
- 해제는 **사람이 원인 확인 후 수동**. 자동 재개 없음.

> 킬스위치는 "최대 자동화"의 안전벨트다. 자동 발행 규모가 클수록 자동 차단이 필수.

---

## 5. 스케줄 (config/schedule.yaml) — 케이던스

| 잡 | 주기 | 내용 |
|----|------|------|
| ingest | 매일 | API 데이터 수집 → DB |
| monitor | 상시(예: 1h) | 정책·색인·CWV·RPM 이상 감지 + 킬스위치 |
| research | 주간 | 키워드·니치·지역 스코어 갱신 |
| generate+gate | 주간 | 초안 생성 → 품질 게이트 → 발행 큐 |
| publish | 매일 | 큐에서 `daily_publish_cap`만큼 점진 발행 |
| report | 주간 | 로컬 HTML 리포트(RPM·세션·CWV·게이트 통과율) |

구동: **보유 Ubuntu 서버의 cron으로 24/7 실행** (`config/sites.yaml` deploy). 서버: `ssh -i ~/.ssh/autobtc_iwinv root@115.68.230.40`, 도메인 `utilverse.info` 서브도메인. **웹서버는 nginx+certbot**(80/443, data·itsmine 등 공유 — Caddy 아님). `stack.utilverse.info` 라이브(정적 vhost+TLS 1회 셋업 완료, [STAGING] X-Robots-Tag noindex). 콘텐츠 배포는 `engine/deploy.py`(tar/scp over ssh). `config/schedule.yaml` → 서버 `crontab`. 보조로 Claude Code 예약 에이전트(`/loop`)·스킬로 점검·디버그. ⚠️ 버전관리·예약 클라우드 에이전트는 **`git init` 후** 가능(이전 ultraplan이 git 부재로 실패).

> 자체 서버가 있으므로 "최대 자동화"의 케이던스는 **서버 cron이 1차**(상시 monitor·일일 ingest/publish). Claude Code는 운영·디버그·리포트 해석 레이어.

---

## 6. 기술 스택 & 외부 API (현실 점검)

- **읽기 API(자동화 핵심, 무료/저비용)**: AdSense Management API, Google Search Console API, PageSpeed Insights API.
- **생성**: Claude API (`claude-opus-4-8` 등) — 초안·요약·구조화.
- **발행(쓰기)**: CMS 어댑터 — 기본 **WordPress REST API**(프로그래매틱 SEO 대중적) 또는 **정적 SSG + git**. → `config/sites.yaml`에서 선택(어댑터 패턴).
- **저장**: SQLite(`engine/store`). **알림**: 텔레그램/슬랙/메일.
- ⚠️ **승인·정책 위반 해소·콘텐츠 품질 최종 판단은 자동화 불가** → 사람 게이트.

---

## 7. 자동화로도 못 채우는 것 (사람 필수)
1. AdSense **승인 신청·검수**(API 없음).
2. 정책 위반/무효 트래픽 **이의제기·원인 해소**.
3. 품질 게이트 **캘리브레이션**(샘플 승인) — 자동 검사의 오탐/미탐 보정.
4. 네트워크 전환 **최종 결정**(net RPM 비교 후).
5. 미해결 질문(docs/RESEARCH.md): 한↔영 RPM 배율, 프로그래매틱 SEO 안전 한계 → **소량 테스트로 자체 데이터 축적** 후 확장.
