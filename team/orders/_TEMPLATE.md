---
id: YYYY-MM-DD-NN-<role>          # 예: 2026-07-24-01-content
to: content | review | ops | growth
rev: 1                            # 재지시 시 +1
gate: none | review-required | human-approval
status: dispatched
---

## 목적 (왜 하는가)
<한 문장. 어떤 KPI/게이트를 움직이는지>

## 근거
<docs/RESEARCH.md F# / 사람 요청 / 이전 보고 team/reports/<ID>.md>

## 작업
- [ ] <구체 작업 1 — 실행 명령 포함>
- [ ] <구체 작업 2>

## 산출물 (정확한 경로)
- `<path>`

## 완료 기준 (DoD — 검증 가능하게)
- <이 문장이 참이면 완료>

## 경계 (하지 말 것)
- 소유 영역 밖 파일 수정 금지(CHARTER §2)
- <이 작업 특유의 금지사항>

## 보고
```powershell
python scripts/tell.py pm "DONE <id> | 결과 | 산출물 | 이슈"
```
