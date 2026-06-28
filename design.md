# design.md — stack.utilverse.info 디자인 시스템

> 목적: **콘텐츠 생성기(generator)가 모든 페이지에 일관되게 입히는 디자인 스펙.** 사람·Claude 모두 이 토큰/컴포넌트만 따른다.
> 사이트 분위기: **모던·테크·신뢰형 에디토리얼** (SaaS·개발·AI 도구 비교/가이드).
> 제약은 디자인에 내장: **Core Web Vitals(LCP/CLS/INP) 안전 · 광고 슬롯 CLS 예약 · E-E-A-T 신뢰 요소 · 가독성 우선.** 근거 @docs/RESEARCH.md(F2·F8), @AUTOMATION.md(§3).

---

## 1. 디자인 원칙 (우선순위 순)
1. **가독성 우선** — 본문은 읽기 위한 것. 긴 비교/가이드를 편하게.
2. **CWV 안전** — 시스템 폰트(웹폰트 fetch 금지), 모든 미디어·광고에 **치수 예약**(CLS=0 지향), JS 최소·지연.
3. **광고는 통합되되 비침투** — 콘텐츠 흐름에 자연스럽게, **레이아웃 이동 없이**, 정책 준수(클릭 유도·기만 배치 금지, F2/F3).
4. **신뢰(E-E-A-T)** — 저자·날짜·출처·구조화 데이터를 디자인으로 명시.
5. **테크 정체성** — 절제된 모노스페이스·코드블록·정밀한 표. 화려함보다 정확·깔끔.

## 2. 컬러 토큰 (CSS 변수 — 라이트 기본 + 다크 토글)
```css
:root{                      /* Light = 본문 가독·광고 시인성 최적 */
  --bg:#ffffff; --surface:#f7f8fa; --surface-2:#eef1f6;
  --ink:#1a1f2b; --ink-soft:#3d4654; --muted:#5b6573;
  --line:#e5e8ee; --line-strong:#d3d8e2;
  --accent:#2f6df6; --accent-ink:#1b4fd1;   /* 테크 블루 — 링크·강조 */
  --good:#0f8a5f; --warn:#b5791a; --bad:#c2392f;
  --code-bg:#0f1320; --code-ink:#e7ebf2;     /* 코드블록은 라이트에서도 다크 */
  --ad-bg:#f4f6fa; --ad-label:#9aa4b2;       /* 광고 영역 — 본문과 미세 구분 */
}
:root[data-theme="dark"]{   /* 개발자 선호 다크 (토글) */
  --bg:#0f1115; --surface:#171a21; --surface-2:#1d212b;
  --ink:#e7ebf2; --ink-soft:#c4ccd8; --muted:#9aa4b2;
  --line:#2a2f3a; --line-strong:#3a4150;
  --accent:#5b9cff; --accent-ink:#8bb6ff;
  --good:#2ecc71; --warn:#f5b942; --bad:#ff6b6b;
  --code-bg:#0c0e13; --code-ink:#e7ebf2; --ad-bg:#141821; --ad-label:#6b7585;
}
```
- 대비 **WCAG AA 이상**. 다크 토글은 `localStorage` + `data-theme`, **FOUC 방지 위해 `<head>` 인라인 스크립트로 초기 적용**(JS 최소).

## 3. 타이포그래피 (시스템 폰트 = CWV·CSP 안전)
```css
--font-sans: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Malgun Gothic",sans-serif;
--font-mono: ui-monospace,SFMono-Regular,"Cascadia Code",Consolas,monospace;
```
- 본문 **17px / line-height 1.7**, 읽기 폭 **max 68ch**. 모바일 16px.
- 스케일: h1 30–34 / h2 24 / h3 19 / small 13.5. h2·h3는 앵커 + 좌측 액센트.
- 링크: `--accent`, hover 밑줄. 외부 링크 `rel="nofollow sponsored"`(제휴 시), 출처는 `noopener`.

## 4. 레이아웃
- **단일 칼럼 본문**(68ch) 중심 + 데스크톱 ≥1024px에서 우측 사이드바(목차/광고). 모바일 1칼럼.
- 컨테이너 max **1120px**, 본문 영역 **720px**. 여백 스케일 4/8/12/16/24/32/48.
- 헤더: 슬림(로고 + 카테고리 + 검색 + 다크토글), `position:sticky` 가볍게. 푸터: About·Contact·**Privacy Policy(필수)**·카테고리.

## 5. 컴포넌트 (생성기가 출력할 표준 블록)
- **Article hero**: H1 + dek(요약 1–2줄) + **메타바(저자·작성/갱신일·읽기시간)** → E-E-A-T 즉시 노출.
- **TOC(목차)**: 긴 글 자동 생성, 스크롤 하이라이트(경량 IntersectionObserver).
- **Comparison table**: 반응형(모바일 가로스크롤 `overflow-x:auto`), sticky 헤더, 행 zebra, 승자 셀 `--good` 강조.
- **Feature matrix**: ✓/✗(`--good`/`--bad`) + 각주. 셀 치수 고정(CLS 방지).
- **Pricing cards**: 플랜별 카드, 가격·핵심기능·CTA. 숫자는 `tabular-nums`.
- **Pros/Cons**: 2칼럼(장 `--good` / 단 `--bad`).
- **Verdict/Callout 박스**: 좌측 액센트 보더, 핸즈온 결론·주의.
- **Author box(E-E-A-T)**: 이름·한줄 전문성·갱신일. 본문 하단.
- **Sources**: 번호 인용 + 하단 출처 리스트(투명성).
- **Related/Internal links**: 같은 클러스터 내부링크(허브↔지원, 토픽 권위).
- **Breadcrumb**: 클러스터 경로 + `BreadcrumbList` schema.

## 6. 광고 슬롯 (CLS 예약 = CWV 핵심, F8)
> 모든 슬롯은 **min-height/aspect-ratio로 공간을 미리 예약** → 광고 로드 시 레이아웃 이동 0.
- **슬롯 위치**(밀도는 `config/content.yaml` 따름):
  - `below-hero` (리더보드, 데스크톱 728×90 / 모바일 320×100) — **단, LCP 요소를 밀어내지 않게 hero 이미지·H1 아래**.
  - `in-content` (반응형, min-height 280px) — 섹션 사이 1–2개, 본문 흐름 자연스럽게.
  - `sidebar-sticky` (데스크톱 300×600) — 사이드바.
- **예약 CSS 예**: `.ad-slot{min-height:280px;display:flex;align-items:center;justify-content:center;background:var(--ad-bg)} .ad-slot::before{content:"Advertisement";color:var(--ad-label);font-size:11px}`
- **금지**: 첫 화면 과밀, 콘텐츠/버튼 인접 기만 배치, 광고 클릭 유도, 인터스티셜. (정책 위반 = 정지, F3)

## 7. 미디어·이미지 (CLS·LCP)
- `<img>`에 **width/height 필수**, `loading="lazy"`(첫 화면 제외), `decoding="async"`. 가능하면 AVIF/WebP.
- hero·아이콘은 인라인 SVG/시스템 이모지(외부 fetch 0, CSP 안전).

## 8. 성능 예산 (CWV 게이트)
- **LCP < 2.5s · CLS < 0.1 · INP < 200ms** 목표(=Search Console "양호").
- Critical CSS 인라인, 비핵심 CSS/JS `defer`. 페이지당 JS **< 30KB**(토글·TOC만). 트래킹 스크립트 최소.

## 9. 구조화 데이터 (E-E-A-T·quality_gate eeat 연계)
- 비교/리뷰: `Article` + `Review`/`ItemList`(+ `Product`/`SoftwareApplication` aggregateRating은 **실제 평가 시에만**, 조작 금지).
- 저자 `author`, 날짜 `datePublished`/`dateModified`, `BreadcrumbList`. 게이트가 `require_schema_org`로 검사.

## 10. 접근성·반응형
- 시맨틱 HTML, 랜드마크, 포커스 가시화, 대비 AA, 이미지 alt.
- 브레이크포인트: 모바일 우선 → ≥640(여백) → ≥1024(사이드바 등장). 표·코드·매트릭스는 **자체 `overflow-x:auto`**(본문 가로스크롤 금지).

---

### 생성기 적용 규칙 (요약)
1. 페이지 유형(comparison/listicle/guide/alternatives) → §5 컴포넌트 매핑.
2. 토큰(§2·§3)만 사용, 하드코딩 색·폰트 금지.
3. 광고 슬롯은 §6 예약 규칙 위반 시 발행 게이트 거부.
4. §9 구조화 데이터·저자·날짜 누락 시 `quality_gate` eeat 실패 → 미발행.
