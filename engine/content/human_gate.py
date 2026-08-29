"""human_gate.py — 품질 게이트 6번: 샘플 % 는 사람 승인 전엔 발행 큐 제외 (AUTOMATION.md §3, content.yaml human_sample_gate).

site_builder.build() 는 dist/queue/*.html 을 그대로 라이브에 반영하므로(글마다 스킵 로직 없음),
샘플로 뽑힌 글은 dist/queue 대신 dist/pending_approval 에 대기시켜 라이브에서 제외한다.
approve() 로 dist/queue 로 옮겨야 다음 build/deploy 부터 반영된다.
"""
from __future__ import annotations
import glob
import hashlib
import os
import shutil

PENDING_DIR = "dist/pending_approval"
QUEUE_DIR = "dist/queue"


def is_sampled(slug: str, sample_pct: int) -> bool:
    """슬러그 해시 기반 결정적 샘플링(같은 슬러그는 재실행해도 항상 같은 결과)."""
    if not sample_pct:
        return False
    h = int(hashlib.sha256(slug.encode("utf-8")).hexdigest(), 16)
    return (h % 100) < sample_pct


# 보류 사유 사이드카 (ORDER 2026-07-25-40 ②) — 사람이 slug 만 보고는 판단할 수 없다.
# 본문 HTML 에는 **손대지 않는다**(승인 시 그대로 발행되는 산출물이라 배너를 심으면 라이브로 나간다).
# 대신 같은 디렉터리에 사유 파일을 나란히 둔다 → 파일 목록만 열어도 읽힌다.
REASON_SUFFIX = ".reason.txt"
REJECTED_DIR = "dist/review"          # 사람이 거부한 초안 보존 위치(_keep_rejected_spec 와 같은 곳)
PUBLISHED_PATH = "engine/store/published.json"


def _reason_path(slug: str) -> str:
    return os.path.join(PENDING_DIR, f"{slug}{REASON_SUFFIX}")


def _keyword_from_reason(path: str) -> str | None:
    """보류 사유 파일에서 키워드를 읽는다 — `orchestrator._hold_notice` 가 적는 `키워드: <kw> · slug: <slug>`.

    왜 파일에서 읽나: slug 만으로는 키워드를 되찾을 수 없는 글이 있다(아래 unpublish 주석 참조).
    사유 파일은 보류 시점에 **키워드를 그대로** 적어 두므로 추론이 아니라 기록을 쓴다.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("키워드:"):
                    kw = line.split("키워드:", 1)[1].split("· slug:")[0].strip()
                    return kw or None
    except OSError:
        pass
    return None


def unpublish(slug: str, keyword: str | None = None) -> str | None:
    """거부된 글의 키워드를 `published.json` 에서 뺀다. 뺀 키워드(해당 없으면 None).

    왜 필요한가(실측 2026-08-05): `orchestrator.stage_generate` 는 보류(hold)든 큐든 **가리지 않고**
    `published.add(kw)` 를 한다 → 사람이 거부해 **발행되지 않은** 글이 '발행됨'으로 남는다.
    실제로 `sculptor vs catnip` 이 라이브 404 인데 published.json 에 있었고, 로그의 '누적 발행'
    수치도 그만큼 부풀려졌다. 상태 파일이 사실과 어긋나는 것 자체가 문제이고, 부작용으로
    **그 주제는 영구히 건너뛰어진다** — 다시 쓰려 해도 생성 루프가 조용히 스킵한다.

    ⚠️ 보류(hold) 시점에는 빼지 않는다. 승인 대기 중에 같은 주제가 매일 재생성되면
       `dist/pending_approval` 에 같은 주제가 쌓인다. **거부라는 확정 사건에만** 되돌린다.
    ⚠️ 검수 판정(`passed`)은 건드리지 않는다 — 여기서 바꾸는 것은 '발행됐는가'뿐이다.
    """
    import json
    if not os.path.exists(PUBLISHED_PATH):
        return None
    from content import renderer                       # 지연 임포트(이 모듈은 stdlib 만으로도 동작해야 한다)
    try:
        with open(PUBLISHED_PATH, encoding="utf-8") as f:
            kws = json.load(f)
        if not isinstance(kws, list):
            return None
        # 🔴 2026-08-29 실측: 아래 접두 규칙이 **트렌드 축 글에서는 절대 맞지 않는다**.
        #    그 축은 slug 를 키워드가 아니라 **제목**에서 만든다 —
        #      키워드 'the ai coding agents that did not exist three months ago'
        #        → 'the-ai-coding-agents-that-did-not-exist-three-months-ago'
        #      실제 slug 'the-new-ai-coding-agents-reasonix-vs-kun-compared'  (접두 불일치)
        #    그래서 reject() 가 조용히 아무것도 되돌리지 못했고, 이 docstring 이 막겠다던 바로 그 상태
        #    ('그 주제는 영구히 건너뛰어진다')가 그대로 벌어졌다. 재생성하려고 거부했는데 생성 루프가
        #    그 주제를 계속 '발행됨'으로 보고 건너뛴다 — 실패가 **조용해서** 더 나쁘다.
        #    → 호출부가 아는 키워드를 받으면 추론하지 않고 그것을 쓴다(기록 > 추론).
        if keyword and keyword in kws:
            payload = json.dumps(sorted(k for k in kws if k != keyword),
                                 ensure_ascii=False, indent=2)
            with open(PUBLISHED_PATH, "w", encoding="utf-8") as f:
                f.write(payload)
            return keyword
        # slug 는 '<키워드 slug>-<제목 꼬리>' 형태다 → **가장 긴** 접두 일치를 고른다
        # (regen.resolve_keyword 와 같은 규칙: 'cursor vs github copilot' 과 'cursor vs windsurf' 를 가른다).
        best, best_kw = "", None
        for kw in kws:
            ks = renderer.slugify(str(kw))
            if ks and (slug == ks or slug.startswith(ks + "-")) and len(ks) > len(best):
                best, best_kw = ks, kw
        if best_kw is None:
            return None
        payload = json.dumps(sorted(k for k in kws if k != best_kw),
                             ensure_ascii=False, indent=2)   # 문자열로 먼저 → 부분 파일 방지
        with open(PUBLISHED_PATH, "w", encoding="utf-8") as f:
            f.write(payload)
        return best_kw
    except Exception as e:                              # 기록 정정 실패가 거부 자체를 막지는 않는다
        print(f"  (published.json 정정 실패 — 거부는 그대로 유효) {type(e).__name__}: {e}")
        return None


def hold(slug: str, html_doc: str, reason: str = "") -> str:
    """승인 대기로 보류. **같은 내용을 두 번 보류해도 바이트가 같아야 한다**(멱등).

    🔴 왜 정규화가 필요한가 (2026-08-01 실측): 예전 판은 받은 문자열을 그대로 텍스트 모드로 썼다.
    호출부가 **파일에서 읽은 내용**(Windows 라 `\\r\\n`)을 넘기면 텍스트 모드가 `\\n` → `\\r\\n` 을 한 번 더
    적용해 `\\r\\r\\n` 이 되고 바이트가 불어난다 — 실측 49,125 B → 49,385 B.
    그러면 보류본이 게이트를 통과한 그 바이트가 아니게 되어 **판정과 산출물이 어긋난다**(43c 원칙 위반).
    파이프라인 경로(메모리 문자열)는 무사했지만, 기존 파일을 재보류하는 도구는 전부 깨졌다.

    → 개행을 먼저 `\\n` 으로 정규화한 뒤 쓴다. 쓰기 자체는 **기본 텍스트 모드 그대로** 둔다:
      `approve()` 가 `shutil.move` 로 이 파일을 그대로 큐에 옮기므로, 큐 산출물(`stage_generate` 도
      기본 텍스트 모드로 쓴다)과 개행 관례가 같아야 한다. 여기만 LF 로 바꾸면 큐 안에서 관례가 갈린다.
    """
    os.makedirs(PENDING_DIR, exist_ok=True)
    path = os.path.join(PENDING_DIR, f"{slug}.html")
    text = (html_doc or "").replace("\r\n", "\n").replace("\r", "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if reason:
        try:                                       # 사유 기록 실패가 보류 자체를 깨지 않게(부가 기능)
            with open(_reason_path(slug), "w", encoding="utf-8") as f:
                f.write(reason.rstrip() + "\n")
        except OSError:
            pass
    return path


def reason(slug: str) -> str:
    """보류 사유(없으면 빈 문자열)."""
    try:
        with open(_reason_path(slug), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def pending() -> list[str]:
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(f"{PENDING_DIR}/*.html"))


def pending_report() -> list[str]:
    """`--list-pending` 용 — slug + 보류 사유 + 처리 명령까지 한 화면에."""
    out = []
    for slug in pending():
        why = reason(slug) or "(사유 기록 없음 — 이 글은 사유 기록 도입 전에 보류됐다)"
        out.append(f"● {slug}\n" + "\n".join(f"    {ln}" for ln in why.splitlines()))
    return out


def approve(slug: str) -> str:
    src = os.path.join(PENDING_DIR, f"{slug}.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"승인 대기 중 아님: {src}")
    os.makedirs(QUEUE_DIR, exist_ok=True)
    dst = os.path.join(QUEUE_DIR, f"{slug}.html")
    shutil.move(src, dst)
    try:                                           # 사유 사이드카는 큐로 따라가지 않는다(발행 산출물 아님)
        os.remove(_reason_path(slug))
    except OSError:
        pass
    return dst


def reject(slug: str) -> str:
    """사람이 거부 — 발행하지 않고 보존만 한다(dist/review/<slug>.human-rejected.html).

    ⛔ 검수 판정(`passed`)을 바꾸지 않는다. 사람이 '이 글은 안 내보낸다'고 결정한 기록일 뿐이다.
    다만 `published.json` 의 '발행됨' 기록은 되돌린다 — 발행되지 않았기 때문이다(unpublish 참조)."""
    src = os.path.join(PENDING_DIR, f"{slug}.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"승인 대기 중 아님: {src}")
    os.makedirs(REJECTED_DIR, exist_ok=True)
    dst = os.path.join(REJECTED_DIR, f"{slug}.human-rejected.html")
    # 사유 파일을 옮기기 **전에** 키워드를 읽는다 — slug 접두 추론이 안 통하는 축이 있다(unpublish 주석).
    kw_recorded = _keyword_from_reason(_reason_path(slug))
    shutil.move(src, dst)
    try:
        os.replace(_reason_path(slug), os.path.join(REJECTED_DIR, f"{slug}.human-rejected.reason.txt"))
    except OSError:
        pass
    kw = unpublish(slug, keyword=kw_recorded)
    if kw:
        print(f"  published.json 정정 — '{kw}' 제거(발행되지 않았다). "
              f"⚠️ 이 주제는 다시 생성 대상이 된다 — 원치 않으면 config/topics.yaml 에서 후보를 빼라.")
    else:
        # 조용히 지나가면 안 된다: '거부했으니 다시 쓸 수 있다'고 믿은 채로 생성 루프는 계속 건너뛴다.
        print(f"  ⚠️ published.json 에서 이 글의 키워드를 찾지 못했다(slug={slug!r}, "
              f"사유파일 키워드={kw_recorded!r}). 거부 자체는 유효하지만 **이 주제는 여전히 "
              f"'발행됨'으로 남아 생성에서 건너뛰어질 수 있다** — 재생성하려면 직접 확인하라.")
    return dst
