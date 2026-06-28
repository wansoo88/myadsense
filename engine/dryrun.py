"""dryrun.py — 첫 페이지 엔드투엔드 드라이런 (오프라인, API 키 불필요).

생성(fixture) → 품질 게이트 → design.md 렌더 → publisher(dry_run) → dist/preview.
실행:  python engine/dryrun.py            (프로젝트 루트에서)
       python engine/dryrun.py "notion vs obsidian"
"""
from __future__ import annotations
import os
import sys

try:  # Windows 콘솔(cp949)에서 한글/유니코드 출력 보정
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from content import generator, quality_gate, publisher

# content.yaml 의 quality_gate 기본값 (pyyaml 없을 때 폴백 — 드라이런 자족)
DEFAULT_CONTENT = {
    "quality_gate": {
        "unique_value": {"require_unique_block": True},
        "near_duplicate": {"method": "minhash", "max_similarity": 0.70},
        "structure": {"require_intent_sections": True, "min_substantive_blocks": 4},
        "eeat": {"require_sources": True, "require_dates": True, "require_author": True, "require_schema_org": True},
        "policy_screen": {"block_prohibited_topics": True, "block_ad_clickbait": True, "block_copyright_risk": True},
        "human_sample_gate": {"enabled": True, "sample_pct": 10},
    }
}


def load_content_cfg() -> dict:
    try:
        import yaml
        with open("config/content.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return DEFAULT_CONTENT


def load_sites_cfg() -> dict:
    try:
        import yaml
        with open("config/sites.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def main(argv=None):
    topic = (argv or sys.argv[1:] or ["cursor vs github copilot"])[0]
    content_cfg = load_content_cfg()

    print(f"\n[1] 생성(fixture) — topic: {topic!r}")
    spec, page = generator.generate(topic, content_cfg, force_fixture=True, draft=True)
    print(f"    slug={spec.slug} · 섹션 {len(spec.sections)} · unique_blocks={page.unique_blocks} · sources {len(page.sources)}")

    print("[2] 품질 게이트")
    result = quality_gate.check(page, content_cfg, existing_corpus=[])
    if result.passed:
        print("    ✅ PASS — 발행 큐 자격")
    else:
        print("    ❌ REJECT:")
        for r in result.reasons:
            print(f"       - {r}")

    print("[3] 발행 (dry_run → dist/preview)")
    path = publisher.StaticSSGPublisher(load_sites_cfg()).publish(page.html, spec.slug, dry_run=True)
    size = os.path.getsize(path)
    print(f"    → {path} ({size:,} bytes)")

    print("\n요약: 게이트 {} · 미리보기 {}".format("통과" if result.passed else "거부", path))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
