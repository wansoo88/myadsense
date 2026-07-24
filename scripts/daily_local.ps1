# daily_local.ps1 — 로컬(Windows) 일일 잡: generate(품질게이트+검수) → killswitch 확인 → 원격 배포(scp).
# 서버 claude 로그인 전까지 임시로 로컬에서 하루 1편 운영 (로컬은 claude 인증돼 있음).
# 서버 daily.sh 와 차이: 배포가 로컬-복사가 아니라 원격 scp(ADSENSE_DEPLOY=1, LOCAL 미설정)이며 경로가 로컬(D:\...).
# 등록: scripts\register_local_task.ps1 (작업 스케줄러, 매일 20:00 — 로그온 트리거는 이 계정 권한으로 등록 불가 확인됨).

$ErrorActionPreference = 'Continue'
$proj = 'D:\cashflow\pjt12-adsense'
Set-Location $proj
$env:PYTHONIOENCODING = 'utf-8'   # Windows cp949 콘솔에서 '—' 등 출력 시 generate 크래시 방지(2026-07-09)
$env:PYTHONUTF8 = '1'

# 파이썬(UTF-8) 출력을 PowerShell 5.1 이 콘솔 OEM 코드페이지(cp949)로 디코드해 로그가 통째로 깨져 있었다
# → 2026-07-16~24 실패 로그를 사람이 읽을 수 없었다. 이 프로세스 한정으로 UTF-8 디코딩 강제.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$logDir = Join-Path $proj 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir 'daily_local.log'
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Log '=== daily_local 시작 ==='

# 0-a) claude 인증 프리플라이트 (ORDER 2026-07-25-20 ①).
#   2026-07-16 이후 20:00 배치 0편의 실제 원인은 환경(PATH·콘솔·CWD)이 아니라 **OAuth 만료**였다.
#   CLI 세션 기록(~/.claude/projects/**.jsonl)에 07-20·07-22·07-23·07-24 전부
#   error=authentication_failed / "Failed to authenticate: OAuth session expired and could not be
#   refreshed" 로 남아 있다(07-16 만 예외 — "Unable to connect to API (ENOTFOUND)" = 그날 DNS 장애).
#   헤드리스(-p)는 /login 을 띄울 수 없어 스스로 복구하지 못한다 → 사람이 대화형으로 한 번 로그인해야 한다.
#   ⚠️ 토큰 값은 절대 로그에 쓰지 않는다 — 만료 시각만 읽는다. 발행 게이트와 무관(차단하지 않는 advisory).
$credPath = Join-Path $env:USERPROFILE '.claude\.credentials.json'
try {
  $oauth = (Get-Content $credPath -Raw -Encoding UTF8 | ConvertFrom-Json).claudeAiOauth
  $exp  = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$oauth.expiresAt).LocalDateTime
  $rexp = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$oauth.refreshTokenExpiresAt).LocalDateTime
  $left = [int]($exp - (Get-Date)).TotalMinutes
  Log ("auth preflight: access_token 만료 {0} (남은 {1}분) / refresh_token 만료 {2}" -f `
       $exp.ToString('yyyy-MM-dd HH:mm:ss'), $left, $rexp.ToString('yyyy-MM-dd HH:mm:ss'))
  if ($left -le 0) {
    Log '################################################################'
    Log '!! access_token 이 이미 만료됨 - 헤드리스 갱신이 실패해 온 이력이 있다(07-20~07-24)'
    Log '   증상: claude CLI 실패(rc=1) x 시드수 -> 신규 0편'
    Log '   조치: 이 PC 에서 claude 를 한 번 실행해 로그인 갱신 후 재실행'
    Log '################################################################'
  }
} catch {
  Log "auth preflight 확인 실패(무시하고 진행): $($_.Exception.Message)"
}

# 0) 검수 게이트 회귀 테스트 (engine/content/reviewer_selftest.py — LLM 미호출·네트워크 없음, 수 초).
#    지키는 성질: 광고·제휴 '고지' 오탐 강등이 reviewer 의 passed(=발행 큐 게이트)를 뒤집지 않는다.
#    기본 advisory(발행 차단 아님) + 시끄러운 실패(배너 + exit 1 전파). 서버 daily.sh 와 동일 규약.
#    ⚠️ 격상 옵션: 환경변수 SELFTEST_BLOCK_GENERATE=1 → generate 만 스킵(배포는 계속). 기본 0(PM 승인 사항).
Log 'selftest 시작 (검수 게이트 회귀 테스트 — LLM 미호출)'
& python engine\content\reviewer_selftest.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$st = $LASTEXITCODE
Log "selftest 종료 rc=$st"
if ($st -ne 0) {
  Log '################################################################'
  Log "!! REVIEWER SELFTEST 실패 (rc=$st) - 검수 게이트 회귀 의심"
  Log '   재현: python engine\content\reviewer_selftest.py'
  Log '   영향: 고지 오탐 강등이 REVIEW 판정을 뒤집을 수 있다 → 리스크 글이 큐에 들어갈 수 있음'
  Log '################################################################'
}

if (($st -ne 0) -and ($env:SELFTEST_BLOCK_GENERATE -eq '1')) {
  Log 'selftest 실패 + SELFTEST_BLOCK_GENERATE=1 → generate 스킵(신규 초안 유입 차단, 배포는 계속)'
  $gen = 0
} else {
  Log 'generate 시작 (품질게이트+검수 내장)'
  $genOut = Join-Path $logDir 'last_generate.out'          # 이번 실행분만 따로 — 사후 판정·grep 용
  & python engine\orchestrator.py --stage generate 2>&1 |
    Tee-Object -FilePath $genOut | Out-File -FilePath $log -Append -Encoding utf8
  $gen = $LASTEXITCODE
  Log "generate 종료 rc=$gen"

  # generate 는 CLI 가 전부 실패해도 rc=0 으로 끝난다(시드별 SKIP) → 0편이 조용히 지나갔다.
  # 이제 실패 사유 원문을 배너로 끌어올린다. 'claude CLI' 는 ASCII 라 로그 인코딩과 무관하게 잡힌다.
  $cliFail = @(Select-String -Path $genOut -Pattern 'claude CLI' -ErrorAction SilentlyContinue)
  if ($cliFail.Count -gt 0) {
    Log '################################################################'
    Log "!! claude CLI 호출 실패 $($cliFail.Count)건 - 오늘 신규 0편일 수 있음"
    Log ("   사유(첫 줄): " + $cliFail[0].Line.Trim())
    Log '   authentication_failed/OAuth 계열이면: 이 PC 에서 claude 를 한 번 실행해 로그인 갱신'
    Log '   (07-16 처럼 ENOTFOUND 면 네트워크·DNS 장애 - 다음 실행에서 자연 회복)'
    Log '################################################################'
  }
}

# 킬스위치 안전벨트: halt 상태면 배포 스킵(사람이 clear 후 재개).
$ks = Join-Path $proj 'engine\store\killswitch_state.json'
if ((Test-Path $ks) -and (Select-String -Path $ks -Pattern '"halted"\s*:\s*true' -Quiet)) {
  Log 'KILLSWITCH halt 상태 — 배포 스킵'
  if (($st -ne 0) -or ($gen -ne 0)) {      # 실패를 삼키지 않는다(예전엔 무조건 exit 0)
    Log "실패 감지(배포 전 종료) — selftest rc=$st, generate rc=$gen"
    exit 1
  }
  exit 0
}

Log 'deploy 시작 (build → 원격 scp → 서버 web_root)'
$env:ADSENSE_DEPLOY = '1'                       # 원격 배포(로컬복사 아님 → ADSENSE_LOCAL_DEPLOY 미설정)
& python engine\orchestrator.py --stage deploy 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$dep = $LASTEXITCODE
Remove-Item Env:\ADSENSE_DEPLOY -ErrorAction SilentlyContinue
Log "deploy 종료 rc=$dep"

# dist/queue·published.json 을 서버에도 동기화 — 안 하면 다음날 09:00 서버 cron이
# 서버 자신의 (구버전) dist/queue 로 재빌드해 오늘 로컬이 배포한 신규 글을 되돌린다.
# (dist/ 는 gitignore 대상이라 git으로는 안 퍼짐 — 서버는 git repo도 아님, scp 수동 동기화. memory: server-cron-rebuilds-from-source)
if ($dep -eq 0) {
  Log 'dist/queue·published.json → 서버 동기화 (익일 서버 cron 되돌림 방지)'
  & scp -i ~/.ssh/autobtc_iwinv -o StrictHostKeyChecking=accept-new dist\queue\*.html root@115.68.230.40:/root/pjt12-adsense/dist/queue/ 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  & scp -i ~/.ssh/autobtc_iwinv -o StrictHostKeyChecking=accept-new engine\store\published.json root@115.68.230.40:/root/pjt12-adsense/engine/store/published.json 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  Log "동기화 종료 rc=$LASTEXITCODE"
}
Log '=== daily_local 종료 ==='

# selftest 실패도 종료코드로 전파 — 배포는 막지 않되(advisory) 조용히 지나가지도 않는다.
if ($st -ne 0 -or $gen -ne 0 -or $dep -ne 0) {
  Log "실패 감지 — selftest rc=$st, generate rc=$gen, deploy rc=$dep"
  exit 1
} else { exit 0 }
