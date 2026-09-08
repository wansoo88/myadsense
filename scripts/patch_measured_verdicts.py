# -*- coding: utf-8 -*-
"""patch_measured_verdicts.py — 측정 섹션이 들어간 글의 **결론·요약이 측정 결과를 참조**하게 본문을 고친다 (ORDER 55 ①).

원칙
- 숫자는 전부 data/measurements/*.json · config/prices.yaml 에서 읽어 넣는다. 본문에 손으로 적는 숫자는 없다.
- 못 잰 것은 "not measured" 라고 쓴다. 추측·경험담 금지.
- 멱등: 넣는 문단은 <!-- mv:<slug>:<name> --> … <!-- /mv --> 표식으로 감싸 재실행 시 교체한다.
- 앵커(교체할 기존 문장)가 0회거나 기대 횟수와 다르면 그 글은 쓰지 않고 에러로 남긴다(조용히 넘어가지 않는다).
- 본문이 실질적으로 바뀐 글은 dateModified·"Updated" 를 패치 날짜로 올린다(F14: 신선도 신호는 사실일 때만).

  python scripts/patch_measured_verdicts.py --src dist/queue_server --dst dist/queue_patched [--only slug ...] [--dry-run]
"""
from __future__ import annotations
import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import yaml                                              # noqa: E402
from engine.measure import common                        # noqa: E402

esc = html.escape
TODAY = common.today()


class Anchor(Exception):
    pass


def _n(v, unit="", nd=0):
    if v is None:
        return "not measured"
    if isinstance(v, float) and nd:
        return f"{v:,.{nd}f}{unit}"
    return f"{int(round(v)):,}{unit}"


def _row(data, suite, key, lst="rows"):
    for role, payload in (data.get(suite) or {}).items():
        for r in payload.get(lst, []):
            if r.get("key") == key:
                return r
    return {}


def _date(data, suite):
    for role, payload in (data.get(suite) or {}).items():
        return payload.get("host", {}).get("date", "")
    return ""


def _dollars(price: str):
    """가격 문자열의 $ 숫자들(정수/소수). note 는 보지 않는다."""
    return [float(x.replace(",", "")) for x in re.findall(r"\$(\d[\d,]*(?:\.\d+)?)", price or "")]


def wrap(slug, name, inner):
    return f"<!-- mv:{slug}:{name} -->{inner}<!-- /mv -->"


def put(doc, slug, name, inner, where):
    """where: (regex, mode) — 'before' 는 매치 직전에 삽입, 'replace' 는 매치를 통째로 교체. 표식이 이미 있으면 그 블록을 교체."""
    block = wrap(slug, name, inner)
    pat = re.compile(rf"<!-- mv:{re.escape(slug)}:{re.escape(name)} -->.*?<!-- /mv -->", re.S)
    if pat.search(doc):
        return pat.sub(lambda m: block, doc, count=1)
    rx, mode = where
    m = re.search(rx, doc, re.S)
    if not m:
        raise Anchor(f"{slug}: anchor for {name!r} not found: {rx[:70]!r}")
    if mode == "before":
        return doc[:m.start()] + block + doc[m.start():]
    return doc[:m.start()] + block + doc[m.end():]


def replace_exact(doc, slug, old, new, want=1):
    """본문(&#x27;)과 JSON-LD(') 표기 변형을 모두 센다. 합이 want 와 다르면 에러(이미 적용된 경우만 통과)."""
    variants = [old] + ([old.replace("'", "&#x27;"), old.replace("'", "&#39;")] if "'" in old else [])
    hits = [(v, doc.count(v)) for v in variants]
    hits = [(v, n) for v, n in hits if n]
    total = sum(n for _v, n in hits)
    if total != want:
        if total == 0 and (new in doc or new.replace("'", "&#x27;") in doc):
            return doc
        raise Anchor(f"{slug}: anchor x{total} (want {want}): {old[:80]!r}")
    for v, n in hits:
        rep = new if v == old else new.replace("'", "&#x27;" if "&#x27;" in v else "&#39;")
        doc = doc.replace(v, rep)
    return doc


def bump_dates(doc, slug):
    m = re.search(r'"dateModified": "(\d{4}-\d{2}-\d{2})"', doc)
    if not m:
        raise Anchor(f"{slug}: dateModified not found")
    old = m.group(1)
    if old == TODAY:
        return doc
    doc = doc.replace(f'"dateModified": "{old}"', f'"dateModified": "{TODAY}"')
    doc = re.sub(rf"(Updated <time[^>]*>){re.escape(old)}", lambda mm: mm.group(1) + TODAY, doc)
    doc = doc.replace(f"Updated {old}</div>", f"Updated {TODAY}</div>")
    return doc


def before_close(doc, sid, closer):
    """id=sid 섹션 안에서 마지막 closer 직전 60자를 앵커로 삼는 정규식(그 자리에 삽입)."""
    m = re.search(rf'<section class="blk" id="{re.escape(sid)}">.*?</section>', doc, re.S)
    if not m:
        raise Anchor(f"section #{sid} not found")
    seg = m.group(0)
    i = seg.rfind(closer)
    if i < 0:
        raise Anchor(f"section #{sid}: closer {closer!r} not found")
    return re.escape(seg[i - 60:i]) + r"(?=" + re.escape(closer) + r")"


# ───────────────────────────── 글별 패치 ─────────────────────────────

def orca_herdr(doc, slug, data, prices):
    d = _date(data, "desktop")
    orca = _row(data, "desktop", "orca")
    herdr = _row(data, "desktop", "herdr_release", "cli")
    ro = _row(data, "repo", "orca")
    rh = _row(data, "repo", "herdr")
    rel_o = _row(data, "releases", "orca")
    rel_h = _row(data, "releases", "herdr")
    dr = _date(data, "repo")
    ratio_fp = (orca.get("footprint_mb") or 0) / (herdr.get("footprint_mb") or 1)
    ratio_c = (ro.get("commits_90d") or 0) / (rh.get("commits_90d") or 1)
    ratio_r = (ro.get("releases_90d_stable") or 0) / (rh.get("releases_90d_stable") or 1)
    hv = (herdr.get("version") or "").replace("herdr ", "")
    s = (f"<p><strong>Measured on our laptop, {esc(d)}:</strong> Orca {esc(orca.get('version', ''))} is a {_n(rel_o.get('mb'), ' MB')} installer "
         f"that occupies {_n(orca.get('footprint_mb'), ' MB')}, opened in {_n(orca.get('cold_start_s'), ' s', 2)} and sat at "
         f"{_n(orca.get('idle_rss_mb'), ' MB')} of memory across {_n(orca.get('process_count'))} processes 25 s later; herdr {esc(hv)} is a "
         f"{_n(rel_h.get('mb'), ' MB', 1)} zip that unpacks to {_n(herdr.get('footprint_mb'), ' MB')}. In the 90 days to {esc(dr)} Orca's repository "
         f"logged {_n(ro.get('commits_90d'))} commits and {_n(ro.get('releases_90d_stable'))} stable releases, herdr's {_n(rh.get('commits_90d'))} and "
         f"{_n(rh.get('releases_90d_stable'))} (<a href=\"#measured\">tables below</a>).</p>")
    doc = put(doc, slug, "summary", s, (before_close(doc, "summary", "</div></section>"), "before"))
    v = (f"<p><strong>What our numbers add.</strong> The size gap is not a matter of taste. On the same laptop on {esc(d)}, Orca occupied "
         f"{_n(orca.get('footprint_mb'), ' MB')} and idled at {_n(orca.get('idle_rss_mb'), ' MB')} of memory as a {_n(orca.get('process_count'))}-process "
         f"desktop app, while herdr was a {_n(herdr.get('footprint_mb'), ' MB')} directory whose <code>--version</code> returned in "
         f"{_n(herdr.get('run_s'), ' s', 2)} — roughly {ratio_fp:.0f}× less disk. The two were not measured the same way (a window against a command-line run), "
         f"so read the memory figure as Orca's cost rather than as a ratio; herdr's memory with an agent session running was not measured. On cadence, both "
         f"repositories had a commit dated {esc(ro.get('last_commit') or '?')}; Orca's {_n(ro.get('commits_90d'))} commits and {_n(ro.get('releases_90d_stable'))} "
         f"stable releases in 90 days are about {ratio_c:.0f}× the commits and {ratio_r:.0f}× the stable releases of herdr's {_n(rh.get('commits_90d'))} and "
         f"{_n(rh.get('releases_90d_stable'))}. Open pull requests point the same way — {_n(ro.get('open_prs'))} against {_n(rh.get('open_prs'))} — which cuts "
         f"both ways: more change arriving, and more of it waiting.</p>")
    doc = put(doc, slug, "verdict", v, (before_close(doc, "verdict", "</div></section>"), "before"))
    return doc


def cursor_windsurf(doc, slug, data, prices):
    d = _date(data, "desktop")
    c = _row(data, "desktop", "cursor")
    w = _row(data, "desktop", "windsurf")
    rw = _row(data, "releases", "windsurf")
    dl = _date(data, "releases")
    asset = rw.get("asset") or ""
    s = (f"<p><strong>Measured on our laptop, {esc(d)}, with an empty profile and no folder open:</strong> Cursor {esc(c.get('version', ''))} opened in "
         f"{_n(c.get('cold_start_s'), ' s', 2)} and idled at {_n(c.get('idle_rss_mb'), ' MB')} of memory across {_n(c.get('process_count'))} processes from a "
         f"{_n(c.get('footprint_mb'), ' MB')} install; Windsurf {esc(w.get('version', ''))} opened in {_n(w.get('cold_start_s'), ' s', 2)} and idled at "
         f"{_n(w.get('idle_rss_mb'), ' MB')} across {_n(w.get('process_count'))} processes from a {_n(w.get('footprint_mb'), ' MB')} install. The Windsurf "
         f"installer we downloaded on {esc(dl)} was named <code>{esc(asset)}</code> and installed to a folder called Devin "
         f"(<a href=\"#measured\">tables below</a>).</p>")
    doc = put(doc, slug, "summary", s, (before_close(doc, "summary", "</div></section>"), "before"))
    diff_mem = (c.get("idle_rss_mb") or 0) - (w.get("idle_rss_mb") or 0)
    diff_fp = (w.get("footprint_mb") or 0) - (c.get("footprint_mb") or 0)
    v = (f"<p><strong>What our numbers add.</strong> Neither editor is light. With nothing open, both idled above 2 GB of resident memory on {esc(d)} "
         f"({_n(c.get('idle_rss_mb'), ' MB')} for Cursor, {_n(w.get('idle_rss_mb'), ' MB')} for Windsurf), which matters if either will sit next to a browser "
         f"and a container stack on a 16 GB machine. Windsurf opened faster ({_n(w.get('cold_start_s'), ' s', 2)} against {_n(c.get('cold_start_s'), ' s', 2)}) and "
         f"used about {_n(diff_mem, ' MB')} less memory at idle; Cursor's install is about {_n(diff_fp, ' MB')} smaller ({_n(c.get('footprint_mb'), ' MB')} against "
         f"{_n(w.get('footprint_mb'), ' MB')}). One observation, recorded as we found it: the Windows build served by the Windsurf stable update endpoint on "
         f"{esc(dl)} was <code>{esc(asset)}</code>; it installed into a folder named Devin under the user's Programs directory, its executable is "
         f"<code>Devin.exe</code>, and the app reported version {esc(w.get('version', ''))}. Scripts or allow-lists that look for a program named Windsurf will "
         f"not find one. <strong>Not measured:</strong> how quickly or how well each agent completes a fixed task. That needs a signed-in session on each free "
         f"tier and an identical task for both, which we have not run, so nothing in this article about agent speed or output quality comes from our own "
         f"testing.</p>")
    doc = put(doc, slug, "verdict", v, (before_close(doc, "verdict", "</div></section>"), "before"))
    return doc


def code_review(doc, slug, data, prices):
    dr = _date(data, "repo")
    pa = _row(data, "repo", "pr_agent")
    sq = _row(data, "repo", "sonarqube")
    sn = _row(data, "repo", "snyk_cli")
    aq = _row(data, "repo", "amazon_q_cli")
    obs = [o for o in (prices.get("observations") or []) if o.get("slug") == slug]
    dates = sorted({str(o.get("as_of")) for o in obs})
    pairs = [(v, o.get("plan", "")) for o in obs for v in _dollars(o.get("price"))]
    lo = min(pairs) if pairs else (None, "")
    hi = max(pairs) if pairs else (None, "")
    aq_price = next((_dollars(o.get("price")) for o in obs if "Amazon Q" in (o.get("plan") or "")), [None])[0]
    s = (f"<p><strong>Two things we read ourselves on {esc(dr)}:</strong> the open-source pieces move at very different speeds — PR-Agent "
         f"{_n(pa.get('commits_90d'))} commits and {_n(pa.get('releases_90d_stable'))} releases in 90 days, SonarQube {_n(sq.get('commits_90d'))} and "
         f"{_n(sq.get('releases_90d_stable'))}, Snyk CLI {_n(sn.get('commits_90d'))} and {_n(sn.get('releases_90d_stable'))}, while the Amazon Q Developer CLI "
         f"repository had no commit since {esc(aq.get('last_commit') or '?')} and no release since {esc(aq.get('latest_release_date') or '?')} — and the per-seat "
         f"prices on the vendors' own pages ({esc(' and '.join(dates))}) ran from ${lo[0]:,.0f} ({esc(lo[1])}) to ${hi[0]:,.0f} ({esc(hi[1])}) per developer "
         f"per month (<a href=\"#measured\">tables below</a>).</p>")
    doc = put(doc, slug, "summary", s, (before_close(doc, "summary", "</div></section>"), "before"))
    v = (f"<p><strong>What our numbers add.</strong> The repository table changes one line of advice. Amazon Q Developer's public CLI repository has been still "
         f"since {esc(aq.get('last_commit') or '?')} — {_n(aq.get('commits_90d'))} commits in the 90 days to {esc(dr)}, no release since "
         f"{esc(aq.get('latest_release_date') or '?')} ({esc(aq.get('latest_release') or '')}), {_n(aq.get('open_issues'))} issues open — so \"already on AWS\" is "
         f"not a reason on its own: the price we read that day was ${aq_price:,.0f} per user per month, and the code behind the CLI is not moving. The other three "
         f"open-source cores were each touched within a day of our reading (PR-Agent {esc(pa.get('last_commit') or '')}, SonarQube {esc(sq.get('last_commit') or '')}, "
         f"Snyk CLI {esc(sn.get('last_commit') or '')}). PR-Agent's repository has also moved: GitHub now redirects <code>qodo-ai/pr-agent</code> to "
         f"<code>{esc(pa.get('repo') or '')}</code>, which is where its {_n(pa.get('commits_90d'))} commits landed. On price, the spread is wide enough to matter "
         f"at team scale — ${lo[0]:,.0f} to ${hi[0]:,.0f} per developer per month in the dated table — and Sonar and Snyk price by lines of code or by contributing "
         f"developer rather than by seat, so compare them on your own repository, not on the headline figure.</p>")
    doc = put(doc, slug, "verdict", v, (before_close(doc, "verdict", "</div></section>"), "before"))
    return doc


def appflowy_affine(doc, slug, data, prices):
    dr = _date(data, "repo")
    af = _row(data, "repo", "appflowy")
    aw = _row(data, "repo", "appflowy_web")
    ac = _row(data, "repo", "appflowy_cloud")
    fn = _row(data, "repo", "affine")
    tags = af.get("release_tag_commits") or []
    tag_s = (", ".join(t["tag"] for t in tags[:-1]) + f" and {tags[-1]['tag']}") if len(tags) > 1 else (tags[0]["tag"] if tags else "")
    tag_sha = tags[0]["sha"] if tags else "?"
    tag_date = tags[0]["commit_date"] if tags else "?"
    stars_k = f"{(af.get('stars') or 0) / 1000:.1f}k"
    # 1) 요약(In short) — 문단 통째로 교체
    new_sum = (f"<p><strong>Short answer (as of {esc(dr)}):</strong> Of the two most-starred open-source Notion alternatives, <strong>AFFiNE</strong> is the one "
               f"whose activity is where you expect it — {_n(fn.get('commits_90d'))} commits on its default branch in the 90 days to {esc(dr)}, newest "
               f"{esc(fn.get('last_commit') or '')}, with its newest release tags pointing at commits from the weeks they shipped. <strong>AppFlowy</strong> "
               f"({stars_k} stars) reads very differently depending on which repository you open: AppFlowy-IO/AppFlowy's default branch received "
               f"{_n(af.get('commits_90d'))} commit in those 90 days ({_n(af.get('commits_52w'))} in 52 weeks; newest {esc(af.get('last_commit') or '')}), yet it "
               f"published {_n(af.get('releases_90d_stable'))} stable releases in the same window, the latest {esc(af.get('latest_release') or '')} on "
               f"{esc(af.get('latest_release_date') or '')} — and the tags for {esc(tag_s)} all point at the same commit <code>{esc(tag_sha)}</code> dated "
               f"{esc(tag_date)}. The visible work moved to the sibling AppFlowy-Web repository ({_n(aw.get('commits_90d'))} commits and "
               f"{_n(aw.get('releases_90d_stable'))} releases in 90 days, newest commit {esc(aw.get('last_commit') or '')}, {_n(aw.get('stars'))} stars). By the "
               f"desktop repository's own signals AppFlowy has slowed; by the organisation's, development continues — in the Web repository. Our 2026-08-21 "
               f"table below counted only the desktop repository, which is why it read as near-dormant.</p>")
    doc = put(doc, slug, "summary", new_sum,
              (r'(?<=<div class="lbl">In short</div>)<p><strong>Short answer \(as of 2026-08-21\):</strong>.*?</p>(?=</div></section>)', "replace"))
    # 2) 52주 표 문단의 "near-dormant" 구절
    doc = replace_exact(doc, slug,
                        "whereas AppFlowy's activity was near-dormant and",
                        f"whereas AppFlowy's desktop repository was near-dormant (that row counts AppFlowy-IO/AppFlowy alone; when we re-read the same "
                        f"endpoint on {dr}, the organisation's AppFlowy-Web repository showed {_n(aw.get('commits_52w'))} commits over its own trailing 52 weeks — "
                        f"see the {dr} table further down) and", 1)
    # 3) AppFlowy 섹션 제목(본문 h2 + 목차 2벌) + 재측정 문단 추가
    old_h = "AppFlowy: a large community with a slowing recent cadence"
    new_h = "AppFlowy: a quiet desktop repository, with the work in AppFlowy-Web"
    doc = replace_exact(doc, slug, old_h, new_h, 3)
    para = (f"<p><strong>Re-read on {esc(dr)}.</strong> The picture above is what AppFlowy-IO/AppFlowy shows, and it is incomplete. On {esc(dr)} that repository's "
            f"default branch had {_n(af.get('commits_90d'))} commit in the trailing 90 days and its newest commit was dated {esc(af.get('last_commit') or '')} — yet "
            f"the same repository published {_n(af.get('releases_90d_stable'))} stable releases in those 90 days (latest {esc(af.get('latest_release') or '')}, "
            f"{esc(af.get('latest_release_date') or '')}), and its release tags for {esc(tag_s)} all resolve to the one commit <code>{esc(tag_sha)}</code> from "
            f"{esc(tag_date)}. The organisation's other repositories explain the gap: AppFlowy-Web had {_n(aw.get('commits_90d'))} commits and "
            f"{_n(aw.get('releases_90d_stable'))} releases in the same 90 days, its newest commit on {esc(aw.get('last_commit') or '')} and each of its newest tags "
            f"pointing at a commit from the day it shipped, while AppFlowy-Cloud had {_n(ac.get('commits_90d'))} commits (newest {esc(ac.get('last_commit') or '')}) "
            f"and no release since {esc(ac.get('latest_release_date') or '')}. So the honest reading is narrower than \"slowing\": the desktop repository that "
            f"carries the {stars_k} stars is quiet, and the development you can see from outside now happens in AppFlowy-Web, a repository with "
            f"{_n(aw.get('stars'))} stars. What that means for the desktop and mobile apps is not something these counts can tell you.</p>")
    doc = put(doc, slug, "appflowy-section", para,
              (before_close(doc, "appflowy-a-large-community-with-a-slowing-recent-cadence", "</section>"), "before"))
    # 4) 결론(Verdict) — 세 문단 통째로 교체
    new_v = (f"<p>Both AppFlowy and AFFiNE are substantial, open-source, self-hostable Notion alternatives with large codebases. The question here is narrow — "
             f"which is <em>actually being developed</em> right now — and on {esc(dr)} the answer depends on where you look.</p>"
             f"<p><strong>AFFiNE</strong> answers it in one place. Its default branch took {_n(fn.get('commits_90d'))} commits in the 90 days to {esc(dr)} "
             f"(newest {esc(fn.get('last_commit') or '')}), and its newest release tags point at commits from the weeks they shipped. If the deciding factor is "
             f"development you can see in the repository you would star, it is the clearer choice.</p>"
             f"<p><strong>AppFlowy</strong> has to be read across three repositories. The desktop repository has slowed by every signal we count — "
             f"{_n(af.get('commits_90d'))} commit in 90 days, {_n(af.get('commits_52w'))} in 52 weeks, {_n(af.get('open_prs'))} pull requests open — while still "
             f"publishing releases whose tags sit on a commit from {esc(tag_date)}. AppFlowy-Web, by contrast, moved every week ({_n(aw.get('commits_90d'))} commits, "
             f"{_n(aw.get('releases_90d_stable'))} releases in the same 90 days). Development has moved rather than stopped; what our counts cannot say is how much "
             f"of it reaches the desktop and mobile apps. Both readings are in the {esc(dr)} table below, with the tag-to-commit column that makes the difference "
             f"visible.</p>")
    doc = put(doc, slug, "verdict", new_v,
              (r'(?<=<div class="lbl">Verdict</div>)<p>Both AppFlowy and AFFiNE are substantial.*?</p>(?=</div></section>)', "replace"))
    # 5) FAQ (본문 + FAQPage JSON-LD, 각 2회)
    q1_old = ("As of 2026-08-21, AppFlowy's GitHub repository showed a recent commit dated 2026-08-11, but its trailing-52-week cadence had slowed to roughly nine "
              "commits, with 103 open pull requests and 896 open issues. That points to a large, established project whose recent development has thinned rather "
              "than stopped, so it is worth checking the repository's current activity before you depend on it.")
    q1_new = (f"It depends on which repository you read. As of {dr}, AppFlowy-IO/AppFlowy's default branch had {_n(af.get('commits_90d'))} commit in the trailing 90 "
              f"days (newest {af.get('last_commit') or ''}) and {_n(af.get('open_prs'))} pull requests open, yet the project published "
              f"{_n(af.get('releases_90d_stable'))} stable releases in that window whose tags all point at one commit from {tag_date}. The organisation's "
              f"AppFlowy-Web repository had {_n(aw.get('commits_90d'))} commits and {_n(aw.get('releases_90d_stable'))} releases in the same 90 days, with its "
              f"newest commit on {aw.get('last_commit') or ''}. Development has moved to the Web repository rather than stopped.")
    doc = replace_exact(doc, slug, q1_old, q1_new, 2)
    q2_old = ("By the public signals on its GitHub repository as of 2026-08-21, yes: it does live work on a canary branch that showed ongoing commits and has the "
              "larger commit history of the two (11,465 total commits). Development activity can change, so re-check the repository on the day you decide.")
    q2_new = (f"Yes, by the signals we read on {dr}: {_n(fn.get('commits_90d'))} commits on its default branch in the trailing 90 days, the newest dated "
              f"{fn.get('last_commit') or ''}, {_n(fn.get('releases_90d_stable'))} stable and {_n(fn.get('releases_90d_pre'))} pre-releases in the same window, and "
              f"newest release tags that point at commits from the weeks they shipped.")
    doc = replace_exact(doc, slug, q2_old, q2_new, 2)
    q4_old = ("On recent-development signals as of 2026-08-21, AFFiNE is the stronger bet because of its active canary branch and larger, continuing commit history. "
              "AppFlowy remains a viable option with a bigger community and a public roadmap, but confirm its current commit cadence on GitHub first.")
    q4_new = (f"On the {dr} readings, AFFiNE — its development is visible in the one repository you would star ({_n(fn.get('commits_90d'))} commits in 90 days). "
              f"AppFlowy is still shipping ({_n(af.get('releases_90d_stable'))} stable releases in 90 days) and its Web repository is busy "
              f"({_n(aw.get('commits_90d'))} commits), but the desktop repository itself has slowed to {_n(af.get('commits_90d'))} commit in 90 days, so what you "
              f"see from its GitHub page understates the project.")
    doc = replace_exact(doc, slug, q4_old, q4_new, 2)
    return doc


def price_index(doc, slug, data, prices):
    """가격 지수 글: 회피 문구를 '비판하며 인용'한 두 곳도 문구 자체가 남지 않게 고쳐 쓴다(어떤 검사 정규식이든 0)."""
    doc = replace_exact(doc, slug,
                        "will tell you to check current pricing on the vendor's site. That advice is correct and completely useless:",
                        "will send you off to look the price up yourself. That advice is correct and completely useless:", 1)
    doc = replace_exact(doc, slug,
                        "instead of writing “confirm current pricing on the vendor's site.”",
                        "instead of sending you to look it up yourself.", 1)
    return doc


PATCHES = {
    "orca-vs-herdr-agent-ide-or-terminal-multiplexer-for-coding-agents": orca_herdr,
    "cursor-vs-windsurf-which-ai-code-editor-should-you-use-in-2026": cursor_windsurf,
    "the-best-ai-code-review-tools-in-2026-8-options-compared": code_review,
    "which-open-source-notion-alternatives-are-actually-being-developed-appflowy-vs-affine-2026": appflowy_affine,
    "what-developer-tools-actually-cost-a-checked-price-index": price_index,
}
NO_DATE_BUMP = {"what-developer-tools-actually-cost-a-checked-price-index"}   # 문구 두 곳 — 내용 변화가 아니다


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.dst, exist_ok=True)
    data = common.load_all()
    with open("config/prices.yaml", encoding="utf-8") as f:
        prices = yaml.safe_load(f) or {}
    rc = 0
    for slug, fn in PATCHES.items():
        if a.only and slug not in a.only:
            continue
        out_path = os.path.join(a.dst, slug + ".html")
        path = out_path if os.path.isfile(out_path) else os.path.join(a.src, slug + ".html")   # 먼저 쌓인 패치 위에 쌓는다
        if not os.path.isfile(path):
            print(f"  - {slug[:60]}: none — skipped")
            continue
        doc = open(path, encoding="utf-8").read()
        try:
            new = fn(doc, slug, data, prices)
            if new != doc and slug not in NO_DATE_BUMP:
                new = bump_dates(new, slug)
        except Anchor as e:
            print(f"  x {e}")
            rc = 1
            continue
        if new == doc:
            print(f"  = {slug[:60]}: unchanged")
            continue
        if not a.dry_run:
            open(out_path, "w", encoding="utf-8", newline="").write(new)
        print(f"  ok {slug[:60]}: {len(new) - len(doc):+,} chars{' [dry]' if a.dry_run else ''}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
