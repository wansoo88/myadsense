"""generator.py — 콘텐츠 초안 생성 (AUTOMATION.md §2 GENERATE).

두 모드:
  - fixture (드라이런/오프라인 기본): API 키 없이 구조 완성된 초안 생성 → design.md 렌더 검증용.
  - api: ANTHROPIC_API_KEY 있으면 Claude 로 실제 생성(여기선 골격만, 운영 시 확장).
생성물은 renderer 로 HTML 렌더 후 quality_gate.Page 로 변환 → 게이트 통과해야 발행 큐.
순수 템플릿 양산 방지: 페이지마다 unique_blocks(비교표·가격표·핸즈온) 필수.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime
import json
import os
import re

from content import renderer, source_fetch
from content.quality_gate import Page


@dataclass
class ContentSpec:
    slug: str
    title: str
    dek: str
    page_type: str                     # comparison | listicle | guide | alternatives
    breadcrumb: list                   # [(name, url), ...]
    author: str
    published_at: str
    updated_at: str | None
    intro_html: str
    sections: list                     # [{"heading","html"}]
    sources: list                      # [{"title","url"}]
    canonical: str = ""
    author_bio: str = ""
    reading_time: int = 6
    comparison: dict | None = None      # {"a","b","rows":[{"feature","a","b","winner"}]}
    pricing: list | None = None         # [{"name","price","features":[...],"cta":{...}}]
    pros_cons: list | None = None       # [{"name","pros":[...],"cons":[...]}]
    verdict_html: str | None = None
    related: list = field(default_factory=list)
    kicker: str = ""                    # eyebrow 라벨(없으면 renderer 가 page_type 로 유도)
    tldr_html: str | None = None        # 상단 'At a glance' 한 줄 결론
    feature_matrix: dict | None = None  # {"a","b","rows":[{"label","a","b"(✓/△/✗),"note"}]}
    cluster: str | None = None          # topics.yaml 클러스터 id(카테고리 허브 그룹핑용)
    grounding_context: str = ""         # 생성 시 주입한 공식 소스 텍스트(검수 사실대조용, 렌더 미노출)
    faq: list = field(default_factory=list)  # [{"q","a"}] — People-Also-Ask 대응 + FAQPage 스키마
    selfcheck_flags: list = field(default_factory=list)  # 생성측 자가검수 잔여 경고(로그용, 렌더 미노출)


def _strip(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def spec_to_page(spec: ContentSpec, html_doc: str) -> Page:
    blocks = [_strip(spec.intro_html)] + [_strip(s["html"]) for s in spec.sections]
    if spec.verdict_html:
        blocks.append(_strip(spec.verdict_html))
    for f in (spec.faq or []):                 # FAQ 답변도 실질 산문으로 집계
        blocks.append(_strip(f.get("a", "")))
    unique = []
    if spec.comparison:
        unique.append("comparison-table")
    if spec.pricing:
        unique.append("pricing-table")
    if spec.pros_cons:
        unique.append("pros-cons")
    return Page(
        slug=spec.slug, title=spec.title, html=html_doc,
        blocks=[b for b in blocks if b], unique_blocks=unique,
        sources=[s["url"] for s in spec.sources], author=spec.author,
        published_at=spec.published_at, updated_at=spec.updated_at, has_schema_org=True,
    )


def generate(topic: str, content_cfg: dict, *, force_fixture: bool = False,
             draft: bool = False, cluster: str | None = None, feedback: str | None = None):
    """topic(시드 키워드) → (spec, page). page.html 은 design.md 렌더 결과.
    feedback: 이전 시도의 게이트/검수 거절 사유(있으면 재생성 시 고쳐야 할 지시로 주입)."""
    spec = _resolve_provider(topic, content_cfg, force_fixture, feedback=feedback)
    if cluster:
        spec.cluster = cluster                # 카테고리 허브 그룹핑용(렌더 시 meta로 기록)
    html_doc = renderer.render(spec, draft=draft)
    return spec, spec_to_page(spec, html_doc)


def _resolve_provider(topic: str, content_cfg: dict, force_fixture: bool,
                       feedback: str | None = None) -> ContentSpec:
    """provider 선택: api(키) | claude_cli(구독 헤드리스) | auto | fixture(오프라인)."""
    if force_fixture or os.environ.get("ADSENSE_FIXTURE") == "1":
        return _fixture(topic)                # 스테이징/프리뷰 빠른 빌드(LLM 호출 없음)
    provider = (content_cfg.get("generation", {}) or {}).get("provider", "auto")
    if provider == "auto":                    # 키 있으면 API, 없고 claude CLI 있으면 구독, 둘 다 없으면 fixture
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "api"
        elif _claude_cli_available():
            provider = "claude_cli"
        else:
            provider = "fixture"
    grounding_text, fetched = _ground(topic, content_cfg)   # 공식 소스 페치(실패/비활성 시 "", [])
    if provider not in ("api", "claude_cli"):
        return _fixture(topic)

    def _one(fb):
        if provider == "api":
            return _via_api(topic, content_cfg, feedback=fb, grounding=grounding_text)
        return _via_claude_cli(topic, content_cfg, feedback=fb, grounding=grounding_text)

    spec = _one(feedback)
    # 생성측 자가검수 — 5종(제목계약·부재단정·무헤지수치·파이프라인언어·AI티)이 걸리면 다시 쓰게 한다.
    # ⚠️ 반려가 아니다(판정은 reviewer.py). 실패해도 원본 spec 으로 진행 → 파이프라인 정지 없음.
    # 피드백은 플래그 원문이 아니라 _rewrite_feedback() 의 일반화 지침 — 탐지 토큰을 알려주지 않기 위해서다.
    #
    # 2026-07-25-16-content P1 ⑤: 예전 판은 **1회만** 다시 쓰고 끝냈다. 14-content 실측에서 그 1회가
    # 아무것도 못 줄였고(2건 → 2건) 검수기가 AI 티 5건으로 반려했다. → 재검사 후 남아 있으면 한 번 더
    # 돌린다. ⛔ **최대 2회**(_SELFCHECK_MAX_REWRITES). 그래도 안 줄면 멈추고 잔여를 로그로 보고한다 —
    # 무한 재작성은 비용만 태우고, 최종 판정은 어차피 reviewer.py 가 한다.
    if os.environ.get("ADSENSE_SELFCHECK") != "0":
        details = selfcheck_detail(spec, grounding_text)
        rounds, history = 0, [len(details)]
        try:
            max_rounds = max(0, int(os.environ.get("ADSENSE_SELFCHECK_MAX_REWRITES",
                                                   _SELFCHECK_MAX_REWRITES)))
        except ValueError:
            max_rounds = _SELFCHECK_MAX_REWRITES
        while details and rounds < max_rounds:
            rounds += 1
            print(f"generate: 자가검수 {len(details)}건 — 재작성 {rounds}/{max_rounds} 회차\n  - "
                  + "\n  - ".join(f[:120] for f in selfcheck(spec, grounding_text)))
            try:
                fb = ((feedback + "\n\n") if feedback else "") + _rewrite_feedback(details, attempt=rounds)
                spec2 = _one(fb)
                details2 = selfcheck_detail(spec2, grounding_text)
            except Exception as e:               # 재작성 실패는 치명적이지 않다 — 원본으로 진행
                print(f"generate: 자가검수 재작성 {rounds}회차 건너뜀({type(e).__name__}: {e})")
                break
            if len(details2) <= len(details):    # 나아졌을 때만 채택(악화 시 직전 판 유지)
                spec, details = spec2, details2
            history.append(len(details))
            print(f"generate: 자가검수 재작성 {rounds}회차 후 잔여 {len(details)}건")
        if details:
            print(f"generate: ⚠️ 자가검수 잔여 {len(details)}건 — 재작성 {rounds}회 후 중단"
                  f"(추이 {' → '.join(str(h) for h in history)}). 판정은 REVIEW 에 맡긴다")
        spec.selfcheck_flags = selfcheck(spec, grounding_text)   # 잔여 경고(로그·검수 참고, 렌더 미노출)
    _finalize_sources(spec, content_cfg, fetched, grounding_text)
    return spec


# ── 소스 그라운딩 (F10·F14) — 공식 페이지 페치 → 프롬프트 주입. 전 과정 방어적(실패=기억기반 폴백) ──
def _ground(topic: str, cfg: dict) -> tuple[str, list]:
    """(주입 텍스트, 페치된 URL 목록). grounding.enabled=false 이거나 어떤 단계든 실패하면 ('', [])."""
    g = (cfg.get("grounding") or {})
    if not g.get("enabled"):
        return "", []
    try:
        urls = _discover_source_urls(topic, cfg)
        if not urls:
            return "", []
        docs = source_fetch.gather(
            urls, timeout=int(g.get("fetch_timeout", 12)),
            max_chars=int(g.get("max_chars_per_source", 3500)),
            max_sources=int(g.get("max_sources", 5)))
        if not docs:
            return "", []
        text = "\n\n".join(f"[SOURCE {i + 1}] {d['url']}\n{d['text']}" for i, d in enumerate(docs))
        print(f"generate: 그라운딩 — 공식 소스 {len(docs)}개 페치({sum(len(d['text']) for d in docs)}자)")
        return text, [d["url"] for d in docs]
    except Exception as e:                          # 그라운딩은 부가기능 — 실패해도 생성은 진행
        print(f"generate: 그라운딩 건너뜀({type(e).__name__}: {e}) — 기억기반 생성으로 폴백")
        return "", []


def _discover_source_urls(topic: str, cfg: dict) -> list:
    """토픽의 공식 벤더 URL(홈/pricing/docs)을 모델에게 물어 목록만 받는다(짧은 호출)."""
    sys = ("You return only official vendor URLs for research — no prose. For the given topic, list the "
           "official homepage, pricing, and docs URLs of the product(s) involved. One URL per line. "
           "Only real, canonical official domains you are confident exist.")
    user = f"Topic: {topic}\nOfficial pricing/docs/homepage URLs (one per line):"
    raw = complete_text(sys, user, cfg, max_tokens=500)
    seen = []
    for u in re.findall(r"https?://[^\s<>\"')]+", raw or ""):
        u = u.rstrip(".,);]")
        if u not in seen:
            seen.append(u)
    return seen[:8]


def _url_title(u: str) -> str:
    try:
        p = re.sub(r"^https?://(www\.)?", "", u).rstrip("/")
        host = p.split("/")[0]
        tail = p.split("/")[-1] if "/" in p else ""
        return f"{host} — {tail}".rstrip(" —") if tail and tail != host else host
    except Exception:
        return u


def _norm_url(u: str) -> str:
    """인용 중복 판정용 정규화 — scheme·www·트레일링 슬래시·대소문자 차이를 흡수."""
    return re.sub(r"^https?://(www\.)?", "", (u or "").strip()).rstrip("/").lower()


def _split_grounding(grounding_text: str) -> dict:
    """'[SOURCE n] <url>\\n<본문>' 블록 → {url: 본문}. `_ground()` 가 만든 형식의 역변환."""
    out = {}
    parts = re.split(r"(?m)^\[SOURCE \d+\]\s+(\S+)\s*$", grounding_text or "")
    for i in range(1, len(parts) - 1, 2):          # [앞머리, url1, 본문1, url2, 본문2, …]
        out[parts[i]] = parts[i + 1]
    return out


# 고유명사구·제품 코드 — 어떤 소스에서 왔는지 식별 가능한 '사실 지문'
_PROPER_TERM_RE = re.compile(r"\b[A-Z][A-Za-z0-9]{2,}(?:[ -][A-Z0-9][A-Za-z0-9]*)+\b|\b[A-Z]{2,}\d{1,3}\b")


def _figure_tokens(text: str) -> set:
    """'$24' · '40%' · '2x' · '70 models' 같은 **수치 토큰** 집합(정규화).

    맨숫자(_numeric_values)를 쓰면 안 된다 — 관측일 '2026-07-24' 가 24·07 로 쪼개져
    엉뚱한 소스를 '사용함'으로 만든다(실측 오탐: DO droplets 가 'figure 24' 로 통과).
    """
    return {re.sub(r"\s+", "", m.group(0)).replace(",", "").lower()
            for m in _FIGURE_TOKEN_RE.finditer(text or "")}


def _doc_signature(text: str) -> tuple:
    return _figure_tokens(text), {m.group(0) for m in _PROPER_TERM_RE.finditer(text or "")}


def _source_used_in(prose: str, doc: str, others: str):
    """본문이 이 소스를 실제로 썼다는 근거 문자열(없으면 None).

    **그 문서에만 있는** 수치 토큰·고유명사구가 본문에 나타나는지를 본다. 여러 소스가 공유하는
    벤더명("DigitalOcean")으로는 인정하지 않는다 — 같은 벤더의 안 쓴 페이지까지 인용으로 붙기 때문.
    보수적으로 틀린다: 근거를 못 찾으면 인용하지 않는다(모델이 스스로 적은 인용은 이 판정 밖).
    """
    d_figs, d_terms = _doc_signature(doc)
    o_figs, o_terms = _doc_signature(others)
    p_figs, p_terms = _doc_signature(prose)
    hit = (d_figs - o_figs) & p_figs
    if hit:
        return f"figure {sorted(hit)[0]}"
    hit_t = {t for t in (d_terms - o_terms) if len(t) >= 5} & p_terms
    if hit_t:
        return f"term '{sorted(hit_t)[0]}'"
    return None


def _finalize_sources(spec: ContentSpec, cfg: dict, fetched: list, grounding_text: str) -> None:
    """검수 사실대조용 grounding 저장 + 죽은 소스 URL 제거 + **본문이 실제로 쓴** 페치 URL만 인용에 추가.

    2026-07-25-16-content P2: 예전 판은 페치한 URL 을 **전부 무조건** sources 에 넣었다.
    본문이 쓰지 않은 페이지가 출처로 붙는 것은 E-E-A-T 상 허위 인용이고, 실제로 검수 반려를 만들었다
    (14-content ③-1: DO droplets 가격 페이지가 인용에만 있고 본문에 근거 없음 → [coherence]).
    모델이 스스로 적은 인용(spec.sources)은 건드리지 않는다 — 좁히는 대상은 **우리가 덧붙이는 몫**뿐.
    """
    g = (cfg.get("grounding") or {})
    try:
        spec.grounding_context = grounding_text or ""
    except Exception:
        pass
    if g.get("validate_source_urls") and spec.sources:
        try:
            good, dropped = source_fetch.validate_sources(spec.sources, timeout=int(g.get("fetch_timeout", 12)))
            if dropped:
                print(f"generate: 죽은 소스 URL {len(dropped)}개 제거 — {[d.get('url') for d in dropped]}")
                spec.sources = good
        except Exception:
            pass
    docs = _split_grounding(grounding_text)
    prose = " ".join(_prose_units(spec) + [getattr(spec, "title", "") or "", getattr(spec, "dek", "") or ""])
    have = {_norm_url(s.get("url")) for s in (spec.sources or [])}
    added, skipped = [], []
    for u in (fetched or []):
        if _norm_url(u) in have:                   # 모델이 이미 인용함(정규화 비교 → 중복 방지)
            continue
        doc = docs.get(u, "")
        others = "\n".join(t for k, t in docs.items() if k != u)
        why = _source_used_in(prose, doc, others) if doc else None
        if why:
            spec.sources.append({"title": _url_title(u), "url": u})
            have.add(_norm_url(u))
            added.append((u, why))
        else:
            skipped.append(u)
    if added:
        print(f"generate: 인용 추가 {len(added)}개(본문에 근거 등장) — " + ", ".join(f"{u} [{w}]" for u, w in added))
    if skipped:
        print(f"generate: 인용 제외 {len(skipped)}개(페치했으나 본문 미사용) — {skipped}")
    if not spec.sources and fetched:               # E-E-A-T 게이트(출처 필수)까지 비우지는 않는다
        print("generate: ⚠️ 인용 0건 — 페치 소스 1개를 최소 인용으로 복원")
        spec.sources = [{"title": _url_title(fetched[0]), "url": fetched[0]}]


def _claude_cli_available() -> bool:
    import shutil
    return shutil.which("claude") is not None


# ── claude CLI 호출 (2026-07-25-16-content P0) ────────────────────────────────────────────
# Windows `CreateProcess` 의 **명령줄 총길이 한도는 32,767자**다. 프롬프트를 argv 로 넘기면
# 그라운딩된 정상 길이 글의 검수 프롬프트(실측 36,568자)가 한도를 넘어
# `FileNotFoundError: [WinError 206]` 로 **호출 자체가 실패**한다(14-content ⑤ 실측).
# orchestrator 는 이 예외를 "REVIEW 실패→미발행"으로 삼키므로 → 초안은 있는데 큐 0편.
# → 프롬프트(user)는 **stdin**, 시스템 프롬프트만 argv(`--append-system-prompt`).
#
# ⚠️ stdin 보호(01-content 의 `stdin=DEVNULL` 도입 취지)를 깨지 않는다:
#    그 보호의 목적은 "**부모의 stdin 을 상속시키지 않는다**" 이다 — 콘솔 없는 환경
#    (Task Scheduler 20:00 배치)에서 상속된 핸들을 읽던 CLI 가 rc=1·빈 stderr 로 즉사했다.
#    `subprocess.run(input=...)` 은 stdin 을 **새 파이프로 열고**(상속 없음) 텍스트를 다 쓴 뒤
#    **닫는다**(communicate 가 write→close). 자식은 프롬프트를 읽고 즉시 EOF 를 본다.
#    DEVNULL = "빈 입력 + 즉시 EOF", PIPE+close = "프롬프트 + 즉시 EOF" — 상속이 없다는 점이 동일하고
#    tty 를 기다리며 멈추는 경로도 동일하게 없다. 무콘솔 실측은 보고서 참조.
_WIN_CMDLINE_LIMIT = 32767          # CreateProcess 한도(문자). 넘으면 WinError 206
_ARGV_SAFETY_MARGIN = 2048          # 인용부호·환경 오버헤드 여유


def _claude_cli_text(user: str, system: str, model: str, *, timeout: int = 900) -> str:
    """claude CLI 1회 실행 → 결과 텍스트. user 는 stdin, system 은 argv.

    실패(rc≠0 또는 봉투 is_error)는 RuntimeError 로 올린다 — 오류 문자열을 결과인 척
    돌려주면 상위(_extract_json·reviewer)가 엉뚱한 곳에서 깨진다.
    """
    import shutil
    import subprocess
    if not shutil.which("claude"):
        raise RuntimeError("claude CLI 미설치/미로그인 — Claude Code 설치 + 구독 로그인 필요")
    cmd = ["claude", "-p", "--append-system-prompt", system,
           "--output-format", "json", "--model", model]
    # user 는 stdin 이라 한도와 무관하다. system 만 argv → 남은 것도 한도 안인지 확인(진단 명확화).
    argv_chars = sum(len(a) for a in cmd) + len(cmd)
    if os.name == "nt" and argv_chars > _WIN_CMDLINE_LIMIT - _ARGV_SAFETY_MARGIN:
        raise RuntimeError(
            f"system 프롬프트가 너무 길다({argv_chars:,}자 argv > Windows 한도 {_WIN_CMDLINE_LIMIT:,}) — "
            "user 프롬프트는 stdin 이라 무관하니 system 쪽을 줄여야 한다")
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI 실패(rc={proc.returncode}): {_cli_error_detail(proc)}")
    # Claude Code --output-format json 봉투: {"result":"<텍스트>","is_error":bool, ...}
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout
    if isinstance(env, dict):
        if env.get("is_error"):
            raise RuntimeError(f"claude CLI 결과 오류: {str(env.get('result'))[:200]}")
        return env.get("result", proc.stdout)
    return proc.stdout


def _cli_error_detail(proc) -> str:
    """claude CLI 실패 사유 1줄 — CLI 는 오류를 **stdout JSON 의 result** 에 넣고 stderr 는 비운다.
    stderr 만 찍던 탓에 로그에 사유가 공백으로 남아 서버 0편이 21일간 묻혔다(2026-07-24-03-ops 이슈 2).
    예) {"is_error":true,"result":"Not logged in · Please run /login"} → 'Not logged in · Please run /login'
    """
    parts = []
    if (proc.stderr or "").strip():
        parts.append(proc.stderr.strip())
    out = (proc.stdout or "").strip()
    if out:
        try:
            env = json.loads(out)
            detail = env.get("result") or env.get("error") or "" if isinstance(env, dict) else ""
        except json.JSONDecodeError:
            detail = ""
        parts.append(str(detail).strip() or out)      # 파싱 실패·빈 result 면 원문 폴백
    return " | ".join(parts)[:300] or "(stderr·stdout 모두 비어 있음)"


# adsense-review 스킬 블록리스트(SKILL.md) — 생성·검수 양쪽에서 같은 목록을 씀(예방 + 탐지).
AI_CLICHE_PATTERNS = [
    (r"in today'?s fast-paced world", "in today's fast-paced world"),
    (r"whether you'?re\b", "whether you're A or B"),
    (r"it'?s worth noting", "it's worth noting"),
    (r"look no further", "look no further"),
    (r"\bdelve[sd]?\b|\bdelving\b", "delve"),
    (r"\belevate[sd]?\b", "elevate"),
    (r"\brobust\b", "robust"),
    (r"\bseamless(?:ly)?\b", "seamless"),
    (r"\bgame[- ]?changer\b", "game-changer"),
]
AI_CLICHE_LABELS = [label for _, label in AI_CLICHE_PATTERNS]


def scan_ai_cliches(text: str) -> list[str]:
    """블록리스트 정규식 스캔 — LLM 호출 전 무료 사전 필터(reviewer.py 가 사용)."""
    t = text or ""
    return [label for pattern, label in AI_CLICHE_PATTERNS if re.search(pattern, t, re.I)]


# ══ 생성측 자가검수 (2026-07-24-14-content) ══════════════════════════════════════════════
# 검수 반려 4건 전반에서 반복된 '진짜 결함 5종'(team/reports/2026-07-24-11-review.md ③)을
# 생성 단계에서 잡는다. ① 최상급 제목 vs 본문 불일치 ② 경쟁사 단정적 부정 주장
# ③ 휘발성·제3자 수치 무헤지 ④ 파이프라인 언어 노출 ⑤ AI 티(리듬·자기지시).
#
# ⚠️ 이것은 **게이트가 아니라 보조 신호(hint)** 다.
#    - 반려 권한이 없다: 걸려도 최대 1회 자가 재작성일 뿐, 통과/탈락 판정은 전적으로 reviewer.py(REVIEW 소유).
#    - 정규식은 거칠다: 여기서 0건이어도 "좋은 글"이라는 뜻이 아니고, 발화해도 "나쁜 글"이라는 뜻이 아니다.
#      1차 방어선은 _SYSTEM/_user_prompt(예방)이고 최종 방어선은 reviewer.py(판정)다. 이 스캐너는 그 사이의 값싼 보조.
#    - 그래서 재작성 피드백에는 **탐지 문구(토큰)를 그대로 노출하지 않는다**(_REWRITE_GUIDANCE):
#      "as of …" / "How we chose:" / "Our pick is …" 같은 표면 토큰만 덧대면 플래그가 0이 되는 게이밍을 부추기기 때문.
#      대신 (a) 피드백은 실질 수정 지시로 일반화하고 (b) 수치는 실제 소스(grounding)에 있는지 대조한다(_figure_evidence).
# ⚠️ 경계: 이 목록은 **생성 전용**이다. reviewer.py 의 자동반려 블록리스트(AI_CLICHE_PATTERNS)와
#    판정 임계값에는 손대지 않는다(REVIEW 소유).

# ── config 주도 배선: title_policy (config/topics.yaml) ────────────────────────────────
# rev2(2026-07-24): 이 블록은 engine 어디에서도 읽히지 않아 "값을 바꿔도 동작이 안 바뀌는" 착시였다
# (감사 실측: engine 전체 grep 0건). 아래 로더가 **프롬프트의 TITLE CONTRACT 문구**와 **selfcheck 의
# [title-contract] 검사 활성화 여부**를 실제로 결정한다 — config 에서 키를 빼면 해당 문구·검사가 사라진다.
#   superlative_requires 항목 → 프롬프트 요구사항 줄(_REQ_PROMPT_LINES) + 스캐너 검사 활성화
#     · stated_selection_criteria → 기준 명시 검사(_criteria_unit)
#     · named_pick_per_use_case   → 지목 검사(_named_pick)
#     · opinion_framing           → 프롬프트 전용(스캐너 검사 없음: 토큰 검사를 붙이면 게이밍만 유발)
#   otherwise → 최상급을 이행 못 할 때의 지시(retitle = 제목 변경)
#   never     → "최상급 제목 + 순위 거부 본문" 금지 = RANK_REFUSAL 검사 활성화
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_TITLE_POLICY = {
    "superlative_requires": ["stated_selection_criteria", "named_pick_per_use_case", "opinion_framing"],
    "otherwise": "retitle",
    "never": "superlative_title_over_no_ranking_body",
}
_TITLE_POLICY = None


def title_policy(*, reload: bool = False) -> dict:
    """config/topics.yaml 의 title_policy 를 읽는다(1회 캐시). 파일·키가 없으면 기본값으로 폴백."""
    global _TITLE_POLICY
    if _TITLE_POLICY is not None and not reload:
        return _TITLE_POLICY
    pol = dict(_DEFAULT_TITLE_POLICY)
    for path in (os.path.join(_REPO_ROOT, "config", "topics.yaml"), os.path.join("config", "topics.yaml")):
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            tp = data.get("title_policy")
            if isinstance(tp, dict):
                # config 에 **있는 키는 그대로 반영**(빈 값 = 그 규칙 끄기), 없는 키만 기본값 폴백.
                pol.update({k: ("" if v is None else v) for k, v in tp.items()})
            break
        except FileNotFoundError:
            continue
        except Exception as e:                    # YAML 손상 등 — 정책 부재로 생성을 막지 않는다
            print(f"generate: title_policy 로드 실패({type(e).__name__}: {e}) — 기본값 사용")
            break
    pol["superlative_requires"] = [str(x) for x in (pol.get("superlative_requires") or [])]
    _TITLE_POLICY = pol
    return pol

# ① 제목이 순위/최상급을 약속하는가
SUPERLATIVE_TITLE_RE = re.compile(r"\b(best|cheapest|fastest|top\s*\d+|#\s*1|ultimate|greatest|winner)\b", re.I)
# ① 결론부(TLDR/verdict)가 순위 판정을 내리는가 — 제목에서 최상급을 뺐다고 본문 판정이 면제되진 않는다.
#    (2026-07-25-16-content P1) 14-content 실측: 모델이 (b) retitle 을 고르자 제목계약 검사 3종이
#    `if sup:` 중첩 때문에 **동시에 꺼졌고**, 최상급은 TLDR 로 이동했다("Cheapest path … Hetzner Cloud").
#    그 글은 `_criteria_unit` 이 없는데도 플래그가 0건이었다 → 트리거를 제목 ∨ 결론부로 넓힌다.
SUPERLATIVE_BODY_RE = re.compile(
    r"\b(best|cheapest|fastest|top\s*\d+|#\s*1|ultimate|greatest|winner|wins|"
    r"comes out ahead|better value|cheaper than|faster than)\b", re.I)
# 위 단어가 나왔다고 다 순위 '주장'은 아니다. 발행 28편 실측으로 걸러낸 두 오탐:
#  (a) 거부 문맥 — "There is no single winner", "No single tool wins for everyone",
#      "There isn't a single 'best' password manager" (15건 중 10건이 이 형태였다)
#  (b) 부사적 용법 — "These tools are best understood as complements", "work best as a first pass"
_SUP_NEG_RE = re.compile(r"\b(?:no|not|isn'?t|aren'?t|never|rather than|instead of)\b[^.;:]{0,55}$", re.I)
_SUP_ADVERBIAL_RE = re.compile(
    r"\bbest\s+(?:understood|described|thought|seen|viewed|used|suited|placed|left|read|"
    r"approached|treated|explained|judged)\b", re.I)


def _ranking_claim(text: str):
    """결론부가 실제로 순위를 **주장**하는 첫 지점(거부·부사적 용법은 제외). 없으면 None."""
    for m in SUPERLATIVE_BODY_RE.finditer(text or ""):
        pre = text[max(0, m.start() - 60):m.start()]
        if _SUP_NEG_RE.search(pre):
            continue                                   # (a) "no single winner" 류
        if _SUP_ADVERBIAL_RE.match(text[m.start():m.start() + 40]):
            continue                                   # (b) "best understood as"
        return m
    return None
# ① 본문이 순위를 거부하는가(= 제목과 정면 충돌). 실제 반려문에서 관측된 형태들.
RANK_REFUSAL_PATTERNS = [
    r"there (?:is|'s) no single (?:best|cheapest|fastest|right|winner)",
    r"no single (?:best|cheapest|fastest|right) \w+",
    r"\bis not a ranked list\b|\bdifferent angle (?:from|than) a ranked list\b",
    r"\b(?:we|this guide|this article|this piece) (?:do(?:es)? not|don'?t|doesn'?t|declines? to) rank\b",
    r"no (?:specific )?(?:figures|prices|numbers) are (?:quoted|given|listed|printed)",
    r"\bdeliberately (?:prints?|quotes?|lists?) no (?:prices|figures|numbers)\b",
]
# ① 제목의 약속을 본문이 이행했는가 — 지목된 선택 + 선정 기준
PICK_RE = re.compile(r"\b(pick|choose|go with|our pick|we recommend|best for)\b", re.I)
CRITERIA_RE = re.compile(
    r"\bhow (?:we|these|they) (?:chose|were chosen|judged|picked|ranked|compared)\b|\bselection criteria\b"
    r"|\bcriteria (?:used|below|here|we)\b|\bwhat (?:we|this guide) (?:looked at|weighed|measured)\b"
    r"|\bmethodolog(?:y|ies)\b|\bhow this (?:list|comparison) was (?:built|made|assembled)\b", re.I)

# ② 경쟁사 부재 단정 — 소스에 명시적 부재 근거가 있고 '무엇을·언제 확인했는지' 범위가 붙어야 한다.
ABSENCE_CLAIM_RE = re.compile(
    r"\b(?:does not|doesn'?t|do not|don'?t|cannot|can'?t|will not|won'?t)\s+(?:currently\s+|yet\s+)?"
    r"(?:support|offer|include|provide|list|have|expose|ship|allow|appear|exist|come with)\b"
    # "there is no single/one/universal ..." 류 일반론은 ①(제목계약)의 영역이라 여기선 제외(중복 발화 방지)
    r"|\b(?:lacks|has no|have no|no equivalent|is missing|are missing|is absent|are absent|never supports?)\b"
    r"|\bthere(?:'?s| is) no (?!single\b|one\b|universal\b|clear\b|right\b|wrong\b|perfect\b|substitute\b)", re.I)
# 부재 단정에 동반되어야 하는 '무엇을 확인했는가' 단서(= 어느 페이지·문서를 봤는가).
# ⚠️ rev2: 예전 판은 여기에 날짜 단서(as of / 2026-07-24)까지 넣어 놨다 → "as of <날짜>" 한 토막만 붙이면
#    부재 단정이 통과했다(감사가 실측한 게이밍 경로 그대로). 이제 날짜는 DATE_CUE_RE 로 따로 요구하고,
#    여기서는 **관측 대상**만 본다. 즉 "무엇을 봤는가 + 언제 봤는가" 둘 다 있어야 한다(프롬프트가 시키는 형태와 동일).
SCOPE_CUE_RE = re.compile(
    r"\bon (?:the|its|their) [^.;]{0,40}(?:page|menu|docs|documentation|site|overview)\b"
    r"|\b(?:pricing page|plans? page|product page|docs|documentation|changelog|release notes|feature list)\b"
    r"|\blist(?:s|ed)\b|\bdocumented\b|\bpublicly documented\b", re.I)

# ③ 휘발성 수치 — 가격·비율·배수·개수는 관측일 없이 사실 단정 금지
VOLATILE_FIGURE_RE = re.compile(
    r"[$€£]\s?\d|\b\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?\s?[x×]\s|\b\d{2,}\s+"
    r"(?:models|regions|data ?centers|datacentres|locations|countries|servers)\b", re.I)
DATE_CUE_RE = re.compile(
    r"\bas of\b|\bchecked (?:on|in)\b|\breviewed on\b|\bat the time of writing\b|\b20\d\d-\d\d-\d\d\b"
    r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d\d\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d\d\b", re.I)

# ④ 파이프라인 언어 — 생성 과정을 자백하는 문구(독자에겐 무의미, 신뢰 훼손). 반려문 원문에서 수집.
#
# ⚠️ rev2(2026-07-24) 오탐 해소: 이전 판은 **단어**를 금지해서 개발 어휘를 오탐했다(감사 실측 —
#    "Postman displays the parsed response body, and the fetched JSON is cached" → 2건,
#    "Scraped data can be exported to CSV" → 1건). 우리는 개발툴 비교 사이트다: fetch/parse/scrape/crawl/
#    ingest 는 **주제어**이지 금지어가 아니다. 이걸 금지하면 매 초안에 불필요한 재작성 1회(LLM 비용)를
#    유발하고, 모델이 정확한 기술 용어를 피하도록 압박한다.
#    → 금지 대상은 단어가 아니라 **"이 페이지의 입력물"을 가리키는 문맥**이다:
#       (a) 한정사 + 파이프라인 동사 + 우리 입력물 목적어  ("the fetched text", "the supplied sources")
#       (b) 우리 입력물 목적어 + 후치 파이프라인 동사      ("the sources supplied", "the excerpt provided")
#       (c) 그 자체로 입력물을 뜻하는 명사구              ("source material", "used for this article")
#       (d) 템플릿·마커 누출 / 렌더러가 정하는 위치 지시
#    같은 동사라도 목적어가 기술 대상(JSON·response·data·page·schema)이면 통과한다.
_PIPE_VERB = r"(?:fetched|supplied|provided|given|scraped|crawled|ingested|retrieved|gathered|collected|delivered|reviewed)"
# 'provided/given' 은 AI 글쓰기 툴 글에서 사용자 입력을 가리키는 정상어("Jasper rewrites the provided text")라
# text/material 계열에는 붙이지 않는다 — 우리 입력물을 가리키는 좁은 동사만.
_PIPE_VERB_NARROW = r"(?:fetched|supplied|scraped|crawled|ingested|retrieved|gathered|delivered|reviewed)"
# 목적어는 '우리가 받은 원문'을 뜻하는 것만 — data/page/response/JSON/schema/copy/draft 등은 일부러 뺐다.
_PIPE_OBJ_SRC = r"(?:source|sources|excerpt|excerpts|corpus)"
_PIPE_OBJ_TXT = r"(?:text|texts|material|materials)"
PIPELINE_LEAK_PATTERNS = [
    (rf"\b(?:the|this|these|those|our|its|only the)\s+{_PIPE_VERB}\s+{_PIPE_OBJ_SRC}\b",
     "pipeline wording ('the supplied sources')"),
    (rf"\b(?:the|this|these|those|our|its|only the)\s+{_PIPE_VERB_NARROW}\s+{_PIPE_OBJ_TXT}\b",
     "pipeline wording ('the fetched text' / 'the reviewed material')"),
    # 후치 수식: "the sources supplied". 'used/available' 은 뺐다 — "the sources used by the crawler" 오탐.
    (rf"\b(?:the|this|these|those|our)\s+{_PIPE_OBJ_SRC}\s+(?:{_PIPE_VERB}|we (?:were )?(?:given|had))\b",
     "pipeline wording ('the sources supplied' / 'the excerpt provided')"),
    (r"\bsource material\b", "'source material'"),
    (r"\b(?:used|available|provided|supplied|given)\s+(?:to us\s+)?for this (?:article|page|piece|comparison|guide|review|draft)\b",
     "'used for this article' (describes this page's inputs)"),
    (r"\bin the (?:version|copy|draft|text|material) reviewed\b", "'in the version reviewed'"),
    (r"\[?\bSOURCE \d+\]?", "'[SOURCE n]' marker"),
    (r"\bMarks and (?:descriptions|scores)\b", "template boilerplate 'Marks and descriptions'"),
    (r"\bas delivered\b|\bin (?:this|the) draft\b", "'as delivered' / 'in this draft'"),
    # 위치 지시 — 표·matrix·verdict·sources 의 배치는 renderer.py 가 정한다(모델이 아니다) → 방향 오류 상습.
    # 단, 모델이 같은 섹션 html 안에 직접 쓰는 list/section/checklist 는 뺐다(모델이 순서를 통제 = 오탐).
    (r"\b(?:table|matrix|chart|verdict|summary|column)s?\s+(?:above|below)\b",
     "positional reference ('table below')"),
    (r"\b(?:as\s+)?(?:marked|listed|shown|noted|described|summari[sz]ed)\s+(?:\w+\s+){0,3}(?:above|below)\b",
     "positional reference ('marked as absent below')"),
    (r"\bsources?\s+(?:section|list)\s+(?:below|at the end|that follows)\b",
     "positional reference to the sources section"),
]

# ⑤ AI 티 — **생성 전용** 목록(검수기 자동반려 목록과 분리). 반려문에서 실제 지적된 형태.
GEN_STYLE_BANS = [
    (r"\bgenuine(?:ly)?\b", "'genuine/genuinely'"),
    (r"\bworth (?:stating|noting|mentioning|flagging|remembering)\b", "'worth noting' variants"),
    (r"\bthis (?:guide|article|piece|comparison|post)\s+(?:takes|is not|isn'?t|does not|doesn'?t|will)\b",
     "meta-commentary about the article itself"),
    (r"\bmost comparison (?:articles|sites|guides|posts)\b", "swipe at unnamed competitors"),
    (r"\b(?:stated|put) plainly\b|\bplainly (?:put|stated)\b", "throat-clearing connective"),
    (r"\bcuts both ways\b|\bis a moving target\b", "stock idiom used as a pivot"),
    (r"\bread (?:those|these) (?:two )?paragraphs\b|\bhold onto\b|\bthe most useful thing\b",
     "reader signposting filler"),
    (r"^(?:Five|Four|Three|Two|Six|Seven)\s+(?:things|situations|factors|reasons|questions)\b",
     "counted-list section opener"),
]
# ⑤ 미러 구문("X, not Y" / "not X, but Y") 반복
MIRROR_RE = re.compile(r"\bnot\s+[^,.;:]{1,45},\s*but\b|,\s*not\s+(?:merely\s+|just\s+|only\s+)?[a-z][^,.;:]{0,40}[.;]", re.I)
_EM_DASH = "—"
# 임계값은 발행 28편 실측 분포로 잡았다(추정 아님, 2026-07-24):
#   미러 구문 수(28편)   0:19편 · 1:5 · 2:2 · 3:1 · 4:1  → 임계 3 = 2편(7%) / 임계 2 = 4편(14%)
#   em 대시 단락 커버리지 min 0.00 / median 0.31 / p75 0.42 / max 0.62 → 0.60 이상이면 상위 4%(1편)
#
# ⚠️ rev2 재검토(감사 지적: "임계 3은 기존 코퍼스 상위 극단이라 사실상 발화하지 않는다 = 지금 리듬을 정상으로
#    승인하는 셈"). 실제로 검수기는 미러 **1회**인 글(vercel-vs-netlify)도 지적했다 → 스캐너가 검수기 감도를
#    따라잡을 방법은 없다. 그래서 **주 방어선은 프롬프트(_SYSTEM VOICE 불릿)이고, 최종 판정은 reviewer.py 의
#    ai_tells(자동반려)** 다. 이 임계값은 그 사이의 값싼 백스톱일 뿐이다.
#    다만 3 → 2 로 낮춘다: 미탐 1건의 비용(생성+검수 1사이클 폐기)이 오탐 1건의 비용(재작성 1회)보다 크고,
#    2 이상은 여전히 상위 14%(28편 중 4편)라 "대부분의 글을 자동 재작성"시키지 않는다.
MIRROR_MAX = 2
EM_DASH_PARA_RATIO_MAX = 0.60
SELFCHECK_MAX_FLAGS = 12                  # 피드백 프롬프트 폭주 방지
# 자가 재작성 상한 — 1편당 생성 LLM 호출은 최대 1 + _SELFCHECK_MAX_REWRITES 회.
# 환경변수 ADSENSE_SELFCHECK_MAX_REWRITES 로 조정(0 = 재작성 없음, ADSENSE_SELFCHECK=0 = 자가검수 자체 끔).
_SELFCHECK_MAX_REWRITES = 2
_P_RE = re.compile(r"(?is)<(?:p|li|h3)[^>]*>(.*?)</(?:p|li|h3)>")


def _prose_units(spec) -> list:
    """spec 의 산문 단락 목록(표·매트릭스는 제외 — 자가검수는 산문만 본다)."""
    htmls = [getattr(spec, "intro_html", "") or ""]
    htmls += [s.get("html", "") for s in (getattr(spec, "sections", None) or [])]
    for attr in ("verdict_html", "tldr_html"):
        if getattr(spec, attr, None):
            htmls.append(getattr(spec, attr))
    htmls += [f.get("a", "") for f in (getattr(spec, "faq", None) or [])]
    units = []
    for h in htmls:
        found = [u for u in (_strip(m) for m in _P_RE.findall(h)) if u]
        units += found or ([_strip(h)] if _strip(h) else [])
    return units


def _sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


# ── 게이밍 방지 헬퍼 (rev2) ────────────────────────────────────────────────────────────
# 감사 실측: 표면 토큰 3개("How we chose:" · "as of …" · "Our pick is …")만 덧대면 7건 → 0건이 됐다
# (근거·수치는 하나도 안 바뀐 채). 아래 3개는 "토큰이 있는가"가 아니라 **근거가 동반됐는가**를 본다.
_CRITERIA_MIN_WORDS = 25          # 기준 선언이 실질 문단인가(제목·한 줄 상투구 배제)
_GENERIC_NAMES = {"free", "pro", "team", "plus", "basic", "premium", "starter", "business",
                  "enterprise", "hobby", "personal", "standard", "cloud", "self-hosted"}
# 휘발성 수치 토큰(값 추출용) — VOLATILE_FIGURE_RE 는 '단락이 휘발성인가' 판정용이라 그대로 둔다.
_FIGURE_TOKEN_RE = re.compile(
    r"[$€£]\s?\d+(?:[.,]\d+)*|\b\d+(?:[.,]\d+)*\s?%|\b\d+(?:\.\d+)?\s?[x×]\b"
    r"|\b\d{2,}\s+(?:models|regions|data ?centers|datacentres|locations|countries|servers)\b", re.I)
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _numeric_values(text: str) -> set:
    """텍스트의 수치 리터럴 집합(1,000→1000 / 4.50→4.5 정규화)."""
    vals = set()
    for m in _NUM_RE.finditer(text or ""):
        try:
            vals.add(round(float(m.group(0).replace(",", "")), 4))
        except ValueError:
            continue
    return vals


def _unsupported_figures(unit: str, ground_values: set) -> list:
    """단락의 휘발성 수치 중 **소스(grounding)에 존재하지 않는** 값 목록.
    관측일 토큰을 붙여도 지워지지 않는다 = '날짜만 덧대는' 게이밍이 통하지 않는 지점."""
    missing = []
    for m in _FIGURE_TOKEN_RE.finditer(unit or ""):
        for num in _NUM_RE.findall(m.group(0)):
            try:
                v = round(float(num.replace(",", "")), 4)
            except ValueError:
                continue
            if 1990 <= v <= 2100 and v == int(v):        # 연도는 수치가 아니라 날짜
                continue
            if v not in ground_values:
                missing.append(m.group(0).strip())
            break
    return missing


def _criteria_unit(units: list):
    """'기준을 밝혔다'고 인정할 수 있는 단락 — 신호어 + 실질 분량(_CRITERIA_MIN_WORDS)."""
    for u in units:
        if CRITERIA_RE.search(u) and len(u.split()) >= _CRITERIA_MIN_WORDS:
            return u
    return None


def _product_names(spec) -> list:
    """spec 의 구조화 필드에서 실제 제품명을 뽑는다(플랜명 pricing[].name 은 제외 — 'Free' 등 오검출).
    지목 검사는 이 이름이 결론부에 실제로 등장하는지를 본다 = 'Our pick is …'만으론 통과 못 함."""
    names = []
    for attr in ("comparison", "feature_matrix"):
        d = getattr(spec, attr, None) or {}
        if isinstance(d, dict):
            names += [d.get("a"), d.get("b")]
    for row in (getattr(spec, "pros_cons", None) or []):
        if isinstance(row, dict):
            names.append(row.get("name"))
    out = []
    for n in names:
        n = (n or "").strip()
        if len(n) >= 2 and n.lower() not in _GENERIC_NAMES and n not in out:
            out.append(n)
    return out


def _named_pick(decision: str, names: list) -> bool:
    """결론부가 '지목'을 했는가 — 추천 표현 + (알려진 제품명이 있으면) 그 이름의 실제 등장."""
    if not PICK_RE.search(decision or ""):
        return False
    if not names:                                  # 구조화 필드가 없는 페이지(가이드 등) → 표현만 확인
        return True
    return any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", decision, re.I) for n in names)


# 재작성 피드백 문구 — **탐지 토큰을 알려주지 않는다**(as of / how we chose / our pick 등 문자열 없음).
# 플래그(로그)와 피드백(프롬프트)을 분리한 이유: 플래그 원문을 그대로 주입하면 모델이 '검사기를 만족시키는
# 문구'를 덧대는 최단 경로를 학습한다(감사 실측 7→0건). 여기서는 **무엇을 실제로 고쳐야 하는지**만 말한다.
_REWRITE_PREAMBLE = (
    "SELF-CHECK NOTES (automatic pattern scan of your own draft — not a reviewer verdict, and it can be wrong). "
    "Fix the substance behind each note. Do NOT satisfy these by inserting a heading, a stock sentence or a "
    "date next to an unverified claim: a full editorial review reads the finished draft afterwards and rejects that.")
_REWRITE_GUIDANCE = {
    "title-contract": ("The headline promises a ranking that the body does not deliver. Either rank honestly — "
                       "say which option wins for which kind of reader and show the evidence that decided it — "
                       "or change the headline so it describes what this article actually does. The title field "
                       "is yours to set; it does not have to repeat the search query."),
    "negative-claim": ("You state that a named product is missing something without saying what you actually "
                       "looked at. Name the specific vendor page you read and the day you read it, or drop the "
                       "claim. If the material does not positively show the absence, drop it — do not soften it."),
    "volatile-figure": ("These numbers are presented as standing fact, or do not appear anywhere in the material "
                        "you were working from. Every figure has to trace to a page you cite and to the day you "
                        "observed it. A number you cannot trace must be deleted, not dated."),
    "pipeline-language": ("Remove wording that describes how this page was produced, or that points at where a "
                          "block will sit on the finished page. The reader knows nothing about any of that, and "
                          "the site template — not you — decides where tables, the verdict and the sources land."),
    "ai-tell": ("Rewrite the quoted sentences themselves — deleting the flagged word and leaving the same "
                "sentence shape behind does not fix it. Change the sentence lengths and the openings around "
                "them so the passage stops running on one cadence, and say the point plainly in your own "
                "words without commenting on the article itself."),
}
# ⑤ 리듬·클리셰(ai-tell)는 **왜 걸렸는지**를 알려준다: 형태에 대한 지적이라 토큰을 덧대 만족시킬 수
#    없고(고치려면 문장을 다시 써야 한다), 반대로 알려주지 않으면 모델이 고칠 대상을 특정할 수 없다.
#    다른 kind 의 note 는 계속 숨긴다 — 그쪽은 "무엇을 붙이면 통과하는가"를 알려주는 셈이 되기 때문.
_NOTE_VISIBLE_KINDS = {"ai-tell"}
_REWRITE_ESCALATION = (
    "THIS IS REWRITE ATTEMPT {n}. The previous rewrite did NOT remove the problems below — the same "
    "patterns are still in the draft. Do not make another light edit: rewrite the affected passages from "
    "scratch, in different sentence shapes, and re-read the whole draft for the same habit elsewhere.")


def _rewrite_feedback(details: list, *, attempt: int = 1) -> str:
    """(kind, quote, note) → 재작성 프롬프트. 문제 지점(초안 자신의 문장)만 인용하고, 지침은 일반화한다."""
    by_kind, notes = {}, {}
    for kind, quote, note in details:
        by_kind.setdefault(kind, [])
        if quote and quote not in by_kind[kind]:
            by_kind[kind].append(quote)
        if kind in _NOTE_VISIBLE_KINDS and note:
            notes.setdefault(kind, [])
            if note not in notes[kind]:
                notes[kind].append(note)
    parts = [_REWRITE_PREAMBLE]
    if attempt > 1:
        parts.append(_REWRITE_ESCALATION.format(n=attempt))
    for kind, quotes in by_kind.items():
        block = "- " + _REWRITE_GUIDANCE.get(kind, "Fix this issue.")
        for n in notes.get(kind, [])[:4]:
            block += f"\n    what is wrong: {n}"
        for q in quotes[:4]:
            block += f"\n    offending text: \"{q[:200]}\""
        parts.append(block)
    return "\n".join(parts)


def selfcheck_detail(spec, grounding: str = "") -> list:
    """생성 직후 자가검수 → [(kind, quote, note)]. **판정·반려가 아니라 재작성 힌트**(REVIEW 가 판정한다).
    grounding: 생성 시 주입한 소스 원문(있으면 수치를 소스와 대조 — 표면 토큰으로 못 지나감)."""
    units = _prose_units(spec)
    prose = "\n".join(units)
    if not prose:
        return []
    title = getattr(spec, "title", "") or ""
    decision = _strip((getattr(spec, "tldr_html", "") or "") + " " + (getattr(spec, "verdict_html", "") or ""))
    pol = title_policy()
    requires = pol.get("superlative_requires") or []
    out = []

    # ① 순위 약속 ↔ 이행 (검사 활성화 여부 = config/topics.yaml title_policy)
    #    트리거는 **제목 ∨ 결론부**다. 제목을 중립으로 바꿔도(retitle) TLDR/verdict 가 순위를 판정하면
    #    기준명시·지목·순위거부 검사는 그대로 적용된다 — 예전 `if sup:` 중첩이 이걸 통째로 껐다.
    sup_title = SUPERLATIVE_TITLE_RE.search(title)
    sup_body = _ranking_claim(decision)
    sup = sup_title or sup_body
    if sup:
        word = sup.group(0)
        where = "the title" if sup_title else "the conclusion"
        promise = f"{where} claims '{word}'"
        if pol.get("never") and any(re.search(p, prose, re.I) for p in RANK_REFUSAL_PATTERNS):
            out.append(("title-contract", title if sup_title else decision[:160],
                        f"{promise} while the body declines to rank"))
        if "named_pick_per_use_case" in requires and not _named_pick(decision, _product_names(spec)):
            out.append(("title-contract", decision[:160],
                        f"{promise} but the conclusion names no product as the choice"))
        if "stated_selection_criteria" in requires and _criteria_unit(units) is None:
            out.append(("title-contract", (title if sup_title else decision[:160]),
                        f"{promise} with no substantive passage on what was weighed"))

    # ② 경쟁사 부재 단정 — 무엇을·언제 확인했는지 둘 다 있어야 한다(하나만으론 토큰 덧대기와 구별 불가)
    for s in _sentences(prose):
        if ABSENCE_CLAIM_RE.search(s) and not (SCOPE_CUE_RE.search(s) and DATE_CUE_RE.search(s)):
            out.append(("negative-claim", s, "absence asserted without both the page checked and the date"))

    # ③ 휘발성 수치 — (a) 소스에 없는 수치 (b) 관측일 없는 수치
    ground_values = _numeric_values(grounding or getattr(spec, "grounding_context", "") or "")
    for u in units:
        if not VOLATILE_FIGURE_RE.search(u):
            continue
        missing = _unsupported_figures(u, ground_values) if ground_values else []
        if missing:
            out.append(("volatile-figure", u, "figures absent from the cited material: " + ", ".join(missing[:4])))
        elif not DATE_CUE_RE.search(u):
            out.append(("volatile-figure", u, "figure given with no observation date"))

    # ④ 파이프라인 언어
    for pattern, label in PIPELINE_LEAK_PATTERNS:
        m = re.search(pattern, prose, re.I | re.M)
        if m:
            out.append(("pipeline-language", m.group(0), label))

    # ⑤ AI 티(생성 전용 목록 + 리듬 측정)
    for pattern, label in GEN_STYLE_BANS:
        m = re.search(pattern, prose, re.I | re.M)
        if m:
            out.append(("ai-tell", m.group(0), label))
    # 리듬 플래그는 **인용문을 반드시 채운다**(2026-07-25-16-content P1 ⑤).
    # 예전 판은 quote="" 라 재작성 피드백이 "Cut this stock phrasing" 한 줄뿐이었다 — 모델은 어느 문장이
    # 걸렸는지 알 수 없으니 고칠 수도 없었다(14-content 실측: 2건 검출 → 재작성 → 2건 그대로).
    mirrors = [m.strip() for m in MIRROR_RE.findall(prose) if m.strip()]
    if len(mirrors) >= MIRROR_MAX:
        # 정규식 조각이 아니라 **그 조각이 들어 있는 문장 전체**를 인용한다 — 조각만 주면
        # 모델이 어디를 다시 써야 하는지 알 수 없다.
        sents, shown = _sentences(prose), []
        for frag in mirrors:
            whole = next((s for s in sents if frag in s), frag)
            if whole not in shown:
                shown.append(whole)
        out.append(("ai-tell", " ⟂ ".join(shown[:3]),
                    f"the 'X, not Y' antithesis appears {len(mirrors)} times"))
    if units:
        dashed = [u for u in units if _EM_DASH in u]
        ratio = len(dashed) / len(units)
        if ratio >= EM_DASH_PARA_RATIO_MAX:
            out.append(("ai-tell", " ⟂ ".join(u[:110] for u in dashed[:2]),
                        f"em-dash asides in {ratio:.0%} of paragraphs — one cadence throughout"))
    return out[:SELFCHECK_MAX_FLAGS]


def selfcheck(spec, grounding: str = "") -> list[str]:
    """selfcheck_detail 의 로그용 1줄 표현. 재작성 프롬프트에는 이 문자열을 쓰지 않는다(_rewrite_feedback)."""
    return [f"[{kind}] {note}" + (f' — "{quote[:120]}"' if quote else "")
            for kind, quote, note in selfcheck_detail(spec, grounding)]


# config/topics.yaml title_policy → 프롬프트 문구(요구사항 1줄씩). 모르는 키도 그대로 요구로 나간다
# (= config 에 항목을 추가하면 프롬프트가 바뀐다. 값이 코드에 없어서 무시되는 일이 없게).
_REQ_PROMPT_LINES = {
    "stated_selection_criteria": "state the criteria you judged on explicitly, in an early section — what you "
                                 "weighed, and why those things and not others",
    "named_pick_per_use_case": "name a specific pick for each use case in tldr_html and verdict_html, with the "
                               "evidence behind each one",
    "opinion_framing": "frame the picks as this site's judgement on those criteria, not as objective fact",
}
_OTHERWISE_LINES = {
    "retitle": "if the material does not let you rank honestly, write a title that matches what you actually "
               "deliver — 'How to choose a cheap VPS in 2026', 'Cheap VPS hosting in 2026: Hetzner and "
               "DigitalOcean compared' — and drop the superlative. The 'title' field is yours to set; it does "
               "not have to repeat the query.",
}
_NEVER_LINES = {
    "superlative_title_over_no_ranking_body": "A title that promises a ranking over a body that says 'there is "
                                              "no single best' is a misleading headline and will be rejected.",
}


def _title_contract_block(pol: dict | None = None) -> str:
    """config/topics.yaml title_policy → TITLE CONTRACT 프롬프트 블록."""
    pol = pol or title_policy()
    reqs = pol.get("superlative_requires") or []
    lines = ["TITLE CONTRACT (this query asks for a superlative — pick ONE of these two, do not blend them):"]
    if reqs:
        lines.append("  (a) DELIVER IT: " + "; ".join(
            _REQ_PROMPT_LINES.get(r, f"satisfy the '{r}' requirement") for r in reqs) + ".")
    otherwise = str(pol.get("otherwise") or "")
    if otherwise:
        lines.append("  (b) " + otherwise.upper() + ": " + _OTHERWISE_LINES.get(
            otherwise, f"otherwise apply the '{otherwise}' rule from the site's title policy."))
    never = str(pol.get("never") or "")
    if never:
        lines.append(_NEVER_LINES.get(never, f"Never do this: {never}."))
    return "\n".join(lines)


def _user_prompt(topic: str, language: str, feedback: str | None = None, grounding: str = "",
                 today: str | None = None) -> str:
    today = today or datetime.date.today().isoformat()
    base = (f"Write a {language} article for this search query: \"{topic}\".\n"
            "If it is an 'X vs Y' query, make page_type 'comparison' and fill comparison/pricing/pros_cons. "
            "If it is 'best ...' make it 'listicle'; if 'how to ...' make it 'guide' (comparison may be null). "
            "Include 2+ official sources. Aim for depth that fully answers the query.\n"
            f"OBSERVATION DATE: {today}. Every price, plan name, quota, limit, model/region count or benchmark "
            f"figure you put in prose is an observation made on {today} — write that date next to the figures "
            f"the first time they appear in a section (\"as of {today}\") and cite the vendor page it came "
            "from in 'sources'. If you cannot tie a number to a cited page, leave the number out.")
    # ① 제목 계약 — 'best/cheapest/top N' 질의는 제목이 순위를 약속한다. 이행하거나 제목을 바꾼다.
    #    문구는 config/topics.yaml 의 title_policy 가 만든다(하드코딩 아님, title_policy() 참조).
    if SUPERLATIVE_TITLE_RE.search(topic):
        base += "\n\n" + _title_contract_block()
    if grounding:
        base += ("\n\n=== SOURCE MATERIAL (fetched from official pages just now) ===\n"
                 "Use this for ACCURATE, CURRENT pricing tiers and features — prefer it over prior knowledge. "
                 "CRITICAL — do not fabricate specifics: state a specific price, plan name, numeric limit, or "
                 "feature/product name ONLY if it appears in the SOURCE MATERIAL below. Do NOT pull specific "
                 "prices, feature names, or claims about what a competitor does/doesn't support from memory. "
                 "If the sources don't cover something, describe it in general terms or leave it out — never "
                 "invent a number or a proper feature name. Do NOT attribute a quote to a vendor unless it "
                 "appears verbatim in the sources. Express prices as tiers and tell readers to confirm on the "
                 "vendor's site. Cite these source URLs in the 'sources' field.\n"
                 # ② 부재 단정: 소스는 부분 발췌다 — '안 보임'은 '없음'이 아니다.
                 "NEGATIVE CLAIMS: this material is a PARTIAL excerpt of each page. Something missing here is "
                 "NOT evidence that the vendor lacks it. Never write 'X does not support Y', 'X lacks Y', "
                 "'X has no Y' or imply the gap. If the absence matters to the decision, scope it to what you "
                 "checked: \"the pricing page listed no managed database as of " + today + "\". "
                 "Do the same for both vendors — never describe one from the sources and the other from memory.\n"
                 # ④ 이 블록의 존재 자체를 글에 노출하지 않는다.
                 "NEVER DESCRIBE THIS MATERIAL IN THE ARTICLE. The reader has no idea it exists. Do not write "
                 "'the fetched text', 'the supplied sources', 'the excerpt', 'in the version reviewed', "
                 "'[SOURCE 1]' or any other description of how this page was produced. Cite the vendor page "
                 "by name and date instead.\n\n" + grounding[:12000])
    if feedback:
        base += ("\n\nIMPORTANT: a previous draft for this exact topic was rejected in quality review. "
                  f"You MUST fix these specific problems in this rewrite — do not repeat them:\n{feedback}")
    return base


def complete_text(system: str, user: str, content_cfg: dict, *, max_tokens: int = 6000) -> str:
    """provider(api|claude_cli)로 1회 완성 텍스트 반환 — reviewer 등 범용 재사용."""
    gen = content_cfg.get("generation", {})
    model = gen.get("model", "claude-opus-4-8")
    provider = gen.get("provider", "auto")
    if provider == "auto":
        provider = "api" if os.environ.get("ANTHROPIC_API_KEY") else ("claude_cli" if _claude_cli_available() else "")
    if provider == "api":
        import anthropic
        resp = anthropic.Anthropic().messages.create(
            model=model, max_tokens=max_tokens, thinking={"type": "adaptive"},
            output_config={"effort": "medium"}, system=system,
            messages=[{"role": "user", "content": user}])
        return next(b.text for b in resp.content if b.type == "text")
    if provider == "claude_cli":
        # user 는 stdin 으로 — argv 로 넘기면 32,767자에서 WinError 206(_claude_cli_text 주석)
        return _claude_cli_text(user, system, model)
    raise RuntimeError("생성 provider 없음 — ANTHROPIC_API_KEY 또는 claude CLI 필요")


# 구조화 출력 스키마 — Claude 가 이 형태로만 반환(output_config.format).
# 날짜·저자·slug·canonical 은 모델이 아니라 시스템이 채운다(날조 방지) → 스키마에 없음.
_CONTENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "dek": {"type": "string"},
        "page_type": {"type": "string", "enum": ["comparison", "listicle", "guide", "alternatives"]},
        "intro_html": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"heading": {"type": "string"}, "html": {"type": "string"}},
            "required": ["heading", "html"]}},
        "comparison": {"type": ["object", "null"], "additionalProperties": False,
            "properties": {"a": {"type": "string"}, "b": {"type": "string"},
                "rows": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"feature": {"type": "string"}, "a": {"type": "string"},
                        "b": {"type": "string"}, "winner": {"type": ["string", "null"]}},
                    "required": ["feature", "a", "b", "winner"]}}},
            "required": ["a", "b", "rows"]},
        "pricing": {"type": ["array", "null"], "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "price": {"type": "string"},
                "features": {"type": "array", "items": {"type": "string"}},
                "cta": {"type": ["object", "null"], "additionalProperties": False,
                    "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                    "required": ["label", "url"]}},
            "required": ["name", "price", "features", "cta"]}},
        "pros_cons": {"type": ["array", "null"], "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": {"type": "string"},
                "pros": {"type": "array", "items": {"type": "string"}},
                "cons": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "pros", "cons"]}},
        "tldr_html": {"type": ["string", "null"]},
        "feature_matrix": {"type": ["object", "null"], "additionalProperties": False,
            "properties": {"a": {"type": "string"}, "b": {"type": "string"},
                "rows": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"label": {"type": "string"},
                        "a": {"type": "string"}, "b": {"type": "string"},
                        "note": {"type": ["string", "null"]}},
                    "required": ["label", "a", "b", "note"]}}},
            "required": ["a", "b", "rows"]},
        "verdict_html": {"type": "string"},
        "sources": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
            "required": ["title", "url"]}},
        "related": {"type": ["array", "null"], "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
            "required": ["title", "url"]}},
        "faq": {"type": ["array", "null"], "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
            "required": ["q", "a"]}},
    },
    "required": ["title", "dek", "page_type", "intro_html", "sections", "comparison",
                 "pricing", "pros_cons", "tldr_html", "feature_matrix",
                 "verdict_html", "sources", "related", "faq"],
}

_SYSTEM = """You are an editor for an independent software-comparison site (SaaS, developer, and AI tools) for an English-speaking audience.
Write useful, original content that satisfies search intent. Rules:
- E-E-A-T: be specific and accurate. Cite official sources (the vendors' own sites). Do NOT invent precise volatile facts — exact prices, exact benchmark numbers, or stats you are unsure of. Describe pricing as tiers (e.g. "free tier + paid Pro") and tell readers to confirm current pricing on the vendor's site.
- TITLE CONTRACT: the title may promise only what the body delivers. If the title says "best", "cheapest", "top N" or otherwise ranks, the body MUST (a) state the selection criteria explicitly and (b) name a specific pick per use case in tldr_html and verdict_html. If the material does not let you rank honestly, do not hedge inside a superlative title — change the title ("How to choose ...", "... compared"). A title that ranks over a body saying "there is no single best/cheapest" is a misleading headline.
- NEGATIVE CLAIMS about a named product ("X does not support Y", "X lacks Y", "X has no Z", or the same thing implied): only when a cited page positively establishes the absence, and always scoped and dated — "the pricing page listed no managed database as of the observation date given in the prompt". Otherwise drop the claim. Do not describe one vendor from cited pages and its competitor from memory.
- VOLATILE FACTS: every price, plan name, quota, limit, model/region count and benchmark figure in prose carries an as-of date (use the observation date given in the prompt) and traces to a vendor page cited in sources. Third-party benchmark and customer-result stats ("customer X saw 67% lower cost", "2x throughput") are marketing claims — leave them out unless the vendor's own cited page carries them, and then attribute them to that page rather than stating them as measured fact.
- FAQ: include 2-4 faq entries (q/a) answering real follow-up questions a searcher would ask (e.g. "Is X free?", "Can I switch from X to Y?"). Concise, factual, no fluff — these render as an FAQ section and FAQPage structured data.
- Structure: at least 4 substantive sections. For comparisons include: a one-line tldr_html verdict; a comparison table (real differentiating features, set winner to 'a'/'b'/null); a feature_matrix where each row's a/b is exactly one of "✓" (full), "△" (partial/paid), or "✗" (none), with an optional footnote in note; tiered pricing; pros/cons per option; and a clear, evidence-based verdict_html.
- NO false experience: do NOT claim first-person testing or personal use you did not perform (never write "after working with both", "I tested for weeks", "in my experience", "a joy to use"). Write from documented features and typical workflows. Do NOT state absolute superlatives ("the best", "#1", "fastest") as fact — attribute them or frame as opinion.
- NO PIPELINE LANGUAGE: write for a reader who knows nothing about how this page was produced. Never mention fetching, scraping, excerpts, drafts, "the text reviewed", or supplied/provided source material ("the fetched text", "the supplied sources", "in the version reviewed", "as delivered", "[SOURCE 1]"). Name the vendor page and the date instead. Never promise a scoring or marking system you do not actually output ("marks and descriptions below"). Never point at page positions ("the table below", "listed above", "the sources section at the end") — the site template, not you, decides where the tables, the verdict and the sources land; refer to sections by name.
- VOICE: vary sentence length and paragraph openings. Do NOT (a) close sections with an aphoristic one-liner, (b) repeat the "X, not Y" / "not X, but Y" antithesis, (c) open sections with counted lists ("Five things move the real cost...", "Three situations regularly end with..."), (d) comment on the article itself ("this guide takes a different angle", "read those two paragraphs together", "most comparison articles admit"), (e) put an em-dash aside in most paragraphs, or (f) use the word "genuine" or "genuinely". Never use these AI-cliché words/phrases: "in today's fast-paced world", "whether you're X or Y", "it's worth noting" (or variants like "worth stating outright"), "look no further", "delve", "elevate", "robust", "seamless", "game-changer".
- HTML fields (*_html): simple semantic HTML only — <p>, <strong>, <em>, <ul>, <li>, <h3>. NO <script>, NO inline styles, NO ad/clickbait language, NO "click the ad". Styling is handled by the site theme.
- Neutral, trustworthy, editorial tone. No fabricated testimonials or reviews. Output must match the provided JSON schema exactly."""


def _via_api(topic: str, content_cfg: dict, *, feedback: str | None = None, grounding: str = "") -> ContentSpec:
    """ANTHROPIC_API_KEY 사용 시 Claude(claude-opus-4-8)로 ContentSpec 생성 — 구조화 출력."""
    try:
        import anthropic  # SDK는 이 경로에서만 필요(드라이런 fixture는 불필요)
    except ImportError as e:
        raise RuntimeError("anthropic SDK 미설치 — `pip install anthropic` (requirements.txt)") from e

    gen = content_cfg.get("generation", {})
    model = gen.get("model", "claude-opus-4-8")
    language = gen.get("language", "en")
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수에서 인증

    user = _user_prompt(topic, language, feedback=feedback, grounding=grounding)

    resp = client.messages.create(
        model=model,
        max_tokens=16000,                       # 비스트리밍 안전 한도(타임아웃 회피)
        thinking={"type": "adaptive"},          # opus-4-8: adaptive only (budget_tokens 금지)
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _CONTENT_SCHEMA}},
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":           # 안전 분류기 거절 → 파이프라인이 스킵
        raise RuntimeError(f"content generation refused: {getattr(resp, 'stop_details', None)}")

    text = next(b.text for b in resp.content if b.type == "text")  # thinking 블록 뒤의 text
    data = json.loads(text)                     # output_config.format 가 유효 JSON 보장
    return _dict_to_spec(topic, data, content_cfg)


def _dict_to_spec(topic: str, d: dict, content_cfg: dict) -> ContentSpec:
    """모델 출력(dict) → ContentSpec. 날짜·저자·slug·canonical 은 시스템이 채움."""
    gen = content_cfg.get("generation", {})
    title = d.get("title") or topic
    slug = renderer.slugify(title)
    today = datetime.date.today().isoformat()   # 모델이 아니라 시스템 날짜
    domain = "stack.utilverse.info"
    words = len(_strip(d.get("intro_html", "") + " " + " ".join(s.get("html", "") for s in d.get("sections", []))).split())
    return ContentSpec(
        slug=slug, title=title, dek=d["dek"], page_type=d.get("page_type", "comparison"),
        breadcrumb=[("Home", "/"), ("Compare", "/compare/"), (title, "")],
        author=gen.get("author", "The stack. editors"),
        author_bio="Independent software comparisons from official docs and public data.",
        published_at=today, updated_at=today, reading_time=max(3, round(words / 200)),
        canonical=f"https://{domain}/compare/{slug}/",
        intro_html=d["intro_html"], sections=d["sections"],
        comparison=d.get("comparison"), pricing=d.get("pricing"),
        pros_cons=d.get("pros_cons"), verdict_html=d.get("verdict_html"),
        tldr_html=d.get("tldr_html"), feature_matrix=d.get("feature_matrix"),
        sources=d.get("sources", []), related=d.get("related") or [],
        faq=d.get("faq") or [],
    )


def _extract_json(text: str) -> dict:
    """모델 텍스트에서 JSON 추출 — 코드펜스/잡음 제거 후 최외곽 {..} 파싱(스키마 강제 없는 CLI용)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    a, b = t.find("{"), t.rfind("}")
    if a != -1 and b != -1 and b > a:
        t = t[a:b + 1]
    return json.loads(t)


def _via_claude_cli(topic: str, content_cfg: dict, *, feedback: str | None = None,
                    grounding: str = "") -> ContentSpec:
    """Claude Code 헤드리스(구독 로그인)로 ContentSpec 생성 — API 키 불필요.

    `claude -p --append-system-prompt <sys> --output-format json --model <m>` (프롬프트는 stdin).
    API의 output_config.format(스키마 강제)이 없으므로 프롬프트로 JSON-only 요구 + 견고 파싱.
    """
    gen = content_cfg.get("generation", {})
    model = gen.get("model", "claude-opus-4-8")
    language = gen.get("language", "en")
    schema_str = json.dumps(_CONTENT_SCHEMA, ensure_ascii=False)
    user = (_user_prompt(topic, language, feedback=feedback, grounding=grounding)
            + "\n\nReturn ONLY a single JSON object — no markdown, no code fences, no commentary — "
              "that strictly matches this JSON schema (every required key present; nullable fields "
              "may be null):\n" + schema_str)
    # 프롬프트(그라운딩 최대 12,000자 + 스키마)는 stdin 으로 — argv 였다면 WinError 206.
    # stdin 상속 금지 보호는 그대로다(_claude_cli_text 주석: PIPE 를 새로 열고 쓴 뒤 닫는다).
    text = _claude_cli_text(user, _SYSTEM, model)
    data = _extract_json(text)
    return _dict_to_spec(topic, data, content_cfg)


# ── fixture (오프라인 드라이런) ─────────────────────────────────────────────
def _fixture(topic: str) -> ContentSpec:
    if slug_topic(topic) == "cursor-vs-github-copilot":
        return _cursor_vs_copilot()
    return _generic_comparison(topic)


def slug_topic(topic: str) -> str:
    return renderer.slugify(topic)


def _cursor_vs_copilot() -> ContentSpec:
    return ContentSpec(
        slug="cursor-vs-github-copilot",
        title="Cursor vs GitHub Copilot: Which AI Coding Assistant Wins in 2026?",
        dek="A comparison of pricing, features, and real-world workflow — so you can pick the right AI coding assistant for your stack.",
        page_type="comparison",
        breadcrumb=[("Home", "/"), ("AI Coding", "/ai-coding/"), ("Cursor vs GitHub Copilot", "")],
        author="The stack. editors",
        author_bio="Independent software comparisons from official docs and public data.",
        published_at="2026-06-28", updated_at="2026-06-28", reading_time=8,
        canonical="https://stack.utilverse.info/ai-coding/cursor-vs-github-copilot/",
        intro_html=(
            "<p>Both <strong>Cursor</strong> and <strong>GitHub Copilot</strong> bring AI into your editor, "
            "but they take different shapes: Cursor is an AI-first editor (a VS Code fork) built around the "
            "chat-and-edit loop, while Copilot is an extension that layers completions and chat onto editors "
            "you already use. That single architectural choice ripples through everything else — how much context "
            "the AI can see, how disruptive it is to adopt, and how it fits an existing team. Here is how they "
            "compare on refactors and greenfield work, based on each vendor's documented features.</p>"
        ),
        sections=[
            {"heading": "What they are",
             "html": "<p>Cursor ships as a standalone editor with deep, repo-aware AI editing and an agent mode. "
                     "Because it owns the whole editing surface, it can index your codebase and reason across many "
                     "files at once. GitHub Copilot is an extension for VS Code, JetBrains, Neovim and others, with inline "
                     "completions and Copilot Chat; it meets you inside the editor you have already configured. "
                     "If you are committed to your current tools, that difference matters more than any single feature.</p>"},
            {"heading": "Workflow & developer experience",
             "html": "<p>Cursor's strength is multi-file, context-aware edits and its agent loop — useful for larger "
                     "changes that touch several modules at once. Copilot excels at fast, low-friction inline completions inside the tools teams already "
                     "standardize on, so there is nothing new to learn. On a repo-wide refactor, Cursor's indexed context is the documented "
                     "differentiator; for day-to-day typing, Copilot's inline completions are the documented strength. "
                     "Which one feels faster depends on whether your work skews toward broad refactors or steady incremental edits.</p>"},
            {"heading": "Models & integrations",
             "html": "<p>Both offer access to frontier models and chat. Copilot benefits from tight GitHub/PR integration, so it can draw on "
                     "pull-request context and fits naturally into GitHub-centric review flows; "
                     "Cursor focuses the experience inside its editor and exposes model choices directly in the interface. "
                     "Check each vendor's current model list before deciding — model availability and limits change often, "
                     "and the specific models on offer can be the deciding factor for heavier tasks.</p>"},
            {"heading": "Who should pick which",
             "html": "<p>Pick <strong>Cursor</strong> if you want an AI-first editor and frequent multi-file edits. "
                     "Pick <strong>Copilot</strong> if you want to stay in your existing editor and value GitHub-native flow.</p>"},
        ],
        comparison={
            "a": "Cursor", "b": "GitHub Copilot",
            "rows": [
                {"feature": "Form factor", "a": "Standalone AI editor (VS Code fork)", "b": "Extension for existing editors", "winner": None},
                {"feature": "Multi-file / agent edits", "a": "Strong, repo-aware", "b": "Improving", "winner": "a"},
                {"feature": "Editor flexibility", "a": "Cursor only", "b": "VS Code, JetBrains, Neovim…", "winner": "b"},
                {"feature": "GitHub / PR integration", "a": "Good", "b": "Native", "winner": "b"},
                {"feature": "Free tier", "a": "Yes (limited)", "b": "Yes (limited)", "winner": None},
            ],
        },
        pricing=[
            {"name": "Cursor", "price": "Free / paid tiers", "features": ["Free hobby tier", "Paid Pro tier", "Team plans"],
             "cta": {"label": "See Cursor pricing", "url": "https://cursor.com/pricing"}},
            {"name": "GitHub Copilot", "price": "Free / paid tiers", "features": ["Free tier", "Pro for individuals", "Business / Enterprise"],
             "cta": {"label": "See Copilot pricing", "url": "https://github.com/features/copilot/plans"}},
        ],
        pros_cons=[
            {"name": "Cursor", "pros": ["AI-first, repo-aware editing", "Strong multi-file agent flow"],
             "cons": ["Must switch editors", "Heavier learning curve"]},
            {"name": "GitHub Copilot", "pros": ["Works in your existing editor", "Native GitHub/PR flow"],
             "cons": ["Less opinionated multi-file editing", "Best value inside GitHub ecosystem"]},
        ],
        verdict_html=(
            "<p>There is no single winner — it depends on your workflow. For AI-heavy, multi-file work in a "
            "dedicated editor, <strong>Cursor</strong> is compelling. To stay in your current editor with GitHub-native "
            "integration, <strong>Copilot</strong> is the safer pick. Try both free tiers on a real task before committing.</p>"
            "<p><em>Pricing and model availability change frequently — confirm current details on each vendor's site.</em></p>"
        ),
        tldr_html=("<p>Pick <strong>Cursor</strong> for an AI-first editor with heavy multi-file edits; "
                   "pick <strong>GitHub Copilot</strong> to stay in your current editor with GitHub-native flow.</p>"),
        feature_matrix={"a": "Cursor", "b": "GitHub Copilot", "rows": [
            {"label": "Inline completions", "a": "✓", "b": "✓", "note": None},
            {"label": "Multi-file agent edits", "a": "✓", "b": "△", "note": None},
            {"label": "Works in your existing editor", "a": "✗", "b": "✓", "note": None},
            {"label": "Native GitHub / PR flow", "a": "△", "b": "✓", "note": None},
            {"label": "Free tier", "a": "✓", "b": "✓", "note": None},
        ]},
        sources=[
            {"title": "Cursor — official site", "url": "https://cursor.com"},
            {"title": "GitHub Copilot — official site", "url": "https://github.com/features/copilot"},
        ],
        related=[
            {"title": "Claude Code vs Cursor", "url": "/ai-coding/claude-code-vs-cursor/"},
            {"title": "Best GitHub Copilot alternatives", "url": "/ai-coding/github-copilot-alternatives/"},
        ],
        faq=[
            {"q": "Is Cursor or GitHub Copilot free?",
             "a": "Both offer a free tier and paid plans. Cursor has a free hobby tier plus a paid Pro plan; "
                  "GitHub Copilot has a free tier plus Pro, Business, and Enterprise plans. Confirm current "
                  "limits on each vendor's pricing page, as free-tier caps change."},
            {"q": "Can I use GitHub Copilot inside my existing editor?",
             "a": "Yes. Copilot is an extension for VS Code, Visual Studio, JetBrains IDEs, Neovim, and more, "
                  "so you keep your current setup. Cursor is a standalone editor, so adopting it means switching editors."},
            {"q": "Which is better for large multi-file changes?",
             "a": "Cursor is designed around repo-aware, multi-file edits and an agent mode, which suits larger "
                  "refactors. Copilot also has an agent mode but is strongest at fast inline completions in your existing tools."},
        ],
    )


def _generic_comparison(topic: str) -> ContentSpec:
    """'A vs B' 형태 시드용 일반 초안 골격 (드라이런 — 실데이터는 API/핸즈온으로 대체)."""
    m = re.split(r"\s+vs\.?\s+", topic, flags=re.I)
    a, b = (m[0].strip().title(), m[1].strip().title()) if len(m) == 2 else (topic.title(), "Alternatives")
    slug = renderer.slugify(topic)
    return ContentSpec(
        slug=slug, title=f"{a} vs {b}: Comparison (2026)",
        dek=f"A comparison of {a} and {b} — pricing, features, and which to choose.",
        page_type="comparison",
        breadcrumb=[("Home", "/"), ("Compare", "/compare/"), (f"{a} vs {b}", "")],
        author="The stack. editors",
        author_bio="Independent software comparisons from official docs and public data.",   # 허위 '핸즈온' 주장 제거
        published_at="2026-06-28", updated_at="2026-06-28", reading_time=6,
        canonical=f"https://stack.utilverse.info/compare/{slug}/",
        intro_html=f"<p>How do <strong>{a}</strong> and <strong>{b}</strong> compare? We weigh features, pricing and fit.</p>",
        sections=[
            {"heading": "Overview", "html": f"<p>{a} and {b} target similar needs with different trade-offs.</p>"},
            {"heading": "Key differences", "html": "<p>The table below summarizes where each tool leads.</p>"},
            {"heading": "Who should choose which", "html": f"<p>Pick {a} or {b} based on your workflow and budget.</p>"},
        ],
        comparison={"a": a, "b": b, "rows": [
            {"feature": "Best for", "a": f"{a} use case", "b": f"{b} use case", "winner": None},
            {"feature": "Pricing", "a": "Free / paid", "b": "Free / paid", "winner": None},
        ]},
        pros_cons=[{"name": a, "pros": ["Pro 1", "Pro 2"], "cons": ["Con 1"]},
                   {"name": b, "pros": ["Pro 1", "Pro 2"], "cons": ["Con 1"]}],
        verdict_html=f"<p>Both are solid; choose {a} or {b} by fit. Confirm current pricing on each vendor's site.</p>",
        tldr_html=f"<p>Choose <strong>{a}</strong> or <strong>{b}</strong> based on your workflow and budget.</p>",
        feature_matrix={"a": a, "b": b, "rows": [
            {"label": "Free tier", "a": "✓", "b": "✓", "note": None},
            {"label": "Best-in-class for its core use", "a": "✓", "b": "△", "note": None},
        ]},
        sources=[{"title": f"{a} — official", "url": "https://example.com"},
                 {"title": f"{b} — official", "url": "https://example.com"}],
    )
