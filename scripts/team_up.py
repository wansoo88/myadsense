"""team_up.py — 에이전트 팀 부팅/복구/상태 (team/CHARTER.md §8).

    python scripts/team_up.py            # 팀 상태 표 (API 죽어도 pane 라벨은 보여준다)
    python scripts/team_up.py --boot     # 없는 워커를 살린다: 라벨 pane 이 있으면 그 pane 을 재사용, 없으면 새로 만든다
    python scripts/team_up.py --kick ops # 특정 역할에 킥오프(역할 숙지) 재전송
    python scripts/team_up.py --boot --yolo   # 워커를 --dangerously-skip-permissions 로 기동

pane 배치 (workspace = PM 이 있는 곳):

    ┌──────────┬─────────┬─────────┐
    │          │ CONTENT │ REVIEW  │
    │    PM    ├─────────┼─────────┤
    │          │  OPS    │ GROWTH  │
    └──────────┴─────────┴─────────┘

PM pane 은 **사람이 쓰고 있는 pane** 이다 → 새로 만들지 않는다.
아직 이름이 없으면: herdr agent rename <pane_id> pm

⚠️ 2026-07-24 장애 교훈 — herdr 서버 프로세스는 살아 있는데 **소켓 API 만 죽는** 경우가 있다.
그러면 `herdr agent *` 전부 NotFound 로 실패하고(=PM 이 지시를 못 보냄), 워커 pane 은 화면에 남아 있지만
session.json 의 `agent_name` 이 날아가 이름으로 찾을 수 없게 된다. 이때 예전 --boot 는 **살아 있는 pane 을
못 보고 새 pane 을 또 만들었다**(9분할). 그래서 이 스크립트는 라벨(PM/CONTENT/…)로 기존 pane 을 먼저 찾아
**입양(adopt)** 한다. 라벨 지도는 API 없이 session.json 에서 직접 읽는다.
소켓 API 자체가 죽었으면 herdr 서버 재시작 외엔 방법이 없다 → `herdr status` 로 먼저 확인할 것.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

HERDR = shutil.which("herdr") or "herdr"
CWD = r"D:\cashflow\pjt12-adsense"
SESSION_JSON = os.path.join(os.environ.get("APPDATA", ""), "herdr", "session.json")

# 역할 → (분할 기준이 되는 부모 역할, 분할 방향)
LAYOUT = [
    ("content", "pm", "right"),
    ("ops", "content", "down"),
    ("review", "content", "right"),
    ("growth", "ops", "right"),
]
ROLES = [r for r, _, _ in LAYOUT]

KICKOFF = {
    "content": (
        "너는 이 프로젝트의 CONTENT 에이전트다. 먼저 team/CHARTER.md 와 team/roles/content.md 를 읽고 "
        "역할·소유영역·경계·보고 형식을 숙지하라."
    ),
    "review": (
        "너는 이 프로젝트의 REVIEW 에이전트다. 먼저 team/CHARTER.md 와 team/roles/review.md 를 읽고 "
        "역할·거부권(veto)·검수 루브릭·킬스위치 감시·경계를 숙지하라."
    ),
    "ops": (
        "너는 이 프로젝트의 OPS 에이전트다. 먼저 team/CHARTER.md 와 team/roles/ops.md 를 읽고 "
        "역할·발행 전 체크리스트·경계를 숙지하라. 발행·배포는 REVIEW pass 와 PM 승인 없이 절대 실행하지 않는다."
    ),
    "growth": (
        "너는 이 프로젝트의 GROWTH 에이전트다. 먼저 team/CHARTER.md 와 team/roles/growth.md 를 읽고 "
        "역할·업무 원칙·절대 금지선을 숙지하라. 트래픽·클릭 생성과 자동 홍보/백링크 봇은 어떤 형태로도 만들지 않는다."
    ),
}

COMMON_TAIL = (
    " 숙지 후 새 작업은 시작하지 말고 대기하되, 먼저 PM 에게 준비 완료를 보고하라."
    " 보고는 반드시 python scripts/tell.py 로 한다 (herdr agent send 만 쓰면 Enter 제출이 안 되어 상대가 못 본다)."
    " 보고 예: python scripts/tell.py pm READY {role} 역할숙지완료 대기중."
    " 앞으로 사람과 직접 대화하지 않고 PM 의 ORDER 만 수행한다."
)

API_DEAD_HINT = (
    "herdr 소켓 API 에 연결할 수 없다.\n"
    "  1) `herdr status` 로 server 상태 확인 (server: not running 이면 API 소켓이 죽은 것)\n"
    "  2) 서버 프로세스가 살아 있어도 API 만 죽을 수 있다 → herdr 재시작 외 복구 불가\n"
    "     (재시작하면 모든 workspace 의 pane 이 닫힌다 — 다른 프로젝트 팀도 함께 죽는다)\n"
    "  3) 재시작 후 이 스크립트를 --boot 로 다시 실행하면 라벨 pane 을 입양해 팀을 복구한다."
)


def run(args: list[str], check: bool = True) -> str:
    p = subprocess.run([HERDR] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip()
        if check:
            if "NotFound" in err or "지정된 파일을 찾을 수 없" in err:
                raise SystemExit(f"herdr {' '.join(args)} 실패: {err}\n\n{API_DEAD_HINT}")
            raise SystemExit(f"herdr {' '.join(args)} 실패: {err}")
        return ""
    return p.stdout


def agents() -> dict[str, dict]:
    data = json.loads(run(["agent", "list"]))
    return {a["name"]: a for a in data.get("result", {}).get("agents", []) if a.get("name")}


# ── 라벨 지도: API 없이도 읽히는 유일한 경로 (herdr 가 주기적으로 저장하는 session.json) ──
def workspace_id() -> str:
    ws = os.environ.get("HERDR_WORKSPACE_ID")
    if ws:
        return ws
    try:
        data = json.load(open(SESSION_JSON, encoding="utf-8"))
    except Exception:
        return ""
    for w in data.get("workspaces", []):
        if os.path.normcase(w.get("identity_cwd", "")) == os.path.normcase(CWD):
            return w.get("id", "")
    return ""


def labeled_panes() -> dict[str, str]:
    """라벨(대문자) → pane_id. 예: {'PM': 'w2:p1', 'CONTENT': 'w2:p2', ...}"""
    ws_id = workspace_id()
    if not ws_id:
        return {}
    try:
        data = json.load(open(SESSION_JSON, encoding="utf-8"))
    except Exception:
        return {}
    for w in data.get("workspaces", []):
        if w.get("id") != ws_id:
            continue
        public = {str(k): v for k, v in (w.get("public_pane_numbers") or {}).items()}
        out: dict[str, str] = {}
        for tab in w.get("tabs", []):
            for internal, meta in (tab.get("panes") or {}).items():
                label = (meta.get("label") or "").strip().upper()
                num = public.get(str(internal))
                if label and num is not None:
                    out.setdefault(label, f"{ws_id}:p{num}")
        return out
    return {}


def pane_running_agent(pane_id: str) -> bool:
    """pane 에서 이미 claude 가 돌고 있는가 (돌고 있으면 명령어를 타이핑해선 안 된다 — 입력창에 들어간다)."""
    out = run(["pane", "process-info", "--pane", pane_id], check=False)
    return "claude" in out.lower()


def kick(role: str) -> None:
    text = KICKOFF[role] + COMMON_TAIL.format(role=role)
    subprocess.run([sys.executable, "scripts/tell.py", role, text], check=True)


def adopt(role: str, pane_id: str, yolo: bool) -> bool:
    """화면에 남아 있는 라벨 pane 을 재사용해 워커를 복구한다. 성공하면 True."""
    if not pane_running_agent(pane_id):
        cmd = "claude --dangerously-skip-permissions" if yolo else "claude"
        print(f"  [{role}] {pane_id} 에 `{cmd}` 기동")
        run(["pane", "send-text", pane_id, cmd])
        run(["pane", "send-keys", pane_id, "Enter"])
        for _ in range(40):                      # 최대 ~80초 대기
            time.sleep(2)
            if pane_running_agent(pane_id):
                break
        else:
            print(f"  [{role}] {pane_id} 에서 claude 기동 확인 실패 — 사람이 직접 확인 필요")
            return False
    else:
        print(f"  [{role}] {pane_id} 에 이미 claude 실행 중 → 이름만 재등록")
    run(["agent", "rename", pane_id, role])
    run(["agent", "wait", role, "--status", "idle", "--timeout", "120000"], check=False)
    kick(role)
    return True


def status() -> None:
    labels = labeled_panes()
    try:
        found = agents()
        api = True
    except SystemExit as e:
        print(str(e).splitlines()[0])
        print("→ API 없이 session.json 라벨만 표시한다.\n")
        found, api = {}, False
    print(f"{'role':10} {'pane':8} {'status':10} cwd")
    for role in ["pm"] + ROLES:
        a = found.get(role)
        if a:
            print(f"{role:10} {a['pane_id']:8} {a['agent_status']:10} {a['cwd']}")
            continue
        pane = labels.get(role.upper(), "-")
        note = "UNNAMED" if pane != "-" else "MISSING"
        if not api:
            note = "API-DOWN"
        print(f"{role:10} {pane:8} {note:10} " + ("(라벨 pane 존재 → --boot 가 입양)" if pane != "-"
                                                  else "(python scripts/team_up.py --boot)"))


def boot(yolo: bool = False) -> None:
    found = agents()
    if "pm" not in found:
        raise SystemExit(
            "PM 이 없다. 사람이 쓰는 Claude pane 을 PM 으로 지정하라: herdr agent rename <pane_id> pm"
        )
    tab = found["pm"]["tab_id"]
    labels = labeled_panes()
    adopted: list[str] = []
    created: list[str] = []

    for role, parent, direction in LAYOUT:
        found = agents()
        if role in found:
            continue
        pane_id = labels.get(role.upper())
        if pane_id and pane_id != found["pm"]["pane_id"]:
            # 화면에 이미 있는 pane → 새로 만들지 말고 입양 (2026-07-24 장애: 새로 만들면 pane 이 두 배가 된다)
            if adopt(role, pane_id, yolo):
                adopted.append(role)
                continue
            print(f"  [{role}] 입양 실패 → 새 pane 생성으로 폴백")
        anchor = parent if parent in found else "pm"
        run(["agent", "focus", anchor])
        run(["agent", "start", role, "--cwd", CWD, "--tab", tab,
             "--split", direction, "--no-focus", "--", "claude"])
        created.append(role)
        time.sleep(1)

    if created:
        run(["agent", "focus", "pm"])
        for role in created:
            found = agents()
            run(["pane", "rename", found[role]["pane_id"], role.upper()])
            run(["agent", "wait", role, "--status", "idle", "--timeout", "120000"])
            kick(role)
            time.sleep(1)

    if adopted or created:
        run(["agent", "focus", "pm"], check=False)
        print(f"복구 완료 — 입양: {', '.join(adopted) or '없음'} / 신규: {', '.join(created) or '없음'}")
    else:
        print("모든 pane 이 이미 살아 있다. (킥오프 재전송: --kick <role>)")
    status()


if __name__ == "__main__":
    if "--boot" in sys.argv:
        boot(yolo="--yolo" in sys.argv)
    elif "--kick" in sys.argv:
        target = sys.argv[sys.argv.index("--kick") + 1]
        if target not in KICKOFF:
            raise SystemExit(f"알 수 없는 역할: {target} (선택: {', '.join(KICKOFF)})")
        kick(target)
    else:
        status()
