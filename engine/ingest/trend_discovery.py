"""trend_discovery.py — **저가시성** 후보 발굴 (trend_axis 풀 채우기 전용).

⚠️ 이름에 주의: 이 축은 '최신성(recency)'이 아니라 **'저가시성(low visibility)'** 이다.
   우리는 오랫동안 "신생 툴을 찾는다"고 생각했지만 **실측에서 이긴 변수는 나이가 아니라 가시성**이었다.
   *스타가 적다* 와 *새것이다* 는 다른 조건이고, **오래됐지만 안 알려진 프로젝트도 스타가 적다.**
   메커니즘상으로도 집계 농장은 나이가 아니라 **DB 등재 여부**로 움직이므로 스타가 옳은 변수다.
   → 이름을 틀리게 두면 다음 사람이 다시 나이로 찾는다.

━━ 근거: 신호 검정 (2026-08-01, 라벨된 23개 짝 · 기준3 통과 12 / 탈락 11) ━━━━━━━━━━━━━
    신호                     분리력(AUC)
    첫 릴리스 후 경과일        0.570 / 0.562   ← 거의 무작위(설계 초안이 주 신호로 권고했던 것)
    생성 후 경과일             0.765 / 0.777
    스타/일                   0.879 / 0.705
    **절대 스타수**            **0.924 / 0.928**   ← 최고. 순열검정 p=0.0001(20,000회)

    최적 임계: **min(stars) 11,672 → 오분류 1/23 (4%)** · max 기준은 2/23
    **min 이 더 깨끗한 이유가 메커니즘과 일치한다**: 집계 농장은 **양쪽 제품이 모두 자기 DB 에 있어야**
    쌍 페이지를 만든다 → 짝의 안전성은 **덜 알려진 쪽**이 좌우한다.
    실례: `paneflow vs cmux` — cmux 는 25,451 스타로 유명하지만 **paneflow 가 43 스타라 쌍 페이지가 없다.**

━━ 🔴 하한을 두지 않는 이유 (PM 2026-08-01) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    저가시성은 **이길 확률**을 올리지만 **검색 수요**도 같이 낮춘다. 너무 무명이면 이겨도 아무도 안 찾는다.
    `orca-vs-herdr` 이 63 방문을 만든 건 herdr 이 **실제로 뜨고 있었기 때문일 수 있다.**
    즉 min(stars) 는 낮을수록 좋은 게 아니라 **최적 구간**이 있을 것이다 — 그런데 그건 지금 데이터로 못 잰다.
    트렌드 축 글이 라이브에 쌓이고 유입이 붙어야 잰다.
    → **하한을 지금 넣지 않는다.** 대신 후보마다 min(stars) 를 **기록**해 두고 나중에 실제 유입과 대조한다.
    **이기는 조건은 쟀고 팔리는 조건은 아직 못 쟀다 — 그 둘을 같은 숫자로 가정하지 않는다.**

━━ ⚠️ 모수 한계 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    검정 모수는 **우리 조사 이력에 한정**된다 — 전부 개발자 툴 OSS 다.
    다른 니치로 넓힐 때 **이 임계(11,672)를 그대로 쓰면 안 된다.** 그 니치에서 다시 재야 한다.

━━ 🔴 게이트 불변 (구조로 보장) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    이 모듈은 `dist/research/trend-pool.json` **에만** 쓴다. **제안일 뿐이다.**
    · `orchestrator` 는 `config/topics.yaml` 의 `trend_axis.candidates` **만** 읽는다.
    · 이 산출물을 읽는 코드 경로는 **어디에도 없다**(그래서 orchestrator 를 건드리지 않는다).
    → 발굴된 후보가 3기준 심사를 우회해 생성에 도달할 **경로 자체가 존재하지 않는다.**
    승격은 사람이 한다: 3기준(공식 docs 200 · 공개 저장소 · 제3자 심층 1:1 부재) + 등가성(kind)
    + 관측표 `usable()` + **수명주기 이벤트 확인** 을 전부 통과해야 `candidates` 에 들어간다.
    ⚠️ 발굴이 늘고 통과가 그대로면 **탈락률이 오르는 게 정상**이다.

⛔ 하지 않는 것
    · 집계 농장(openalternative·slashdot·alternativeto…) 크롤 금지 — 기준(3) 자동판정은 자격 자동화다.
    · 짝 짓기 금지 — `kind` 등가성은 사람의 선언이다. 이 모듈은 **엔티티만** 내놓는다.
    · 쓰기·인증·robots 우회 없음. 공개 REST **GET 만**(F3 리스크 0).

사용
    python engine/ingest/trend_discovery.py            # config 의 discovery.enabled 가 true 일 때만 동작
    python engine/ingest/trend_discovery.py --dry-run  # 호출 없이 계획만
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse

_ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from content import observed  # noqa: E402  — SSRF 가드·UTC 캐시·크기상한·호출로그를 그대로 상속

OUT = os.path.join("dist", "research", "trend-pool.json")
SEARCH = "https://api.github.com/search/repositories"
API = "https://api.github.com"


def _cfg(cfg) -> dict:
    return ((cfg.get("topics") or {}).get("trend_axis") or {}).get("discovery") or {}


def _entity(full_name: str, item: dict, now: dt.datetime) -> dict:
    """검색 결과 1건 → 후보 엔티티 레코드(제안). 자격 판정은 하지 않는다."""
    created = observed._parse_dt(item.get("created_at"))
    pushed = observed._parse_dt(item.get("pushed_at"))
    age = (now - created).days if created else None
    stars = int(item.get("stargazers_count") or 0)
    return {
        "repo": full_name,
        "stars": stars,                                   # 🔴 주 신호(저가시성)
        "stars_per_day": round(stars / max(age or 1, 1), 2),
        "created": created.date().isoformat() if created else None,
        "age_days": age,
        "last_push": pushed.date().isoformat() if pushed else None,
        "homepage": (item.get("homepage") or "").strip(),
        "description": (item.get("description") or "")[:200],
        "archived": bool(item.get("archived")),
        "license": ((item.get("license") or {}) or {}).get("spdx_id"),
        # ── 사람이 승격 전에 반드시 채우고 확인할 칸 (자동으로 정하지 않는다) ──
        "_needs_human": {
            "official_url_200": None,      # 기준(1) 공식 docs 200 실호출 확인
            "third_party_1to1": None,      # 기준(3) 제3자 심층 1:1 비교글 존재 여부(검색)
            "kind": None,                  # 등가성 — 사람의 선언
            "lifecycle_ok": None,          # 폐기·이관·은퇴 여부(스타 신호가 원리상 못 잡는 축)
            "observed_usable": None,       # 짝을 지은 뒤 usable() 확인
        },
    }


def run(cfg, *, dry_run: bool = False) -> dict:
    d = _cfg(cfg)
    if not d.get("enabled"):
        print("discovery: config trend_axis.discovery.enabled=false — 아무것도 하지 않는다")
        return {"enabled": False, "entities": []}
    budget = int(d.get("max_calls", 20))
    queries = [q for q in (d.get("queries") or []) if isinstance(q, str) and q.strip()]
    if not queries:
        print("discovery: 질의가 비어 있다(config trend_axis.discovery.queries) — 중단")
        return {"enabled": True, "entities": []}
    now = dt.datetime.now(dt.timezone.utc)
    print(f"discovery: 질의 {len(queries)}개 · 호출 상한 {budget} "
          f"(⚠️ 생성 경로 우선 — 상한을 넘기면 발굴을 포기한다)")
    if dry_run:
        for q in queries:
            print(f"  (dry-run) {SEARCH}?q={q}")
        return {"enabled": True, "dry_run": True, "entities": []}

    calls, seen, ents = [], set(), []
    for q in queries:
        if len(calls) >= budget:
            print(f"discovery: 호출 상한 {budget} 도달 — 남은 질의를 포기한다(생성 경로를 방해하지 않는다)")
            break
        # ⚠️ 질의를 반드시 인코딩한다 — 공백·`:`·`>` 가 그대로 들어가면 urllib 이 InvalidURL 로 죽는다
        #    (첫 판이 이 버그로 전 질의 실패했다. 실패가 "빈 결과"처럼 보여 조용했다.)
        url = f"{SEARCH}?q={urllib.parse.quote(q)}&sort=updated&order=desc&per_page=30"
        data = observed._get_json(url, int(d.get("timeout", 15)), calls)
        if not isinstance(data, dict):
            print(f"  ⚠️ 질의 호출 실패(status={calls[-1]['status'] if calls else '?'}): {q}")
            continue
        items = data.get("items") or []
        if not items:
            print(f"  질의 결과 0건(정상 응답): {q}")
            continue
        for it in items:
            fn = (it or {}).get("full_name")
            if not fn or fn in seen:
                continue
            seen.add(fn)
            ents.append(_entity(fn, it, now))
        print(f"  '{q}' → {len(items)}건")

    # 🔴 저가시성 우선 정렬. **하한 없음** — 낮을수록 무조건 좋다는 뜻이 아니라,
    #    최적 구간을 아직 못 쟀으므로 값을 기록해 두고 나중에 유입과 대조하기 위함이다.
    ents.sort(key=lambda e: (e["stars"], e["stars_per_day"]))
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "axis": "low-visibility",          # ⚠️ 'recency' 아니다 — 이긴 변수는 나이가 아니라 가시성이다
        "ranked_by": "stars ascending (저가시성) · tiebreak stars_per_day",
        "no_lower_bound": ("이기는 조건(가시성 낮음)은 쟀지만 팔리는 조건(검색 수요)은 아직 못 쟀다. "
                           "하한을 두지 않고 값만 기록해 라이브 유입과 대조할 것."),
        "signal_basis": {"study": "2026-08-01 · n=23 pairs · AUC(min stars)=0.924 · p=0.0001",
                         "optimal_threshold_min_stars": 11672,
                         "population_caveat": "개발자 툴 OSS 한정 — 다른 니치에 이 임계를 그대로 쓰지 말 것"},
        "gate_note": ("제안일 뿐이다. orchestrator 는 이 파일을 읽지 않는다. "
                      "승격은 사람이 3기준+등가성+usable()+수명주기 확인을 거쳐 topics.yaml 에 적을 때만."),
        "api_calls": len(calls),
        "entities": ents,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"discovery: 후보 {len(ents)}개(저가시성 순) · API {len(calls)}콜 → {OUT}")
    print("  ⚠️ 이 파일은 **제안**이다. 사람이 3기준·등가성·usable()·수명주기를 확인해 승격해야 시드가 된다.")
    for e in ents[:8]:
        print(f"    {e['stars']:>7,}★ {e['repo']:<40} {(e['description'] or '')[:52]}")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="저가시성 후보 발굴(제안 전용 — 게이트를 넓히지 않는다)")
    p.add_argument("--dry-run", action="store_true", help="호출 없이 질의 계획만 출력")
    a = p.parse_args(argv)
    import yaml
    cfg = {}
    for n in ("topics",):
        with open(f"config/{n}.yaml", encoding="utf-8") as f:
            cfg[n] = yaml.safe_load(f)
    run(cfg, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
