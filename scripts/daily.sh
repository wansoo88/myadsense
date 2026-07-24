#!/usr/bin/env bash
# daily.sh — pjt12-adsense 서버 cron 일일 잡 (AUTOMATION.md §5).
#   0) selftest : 검수 게이트 회귀 테스트(LLM 미호출·네트워크 없음, 수 초)
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
# cron 은 LANG 없이 도는 일이 많다 → 파이썬 stdout 인코딩이 ascii/cp 계열이 되면 한글 로그 한 줄에
# UnicodeEncodeError 로 단계 전체가 rc=1 로 죽는다(로컬 20:00 배치에서 실측된 동일 사고: daily_local.ps1:9).
# 셀프테스트도 한글을 찍으므로 이 한 줄이 없으면 '테스트 실패'가 아니라 '인코딩 실패'로 오경보가 난다.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

ts() { date '+%F %T'; }

echo "[$(ts)] === daily 시작 ==="

# 0) 검수 게이트 회귀 테스트 (engine/content/reviewer_selftest.py — LLM 미호출·네트워크 없음·파일 쓰기 없음).
#    지키는 것: 광고·제휴 '고지' 오탐 강등이 reviewer 의 passed(=발행 큐 게이트)를 절대 뒤집지 않는다는 성질.
#    이게 조용히 깨지면 검수 통과 기준이 느슨해진 채로 매일 글이 큐에 들어간다 → 매 실행 확인한다.
#    기본은 **advisory(발행 차단 아님)**: 이미 큐에 있는 글은 검수를 통과한 것들이라 배포를 멈출 이유가 없다.
#    대신 실패를 시끄럽게 만든다 — 배너 + 마지막 exit 1 전파(cron MAILTO/모니터가 잡도록).
#    ⚠️ 격상 옵션: SELFTEST_BLOCK_GENERATE=1 이면 **generate 만** 스킵(신규 초안 유입 차단, 배포는 계속).
#       기본값 0 인 이유 = 게이트 강화는 PM 승인 사항(team/orders/2026-07-25-17-ops.md ②).
echo "[$(ts)] selftest (검수 게이트 회귀 테스트) 시작"
"$PY" engine/content/reviewer_selftest.py
st_rc=$?
echo "[$(ts)] selftest 종료(rc=$st_rc)"
if [ "$st_rc" -ne 0 ]; then
  echo "################################################################"
  echo "[$(ts)] !! REVIEWER SELFTEST 실패 (rc=$st_rc) — 검수 게이트 회귀 의심"
  echo "   재현: cd $ROOT && $PY engine/content/reviewer_selftest.py"
  echo "   영향: 고지 오탐 강등이 REVIEW 판정을 뒤집을 수 있다 → 저품질/정책 리스크 글이 큐에 들어갈 수 있음"
  echo "################################################################"
fi

# ingest: GSC(검색성과·색인상태)·PageSpeed → DB. 읽기전용(F3). 비치명적 — 실패해도 생성/배포는 계속.
echo "[$(ts)] ingest (GSC·PageSpeed → DB) 시작"
"$PY" engine/orchestrator.py --stage ingest || echo "[$(ts)] ingest 경고(비치명적, 계속 진행)"
if [ "$st_rc" -ne 0 ] && [ "${SELFTEST_BLOCK_GENERATE:-0}" = "1" ]; then
  echo "[$(ts)] selftest 실패 + SELFTEST_BLOCK_GENERATE=1 → generate 스킵(신규 초안 유입 차단)"
  gen_rc=0
else
  echo "[$(ts)] generate (품질 게이트+검수) 시작"
  "$PY" engine/orchestrator.py --stage generate
  gen_rc=$?        # rc 는 바로 다음 줄에서 캡처 — echo 안 $(ts) 가 $? 를 덮어쓰기 전에.
  echo "[$(ts)] generate 종료(rc=$gen_rc)"
fi

# 킬스위치 안전벨트: halt 상태면 배포하지 않는다(사람이 clear 후 재개).
if [ -f engine/store/killswitch_state.json ] && grep -q '"halted"[[:space:]]*:[[:space:]]*true' engine/store/killswitch_state.json; then
  echo "[$(ts)] KILLSWITCH halt 상태 — 배포 스킵"
  # 여기서도 selftest·generate 실패는 삼키지 않는다(예전엔 무조건 exit 0 → 실패가 묻혔다).
  if [ "$st_rc" -ne 0 ] || [ "$gen_rc" -ne 0 ]; then
    echo "[$(ts)] 실패 감지(배포 전 종료) — selftest rc=$st_rc, generate rc=$gen_rc"
    exit 1
  fi
  exit 0
fi

echo "[$(ts)] deploy (build → web_root 로컬 복사) 시작"
ADSENSE_DEPLOY=1 ADSENSE_LOCAL_DEPLOY=1 "$PY" engine/orchestrator.py --stage deploy
dep_rc=$?
echo "[$(ts)] deploy 종료(rc=$dep_rc)"

# syndicate: 라이브 글 1편을 dev.to 에 canonical 교차게시(earned backlink·유입). 비치명적.
# .env DEVTO_API_KEY 없거나 config enabled=false 면 스스로 스킵. ⚠️ 커뮤니티 자동게시 아님(dev.to 한정).
echo "[$(ts)] syndicate (dev.to canonical 교차게시) 시작"
ADSENSE_SYNDICATE=1 "$PY" engine/orchestrator.py --stage syndicate || echo "[$(ts)] syndicate 경고(비치명적, 계속)"

echo "[$(ts)] === daily 종료 ==="

# 실패를 cron 에 전파(MAILTO·모니터가 감지하도록) — 마지막이 echo 면 항상 exit 0 이 되어 실패가 묻힌다.
# selftest 실패도 여기 포함한다: 배포는 막지 않되(advisory) **조용히 지나가지도 않는다**.
if [ "$st_rc" -ne 0 ] || [ "$gen_rc" -ne 0 ] || [ "$dep_rc" -ne 0 ]; then
  echo "[$(ts)] 실패 감지 — selftest rc=$st_rc, generate rc=$gen_rc, deploy rc=$dep_rc"
  exit 1
fi
