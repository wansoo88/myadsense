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


# ── GitHub 쿼터 관리 ────────────────────────────────────────────────────────────────
# 🔴 왜 필요한가(실측 2026-08-08): 무인증 GitHub core 는 **시간당 60회**다. 후보 1건당 4회쯤 쓰는데
#    24건을 검증하면 그 자리에서 소진되고, 그 뒤 응답은 전부 **403** 이 된다.
#    그런데 첫 구현은 403 을 "저장소 응답 없음/404 — catnip 과 같은 소멸 사례"로 보고했다.
#    멀쩡한 `cloudflare/cloudflare-os` `vercel-labs/deepsec` 가 죽은 저장소로 찍혔다 —
#    이대로면 사람이 **살아 있는 후보를 지운다.** 쿼터 소진과 소멸은 반드시 구분해야 한다.
_COST_PER_CANDIDATE = 4        # /repos + _github 내부 호출(릴리스·participation 등)
_QUOTA_RESERVE = 5             # 여유분 — 소진 직전에 멈춘다


def install_github_auth() -> bool:
    """`GITHUB_TOKEN` 이 있으면 api.github.com 요청에만 Authorization 을 붙인다(60/시간 → 5,000/시간).

    왜 이렇게 하나: 인증 헤더는 `observed._get_json` 안에서 만들어지는데 그 파일은 지금 다른 에이전트가
    수정 중이라 손대지 않는다. `urllib.request.install_opener` 는 표준 확장 지점이라 남의 모듈 내부를
    건드리지 않고 헤더를 얹을 수 있다.
    ⚠️ 프로세스 전역이다 — 그래서 **호스트를 api.github.com 으로 좁히고**, 토큰이 없으면 아무것도
       설치하지 않는다(토큰 미설정 시 동작은 완전히 이전과 같다).
    ⚠️ 토큰 경로는 아직 실측 안 됨(이 환경에 토큰이 없다). 무토큰 경로만 검증됐다.
    """
    import urllib.request
    tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not tok:
        return False

    class _Auth(urllib.request.BaseHandler):
        def http_request(self, req):
            if (req.host or "").lower().endswith("api.github.com"):
                req.add_unredirected_header("Authorization", "Bearer " + tok)
            return req
        https_request = http_request

    urllib.request.install_opener(urllib.request.build_opener(_Auth()))
    return True


class RateLimited(RuntimeError):
    """GitHub 쿼터 소진. 판정을 계속하면 살아 있는 저장소가 죽은 것으로 찍힌다 → 즉시 멈춘다."""


def gh_quota(timeout: int = 10) -> tuple[int, str]:
    """남은 core 쿼터와 리셋 시각. `/rate_limit` 자체는 쿼터를 **소비하지 않는다**."""
    import urllib.request
    try:
        req = urllib.request.Request("https://api.github.com/rate_limit",
                                     headers={"User-Agent": observed.UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            core = (json.loads(resp.read().decode("utf-8", "replace")).get("resources") or {}).get("core") or {}
        return int(core.get("remaining", 0)), datetime.datetime.fromtimestamp(
            int(core.get("reset", 0))).strftime("%H:%M")
    except Exception:
        return -1, "?"          # 모르면 -1 — 호출부가 '모름'으로 취급한다


def _last_status(calls: list):
    return calls[-1].get("status") if calls else None


# ── 근거량 측정 (크롬 제외) ─────────────────────────────────────────────────────────
# 🔴 왜 raw 를 쓰나(실측 2026-08-08, CONTENT 검증 + OPS 재확인): `source_fetch` 로 github.com 페이지를
#    뽑으면 앞 1,105~3,447자가 **GitHub 사이트 크롬**(상단 내비·Solutions·Resources 메뉴)이다.
#    그래서 README 가 비어 있어도 3,000자 임계를 통과했다 — 측정이 메뉴를 재고 있었다.
#    raw.githubusercontent 는 크롬이 0이라 **README 실물**만 잰다.
_README_NAMES = ("README.md", "readme.md", "README.rst", "README", "docs/README.md")


def readme_chars(repo: str, timeout: int) -> int:
    """저장소 README 실물 길이(크롬 0). 못 찾으면 0."""
    import urllib.request
    for name in _README_NAMES:
        url = f"https://raw.githubusercontent.com/{repo}/HEAD/{name}"
        if not observed._url_allowed(url):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": observed.UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return len(resp.read(2_000_000).decode("utf-8", "replace"))
        except Exception:
            continue
    return 0


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

    무엇을 보나 — 8월에 실제로 후보를 죽인 것들이다(2026-08-08 CONTENT 52 보고 + OPS 재확인):
      (1) 저장소 생존              catnip: 8-04 존재 → 8-06 404
      (2) **릴리스 1건 이상**       github 단독 엔티티가 만들 수 있는 관측표 행은 릴리스일·주간커밋·
          최종커밋 **3개뿐**이다. 하나라도 비면 `observed.usable(min_rows=3)` 가 수학적으로 불가능하다.
          갓 만든 저장소는 태그를 안 단다 — 스카우트 1순위였던 loopkit 이 정확히 이 사유로 죽었다.
      (3) 근거량(크롬 제외)         README 실물 + 공식 사이트. ⚠️ '두꺼운가'가 아니라 짝의 **비대칭**이
          진짜 예측변수다(pair 에서 본다). 성공작 herdr 의 README 는 2,771자로 제일 얇았다.

    판정은 `observed._github` 을 **그대로 호출**해서 한다 — 표를 만드는 그 코드로 재야 예측이 맞는다.
    """
    pf = cfg.get("preflight") or {}
    timeout = int(pf.get("fetch_timeout", 12))
    repo = cand.get("github")
    out = {"repo_alive": None, "readme_chars": 0, "site_chars": 0, "grounding_chars": 0,
           "kind": None, "reasons": [], "usable": False}

    if not repo:
        out["reasons"].append("GitHub 저장소를 못 찾음(비교 관측 대상이 없다)")
        return out

    meta = observed._get_json(f"https://api.github.com/repos/{repo}", timeout, calls)
    st = _last_status(calls)
    if st in (403, 429):                           # 쿼터 소진 — '소멸'과 절대 섞지 않는다(위 주석)
        raise RateLimited(f"{repo} 검증 중 GitHub {st}")
    out["repo_alive"] = bool(meta and meta.get("full_name"))
    if not out["repo_alive"]:
        out["reasons"].append(f"저장소 {st} — {repo}"
                              + (" (catnip 과 같은 소멸 사례)" if st == 404 else " (원인 불명 — 재확인 필요)"))
        if pf.get("require_repo_alive", True):
            return out
        meta = {}

    out["stars"] = meta.get("stargazers_count")
    out["archived"] = bool(meta.get("archived"))
    out["homepage"] = (meta.get("homepage") or "").strip() or None
    out["license"] = ((meta.get("license") or {}) or {}).get("spdx_id")
    out["topics"] = [str(t).lower() for t in (meta.get("topics") or [])]
    if not cand.get("desc"):                       # HN 출신은 desc 가 비어 있다 → 저장소 설명으로 채운다
        cand["desc"] = meta.get("description") or ""
    if out["archived"]:
        out["reasons"].append("보관됨(archived) — 활동이 끝난 프로젝트")

    # 관측표 성립 여부 — 표를 만드는 그 함수로 직접 잰다(재구현하면 어긋난다)
    m = observed._github(repo, timeout, calls, datetime.datetime.now(datetime.timezone.utc)) or {}
    if _last_status(calls) in (403, 429):
        raise RateLimited(f"{repo} 관측 검증 중 GitHub {_last_status(calls)}")
    out["latest_release_date"] = m.get("latest_release_date")
    out["last_push_date"] = m.get("last_push_date")
    out["commits_per_week"] = m.get("commits_per_week")
    missing = [n for n, k in (("릴리스", "latest_release_date"), ("주간커밋", "commits_per_week"),
                              ("최종커밋", "last_push_date")) if not m.get(k)]
    if missing and pf.get("require_releases", True):
        out["reasons"].append(f"관측표 행 부족 — {'·'.join(missing)} 없음 "
                              f"(github 단독은 3행뿐이라 하나만 비어도 min_rows=3 불가)")

    out["readme_chars"] = readme_chars(repo, timeout)
    if out["homepage"]:
        try:
            out["site_chars"] = len((source_fetch.fetch(out["homepage"], timeout=timeout,
                                                        max_chars=20000).get("text") or ""))
        except Exception:
            pass
    out["grounding_chars"] = out["readme_chars"] + out["site_chars"]
    need = int(pf.get("min_grounding_chars", 3000))
    if out["grounding_chars"] < need:
        out["reasons"].append(f"근거 부족 {out['grounding_chars']:,}자 < {need:,} "
                              f"(README {out['readme_chars']:,} + 사이트 {out['site_chars']:,}, 크롬 제외)")

    out["kind"] = _guess_kind(" ".join([cand.get("title") or "", cand.get("desc") or "",
                                        " ".join(out.get("topics") or []), cand.get("homepage") or ""]))
    if not out["kind"]:
        out["reasons"].append("kind 규칙 미매치 — 토픽 겹침으로만 짝 제안(사람이 축을 지정할 것)")
    out["usable"] = bool(out["repo_alive"] and not out.get("archived")
                         and out["grounding_chars"] >= need
                         and not (missing and pf.get("require_releases", True)))
    return out


_MIN_SHARED_TOPICS = 2          # 2차 신호 임계 — 1개는 'ai' 처럼 흔해서 아무거나 묶인다


def pair(usable: list, cfg: dict | None = None) -> list:
    """짝 제안. 1차는 kind 일치(등가성 축), 2차는 저장소 토픽 겹침. 짝 단위 결격은 함께 표시한다.

    짝 단위로 봐야만 보이는 것 두 가지 (2026-08-08 CONTENT 52 실측):
      · **비대칭** — 두께가 아니라 한쪽이 상대의 몇 배인가가 진짜 예측변수다.
        성공작 herdr 의 README 는 2,771자로 제일 얇았고, '얇아서 죽었다'던 claude-squad 는 5,162자다.
        `ccmanager vs claude squad` 를 죽인 건 2.6배 격차였다 → 목표 1.5배 이내.
      · **최종커밋일 동일** — 관측표 행이 3개뿐인데 `min_distinct_rows` 를 채우려면 셋 다 값이 갈려야
        한다. 활발한 두 저장소가 같은 날 푸시하면 그날은 미성립이다(영구 결격 아님 — 날짜 문제라
        내일이면 풀린다. 그래서 버리지 않고 경고만 단다).
    """
    cfg = cfg or {}
    max_asym = float((cfg.get("preflight") or {}).get("max_asymmetry", 1.5) or 0)
    pairs, seen = [], set()

    def _add(a, b, kind, basis, extra=""):
        key = tuple(sorted([a.get("github") or "", b.get("github") or ""]))
        if key in seen or not all(key):
            return
        seen.add(key)
        ga, gb = a["pf"]["grounding_chars"], b["pf"]["grounding_chars"]
        asym = (max(ga, gb) / min(ga, gb)) if min(ga, gb) else 999.0
        blocks = []
        # 🔴 토픽 겹침은 "둘 다 AI 에이전트와 관련 있다"는 뜻이지 "같은 일을 한다"가 아니다.
        #    실측 2026-08-08: loop-engineering(패턴·점수 툴킷) 과 wigolo(웹검색 MCP 서버)가
        #    공통 토픽 claude·mcp 로 묶여 ✓ 를 받았다. 기계 검사(릴리스·비대칭·등가성)는 전부
        #    통과하는데 **독자가 둘 사이에서 고를 일이 없는** 짝이었다 — 지어낸 비교가 된다.
        #    그래서 토픽 기반은 결코 통과 표시를 주지 않는다. 사람이 '무슨 일을 하는가'를 읽고 정한다.
        if basis == "topics":
            blocks.append("토픽만 겹침 — 같은 일을 하는지 **설명을 읽고** 확인하라(기계로는 판별 불가)")
        if max_asym and asym > max_asym:
            blocks.append(f"비대칭 {asym:.1f}배 > {max_asym}배 (한쪽 열이 빈다)")
        if a["pf"].get("last_push_date") and a["pf"]["last_push_date"] == b["pf"].get("last_push_date"):
            blocks.append(f"최종커밋일 동일({a['pf']['last_push_date']}) — 오늘은 구별행 부족(날짜 문제, 내일 풀림)")
        pairs.append({"kind": kind, "basis": basis, "note": extra, "asym": round(asym, 2),
                      "blocks": blocks, "ok": not blocks,
                      "keyword": f"{_short(a)} vs {_short(b)}", "a": a, "b": b,
                      "grounding": [ga, gb], "stars": [a["pf"].get("stars"), b["pf"].get("stars")]})

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
    pairs.sort(key=lambda p: (not p["ok"], p["basis"] != "kind", p["asym"]))
    return pairs


def _short(c: dict) -> str:
    """'owner/repo' → 'repo' (키워드용 짧은 이름)."""
    g = c.get("github") or c.get("title") or ""
    return g.split("/")[-1].replace("-", " ").strip() or g


# ── 실행 ────────────────────────────────────────────────────────────────────────────
def run(cfg: dict | None = None) -> dict:
    cfg = cfg or load_cfg()
    # 폐기된 키가 남아 있으면 시끄럽게 알린다 — 값을 바꿔도 동작이 안 변하는 '장식 설정'을 만들지 않는다.
    if "min_prose_chars" in (cfg.get("preflight") or {}):
        print("⚠️ config/trend_scout.yaml: `min_prose_chars` 는 폐기됐다(측정 대상이 바뀜 — GitHub 크롬 포함). "
              "`min_grounding_chars` 로 바꿔라. 지금은 무시된다.")
    authed = install_github_auth()
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
    # 쿼터 안에서만 검증한다 — 넘기면 403 이 오고, 403 을 '소멸'로 오독하면 살아 있는 후보를 지운다.
    cap = int((cfg.get("preflight") or {}).get("max_candidates", 24))
    remaining, reset_at = gh_quota()
    quota_note = "" if authed else ""
    if not authed and 0 <= remaining < 40:
        quota_note = (f"GITHUB_TOKEN 미설정 → 시간당 60회 제한. 지금 {remaining}회 남음(리셋 {reset_at}). "
                      f"토큰(읽기 전용 public_repo 불필요, 스코프 없이도 5,000/시간)을 넣으면 한 번에 다 돈다.")
    if remaining >= 0:
        affordable = max(0, (remaining - _QUOTA_RESERVE) // _COST_PER_CANDIDATE)
        if affordable < cap:
            quota_note = ((quota_note + " / ") if quota_note else "") + (
                          f"GitHub 쿼터 {remaining} 남음(리셋 {reset_at}) → "
                          f"이번 실행은 {affordable}건만 검증한다(설정 상한 {cap})")
            cap = affordable
    dropped_by_cap = max(0, len(cands) - cap)
    cands = cands[:cap]

    stopped = ""
    checked = []
    for c in cands:
        try:
            c["pf"] = preflight(c, cfg, calls)
        except RateLimited as e:
            stopped = (f"{e} — 쿼터 소진으로 검증 중단. 남은 {len(cands) - len(checked)}건은 "
                       f"판정하지 않았다(‘소멸’ 아님). 리셋 {gh_quota()[1]} 이후 재실행하라.")
            break
        checked.append(c)
    cands = checked
    usable = [c for c in cands if c["pf"]["usable"]]
    pairs = [p for p in pair(usable, cfg) if p["keyword"].lower() not in known_kw]

    result = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
              "found": len(raw), "unique": len(seen), "no_repo": len(no_repo),
              "examined": len(cands),
              "dropped_by_cap": dropped_by_cap, "usable": len(usable),
              "quota_note": quota_note, "stopped": stopped,
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
    if r.get("quota_note"):
        L.append(f"  ⚠️ {r['quota_note']}")
    if r.get("stopped"):
        L.append(f"  🔴 {r['stopped']}")
    if r.get("dropped_by_cap"):
        L.append(f"  ⚠️ 상한(max_candidates)으로 {r['dropped_by_cap']}건은 검증하지 않았다 — 조용한 절단 아님")
    L.append("")
    L.append("── 짝 제안 (양쪽 관측표 성립 · 근거 충분) " + "─" * 20)
    L.append("   ⚠️ ✓ 는 **기계 검사** 통과일 뿐이다 — 릴리스·비대칭·최종커밋일·kind 규칙.")
    L.append("      '독자가 이 둘 사이에서 고르는가'는 기계가 못 잰다. 아래 설명(└)을 읽고 사람이 정한다.")
    if not r["pairs"]:
        L.append("  없음 — 아래 '탈락 사유'를 보고 쿼리나 임계를 조정하라")
    for p in r["pairs"][:12]:
        tag = "kind 일치" if p.get("basis") == "kind" else "토픽 겹침(약)"
        mark = "✓" if p.get("ok") else "△"
        # 포화 경고 — 우리 전략은 '초저포화 신생툴'이다(orca-vs-herdr 가 검색유입 53%를 낸 이유).
        # ⚠️ 별 수는 포화의 **대리 지표일 뿐**이고(herdr 도 24k 인데 비교글은 없었다) 진짜 판정은
        #    '심층 비교글이 실제로 있는가' 검색이다 → 자동으로 자르지 않고 사람에게 보여만 준다.
        hot = [x for x in p["stars"] if (x or 0) >= 10000]
        L.append(f"  {mark} {p['keyword']}   [{p['kind']}] — {tag} · 비대칭 {p['asym']}배"
                 + (f"  {p['note']}" if p.get("note") else "")
                 + ("   ⚠️ 대형 런칭 포함 — 비교글 포화 여부 검색 확인 필요" if hot else ""))
        for blk in p.get("blocks") or []:
            L.append(f"      ⛔ {blk}")
        for side in ("a", "b"):
            c = p[side]
            pf = c["pf"]
            L.append(f"      {c['github']}  ⭐{pf.get('stars')}  근거 {pf['grounding_chars']:,}자"
                     f"(README {pf['readme_chars']:,}+사이트 {pf['site_chars']:,})"
                     f"  릴리스 {pf.get('latest_release_date') or '없음'}")
            # 🔴 '무엇을 하는 툴인가'를 반드시 함께 보여준다. 이 줄이 없어서 별·산문·릴리스만 보고
            #    서로 대체재가 아닌 짝을 고를 뻔했다(2026-08-08). 비교글은 **독자가 둘 중 하나를
            #    고르는 상황**에서만 성립한다 — 그 판단에 필요한 유일한 정보가 이 한 줄이다.
            L.append(f"         └ {(c.get('desc') or '(설명 없음)')[:150]}")
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
