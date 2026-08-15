"""axes.py — 생성 축 레지스트리 + 짝비교가 아닌 두 축(시계열·지형도).

왜 이 파일이 생겼나 (2026-08-15):
    2026-08-11 AdSense 가 "가치가 별로 없는 콘텐츠"로 사이트를 거절했다. 원인 하나는 발행분 전부가
    `X vs Y` 한 포맷이었다는 것이다. 그런데 `trend_axis` 는 **짝비교만** 만들 수 있었다 —
    관측표(`observed.usable`)가 `min_entities: 2` + 값이 갈리는 행을 요구했기 때문이다.
    즉 **짝짓기는 목적이 아니라 표를 세우려던 수단**이었다. 그래서 표를 세우는 다른 방법을 추가한다.

⛔ `observed.py` 는 고치지 않는다 (딱 한 줄, `commit_weekly` 원자료 보존만 추가했다).
   그 모듈의 가드는 전부 사고에서 나왔다 — 관측창 겹침(1년 시차를 비교로 낸 건),
   비율지표 0 배제("무한배 활발"), `open_issues` 렌더 금지(3.9배가 결함이 아니라 유입량이었던 건).
   손대면 그 사고가 돌아온다. **수집기는 그대로 쓰고 소비자만 새로 붙인다.**

축 세 개:
    pair       — 기존. 두 등가 엔티티 × 지표.            → `observed` 가 그대로 담당한다.
    timeline   — 여러 엔티티 × **시간**(52주 주간 커밋).  → 짝이 필요 없다.
    landscape  — 우리가 기록한 소멸·이전·정지 × **오늘 재확인**. → 우리만 가진 데이터.

계약: 각 축 모듈은 `observed` 와 **같은 이름의 함수**를 노출한다
    observe(topic, cfg, hints) · prompt_block · data_block · section · source_links ·
    takeaway_ok · takeaway_request · heading
generator 는 `axes.renderer_for(result)` 로 골라 부른다. `result` 에 `axis` 키가 없으면
`observed` 가 나오므로 **기존 경로는 한 바이트도 달라지지 않는다.**
"""
from __future__ import annotations

import datetime
import html
import os
import re

from content import observed

# ── 축 이름 → 모듈. `pair` 는 기존 observed 를 그대로 가리킨다(하위호환의 핵심) ─────────────
_AXES = {"timeline": "timeline", "landscape": "landscape"}
HISTORY_PATH = os.environ.get("ADSENSE_OBSERVED_HISTORY") or os.path.join(
    "config", "observed_history.yaml")


def module_for(name: str):
    """축 이름 → 처리 모듈. 모르는 이름이면 기존 짝비교로 떨어뜨린다(조용히 죽지 않는다)."""
    return _Timeline if name == "timeline" else _Landscape if name == "landscape" else observed


def renderer_for(result: dict | None):
    """관측 결과를 **만든 축**의 렌더러. `axis` 키가 없으면 기존 `observed`."""
    return module_for((result or {}).get("axis") or "pair")


def observe(axis: str, topic: str, cfg: dict, hints: dict | None):
    """축 이름으로 수집을 위임한다. 어떤 실패도 예외로 올리지 않는다(표 없이 생성 계속)."""
    mod = module_for(axis)
    if mod is observed:
        return None                          # pair 는 generator 의 기존 경로가 처리한다
    try:
        return mod.observe(topic, cfg, hints)
    except Exception as e:
        print(f"generate: 축 '{axis}' 관측 건너뜀({type(e).__name__}: {e}) — 표 없이 생성 계속")
        return None


# ── 공용 헬퍼 ────────────────────────────────────────────────────────────────────────
def _esc(s) -> str:
    return html.escape(str(s), quote=False)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(calls: list) -> tuple[str, str]:
    """관측 시각 = 실제로 응답을 받은 시각 중 **가장 오래된 것**(observed.py 와 같은 규칙).
    '지금'으로 찍으면 캐시된 값에 더 새 날짜를 붙이는 셈이 된다."""
    ts = [c["fetched_at"] for c in calls if c.get("status") == 200 and c.get("fetched_at")]
    at = (datetime.datetime.fromtimestamp(min(ts), datetime.timezone.utc) if ts else _now())
    at = at.replace(microsecond=0)
    return at.isoformat().replace("+00:00", "Z"), at.date().isoformat()


def _tokens_from(values: list, observed_date: str) -> list:
    """해석 단락이 **실제로** 수치를 인용했는지 볼 토큰(observed.figure_tokens 와 같은 규칙)."""
    toks = []
    for v in values:
        for m in re.finditer(r"v?\d+(?:\.\d+){1,3}|\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:\.\d+)?\b", str(v)):
            t = m.group(0)
            if len(t) >= 3 and t not in toks:
                toks.append(t)
    if observed_date and observed_date not in toks:
        toks.append(observed_date)
    return toks


def _takeaway_ok(result: dict, takeaway_html: str, *, min_figures: int = 2) -> bool:
    text = re.sub(r"<[^>]+>", " ", takeaway_html or "")
    if not text.strip():
        return False
    date = str(result.get("observed_date") or "")
    if date and date not in text:
        return False
    hits = {t for t in (result.get("figure_tokens") or [])
            if re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\w.])", text)}
    hits.discard(date)
    return len(hits) >= min_figures


def _method_note(result: dict, what: str) -> str:
    """표 각주 — 관측일·엔드포인트·**무엇을 재지 않았는가**를 표와 같은 자리에 둔다(F10·F14).
    observed.py 가 지표마다 '자기 자신을 방어하는 문장'을 데리고 다니는 것과 같은 규칙이다."""
    ok, tot = result.get("ok_calls", 0), result.get("total_calls", 0)
    return (f'<p class="footnote">{what} Collected by this site on '
            f'{_esc(result.get("observed_date"))} ({_esc(result.get("observed_at"))}) by calling the '
            f'public APIs ourselves — {ok} of {tot} requests returned data. These are our own '
            f'readings, not figures supplied by any vendor.</p>')


# ═══════════════════════════════════════════════════════════════════════════════════════
# 축 B — 시계열: 여러 엔티티 × 52주
# ═══════════════════════════════════════════════════════════════════════════════════════
class _Timeline:
    """`/stats/participation` 이 주는 **최근 52주 주간 커밋 수**를 펼쳐 시간을 축으로 세운다.

    왜 짝이 필요 없나: 열이 제품이 아니라 **시간**이다. 엔티티 하나로도 표가 서고,
    창이 모든 엔티티에 대해 동일(항상 '지금까지의 52주')하므로 `observed` 가 겪었던
    **1년 시차 비교 사고가 구조적으로 불가능**하다.

    다만 엔티티 1개는 얇다 — 한 저장소의 커밋 그래프는 글이 되지 않는다.
    그래서 `MIN_ENTITIES` 를 3으로 둔다: 이건 제품 프로필이 아니라 **분야 스냅숏**이다.
    """
    WEEKS = 52
    BUCKET = 13                      # 13주 × 4 = 52주. 분기 경계가 아니라 **관측 종료일 기준** 역산이다.
    MIN_ENTITIES = 3
    axis = "timeline"

    # ── 수집 ──
    @staticmethod
    def observe(topic: str, cfg: dict, hints: dict | None):
        o = (cfg.get("observed_data") or {})
        targets = [t for t in ((hints or {}).get("targets") or []) if isinstance(t, dict)]
        if len(targets) < _Timeline.MIN_ENTITIES:
            print(f"generate[timeline]: 식별자 {len(targets)}개 — 최소 {_Timeline.MIN_ENTITIES}개 필요. 표 없이 계속")
            return None
        # ⚠️ `sources` 는 **식별자 키**다(github·npm·statuspage·dockerhub). 계열 라벨('repo')을
        #    넘기면 `_COLLECTORS` 에서 걸러져 아무것도 수집되지 않는다 — 2026-08-15 실측으로 겪었다.
        # ⚠️ `max_entities` 는 config 기본이 4 인데 시간축은 분야 스냅숏이라 후보를 다 써야 한다.
        #    호출 수는 엔티티당 3개(repo·participation·releases)뿐이라 6까지는 부담이 없다.
        res = observed.collect(targets, timeout=int(o.get("timeout", 10)),
                               max_entities=min(len(targets), 6), sources=["github"])
        rows = []
        for e in (res.get("entities") or []):
            weekly = (e.get("metrics") or {}).get("commit_weekly")
            # participation 은 52주를 준다. 그보다 짧게 오면 시간축에 못 세운다(잘라 쓰지 않는다 —
            # 창이 엔티티마다 달라지는 순간 이 축의 유일한 장점인 '동일 창'이 사라진다).
            if not isinstance(weekly, list) or len(weekly) < _Timeline.WEEKS:
                continue
            weekly = weekly[-_Timeline.WEEKS:]
            b = [sum(weekly[i:i + _Timeline.BUCKET])
                 for i in range(0, _Timeline.WEEKS, _Timeline.BUCKET)]
            rows.append({"name": e.get("name"), "ids": e.get("ids") or {}, "weekly": weekly,
                         "buckets": b, "total": sum(weekly),
                         "last_push": (e.get("metrics") or {}).get("last_push_date") or "",
                         "latest_release": (e.get("metrics") or {}).get("latest_release_date") or ""})
        if len(rows) < _Timeline.MIN_ENTITIES:
            print(f"generate[timeline]: 주별 원자료를 가진 엔티티 {len(rows)}개 — 표 없이 계속")
            return None
        # 값이 전부 같은 표는 지면만 차지한다(observed.distinct_rows 와 같은 정신).
        # 시간축에서 '갈린다'는 건 **구간끼리 다르다**는 뜻이다 — 한 줄이라도 변화가 있어야 한다.
        moved = [r for r in rows if len(set(r["buckets"])) > 1]
        if len(moved) < 2:
            print(f"generate[timeline]: 구간별로 값이 변한 엔티티 {len(moved)}개(<2) — 표 없이 계속")
            return None
        at, date = _stamp(res.get("calls") or [])
        end = datetime.date.fromisoformat(date)
        windows = []
        for i in range(4):
            hi = end - datetime.timedelta(weeks=_Timeline.BUCKET * (3 - i))
            lo = hi - datetime.timedelta(weeks=_Timeline.BUCKET)
            windows.append((lo.isoformat(), hi.isoformat()))
        result = {
            "axis": "timeline", "rows": rows, "windows": windows,
            "observed_at": at, "observed_date": date,
            "calls": res.get("calls") or [], "ok_calls": res.get("ok_calls", 0),
            "total_calls": res.get("total_calls", 0), "elapsed_ms": res.get("elapsed_ms", 0),
        }
        result["figure_tokens"] = _tokens_from(
            [b for r in rows for b in r["buckets"]] + [r["total"] for r in rows] + [date], date)
        print(f"generate[timeline]: 엔티티 {len(rows)}개 × 52주 · 변화 있는 엔티티 {len(moved)} · "
              f"API {result['ok_calls']}/{result['total_calls']} 성공")
        return result

    # ── 렌더 ──
    @staticmethod
    def heading(result: dict) -> str:
        return f"52 weeks of commits, week by week (measured {result.get('observed_date')})"

    @staticmethod
    def _spark(weekly: list, name: str) -> str:
        """52주 막대. 페이지에 이미 있는 CSS 변수만 쓰므로 다크모드가 따라온다."""
        top = max(weekly) or 1
        w, gap, h = 3.0, 1.0, 26.0
        bars = []
        for i, v in enumerate(weekly):
            bh = max(1.0, (v / top) * h)
            bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1" fill="var(--accent)"'
                        ' opacity="%.2f"/>' % (i * (w + gap), h - bh, w, bh, 0.45 + 0.55 * (v / top)))
        vw = 52 * (w + gap)
        return ('<svg viewBox="0 0 %.0f %.0f" role="img" aria-label="%s: weekly commits over 52 weeks, '
                'highest week %d" style="width:%.0fpx;max-width:100%%;height:auto;display:block">%s</svg>'
                % (vw, h, _esc(name), top, vw, "".join(bars)))

    @staticmethod
    def table_html(result: dict, takeaway_html: str = "") -> str:
        rows, wins = result.get("rows") or [], result.get("windows") or []
        if not rows:
            return ""
        head = "".join(f'<th class="ctr">{_esc(a)}<br>→ {_esc(b)}</th>' for a, b in wins)
        body = []
        for r in rows:
            cells = "".join(f'<td class="ctr">{b:,}</td>' for b in r["buckets"])
            body.append(f'<tr><td class="featc">{_esc(r["name"])}</td>{cells}'
                        f'<td class="ctr">{r["total"]:,}</td>'
                        f'<td>{_Timeline._spark(r["weekly"], r["name"])}</td></tr>')
        table = ('<div class="tablewrap"><table class="tbl"><thead><tr>'
                 '<th class="feat">Repository</th>' + head +
                 '<th class="ctr">52-week total</th><th class="feat">Week by week</th>'
                 '</tr></thead><tbody>' + "".join(body) + "</tbody></table></div>")
        note = _method_note(result, (
            "Weekly commit counts for the last 52 weeks, from each repository's own GitHub statistics "
            "endpoint, grouped into four 13-week windows. Every repository is measured over the same "
            "52 weeks, so the columns are directly comparable. Commit counts include merges, dependency "
            "bumps and documentation edits, and a monorepo will always show more commits than a "
            "single-purpose repository — this measures how busy a repository is, not progress, quality, "
            "or how much of the work reaches users."))
        return table + (takeaway_html or "") + note

    @staticmethod
    def section(result: dict, takeaway_html: str = "") -> dict | None:
        h = _Timeline.table_html(result, takeaway_html=takeaway_html)
        # 🔴 observed.table_html 과 같은 불변식: **해석 없는 표는 렌더하지 않는다.**
        #    규칙은 데이터를 렌더하는 함수 자신이 들고 있어야 한다(43b-review ①).
        if not h or not (takeaway_html or "").strip():
            return None
        return {"heading": _Timeline.heading(result), "html": h, "observed": True}

    @staticmethod
    def data_block(result: dict) -> str:
        rows, wins = result.get("rows") or [], result.get("windows") or []
        if not rows:
            return ""
        lines = []
        for r in rows:
            per = "; ".join(f"{a}→{b}: {n:,} commits" for (a, b), n in zip(wins, r["buckets"]))
            ids = (r.get("ids") or {}).get("github") or ""
            lines.append(f'- {r["name"]} [github {ids}]: {per}; 52-week total {r["total"]:,}'
                         + (f'; most recent commit {r["last_push"]}' if r.get("last_push") else ""))
        return (f"=== OUR OWN OBSERVATION — collected by this site on {result.get('observed_date')} "
                f"({result.get('observed_at')}) ===\n"
                "These are NOT vendor claims. We called the public GitHub statistics API ourselves and "
                "recorded weekly commit counts for the last 52 weeks, grouped into four 13-week windows:\n"
                + "\n".join(lines))

    @staticmethod
    def prompt_block(result: dict) -> str:
        data = _Timeline.data_block(result)
        if not data:
            return ""
        return (data + "\n"
                "HOW TO USE THIS:\n"
                f'- A table of exactly these figures, with the dates and the endpoint we queried, is '
                f'already placed in the article as a section titled "{_Timeline.heading(result)}". '
                "Do NOT rebuild that table in your own sections.\n"
                "- Write about what the SHAPE over time means — speeding up, slowing down, steady, "
                "or stopped — and name the products when you do.\n"
                "- Do NOT treat commit volume as quality, progress, popularity, or team size. A quiet "
                "repository may be stable; a busy one may be churning.\n"
                "- Do NOT compare one product's window against another product's different window. "
                "Every column covers the same 52 weeks for every row.\n"
                # 🔴 실측 반려(2026-08-15 시범 1회차): 모델이 "공개 저장소가 없는 호스티드 툴" 단락을
                #    지어내고 그 예로 Sculptor 를 들었다 — 같은 글의 표가 Sculptor 의 커밋을 세고 있는데.
                #    검수기가 factual+coherence high 로 잡았다. 집합의 성질을 프롬프트에 못 박는다.
                "- EVERY product in the table above has a public GitHub repository — that is how these "
                "numbers were obtained. Do NOT describe any of them as closed-source, hosted-only, or "
                "lacking a public repository, and do NOT use any of them to illustrate such a case.\n"
                "- Do NOT introduce products that are not in the table above.\n")

    @staticmethod
    def source_links(result: dict, *, max_links: int = 6) -> list:
        out = []
        for r in (result.get("rows") or []):
            gh = (r.get("ids") or {}).get("github")
            if gh:
                out.append({"title": f"GitHub — {gh} commit activity",
                            "url": f"https://github.com/{gh}/graphs/commit-activity"})
        return out[:max_links]

    @staticmethod
    def takeaway_ok(result: dict, takeaway_html: str, *, min_figures: int = 2) -> bool:
        return _takeaway_ok(result, takeaway_html, min_figures=min_figures)

    @staticmethod
    def takeaway_request(result: dict) -> str:
        return (_Timeline.data_block(result) + "\n\n"
                "Write ONE paragraph of 3-5 sentences about exactly these figures. All four:\n"
                f"  (a) quote at least TWO of the specific numbers above and carry the observation date "
                f"{result.get('observed_date')} with them;\n"
                "  (b) say what was measured — weekly commit counts from each repository's public "
                "GitHub statistics endpoint, over the same 52 weeks for every row;\n"
                "  (c) say what the shape over time reasonably suggests to someone deciding whether to "
                "depend on one of these projects;\n"
                "  (d) say plainly what it does NOT establish — not quality, not progress, not how many "
                "people use it, not whether the project will still exist next year.\n"
                "Plain prose, no headings, no lists.")


# ═══════════════════════════════════════════════════════════════════════════════════════
# 축 C — 지형도: 우리가 기록한 것 × 오늘 재확인
# ═══════════════════════════════════════════════════════════════════════════════════════
class _Landscape:
    """`config/observed_history.yaml` 의 기록을 **오늘 다시 호출해** 대조한다.

    이 축이 다른 이유: 소재가 공개 문서가 아니라 **우리 원장**이다. 저장소가 사라진 날은
    그날 호출해 본 사람만 안다. 검색으로는 안 나온다.

    🔴 기록만으로 단정하지 않는다. 기록은 과거이고 대조는 현재다 — 실제로 `omnara` 는
       2026-08-01 '정지'로 기록됐다가 2026-08-15 재확인에서 되살아난 것이 확인됐다.
       그 불일치 자체가 이 축이 말하려는 것이다.
    """
    MIN_ROWS = 6
    MIN_KINDS = 2
    axis = "landscape"

    # ── 수집 ──
    @staticmethod
    def _history() -> list:
        import yaml
        path = HISTORY_PATH
        if not os.path.exists(path):
            print(f"generate[landscape]: 원장이 없다 — {path}")
            return []
        with open(path, encoding="utf-8") as fh:
            return ((yaml.safe_load(fh) or {}).get("records") or [])

    @staticmethod
    def observe(topic: str, cfg: dict, hints: dict | None):
        o = (cfg.get("observed_data") or {})
        timeout = int(o.get("timeout", 10))
        recs = [r for r in _Landscape._history() if isinstance(r, dict)]
        if not recs:
            return None
        # 후보가 범위를 좁힐 수 있다(`entities` 에 적힌 이름만). 비어 있으면 원장 전체가 대상이다.
        want = {str(t.get("name") or "").lower()
                for t in ((hints or {}).get("targets") or []) if isinstance(t, dict)}
        if want:
            recs = [r for r in recs if str(r.get("entity") or "").lower() in want]
        # 이미 뒤집힌 기록(superseded_by)은 **후속 기록과 함께** 보여야 뜻이 산다 → 둘 다 남긴다.
        calls, rows = [], []
        api = os.environ.get("ADSENSE_OBSERVED_GITHUB_API") or "https://api.github.com"
        seen_repo, seen_npm = {}, {}
        for r in recs:
            gh, npm = r.get("github"), r.get("npm")
            live = ""
            if gh:
                if gh not in seen_repo:
                    d = observed._get_json(f"{api}/repos/{gh}", timeout, calls)
                    seen_repo[gh] = d if isinstance(d, dict) else None
                d = seen_repo[gh]
                if not d:
                    live = "not found (404)"
                else:
                    full, push = d.get("full_name") or gh, (d.get("pushed_at") or "")[:10]
                    live = (f"redirects to {full}" if full.lower() != gh.lower()
                            else f"live, last commit {push}")
                    if full.lower() == gh.lower() and push:
                        live = f"live, last commit {push}"
                    elif full.lower() != gh.lower():
                        live = f"redirects to {full}; last commit {push}"
            elif npm:
                if npm not in seen_npm:
                    d = observed._get_json(f"https://registry.npmjs.org/{npm}", timeout, calls)
                    seen_npm[npm] = d if isinstance(d, dict) else None
                d = seen_npm[npm]
                url = (((d or {}).get("repository") or {}) or {}).get("url") or ""
                m = re.search(r"github\.com[:/]+([^/]+/[^/.\s]+)", str(url))
                live = f"npm package points at {m.group(1)}" if m else (
                    "npm package has no repository field" if d else "not found (404)")
            if not live:
                continue
            rows.append({
                "entity": r.get("entity"), "event": r.get("event"), "as_of": r.get("as_of"),
                "target": gh or (f"npm:{npm}" if npm else ""), "github": gh, "npm": npm,
                "recorded": _Landscape._recorded(r), "live": live,
                "agrees": _Landscape._agrees(r, live),
                "superseded": bool(r.get("superseded_by")),
            })
        if len(rows) < _Landscape.MIN_ROWS:
            print(f"generate[landscape]: 대조 행 {len(rows)}개(<{_Landscape.MIN_ROWS}) — 표 없이 계속")
            return None
        if len({r["event"] for r in rows}) < _Landscape.MIN_KINDS:
            print("generate[landscape]: 사건 종류가 한 가지뿐 — 표 없이 계속")
            return None
        at, date = _stamp(calls)
        result = {"axis": "landscape", "rows": rows, "observed_at": at, "observed_date": date,
                  "calls": calls, "ok_calls": sum(1 for c in calls if c.get("status") == 200),
                  "total_calls": len(calls),
                  "disagree": [r for r in rows if not r["agrees"]]}
        result["figure_tokens"] = _tokens_from(
            [r["as_of"] for r in rows] + [r["live"] for r in rows] + [date], date)
        print(f"generate[landscape]: 기록 {len(rows)}건 대조 · 오늘과 어긋난 기록 "
              f"{len(result['disagree'])}건 · API {result['ok_calls']}/{result['total_calls']} 성공")
        return result

    @staticmethod
    def _recorded(r: dict) -> str:
        ev, when = r.get("event"), r.get("as_of")
        who = r.get("actual_owner") or r.get("moved_to") or ""
        return {
            "gone": f"repository returned 404 on {when}",
            "dormant": f"no commits recorded as of {when}",
            "revived": f"commits resumed, seen {when}",
            "moved": f"redirected to {who}, seen {when}",
            "name_taken": f"npm name owned by {who}, checked {when}",
            "name_verified": f"npm name matches {who}, checked {when}",
        }.get(str(ev), f"{ev} on {when}")

    @staticmethod
    def _agrees(r: dict, live: str) -> bool:
        """기록과 오늘이 같은 이야기를 하는가. 애매하면 **어긋난 것으로 세지 않는다**(과장 금지)."""
        ev = str(r.get("event"))
        if ev == "gone":
            return "404" in live
        if ev == "moved":
            return "redirects to" in live
        if ev in ("name_taken", "name_verified"):
            return str(r.get("actual_owner", "")).lower() in live.lower()
        if ev == "dormant":
            m = re.search(r"last commit (\d{4}-\d{2}-\d{2})", live)
            # 기록 당시 '멈춰 있다'였다 — 그 뒤로 커밋이 있으면 기록은 더 이상 현재가 아니다.
            return not (m and str(r.get("as_of") or "") and m.group(1) > str(r.get("as_of")))
        if ev == "revived":
            return "live" in live
        return True

    # ── 렌더 ──
    @staticmethod
    def heading(result: dict) -> str:
        return f"What we recorded, and what the same check says on {result.get('observed_date')}"

    @staticmethod
    def table_html(result: dict, takeaway_html: str = "") -> str:
        rows = result.get("rows") or []
        if not rows:
            return ""
        body = []
        for r in rows:
            mark = "" if r["agrees"] else ' <span class="mk-warn">≠</span>'
            body.append(f'<tr><td class="featc">{_esc(r["entity"])}</td>'
                        f'<td><code>{_esc(r["target"])}</code></td>'
                        f'<td>{_esc(r["recorded"])}</td>'
                        f'<td>{_esc(r["live"])}{mark}</td></tr>')
        table = ('<div class="tablewrap"><table class="tbl"><thead><tr>'
                 '<th class="feat">Project</th><th class="feat">What we watched</th>'
                 '<th class="feat">What we recorded, and when</th>'
                 f'<th class="feat">Same check on {_esc(result.get("observed_date"))}</th>'
                 '</tr></thead><tbody>' + "".join(body) + "</tbody></table></div>"
                 '<p class="footnote">≠ marks a row where today\'s check no longer matches what we '
                 'recorded. Those rows are not errors in the record — they are the record working.</p>')
        note = _method_note(result, (
            "The middle column is our own log: what the GitHub REST API and the npm registry returned "
            "when we called them on the date shown, while checking candidates for other articles. The "
            "right column is the same call repeated for this article. A 404 does not distinguish a "
            "deleted repository from one made private, and a redirect is followed automatically by "
            "most clients, which is exactly why moves go unnoticed."))
        return table + (takeaway_html or "") + note

    @staticmethod
    def section(result: dict, takeaway_html: str = "") -> dict | None:
        h = _Landscape.table_html(result, takeaway_html=takeaway_html)
        if not h or not (takeaway_html or "").strip():
            return None
        return {"heading": _Landscape.heading(result), "html": h, "observed": True}

    @staticmethod
    def data_block(result: dict) -> str:
        rows = result.get("rows") or []
        if not rows:
            return ""
        lines = [f'- {r["entity"]} [{r["target"]}]: we recorded "{r["recorded"]}"; '
                 f'the same check on {result.get("observed_date")} returned "{r["live"]}"'
                 + ("" if r["agrees"] else "  <-- no longer matches")
                 for r in rows]
        return (f"=== OUR OWN OBSERVATION LOG — re-checked on {result.get('observed_date')} "
                f"({result.get('observed_at')}) ===\n"
                "These are NOT vendor claims and NOT press reports. Each left-hand entry is what a "
                "public API returned to us on the date shown; each right-hand entry is the same call "
                "repeated today:\n" + "\n".join(lines))

    @staticmethod
    def prompt_block(result: dict) -> str:
        data = _Landscape.data_block(result)
        if not data:
            return ""
        n = len(result.get("disagree") or [])
        return (data + "\n"
                "HOW TO USE THIS:\n"
                f'- A table of exactly these entries is already placed in the article as a section '
                f'titled "{_Landscape.heading(result)}". Do NOT rebuild that table.\n'
                f"- {n} of the rows no longer match what we recorded. Treat that as the point of the "
                "piece, not as an embarrassment: a single check is a snapshot, and snapshots expire.\n"
                "- Do NOT claim to know WHY anything moved, stopped or disappeared. A 404 does not say "
                "whether a repository was deleted or made private. Say what was returned, not what "
                "someone intended.\n"
                "- Do NOT describe any project as abandoned, dead, or failing. Report the dates.\n"
                "- Do NOT imply any maintainer acted in bad faith, including for reused package names.\n")

    @staticmethod
    def source_links(result: dict, *, max_links: int = 8) -> list:
        out, seen = [], set()
        for r in (result.get("rows") or []):
            if r.get("github") and r["github"] not in seen:
                seen.add(r["github"])
                out.append({"title": f"GitHub — {r['github']}",
                            "url": f"https://github.com/{r['github']}"})
            elif r.get("npm") and f"npm:{r['npm']}" not in seen:
                seen.add(f"npm:{r['npm']}")
                out.append({"title": f"npm — {r['npm']}",
                            "url": f"https://www.npmjs.com/package/{r['npm']}"})
        return out[:max_links]

    @staticmethod
    def takeaway_ok(result: dict, takeaway_html: str, *, min_figures: int = 2) -> bool:
        return _takeaway_ok(result, takeaway_html, min_figures=min_figures)

    @staticmethod
    def takeaway_request(result: dict) -> str:
        return (_Landscape.data_block(result) + "\n\n"
                "Write ONE paragraph of 3-5 sentences about exactly these entries. All four:\n"
                f"  (a) quote at least TWO of the specific dates or results above and carry the "
                f"re-check date {result.get('observed_date')} with them;\n"
                "  (b) say what each side of the comparison is — our own logged API responses versus "
                "the same calls repeated today;\n"
                "  (c) say what this reasonably suggests for someone who depends on small, young "
                "projects;\n"
                "  (d) say plainly what it does NOT establish — not why anything changed, not whether "
                "a project was abandoned, and not anything about the intent of any maintainer.\n"
                "Plain prose, no headings, no lists.")
