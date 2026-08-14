#!/usr/bin/env python3
"""빌더가 만든 spec 한 편을 정본 검수기(engine/content/reviewer.py)에 태운다.

왜 — 1차 데이터 글은 orchestrator 의 생성 루프를 타지 않고 전용 빌더가 만든다.
그래서 자동 검수 게이트를 그냥 지나친다. "만드는 자 ≠ 막는 자" 원칙상
발행 전 반드시 같은 검수기를 통과해야 한다.

사용:
    ./.venv/bin/python scripts/review_one.py build_index_gap_report
    ./.venv/bin/python scripts/review_one.py build_crawler_report
"""
from __future__ import annotations

import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("사용: review_one.py <빌더 모듈명>")
    mod = importlib.import_module(sys.argv[1])

    from content import reviewer
    import yaml

    with open(os.path.join(ROOT, "config", "content.yaml"), encoding="utf-8") as fh:
        content_cfg = yaml.safe_load(fh)

    # 빌더마다 spec 을 만드는 진입점이 조금씩 다르다 — 있는 것을 찾아 쓴다.
    if hasattr(mod, "measure") and hasattr(mod, "load"):
        spec = mod.build_spec(mod.measure(mod.load()))
    elif hasattr(mod, "measure") and hasattr(mod, "gsc_snapshot"):
        spec = mod.build_spec(mod.measure(), mod.gsc_snapshot())
    else:
        spec = mod.build_spec()

    rv = reviewer.review(spec, content_cfg)
    print("passed  :", rv.get("passed"))
    print("severity:", rv.get("severity"))
    print("ai_tells:", json.dumps(rv.get("ai_tells"), ensure_ascii=False)[:600])
    issues = rv.get("issues") or []
    print("issues  :", len(issues))
    for i in issues:
        print("  -", json.dumps(i, ensure_ascii=False)[:700])
    if rv.get("notes"):
        print("notes   :", str(rv["notes"])[:800])
    return 0 if rv.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
