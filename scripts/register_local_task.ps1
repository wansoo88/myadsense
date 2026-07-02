# register_local_task.ps1 — Windows 작업 스케줄러에 daily_local.ps1 등록.
# 서버 claude 로그인 전까지 로컬(Windows)에서 하루 1편 생성·배포를 대신 운영하기 위한 임시 장치.
# 트리거: 매일 20:00 + 로그온 시(PC가 20:00에 꺼져 있어도 다음 로그온 때 대신 실행, MultipleInstances로 중복 실행 방지).
# 재실행해도 안전(기존 작업 지우고 재등록 — 멱등). 관리자 권한 불필요(현재 사용자 컨텍스트로 등록).

$ErrorActionPreference = 'Stop'
$taskName = 'pjt12-adsense-daily'
$scriptPath = Join-Path $PSScriptRoot 'daily_local.ps1'

if (-not (Test-Path $scriptPath)) { throw "스크립트 없음: $scriptPath" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

$triggers = @(
  New-ScheduledTaskTrigger -Daily -At 20:00
  New-ScheduledTaskTrigger -AtLogOn
)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew -DontStopOnIdleEnd

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
  -Description 'pjt12-adsense 일일 생성+검수+배포 (서버 claude 로그인 전 임시 로컬 운영). 해제: Unregister-ScheduledTask -TaskName pjt12-adsense-daily' `
  | Out-Null

Write-Host "등록 완료: $taskName (매일 20:00 + 로그온 시)"
Write-Host "확인: Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo"
Write-Host "즉시 테스트 실행: Start-ScheduledTask -TaskName $taskName"
Write-Host "해제: Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
