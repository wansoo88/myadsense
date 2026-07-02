# daily_local.ps1 — 로컬(Windows) 일일 잡: generate(품질게이트+검수) → killswitch 확인 → 원격 배포(scp).
# 서버 claude 로그인 전까지 임시로 로컬에서 하루 1편 운영 (로컬은 claude 인증돼 있음).
# 서버 daily.sh 와 차이: 배포가 로컬-복사가 아니라 원격 scp(ADSENSE_DEPLOY=1, LOCAL 미설정)이며 경로가 로컬(D:\...).
# 등록: scripts\register_local_task.ps1 (작업 스케줄러, 매일 20:00, 로그온 시).

$ErrorActionPreference = 'Continue'
$proj = 'D:\cashflow\pjt12-adsense'
Set-Location $proj

$logDir = Join-Path $proj 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir 'daily_local.log'
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Log '=== daily_local 시작 ==='
Log 'generate 시작 (품질게이트+검수 내장)'
& python engine\orchestrator.py --stage generate 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$gen = $LASTEXITCODE
Log "generate 종료 rc=$gen"

# 킬스위치 안전벨트: halt 상태면 배포 스킵(사람이 clear 후 재개).
$ks = Join-Path $proj 'engine\store\killswitch_state.json'
if ((Test-Path $ks) -and (Select-String -Path $ks -Pattern '"halted"\s*:\s*true' -Quiet)) {
  Log 'KILLSWITCH halt 상태 — 배포 스킵'
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

if ($gen -ne 0 -or $dep -ne 0) { exit 1 } else { exit 0 }
