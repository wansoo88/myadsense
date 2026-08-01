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
            d.get("web_root", "/var/www/utilverse.info"),
            os.path.expanduser(d.get("ssh_key", DEFAULT_KEY)),
            d.get("domain_root", "utilverse.info"))


def nginx_vhost(domain: str, web_root: str) -> str:
    """참고용 nginx 정적 vhost (1회 셋업 — 이미 적용됨). certbot --nginx -d {domain} 로 TLS."""
    return (f"server {{\n  server_name {domain};\n  root {web_root};\n  index index.html;\n"
            f"  location / {{ try_files $uri $uri/ $uri/index.html =404; }}\n"
            f"  gzip on; gzip_types text/css application/javascript image/svg+xml;\n  listen 80;\n}}\n")


def deploy(cfg, *, dry_run: bool = True):
    host, web_root, key, droot = _cfg(cfg)
    # 안전장치: 새 디렉토리(.new)에 빌드 후 web_root 로 교체하므로 경로가 정상인지 먼저 검증.
    if not (web_root.startswith("/var/www/") and web_root.rstrip("/") != "/var/www"):
        raise RuntimeError(f"안전장치: 비정상 web_root({web_root!r}) — 정리 배포 거부")
    # 파이프라인이 웹서버와 같은 호스트(서버 cron)에서 돌 때: ssh(자기 자신) 대신 로컬 복사.
    if os.environ.get("ADSENSE_LOCAL_DEPLOY") == "1":
        return _deploy_local(web_root, droot, dry_run=dry_run)
    tgz = "dist/_site.tgz"
    ssh = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=accept-new", f"root@{host}"]
    # 원자적 교체: 새 디렉토리(.new)에 먼저 전량 추출 → rename 으로 순간 교체(mv old, mv new).
    # 이전 방식(web_root 비우고 추출)은 배포 중 사이트가 초 단위로 비어 404 발생 → 색인 손상.
    # 이제 빈 창은 rename 2회(마이크로초)로 축소. .new/.old 는 web_root 형제(동일 FS → rename 원자적).
    new_dir, old_dir = f"{web_root}.new", f"{web_root}.old"
    swap = (
        f"set -e; rm -rf {new_dir} {old_dir}; mkdir -p {new_dir}; "
        f"tar -C {new_dir} -xzf /tmp/stack_site.tgz; rm -f /tmp/stack_site.tgz; "
        f"if [ -d {web_root} ]; then mv {web_root} {old_dir}; fi; "
        f"mv {new_dir} {web_root}; rm -rf {old_dir}"
    )
    steps = [
        ["tar", "-C", SRC, "-czf", tgz, "."],
        ["scp", "-i", key, "-o", "StrictHostKeyChecking=accept-new", tgz, f"root@{host}:/tmp/stack_site.tgz"],
        ssh + [swap],
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
    """서버 cron 실행용 — ssh 없이 로컬에서 web_root 를 dist/site 로 원자적 교체.

    새 디렉토리(.new)에 전량 복사 후 rename 2회로 순간 교체 → 배포 중 사이트가 비는 창을
    초 단위에서 마이크로초로 축소(빈 창 접속 시 404 → 색인 손상 방지). .new/.old 는 web_root
    형제 경로(동일 파일시스템 → os.rename 원자적). nginx root(=web_root) 디렉토리는 매 요청
    resolve 되므로 rename 즉시 새 콘텐츠 반영."""
    import shutil
    new_dir, old_dir = web_root.rstrip("/") + ".new", web_root.rstrip("/") + ".old"
    if dry_run:
        print("[deploy LOCAL DRY-RUN] 실제 배포하려면 ADSENSE_DEPLOY=1 + ADSENSE_LOCAL_DEPLOY=1")
        print(f"  copytree {SRC} → {new_dir}  &&  mv {web_root} {old_dir}  &&  mv {new_dir} {web_root}  &&  rm -rf {old_dir}")
        return None
    if not os.path.isdir(SRC):
        raise RuntimeError("dist/site 없음 — 먼저 orchestrator --stage build")
    # 1) 새 디렉토리에 전량 빌드(느린 작업 — 교체 창 밖에서 수행)
    for tmp in (new_dir, old_dir):
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
    shutil.copytree(SRC, new_dir)
    # 2) 원자적 교체: rename 2회(마이크로초). 그 사이에만 web_root 부재 → 실질 빈 창 제거.
    if os.path.isdir(web_root):
        os.rename(web_root, old_dir)
    os.rename(new_dir, web_root)
    # 3) 구 버전 정리(교체 완료 후 — 서비스 영향 없음)
    if os.path.isdir(old_dir):
        shutil.rmtree(old_dir)
    print(f"[deploy LOCAL] {SRC} → {web_root} 원자적 교체 완료 → https://stack.{droot}")
    return "local"


def remove_noindex(cfg):
    """[STAGING] noindex 해제 — vhost 의 X-Robots-Tag 줄 제거 + nginx reload (실제 변경: ADSENSE_DEPLOY=1).
    이미 1회 적용됨(2026-07-02 색인 허용 확인). sed 삭제는 멱등이라 재실행해도 안전."""
    host, _, key, _ = _cfg(cfg)
    conf = f"/etc/nginx/sites-available/{_cfg(cfg)[3]}"   # 서빙 중인 vhost(= domain_root)
    remote = (f"sed -i '/X-Robots-Tag/d' {conf} && nginx -t && systemctl reload nginx "
              f"&& echo 'noindex 제거·reload 완료'")
    cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=accept-new", f"root@{host}", remote]
    if os.environ.get("ADSENSE_DEPLOY") != "1":
        print("[remove_noindex DRY-RUN] ADSENSE_DEPLOY=1 필요:\n  " + " ".join(cmd[:-1]) + f" '{remote}'")
        return
    subprocess.run(cmd, check=True)
