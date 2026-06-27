---
name: adsense-pipeline
description: AdSense 자동화 파이프라인 운영 SOP — 수집(ingest)→리서치→생성(generate)→품질 게이트→발행(publish)을 config 주도로 돌린다. 대량 프로그래매틱 SEO를 "생존 가능"하게(페이지별 고유 가치 게이트 + 점진 롤아웃 + 킬스위치) 운영한다. 파이프라인 단계 실행·디버그, 발행 큐 점검, 새 CMS/소스 어댑터 추가, 배치 발행 운영 시 사용. 트래픽/클릭 생성은 절대 다루지 않는다(계정 정지).
---

# /adsense-pipeline — 자동 콘텐츠 파이프라인 운영 SOP

## 언제 쓰나
- 파이프라인 단계 실행/디버그, 발행 큐·품질 게이트 통과율 점검, CMS/소스 어댑터 추가, 배치 발행 램프업.

## 가드레일 (먼저 — AUTOMATION.md §0·§4)
- ⛔ **트래픽/클릭 생성·부풀리기·다계정은 파이프라인에 없다.** 구현/실행 금지(F3).
- 🟡 **발행은 품질 게이트 통과분만 + 킬스위치 + 일일 cap 준수.** 게이트 우회 금지.
- 발행 전 `killswitch.is_halted()` 확인 — 중단 상태면 사람이 원인 확인·`clear()` 전까지 발행 금지.

## 단계 (engine/orchestrator.py --stage ...)
1. **ingest** 🟢 — AdSense/Search Console/PageSpeed API → DB. 읽기 전용.
2. **research** 🟢 — `config/niches.yaml` weights로 키워드·니치·지역 스코어. Tier-1 영어권·비교/거래 의도 우선(F5·F7).
3. **generate** 🟢 — Claude로 초안 + **페이지별 고유 데이터 주입**. 순수 템플릿 치환 금지.
4. **gate** 🟢 — `quality_gate.check()` 전부 PASS만 발행 큐로 (AUTOMATION.md §3):
   - 고유 가치 / 근접중복(<0.70) / 구조(빈 골격 거부) / E-E-A-T(출처·날짜·저자·schema) / 정책 스크리닝.
   - 배치의 `sample_pct`(기본 10%)는 휴먼 승인 큐로 분기.
5. **publish** 🟡 — 큐에서 `daily_publish_cap`만큼 점진 발행. 색인 정상일 때만 다음 배치 램프업.

## 운영 절차
1. **드라이런 우선**: 신규 어댑터·템플릿은 소량(예: 5건) 생성→게이트→발행으로 검증 후 확대.
2. **게이트 통과율 모니터**: 통과율이 낮으면 템플릿/고유 데이터 소스를 개선(거부 사유 로그 활용). 게이트를 느슨하게 풀지 말 것.
3. **점진 롤아웃**: `daily_publish_cap`부터 시작, 색인·품질 정상 시 `ramp_up_factor`로 단계 상향(상한 `ramp_up_max`).
4. **CMS 어댑터 추가**(`engine/content/publisher.py`): 공통 인터페이스 `publish(page)->url`. WordPress REST / static SSG. `config/sites.yaml`에 등록, 드라이런 검증.

## 출력 형식
```
[adsense-pipeline] stage={...}
■ 생성 {n} → 게이트 통과 {p}/{n} (통과율 {%}) / 거부 사유 top: ...
■ 발행 {published}/{cap} (램프업 {상태}) / 킬스위치 {정상/중단}
■ 색인 추세 / 다음 배치 조건
```

## 절대 금지
트래픽/클릭 자동화, 품질 게이트 우회·완화 후 대량 발행, 킬스위치 중단 중 발행, 순수 템플릿 양산.
