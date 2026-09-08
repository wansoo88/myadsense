# -*- coding: utf-8 -*-
"""patch_measured_titles.py — 이미 발행된 measured 섹션의 **제목(h2)과 도입 문장만** 표 내용에 맞게 줄인다(ORDER 55 B0).

왜 따로 있나: add_measurements.py 를 다시 돌리면 표도 최신 측정치로 바뀐다. B0 는 "제목이 표를 넘어선다"는 검수 지적만
고치는 일이라 표는 바이트 그대로 두고 h2·intro 두 줄만 바꾼다. 제목은 add_measurements.derive_title 이 만들므로 다음 재주입과 같다.

  python scripts/patch_measured_titles.py --src dist/queue_server --dst dist/queue_patched [--only slug ...]
"""
from __future__ import annotations
import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_measurements import MARK, INTRO, derive_title   # noqa: E402

# 표 머리글 → 표 종류 (add_measurements 의 각 *_table 이 쓰는 머리글 그대로)
HEAD_KIND = [("TCP connect (ms)", "latency_table"), ("Download (MB/s)", "throughput_table"),
             ("Compressed size", "image_table"), ("First HTTP response", "run_table"),
             ("Installer size", "release_table"), ("Idle memory", "desktop_table"),
             ("Run (--version)", "cli_table"), ("Commits (", "repo_table"), ("Observed price", "price_table")]


def kinds_in(section: str) -> list:
    out = []
    for head in re.findall(r"<thead><tr>(.*?)</tr></thead>", section, re.S):
        for needle, kind in HEAD_KIND:
            if needle in head and kind not in out:
                out.append(kind)
                break
    return out


def patch(doc: str) -> tuple[str, str | None]:
    m = re.search(r'(<section class="blk" id="measured">' + re.escape(MARK) + r')<h2>(.*?)</h2>(<p>.*?</p>)(.*?)</section>', doc, re.S)
    if not m:
        return doc, None
    kinds = kinds_in(m.group(4))
    title = derive_title(kinds)
    new = f"{m.group(1)}<h2>{html.escape(title)}</h2>{INTRO}{m.group(4)}</section>"
    return doc[:m.start()] + new + doc[m.end():], f"{html.unescape(m.group(2))!r} → {title!r} (tables: {', '.join(kinds)})"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    os.makedirs(a.dst, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(a.src)):
        slug = fn[:-5]
        if not fn.endswith(".html") or (a.only and slug not in a.only):
            continue
        path = os.path.join(a.src, fn)
        out_path = os.path.join(a.dst, fn)
        if os.path.isfile(out_path):                      # 먼저 쌓인 패치 위에 쌓는다
            path = out_path
        doc = open(path, encoding="utf-8").read()
        new, how = patch(doc)
        if how is None:
            continue
        if new != doc:
            open(out_path, "w", encoding="utf-8", newline="").write(new)
            n += 1
        print(f"  {'✓' if new != doc else '='} {slug[:55]}: {how}")
    print(f"patched: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
