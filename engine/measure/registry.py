# -*- coding: utf-8 -*-
"""registry — 컨테이너 이미지의 압축 크기(레지스트리가 보고하는 linux/amd64 레이어 합)와 마지막 푸시일.

Docker Hub 는 v2/repositories API(images[].size), ghcr 은 OCI 매니페스트(layers[].size). 이미지를 내려받지 않는다.
'압축 크기' = 네트워크로 받는 바이트. 디스크 전개 크기는 docker_run 이 실제 pull 뒤에 잰다.
"""
from __future__ import annotations
import json
import urllib.request

UA = {"User-Agent": "utilverse-measure/1.0"}


def _get(url: str, headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _parse(ref: str):
    """docker.io/ns/repo:tag · ghcr.io/org/repo:tag → (registry, path, tag)"""
    reg, rest = ref.split("/", 1)
    path, _, tag = rest.partition(":")
    return reg, path, tag or "latest"


def dockerhub(path: str, tag: str) -> dict:
    ns, repo = path.split("/", 1)
    j = _get(f"https://hub.docker.com/v2/repositories/{ns}/{repo}/tags/{tag}")
    amd = [i for i in j.get("images", []) if i.get("architecture") == "amd64" and i.get("os") == "linux"]
    size = amd[0]["size"] if amd else j.get("full_size")
    return {"compressed_bytes": size, "last_pushed": (j.get("tag_last_pushed") or "")[:10],
            "digest": ((amd[0].get("digest") or "") if amd else (j.get("digest") or ""))[:19]}


def ghcr(path: str, tag: str) -> dict:
    tok = _get(f"https://ghcr.io/token?scope=repository:{path}:pull")["token"]
    acc = ("application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, "
           "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json")
    h = {"Authorization": f"Bearer {tok}", "Accept": acc}
    m = _get(f"https://ghcr.io/v2/{path}/manifests/{tag}", h)
    digest = ""
    if "manifests" in m:
        cand = [x for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64"
                and x.get("platform", {}).get("os") == "linux"]
        digest = cand[0]["digest"] if cand else m["manifests"][0]["digest"]
        m = _get(f"https://ghcr.io/v2/{path}/manifests/{digest}", h)
    size = sum(l.get("size", 0) for l in m.get("layers", []))
    return {"compressed_bytes": size, "last_pushed": None, "digest": digest[:19]}   # ghcr 매니페스트엔 푸시일이 없다


def run(cfg: dict) -> dict:
    rows = []
    for im in cfg.get("images", []):
        reg, path, tag = _parse(im["ref"])
        row = {"key": im["key"], "label": im["label"], "ref": im["ref"]}
        try:
            row.update(dockerhub(path, tag) if reg == "docker.io" else ghcr(path, tag))
            row["compressed_mb"] = round(row["compressed_bytes"] / 1e6, 0) if row.get("compressed_bytes") else None
        except Exception as e:                       # 못 잰 것은 못 잰 것으로
            row.update({"error": f"{type(e).__name__}: {str(e)[:120]}", "compressed_mb": None})
        rows.append(row)
        print(f"  {row['label']:<16} {row.get('compressed_mb')} MB  pushed {row.get('last_pushed')}  {row.get('error', '')}")
    return {"rows": rows}
