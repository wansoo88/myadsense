#!/usr/bin/env bash
# setup_analytics_server.sh — 방문 분석 대시보드 1회 서버 셋업(멱등).
#   1) nginx JSON log_format(conf.d) + stack vhost 에 전용 access_log + /_analytics/ (Basic Auth) location
#   2) htpasswd 생성(없을 때만 — 재실행해도 비밀번호 안 바뀜), 출력 디렉토리 생성
#   3) nginx -t && reload
#   4) 15분마다 analytics.sh 실행하는 cron 등록
# 실행: bash /root/pjt12-adsense/scripts/setup_analytics_server.sh
set -euo pipefail

VHOST=/etc/nginx/sites-available/stack.utilverse.info
LOGFMT=/etc/nginx/conf.d/stack_analytics_log.conf
HTPASS=/etc/nginx/.stack_analytics.htpasswd
OUTDIR=/var/www/stack-analytics
ANALYTICS_SH=/root/pjt12-adsense/scripts/analytics.sh

# --- 1) JSON log_format (http 컨텍스트: conf.d 는 nginx.conf http{} 에서 include) ---
cat > "$LOGFMT" <<'EOF'
# stack.utilverse.info 전용 방문 분석 로그 포맷(JSON). engine/analytics/parser.py 가 소비.
log_format stack_json escape=json '{'
  '"t":"$time_iso8601",'
  '"ip":"$remote_addr",'
  '"m":"$request_method",'
  '"u":"$request_uri",'
  '"s":$status,'
  '"b":$body_bytes_sent,'
  '"r":"$http_referer",'
  '"ua":"$http_user_agent",'
  '"h":"$host",'
  '"cc":"$cookie_noana"'
'}';
EOF

# --- 2) stack vhost 재작성(전용 access_log + /_analytics/ Basic Auth location) ---
cat > "$VHOST" <<'EOF'
# stack.utilverse.info — 정적 사이트(AdSense 콘텐츠). nginx(이 서버 80/443) + certbot.
server {
    server_name stack.utilverse.info;
    root /var/www/stack.utilverse.info;
    index index.html;

    # 방문 분석: stack 전용 JSON 접속 로그(회전은 기존 logrotate /var/log/nginx/*.log 가 처리)
    access_log /var/log/nginx/stack.access.log stack_json;

    location / {
        try_files $uri $uri/ $uri/index.html =404;
    }

    # 관리자 방문 분석 대시보드 — web_root 밖(콘텐츠 재배포에도 안 지워짐) + Basic Auth + 비색인
    location /_analytics/ {
        alias /var/www/stack-analytics/;
        index index.html;
        auth_basic "stack analytics";
        auth_basic_user_file /etc/nginx/.stack_analytics.htpasswd;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }

    gzip on;
    gzip_comp_level 5;
    gzip_types text/html text/css application/javascript application/xml image/svg+xml application/json;

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/stack.utilverse.info/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/stack.utilverse.info/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = stack.utilverse.info) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    server_name stack.utilverse.info;
    listen 80;
    return 404; # managed by Certbot
}
EOF

# --- 3) 출력 디렉토리 ---
mkdir -p "$OUTDIR"
chmod 755 "$OUTDIR"

# --- 4) htpasswd (없을 때만 생성, 재실행 시 비번 유지) ---
if [ ! -f "$HTPASS" ]; then
  PW="$(openssl rand -base64 9)"
  printf 'admin:%s\n' "$(openssl passwd -apr1 "$PW")" > "$HTPASS"
  chown root:www-data "$HTPASS"; chmod 640 "$HTPASS"
  echo "=== 새 관리자 계정 생성됨 ==="
  echo "URL : https://stack.utilverse.info/_analytics/"
  echo "USER: admin"
  echo "PASS: $PW"
  echo "============================"
else
  echo "htpasswd 이미 존재 — 비밀번호 유지($HTPASS)"
fi

# --- 5) nginx 검증·리로드 ---
nginx -t && systemctl reload nginx && echo "nginx reload OK"

# --- 6) cron (15분마다 분석 갱신) ---
chmod +x "$ANALYTICS_SH" || true
LINE="*/15 * * * * $ANALYTICS_SH >> /var/log/adsense_analytics.log 2>&1"
if crontab -l 2>/dev/null | grep -qF "$ANALYTICS_SH"; then
  echo "cron 이미 등록됨"
else
  ( crontab -l 2>/dev/null; echo "# === pjt12-adsense 방문 분석(15분) ==="; echo "$LINE" ) | crontab -
  echo "cron 등록: $LINE"
fi
echo "setup 완료."
