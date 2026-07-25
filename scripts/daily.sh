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
SELF="$ROOT/scripts/daily.sh"
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

# -1) 코드 자기 갱신 (git pull) — 서버가 스스로 최신 코드를 받는다.
#   왜: 예전엔 사람이 scp 로 밀어야 서버에 반영됐고, 그 수동 단계가 2026-07-25 실제 사고를 냈다
#       (Windows 체크아웃 CRLF 가 섞여 셰방이 `#!/usr/bin/env bash\r` 로 깨짐 → 09:00 cron 통째 미실행).
#       repo(.gitattributes) 가 LF 를 강제하고, 배포 경로가 git 이 되면 그 사고 경로 자체가 사라진다.
#   repo 는 public 이라 자격증명이 필요 없다. 다만 cron 에는 TTY 가 없어 git 이 자격증명을 물으면
#   영원히 멈춘다 → GIT_TERMINAL_PROMPT=0 + timeout 으로 이중 차단한다.
#   ⚠️ 비치명적: pull 이 실패해도 파이프라인은 계속한다(어제 코드로라도 오늘 글은 나와야 한다).
#      대신 배너 + 드리프트 목록으로 시끄럽게 남기고 마지막에 exit 1 로 전파한다
#      (selftest 와 같은 advisory 패턴 — 막지는 않되 조용히 지나가지도 않는다).
pull_rc=0
if [ -d "$ROOT/.git" ]; then
  echo "[$(ts)] git pull (코드 자기 갱신) 시작"
  self_md5_before=$(md5sum "$SELF" 2>/dev/null | awk '{print $1}')
  head_before=$(git rev-parse --short HEAD 2>/dev/null)
  pull_out=$(GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND='ssh -o BatchMode=yes' timeout 120 git pull --ff-only 2>&1)
  pull_rc=$?
  printf '%s\n' "$pull_out" | sed 's/^/[git] /'
  if [ "$pull_rc" -ne 0 ]; then
    echo "################################################################"
    echo "[$(ts)] !! GIT PULL 실패 (rc=$pull_rc) — 서버가 낡은 코드로 오늘을 실행한다"
    echo "   원인 후보: 1) 작업트리에 로컬 수정이 남아 pull 거부(scp 흔적) 2) 네트워크/GitHub 장애"
    echo "              3) 브랜치 분기로 fast-forward 불가  4) timeout(120s) 초과"
    echo "   현재 드리프트(추적 파일):"
    git status --short --untracked-files=no | sed 's/^/     /'
    echo "   재현: cd $ROOT && git pull --ff-only"
    echo "   영향: 코드만 낡음 — 생성·검수·배포 자체는 아래에서 계속 진행한다."
    echo "################################################################"
  else
    head_after=$(git rev-parse --short HEAD 2>/dev/null)
    if [ "$head_before" = "$head_after" ]; then
      echo "[$(ts)] git pull ok — 변경 없음 (HEAD=$head_after)"
    else
      echo "[$(ts)] git pull ok — $head_before → $head_after 갱신"
      git --no-pager log --oneline "$head_before..$head_after" 2>/dev/null | sed 's/^/     /'
    fi
    # repo 가 *.sh 를 100644(비실행)로 저장한다(Windows 에서 커밋되어 실행비트가 없음).
    # 그래서 내용이 바뀐 pull 은 실행비트를 벗긴다(서버 실측 확인: 755 → 644).
    # cron 은 daily.sh 를 직접 실행하므로 벗겨지면 다음날 "Permission denied" 로 전체가 죽는다 → 매번 되살린다(멱등).
    chmod +x "$ROOT"/scripts/*.sh 2>/dev/null || true
    # ⚠️ 실행 중 자기 자신 교체 주의: pull 이 daily.sh 를 갈아치우면 bash 가 파일 오프셋 기준으로
    #    남은 줄을 읽다가 엉뚱한 코드를 실행할 수 있다(서버 실측: git 은 같은 inode 에 덮어쓰는 경우도 있다).
    #    daily.sh 자체가 바뀐 경우에만 새 버전으로 1회 재실행한다(환경변수로 무한루프 차단).
    if [ "$self_md5_before" != "$(md5sum "$SELF" 2>/dev/null | awk '{print $1}')" ]; then
      if [ "${ADSENSE_DAILY_REEXEC:-0}" = "1" ]; then
        echo "[$(ts)] daily.sh 가 또 바뀌었으나 재실행은 1회만 — 그대로 계속"
      else
        echo "[$(ts)] daily.sh 자체가 갱신됨 → 새 버전으로 재실행(exec)"
        export ADSENSE_DAILY_REEXEC=1
        exec bash "$SELF" "$@"
      fi
    fi
  fi
else
  echo "[$(ts)] !! 경고: $ROOT 가 git 작업트리가 아님(.git 없음) — 코드 자기 갱신 불가(수동 scp 의존)"
fi

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
  if [ "$st_rc" -ne 0 ] || [ "$gen_rc" -ne 0 ] || [ "$pull_rc" -ne 0 ]; then
    echo "[$(ts)] 실패 감지(배포 전 종료) — pull rc=$pull_rc, selftest rc=$st_rc, generate rc=$gen_rc"
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
# selftest·git pull 실패도 여기 포함한다: 파이프라인은 막지 않되(advisory) **조용히 지나가지도 않는다**.
# (pull 실패 = "오늘은 낡은 코드로 돌았다" 는 뜻이라 알림 가치가 있다.)
if [ "$pull_rc" -ne 0 ] || [ "$st_rc" -ne 0 ] || [ "$gen_rc" -ne 0 ] || [ "$dep_rc" -ne 0 ]; then
  echo "[$(ts)] 실패 감지 — pull rc=$pull_rc, selftest rc=$st_rc, generate rc=$gen_rc, deploy rc=$dep_rc"
  exit 1
fi
