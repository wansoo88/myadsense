"""trend_scout.py — 트렌드 후보 자동 발굴 + 사전 검증 (읽기 전용 공개 API).

왜 만들었나 (2026-08-08): `trend_axis.candidates` 7개가 전부 소진/차단돼 신규 생성이 0편이 됐다.
  발행 5 / 죽음 2 — 죽은 이유가 발굴 부족이 아니라 **선별 실패**였다는 게 핵심이다:
    · `wandb/catnip` 저장소가 GitHub 에서 사라짐(404) → 관측표 불가로 매일 자동 드롭
    · `ccmanager vs claude squad` → 한쪽 문서가 얇아 비교표 공백 56%로 게이트 반복 탈락(LLM 3회 낭비)
  그래서 이 모듈의 무게중심은 '많이 찾기'가 아니라 **'못 쓸 후보를 후보 단계에서 떨어뜨리기'** 다.

무엇을 자동화하고 무엇을 하지 않나
  🟢 자동: 발굴(HN·GitHub 공개 API) · 사전 검증(저장소 생존·산문량·kind) · 짝 제안 · 다이제스트
  🔴 사람: **후보 확정**. 산출물은 제안일 뿐이고 `config/topics.yaml` 에 쓰는 것은 사람이다.
     ORDER 2026-08-01-45 ③ 이 '식별자는 사람이 미리 확정한다'로 정한 원칙을 그대로 지킨다
     (모델 자동 발견이 07-08 반려 루프의 원인이었다).
  ⛔ 안 함: 트래픽/클릭 생성, 자동 홍보, ToS 를 어기는 스크래핑(X·Reddit). AUTOMATION.md §0.

왜 `content.observed`·`content.source_fetch` 를 재사용하나
  · `observed._get_json` 은 SSRF 가드(공인 호스트만)와 응답 캐시를 이미 갖고 있다. 보안 장치를
    베껴 쓰면 한쪽만 고쳐질 때 드리프트가 난다 — 문은 하나로 둔다.
  · 산문량은 `source_fetch.fetch` 로 잰다. **생성기가 실제로 읽는 그 추출기**라야 측정이
    "이 후보로 글을 쓰면 표가 빌까"를 예측한다. 다른 잣대로 재면 예측이 안 된다.

실행: python engine/ingest/trend_scout.py            (설정: config/trend_scout.yaml)
      python engine/ingest/trend_scout.py --json     (다이제스트 없이 JSON 만)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:            # 단독 실행 시 engine/ 을 경로에 넣는다
    sys.path.insert(0, os.path.dirname(_HERE))

from content import observed, source_fetch            # noqa: E402  (경로 주입 뒤여야 한다)

CFG_PATH = "config/trend_scout.yaml"
TOPICS_PATH = "config/topics.yaml"
PUBLISHED_PATH = "engine/store/published.json"

# kind 추론 — 비교 등가성(`observed.equivalent_kinds`)이 요구하는 그 축이다.
# 서로 다른 kind 를 짝지으면 `trend_preflight` 가 후보를 버린다(실측: 8-01 herdr vs tmux 탈락).
# 완벽할 필요는 없다 — 사람이 확정하기 전 **묶음 제안**을 만드는 용도다.
_KIND_RULES = [
    ("containerized-agent-workspace", r"\b(container|sandbox|isolat\w+|devcontainer|worktree)\b"),
    ("terminal-agent-manager", r"\b(terminal|tmux|tui|session manager|multiplex\w*|pane)\b"),
    ("agent-ide", r"\b(ide|editor|vscode|workspace app|desktop app)\b"),
    ("agent-runtime", r"\b(runtime|orchestrat\w+|harness|framework|scheduler)\b"),
    ("agent-observability", r"\b(observab\w+|trace|telemetry|analytics|monitor\w*|eval)\b"),
    ("coding-assistant", r"\b(assistant|autocomplet\w+|copilot|completion)\b"),
]


def load_cfg(path: str = CFG_PATH) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _known() -> tuple[set, set]:
    """이미 다룬 것 — (발행 키워드, 후보에 등장한 github 저장소). 중복 제안을 막는다."""
    kws, repos = set(), set()
    try:
        with open(PUBLISHED_PATH, encoding="utf-8") as f:
            kws = {str(k).lower() for k in json.load(f)}
    except Exception:
        pass
    try:
        import yaml
        with open(TOPICS_PATH, encoding="utf-8") as f:
            t = (yaml.safe_load(f) or {}).get("trend_axis") or {}
        for c in (t.get("candidates") or []):
            kws.add(str(c.get("keyword") or "").lower())
            for e in (c.get("entities") or []):
                if e.get("github"):
                    repos.add(str(e["github"]).lower())
    except Exception:
        pass
    return kws, repos


def _guess_kind(text: str) -> str | None:
    t = (text or "").lower()
    for kind, pat in _KIND_RULES:
        if re.search(pat, t):
            return kind
    return None


def _gh_repo_from_url(url: str) -> str | None:
    """https://github.com/<owner>/<repo>… → 'owner/repo'. 그 외 None."""
    try:
        p = urllib.parse.urlsplit(url or "")
    except Exception:
        return None
    if p.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    seg = [s for s in p.path.split("/") if s]
    if len(seg) < 2:
        return None
    return f"{seg[0]}/{seg[1]}".removesuffix(".git")


# ── 발굴 ────────────────────────────────────────────────────────────────────────────
def from_hackernews(cfg: dict, calls: list) -> list:
    """Show HN = 신규 툴 런칭. Algolia 공식 API(무인증)."""
    s = (cfg.get("sources") or {}).get("hackernews") or {}
    if not s.get("enabled"):
        return []
    since = int((datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=int(s.get("days", 21)))).timestamp())
    out = []
    for q in (s.get("queries") or []):
        url = ("https://hn.algolia.com/api/v1/search?tags=show_hn"
               f"&query={urllib.parse.quote(q)}"
               f"&numericFilters=created_at_i>{since},points>{int(s.get('min_points', 8))}"
               "&hitsPerPage=20")
        data = observed._get_json(url, int((cfg.get("preflight") or {}).get("fetch_timeout", 12)), calls)
        for h in ((data or {}).get("hits") or []):
            repo = _gh_repo_from_url(h.get("url") or "")
            out.append({"source": "hackernews", "query": q,
                        "title": (h.get("title") or "").strip(),
                        "url": h.get("url") or "", "github": repo,
                        "signal": {"points": h.get("points"), "comments": h.get("num_comments")}})
    return out


def from_github(cfg: dict, calls: list) -> list:
    """신규 생성 + 별 급증 저장소. 정렬은 별 순 — '이미 검증된 신생'을 위로."""
    s = (cfg.get("sources") or {}).get("github") or {}
    if not s.get("enabled"):
        return []
    since = (datetime.date.today() - datetime.timedelta(days=int(s.get("days", 45)))).isoformat()
    out = []
    for q in (s.get("queries") or []):
        qs = f'"{q}" created:>{since} stars:>{int(s.get("min_stars", 60))}'
        url = ("https://api.github.com/search/repositories?q=" + urllib.parse.quote(qs)
               + f"&sort=stars&order=desc&per_page={int(s.get('per_query', 10))}")
        data = observed._get_json(url, int((cfg.get("preflight") or {}).get("fetch_timeout", 12)), calls)
        for r in ((data or {}).get("items") or []):
            out.append({"source": "github", "query": q,
                        "title": r.get("full_name") or "",
                        "url": r.get("html_url") or "", "github": r.get("full_name"),
                        "homepage": (r.get("homepage") or "").strip() or None,
                        "desc": r.get("description") or "",
                        "signal": {"stars": r.get("stargazers_count"),
                                   "created_at": (r.get("created_at") or "")[:10],
                                   "pushed_at": (r.get("pushed_at") or "")[:10]}})
    return out


# ── 사전 검증 ───────────────────────────────────────────────────────────────────────
def preflight(cand: dict, cfg: dict, calls: list) -> dict:
    """후보 하나를 실제로 불러보고 **쓸 수 있는지** 판정한다. 판정 사유를 함께 남긴다.

    두 가지만 본다 — 8월에 실제로 후보를 죽인 그 두 가지다:
      (1) 저장소가 살아 있는가        (catnip: 8-04 존재 → 8-06 404)
      (2) 산문이 충분한가            (얇으면 비교표 절반이 "확인 못 함"으로 채워진다)
    """
    pf = cfg.get("preflight") or {}
    timeout = int(pf.get("fetch_timeout", 12))
    repo = cand.get("github")
    out = {"repo_alive": None, "prose_chars": 0, "kind": None, "reasons": [], "usable": False}

    if not repo:
        out["reasons"].append("GitHub 저장소를 못 찾음(비교 관측 대상이 없다)")
        return out

    meta = observed._get_json(f"https://api.github.com/repos/{repo}", timeout, calls)
    out["repo_alive"] = bool(meta and meta.get("full_name"))
    if not out["repo_alive"]:
        out["reasons"].append(f"저장소 응답 없음/404 — {repo} (catnip 과 같은 소멸 사례)")
        if pf.get("require_repo_alive", True):
            return out
    else:
        out["stars"] = meta.get("stargazers_count")
        out["archived"] = bool(meta.get("archived"))
        out["homepage"] = (meta.get("homepage") or "").strip() or None
        out["license"] = ((meta.get("license") or {}) or {}).get("spdx_id")
        out["pushed_at"] = (meta.get("pushed_at") or "")[:10]
        out["topics"] = [str(t).lower() for t in (meta.get("topics") or [])]
        # HN 출신 후보는 `desc` 가 비어 있다(Algolia 는 제목·URL 만 준다) → 저장소 설명으로 채운다.
        # 이걸 안 하면 kind 추론이 제목만 보고 대부분 실패한다(실측 2026-08-08: 사용가능 8건 중 7건 실패).
        if not cand.get("desc"):
            cand["desc"] = meta.get("description") or ""
        if out["archived"]:
            out["reasons"].append("보관됨(archived) — 활동이 끝난 프로젝트")

    # 산문량 — **생성기가 실제로 읽는 추출기**로 잰다(다른 잣대로 재면 예측이 안 된다).
    try:
        doc = source_fetch.fetch(f"https://github.com/{repo}#readme",
                                 timeout=timeout, max_chars=20000)
        out["prose_chars"] = len(doc.get("text") or "")
    except Exception as e:
        out["reasons"].append(f"README 페치 실패 {type(e).__name__}")
    need = int(pf.get("min_prose_chars", 3000))
    if out["prose_chars"] < need:
        out["reasons"].append(f"산문 부족 {out['prose_chars']}자 < {need} — 비교표가 빈다")

    # kind 는 **저장소가 스스로 말한 것**(설명·토픽)까지 넣어 추론한다 — 제목만 보면 대부분 실패한다.
    out["kind"] = _guess_kind(" ".join([cand.get("title") or "", cand.get("desc") or "",
                                        " ".join(out.get("topics") or []), cand.get("homepage") or ""]))
    if not out["kind"]:
        # 규칙에 안 걸려도 버리지 않는다 — 저장소 토픽이 겹치면 짝 후보는 된다(pair 의 2차 신호).
        # ⚠️ 이건 kind 확정이 아니라 **제안 근거가 약하다**는 표시다. 사람이 kind 를 정한다.
        out["reasons"].append("kind 규칙 미매치 — 토픽 겹침으로만 짝 제안(사람이 축을 지정할 것)")
    out["usable"] = out["repo_alive"] and out["prose_chars"] >= need and not out.get("archived")
    return out


_MIN_SHARED_TOPICS = 2          # 2차 신호 임계 — 1개는 'ai' 처럼 흔해서 아무거나 묶인다


def pair(usable: list) -> list:
    """짝 제안. 1차는 kind 일치(등가성 축), 2차는 저장소 토픽 겹침.

    왜 2차가 필요한가(실측 2026-08-08): kind 규칙은 우리가 미리 적어둔 6개 축뿐이라
    새 유형이 나오면 전부 미매치가 된다. 그렇다고 규칙에 포괄어를 넣으면 무관한 것끼리 묶인다.
    저장소가 **스스로 붙인 토픽**이 겹치는지를 보면 규칙을 넓히지 않고도 새 유형을 잡는다.
    ⚠️ 2차는 근거가 약하다 — `basis` 로 구분해 표시하고, 축 확정은 사람이 한다.
    """
    pairs, seen = [], set()

    def _add(a, b, kind, basis, extra=""):
        key = tuple(sorted([a.get("github") or "", b.get("github") or ""]))
        if key in seen or not all(key):
            return
        seen.add(key)
        pairs.append({"kind": kind, "basis": basis, "note": extra,
                      "keyword": f"{_short(a)} vs {_short(b)}", "a": a, "b": b,
                      "prose": [a["pf"]["prose_chars"], b["pf"]["prose_chars"]],
                      "stars": [a["pf"].get("stars"), b["pf"].get("stars")]})

    ranked = sorted(usable, key=lambda c: -((c.get("pf") or {}).get("stars") or 0))
    by_kind: dict = {}
    for c in ranked:
        k = (c.get("pf") or {}).get("kind")
        if k:
            by_kind.setdefault(k, []).append(c)
    for kind, items in by_kind.items():                       # 1차 — kind 일치
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                _add(items[i], items[j], kind, "kind")

    for i in range(len(ranked)):                              # 2차 — 토픽 겹침
        for j in range(i + 1, len(ranked)):
            a, b = ranked[i], ranked[j]
            shared = set(a["pf"].get("topics") or []) & set(b["pf"].get("topics") or [])
            if len(shared) >= _MIN_SHARED_TOPICS:
                _add(a, b, (a["pf"].get("kind") or b["pf"].get("kind") or "?"),
                     "topics", "공통 토픽: " + ", ".join(sorted(shared)[:5]))
    return pairs


def _short(c: dict) -> str:
    """'owner/repo' → 'repo' (키워드용 짧은 이름)."""
    g = c.get("github") or c.get("title") or ""
    return g.split("/")[-1].replace("-", " ").strip() or g


# ── 실행 ────────────────────────────────────────────────────────────────────────────
def run(cfg: dict | None = None) -> dict:
    cfg = cfg or load_cfg()
    calls: list = []
    known_kw, known_repos = _known()

    raw = from_hackernews(cfg, calls) + from_github(cfg, calls)
    seen, cands = set(), []
    for c in raw:
        key = (c.get("github") or c.get("url") or "").lower()
        if not key or key in seen:
            continue
        if (c.get("github") or "").lower() in known_repos:      # 이미 후보/발행에 있는 저장소
            continue
        seen.add(key)
        cands.append(c)

    # 저장소가 없는 후보는 preflight 를 **통과할 수 없다**(관측표 대상이 없다). 상한을 먹기 전에 뺀다.
    # 실측 2026-08-08: 안 그랬더니 HN 랜딩페이지 16건이 24칸 중 절반 이상을 먹고 GitHub 후보가 밀렸다.
    no_repo = [c for c in cands if not c.get("github")]
    cands = [c for c in cands if c.get("github")]
    cap = int((cfg.get("preflight") or {}).get("max_candidates", 24))
    dropped_by_cap = max(0, len(cands) - cap)
    cands = cands[:cap]

    for c in cands:
        c["pf"] = preflight(c, cfg, calls)
    usable = [c for c in cands if c["pf"]["usable"]]
    pairs = [p for p in pair(usable) if p["keyword"].lower() not in known_kw]

    result = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
              "found": len(raw), "unique": len(seen), "no_repo": len(no_repo),
              "examined": len(cands),
              "dropped_by_cap": dropped_by_cap, "usable": len(usable),
              "pairs": pairs, "candidates": cands, "api_calls": len(calls)}
    out_path = ((cfg.get("output") or {}).get("json")) or "dist/research/trend_scout.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    result["_path"] = out_path
    return result


def digest(r: dict) -> str:
    L = []
    L.append(f"trend_scout: 수집 {r['found']}건 → 고유 {r['unique']} "
             f"→ 저장소 없음 {r.get('no_repo', 0)} 제외 → 검증 {r['examined']} "
             f"→ **사용 가능 {r['usable']}** (API {r['api_calls']}회)")
    if r.get("dropped_by_cap"):
        L.append(f"  ⚠️ 상한(max_candidates)으로 {r['dropped_by_cap']}건은 검증하지 않았다 — 조용한 절단 아님")
    L.append("")
    L.append("── 짝 제안 (같은 kind · 양쪽 다 문서 충분) " + "─" * 24)
    if not r["pairs"]:
        L.append("  없음 — 아래 '탈락 사유'를 보고 쿼리나 임계를 조정하라")
    for p in r["pairs"][:12]:
        tag = "kind 일치" if p.get("basis") == "kind" else "토픽 겹침(약)"
        # 포화 경고 — 우리 전략은 '초저포화 신생툴'이다(orca-vs-herdr 가 검색유입 53%를 낸 이유).
        # 대형 런칭은 이미 비교글이 넘쳐 우리 글이 묻힌다. ⚠️ 별 수는 포화의 **대리 지표일 뿐**이고
        # (herdr 도 24k 인데 비교글은 없었다) 진짜 판정은 '심층 비교글이 실제로 있는가' 검색이다 →
        # 그래서 자동으로 자르지 않고 사람에게 보여만 준다.
        hot = [s for s in p["stars"] if (s or 0) >= 10000]
        L.append(f"  · {p['keyword']}   [{p['kind']}] — {tag}"
                 + (f"  {p['note']}" if p.get("note") else "")
                 + ("   ⚠️ 대형 런칭 포함 — 비교글 포화 여부 검색 확인 필요" if hot else ""))
        L.append(f"      {p['a']['github']}  ⭐{p['stars'][0]}  산문 {p['prose'][0]:,}자")
        L.append(f"      {p['b']['github']}  ⭐{p['stars'][1]}  산문 {p['prose'][1]:,}자")
    L.append("")
    L.append("── 탈락 사유 " + "─" * 44)
    for c in r["candidates"]:
        pf = c.get("pf") or {}
        if pf.get("usable"):
            continue
        L.append(f"  ✗ {c.get('github') or c.get('url')}: {'; '.join(pf.get('reasons') or ['?'])}")
    L.append("")
    L.append("→ 확정은 사람이 한다. 쓸 짝을 골라 config/topics.yaml `trend_axis.candidates` 에 "
             "기존 스키마(name/kind/official_url/github/why)로 추가하라.")
    return "\n".join(L)


if __name__ == "__main__":
    res = run()
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(digest(res))
        print(f"\n(상세 {res['_path']})")
