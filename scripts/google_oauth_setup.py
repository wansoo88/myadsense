#!/usr/bin/env python
"""google_oauth_setup.py — Google OAuth 리프레시 토큰 1회 발급 (AdSense + Search Console 읽기).

이 스크립트는 **로컬(브라우저 있는 PC)** 에서 1회만 실행한다. 발급된 refresh token 을
서버 .env 의 GOOGLE_OAUTH_REFRESH_TOKEN 에 넣으면 ingest 가 AdSense·Search Console 를 읽는다.

사전 준비(회원 계정, Google Cloud Console):
  1) 프로젝트 생성 → "API 및 서비스 > 라이브러리" 에서
     'Google Search Console API' 와 'AdSense Management API' 사용 설정.
  2) "OAuth 동의 화면" 구성(외부, 테스트 사용자에 본인 이메일 추가).
  3) "사용자 인증 정보 > OAuth 클라이언트 ID > 데스크톱 앱" 생성 → client_id / client_secret 확보.

실행:
  # 환경변수로 넘기거나(권장), 없으면 프롬프트로 입력받는다.
  GOOGLE_OAUTH_CLIENT_ID=xxx GOOGLE_OAUTH_CLIENT_SECRET=yyy python scripts/google_oauth_setup.py

출력된 refresh token 을 서버 .env 에 기록:
  GOOGLE_OAUTH_CLIENT_ID=...
  GOOGLE_OAUTH_CLIENT_SECRET=...
  GOOGLE_OAUTH_REFRESH_TOKEN=<출력값>
  SEARCH_CONSOLE_SITE_URL=https://stack.utilverse.info/   # GSC 속성 문자열과 정확히 일치
  ADSENSE_ACCOUNT_ID=pub-XXXXXXXXXXXXXXXX                  # (AdSense 승인 후)
"""
from __future__ import annotations
import os
import sys

# adsense + search console 읽기 — 한 토큰으로 두 API 모두 커버
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/adsense.readonly",
]


def main() -> int:
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or input("OAuth Client ID: ").strip()
    secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or input("OAuth Client Secret: ").strip()
    if not cid or not secret:
        print("client_id / client_secret 이 필요합니다.", file=sys.stderr)
        return 1
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("google-auth-oauthlib 미설치 → pip install google-auth-oauthlib", file=sys.stderr)
        return 1

    client_config = {"installed": {
        "client_id": cid,
        "client_secret": secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # 로컬 브라우저가 열리며 동의 → 자동으로 토큰 수신(포트 임의). 브라우저 없으면 URL 을 직접 열 것.
    creds = flow.run_local_server(port=0, prompt="consent")
    if not creds.refresh_token:
        print("refresh_token 미발급 — 이미 동의한 클라이언트면 prompt=consent 로 재시도하세요.", file=sys.stderr)
        return 1
    print("\n=== 서버 .env 에 아래를 기록하세요 ===")
    print(f"GOOGLE_OAUTH_CLIENT_ID={cid}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("SEARCH_CONSOLE_SITE_URL=https://stack.utilverse.info/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
