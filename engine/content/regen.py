"""regen.py — **이미 발행된 특정 slug 를 같은 URL 로 재생성**한다 (ORDER 2026-07-25-30-content).

왜 필요한가
-----------
`--stage generate` 는 백로그 키워드에서 뽑고 `published.json` 에 있는 키워드는 **스킵**한다.
`--stage build` 는 `dist/queue` 의 **베이크된 HTML** 을 읽어 chrome/내부링크만 갈아끼울 뿐
본문을 재렌더하지 않는다(26-content §3.1). 따라서 이미 발행된 글에 새 렌더 구조·새 본문을
반영할 경로가 **어디에도 없었다**. 이 모듈이 그 하나뿐인 경로다.

무엇을 우회하고 무엇을 우회하지 않는가 (⚠️ 경계)
------------------------------------------------
- ✅ 우회: "이미 발행한 키워드는 건너뛴다"는 **스킵 로직**과 하루 1편 멱등 가드뿐.
- ⛔ 우회하지 않음: `quality_gate.check` · `reviewer.review` · `human_gate` 는 파이프라인과
  **완전히 동일하게** 호출되고, 통과하지 못하면 큐에 아무것도 쓰지 않는다.
- ⛔ 발행·배포 없음. 산출물은 `dist/queue/<slug>.html` 까지다(G1: 라이브 교체는 REVIEW pass +
  사람 승인 + OPS).
- ⛔ `engine/store/published.json` · `last_publish_date.txt` 를 **건드리지 않는다**
  (재생성은 신규 발행이 아니다 — 일일 카덴스·중복 가드를 오염시키면 안 된다).

URL 불변 보장 (🔴 최중요)
------------------------
`_dict_to_spec()` 는 slug 를 **모델이 지은 제목**에서 만든다 → 재생성하면 제목이 조금만 달라져도
URL 이 바뀌고, 기존 크롤 이력이 날아가며 404 가 생긴다(색인이 더 나빠짐). 그래서 이 모듈은
렌더 **직전에** slug·canonical·breadcrumb·발행일을 **원본 페이지에서 읽은 값으로 고정**한다:

    slug         ← 원본 파일명 (인자로 받은 값)
    canonical    ← 원본 HTML 의 <link rel=canonical> 원문 그대로
    published_at ← 원본 Article JSON-LD 의 datePublished (가짜 신선도 금지)
    updated_at   ← 오늘 (F14 dateModified = 실제 변경일)
    cluster      ← 원본 <meta name=cluster>

⚠️ 이 도구의 용도는 31-content 이후 **바뀌었다** (2026-07-25)
--------------------------------------------------------
원래 지시(30-content)는 "이미 발행된 글에 새 렌더 **구조**를 입히면 색인이 풀린다"는 전제였다.
그 전제는 **틀렸다** — 31-content 감사 실측: 발행 9편의 H2 제목 9/9 고유·본문 H2 59/60 고유·
연문 중복 1%. 구조는 이미 충분히 달랐고, 색인 거부의 원인이 아니었다.
진짜 결손은 **원저 데이터**다: 소스 49개가 100% 벤더 자사 페이지, 자체 측정·1차 관측 0건.
→ 그러므로 이 모듈은 **구조 리페인트용이 아니라, 원저 데이터를 얻은 뒤 그것을 기존 URL 에
   싣기 위한 경로**로만 쓴다. 넣을 새 데이터 없이 돌리면 같은 글을 다시 쓰는 낭비다.

사용
----
    python engine/content/regen.py --slug <slug> [--slug <slug> ...]
    python engine/content/regen.py --slug <slug> --keyword "fly.io vs railway"
    python engine/content/regen.py --slug <slug> --plan-only      # 호출 없이 계획만 출력
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html as _html
import json
import os
import re
import shutil
import sys

# `python engine/content/regen.py` 로 직접 실행해도 orchestrator 와 같은 임포트 경로를 쓰도록
# engine/ 을 sys.path 에 넣는다(orchestrator 는 sys.path[0] 이 engine/ 이라 그냥 된다).
_ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

for _s in (sys.stdout, sys.stderr):          # Windows cp949 콘솔에서 '—' 출력 시 죽지 않게
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

QUEUE_DIR = "dist/queue"
REVIEW_DIR = "dist/review"
BACKUP_ROOT = "dist/backup"


# ── 원본 페이지에서 불변으로 지켜야 할 값 읽기 ────────────────────────────────────────
_CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
_CLUSTER_RE = re.compile(r'<meta name="cluster" content="([^"]+)"')
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)


def _h2_list(html_doc: str) -> list:
    return [_html.unescape(re.sub(r"<[^>]+>", "", m).strip()) for m in _H2_RE.findall(html_doc)]


def read_original(slug: str) -> dict:
    """dist/queue/<slug>.html 에서 URL·날짜·클러스터·구조 시그니처를 읽는다(없으면 예외)."""
    path = os.path.join(QUEUE_DIR, f"{slug}.html")
    if not os.path.exists(path):
        raise SystemExit(f"원본 없음: {path} — 발행된 slug 만 재생성할 수 있다")
    doc = open(path, encoding="utf-8").read()
    raw = open(path, "rb").read()
    out = {
        "path": os.path.abspath(path),
        "bytes": len(raw),
        "md5": hashlib.md5(raw).hexdigest(),
        "canonical": (_CANONICAL_RE.search(doc).group(1) if _CANONICAL_RE.search(doc) else ""),
        "cluster": (_CLUSTER_RE.search(doc).group(1) if _CLUSTER_RE.search(doc) else None),
        "title": _html.unescape(_TITLE_RE.search(doc).group(1).strip()) if _TITLE_RE.search(doc) else "",
        "h2": _h2_list(doc),
        "published_at": None, "updated_at": None, "headline": "",
    }
    for block in _LD_RE.findall(doc):
        try:
            d = json.loads(block)
        except Exception:
            continue
        if isinstance(d, dict) and d.get("@type") == "Article":
            out["published_at"] = d.get("datePublished")
            out["updated_at"] = d.get("dateModified")
            out["headline"] = d.get("headline", "")
    if not out["canonical"]:
        raise SystemExit(f"canonical 을 못 읽었다: {path} — URL 불변을 보장할 수 없으므로 중단")
    if not out["published_at"]:
        raise SystemExit(f"datePublished 를 못 읽었다: {path} — 원발행일 보존 불가이므로 중단")
    return out


# ── 키워드 해석 (published.json 의 원 키워드 ↔ slug) ─────────────────────────────────
def resolve_keyword(slug: str) -> str:
    """`engine/store/published.json` 의 키워드 중 slugify 결과가 slug 의 접두인 것을 고른다.

    slug 는 '<키워드 slug>-<제목 꼬리>' 형태다(제목이 키워드로 시작하므로). 가장 긴 접두 일치를
    고르면 'cursor vs github copilot' 과 'cursor vs windsurf' 를 안전하게 가른다.
    """
    from content import renderer
    pub = "engine/store/published.json"
    if not os.path.exists(pub):
        raise SystemExit("engine/store/published.json 없음 — --keyword 로 직접 지정하라")
    best, best_kw = "", ""
    for kw in json.load(open(pub, encoding="utf-8")):
        ks = renderer.slugify(kw)
        if ks and (slug == ks or slug.startswith(ks + "-")) and len(ks) > len(best):
            best, best_kw = ks, kw
    if not best:
        raise SystemExit(f"'{slug}' 에 대응하는 원 키워드를 못 찾았다 — --keyword 로 직접 지정하라")
    return best_kw


# ── 백업 (되돌릴 수 없으면 시작하지 않는다) ──────────────────────────────────────────
def backup(slugs: list, tag: str = "regen") -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    root = os.path.abspath(os.path.join(BACKUP_ROOT, f"{ts}-{tag}"))
    os.makedirs(root, exist_ok=True)
    man = {"created": ts, "kind": tag, "files": []}
    for s in slugs:
        # (kind, 원본경로) — 백업 파일명은 kind + slug 로 만든다(경로를 파일명에 욱여넣으면
        # 드라이브 문자의 ':' 때문에 Windows 에서 생성 자체가 실패한다).
        for kind, src in (("queue", os.path.join(QUEUE_DIR, f"{s}.html")),
                          ("review", os.path.join(REVIEW_DIR, f"{s}.json")),
                          ("site", os.path.join("dist/site/compare", s, "index.html"))):
            if not os.path.exists(src):
                continue
            dst = os.path.join(root, f"{kind}__{s}{os.path.splitext(src)[1]}")
            shutil.copy2(src, dst)
            raw = open(src, "rb").read()
            man["files"].append({"kind": kind, "src": os.path.abspath(src), "backup": dst,
                                 "bytes": len(raw), "md5": hashlib.md5(raw).hexdigest()})
    json.dump(man, open(os.path.join(root, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"backup: {len(man['files'])}개 파일 → {root}")
    return root


# ── 재생성 1편 ───────────────────────────────────────────────────────────────────────
def regen_one(slug: str, cfg: dict, *, keyword: str | None = None, max_attempts: int = 2,
              corpus: list | None = None) -> dict:
    from content import generator, human_gate, quality_gate, renderer, reviewer
    import orchestrator                                   # review_feedback / _keep_rejected_spec 재사용

    orig = read_original(slug)
    kw = keyword or resolve_keyword(slug)
    today = datetime.date.today().isoformat()
    corpus = [] if corpus is None else corpus
    hsg = (cfg["content"].get("quality_gate", {}).get("human_sample_gate", {}) or {})

    # 🔴 트렌드 축 후보면 **사람이 미리 확정한** URL·식별자를 그대로 쓴다 — 일일 경로와 같아야 한다.
    #   왜(실측 2026-08-04): 이걸 안 넘겼더니 모델이 소스를 다시 찾다가 4개 중 **1개만** 찾았고,
    #   관측 대상도 제품 2개 중 1개만 잡혀 **관측표가 통째로 사라진** 재생성본이 나왔다
    #   (원본 관측표 3행 → 재생성본 0행). 재생성이 원본보다 나빠지는 경로였다.
    #   ORDER 45 ③ 이 발견 단계를 제거한 이유가 그대로 여기에도 적용된다.
    hints = None
    try:
        _, _cands = orchestrator._trend_seeds(cfg)
        _cand = _cands.get(kw)
        if _cand:
            hints = orchestrator._trend_hints(_cand)
    except Exception as e:                                # 힌트 해석 실패는 치명적이지 않다(옛 경로로 진행)
        print(f"    ⚠️ 트렌드 확정값 조회 실패 — {type(e).__name__}: {e}
       → 모델 발견 경로로 진행한다(소스·관측 대상이 줄어들 수 있다). 심볼명을 확인하라.")

    print(f"\n=== REGEN {slug}")
    print(f"    keyword   : {kw}"
          + (f"  [트렌드 축 확정값 사용 — 소스 {len(hints.get('source_urls') or [])}개 ·"
             f" 관측대상 {len(hints.get('targets') or [])}개]" if hints else "  [일반 축 — 모델 발견]"))
    print(f"    canonical : {orig['canonical']}  (불변)")
    print(f"    published : {orig['published_at']}  (보존) / updated → {today}")
    print(f"    cluster   : {orig['cluster']}")

    result = {"slug": slug, "keyword": kw, "canonical": orig["canonical"],
              "published_at": orig["published_at"], "before": orig, "attempts": [],
              "written": None, "passed": False}

    feedback = None
    for attempt in range(1, max_attempts + 1):
        try:
            spec, _ = generator.generate(kw, cfg["content"], cluster=orig["cluster"],
                                         feedback=feedback, hints=hints)
        except Exception as e:
            print(f"  ✗ 생성 실패: {type(e).__name__}: {e}")
            result["attempts"].append({"n": attempt, "stage": "generate", "error": f"{type(e).__name__}: {e}"})
            break

        # 🔴 URL 불변 고정 — 렌더 전에 반드시.
        new_title = spec.title
        spec.slug = slug
        spec.canonical = orig["canonical"]
        spec.published_at = orig["published_at"]
        spec.updated_at = today
        if orig["cluster"]:
            spec.cluster = orig["cluster"]
        spec.breadcrumb = [("Home", "/"), ("Compare", "/compare/"), (spec.title, "")]

        html_doc = renderer.render(spec)                  # 고정값 반영해 다시 렌더
        page = generator.spec_to_page(spec, html_doc)

        g = quality_gate.check(page, cfg["content"], existing_corpus=corpus)
        if not g.passed:
            kept = orchestrator._keep_rejected_spec(spec, stage="quality_gate", keyword=kw,
                                                    attempt=attempt, reasons=g.reasons)
            print(f"  ✗ GATE REJECT (시도 {attempt}/{max_attempts}): {g.reasons}")
            result["attempts"].append({"n": attempt, "stage": "quality_gate", "reasons": g.reasons,
                                       "kept_spec": kept})
            feedback = "; ".join(g.reasons)
            continue

        try:
            rv = reviewer.review(spec, cfg["content"])
        except Exception as e:
            orchestrator._keep_rejected_spec(spec, stage="review_error", keyword=kw,
                                             attempt=attempt, reasons=[f"{type(e).__name__}: {e}"])
            print(f"  ✗ REVIEW 실행 실패: {type(e).__name__}: {e}")
            result["attempts"].append({"n": attempt, "stage": "review_error", "error": f"{type(e).__name__}: {e}"})
            break
        os.makedirs(REVIEW_DIR, exist_ok=True)
        # ⚠️ 기존 판정 기록(dist/review/<slug>.json)은 감사 이력이므로 덮지 않는다 → .regen.json 로 별도 보관.
        vpath = os.path.join(REVIEW_DIR, f"{slug}.regen.json")
        json.dump(rv, open(vpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        if not rv.get("passed"):
            types = [i.get("type") for i in rv.get("issues", [])][:5]
            kept = orchestrator._keep_rejected_spec(spec, stage="review", keyword=kw, attempt=attempt,
                                                    reasons=[f"severity={rv.get('severity')}"] + [str(t) for t in types])
            print(f"  ✗ REVIEW REJECT (시도 {attempt}/{max_attempts}): sev={rv.get('severity')} {types} → {vpath}")
            result["attempts"].append({"n": attempt, "stage": "review", "passed": False,
                                       "severity": rv.get("severity"), "issue_types": types,
                                       "verdict_json": vpath, "kept_spec": kept})
            feedback = orchestrator.review_feedback(rv)
            continue

        # 게이트·검수 통과. human_sample_gate 는 파이프라인과 동일하게 적용(우회하지 않는다).
        if hsg.get("enabled") and human_gate.is_sampled(slug, hsg.get("sample_pct", 0)):
            path = human_gate.hold(slug, html_doc)
            print(f"  ⏸ HUMAN GATE 대기(샘플 {hsg.get('sample_pct')}%) → {path} (큐 미교체)")
        else:
            os.makedirs(QUEUE_DIR, exist_ok=True)
            path = os.path.join(QUEUE_DIR, f"{slug}.html")
            with open(path, "w", encoding="utf-8") as f:  # 파이프라인과 동일한 쓰기(개행 변환 포함)
                f.write(html_doc)
        raw = open(path, "rb").read()
        after = {"path": os.path.abspath(path), "bytes": len(raw), "md5": hashlib.md5(raw).hexdigest(),
                 "title": spec.title, "page_type": spec.page_type,
                 "canonical": spec.canonical, "h2": _h2_list(html_doc),
                 "prose_words": sum(len(b.split()) for b in page.blocks),
                 "sections": len(spec.sections), "sources": len(spec.sources),
                 "faq": len(spec.faq or []), "unique_blocks": page.unique_blocks}
        result.update({"written": after, "passed": True,
                       "verdict": {"passed": True, "severity": rv.get("severity"),
                                   "issues": len(rv.get("issues") or []),
                                   "ai_tells": len(rv.get("ai_tells") or []), "json": vpath}})
        result["attempts"].append({"n": attempt, "stage": "accepted", "passed": True,
                                   "severity": rv.get("severity"), "verdict_json": vpath})
        corpus.append(" ".join(page.blocks))
        print(f"  ✓ 통과 → {path} ({after['bytes']}B, md5={after['md5']})")
        print(f"    title: {orig['title']!r}\n        → {new_title!r}")
        break

    return result


def main(argv=None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    p = argparse.ArgumentParser(description="발행된 slug 를 같은 URL 로 재생성 (큐까지만, 발행·배포 없음)")
    p.add_argument("--slug", action="append", required=True, help="재생성할 slug (여러 번 지정 가능)")
    p.add_argument("--keyword", help="원 키워드 직접 지정(생략 시 published.json 에서 자동 해석)")
    p.add_argument("--max-attempts", type=int, default=2,
                   help="게이트·검수 반려 시 총 시도 횟수 상한(기본 2 — 무한 재작성 금지)")
    p.add_argument("--plan-only", action="store_true", help="LLM 호출 없이 계획(불변값·키워드)만 출력")
    p.add_argument("--out", default="", help="요약 JSON 경로(기본 dist/review/regen-<ts>.json)")
    a = p.parse_args(argv)

    import orchestrator
    cfg = orchestrator.load_config()

    if a.plan_only:
        for s in a.slug:
            o = read_original(s)
            print(json.dumps({"slug": s, "keyword": a.keyword or resolve_keyword(s),
                              "canonical": o["canonical"], "published_at": o["published_at"],
                              "cluster": o["cluster"], "title": o["title"], "md5": o["md5"],
                              "h2": o["h2"]}, ensure_ascii=False, indent=2))
        return 0

    backup_root = backup(a.slug)                        # ⚠️ 되돌릴 수 없으면 시작하지 않는다
    corpus, results = [], []
    for s in a.slug:
        results.append(regen_one(s, cfg, keyword=a.keyword, max_attempts=a.max_attempts, corpus=corpus))

    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    out = a.out or os.path.join(REVIEW_DIR, f"regen-{ts}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"at": ts, "backup": backup_root, "results": results},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    ok = sum(1 for r in results if r["passed"])
    print(f"\nregen: {ok}/{len(results)} 통과 → {QUEUE_DIR} (발행·배포 없음) / 요약 {out} / 백업 {backup_root}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
