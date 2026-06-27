---
name: adsense-optimize
description: AdSense RPM 최적화 + 상향 전환 판단 SOP. 코드 수정 없이 Auto ads experiments로 광고 포맷·로드·on/off를 A/B 테스트해 RPM을 올리고, Core Web Vitals(LCP/CLS)와 수익의 균형점을 찾으며, 25,000 PV/월 도달 시 Raptive 등 프리미엄 네트워크 전환을 net RPM 기준으로 검토한다. 검증된 사실(docs/RESEARCH.md F5·F8·F9)에 근거. 광고 배치 개선, RPM 정체 해소, 네트워크 전환 결정 시 사용.
---

# /adsense-optimize — RPM 최적화 · 상향 전환 SOP

## 언제 쓰나
- 광고 게재 후 RPM 개선, 광고 배치/밀도 점검, Core Web Vitals 악화 대응, **25k PV/월 도달 시 네트워크 전환 판단**.

## 가드레일 (먼저)
- **무효 트래픽 금지**(F3) — 어떤 클릭/노출 부풀리기도 계정 정지. 최적화는 **수익이 아니라 RPM/UX**를 다룬다.
- 판단 지표는 **CPC가 아니라 RPM/CPM**(2024-03 CPM 전환, Caveat 2).
- 블로그 RPM 절대값(R6·R7) 신뢰 금지 → **본인 AdSense 리포트**로 측정.

## 절차

### 1. 현황 베이스라인 (자체 데이터)
- AdSense 리포트에서 수집: **전체 RPM, 페이지별 RPM, 국가별 RPM(F5), 광고 포맷별 성과**.
- Search Console / PageSpeed에서 **Core Web Vitals(LCP·CLS·INP)** 베이스라인.
- 이 수치가 이후 모든 A/B의 비교 기준.

### 2. Auto ads experiments (1순위, 코드 수정 0 — F8)
- AdSense → **실험(Experiments)** 에서 다음을 A/B:
  - **Auto ads on vs off** (수동 배치 대비 효과 측정 — Open Q2)
  - **광고 포맷** (앵커·베스트·인피드 등)
  - **광고 로드(밀도)** 단계별
- 트래픽 분할로 사이트 전체 RPM 영향 측정 → **승자 설정만 채택**. 통계적으로 유의한 기간 확보 후 결정.

### 3. RPM vs Core Web Vitals 균형 (F8 + Open Q2)
- 광고 밀도↑ → RPM↑ 가능하나 **LCP/CLS 악화 → 검색 순위·UX·장기 RPM 손해.**
- 광고 슬롯에 **명시적 크기 예약**(reserved space)으로 CLS(레이아웃 이동) 방지.
- experiment에서 **RPM 상승분 vs CWV 저하**를 함께 보고 균형점 채택. CWV "양호" 유지가 우선.

### 4. 지역·콘텐츠 믹스 레버 (F5)
- 국가별 RPM 리포트로 **Tier-1 비중**이 RPM에 미치는 영향 확인 → 고RPM 지역 겨냥 콘텐츠(/adsense-content)로 환류.

### 5. 상향 전환 판단 (25k PV/월 — F9)
- 트래픽이 **25,000 PV/월** 도달 시 Raptive(구 AdThrive) 진입 가능 → 전환 검토 트리거.
- **결정 기준: 전환 후 net RPM > AdSense net RPM** (수수료·레비뉴셰어 반영, Open Q4).
- ⚠️ **Mediavine·Ezoic 진입 조건 클레임은 반증됨**(R10·R11) → 각 네트워크 **현재 공식 요건·수수료를 직접 견적**받아 비교. 신뢰 가능한 수치는 Raptive 25k뿐.
- net RPM 우위가 불확실하면 **AdSense 유지**.

## 출력 형식
```
[adsense-optimize] 베이스라인 RPM {x} / CWV {LCP·CLS·INP}
■ 실험: {포맷/로드/on-off} → 승자 {설정}, RPM {Δ%}, CWV {영향}
■ 지역: Tier-1 비중 {%} → 액션
■ 상향 전환: PV {n}/월 → {유지 / Raptive 견적 비교}
■ 다음 액션 & 재측정 시점
```
결과 보고는 **로컬 HTML**(Artifact 금지 — CLAUDE.md 정책).

## 절대 금지
무효 트래픽·클릭 유도, CPC 기준 오판, 블로그 RPM 절대값 단정, 반증된 네트워크 요건(Mediavine/Ezoic) 그대로 인용, CWV 무시한 광고 과밀.
