"""alerts.py — 이상 알림 (AUTOMATION.md §4). 텔레그램·슬랙·콘솔 폴백.

채널은 config/sites.yaml alerts.channel, 자격증명은 .env. 없으면 콘솔 출력(graceful).
httpx 만 사용.
"""
from __future__ import annotations
import os


def send(message: str, cfg=None) -> bool:
    channel = "telegram"
    try:
        channel = cfg["sites"]["alerts"]["channel"]
    except Exception:
        pass
    try:
        if channel == "telegram" and _telegram(message):
            return True
        if channel == "slack" and _slack(message):
            return True
    except Exception as e:
        print(f"alerts 전송 실패({channel}): {e}")
    print("[ALERT]", message)   # 폴백(자격증명 없음/실패)
    return False


def _telegram(msg: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    import httpx
    httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
               json={"chat_id": chat, "text": msg}, timeout=15).raise_for_status()
    return True


def _slack(msg: str) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    import httpx
    httpx.post(url, json={"text": msg}, timeout=15).raise_for_status()
    return True
