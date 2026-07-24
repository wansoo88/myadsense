"""tell.py — 에이전트 간 메시지 전달 (herdr send + Enter 제출).

    python scripts/tell.py <대상> <메시지>
    예) python scripts/tell.py pm "DONE 2026-07-24-01-content | 초안 2편 | 산출물: dist/queue/"

왜 필요한가:
  `herdr agent send` 는 대상 pane 입력창에 **텍스트만 넣고 제출하지 않는다**(Enter 없음).
  → 그대로 두면 상대 에이전트는 메시지를 영영 못 본다. 이 스크립트가 send + Enter 를 묶는다.
  또 Windows PowerShell 5.1 은 네이티브 인자의 큰따옴표를 삼키므로, 파이썬 subprocess(리스트 인자)로
  셸을 거치지 않고 전달해 따옴표·파이프(|)가 살아남는다.

대상은 herdr 에이전트 이름(pm / content / review / ops / growth). pane id 를 몰라도 된다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

HERDR = shutil.which("herdr") or "herdr"


def _run(args: list[str]) -> str:
    p = subprocess.run([HERDR] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"herdr {' '.join(args)} 실패(rc={p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def find_agent(name: str) -> dict:
    data = json.loads(_run(["agent", "list"]))
    for a in data.get("result", {}).get("agents", []):
        if a.get("name") == name:
            return a
    raise SystemExit(f"에이전트 '{name}' 없음. `herdr agent list` 로 확인하거나 python scripts/team_up.py 로 부팅.")


def tell(name: str, text: str) -> None:
    agent = find_agent(name)
    status = agent.get("agent_status")
    _run(["agent", "send", name, text])
    _run(["pane", "send-keys", agent["pane_id"], "Enter"])
    print(f"sent -> {name} ({agent['pane_id']}, {status}): {text}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    tell(sys.argv[1], " ".join(sys.argv[2:]))
