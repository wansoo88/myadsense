# -*- coding: utf-8 -*-
"""measure.py — 1차 측정 실행기. 결과는 data/measurements/<suite>.<host-role>.json (git 에 커밋 = 단일 출처).

  python scripts/measure.py --suite netprobe  --host seoul-vps
  python scripts/measure.py --suite registry  --host windows-laptop
  python scripts/measure.py --suite releases  --host windows-laptop
  python scripts/measure.py --suite desktop   --host windows-laptop        # Windows 전용(창 띄우고 스크린샷)
  python scripts/measure.py --suite docker_run --host windows-laptop --only nextcloud
  python scripts/measure.py --suite repo      --host windows-laptop        # GitHub 활동(커밋·릴리스·이슈), API 만

host 역할은 config/measure.yaml hosts 의 키. 어느 기계에서 쟀는지가 값의 일부다(본문 캡션에 실린다).
"""
from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import yaml                                              # noqa: E402

from engine.measure import common                        # noqa: E402


def main(argv=None) -> int:
    try:                                                  # Windows 콘솔(cp949)에서 라벨의 특수문자로 죽지 않게
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["netprobe", "registry", "releases", "desktop", "docker_run", "repo"])
    ap.add_argument("--host", required=True, help="config/measure.yaml hosts 의 키 (seoul-vps · windows-laptop)")
    ap.add_argument("--only", nargs="*", help="docker_run·desktop·repo: 대상 key 제한")
    ap.add_argument("--keep-image", action="store_true", help="docker_run: 측정 후 이미지를 남긴다")
    a = ap.parse_args(argv)
    with open("config/measure.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if a.host not in (cfg.get("hosts") or {}):
        ap.error(f"--host 는 {list(cfg.get('hosts', {}))} 중 하나")
    prof = common.host_profile(a.host)
    prof["description"] = cfg["hosts"][a.host]
    print(f"measure[{a.suite}] on {a.host}: {prof['os']} · {prof['cpu']} · {prof['ram_gb']} GB")
    if a.suite == "netprobe":
        from engine.measure import netprobe
        res = netprobe.run(cfg["netprobe"])
    elif a.suite == "registry":
        from engine.measure import registry
        res = registry.run(cfg["registry"])
    elif a.suite == "releases":
        from engine.measure import releases
        res = releases.run(cfg["releases"])
    elif a.suite == "desktop":
        from engine.measure import desktop_win
        res = desktop_win.run(cfg["desktop"], only=a.only)
    elif a.suite == "repo":
        from engine.measure import repo
        res = repo.run(cfg["repo"], only=a.only)
    else:
        from engine.measure import docker_run
        res = docker_run.run(cfg["docker_run"], only=a.only, keep_image=a.keep_image)
    payload = {"suite": a.suite, "host": prof, **res}
    if a.only:                                            # --only 는 기존 파일의 다른 행을 지우지 않는다(키 단위 병합, 2026-09-08)
        payload = common.merge_only(a.suite, a.host, payload, keys=a.only)
    p = common.save(a.suite, a.host, payload)
    print(f"saved → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
