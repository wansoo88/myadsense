"""observed.py — 제3자 공개 API **관측 데이터**(원저 데이터) 수집 (AUTOMATION.md §0 🟢 자유 자동화).

왜 이 모듈이 있나 (2026-07-25-31-content 실측):
    색인보류 9편의 소스 49개가 **100% 비교 당사자 벤더 자사 도메인**이었고 자체 측정·수치 관측이 9/9 전부 0이었다.
    Google 의 people-first 자가평가 질문 *"Does the content provide original information, reporting,
    research, or analysis?"* 에 측정된 답이 **아니오**였다(F12·F10). 표를 아무리 예쁘게 그려도
    두 벤더가 자기 사이트에서 하는 말을 재배열한 것이면 원저 데이터가 아니다.

이 모듈이 만드는 것:
    **우리가 직접 조회한 공개 기록** — 릴리스 이력(GitHub REST), 패키지 다운로드(npm registry),
    장애 이력(Statuspage v2), 이미지 pull 수(Docker Hub). 값이 제품마다 다르므로 페이지마다 다른 표가 나오고,
    "언제·어떤 엔드포인트로 관측했는가"가 표에 함께 렌더된다(F14 dateModified · F10 Trust).

⛔ 경계
    - 공개 REST 엔드포인트 **GET 만** 한다. 인증·쓰기·로그인·robots 우회 없음 → 트래픽/클릭 생성과 무관(F3 리스크 0).
    - **벤더 주장을 옮기지 않는다.** 여기서 나오는 값은 플랫폼(GitHub·npm·Statuspage)이 기록한 사건이다.
    - **없는 측정을 지어내지 않는다.** 한쪽이라도 값을 못 구한 축은 표에서 **통째로 뺀다**(빈 칸 금지 —
      빈 칸은 지금 Pricing 이 `confirm current rate` 로 비어 있는 것과 같은 실패다, ORDER 2026-07-28-42 ②).
    - 제품에 대한 부재 단정이 아니다: 저장소 지표는 **조회한 저장소 하나**의 기록이지 벤더 비공개 제품의 상태가 아니다.

⚠️ 모든 실패는 비치명적이다. 어떤 호출이 죽어도 빈 결과를 돌려주고 호출부(generator)는 표 없이 생성을 계속한다.
   테스트용 실패 주입: 환경변수 `ADSENSE_OBSERVED_FAIL=net`(엔드포인트를 미존재 호스트로) / `=raise`(즉시 예외).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("utilverse.info-research/1.0 (+https://utilverse.info/about/; "
      "public-API observation, read-only)")

# 실패 주입 시 쓰는 미존재 호스트 — 진짜 네트워크 실패 경로(DNS)를 타게 한다(가짜 예외가 아니다).
_UNREACHABLE = "https://observed-data-fail.invalid"
_MAX_BYTES = 6_000_000                 # 응답 상한(릴리스 목록은 릴리스 노트 때문에 수백 KB)
_DELAY = 0.25                          # 호출 간 예의상 간격
_COMMIT_WEEKS = 12                     # 커밋 빈도 관측 창(주) — 양쪽 동일 창으로 고정한다


def _fail_mode() -> str:
    return (os.environ.get("ADSENSE_OBSERVED_FAIL") or "").strip().lower()


# ── 공인 주소만 허용 (43-review 권고 P1 — SSRF 가드) ────────────────────────────────────────
# 왜: 상태페이지 호스트는 **모델이 준 문자열**이다. `localhost` · `169.254.169.254`(클라우드 메타데이터) ·
# 사내 호스트를 내놓으면 서버에서 도는 이 코드가 내부망을 GET 하게 된다. 공격자가 없어도, 내부 주소를
# 부를 이유가 아예 없으므로 문 앞에서 막는다. 검사 지점은 `_get_json` **한 곳**(모든 호출이 지나는 문).
_HOST_OK_CACHE: dict[str, bool] = {}


def _host_is_public(host: str) -> bool:
    """해석된 IP가 **전부** 공인일 때만 True. 해석 실패·사설/루프백/링크로컬/예약 = False."""
    import ipaddress
    import socket
    if not host:
        return False
    if host in _HOST_OK_CACHE:
        return _HOST_OK_CACHE[host]
    ok = False
    try:
        infos = socket.getaddrinfo(host, None)
        addrs = {i[4][0] for i in infos}
        ok = bool(addrs) and all(
            (lambda ip: ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local
                                              or ip.is_reserved or ip.is_multicast))(ipaddress.ip_address(a))
            for a in addrs)
    except Exception:                              # DNS 실패 등 — 모르면 부르지 않는다(fail-closed)
        ok = False
    _HOST_OK_CACHE[host] = ok
    return ok


def _url_allowed(url: str) -> bool:
    """https/http + 공인 호스트만. 스킴·호스트 파싱 실패도 거부."""
    try:
        p = urllib.parse.urlsplit(url)
    except Exception:
        return False
    return p.scheme in ("http", "https") and _host_is_public(p.hostname or "")


def _base(env_key: str, default: str) -> str:
    """엔드포인트 베이스. 환경변수로 덮어쓸 수 있다(⚠️ 실패 주입·테스트 전용, 운영에선 설정하지 않는다)."""
    if _fail_mode() in ("1", "net", "dns"):
        return _UNREACHABLE
    return os.environ.get(env_key) or default


# ── 응답 캐시 (레이트리밋 절약 — ORDER 2026-07-28-42 PM 회신 ⑤: 토큰 없이 60/시간 안에서 버틴다) ──
# 왜 필요한가: 검수 반려 → 재생성이면 `generate` 가 다시 불리고 관측도 **다시** 돈다(파일럿 2차 실측:
# 시도 2회 = GitHub 8회). 같은 엔드포인트를 몇 분 안에 두 번 때릴 이유가 없다.
# TTL 은 짧게(기본 6시간) — 캐시가 오래되면 '관측일'이 실제와 벌어진다. 그래서 관측 시각은 지금이 아니라
# **실제로 응답을 받은 시각 중 가장 오래된 것**으로 잡는다(collect 참조). 날짜를 부풀리지 않기 위해서다.
_CACHE_DIR = os.environ.get("ADSENSE_OBSERVED_CACHE_DIR") or os.path.join("dist", "cache", "observed")
try:
    _CACHE_TTL = max(0, int(os.environ.get("ADSENSE_OBSERVED_CACHE_TTL", "21600")))   # 6시간
except ValueError:
    _CACHE_TTL = 21600


def _cache_path(url: str) -> str:
    return os.path.join(_CACHE_DIR, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")


def _cache_read(url: str):
    """(payload, fetched_at) 또는 (None, None). 캐시 사고는 전부 무시하고 실호출로 넘어간다.

    🔴 **UTC 날짜가 바뀌면 캐시를 쓰지 않는다** (2026-08-01 검수 [coherence] 반려 실측).
    표 머리의 관측일은 '응답을 받은 시각 중 가장 오래된 것'인데, 캐시 히트와 실호출이 UTC 자정을
    사이에 두고 섞이면 **관측일보다 나중 날짜의 커밋**이 같은 표에 실린다. 실제 반려 사유:
    머리글은 `Measured on 2026-07-31` 인데 커밋 창은 `12 weeks to 2026-08-01`, 최근 커밋은 `2026-08-01`.
    서버 배치가 09:00 KST = **00:00 UTC** 라 이 경계를 매일 정확히 밟는다 → 상시 재발한다.
    날짜를 손보는 대신(그건 실제 사건 날짜를 조작하는 것이다) **한 표의 모든 값이 같은 UTC 날짜에서
    오도록** 캐시 수명을 그 날짜 안으로 제한한다. 캐시의 본래 목적(반려→재생성 시 몇 분 내 재조회
    절약)은 같은 UTC 날짜 안에서 그대로 살아 있다.
    """
    if _CACHE_TTL <= 0:
        return None, None
    try:
        p = _cache_path(url)
        with open(p, encoding="utf-8") as f:
            blob = json.load(f)
        at = float(blob.get("fetched_at") or 0)
        if time.time() - at > _CACHE_TTL:
            return None, None
        if (datetime.datetime.fromtimestamp(at, datetime.timezone.utc).date()
                != datetime.datetime.now(datetime.timezone.utc).date()):
            return None, None                    # UTC 날짜가 넘어갔다 — 섞으면 표 안에서 날짜가 어긋난다
        return blob.get("data"), at
    except Exception:
        return None, None


def _cache_write(url: str, data) -> None:
    if _CACHE_TTL <= 0:
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(url), "w", encoding="utf-8") as f:
            json.dump({"url": url, "fetched_at": time.time(), "data": data}, f, ensure_ascii=False)
    except Exception:
        pass                                     # 캐시는 최적화일 뿐 — 못 써도 동작은 같다


# ── HTTP (표준 라이브러리만, source_fetch.py 와 같은 방어 수준) ──────────────────────────────
def _get_json(url: str, timeout: int, calls: list) -> dict | list | None:
    """공개 JSON 엔드포인트 1회 GET(캐시 우선). 실패는 None — 호출 기록(calls)에 사유를 남긴다."""
    if not _url_allowed(url):                    # 사설·메타데이터·비HTTP 주소는 부르지 않는다(위 가드)
        calls.append({"url": url, "status": "blocked-non-public-host", "ms": 0, "bytes": 0,
                      "cached": False, "fetched_at": None})
        return None
    cached, at = _cache_read(url)
    if cached is not None:
        calls.append({"url": url, "status": 200, "ms": 0, "bytes": 0, "cached": True, "fetched_at": at})
        return cached
    t = time.time()
    rec = {"url": url, "status": None, "ms": 0, "bytes": 0, "cached": False, "fetched_at": t}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rec["status"] = resp.status
            raw = resp.read(_MAX_BYTES)
            rec["bytes"] = len(raw)
            data = json.loads(raw.decode("utf-8", "replace"))
        _cache_write(url, data)
    except urllib.error.HTTPError as e:
        rec["status"] = e.code
        data = None
    except Exception as e:                       # DNS·타임아웃·JSON 파손 등 전부 여기서 흡수
        rec["status"] = type(e).__name__
        data = None
    rec["ms"] = round((time.time() - t) * 1000)
    calls.append(rec)
    time.sleep(_DELAY)
    return data


def _parse_dt(s) -> datetime.datetime | None:
    """'2026-07-23T17:26:41Z' / '2026-07-22T09:42:22.960-07:00' → aware datetime. 실패 시 None."""
    if not isinstance(s, str) or not s:
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


# ── 수집기 (소스별) ───────────────────────────────────────────────────────────────────────
def _github(repo: str, timeout: int, calls: list, now, ctx: dict | None = None) -> dict:
    """저장소 활동 — 최신 릴리스·릴리스 속도(구간 명시)·오픈 이슈·마지막 커밋.

    ⚠️ 두 가지를 일부러 피한다.
      ① **"최근 90일 릴리스 수" 같은 고정 구간 집계** — 한 페이지(per_page=15)만 받으므로 릴리스가 잦은
         저장소에서는 구간이 잘려 과소집계된다(= 틀린 수치). 대신 **받은 릴리스가 실제로 덮는 구간을
         셀에 함께 적어** 속도를 낸다. 구간이 제품마다 달라도 값 자체는 정확하다.
      ② **"…한 지 N일" 류의 감쇠 지표** — 페이지는 한 번 렌더되고 그대로 서비스되므로 내일이면 틀린 값이
         된다. 날짜(절대값)만 싣는다.
    """
    api = _base("ADSENSE_OBSERVED_GITHUB_API", "https://api.github.com")
    out = {}
    meta = _get_json(f"{api}/repos/{urllib.parse.quote(repo)}", timeout, calls)
    if isinstance(meta, dict) and meta.get("full_name"):
        out["repo"] = meta["full_name"]
        if isinstance(meta.get("open_issues_count"), int):
            out["open_issues"] = meta["open_issues_count"]
        pushed = _parse_dt(meta.get("pushed_at"))
        if pushed:
            out["last_push_date"] = pushed.date().isoformat()
    # 커밋 빈도 — **태깅 관행과 무관한 활동 지표** (43c-review ② · PM 지시 2026-07-29).
    # 왜 릴리스 빈도를 버렸나: 실측에서 `supabase/supabase` 주 115.5커밋 vs `firebase/firebase-js-sdk`
    # 주 8.2커밋인데 태그된 릴리스는 0.1 vs 0.3 이었다 — **활동 순서가 뒤집힌다.** 각주가 약속한 구제책
    # ("커밋 날짜가 보여준다")도 두 날짜가 같으면 작동하지 않는다. 릴리스 태깅은 프로젝트 관행이지 활동이 아니다.
    # `/stats/participation` 은 **최근 52주 주간 커밋 수**를 준다 → 창이 양쪽 모두 동일해 시차 사고가 원천 봉쇄된다.
    part = _get_json(f"{api}/repos/{urllib.parse.quote(repo)}/stats/participation", timeout, calls)
    if not isinstance(part, dict) or not part.get("all"):
        part = _get_json(f"{api}/repos/{urllib.parse.quote(repo)}/stats/participation", timeout, calls)
    weeks = (part or {}).get("all") if isinstance(part, dict) else None
    if isinstance(weeks, list) and len(weeks) >= _COMMIT_WEEKS:
        window = [int(w) for w in weeks[-_COMMIT_WEEKS:] if isinstance(w, (int, float))]
        if len(window) == _COMMIT_WEEKS:
            end = now.date()
            out["commit_total"] = sum(window)
            out["commits_per_week"] = round(sum(window) / float(_COMMIT_WEEKS), 1)
            out["commit_weeks"] = _COMMIT_WEEKS
            out["commit_window_to"] = end.isoformat()
            out["commit_window_from"] = (end - datetime.timedelta(weeks=_COMMIT_WEEKS)).isoformat()
    rels = _get_json(f"{api}/repos/{urllib.parse.quote(repo)}/releases?per_page=15", timeout, calls)
    if isinstance(rels, list) and rels:
        dates, tags = [], []
        for r in rels:
            if not isinstance(r, dict) or r.get("draft"):
                continue
            d = _parse_dt(r.get("published_at"))
            if d:
                dates.append(d)
                tags.append(str(r.get("tag_name") or "").strip())
        if dates:
            out["latest_release_tag"] = tags[0] or "(untagged)"
            out["latest_release_date"] = dates[0].date().isoformat()
        if len(dates) >= 4:                       # 속도는 표본 4개(= 구간 3개) 이상일 때만
            span_days = (dates[0] - dates[-1]).days
            if span_days >= 1:
                out["release_count"] = len(dates)
                out["release_window_from"] = dates[-1].date().isoformat()
                out["release_window_to"] = dates[0].date().isoformat()
                out["release_span_days"] = span_days
                out["releases_per_week"] = round((len(dates) - 1) / (span_days / 7.0), 1)
    return out


_REPO_OWNER_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/.\s]+)", re.I)


def _npm(pkg: str, timeout: int, calls: list, now, ctx: dict | None = None) -> dict:
    """패키지 다운로드 — 최근 30일(레지스트리가 창을 함께 준다 = 구간이 잘릴 여지 없음).

    🔴 **소유 검증을 반드시 먼저 한다**(2026-07-28 실측으로 드러난 함정):
       `codeium` 은 200 을 주지만 실제로는 `npm/security-holder` 플레이스홀더(v0.0.1-security.1)이고,
       `windsurf` 도 v0.0.1·repository 없음이다. **엔드포인트가 200 이라는 사실은 그 패키지가 그 제품이라는
       증거가 아니다.** 이름만 같은 빈 패키지의 다운로드 수를 제품 지표로 실으면 그게 곧 허위 수치다.
       → 레지스트리 메타의 `repository` 가 (a) 존재하고 (b) security-holder 가 아니며
         (c) 저장소 식별자를 아는 경우 **같은 GitHub owner** 여야 채택한다.
    """
    api = _base("ADSENSE_OBSERVED_NPM_API", "https://api.npmjs.org")
    reg = _base("ADSENSE_OBSERVED_NPM_REGISTRY", "https://registry.npmjs.org")
    quoted = urllib.parse.quote(pkg, safe="@/")
    meta = _get_json(f"{reg}/{quoted}/latest", timeout, calls)
    repo = (meta or {}).get("repository") if isinstance(meta, dict) else None
    repo_url = repo.get("url") if isinstance(repo, dict) else (repo if isinstance(repo, str) else "")
    m = _REPO_OWNER_RE.search(repo_url or "")
    if not m or "security-holder" in (repo_url or "").lower():
        print(f"observed: npm '{pkg}' 소유 미확인(repository={repo_url!r}) — 이 축은 버린다")
        return {}
    expect = ((ctx or {}).get("github") or "").split("/")[0]
    if expect and m.group(1).lower() != expect.lower():
        print(f"observed: npm '{pkg}' 소유 불일치(repository owner={m.group(1)} ≠ {expect}) — 이 축은 버린다")
        return {}
    d = _get_json(f"{api}/downloads/point/last-month/{quoted}", timeout, calls)
    if not isinstance(d, dict) or not isinstance(d.get("downloads"), int):
        return {}
    return {"npm_package": pkg, "npm_downloads_30d": d["downloads"],
            "npm_window": f"{d.get('start')}~{d.get('end')}",
            "npm_repo": f"{m.group(1)}/{m.group(2)}"}


def _statuspage(host: str, timeout: int, calls: list, now, ctx: dict | None = None) -> dict:
    """공개 상태페이지의 **장애 이력** — 벤더 마케팅이 아니라 벤더가 스스로 기록한 사건 목록."""
    host = re.sub(r"^https?://", "", str(host or "")).strip("/")
    if not host:
        return {}
    base = _base("ADSENSE_OBSERVED_STATUS_BASE", f"https://{host}")
    if base == _UNREACHABLE:                       # 실패 주입 모드
        _get_json(base + "/api/v2/incidents.json", timeout, calls)
        return {}
    d = _get_json(f"{base}/api/v2/incidents.json", timeout, calls)
    inc = d.get("incidents") if isinstance(d, dict) else None
    if not isinstance(inc, list):
        return {}
    cutoff = now - datetime.timedelta(days=90)
    dates = [x for x in (_parse_dt(i.get("created_at")) for i in inc if isinstance(i, dict)) if x]
    if not dates:
        return {"status_host": host, "status_incidents_90d": 0, "status_incidents_exact": True}
    recent = [d0 for d0 in dates if d0 >= cutoff]
    # 응답이 90일보다 짧은 구간만 담고 있으면(목록 절단) 값은 '이상'이다 — 그대로 표기한다.
    exact = min(dates) < cutoff
    out = {"status_host": host, "status_incidents_90d": len(recent), "status_incidents_exact": exact,
           "status_last_incident": max(dates).date().isoformat()}
    return out


def _dockerhub(repo: str, timeout: int, calls: list, now, ctx: dict | None = None) -> dict:
    """공식 이미지 pull 수 — 셀프호스트 주제의 채택 신호(플랫폼 기록)."""
    api = _base("ADSENSE_OBSERVED_DOCKER_API", "https://hub.docker.com")
    if "/" not in str(repo or ""):
        return {}
    # 값은 모델이 준 문자열이다 — `a/../..` 로 다른 엔드포인트를 치지 못하게 인코딩한다(43-review 권고 P2).
    d = _get_json(f"{api}/v2/repositories/{urllib.parse.quote(repo, safe='/')}/", timeout, calls)
    if not isinstance(d, dict) or not isinstance(d.get("pull_count"), int):
        return {}
    return {"docker_repo": repo, "docker_pulls": d["pull_count"]}


_COLLECTORS = {"github": ("github", _github), "npm": ("npm", _npm),
               "statuspage": ("status", _statuspage), "dockerhub": ("docker", _dockerhub)}


# ── 대상(엔티티) 파싱 — 모델이 준 식별자 후보를 받되, 존재 여부는 **실호출로만** 인정한다 ────────────
DISCOVER_SYSTEM = (
    "You map a topic to public, machine-readable identifiers. You output only lines in the requested "
    "format — no prose, no markdown, no commentary. Never guess an identifier: omit a field you are not "
    "confident exists. A wrong identifier is worse than a missing one.")


def discover_user(topic: str, max_entities: int = 5) -> str:
    return (
        f'Topic: "{topic}"\n'
        f"List up to {max_entities} products this article will cover. One line each, pipe-separated:\n"
        "name | github:<owner/repo> | npm:<package> | status:<status-page-host> | docker:<namespace/repo>\n"
        "Rules:\n"
        "- 'name' is the product name a reader knows.\n"
        "- Include only the fields you are confident exist; drop the rest of the line's fields.\n"
        "- For a closed-source product, you may give the vendor's own official open-source CLI/SDK "
        "repository and package (that is what we will measure) — do not give a third party's repo.\n"
        "- status: only a public status page host (e.g. status.example.com).\n"
        "- No headers, no numbering, no extra text.")


_ID_RE = re.compile(r"^(github|npm|status|docker|kind|why)\s*:\s*(.+)$", re.I)
_KEY_BY_PREFIX = {"github": "github", "npm": "npm", "status": "statuspage", "docker": "dockerhub",
                  "kind": "kind", "why": "why"}
_IDENT_KEYS = ("github", "npm", "statuspage", "dockerhub")


def equivalent_kinds(targets: list) -> bool:
    """비교 등가성 — 선언된 `kind:` 가 서로 다르면 비교 자체가 성립하지 않는다 (43c-review ③).

    실측 사례(notion-vs-obsidian): 한쪽은 **JS SDK**(`makenotion/notion-sdk-js`), 다른 쪽은
    **데스크톱 앱 릴리스 피드**(`obsidianmd/obsidian-releases`)였고 npm 도 API 클라이언트 vs 플러그인
    타입정의였다. 값은 정확해도 **같은 것을 재고 있지 않다.** kind 를 선언했으면 CLI↔CLI · SDK↔SDK 만 허용한다.
    (선언이 없으면 강제하지 않는다 — 모르는 것을 아는 척하지 않는다.)
    """
    kinds = {str((t or {}).get("kind") or "").strip().lower() for t in (targets or [])}
    kinds.discard("")
    return len(kinds) <= 1


def parse_targets(text: str, *, max_entities: int = 5) -> list:
    """모델 출력 → [{'name':…, 'github':…, 'npm':…, …}]. 형식을 벗어난 줄은 조용히 버린다."""
    targets = []
    for line in (text or "").splitlines():
        line = line.strip().strip("-•").strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0].strip(" *`\"'")
        if not name or len(name) > 60 or name.lower().startswith(("name", "product")):
            continue
        t = {"name": name}
        for p in parts[1:]:
            m = _ID_RE.match(p)
            if not m:
                continue
            key = _KEY_BY_PREFIX[m.group(1).lower()]
            val = m.group(2).strip().strip("`\"'<>")
            if val and val.lower() not in ("none", "n/a", "-", "null"):
                t[key] = val
        if any(k in t for k in _IDENT_KEYS):       # kind/why 만 있는 줄은 관측할 게 없다
            targets.append(t)
        if len(targets) >= max_entities:
            break
    return targets


# ── 수집 ────────────────────────────────────────────────────────────────────────────────
def collect(targets: list, *, timeout: int = 10, max_entities: int = 5,
            sources: list | None = None) -> dict:
    """대상 목록 → 관측 결과. 개별 호출 실패는 그 칸만 비우고 계속한다(전체 실패 아님)."""
    if _fail_mode() == "raise":                    # 테스트용: 예상 못 한 예외 경로 확인
        raise RuntimeError("ADSENSE_OBSERVED_FAIL=raise — 실패 주입(테스트)")
    enabled = [s for s in (sources or list(_COLLECTORS)) if s in _COLLECTORS]
    now = datetime.datetime.now(datetime.timezone.utc)
    t0 = time.time()
    calls, entities = [], []
    for t in (targets or [])[:max_entities]:
        metrics, ids = {}, {}
        for key in enabled:
            field, fn = _COLLECTORS[key]
            val = t.get(key) if key in _IDENT_KEYS else None
            if not val:
                continue
            ids[key] = val
            try:
                metrics.update(fn(val, timeout, calls, now, t) or {})
            except Exception as e:                 # 수집기 하나가 죽어도 나머지는 계속
                calls.append({"url": f"{key}:{val}", "status": type(e).__name__, "ms": 0, "bytes": 0})
        if metrics:
            entities.append({"name": t.get("name"), "ids": ids, "metrics": metrics,
                             "kind": t.get("kind") or "", "why": t.get("why") or ""})
    # 관측 시각 = **실제로 응답을 받은 시각 중 가장 오래된 것**(캐시 히트 포함). '지금'으로 찍으면
    # 캐시된 값에 더 최근 날짜를 붙이는 셈이라 관측일이 사실보다 새것이 된다.
    stamps = [c["fetched_at"] for c in calls if c.get("status") == 200 and c.get("fetched_at")]
    seen_at = datetime.datetime.fromtimestamp(min(stamps), datetime.timezone.utc) if stamps else now
    cached_hits = sum(1 for c in calls if c.get("cached"))
    return {
        "observed_at": seen_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "observed_date": seen_at.date().isoformat(),
        "entities": entities, "calls": calls,
        "elapsed_ms": round((time.time() - t0) * 1000),
        "ok_calls": sum(1 for c in calls if c["status"] == 200), "total_calls": len(calls),
        "cached_calls": cached_hits,
    }


# ── 표 렌더 (renderer.py 를 고치지 않는다 — 기존 .tablewrap/.tbl 클래스를 그대로 쓴다) ────────────
def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _num(n) -> str:
    return f"{n:,}"


# (지표키, 행 제목, 출처계열, 셀 포맷터, **오독 주의**) — 행 = 지표, 열 = 제품.
#
# ⛔ **모든 제품이 값을 가진 행만** 렌더한다(ORDER 2026-07-28-42 ②): 빈 칸을 남기는 것은
#    지금 Pricing 섹션이 `confirm current rate` 로 비어 있는 것과 같은 실패다. 못 구한 축은 표에서 뺀다.
#
# 🔴 **`open_issues` 는 의도적으로 여기 없다** (43-review §1-3 · PM 지시 2026-07-28).
#    실측: `superfly/flyctl` 291 vs `railwayapp/cli` 75 = 3.9배인데, 같은 두 저장소의 stars 비가 2.9배·
#    저장소 크기 17배·연식 1.2배였다. 즉 이 값은 **결함 밀도가 아니라 유입량(인기·연식·분류 정책)의 함수**다.
#    승패 색이 있는 비교표 안에서는 어떤 각주를 붙여도 "결함이 4배 많은 제품"으로 읽힌다 = 경쟁사 부정 단정 리스크.
#    대체 축으로 **이슈 종료 시간 중앙값**(규모 정규화)을 실측해 봤으나 이것도 못 쓴다:
#    flyctl 중앙값 1,396일(스테일봇 일괄 종료) · railwayapp/cli 표본 1건 · vercel·netlify 표본 0건.
#    → 행 수가 줄어드는 쪽을 택했다(PM: "없으면 행 수가 줄어도 좋다"). 수집은 계속하되(감사 기록) **렌더하지 않는다.**
#
# 마지막 원소(주의 문구)는 그 행이 렌더될 때만 표 각주에 함께 실린다 — 오독 위험이 있는 지표는
# **자기 자신을 방어하는 문장을 데리고 다닌다**(각주가 특정 행만 면책하던 43-review §1-3 결함의 구조적 해소).
# 각 행: (지표키, 행 제목, 출처계열, 셀 포맷터, 오독 주의, **관측 창 추출기**)
# 창 추출기는 (시작, 끝) ISO 날짜 또는 None. None 이면 시점 사실이라 창 검사를 하지 않는다.
_ROWS = [
    ("latest_release_date", "Latest release", "repo",
     lambda m: (f'{m["latest_release_tag"]}, published {m["latest_release_date"]}'
                if m.get("latest_release_tag") else m["latest_release_date"]),
     "", None),
    ("commits_per_week", "Commits, weekly average", "repo",
     lambda m: f'{m["commits_per_week"]} a week ({_num(m["commit_total"])} commits in the '
               f'{m["commit_weeks"]} weeks to {m["commit_window_to"]})',
     "Commit counts include merges, dependency bumps and documentation changes, and a monorepo will "
     "always show more commits than a single-purpose repository, so this measures how busy the named "
     "repository is — not progress, quality, or how much of it reaches the product.",
     lambda m: (m.get("commit_window_from"), m.get("commit_window_to"))),
    ("last_push_date", "Most recent commit", "repo",
     lambda m: m["last_push_date"],
     "The commit date says the repository is being worked on, nothing about what changed.", None),
    ("npm_downloads_30d", "Downloads from npm, last 30 days", "npm",
     lambda m: f'{_num(m["npm_downloads_30d"])} ({m.get("npm_window")})',
     "Downloads count installs by machines — CI runs and mirrors included — so they track how widely a "
     "package is pulled, not how many people use the product.",
     lambda m: tuple((m.get("npm_window") or "~").split("~")[:2])),
    ("docker_pulls", "Docker Hub pulls, all time", "docker",
     lambda m: _num(m["docker_pulls"]),
     "Pull counts are cumulative since the image was published and include automated rebuilds, so an "
     "older image will show a larger number.", None),
    ("status_incidents_90d", "Status-page incidents, last 90 days", "status",
     lambda m: (_num(m["status_incidents_90d"]) if m.get("status_incidents_exact")
                else f'{_num(m["status_incidents_90d"])} or more'),
     "Incident counts reflect what each vendor chooses to post on its own status page and how finely it "
     "splits components; they are not an uptime measurement and are not comparable as one.", None),
]
_FAMILY_LABEL = {"repo": "GitHub REST API", "npm": "npm registry download API",
                 "docker": "Docker Hub API", "status": "public status-page API"}


def _windows_overlap(row, entities: list) -> bool:
    """이 행의 관측 창이 **제품끼리 겹치는가**. 창이 없는 지표(시점 사실)는 항상 True.

    🔴 왜 필요한가 (43c-review ② 실측): planetscale/neon 행이 neon 의 **2025년 7월 창**을
    planetscale 의 **2026년 7월 창** 옆에 나란히 놓고 `5.4 vs 3.5` 로 보여줬다. 각 값은 정확하지만
    **1년 시차를 비교로 제시한 것**이다. 사람이 매번 알아채기를 기대하지 말고 구조로 막는다:
    창이 겹치지 않으면 그 행은 **만들지 않는다**.
    """
    wf = row[5]
    if wf is None:
        return True
    spans = []
    for e in entities:
        try:
            a, b = wf(e["metrics"])
        except Exception:
            return False
        if not a or not b:
            return False
        spans.append((str(a), str(b)))
    lo = max(s for s, _ in spans)                  # 가장 늦은 시작
    hi = min(t for _, t in spans)                  # 가장 이른 끝
    return lo <= hi                                # ISO 날짜라 문자열 비교로 충분


# 비율·속도 지표 — **한쪽이 0이면 렌더하지 않는다** (43d-review R1, PM 지시 2026-07-29).
# 왜: 0 은 비율 비교를 퇴화시킨다("무한배 활발"). 게다가 0 이 찍힌 쪽은 어떤 각주를 붙여도
# "죽은 프로젝트"로 읽힌다 — 실제로는 그 저장소가 안정기라 커밋이 없을 뿐일 수 있다.
# ⚠️ **대칭 규칙**이라는 점이 핵심이다: 우리가 다루는 제품 쪽이 0이든 상대가 0이든 **똑같이** 빠진다.
#    그래서 "불리한 값을 골라 뺐다"는 논란이 구조적으로 성립하지 않는다.
# ⛔ 개수 지표에는 적용하지 않는다 — 장애 이력 `0건`은 퇴화가 아니라 **의미 있는 정보**다.
_RATIO_KEYS = {"commits_per_week"}


def live_rows(entities: list) -> list:
    """**모든** 엔티티가 값을 가졌고 · **관측 창이 겹치며** · **비율 지표에 0이 없는** 행만 남긴다."""
    if not entities:
        return []
    out = []
    for r in _ROWS:
        if not all(r[0] in e["metrics"] for e in entities):
            continue
        if not _windows_overlap(r, entities):
            print(f"observed: '{r[1]}' 행 제외 — 제품별 관측 창이 겹치지 않는다(시차 비교 방지)")
            continue
        if r[0] in _RATIO_KEYS and any(not e["metrics"].get(r[0]) for e in entities):
            print(f"observed: '{r[1]}' 행 제외 — 한쪽 값이 0이라 비율 비교가 성립하지 않는다(대칭 규칙)")
            continue
        out.append(r)
    return out


def distinct_rows(entities: list) -> list:
    """제품끼리 **값이 실제로 다른** 행만 — 전원이 같은 값인 행은 비교로서 아무것도 말하지 않는다."""
    out = []
    for row in live_rows(entities):
        fmt = row[3]
        try:
            vals = {fmt(e["metrics"]) for e in entities}
        except Exception:
            continue
        if len(vals) > 1:
            out.append(row)
    return out


def usable(result: dict, *, min_entities: int = 2, min_rows: int = 3,
           min_distinct_rows: int = 3) -> bool:
    """표를 붙일 만한가 (ORDER 2026-07-28-42 ② — "최소 3행 이상, 두 제품이 **서로 다른 값**을 갖는 축으로").

    두 조건을 따로 본다:
      · `min_rows`          — 양쪽 다 값이 있는 행 수(빈 칸이 없어야 하므로 이미 교집합이다)
      · `min_distinct_rows` — 그중 **값이 갈리는** 행 수. 전부 같은 값인 표는 지면만 차지한다.
    못 넘으면 표를 아예 붙이지 않는다 — 억지로 채우는 것이 ORDER 가 금지한 '지어낸 비교'다.
    """
    ents = result.get("entities") or []
    return (len(ents) >= min_entities and len(live_rows(ents)) >= min_rows
            and len(distinct_rows(ents)) >= min_distinct_rows)


def _endpoints(e: dict, families: set) -> list:
    """이 제품에서 **실제로 값을 낸 계열**의 엔드포인트 URL — 사람이 그대로 다시 호출할 수 있는 주소."""
    ids, out = e.get("ids") or {}, []
    gh = _base("ADSENSE_OBSERVED_GITHUB_API", "https://api.github.com")
    npm = _base("ADSENSE_OBSERVED_NPM_API", "https://api.npmjs.org")
    if "repo" in families and ids.get("github"):
        out.append(("GitHub REST API", f"{gh}/repos/{ids['github']}"))
        out.append(("GitHub releases API", f"{gh}/repos/{ids['github']}/releases?per_page=15"))
    if "npm" in families and ids.get("npm"):
        out.append(("npm registry", f"{npm}/downloads/point/last-month/{ids['npm']}"))
    if "status" in families and ids.get("statuspage"):
        out.append(("status page", f"https://{ids['statuspage']}/api/v2/incidents.json"))
    if "docker" in families and ids.get("dockerhub"):
        out.append(("Docker Hub", f"https://hub.docker.com/v2/repositories/{ids['dockerhub']}/"))
    return out


def _col_id(e: dict, families: set) -> str:
    """열 머리에 붙는 '무엇을 쟀는가' — 제품명 아래에 조회한 저장소·패키지를 그대로 밝힌다."""
    ids = e.get("ids") or {}
    bits = []
    if "repo" in families and ids.get("github"):
        bits.append(f'<a href="https://github.com/{_esc(ids["github"])}/releases" rel="noopener" '
                    f'target="_blank">{_esc(ids["github"])}</a>')
    if "npm" in families and ids.get("npm"):
        bits.append(f'<a href="https://www.npmjs.com/package/{_esc(ids["npm"])}" rel="noopener" '
                    f'target="_blank">{_esc(ids["npm"])}</a>')
    if "status" in families and ids.get("statuspage"):
        bits.append(f'<a href="https://{_esc(ids["statuspage"])}" rel="noopener" '
                    f'target="_blank">{_esc(ids["statuspage"])}</a>')
    if "docker" in families and ids.get("dockerhub"):
        bits.append(f'<a href="https://hub.docker.com/r/{_esc(ids["dockerhub"])}" rel="noopener" '
                    f'target="_blank">{_esc(ids["dockerhub"])}</a>')
    return ("<br><small>" + " · ".join(bits) + "</small>") if bits else ""


def _subject(result: dict) -> str:
    names = [str(e.get("name") or "").strip() for e in (result.get("entities") or [])]
    names = [n for n in names if n]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 2 else (names[0] if names else "")


def heading(result: dict) -> str:
    """제목은 **제품명 + 관측 계열**로 조립한다 — 글마다 달라야 새 템플릿 중복이 되지 않는다."""
    fams = {r[2] for r in live_rows(result.get("entities") or [])}
    what = "release record"
    if fams == {"repo"}:
        what = "release record"
    elif "status" in fams and "repo" in fams:
        what = "release and incident record"
    elif "npm" in fams and "repo" in fams:
        what = "release and download record"
    elif fams:
        what = "public record"
    return f"{_subject(result)}: the public {what} on {result.get('observed_date')}"


def table_html(result: dict, takeaway_html: str = "") -> str:
    """표 + 관측 방법 각주. **관측일·수집 방법·원본 URL 이 표와 같은 자리에** 렌더된다(F10·F14).

    구성: 행 = 지표(양쪽 다 값이 있는 것만) · 열 = 제품(머리에 조회 대상 저장소/패키지 링크).
    빈 칸은 만들지 않는다 — 값이 없는 축은 `live_rows()` 가 이미 통째로 뺐다.

    🔴 **불변식은 여기서도 막는다 — 해석 없는 표는 렌더하지 않는다** (43b-review ①, 이중 방어).
    generator 층에도 같은 가드가 있지만(`_ensure_takeaway`), 거기에만 두면 **이 모듈을 직접 부르는
    다른 호출부가 생기는 순간 무방비**가 된다. 정확히 그 형태의 사고가 이미 있었다 —
    ORDER 40 의 medium 보류가 `orchestrator` 에만 있고 `regen.py` 에 없어서, 재생성 9편이 사람 승인 없이
    큐로 갈 뻔했다(43-review §4-A). 규칙은 **데이터를 렌더하는 함수 자신**이 들고 있어야 한다.
    """
    ents = result.get("entities") or []
    rows = live_rows(ents)
    if not ents or not rows:
        return ""
    if not takeaway_ok(result, takeaway_html):
        print("observed: 해석 단락이 없거나 수치를 인용하지 않았다 — 표를 렌더하지 않는다"
              "(분석 없는 수치 블록은 이 파일럿이 막으려던 상태다)")
        return ""
    fams = {r[2] for r in rows}
    date = _esc(result.get("observed_date"))
    head = "".join(f'<th>{_esc(e.get("name"))}{_col_id(e, fams)}</th>' for e in ents)
    body, caveats = "", []
    for key, label, fam, fmt, caveat, _win in rows:
        show = f"{label} — {_FAMILY_LABEL[fam]}" if len(fams) > 1 else label
        cells = ""
        for e in ents:
            try:
                cells += f"<td>{_esc(fmt(e['metrics']))}</td>"
            except Exception:                      # 포맷 실패는 행 전체를 버린다(빈 칸을 만들지 않는다)
                cells = ""
                break
        if cells:
            body += f'<tr><td class="featc">{_esc(show)}</td>{cells}</tr>'
            if caveat:                             # 렌더된 행만 자기 주의 문구를 각주로 데려간다
                caveats.append(caveat)
    if not body:
        return ""
    table = ('<div class="tablewrap"><table class="tbl"><thead><tr>'
             f'<th class="feat">Measured on {date}</th>{head}</tr></thead>'
             f"<tbody>{body}</tbody></table></div>")
    take = (takeaway_html or "").strip()          # 모델의 해석 단락(있을 때만) — 표 다음, 각주 앞
    src = ""
    for e in ents:
        eps = _endpoints(e, fams)
        if eps:
            links = " · ".join(f'<a href="{_esc(u)}" rel="nofollow noopener" target="_blank">{_esc(n)}</a>'
                               for n, u in eps)
            # 무엇을 왜 골랐는지 산출물에 남긴다 (43c-review ③ 안전장치): 사람이 식별자를 고를 때
            # 그 사유를 함께 적게 하고, 독자도 "무엇을 서로 비교했는지" 를 페이지에서 바로 읽는다.
            why = str(e.get("why") or "").strip()
            src += (f'<li><strong>{_esc(e.get("name"))}</strong> — {links}'
                    + (f' · {_esc(why)}' if why else "") + "</li>")
    # 각주 = 방법 + **렌더된 행마다의 주의 문구**. 특정 행만 면책하고 나머지를 무방비로 두지 않는다
    # (43-review §1-3: 각주가 릴리스 속도만 보호하고 이슈 행은 한 줄도 보호하지 않던 결함).
    limits = " ".join(caveats)
    method = (
        f'<p class="footnote">Where these numbers come from: on {date} '
        f'({_esc(result.get("observed_at"))}) we called the public endpoints listed below and recorded '
        "what they returned. Nothing here is taken from either vendor's marketing pages, and anyone can "
        "repeat the same calls. Repository figures describe the named repository — for a closed-source "
        "platform that is its official CLI or SDK, not the platform itself. "
        + (f"What these figures do not tell you: {_esc(limits)} " if limits else "")
        + "None of them measures reliability, support or how either product feels to use.</p>")
    return f"{table}{take}{method}" + (f"<ul>{src}</ul>" if src else "")


def section(result: dict, takeaway_html: str = "") -> dict | None:
    """생성기가 spec.sections 에 그대로 넣을 섹션. `observed=True` 표식이 붙는다
    (표·각주는 산문 게이트·자가검수에서 제외 — 그 부분은 산문이 아니라 데이터다).

    `takeaway_html` = 모델이 쓴 **해석 한 단락**(스키마 필드 `observation_takeaway`, PM 승인 2026-07-28).
    표 바로 다음·방법 각주 앞에 놓는다 — 숫자를 본 직후 "이게 무슨 뜻이고 무엇은 아닌가"를 읽게.
    ⚠️ 이 단락은 **모델 산문**이므로 호출부가 산문 집계·자가검수에 따로 포함시킨다(generator 참조).
    """
    html = table_html(result, takeaway_html=takeaway_html)
    if not html:
        return None
    return {"heading": heading(result), "html": html, "observed": True}


def source_links(result: dict, *, max_links: int = 6) -> list:
    """읽는 사람이 직접 확인할 수 있는 **제3자 페이지** 링크(원시 API 주소가 아니라 사람이 보는 페이지).
    표에 실제로 실린 계열만 — 쓰지 않은 소스를 인용에 올리는 것은 허위 인용이다(16-content P2)."""
    ents = result.get("entities") or []
    fams = {r[2] for r in live_rows(ents)}
    out = []
    for e in ents:
        ids = e.get("ids") or {}
        if "repo" in fams and ids.get("github"):
            out.append({"title": f"GitHub — {ids['github']} releases",
                        "url": f"https://github.com/{ids['github']}/releases"})
        if "npm" in fams and ids.get("npm"):
            out.append({"title": f"npm — {ids['npm']}",
                        "url": f"https://www.npmjs.com/package/{ids['npm']}"})
        if "status" in fams and ids.get("statuspage"):
            out.append({"title": f"{e.get('name')} status history",
                        "url": f"https://{ids['statuspage']}/history"})
        if "docker" in fams and ids.get("dockerhub"):
            out.append({"title": f"Docker Hub — {ids['dockerhub']}",
                        "url": f"https://hub.docker.com/r/{ids['dockerhub']}"})
    return out[:max_links]


def figure_tokens(result: dict) -> list:
    """표에 실린 값에서 **본문에서 찾을 수 있는 식별 토큰**(버전 태그·수치·날짜)을 뽑는다.

    해석 단락이 진짜로 수치를 인용했는지 기계적으로 확인하기 위한 것이다 — 문장 전체를 비교하면
    표현이 조금만 달라도 못 찾고, 아무 숫자나 세면 연도·목차 번호에 걸린다.
    """
    ents = result.get("entities") or []
    toks = []
    for key, _label, _fam, fmt, _cav, _win in live_rows(ents):
        for e in ents:
            try:
                cell = fmt(e["metrics"])
            except Exception:
                continue
            for m in re.finditer(r"v?\d+(?:\.\d+){1,3}|\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:\.\d+)?\b", str(cell)):
                t = m.group(0)
                if len(t) >= 3 and t not in toks:
                    toks.append(t)
    return toks


def figure_index(result: dict) -> dict:
    """토큰 → {(제품명, 지표키)} 색인 — 어떤 수치가 **누구의 어떤 축**인지 되짚는다.

    `figure_tokens()` 는 "수치를 인용하기는 했는가"만 보면 되므로 토큰을 평평하게 모은다.
    이쪽은 **누구의 어떤 지표인지**가 필요하다: 산문이 A의 릴리스와 B의 커밋을 나란히 놓는
    교차지표 비교를 잡아내기 위한 것이다(ORDER 2026-08-01-45 PM 회신 2-b).

    왜 필요한가 (2026-08-01 실측): 표에는 창겹침(`_windows_overlap`)·등가성(`equivalent_kinds`)·
    비율대칭(`_RATIO_KEYS`) 세 규칙이 걸려 있는데 **산문에는 아무 가드가 없었다.** 그래서
    43c-review 가 표에서 막은 결함("값은 맞는데 같은 것을 재고 있지 않다")이 산문에서 그대로 재현됐다 —
    herdr 의 **마지막 커밋**(2026-08-01)을 Claude Squad 의 **마지막 릴리스**(v1.0.19, 2026-06-17)와
    나란히 놓은 문장. 두 문장 모두 개별적으로는 참이라 사실검사로는 걸리지 않는다.
    """
    ents = result.get("entities") or []
    idx: dict = {}
    for key, _label, _fam, fmt, _cav, win in live_rows(ents):
        for e in ents:
            name = str(e.get("name") or "").strip()
            if not name:
                continue
            try:
                cell = fmt(e["metrics"])
            except Exception:
                continue
            # 🔴 관측 창의 경계 날짜는 색인에서 뺀다. 그건 **측정값이 아니라 창의 메타데이터**이고,
            #    설계상 제품끼리 **같은 값**이다(커밋 창은 양쪽 동일 창으로 고정 — `_COMMIT_WEEKS`).
            #    빼지 않으면 그 공유 토큰 하나 때문에 두 제품이 '같은 지표를 인용했다'로 잡혀
            #    교차지표 비교가 **미탐지**된다(실측: 커밋창 끝 2026-08-01 이 herdr 의 마지막 커밋 날짜와
            #    같아서, 검수가 실제로 반려한 문장을 스캐너가 놓쳤다).
            skip = set()
            if win is not None:
                try:
                    skip = {str(x) for x in (win(e["metrics"]) or ()) if x}
                except Exception:
                    skip = set()
            for m in re.finditer(r"v?\d+(?:\.\d+){1,3}|\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:\.\d+)?\b", str(cell)):
                t = m.group(0)
                if len(t) >= 3 and t not in skip:
                    idx.setdefault(t, set()).add((name, key))
    return idx


def takeaway_request(result: dict) -> str:
    """해석 단락만 따로 받아오는 요청문(모델이 스키마 필드를 비워 왔을 때의 보충 호출)."""
    return (
        data_block(result) + "\n\n"
        "Write ONE paragraph of 3-5 sentences for a software comparison article, about exactly these "
        "figures. Requirements, all four:\n"
        f"  (a) quote at least TWO of the specific values above and carry the observation date "
        f"{result.get('observed_date')} with them;\n"
        "  (b) say what kind of record each quoted figure is — a public source repository, a package "
        "registry, a vendor's own status page — so the reader knows what was measured;\n"
        "  (c) say what the figures reasonably suggest for someone choosing between these tools;\n"
        "  (d) say plainly what they do NOT establish (not reliability, support, product quality, or how "
        "many people use either product).\n"
        "Compare like with like: if you set the products against each other, quote the SAME measurement for "
        "both (commit against commit, release against release). Pairing one product's release with the "
        "other's commit compares unlike things and fails review even though each half is true.\n"
        "Style: plain editorial prose in the site's neutral voice. No first-person claims of testing or "
        "using the products. Do not describe where anything sits on the page ('the table above/below'), "
        "do not mention prompts, APIs we were given, or how this page was produced beyond naming the "
        "public sources. No headings, no lists, no markdown.\n"
        "Output ONLY the paragraph wrapped in <p>…</p>.")


def takeaway_ok(result: dict, takeaway_html: str, *, min_figures: int = 2) -> bool:
    """해석 단락이 **실제로** 수치를 인용했는가 — 관측일 + 표의 값 토큰 2개 이상."""
    text = re.sub(r"<[^>]+>", " ", takeaway_html or "")
    if not text.strip():
        return False
    date = str(result.get("observed_date") or "")
    if date and date not in text:
        return False
    hits = {t for t in figure_tokens(result) if re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\w.])", text)}
    hits.discard(date)
    return len(hits) >= min_figures


def data_block(result: dict) -> str:
    """**사실만** — 관측 수치와 그 출처. 지시문은 한 줄도 넣지 않는다.

    🔴 왜 나눴나 (2026-07-28 파일럿 실측): `spec.grounding_context` 는 검수기 입력으로도 들어간다
    (`reviewer.review()` 가 근거 대조용으로 읽는다). 예전 판은 지시문까지 통째로 넣었더니
    **검수기가 우리 프롬프트 지시를 읽고 '그 지시를 이행했는가'를 판정 사유로 적었다**
    ("The observation-usage instruction asks one section to work with the API figures…" — 실제 판정문).
    검수기는 **글**을 판정해야지 우리 생성 지시의 준수 여부를 판정하면 안 된다. → 근거(사실)와 지시를 분리한다.

    ⚠️ 표에 실린 행(= 양쪽 다 값이 있는 축)만 넣는다. 한쪽만 가진 수치를 흘리면
    모델이 비대칭 비교("A는 X인데 B는 확인 못 했다")를 쓰고, 그게 30-content 반려 2건의 사유였다.
    """
    ents = result.get("entities") or []
    rows = live_rows(ents)
    if not ents or not rows:
        return ""
    lines = []
    for e in ents:
        m, ids = e["metrics"], (e.get("ids") or {})
        who = "; ".join(f"{k} {v}" for k, v in ids.items())
        bits = []
        for key, label, _fam, fmt, _caveat, _win in rows:
            try:
                bits.append(f"{label.lower()}: {fmt(m)}")
            except Exception:
                continue
        lines.append(f'- {e["name"]} [{who}]: ' + "; ".join(bits))
    return (
        f"=== OUR OWN OBSERVATION — collected by this site on {result.get('observed_date')} "
        f"({result.get('observed_at')}) ===\n"
        "These figures are NOT vendor claims. We queried the public GitHub REST API, the npm registry "
        "download API and public status-page APIs ourselves and recorded what they returned:\n"
        + "\n".join(lines))


def prompt_block(result: dict) -> str:
    """생성 프롬프트용 = 사실(`data_block`) + 사용 지시. **검수기에는 이걸 주지 않는다**(위 docstring)."""
    data = data_block(result)
    if not data:
        return ""
    return (
        data + "\n"
        "HOW TO USE THIS:\n"
        "- A table of exactly these figures, with the date and the endpoints we queried, is already placed "
        f'in the article as a section titled "{heading(result)}". Do NOT rebuild that table in your '
        "sections, and never point at where it sits on the page (no 'the table below/above') — refer to "
        "the findings themselves.\n"
        "- REQUIRED — fill the `observation_takeaway` field: one paragraph (3-5 sentences, plain "
        "<p>…</p>) that does the reader's thinking about these figures. All four of these, or it fails "
        "review: (a) quote at least TWO of the specific values above, each carrying the observation date "
        f"{result.get('observed_date')}; (b) say what kind of record each one is — a public source "
        "repository, a package registry, a vendor's own status page — so the reader knows what was "
        "measured; (c) say what the figures reasonably suggest for someone choosing between these tools; "
        "(d) say plainly what they do NOT establish (they are not a measure of reliability, support, "
        "product quality or how many people use either product). "
        "This paragraph is printed directly under the table, so do not introduce the table, do not repeat "
        "the whole table, and do not describe where anything sits on the page. Numbers that are printed "
        "and never engaged with are decoration — this field is what stops that.\n"
        "- COMPARE LIKE WITH LIKE. When you set the two products against each other in a sentence, use the "
        "SAME row for both — last commit against last commit, release against release, downloads against "
        "downloads. Never put one product's release date next to the other product's commit date (or any "
        "other mismatched pair): each half may be true while the comparison itself is not, and it is "
        "rejected in review. If a second measurement matters, give it for both products or state it on its "
        "own without framing it as the comparison.\n"
        "- Do NOT extrapolate beyond them: release cadence in a repository is not proof of product "
        "quality, downloads are not users, and an incident count is not an uptime figure. Do not turn "
        "them into a claim about what a vendor does or does not support.\n"
        "- These are API observations, not hands-on testing. Never write that we used, ran, installed or "
        "tested any of these products.")
