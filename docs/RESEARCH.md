# RESEARCH.md — AdSense 가성비 전략 리서치 근거 (검증본)

> 출처: deep-research 워크플로우 (5개 검색 앵글 · 25개 소스 fetch · 114개 주장 추출 · 25개 적대적 3표 검증).
> 작성: 2026-06-28. 모든 문서/스킬/계획은 이 파일의 **검증된 발견(✅)** 만 근거로 삼는다.
> ⚠️ **반증된 통념(❌)** 은 그대로 따르지 말 것 — 흔히 인용되지만 검증에서 깨졌다.

---

## ✅ 검증된 발견 (3-0 만장일치, high confidence)

### F1. 승인 — 공식 최소 기준(글 수·도메인 연령·트래픽)은 없다
- Google이 명시하는 실질 요건은 **(a) 고품질·독창적 콘텐츠로 청중을 끌어들일 것, (b) 정책 준수, (c) 18세 이상, (d) HTML 소스 접근권**뿐.
- 트래픽이 있어도 콘텐츠 품질·사이트 권위(E-E-A-T)가 약하면 거절된다. 2025–2026 들어 helpful-content / E-E-A-T 집행이 더 엄격.
- **함의(가성비)**: 글 수 채우기가 아니라 **품질·권위 신호**에 투자하는 것이 ROI가 높다.
- 출처: support.google.com/adsense/answer/9724 (1차) · adpushup.com/blog/google-adsense-approval

### F2. 개인정보처리방침(Privacy Policy)은 강제 필수 페이지
- 모든 AdSense 퍼블리셔는 privacy policy를 게시해야 하며, 위반 시 광고 중단·계정 정지 대상.
- 포함해야 할 것: (a) 데이터 수집·이용 공개, (b) Google 등 제3자 쿠키·광고 네트워크 고지, (c) 벤더/광고 네트워크 링크, (d) 맞춤형 광고 비동의 사용자 옵트아웃 안내(Ads Settings / aboutads.info), (e) 국내·국제 개인정보보호법 준수.
- 출처: Google Publisher Policies(1차) · support.google.com/adsense/answer/10502938 · /1348695 · termly.io

### F3. 무효 트래픽(Invalid Traffic) 금지 — 위반 시 영구 정지
- 자기 광고 클릭·수동 반복 클릭·자동화 도구·봇 등 **어떤 수단으로도** 노출/클릭 인위적 부풀리기 금지.
- 위반 시 사이트 광고 중단 또는 **계정 영구 비활성화**, 재참여 불가(신규 계정 개설도 금지).
- **함의**: 자기 트래픽 테스트조차 금지. 어떤 유료·조작 트래픽도 계정 정지 리스크가 손익을 압도.
- 출처: support.google.com/adsense/answer/48182 (1차) · /2576043

### F4. referrerAdCreative(RAC) 파라미터 — 2025-11-01 발효
- 통제된(controlled, 예: 유료·본인 소유) 소스 유입 트래픽에는 RAC 파라미터 제공이 필수. 값은 광고/링크 소스의 **정확·완전한 크리에이티브 텍스트**여야 함. 누락 = 정책 위반.
- **단, 적용 범위는 AdSense for Search의 Related Search for Content(RSoC) 요청에 한정** — 모든 AdSense 제품에 적용되지 않음.
- 출처: support.google.com/adsense/answer/9336650 (1차) · ppc.land

### F5. 지역(Geo)이 단가를 좌우 — Tier-1 ≫ Tier-3
- 미국·영국·캐나다 등 Tier-1(고구매력 영어권) 트래픽은 인도·필리핀 등 Tier-3 대비 **대략 5~30배** 높은 RPM. 원인은 구매력 높은 국가의 광고주 입찰 경쟁.
- **함의**: 영어권·Tier-1 국가를 겨냥한 콘텐츠가 핵심 ROI 레버.
- ⚠️ 방향성(Tier-1 ≫ 기타)은 견고하나 **정확한 배율은 불확실**(개별 수치 클레임은 반증됨, R-아래 참조).
- 출처: techconda.com · support.google.com/adsense/answer/160525, /190436 · ranktracker.com

### F6. 고CPC 니치 = 금융·보험·기술·건강 (여행은 중간)
- 4대 고CPC 버티컬: **금융·보험·기술·건강**. 다수 독립 벤치마크에서 최상위로 일관 확인.
- ⚠️ 여행(travel)은 통상 중간 단가(~$2대)로 진짜 고CPC 아님. (예: 동일 15만 방문 — 여행 $500–600 vs 금융 $5,000)
- 절대 CPC 숫자(보험 $5.88~$50 등)는 표본 의존적이므로 **순위/방향성만** 신뢰.
- 출처: 다수 독립 소스 교차(Newor Media, Publift, MonetizePros 등) · adsensefarm.kr

### F7. 오가닉(검색) 트래픽 > 소셜 트래픽 (CPC/RPM)
- 검색 유입은 구매·정보 의도가 높아 광고주가 더 높게 입찰 → 소셜보다 RPM/CPC 높음.
- **함의**: 가성비 트래픽의 최적해는 유료·소셜이 아니라 **검색 SEO 오가닉**.
- ⚠️ AdSense는 2024-03 CPC→CPM 모델 전환 → 'CPC' 프레이밍은 부분 구식, **RPM 기준 격차가 더 강하게 문서화됨**.
- 출처: ranktracker.com · adsensefarm.kr · (JEMSU, BloggingJoy, Mozedia 보강)

### F8. Auto ads experiments — 코드 수정 없는 저비용 RPM 최적화
- 사이트 트래픽을 분할해 서로 다른 Auto ads 설정(광고 포맷, 광고 로드, Auto ads on vs off)을 **나란히 A/B 테스트**, 사이트 전체 수익/RPM 영향 측정. **코드 수정 불필요.** 2025–2026 현재 활성.
- **함의**: 저비용·저노력 RPM 최적화의 1순위 수단.
- 출처: support.google.com/adsense/answer/9726342 (1차) · /6321879

### F9. 상향 전환 — Raptive 진입 문턱 25,000 PV/월로 인하
- Raptive(구 AdThrive)가 2025-10-16 가입 요건을 월 **100,000 → 25,000 PV (75%↓)** 로 인하 → 소규모 퍼블리셔의 프리미엄 티어 진입 문턱 급락.
- **함의**: 트래픽이 25k PV/월에 도달하면 프리미엄 네트워크 상향을 ROI 관점에서 검토.
- ⚠️ 원문 'visits' vs 'pageviews' 용어 혼용. **Mediavine $5,000 매출 모델·Ezoic 무최소 트래픽 클레임은 반증됨**(R-아래) — Raptive 25k 수치만 신뢰.
- 출처: ppc.land · searchenginejournal.com (100k→25k, 75%↓ 독립 확인)

---

## ✅ 심화 리서치 2차 (2026-07-03, 방문·리텐션·승인 — 23개 주장 3-0 검증, Google 1차 문서)

> deep-research 워크플로우(6앵글·26소스·121주장→25검증→23확정). **1차 문서 강함**. 리텐션(항목2)은 확정 발견 0 = 근거 공백.

### F10. E-E-A-T — Trust가 핵심 + "누가 책임지고 누가 작성했는지" 명시 필수
- Page Quality 평가틀(SQRG 2025-09-11). 본문(MC)은 **상당한 노력·독창성·역량**으로 작성, **사이트·콘텐츠 책임 주체가 명확**해야 함(별칭 허용). 4대 중 **Trust 최우선**. 승인의 "고품질·독창 콘텐츠" 요건과 동일 기준.
- 함의(적용 2026-07-03): `/about/` 편집기준·방법론 페이지 + Article `author`/`publisher`(Organization) + 바이라인 `/about/` 링크. ⚠️ E-E-A-T 자체는 **직접 랭킹요소 아님**(정렬된 신호로 반영) → 직접 순위상승 기대 금지.
- 출처: developers.google.com/search/docs/fundamentals/creating-helpful-content · SQRG PDF · search/blog/2022/12 E-E-A-T

### F11. YMYL(금융·보험·건강) = "매우 높은" 기준 — 우리 니치(기술)는 상대적 저부담
- 금융·보험·건강은 YMYL → **very high** 품질 기준. 즉 고CPC 니치 = 승인·랭킹 최고난도(동전의 양면).
- 함의: 본 프로젝트 니치는 **기술(SaaS/dev/AI, config niches.yaml)** → YMYL 아님 = **승인 문턱 상대적 낮음**(니치 선택 타당성 재확인). E-E-A-T 투자 없이 YMYL 드리프트 금지.
- 출처: SQRG PDF · searchengineland.com/guide/ymyl

### F12. "스케일드 콘텐츠 남용"·검색엔진-우선 대량 생성 = 스팸(집행 중)
- Google: "여러 주제로 대량 생성해 일부라도 랭크되길 기대"를 people-first 위배로 명시, spam-policy가 **scaled content abuse** 정의. 2024-25 스팸 업데이트 집행. AdSense 측: thin·auto-generated·headline-only 페이지는 **거절 1순위**(answer/81904, "complete sentences and paragraphs, not only headlines").
- 함의(적용 2026-07-03): "대량 프로그래매틱"은 **페이지별 실질 가치** 전제에서만 허용 → 품질 게이트에 **min_prose_words**(산문 최소량) 추가. 게이트 없는 대량 = 정지.
- 출처: creating-helpful-content · search/docs/essentials/spam-policies · adsense/answer/81904

### F13. 페이지 경험/Core Web Vitals — 랭킹 관련, 임계값 구체
- 'good' = **LCP ≤2.5s · INP ≤200ms · CLS ≤0.1**(CrUX 75퍼센타일). **INP가 FID 대체(2024-03)**. 단일 신호 없음 → HTTPS·모바일·**과도/방해 광고 회피** 등 폭넓게.
- 함의: 광고 밀도↑ = CWV·페이지경험 동시 악화 → 승인 후 광고 최적화 시 수익 vs CWV 균형(Open Q2). 현 디자인은 이미 충족(치수예약 CLS·JS<30KB·시스템폰트·certbot HTTPS).
- 출처: search/docs/appearance/core-web-vitals · /page-experience · web.dev/articles/vitals

### F14. Article 구조화 데이터 — 적용 속성만, 랭킹 부스트 없음
- 필수 속성 없음; 권장 headline·image·datePublished·**dateModified**·author·publisher. 랭킹 상승 보장 ❌ — 이해/표시(제목·이미지·날짜)·**신선도(dateModified)** 신호용.
- 함의(적용 2026-07-03): Article에 `publisher`(Organization)·`author`(url→/about/) 보강. 랭킹 목적 아닌 이해·표시·신선도 목적.
- 출처: search/docs/appearance/structured-data/article

### F15. 리텐션·재방문은 1차 문서상 직접 랭킹 신호 아님 — 간접 레버만
- dwell·pages/session·bounce을 랭킹 입력으로 문서화한 1차 근거 **없음**(확정 발견 0). GA4 '참여 세션' = **10초↑ OR 2페이지뷰↑ OR 전환**.
- 함의(적용 2026-07-03): 리텐션 조작 불가·저근거 → **작동하는 내부 링크(관련글·허브)로 2페이지뷰↑** 정도가 합리적 저위험 가설(과투자 금지). 기존 16편 **깨진 내부 링크 68개(관련글 52·브레드크럼 16) 전량 수정** + 허브↔글 연결.
- 출처: support.google.com/analytics/answer/12195621

---

## ❌ 반증된 통념 (검증에서 깨짐 — 그대로 따르지 말 것)

| # | 흔한 주장 | 검증 | 비고 |
|---|-----------|------|------|
| R1 | "AdSense 신청 전 글 30–40개·각 1000단어 이상" | 0-3 | 공식 최소 기준 없음(F1) |
| R2 | "About Us + Privacy + Contact 페이지 필수" | 0-3 | Google 1차로 강제되는 건 **Privacy Policy만**(F2) |
| R3 | "미국 CPC $0.50–3.00 vs 한국 $0.25–1.40 / 일본 $0.20–1.30" | 0-3 | 절대 수치 반증 |
| R4 | "미국 1클릭이 인도/파키스탄 대비 최대 50배" | 0-3 | 절대 배율 반증 (방향성만 OK) |
| R5 | "고CPC 니치 = 보험·금융 $2–9, 법률 $1.5–7…" (구체 수치) | 0-3 | 니치 순위는 OK(F6), 절대 수치는 반증 |
| R6 | "니치별 RPM: 금융 $20–50, 보험 $30–60…" | 0-3 | 절대 수치 반증 |
| R7 | "국가별 RPM: 미국 $15–40, 영국 $12–30…" | 0-3 | 절대 수치 반증 (방향성만 OK) |
| R8 | "한국 CPC(~$0.10)는 미국(~$0.61) 대비 6배 낮다" | 1-2 | 정밀 배율 불확실 |
| R9 | "최고 CPC 국가: 미국 $0.61, 호주 $0.57, 영국 $0.48, 캐나다 $0.45" | 0-3 | 절대 수치 반증 |
| R10 | "Mediavine $5,000 연매출 모델 + Journey 10k 세션 진입" | 0-3 | 반증 — 대안 비교 불완전 |
| R11 | "Ezoic은 최소 트래픽 요건 없음" | 0-3 | 반증 |
| R12 | "사이트는 가입 전 정책 준수가 1차 거절 레버" | 1-2 | 약하게 반증 (품질·권위가 더 핵심) |
| R13 | "토픽 클러스터 = 오가닉 트래픽 +30%·랭킹 유지 2.5배" | 0-3 | 내부링크/클러스터는 **합리적 관행이나 수치 근거 없음**(SEL 블로그 단일). 죽은 링크 수정은 정당하나 클러스터 기계장치 과투자 금지 |
| R14 | "내부링크 앵커텍스트 다양성↑ = 트래픽↑" | 1-2 | 약하게 반증 |

---

## ⚠️ 핵심 캐비엇 (Caveats)

1. **시간 민감성**: RAC 요건(2025-11-01), Raptive 인하(2025-10-16)는 최근 변화. 정책은 빠르게 변하므로 운영 전 1차 문서 재확인.
2. **CPC→CPM 전환**: AdSense는 2024-03 결제 모델을 CPC→CPM으로 전환. 'CPC' 중심 프레이밍은 부분 구식 → **RPM/CPM이 더 적절한 지표.**
3. **소스 품질 차이**: 정책·승인 요건·Auto ads 실험은 **Google 1차 문서**로 강하게 뒷받침(고신뢰). 그러나 **RPM/CPC 절대 수치·니치·국가 단가는 블로그·벤더 소스 의존** — Google이 공식 발표하지 않으므로 교차검증 블로그 집계가 최선. 방향성은 견고하나 절대 수치는 신뢰구간이 넓다.

## ❓ 미해결 질문 (Open Questions — 운영하며 자체 데이터로 채울 것)

0. **리텐션/재방문(dwell·pages/session·bounce)을 실제로 올리는 근거 기반 전술** — 1차 문서상 확정 발견 0(F15). Google이 참여지표를 직접 랭킹 입력으로 문서화하지 않음 → 내부 링크로 2페이지뷰↑ 유도는 저위험 가설이나 정량 근거 부재. 자체 방문 분석(nginx 로그 대시보드)으로 재방문·페이지/세션 추세를 관측해 채울 것.
1. **한국어 트래픽의 정확한 RPM/CPC 절대 수치 및 영어권 대비 배율** — 방향성은 명확(한국 < Tier-1)하나 신뢰할 1차 수치 없음 → 한국 퍼블리셔의 영어권 콘텐츠 전환 ROI 정량화 곤란.
2. **Auto ads(자동) vs 수동 배치의 RPM·Core Web Vitals 트레이드오프 구체 벤치마크** — 광고 밀도가 LCP/CLS에 미치는 정량 영향·최적 밀도 기준 데이터 부족 → **Auto ads experiments로 자체 측정**해야 함.
3. **프로그래매틱 SEO(대량 자동생성 페이지)가 helpful-content/E-E-A-T 집행에서 안전한지** — 'low value content' 거절·정지 리스크 명확한 가이드 부재.
4. **25k PV 도달 시 AdSense 유지 vs 프리미엄 네트워크 전환의 실제 순수익(net RPM) 손익분기** — 수수료·레비뉴셰어 반영 비교 미검증.

---

## 출처 등급 (sources)

- **Primary (Google 1차)**: answer/9724(승인 요건), /48182(무효 트래픽), /12171612, /9726342(Auto ads 실험), /9336650(RAC), /160525, /190436
- **Secondary**: ppc.land(프리미엄 네트워크 수치), searchenginejournal.com(Raptive)
- **Blog(교차검증)**: ranktracker.com, publift.com, adpushup.com, monetizemore.com, setupad.com, justpublishingadvice.com, goldpenguin.org, eastondev.com, whalesync.com, adsensefarm.kr, techconda.com, bloggingjoy.com, bloggingkart.com, termly.io

> 규칙: 절대 수치가 필요한 의사결정은 **블로그 수치를 신뢰하지 말고 자체 AdSense 리포트(RPM by country/page)로 검증.**
