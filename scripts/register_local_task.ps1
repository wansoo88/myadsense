# register_local_task.ps1 — Windows 작업 스케줄러에 daily_local.ps1 등록.
# 서버 claude 로그인 전까지 로컬(Windows)에서 하루 1편 생성·배포를 대신 운영하기 위한 임시 장치.
# 트리거: 매일 20:00 (DAILY). ⚠️ 로그온 트리거(ONLOGON)는 이 계정 권한으로 schtasks 생성 시
# Access denied(관리자 권한 필요) — 시도했으나 등록 불가 확인. 그래서 PC가 20:00에 꺼져 있으면
# 그날은 스킵된다(다음날 20:00에 재시도). 필요하면 관리자 PowerShell에서 별도 등록할 것.
# schtasks.exe 사용(Register-ScheduledTask cmdlet은 이 환경에서 Access denied — CIM/WMI 경로 제한, schtasks는 DAILY 기준 정상 동작 확인됨).
# 재실행해도 안전(/F 로 기존 작업 덮어씀 — 멱등). 관리자 권한 불필요(현재 사용자 컨텍스트로 등록).

$ErrorActionPreference = 'Stop'
$taskNameDaily = 'pjt12-adsense-daily'
$scriptPath = Join-Path $PSScriptRoot 'daily_local.ps1'

if (-not (Test-Path $scriptPath)) { throw "스크립트 없음: $scriptPath" }

$taskRun = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

schtasks /Create /TN $taskNameDaily /TR $taskRun /SC DAILY /ST 20:00 /F | Out-Null

Write-Host "등록 완료: $taskNameDaily (매일 20:00)"
Write-Host "확인: schtasks /Query /TN $taskNameDaily /V /FO LIST"
Write-Host "즉시 테스트 실행: schtasks /Run /TN $taskNameDaily"
Write-Host "해제: schtasks /Delete /TN $taskNameDaily /F"
