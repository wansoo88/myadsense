"""deploy.py — 빌드된 정적 사이트를 보유 Ubuntu 서버로 배포 (AUTOMATION.md §6).

rsync over SSH(키: ~/.ssh/autobtc_iwinv) → 서버 web_root → Caddy 가 서빙.
⚠️ 안전 가드: 기본은 DRY-RUN(명령만 출력). 실제 배포는 환경변수 ADSENSE_DEPLOY=1 일 때만.
   프로덕션 변경이므로 DNS(stack.utilverse.info→서버)·Caddy 설정 선행 필요.
"""
from __future__ import annotations
import os
import shlex
import subprocess

SRC = "dist/site/"
DEFAULT_KEY = "~/.ssh/autobtc_iwinv"


def caddy_snippet(domain: str, web_root: str) -> str:
    return (f"{domain} {{\n"
            f"    root * {web_root}\n"
            f"    file_server\n"
            f"    encode gzip\n"
            f"    try_files {{path}} {{path}}/ {{path}}/index.html\n"
            f"}}\n")


def deploy(cfg, *, dry_run: bool = True) -> str:
    d = (cfg.get("sites", {}) or {}).get("deploy", {}) or {}
    host = d.get("host", "115.68.230.40")
    domain = d.get("domain_root", "utilverse.info")
    web_root = d.get("web_root", "/var/www/stack.utilverse.info")
    key = d.get("ssh_key", DEFAULT_KEY)

    ssh = f"ssh -i {key} -o StrictHostKeyChecking=accept-new"
    cmd = ["rsync", "-az", "--delete", "-e", ssh, SRC, f"root@{host}:{web_root}/"]
    printable = " ".join(shlex.quote(c) for c in cmd)

    if dry_run:
        print("[deploy DRY-RUN] 실제 배포하려면 ADSENSE_DEPLOY=1")
        print("  " + printable)
        print("  Caddy 설정(서버 Caddyfile):\n    " + caddy_snippet(f"stack.{domain}", web_root).replace("\n", "\n    "))
        print("  사전: DNS stack." + domain + " → " + host + ", 서버에 " + web_root + " 생성 권한")
        return printable

    if not os.path.isdir("dist/site"):
        raise RuntimeError("dist/site 없음 — 먼저 site_builder.build() (orchestrator --stage build)")
    print("[deploy] rsync 실행:", printable)
    subprocess.run(cmd, check=True)
    print("[deploy] 완료 → https://stack." + domain)
    return printable
