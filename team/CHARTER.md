# CHARTER.md — pjt12-adsense 에이전트 팀 헌장 (PM 중심 지휘 구조)

> 근거: @CLAUDE.md(절대 규칙) · @AUTOMATION.md(자동화 천장·게이트) · @docs/RESEARCH.md(F1~F15)
> 작성 2026-07-24. **이 문서가 팀의 최상위 운영 규칙이다. 개별 에이전트 판단보다 우선한다.**

---

## 0. 한 줄 원칙

**사람은 PM 하나에게만 말한다. PM이 분해·지시·검증·보고한다. 워커는 사람과 직접 대화하지 않는다.**

이 프로젝트의 최대 리스크는 "기술 실패"가 아니라 **정책 위반(계정 영구 정지)** 과 **게이트 없는 대량 발행**이다.
따라서 팀은 기능이 아니라 **권한 분리**로 나눈다 — 만드는 자(CONTENT) ≠ 막는 자(REVIEW) ≠ 내보내는 자(OPS).

---

## 1. 조직도 (pane 배치)

```
┌──────────────────────┬─────────────────┬─────────────────┐
│                      │  CONTENT        │  REVIEW         │
│   PM                 │  기획·생성       │  검수·감사·게이트 │
│   사람 ↔ 팀 유일 창구  ├─────────────────┼─────────────────┤
│   지시·검증·보고       │  OPS            │  GROWTH         │
│                      │  파이프라인·배포   │  유입·RPM·분석    │
└──────────────────────┴─────────────────┴─────────────────┘
```

- 모든 pane cwd = `D:\cashflow\pjt12-adsense`, 에이전트 = Claude Code (`claude`).
- **지시 대상은 pane id가 아니라 이름**(`pm` `content` `review` `ops` `growth`)으로 지정한다. 재부팅으로 id가 바뀌어도 이름은 유지.
- 현재 pane id는 `herdr pane list` 로 확인. 팀 부팅/복구는 `scripts/team_up.ps1`.

---

## 2. 역할·소유·권한

| 에이전트 | 책임 | 소유 파일/영역 | 주 스킬 | ⛔ 금지 |
|---|---|---|---|---|
| **PM** | 사람 지시 접수 → 분해 → 지시서 발행 → 검증 → 게이트 판정 → 보고 | `team/**`, 로드맵(PLAN.md) 갱신 제안 | (전체 조망) | 사람 승인 없이 발행·배포 지시, 킬스위치 해제 |
| **CONTENT** | 키워드·토픽 기획, 초안 생성, 소스 수집, 렌더링 | `config/topics.yaml`·`niches.yaml`, `engine/content/{generator,keyword_research,source_fetch,renderer}.py`, `docs/CONTENT-PLAN.md` | `/adsense-content` | 발행·배포 실행, **자기 글 검수 통과 선언**, 서버 접속 |
| **REVIEW** | 품질·정책·법적 리스크 검수, 승인 준비도 감사, 킬스위치 감시 | `engine/content/{quality_gate,reviewer,human_gate}.py`, `engine/monitor/{killswitch,health}.py`, `config/content.yaml`·`guardrails.yaml` | `/adsense-review` `/adsense-audit` `/adsense-monitor` | **콘텐츠 생성**(이해상충), 자기 판정만으로 발행 실행 |
| **OPS** | 파이프라인 실행, 사이트 빌드·배포, 서버·cron·nginx 운영 | `engine/{orchestrator,deploy}.py`, `engine/content/{publisher,site_builder}.py`, `scripts/*`, `config/{schedule,sites}.yaml`, 서버 `115.68.230.40` | `/adsense-pipeline` | 게이트 미통과분 발행, 킬스위치 ON 상태 발행, 킬스위치 해제 |
| **GROWTH** | RPM·Auto ads 실험 권고, 색인·유입·방문 분석, 신디케이션, 리포트 | `engine/optimize/*`, `engine/analytics/*`, `engine/ingest/*`, `engine/report.py`, `config/analytics.yaml` | `/adsense-optimize` `/adsense-monitor` | **트래픽·클릭 생성, 자동 홍보/백링크 봇, 유료 트래픽**(= 계정 정지) |

**권한 분리 이유**: 생성자가 스스로 검수·발행하면 품질 게이트가 형해화된다(AUTOMATION.md §3). REVIEW는 CONTENT/OPS에 대해 **거부권(veto)** 을 가진다.

---

## 3. 지시 하달 프로토콜 (PM → 워커)

### 3.1 흐름
```
사람 → PM
      ├ 1) 분해: 무엇을·누가·완료 기준(DoD)·게이트 여부
      ├ 2) 작업지시서 작성: team/orders/<ID>.md
      ├ 3) 상태 확인: herdr agent list  (working 이면 대기 — 인터럽트 금지)
      ├ 4) 하달:  herdr agent send <role> "ORDER <ID> ..."
      ├ 5) 대기:  herdr agent wait <role> --status idle --timeout 600000
      ├ 6) 수취:  herdr agent read <role> --lines 60  +  team/reports/<ID>.md
      ├ 7) 검증: DoD 충족? 경계 위반 없나? 미흡하면 재지시(같은 ID, rev 증가)
      ├ 8) 원장: team/ledger.md 상태 갱신
      └ 9) 사람에게 1회 보고 (필요 시 로컬 HTML 리포트 — Artifact 금지)
```

### 3.2 작업지시서 ID 규칙
`YYYY-MM-DD-NN-<role>` (예: `2026-07-24-01-content`) → 파일 `team/orders/2026-07-24-01-content.md`

### 3.3 메시지 전달은 반드시 `scripts/tell.py` (⚠️ 검증됨)
`herdr agent send` 는 상대 pane 입력창에 **텍스트만 넣고 Enter 를 치지 않는다** → 상대는 메시지를 영영 못 본다.
또 Windows PowerShell 5.1 은 네이티브 인자의 큰따옴표를 삼켜 메시지가 깨진다.
→ **전원 이 스크립트만 사용**(send + Enter 제출 + 이름→pane id 자동 해석):

```powershell
python scripts/tell.py <대상> <메시지>          # 대상 = pm | content | review | ops | growth
```

### 3.4 하달 템플릿 (PM → 워커)
```powershell
python scripts/tell.py content "ORDER 2026-07-24-01-content — team/orders/2026-07-24-01-content.md 를 읽고 수행하라. 완료/차단 시 team/reports/<ID>.md 작성 후 python scripts/tell.py pm 으로 한 줄 보고."
```

### 3.5 보고 템플릿 (워커 → PM)
```powershell
python scripts/tell.py pm "DONE <ID> | <한 줄 결과> | 산출물: <경로> | 이슈: <없음|내용>"
python scripts/tell.py pm "BLOCKED <ID> | <막힌 지점> | 필요: <사람 승인|자격증명|다른 에이전트 산출물>"
python scripts/tell.py pm "VETO <ID> | REVIEW 판정 fail | 사유: <정책·품질 근거>"
```
> 보고는 **PM 에게만**. 워커끼리 직접 지시 금지(정보 조회 목적의 `herdr agent read` 는 허용). 사람에게 직접 말하지 않는다.
> ⚠️ 사람이 PM 창에 타이핑하는 중 워커 보고가 들어오면 입력이 섞일 수 있다 → Esc 후 다시 입력하면 된다.

### 3.6 인터럽트 규칙
- 대상이 `working`/`blocked` 이면 원칙적으로 send 금지 → `herdr agent wait <role> --status idle` 후 하달.
  > ⚠️ **안전상 중요**: 대상 pane 에 승인(permission) 프롬프트가 떠 있을 때 `tell.py` 를 쓰면 Enter 가 **그 프롬프트를 승인해 버린다.** 승인은 사람이 해당 pane 에서 직접 한다.
- 예외(즉시 인터럽트 허용): **킬스위치 트리거·정책 경고·무효 트래픽 알림** → OPS 발행 중단이 최우선.

---

## 4. 게이트 (넘을 수 없는 선)

| 게이트 | 규칙 | 집행 |
|---|---|---|
| **G1 발행** | 발행·배포는 ① REVIEW pass + ② PM 승인 후 OPS만 실행 | OPS가 거부 |
| **G2 킬스위치** | `guardrails.yaml killswitch` ON → 발행 즉시 중단. **해제는 사람만**(auto_resume: false) | REVIEW 감시 · OPS 준수 |
| **G3 일일 cap** | `rollout.daily_generate` / `daily_publish_cap` 초과 발행 금지 | OPS 준수 |
| **G4 무효 트래픽** | 트래픽·클릭 생성 관련 코드/스케줄은 **어느 에이전트도 작성·실행 금지** (F3 = 영구 정지) | 전원, 위반 발견 시 즉시 PM 보고 |
| **G5 검수 독립** | CONTENT가 만든 글은 REVIEW가 검수. 자기 검수·자기 승인 금지 | PM이 확인 |
| **G6 근거** | 모든 권고는 `docs/RESEARCH.md` 검증된 발견(✅)에만 근거. 반증된 통념(R1~R14) 재유포 금지 | REVIEW가 감사 |

---

## 5. 에스컬레이션 (PM도 못 하는 것 → 사람 결정, AUTOMATION.md §7)

1. AdSense **승인 신청·이의제기** (API 없음)
2. 정책 위반·무효 트래픽 **원인 해소 및 소명**
3. 품질 게이트 **캘리브레이션 샘플 승인**(`--approve <slug>`)
4. 프리미엄 네트워크 **전환 결정**(25k PV/월, F9)
5. **킬스위치 해제**
6. 도메인·서버·과금·계정 변경

PM은 위 항목을 발견하면 워커에게 지시하지 않고 **사람에게 선택지와 권고안**을 제시한다.

---

## 6. 산출물 규약

- 작업지시서: `team/orders/<ID>.md` (PM 작성)
- 완료보고서: `team/reports/<ID>.md` (워커 작성)
- 원장: `team/ledger.md` (PM만 갱신, append-only 성격)
- 사람 대상 보고서: **로컬 HTML**(`보고서-*.html`, `reports/*.html`). **Artifact 금지**(프로젝트 정책).
- 문서 갱신: 새 사실을 검증·반증하면 `docs/RESEARCH.md` 에 출처와 함께 반영(REVIEW 승인 후).

---

## 7. herdr 치트시트 (PM 상시 사용)

```powershell
herdr agent list                                     # 전원 상태(idle/working/blocked)
python scripts/tell.py <role> "<지시>"                # 하달·보고 (send+Enter, §3.3)
herdr agent wait  <role> --status idle --timeout 600000
herdr agent read  <role> --lines 60                  # 화면 읽어 진행 파악
herdr agent focus <role>                             # 사람이 직접 볼 때만
herdr pane list                                      # pane id·cwd·label 확인
```

## 8. 팀 부팅 / 복구

```powershell
python scripts/team_up.py            # 현재 팀 상태 출력 (기본)
python scripts/team_up.py --boot     # 없는 워커 복구 — 라벨 pane 이 있으면 입양, 없으면 새로 생성 + 킥오프
python scripts/team_up.py --boot --yolo   # 워커를 --dangerously-skip-permissions 로 기동
```
- PM pane 은 **사람이 쓰고 있는 pane** 이다. 새로 만들지 않고 `herdr agent rename <pane> pm` 으로 지정한다.
- 워커 pane 을 닫았다가 다시 만들면 pane id 는 바뀌지만 **이름은 유지**되므로 지시는 그대로 동작한다.

### 8.1 장애 유형 — "herdr 소켓 API 사망" (2026-07-24 실제 발생)

**증상**: `herdr agent list` 가 `Error: Os { code: 2, kind: NotFound }`, `herdr status` 는 `server: not running`.
그런데 **화면의 pane 은 멀쩡하고 herdr 서버 프로세스도 살아 있다**(`herdr.exe server` 가 로그를 계속 쓴다).
→ 서버 본체는 살아 있고 **소켓 API 리스너만** 죽은 상태. 이때 PM 은 워커에게 지시를 **보낼 수단이 없다**(tell.py 도 API 를 쓴다).

**확인**(사람/PM 공통):
```powershell
herdr status                                     # server: not running 이면 API 소켓 사망
Get-CimInstance Win32_Process -Filter "Name='herdr.exe'"   # `herdr.exe server` 가 살아 있는지
Test-Path "\\.\pipe\$env:APPDATA\herdr\herdr.sock"          # False = API 파이프 없음(확진)
```

**복구**: **herdr 재시작 외에 방법이 없다.** ⚠️ 재시작하면 모든 workspace 의 pane 이 닫힌다 —
**다른 프로젝트 팀(btc·realestate)도 함께 죽는다.** 사람이 결정할 일이지 PM 이 임의로 하지 않는다.
재시작 후 → PM pane 에서 `claude --resume` → `python scripts/team_up.py --boot`.

**왜 --boot 를 고쳤나**: 이 장애에서 session.json 의 워커 `agent_name` 이 날아가 이름 조회가 실패하는데,
pane 라벨(`CONTENT`/`REVIEW`/`OPS`/`GROWTH`)은 남는다. 예전 --boot 는 이름만 보고 **살아 있는 pane 위에
새 pane 을 또 만들었다**(9분할). 지금은 라벨로 기존 pane 을 찾아 **입양**한다. 라벨 지도는 API 가 죽어도 읽히는
`%APPDATA%\herdr\session.json` 에서 직접 읽는다 → `python scripts/team_up.py` 는 **API 사망 중에도** 상태를 보여준다.

## 9. 승인(permission) 설정

`.claude/settings.json` 이 **메시징·조회 명령만** 무프롬프트 허용한다(팀 루프가 매번 승인창에서 멈추지 않도록):
`python scripts/tell.py *`, `python scripts/team_up.py *`, `herdr agent list|get|read|wait *`, `herdr pane list|get|layout *`.

- ⚠️ **명령을 그대로(bare) 실행**해야 매칭된다. `cd ... ; python scripts/tell.py ...` 처럼 묶으면 프롬프트가 뜬다.
- 파이프라인 실행·배포·서버 접속·파일 수정은 **일부러 허용하지 않았다** — 실제 작업은 승인을 거친다(게이트 유지).
- 새 워커 pane 은 부팅 시 이 설정을 읽는다. 그래도 프롬프트가 뜨면 사람이 1회 승인하면 된다.
