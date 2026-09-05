# -*- coding: utf-8 -*-
"""releases — 설치 파일의 버전·배포일·크기. 세 출처: GitHub Releases(자산 크기), 직접 다운로드 URL(HEAD Content-Length),
PyPI(JSON API 의 wheel 크기). 파일을 내려받지 않는다."""
from __future__ import annotations
import json
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "utilverse-measure/1.0", "Accept": "application/vnd.github+json"}


def _get_json(url: str, timeout: int = 30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def github_asset(repo: str, asset_re: str, tag_prefix: str = "") -> dict:
    rel = _get_json(f"https://api.github.com/repos/{repo}/releases?per_page=12")
    pat = re.compile(asset_re)
    for r in rel:
        if tag_prefix and not str(r.get("tag_name", "")).startswith(tag_prefix):
            continue
        for a in r.get("assets", []):
            if pat.match(a["name"]):
                return {"version": r.get("tag_name"), "published": (r.get("published_at") or "")[:10],
                        "asset": a["name"], "bytes": a["size"], "source": r.get("html_url")}
    return {"error": "no matching asset in the last 12 releases"}


def head_size(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0 utilverse-measure/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        final = r.geturl()
        n = r.headers.get("Content-Length")
        fname = urllib.parse.unquote(final.rsplit("/", 1)[-1])
        m = re.search(r"(?<![\d.])(\d+(?:\.\d+)+)", fname)
        return {"bytes": int(n) if n else None, "asset": fname,
                "version": (m.group(1) if m else None), "source": url, "final_url": final}


def pypi(project: str) -> dict:
    j = _get_json(f"https://pypi.org/pypi/{project}/json")
    ver = j["info"]["version"]
    files = j["releases"].get(ver, [])
    wheel = [f for f in files if f.get("packagetype") == "bdist_wheel"] or files
    f = wheel[0] if wheel else {}
    return {"version": ver, "published": (f.get("upload_time") or "")[:10], "asset": f.get("filename"),
            "bytes": f.get("size"), "source": f"https://pypi.org/project/{project}/{ver}/"}


def run(cfg: dict) -> dict:
    rows = []
    for a in cfg.get("apps", []):
        row = {"key": a["key"], "label": a["label"]}
        try:
            if a.get("github"):
                row.update(github_asset(a["github"], a["asset"], a.get("tag_prefix", "")))
            elif a.get("pypi"):
                row.update(pypi(a["pypi"]))
            elif a.get("url"):
                row.update(head_size(a["url"]))
            b = row.get("bytes")
            row["mb"] = (round(b / 1e6, 1) if b < 10e6 else round(b / 1e6, 0)) if b else None
        except Exception as e:
            row.update({"error": f"{type(e).__name__}: {str(e)[:120]}", "mb": None})
        rows.append(row)
        print(f"  {row['label']:<26} {row.get('version')} {row.get('published', '')} {row.get('mb')} MB {row.get('error', '')}")
    return {"rows": rows}
