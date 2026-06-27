---
name: adsense-monitor
description: AdSense 자동 감시 + 킬스위치 운영 SOP — 정책센터 경고·무효 트래픽 알림·수동 조치·색인 급락·Core Web Vitals 불량·RPM 이상·신규 페이지 색인 거부율을 주기적으로 수집해, 임계 초과 시 발행을 즉시 자동 중단(killswitch)하고 알림을 보낸다. 대량 자동 발행의 안전벨트. 감시 잡 운영·디버그, 킬스위치 트리거 점검, 알림 채널 설정, 중단 해제(사람 확인) 시 사용.
---

# /adsense-monitor — 감시 · 킬스위치 SOP

## 언제 쓰나
- 상시 감시 잡(`--stage monitor`) 운영/디버그, 킬스위치 트리거·임계 조정, 알림 채널 설정, **중단 해제(원인 확인 후 사람)**.

## 원칙 (AUTOMATION.md §4)
- 자동 발행 규모가 클수록 **자동 차단이 필수.** 감시는 발행을 멈추는 안전장치다.
- **무효 트래픽 알림(F3)은 최우선 트리거** — 즉시 중단·알림. 계정 정지 = ROI 0.
- 해제는 **사람이 원인 확인 후 수동**(`auto_resume:false`). 자동 재개 금지.

## 절차
1. **신호 수집(`monitor/health.py`)** 🟢 — 읽기 API로:
   - AdSense 정책센터 경고 / 무효 트래픽 알림 / 수익·RPM 이상.
   - Search Console: 수동 조치, 색인률, 신규 페이지 색인 거부율.
   - PageSpeed/CWV: LCP·CLS·INP "불량" 여부.
2. **킬스위치 평가(`killswitch.evaluate`)** — `config/guardrails.yaml` 임계와 비교:
   - invalid_traffic / policy_warning / manual_action → 즉시 trip.
   - indexing_drop ≥30% / cwv_poor / rpm_drop ≥50% / deindex_rate ≥40% → trip.
3. **중단(`engage`) + 알림(`alerts.send`)** — 발행 즉시 중단, 사유 텔레그램/슬랙 통보.
4. **해제(사람)** — 원인 확인·해소 후 `killswitch.clear()`. 그 전엔 publish 차단됨.

## 출력 형식
```
[adsense-monitor] {timestamp}
■ 정책: 경고 {없음/발견} · 무효트래픽 {정상/알림} · 수동조치 {없음/발견}
■ 색인: 거부율 {%} · 급락 {%} / CWV {LCP·CLS·INP} {양호/불량} / RPM Δ {%}
■ 킬스위치: {정상 / 중단 — 사유: ...}
■ 액션: {계속 / 발행중단됨 → 원인 {...} → 해소 후 clear()}
```
주간 종합은 로컬 HTML 리포트(`reports/weekly_*.html`, Artifact 아님).

## 절대 금지
킬스위치 자동 해제, 무효 트래픽 알림 무시, 임계를 정지 회피용으로 느슨화, 경고를 사람에게 안 알리고 발행 지속.
