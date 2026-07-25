#!/usr/bin/env bash
# analytics.sh — 서버 cron 잡: nginx 접속 로그 → 관리자 방문 분석 대시보드 갱신.
#   python engine/orchestrator.py --stage analytics
#   → config/analytics.yaml 대로 로그 파싱·집계 → /var/www/stack-analytics/{index.html,data.json}
# 나(쿠키 noana·지정 IP)·봇 제외. 읽기 전용(트래픽/클릭 생성과 무관).
set -uo pipefail
ROOT="/root/pjt12-adsense"
PY="$ROOT/.venv/bin/python"
cd "$ROOT" || { echo "[analytics] $ROOT 없음"; exit 1; }
[ -f .env ] && { set -a; . ./.env; set +a; }
"$PY" engine/orchestrator.py --stage analytics
