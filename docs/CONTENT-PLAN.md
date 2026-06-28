# CONTENT-PLAN.md — 토픽 클러스터 & 콘텐츠 전략

> 니치: 기술/SaaS·개발·AI 도구 (영어 Tier-1) · 데이터: @../config/topics.yaml · 근거: @RESEARCH.md (F5·F6·F7)
> 원칙: 검색 의도(비교/거래) 우선 · 페이지마다 고유 데이터(품질 게이트) · 깊이 우선 후 대량.

## 1. 클러스터 맵 (허브 → 지원 페이지)

| # | 클러스터 | 우선 | 허브 | 프로그래매틱 패턴 | 가성비 근거 |
|---|----------|------|------|-------------------|-------------|
| A | AI 코딩/개발 도구 | P1 | Best AI coding assistants | `X vs Y` · `alternatives to X` · `X review` | 트렌딩·고의도·고CPC·E-E-A-T 적합 |
| B | VPS·호스팅·셀프호스팅 | P1 | Best cheap VPS for developers | `A vs B` · `how to self-host X` · `self-hosted alt to SaaS` | 서버 운영 경험 = 최강 E-E-A-T·고CPC |
| C | 개발/SaaS 비교 | P2 | Best dev tools by category | `X vs Y` · `best {cat} software` · `X alternatives` | 엔티티 방대 → 볼륨 |
| D | AI 생산성 도구 | P2 | Best AI tools for work | `X vs Y` · `best ai {cat}` | 수요↑·비교 의도 |
| E | VPN·보안 | P3 | Best VPNs & security tools | `A vs B` · `best vpn for {use}` | 초고CPC, 단 포화·선택적 |

## 2. 검색 의도 우선순위 (F7 — 단가 = 의도)
- **비교형(`X vs Y`)·거래형(`best`, `alternatives`, `pricing`, `worth it`)** = 광고 단가 최고 → 1순위.
- 정보형(`how to`, `what is`)은 클러스터 내부링크·권위 보강용으로 배치(허브 강화).
- **소셜·유료 트래픽 ❌** → 오가닉 검색만(F7, 자동화 금지선).

## 3. 프로그래매틱 SEO 패턴 — "생존 가능"하게 (AUTOMATION.md §3)
각 패턴 페이지는 **템플릿 + 고유 데이터(unique_data)** 필수. 순수 템플릿 치환은 게이트 거부:
- `X vs Y` → **가격표 + 기능 매트릭스 + 핸즈온 판단(verdict)**.
- `best {category}` → 후보별 **실측·가격·장단점 표**(빈 리스트 금지).
- `how to self-host X` → **실제 단계·명령·스크린샷급 디테일**(본인 서버 검증).
- `alternatives to X` → 대안별 **차이점·전환 비용·가격 비교**.

## 4. 콘텐츠 캘린더 (PLAN.md 단계 연결)
- **Phase 1 (승인 전)**: P1(A·B) 중심 **코너스톤 8~15편**을 깊게 — 허브 2 + 강한 비교글 6~12. 품질 우선(글 수 채우기 ❌). Privacy Policy 발행.
- **Phase 2 (승인 후 성장)**: 파이프라인으로 **P1 패턴 대량 생성** → 게이트 → 점진 발행(`daily_publish_cap`부터 램프업). 색인·품질 정상 시 P2(C·D) 확장.
- **Phase 3 (최적화)**: 고RPM 클러스터에 자원 집중, 저성과 통합. P3(VPN·보안)는 권위 쌓인 뒤 선택 진입.
- **Phase 4**: 25k PV/월 → 프리미엄 네트워크 net RPM 비교(F9).

## 5. E-E-A-T·디자인 연계
- 각 페이지: **저자·작성/갱신일·출처·schema.org**(quality_gate eeat 필수). 실사용 핸즈온 = 차별화.
- 비교표·기능매트릭스·가격카드·장단점·verdict·저자박스 등 **컴포넌트는 @../design/design.md** 디자인 시스템(`engine/content/renderer.py` 구현)을 따른다(광고 슬롯 CLS 예약 포함).

## 6. 측정 → 확장 (자체 데이터로 미해결 질문 해소)
- 글별 RPM·오가닉 세션·색인률을 ingest로 수집 → 고성과 패턴/엔티티에 생성 집중.
- 시드 키워드의 실제 검색량·경쟁도는 **Search Console로 검증 후** topics.yaml 확장(블로그 추정치 맹신 금지).
