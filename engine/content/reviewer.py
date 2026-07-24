"""reviewer.py — 발행 전 콘텐츠 검수 게이트 (사용자 방침: 항상 리뷰 스킬로 QC).

.claude/skills/adsense-review 루브릭 자동화: AI 티·사실/맥락·법적(허위 1인칭 경험·명예훼손·
과장 단정·상표·YMYL)·AdSense 정책·논리 일관성. provider(claude_cli/api)로 비평 → JSON 판정.
high(법적·허위·정책) → REJECT. 통과분만 발행 큐로.
"""
from __future__ import annotations
import glob
import html as _html
import os
import re

from content import generator

# ── 검수기가 '보는 입력'의 상한 (판정 기준 아님 — 입력이 잘리면 검수기가 절단을 글의 결함으로 오인) ──
# 실측(2026-07-24): 발행 28편의 평문 길이 9,969~15,417자 → 구 상한 12,000 은 16편을 잘랐고,
# 그중 VERDICT 를 통째로 못 본 글 10편·SOURCES 를 못 본 글 14편(= 검수 사각지대). 40,000 은 충분한 여유.
_MAX_REVIEW_CHARS = 40000
# 소스 그라운딩: 생성기는 grounding[:12000] 을 보고 쓰는데(generator._user_prompt) 검수기는 [:5000] 만 봤다 →
# 글이 실제 소스에 근거해 쓴 사실을 검수기가 "소스에 없음"으로 오판. 검수기는 최소한 생성기 이상을 봐야 한다.
# max_sources(5) × max_chars_per_source(3500) = 17,500 을 덮는 값.
_MAX_GROUND_CHARS = 20000


def _cut_note(limit: int, what: str) -> str:
    """절단이 실제로 일어났을 때만 붙는 표식 — 검수기가 도구의 절단을 글의 결함으로 오인하지 않게."""
    return (f"\n\n[!! CUT BY THE REVIEW TOOL — NOT BY THE AUTHOR. The {what} above was cut here because it "
            f"exceeded this tool's {limit:,}-character limit. This cut is an artifact of the review harness. "
            "Do NOT report the article as truncated, incomplete, unfinished or 'ends mid-sentence' because of "
            "this marker, and do not treat missing later sections as a defect. Judge only the text shown.]")


def _clip(text: str, limit: int, what: str) -> str:
    return text if len(text) <= limit else text[:limit] + _cut_note(limit, what)


# 블록 종료 태그 → 개행. 공백으로만 치환하면 <li>·<p> 경계가 사라져 목록이 한 줄로 뭉개지고,
# 검수기가 그 붕괴를 글의 마크업 결함("run-on prose")으로 오인한다.
_BLOCK_END = re.compile(
    r"</(?:p|li|ul|ol|h[1-6]|tr|div|section|article|blockquote|dd|dt|dl|table|thead|tbody|tfoot|caption"
    r"|figure|figcaption|pre|address)\s*>|<(?:br|hr)\s*/?>", re.I)
_CELL_END = re.compile(r"</t[dh]\s*>", re.I)


# ── 광고·제휴 고지 요구의 조건부화 (ORDER 2026-07-24-12) ───────────────────────────────────
# 문제(실측 2026-07-24): 루브릭이 "missing affiliate/ad disclosure" 를 무조건 적용해 보존된 검수 판정
#   50건 중 38건이 이 지적을 냈다. 그런데 이 사이트에는 광고 코드도 제휴 링크도 없다
#   (dist/site 39페이지·렌더러 소스 전수 스캔 0건). 없는 상업관계를 고지하면 그 고지 자체가 허위 진술이 된다.
# 처리: 항목을 **삭제하지 않고** 실제 수익화 상태에 **연동**한다. 상태는 추측이 아니라 관측한다 —
#   ① 렌더 템플릿·빌드 산출물의 광고 네트워크 코드, ② 초안 자체의 제휴/추천 링크, ③ 명시 선언(켜는 방향만).
#   광고 코드나 제휴 링크가 들어오는 순간 스캔이 잡아내 요구가 **자동으로 되살아난다**(사람이 잊어도 켜진다).
# ⚠️ 이 조건부화는 '고지' 항목 하나에만 적용된다. Privacy Policy(F2)·클릭 유도 문구(F3)·금지 주제·
#   사실/법적/일관성 검사는 수익화 상태와 무관하게 항상 그대로 유효하다.
# ⚠️ 조건부화가 **작동하는 지점은 프롬프트 하나뿐**이다(`_system`: 미게재면 고지 절을 빼고 준다).
#   후처리(`_apply_disclosure_policy`)는 ORDER 2026-07-25-19 이후 **판정을 건드리지 않는다** —
#   지적에 not_applicable 표식을 달아 보존할 뿐이고, `passed`·`severity` 는 검수기 원본 그대로다.

# 광고 네트워크 '코드'만 매칭한다. 자리표시자(.ad-slot / data-ad-slot, renderer.py:318 — 텍스트 "Advertisement"
# 뿐이고 어떤 광고도 로드하지 않음)는 광고가 아니므로 의도적으로 제외한다.
_AD_CODE_RE = re.compile(
    r"adsbygoogle|googlesyndication\.com|data-ad-client|ca-pub-\d{6}|amazon-adsystem\.com"
    r"|doubleclick\.net|adservice\.google\.|ezoic\.net|adthrive\.com|mediavine\.com|raptive\.com", re.I)

# 제휴/추천 링크. 오탐이 큰 일반 파라미터(`ref=`, `source=`, `utm_*`)는 일부러 넣지 않는다 —
# 벤더 문서 링크에 흔해서 그것만으로 '수익화'라고 볼 수 없다.
_AFFILIATE_RE = re.compile(
    r"amzn\.to/|amazon\.[a-z.]{2,6}/[^\s\"'<>]*[?&]tag=[\w.-]+-\d{2}"
    r"|shareasale\.com|awin1\.com|anrdoezrs\.net|dpbolvw\.net|tkqlhce\.com|jdoqocy\.com|kqzyfj\.com"
    r"|linksynergy\.com|clickbank\.net|avantlink\.com|partnerize\.|impact\.com/c/|refersion\.com"
    r"|rewardful\.|firstpromoter\.com|partnerstack\.com|tolt\.io"
    r"|[?&](?:aff|affid|aff_id|affiliate|affiliate_id|a_aid|irclickid|irgwc|ranMID|clickid|subid|partner_id|via)=",
    re.I)

# 스캔 경로는 **cwd 가 아니라 리포 루트 기준**으로 잡는다 (ORDER 2026-07-25-18 ③).
# 구현 전 실측: cwd 가 리포 밖이면 `0 render template file(s) + 0 built page(s)` 를 읽고도
# "광고 없음"으로 단정해 고지 지적을 강등했다(= fail-open). 0파일은 '없다'가 아니라 '모른다'다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RENDER_SOURCES = ("engine/content/renderer.py", "engine/content/site_builder.py")
_SITE_GLOB = "dist/site/**/*.html"
_SITE_SCAN_CAP = 400                     # 산출물이 커져도 검수가 느려지지 않게 스캔 파일 수 상한
_site_scan_cache: dict[str, dict] = {}   # cwd 별 캐시 (cwd 가 바뀌면 관측도 달라진다)


def _scan_text(name: str, text: str) -> tuple[str, str]:
    """(광고코드 증거, 제휴링크 증거) — 없으면 빈 문자열."""
    a = _AD_CODE_RE.search(text or "")
    f = _AFFILIATE_RE.search(text or "")
    return (f"{name}: {a.group(0)!r}" if a else "", f"{name}: {f.group(0)!r}" if f else "")


def _scan_roots() -> list[str]:
    """스캔 기준 디렉터리 — 리포 루트가 1순위, cwd 는 추가로(합집합) 본다.

    합집합인 이유: 소스가 복사·배포된 위치에서 실행돼도 광고 코드를 **더** 잡을 뿐 덜 잡지 않는다
    (탐지 방향이 항상 엄격 쪽). 중복은 realpath 로 제거."""
    roots, seen = [], set()
    for r in (_REPO_ROOT, os.getcwd()):
        try:
            key = os.path.realpath(r)
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            roots.append(r)
    return roots


def _scan_site(refresh: bool = False) -> dict:
    """사이트 수준 관측 — 렌더 템플릿 소스 + 빌드 산출물에 광고 코드/제휴 링크가 있는가.

    렌더러 소스까지 보는 이유: dist 가 아직 없는 환경(초회 실행·서버 재빌드 전)에서도 판정이 결정적이어야 한다.
    광고를 넣으려면 반드시 이 소스가 광고 태그를 뿜도록 바뀌므로, 소스 스캔이 선행 지표가 된다.

    ⚠️ 템플릿을 **한 개도 못 찾으면** 관측 자체가 실패한 것이다 → `templates=0` 을 그대로 실어 보내
    상위(`monetization_state`)가 '모름(fail-closed)' 으로 처리하게 한다."""
    ck = os.path.realpath(os.getcwd())
    if not refresh and ck in _site_scan_cache:
        return _site_scan_cache[ck]
    tmpl, built = [], []
    for root in _scan_roots():
        tmpl += [os.path.join(root, p) for p in _RENDER_SOURCES
                 if os.path.exists(os.path.join(root, p))]
        built += sorted(glob.glob(os.path.join(root, _SITE_GLOB), recursive=True))[:_SITE_SCAN_CAP]
    ads, aff = [], []
    for p in tmpl + built:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                a, x = _scan_text(os.path.relpath(p, _REPO_ROOT) if p.startswith(_REPO_ROOT) else p,
                                  f.read())
        except OSError:
            continue
        if a:
            ads.append(a)
        if x:
            aff.append(x)
    out = {"ads": ads, "affiliate": aff, "templates": len(tmpl), "built": len(built),
           "scanned": f"{len(tmpl)} render template file(s) + {len(built)} built page(s)"}
    _site_scan_cache[ck] = out
    return out


def _spec_raw(spec) -> str:
    """초안의 원본 텍스트(태그·URL 포함) — 링크 URL 을 봐야 제휴 링크를 판정할 수 있다."""
    bits = [str(getattr(spec, k, "") or "") for k in
            ("title", "dek", "tldr_html", "intro_html", "verdict_html")]
    for s in (getattr(spec, "sections", None) or []):
        bits.append(str((s or {}).get("html", "")))
    for f in (getattr(spec, "faq", None) or []):
        bits.append(str((f or {}).get("a", "")))
    for s in (getattr(spec, "sources", None) or []):
        bits.append(str((s or {}).get("url", "")))
    for p in (getattr(spec, "pricing", None) or []):
        bits.append(str(((p or {}).get("cta") or {}).get("url", "")))
    return "\n".join(bits)


def monetization_state(spec=None, content_cfg: dict | None = None) -> dict:
    """이 사이트/초안이 **지금 실제로** 수익화돼 있는가 — 관측 결과 + 근거.

    override 는 **켜는 방향으로만** 허용한다: 설정·환경변수는 고지 요구를 켤 수는 있어도 끌 수는 없다.
    끌 수 있는 것은 오직 '광고 코드도 제휴 링크도 관측되지 않는다'는 사실뿐이다(= 게이트를 낮추는 스위치 없음).
      · config/content.yaml:  monetization: {ads_live: true, affiliate_links: true}   ← 신설 제안(값 없으면 자동 관측)
      · 환경변수:             ADSENSE_MONETIZED=1                                     ← 임시 강제 ON

    반환 키 `known` (ORDER 2026-07-25-18 ③ — fail-closed):
      True  = 관측이 성립했다(렌더 템플릿을 실제로 읽었거나, 광고/제휴 증거를 직접 찾았다).
      False = **알 수 없다**(스캔 대상 0파일 등). 이때 `monetized=False` 는 "광고 없음"이 아니라
              "확인 못 함"이며, 호출부는 고지 요구를 **유지**해야 한다(강등 금지).
    """
    site = _scan_site()
    ev, ads, aff = [], False, False
    if site["ads"]:
        ads = True
        ev.append("ad-network code found — " + "; ".join(site["ads"][:3]))
    if site["affiliate"]:
        aff = True
        ev.append("affiliate link found in templates/built pages — " + "; ".join(site["affiliate"][:3]))
    if spec is not None:
        a, x = _scan_text("draft", _spec_raw(spec))
        if a:
            ads = True
            ev.append("ad-network code in the draft — " + a)
        if x:
            aff = True
            ev.append("affiliate/referral link in the draft — " + x)
    mon = ((content_cfg or {}).get("monetization") or {})
    if mon.get("ads_live") is True:
        ads = True
        ev.append("declared: config/content.yaml monetization.ads_live=true")
    if mon.get("affiliate_links") is True:
        aff = True
        ev.append("declared: config/content.yaml monetization.affiliate_links=true")
    if os.environ.get("ADSENSE_MONETIZED") == "1":
        ads = True
        ev.append("declared: env ADSENSE_MONETIZED=1")
    # 관측 성립 여부. 증거를 직접 찾았으면 당연히 성립. 아니면 '렌더 템플릿을 실제로 읽었는가'가 기준이다.
    known, warning = (True, "") if (ads or aff) else (site.get("templates", 0) > 0, "")
    if not known:
        warning = ("monetization NOT verifiable — the render templates were not found "
                   f"(scanned {site['scanned']}; repo root={_REPO_ROOT}, cwd={os.getcwd()}). "
                   "Treating the state as UNKNOWN: the ad/affiliate disclosure requirement stays in force.")
        ev.append(warning)
    elif not ev:
        ev.append(f"no ad-network code and no affiliate/referral link pattern in {site['scanned']}"
                  + (" or in this draft" if spec is not None else ""))
    return {"monetized": ads or aff, "ads": ads, "affiliate": aff, "known": known,
            "evidence": ev, "scanned": site["scanned"], "warning": warning}


_SYSTEM = (
    "You are a strict editorial AND legal reviewer for an independent software-comparison site. "
    "Catch: (1) AI-tells/cliches and unnatural filler — flag on sight if present (case-insensitive): "
    "\"in today's fast-paced world\", \"whether you're X or Y\", \"it's worth noting\", \"look no further\", "
    "\"delve\", \"elevate\", \"robust\", \"seamless\", \"game-changer\", plus any other unnatural filler/cliche "
    "even if not in this list, and all-paragraphs-same-rhythm writing; (2) factual or contextual errors and internal "
    "contradictions (table vs prose vs verdict), and unhedged volatile specifics (exact prices/benchmarks) "
    "stated as fact; (3) LEGAL risk — especially FALSE first-person experience claims (e.g. 'after working "
    "with both', 'I tested for 8 weeks', 'a joy to use') when the text was AI-generated without real testing; "
    "defamation/unverified negative claims about products; absolute superlatives ('best/cheapest/#1') stated "
    "as fact; trademark misuse; copyright; YMYL overreach; missing affiliate/ad disclosure; "
    "(4) AdSense policy (prohibited topics, deceptive, ad-clickbait); (5) coherence/usefulness. "
    "Be conservative: when in doubt, fail."
)

# 위 _SYSTEM 은 '수익화 상태'의 기준선 그대로다(한 글자도 바꾸지 않았다). 아래 절만 상태에 따라 붙였다 뗀다.
_DISCLOSURE_CLAUSE = "missing affiliate/ad disclosure; "

_NOT_MONETIZED_NOTE = (
    "\n\nMONETIZATION STATE — verified by the review harness at review time (an observation, not an assumption): "
    "this site currently serves NO advertising (no ad-network code in the page templates or the rendered pages) "
    "and this draft carries NO affiliate or referral links — outbound vendor links are plain informational "
    "citations. Evidence: {evidence}. "
    "Therefore do NOT raise a missing affiliate/advertising/monetization disclosure issue for this draft: "
    "publishing a disclosure of a commercial relationship that does not exist would itself be a false statement. "
    "This suspension covers the disclosure item ONLY, and only while that stays true. Everything else remains in "
    "full force — AdSense prohibited topics, deceptive content, any wording that solicits ad clicks, the "
    "site-level Privacy Policy requirement, and all factual, legal, trademark and coherence checks."
)

_MONETIZED_NOTE = (
    "\n\nMONETIZATION STATE — verified by the review harness at review time: this site IS monetized. "
    "Evidence: {evidence}. A clear, conspicuous affiliate/advertising disclosure is therefore REQUIRED on "
    "monetized recommendation content — flag its absence."
)

# 관측 실패(=알 수 없음) 전용. 고지 절을 **떼지 않는다** — 기준선 _SYSTEM 그대로에 경고만 덧붙인다.
_UNKNOWN_NOTE = (
    "\n\nMONETIZATION STATE — UNKNOWN: the review harness could not verify whether this site serves ads or "
    "affiliate links ({evidence}). Because absence could not be verified, the affiliate/advertising "
    "disclosure requirement above stays fully in force — judge it as you normally would."
)


def _system(state: dict) -> str:
    """수익화 상태에 따른 시스템 프롬프트. monetized=True 또는 known=False 면 기준선 _SYSTEM 과 동일하다."""
    ev = "; ".join(state.get("evidence") or []) or "n/a"
    if state.get("monetized"):
        return _SYSTEM + _MONETIZED_NOTE.format(evidence=ev)
    if not state.get("known"):            # fail-closed: 모르면 고지 절을 유지한다
        return _SYSTEM + _UNKNOWN_NOTE.format(evidence=ev)
    # 고지 절만 떼고, 왜 뗐는지·무엇은 그대로인지 명시한다(모델이 스스로 되살리지 않도록).
    return _SYSTEM.replace(_DISCLOSURE_CLAUSE, "") + _NOT_MONETIZED_NOTE.format(evidence=ev)


# ── 고지 지적의 '표식' 식별 — 판정 경로가 아니다 (ORDER 2026-07-25-19) ─────────────────────────
# 폐기된 것: **정규식으로 자유 텍스트를 분류해 `passed` 를 뒤집는 기전 전체.**
#   12 rev1(문장 단위 면제) → 12 rev2(블록리스트 `_OTHER_RISK`) → 18(얼라우리스트 `_out_of_scope`
#   /`_GENERIC_OK`/`_DOMAIN_VOCAB`) — 세 번 모두 감사자가 **새 표현**으로 다시 뚫었다.
#   18 감사 실측: 창작 21종 중 13종이 flip. 13종에는 허위 1인칭 실사용·저작권 복제·YMYL 건강 지시·
#   경쟁사 부정 단정·광고 클릭 유도(F3 인접)가 전부 포함됐다. 구현 실력이 아니라 **기전 선택**의 문제다.
#
# 그 기전이 실제로 필요했는가 — 아니다:
#   ① 오탐 해소의 본체는 **프롬프트 조건화**(`_system`)다. 미게재 시 고지 절을 아예 빼고 검수기에 준다
#      → 요구하지 않은 것을 모델이 지적할 일 자체가 줄어든다. 이건 그대로 살아 있다.
#   ② 실코퍼스 리플레이에서 `passed` 뒤집힘은 **0건**이었다(= "고지가 유일한 반대 사유"인 경우는
#      관측된 적이 없다). 이득 0 · 리스크는 법적 리스크 글의 자동 발행 → 비대칭이 명확하다.
#
# 그래서 아래 두 검사는 **사람이 읽는 표식**을 보수적으로 달기 위한 것뿐이다.
# 틀려도(달거나 못 달거나) `passed`·`severity` 는 바뀌지 않는다 — `_apply_disclosure_policy` 참조.
#   ① `_ABSENCE_OF_DISCLOSURE` — '광고·제휴 고지의 부재'를 말하는 문형인가
#   ② `_OTHER_RISK`            — 고지 외 리스크 어휘가 섞였으면 표식을 달지 않는다(표식도 보수적으로)
# 삭제된 판정 장치: `_out_of_scope` · `_GENERIC_OK` · `_DOMAIN_VOCAB` · `_SEGMENT_SPLIT` ·
#   `_STOPWORDS` · `_WORD` · `_segments` · `_unknown_words` · `passed` 뒤집기 직전의 재유도 가드.
#   (재유도 가드는 뒤집을 판정 자체가 없어졌으므로 존재 이유가 사라졌다.)

# 고지의 '대상' — 광고/제휴 어휘와 disclos* 가 서로 근접해야 한다("privacy disclosure" 같은 무관 결합 배제).
_DISCLOSURE_OBJ = (
    r"(?:(?:affiliate|advertis\w*|ads?|adsense|sponsor\w*|monetiz\w*|monetis\w*|commission|referral"
    r"|relationship)[\w\s,'’/&()\-]{0,40}?disclos\w*"
    r"|disclos\w*[\w\s,'’/&()\-]{0,40}?(?:affiliate|advertis\w*|ads?|sponsor\w*|monetiz\w*|monetis\w*"
    r"|commission|referral))")

# ① 부재 문형 + 고지 대상. 문장부호를 넘지 않게([^.;!?]) 묶어 다른 문장의 부정어와 결합하지 못하게 한다.
# 두 어순을 모두 받는다: 부재어가 앞("no … disclosure") / 뒤("the disclosure is absent").
# 후치형의 창(25자)을 좁게 잡은 이유: 넓히면 "…discloses affiliate commissions …, which the source
# does not support"(= 고지 누락이 아니라 사실오류) 가 부재 문형으로 오인된다(실측으로 확인).
_ABSENCE_OF_DISCLOSURE = re.compile(
    r"(?:\bno\b|\bnot\b|\bnone\b|\bnever\b|\bnowhere\b|\bwithout\b|\bmissing\b|\bmisses\b|\blacks?\b"
    r"|\blacking\b|\babsent\b|\babsence\b|\bomits?\b|\bomitted\b|\bomission\b|\bfails?\s+to\b"
    r"|\bfailing\s+to\b|\bneither\b|\bnor\b)"
    r"[^.;!?]{0,80}?" + _DISCLOSURE_OBJ
    + r"|" + _DISCLOSURE_OBJ + r"[^.;!?]{0,25}?\b(?:is|are|was|were|remains?)\s+"
    r"(?:(?:not|never)\s+(?:present|included|shown|rendered|disclosed|stated|visible|there)"
    r"|missing|absent|lacking|omitted)\b", re.I)


def _issue_text(issue: dict) -> str:
    return f"{issue.get('detail', '')} {issue.get('fix', '')}"


def _has_disclosure_absence(text: str) -> bool:
    """① 부재 문형 + 고지 대상이 실제로 있는가."""
    return bool(_ABSENCE_OF_DISCLOSURE.search(text or ""))


# ② 표식 억제용 어휘(옛 rev2 의 주 기전). 목록 밖 표현은 못 잡는다 — 그래서 판정 근거로는 폐기됐다.
# 지금은 "고지 외 리스크가 섞인 지적에는 not_applicable 표식을 달지 않는다"는 **라벨링 보수성**에만 쓴다.
# `privacy policy`(F2)·클릭 유도/무효 트래픽(F3) 어휘는 ORDER 2026-07-24-12 24행이 "그대로 유지"를
# 요구한 항목이라 그대로 둔다.
_OTHER_RISK = re.compile(
    r"contradict|fabricat|defam|trademark|copyright|prohibit|deceptive|clickbait|first[- ]person|"
    r"superlativ|unverified|unhedged|inaccurat|incorrect|misleading|plagiar|privacy policy|"
    r"not (?:appear|found|backed|supported)|"
    r"solicit\w*|invalid traffic|self[- ]click|click[\w\s]{0,20}\bads?\b|\bads?\b[\w\s]{0,20}clicks?\b", re.I)


def _has_other_risk(issue: dict) -> bool:
    """고지 외 리스크 어휘가 지적 **어디에든** 있는가 — detail+fix 전체 텍스트 검사.

    ⚠️ 문장 단위로 쪼개 검사하지 말 것(rev1 의 구멍, PM 감사 2026-07-24): '고지 구절이 든 문장'을
    이 검사에서 면제하면 고지와 실질 리스크가 한 문장에 섞였을 때 지적 전체에 표식이 붙는다.
    지금은 판정이 걸려 있지 않으므로 최악이라도 '표식 오부착'이지만, 사람이 읽는 라벨이므로
    보수적으로 유지한다. 회귀 방지: engine/content/reviewer_selftest.py
    """
    return bool(_OTHER_RISK.search(_issue_text(issue)))


def _is_disclosure_only(issue: dict) -> bool:
    """이 지적이 '광고·제휴 고지 없음' 하나만 말하는 것으로 **보이는가** (표식용 판별, 판정 아님)."""
    text = _issue_text(issue)
    return _has_disclosure_absence(text) and not _has_other_risk(issue)


def _apply_disclosure_policy(data: dict, state: dict) -> dict:
    """'광고·제휴 고지 없음' 지적에 not_applicable **표식만** 단다 (ORDER 2026-07-25-19).

    ⛔ 이 함수는 `passed` 와 `severity` 를 **어떤 입력에서도 쓰지 않는다.** 읽기만 한다.
       판정은 검수기(LLM) 원본 그대로다. 불변식 테스트: reviewer_selftest.py `[2]`.

       왜 없앴나 — 세 라운드(12 rev1 → rev2 → 18) 동안 정규식 분류로 판정을 뒤집으려다 매번
       감사자에게 새 표현으로 뚫렸다(18: 창작 21종 중 13종 flip, 허위 1인칭·저작권·YMYL·경쟁사
       부정 단정·광고 클릭 유도 포함). 반면 실코퍼스 리플레이의 flip 은 **0건** —
       "고지가 유일한 반대 사유"인 초안은 관측된 적이 없다. 이득 0 · 리스크는 자동 발행. 폐기.

    남기는 것(사람이 읽는 표식):
      · 지적을 **삭제하지 않는다** — `issues_not_applicable` 로 옮겨 사유와 함께 보존한다.
      · 수익화가 관측되면(`monetized`) 아무것도 하지 않는다 — 고지 요구가 되살아난다.
      · 수익화 상태를 **모르면**(`known=False`) 역시 아무것도 하지 않는다(fail-closed, ORDER 18 ③).

    관측용 로그: 표식 후 남은 반대 사유가 0이면(= '고지가 유일한 반대 사유'였다면) notes 에
      `SOLE-OBJECTION` 을 남긴다. 판정은 그대로 반려이고, 이 경우가 실제로 발생하는지
      `grep SOLE-OBJECTION dist/review/*.json` 으로 관측해 PM 이 수동 판단한다.
    """
    data["monetization"] = state
    if state.get("monetized"):
        return data
    if not state.get("known"):
        w = state.get("warning") or "monetization state could not be verified"
        data["notes"] = f"{data.get('notes', '')} [disclosure gate] no annotation — {w}".strip()
        return data
    issues = [i for i in (data.get("issues") or []) if isinstance(i, dict)]
    moved = [i for i in issues if _is_disclosure_only(i)]
    if not moved:
        return data
    kept = [i for i in (data.get("issues") or []) if i not in moved]
    data["issues"] = kept
    data["issues_not_applicable"] = [
        dict(i, status="not_applicable",
             reason="ANNOTATION ONLY — the verdict was NOT changed by this label. The ad/affiliate "
                    "DISCLOSURE part of this objection does not apply: no ads are served and the draft "
                    "has no affiliate links (verified at review time), so disclosing a commercial "
                    "relationship that does not exist would itself be a false statement. It revives "
                    "automatically as soon as ad code or affiliate links appear. ⚠️ Read the full text "
                    "below: if this objection also states any OTHER defect, that defect still stands — "
                    "this label is a lexical guess and is known to over-match mixed objections.")
        for i in moved]
    note = (f"[disclosure gate] {len(moved)} ad/affiliate-disclosure issue(s) annotated NOT APPLICABLE "
            f"(monetization not observed: {'; '.join(state.get('evidence') or [])}). "
            f"Verdict untouched — passed={data.get('passed')!r}, severity={data.get('severity')!r}.")
    if not kept and not data.get("ai_tells"):
        note += (" SOLE-OBJECTION: the ad/affiliate disclosure gap was this draft's ONLY objection, "
                 "and the draft is still judged on the reviewer's own verdict (no override). "
                 "If this line shows up in practice, a human decides.")
    data["notes"] = f"{data.get('notes', '')} {note}".strip()
    return data


def _text(h) -> str:
    """HTML → 검수용 평문. 블록 경계는 개행으로 보존하고 표 셀은 ' | ' 로, 엔티티는 해제한다.
    (구현 전엔 모든 태그를 공백 1개로 치환 → 목록·문단이 한 줄로 붕괴, &amp; 등 엔티티 그대로 노출)"""
    t = _CELL_END.sub(" | ", h or "")
    t = _BLOCK_END.sub("\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = re.sub(r"[^\S\n]+", " ", t)              # 줄 안의 공백만 접기(개행 보존)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _flatten(spec) -> str:
    # 페이지에 실제로 렌더되는 바이라인·날짜(renderer.py 의 metabar·authorbox·schema.org)를 함께 보여준다.
    # 이 줄이 없어서 검수기가 "저자·발행일 없음"을 반복 지적했다 — 페이지에는 있는데 검수 입력에만 없던 것.
    byline = (f"BYLINE (rendered on the page): author={getattr(spec, 'author', '') or '(none)'}; "
              f"published={getattr(spec, 'published_at', '') or '(none)'}; "
              f"updated={getattr(spec, 'updated_at', '') or getattr(spec, 'published_at', '') or '(none)'}")
    parts = [f"TITLE: {_text(spec.title)}", f"DEK: {_text(spec.dek)}", byline,
             f"TLDR: {_text(spec.tldr_html)}", f"INTRO: {_text(spec.intro_html)}"]
    for s in spec.sections:
        parts.append(f"## {_text(s['heading'])}\n{_text(s['html'])}")
    parts.append(f"VERDICT: {_text(spec.verdict_html)}")
    for f in (getattr(spec, "faq", None) or []):
        parts.append(f"FAQ Q: {_text(f.get('q', ''))}\nFAQ A: {_text(f.get('a', ''))}")
    parts.append("SOURCES: " + "; ".join(s.get("url", "") for s in (spec.sources or [])))
    return _clip("\n\n".join(parts), _MAX_REVIEW_CHARS, "article")


def _dump_input(spec, text: str) -> None:
    """검수기에 들어간 실제 입력을 dist/review/<slug>.input.txt 로 남긴다.
    반려된 초안은 어디에도 보존되지 않아 '왜 반려됐는지' 사후 재현이 불가능했다(2026-07-24 확인).
    부가 기능이므로 어떤 실패도 검수 자체를 막지 않는다."""
    try:
        os.makedirs("dist/review", exist_ok=True)
        with open(f"dist/review/{spec.slug}.input.txt", "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def review(spec, content_cfg: dict) -> dict:
    """검수 → {passed, severity, ai_tells, issues:[{type,detail,fix}], notes}.

    먼저 블록리스트를 정규식으로 스캔(generator.scan_ai_cliches) — 확정 위반이면
    LLM 호출 없이 즉시 반려(비용 절감). 없으면 전체 루브릭으로 LLM 검수.
    """
    flat = _flatten(spec)
    hits = generator.scan_ai_cliches(flat)
    if hits:
        return {
            "passed": False, "severity": "medium", "ai_tells": hits,
            "issues": [{"type": "ai_tone", "detail": f"banned cliché phrase(s) found: {', '.join(hits)}",
                        "fix": "rewrite the affected sentence(s) without these words/phrases"}],
            "notes": "규칙 기반 사전 필터에서 확정 검출 — LLM 미호출",
        }
    ground = _clip(getattr(spec, "grounding_context", "") or "", _MAX_GROUND_CHARS, "source material")
    src_block = (
        "\n\n=== SOURCE MATERIAL (official pages fetched at generation; NOTE: PARTIAL/truncated excerpt — "
        "a real fact may exist on the page yet be outside this excerpt) ===\n"
        "Fact-check against it, but calibrate severity carefully. Mark HIGH-severity (passed=false) ONLY for: "
        "(a) a claim that CONTRADICTS the sources; (b) a direct quote or attribution to a vendor that does not "
        "appear verbatim in the sources (fabricated quote); (c) a definitive NEGATIVE claim about a named "
        "competitor ('X does not support Y', 'X lacks Z') not backed by the sources. "
        "For other plausible specifics merely NOT FOUND in this excerpt (a price/plan/feature that could be "
        "real but beyond the truncation), flag LOW severity only — do NOT fail the article for those alone.\n"
        + ground) if ground else ""
    user = (
        "Review this article draft against the rubric and return ONLY JSON "
        '{"passed":bool,"severity":"none|low|medium|high","ai_tells":[str],'
        '"issues":[{"type":"factual|legal|policy|coherence|ai_tone","detail":str,"fix":str}],"notes":str}. '
        "passed=false if any high-severity legal/factual/policy issue (esp. false first-person testing claims "
        "or claims contradicting the source material).\n\n"
        + flat + src_block)
    # 광고·제휴 고지 요구는 '실제 수익화 상태'에 연동한다(관측 근거 포함). 광고가 들어오면 자동으로 되살아난다.
    state = monetization_state(spec, content_cfg)
    _dump_input(spec, user)                      # 감사용: 검수기가 실제로 본 텍스트 보존(재검수 가능하게)
    raw = generator.complete_text(_system(state), user, content_cfg, max_tokens=4000)
    data = generator._extract_json(raw)
    data.setdefault("passed", False)
    data.setdefault("severity", "unknown")
    data.setdefault("issues", [])
    data.setdefault("ai_tells", [])
    # 미수익화 시 고지 지적에 not_applicable **표식**만 단다(삭제 아님·판정 불변, ORDER 2026-07-25-19).
    data = _apply_disclosure_policy(data, state)
    # 엄격 스타일 게이트(사용자 방침 2026-07-05): AI 티(ai_tells)가 하나라도 있으면 medium 이라도 반려
    # → 재생성 유도. 평행구문 등 블록리스트 밖 AI 티까지 차단(LLM 이 ai_tells 로 잡음).
    if data.get("ai_tells"):
        data["passed"] = False
        if data.get("severity") in (None, "none", "low", "unknown"):
            data["severity"] = "medium"
    return data
