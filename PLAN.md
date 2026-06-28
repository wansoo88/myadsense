# PLAN.md — AdSense 가성비 실행 계획

> 리서치 근거: @docs/RESEARCH.md (검증된 발견 F1~F9). 항상 로드 규칙: @CLAUDE.md.
> 원칙: **최소 비용·노력 대비 최대 RPM ROI.** 글 수·유료 트래픽이 아니라 품질·니치·지역·검색 SEO·자체 A/B에 투자.
> 작성 2026-06-28.

---

## 0. 전략 한 줄 요약
**Tier-1 영어권 검색 의도 + 고CPC 니치(금융·보험·기술·건강) 콘텐츠를, 품질·권위·Privacy Policy로 승인받아, Auto ads experiments로 RPM을 자체 최적화하고, 25k PV/월에서 프리미엄 네트워크 전환을 검토한다. 유료·조작 트래픽은 쓰지 않는다.**

## 0.5 자동화 오버레이 (풀스택 + 대량 프로그래매틱 SEO — @AUTOMATION.md)
- **구동**: 보유 Ubuntu 서버 cron 24/7 (`ssh -i ~/.ssh/autobtc_iwinv root@115.68.230.40`, **nginx+certbot**, Caddy 아님). 운영·디버그는 스킬. `stack.utilverse.info` 라이브([STAGING] noindex).
- **단계별 자동화 등급**: 🟢 수집·리서치·생성·모니터·리포트 = 풀 자동 / 🟡 발행 = 품질 게이트+킬스위치+일일 cap / 🔴 승인 신청·정책 이의제기·게이트 캘리브레이션·전환 결정 = 사람 / ⛔ 트래픽·클릭 생성 = 금지(정지).
- **생존 장치**: 품질 게이트(고유 가치·근접중복·E-E-A-T) → 점진 롤아웃 → 킬스위치. 게이트 없는 대량 = 정지.

---

## 1. 단계별 로드맵 (Phase)

### Phase 0 — 준비 (Day 0, 비용 ≈ 도메인비만)
- [ ] 니치 확정: 금융·보험·기술·건강 중 **본인이 실제 경험/지식 있는 하위 니치** 1개 (E-E-A-T 신호 = 가성비). → `/adsense-content`
- [ ] 타깃 지역/언어 결정: 가능하면 **영어권(Tier-1)** 검색 의도 키워드. 한국어만 가능하면 한국 고단가 하위주제(금융·세금·보험)로 한정.
- [ ] 도메인·호스팅·CMS 셋업(저비용: 정적 사이트/WordPress 등). 빠른 로딩 = Core Web Vitals 유리.
- **산출물**: 니치 1개 + 타깃 키워드 10~20개 목록.

### Phase 1 — 승인 통과 (Week 1~3, 비용 ≈ 0)
- [ ] **고품질·독창적 콘텐츠** 작성 (글 수 채우기 ❌ → 검색 의도를 충족하는 깊이 우선, F1). 우선 **핵심 글 8~15편**을 "얇게 많이"보다 "깊게"로.
- [ ] **Privacy Policy 게시 (필수, F2)**: 데이터 수집·제3자 쿠키·벤더 링크·맞춤광고 옵트아웃(aboutads.info)·개인정보법 준수 포함.
- [ ] About/Contact 페이지는 **신뢰 신호로 권장**(필수 아님, R2) — 저비용이니 추가 권장.
- [ ] 신청 전 `/adsense-audit` 실행으로 거절 사유 사전 점검 → 신청.
- **게이트**: audit 통과 + Privacy Policy 존재 → AdSense 신청. 거절 시 사유별 보강 후 재신청.

### Phase 2 — 콘텐츠·트래픽 성장 (Month 1~6, 비용 ≈ 0, 노력 집중)
- [ ] **오가닉 검색 SEO에 집중 (F7)**: 키워드 의도 충족 + 내부 링크 + 검색 의도 매칭. 유료·소셜은 ROI·정지 리스크상 후순위.
- [ ] 고CPC 니치 키워드 확장 (F6) — `/adsense-content`로 클러스터(토픽 허브) 구축.
- [ ] 프로그래매틱 SEO는 **신중히**: helpful-content/E-E-A-T 집행 리스크(Open Q3) → 대량 저품질 양산 금지, 페이지마다 실질 가치.
- [ ] 자체 데이터 수집 시작: AdSense 리포트에서 **RPM by country / by page** 기록(블로그 수치 대신 자체 검증, Caveat 3).
- **게이트**: 안정적 오가닉 유입 + 인덱싱 정상.

### Phase 3 — RPM 최적화 (수익 발생 후 상시, 비용 ≈ 0)
- [ ] **Auto ads experiments 가동 (F8)**: 코드 수정 없이 포맷·광고 로드·on/off A/B → 사이트 RPM 최대 설정 채택. → `/adsense-optimize`
- [ ] Core Web Vitals 보호: 광고 밀도↑로 LCP/CLS 악화되면 검색 순위·UX 손해 → experiments로 **수익 vs CWV 균형점** 탐색(Open Q2).
- [ ] 지역 믹스 점검: Tier-1 비중↑ 콘텐츠로 RPM 레버 강화(F5).
- **게이트**: experiment 승자 설정 적용 + CWV "양호" 유지.

### Phase 4 — 상향 전환 검토 (25,000 PV/월 도달 시)
- [ ] **Raptive(구 AdThrive) 진입 가능 (25k PV/월, F9)** → AdSense 유지 vs 전환 **net RPM 비교**.
- [ ] ⚠️ Mediavine·Ezoic 진입 조건 클레임은 반증됨(R10·R11) → 각 네트워크 **현재 공식 요건을 직접 확인** 후 판단(Open Q4).
- **게이트**: 전환 후 net RPM이 AdSense 대비 유의미 ↑일 때만 이전.

---

## 2. 가성비 우선순위 (노력 대비 효과)

| 순위 | 레버 | 비용 | 효과 | 스킬 |
|------|------|------|------|------|
| 1 | 고CPC 니치 + Tier-1 영어권 검색 타깃팅 | 0 | ★★★ (RPM 5~30x 차이, F5·F6) | /adsense-content |
| 2 | Auto ads experiments로 RPM A/B | 0 | ★★★ (코드 수정 0, F8) | /adsense-optimize |
| 3 | 품질·권위 콘텐츠로 승인·SEO | 노력 | ★★★ (F1·F7) | /adsense-content |
| 4 | Privacy Policy·정책 준수 | 0 | ★★★ (위반=ROI 0, F2·F3) | /adsense-audit |
| 5 | 25k PV에서 프리미엄 전환 | 0 | ★★ (조건부, F9) | /adsense-optimize |
| ❌ | 유료 트래픽 구매 | 높음 | 마이너스 (정지 리스크·낮은 의도 RPM) | — |

## 3. 측정 지표 (KPI)
- **북극성**: 월 순수익 / 투입 시간 (= 가성비). 보조: **RPM/CPM**(CPC 아님, Caveat 2), 오가닉 세션, Tier-1 비중, Core Web Vitals.
- **계정 건강**: 정책 경고 0, 무효 트래픽 알림 0. (이게 깨지면 다른 KPI 무의미)

## 4. 리스크 & 회피
- **계정 정지(최대 리스크)**: 무효 트래픽 금지(F3) — 자기/지인 클릭, 유료 트래픽 남용 금지.
- **수치 맹신**: 블로그 RPM/CPC 절대값(R3~R9) 신뢰 금지 → 자체 리포트로 검증.
- **콘텐츠 품질 집행**: AI 대량 양산·스크래핑 금지(helpful-content).
- **정책 변동**: RAC(2025-11-01)·Raptive(2025-10-16) 등 최근 변화 → 운영 직전 1차 문서 재확인.

## 5. 미해결 → 자체 실험으로 해소 (docs/RESEARCH.md Open Questions)
- 한국어 vs 영어권 정확 RPM 배율 → 자체 RPM-by-country 리포트로 측정.
- Auto vs 수동 광고의 RPM·CWV 트레이드오프 → Auto ads experiments로 측정.
- 프로그래매틱 SEO 안전성 → 소량 테스트 후 인덱싱/품질 모니터.
- 25k PV에서 net RPM 손익분기 → 전환 전 양 네트워크 견적 비교.
