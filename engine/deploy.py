"""deploy.py — 빌드된 정적 사이트를 보유 서버로 배포 (AUTOMATION.md §6).

이 서버는 **nginx**(80/443) + certbot 구성(Caddy 아님 — data·itsmine 등 기존 서브도메인 공유).
stack.utilverse.info 의 nginx vhost·TLS는 1회 셋업 완료. 이후 배포는 dist/site 콘텐츠 동기화뿐.
전송: tar → scp → 원격 추출 (로컬 rsync 불필요, Windows/Git-Bash·Linux 공통).
안전 가드: 기본 DRY-RUN, ADSENSE_DEPLOY=1 일 때만 실제 전송.

ℹ️ [STAGING] noindex 해제 완료 — 실콘텐츠(15편) 배포 후 vhost 의 X-Robots-Tag 줄 제거됨.
   2026-07-02 확인: 응답 헤더·robots 메타 없음, robots.txt Allow / → 색인 허용 상태.
   noindex 재적용/재해제가 필요하면 remove_noindex()(서버 add_header 조작 + nginx reload) 참고.
"""
from __future__ import annotations
import os
import subprocess

SRC = "dist/site"
DEFAULT_KEY = "~/.ssh/autobtc_iwinv"


def _cfg(cfg):
    d = (cfg.get("sites", {}) or {}).get("deploy", {}) or {}
    return (d.get("host", "115.68.230.40"),
            d.get("web_root", "/var/www/stack.utilverse.info"),
            os.path.expanduser(d.get("ssh_key", DEFAULT_KEY)),
            d.get("domain_root", "utilverse.info"))


def nginx_vhost(domain: str, web_root: str) -> str:
    """참고용 nginx 정적 vhost (1회 셋업 — 이미 적용됨). certbot --nginx -d {domain} 로 TLS."""
    return (f"server {{\n  server_name {domain};\n  root {web_root};\n  index index.html;\n"
            f"  location / {{ try_files $uri $uri/ $uri/index.html =404; }}\n"
            f"  gzip on; gzip_types text/css application/javascript image/svg+xml;\n  listen 80;\n}}\n")


def deploy(cfg, *, dry_run: bool = True):
    host, web_root, key, droot = _cfg(cfg)
    # 안전장치: web_root 를 비우고 추출하므로(=stale 페이지 제거) 경로가 정상인지 먼저 검증.
    if not (web_root.startswith("/var/www/") and web_root.rstrip("/") != "/var/www"):
        raise RuntimeError(f"안전장치: 비정상 web_root({web_root!r}) — 정리 배포 거부")
    # 파이프라인이 웹서버와 같은 호스트(서버 cron)에서 돌 때: ssh(자기 자신) 대신 로컬 복사.
    if os.environ.get("ADSENSE_LOCAL_DEPLOY") == "1":
        return _deploy_local(web_root, droot, dry_run=dry_run)
    tgz = "dist/_site.tgz"
    ssh = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=accept-new", f"root@{host}"]
    # web_root 내용물만 삭제(-mindepth 1, 디렉터리 자체·nginx root 유지) → 추출. 구 샘플/삭제된 슬러그가 남아 색인되는 것 방지.
    steps = [
        ["tar", "-C", SRC, "-czf", tgz, "."],
        ["scp", "-i", key, "-o", "StrictHostKeyChecking=accept-new", tgz, f"root@{host}:/tmp/stack_site.tgz"],
        ssh + [f"mkdir -p {web_root} && find {web_root} -mindepth 1 -delete && "
               f"tar -C {web_root} -xzf /tmp/stack_site.tgz && rm -f /tmp/stack_site.tgz"],
    ]
    if dry_run:
        print("[deploy DRY-RUN] 실제 배포하려면 ADSENSE_DEPLOY=1")
        for s in steps:
            print("  " + " ".join(s))
        print(f"  → https://stack.{droot} (nginx vhost·TLS 셋업 완료)")
        return None
    if not os.path.isdir(SRC):
        raise RuntimeError("dist/site 없음 — 먼저 orchestrator --stage build")
    print(f"[deploy] tar/scp over ssh → {host}:{web_root}")
    for s in steps:
        subprocess.run(s, check=True)
    if os.path.exists(tgz):
        os.remove(tgz)
    print(f"[deploy] 완료 → https://stack.{droot}")
    return host


def _deploy_local(web_root: str, droot: str, *, dry_run: bool = True):
    """서버 cron 실행용 — ssh 없이 로컬에서 web_root 를 dist/site 로 갱신(내용만 교체, root 디렉토리 유지)."""
    import shutil
    if dry_run:
        print("[deploy LOCAL DRY-RUN] 실제 배포하려면 ADSENSE_DEPLOY=1 + ADSENSE_LOCAL_DEPLOY=1")
        print(f"  find {web_root} -mindepth 1 -delete  &&  cp -a {SRC}/. {web_root}/")
        return None
    if not os.path.isdir(SRC):
        raise RuntimeError("dist/site 없음 — 먼저 orchestrator --stage build")
    os.makedirs(web_root, exist_ok=True)
    for name in os.listdir(web_root):          # web_root 내용만 비움(디렉토리 자체·nginx 설정 유지)
        p = os.path.join(web_root, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    shutil.copytree(SRC, web_root, dirs_exist_ok=True)
    print(f"[deploy LOCAL] {SRC} → {web_root} 완료 → https://stack.{droot}")
    return "local"


def remove_noindex(cfg):
    """[STAGING] noindex 해제 — vhost 의 X-Robots-Tag 줄 제거 + nginx reload (실제 변경: ADSENSE_DEPLOY=1).
    이미 1회 적용됨(2026-07-02 색인 허용 확인). sed 삭제는 멱등이라 재실행해도 안전."""
    host, _, key, _ = _cfg(cfg)
    conf = "/etc/nginx/sites-available/stack.utilverse.info"
    remote = (f"sed -i '/X-Robots-Tag/d' {conf} && nginx -t && systemctl reload nginx "
              f"&& echo 'noindex 제거·reload 완료'")
    cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=accept-new", f"root@{host}", remote]
    if os.environ.get("ADSENSE_DEPLOY") != "1":
        print("[remove_noindex DRY-RUN] ADSENSE_DEPLOY=1 필요:\n  " + " ".join(cmd[:-1]) + f" '{remote}'")
        return
    subprocess.run(cmd, check=True)
