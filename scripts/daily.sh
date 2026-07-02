#!/usr/bin/env bash
# daily.sh — pjt12-adsense 서버 cron 일일 잡 (AUTOMATION.md §5).
#   1) generate : 초안 생성 → 품질 게이트 → 검수(reviewer 내장) → dist/queue (통과분만, daily_generate=1)
#   2) deploy   : dist/queue → build → web_root 로 로컬 배포 (킬스위치 halt 시 스킵)
# 검수는 generate 단계에 내장되어 있으므로 "생성·검수·발행"이 이 한 스크립트로 처리된다.
# 생성 provider = claude CLI(구독 헤드리스). claude 미로그인 시 generate 는 0편 → deploy 는 기존 큐 재배포(무해).
set -uo pipefail

ROOT="/root/pjt12-adsense"
PY="$ROOT/.venv/bin/python"
cd "$ROOT" || { echo "[daily] $ROOT 없음"; exit 1; }

# .env 로드(있으면) — 시크릿/토큰. claude CLI PATH 보장.
[ -f .env ] && { set -a; . ./.env; set +a; }
export PATH="/usr/local/bin:/usr/bin:$PATH"

ts() { date '+%F %T'; }

echo "[$(ts)] === daily 시작 ==="
echo "[$(ts)] generate (품질 게이트+검수) 시작"
"$PY" engine/orchestrator.py --stage generate
gen_rc=$?          # rc 는 바로 다음 줄에서 캡처 — echo 안 $(ts) 가 $? 를 덮어쓰기 전에.
echo "[$(ts)] generate 종료(rc=$gen_rc)"

# 킬스위치 안전벨트: halt 상태면 배포하지 않는다(사람이 clear 후 재개).
if [ -f engine/store/killswitch_state.json ] && grep -q '"halted"[[:space:]]*:[[:space:]]*true' engine/store/killswitch_state.json; then
  echo "[$(ts)] KILLSWITCH halt 상태 — 배포 스킵"
  exit 0
fi

echo "[$(ts)] deploy (build → web_root 로컬 복사) 시작"
ADSENSE_DEPLOY=1 ADSENSE_LOCAL_DEPLOY=1 "$PY" engine/orchestrator.py --stage deploy
dep_rc=$?
echo "[$(ts)] deploy 종료(rc=$dep_rc)"
echo "[$(ts)] === daily 종료 ==="

# 실패를 cron 에 전파(MAILTO·모니터가 감지하도록) — 마지막이 echo 면 항상 exit 0 이 되어 실패가 묻힌다.
if [ "$gen_rc" -ne 0 ] || [ "$dep_rc" -ne 0 ]; then
  echo "[$(ts)] 실패 감지 — generate rc=$gen_rc, deploy rc=$dep_rc"
  exit 1
fi
