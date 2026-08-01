"""source_fetch.py — 콘텐츠 그라운딩용 공식 소스 페치 (AUTOMATION.md §0 🟢 읽기전용 데이터수집).

목적: 생성 전 벤더 공식 페이지(pricing/docs)의 **실제 텍스트**를 가져와 프롬프트에 주입 →
모델이 "읽은 것"으로 정확·최신 비교를 쓰게 한다. 소스 URL 유효성 검증도 제공.

⛔ 트래픽/클릭 생성과 무관 — 순수 읽기(사람이 자료 조사하듯). robots.txt 존중 · rate-limit ·
실패 시 graceful(빈 결과 → 생성기가 기존 방식으로 폴백). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

UA = "utilverse.info-research/1.0 (+https://utilverse.info/about/; content grounding, read-only)"
_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _robots_ok(url: str, timeout: int = 8) -> bool:
    """robots.txt 존중 — Disallow 면 페치 안 함. robots 조회 실패 시 허용(관행)."""
    try:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
    except Exception:
        return False
    if base not in _ROBOTS_CACHE:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                rp.parse(resp.read().decode("utf-8", "replace").splitlines())
            _ROBOTS_CACHE[base] = rp
        except Exception:
            _ROBOTS_CACHE[base] = None          # 조회 실패 → 허용(폴백)
    rp = _ROBOTS_CACHE[base]
    if rp is None:
        return True
    try:
        return rp.can_fetch(UA, url)
    except Exception:
        return True


_TAG_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def extract_readable(raw_html: str, max_chars: int = 4000) -> str:
    """HTML → 사람이 읽는 텍스트(스크립트/스타일 제거, 태그 제거, 공백 정리, 절단)."""
    t = _TAG_DROP.sub(" ", raw_html)
    t = re.sub(r"<(br|/p|/div|/li|/tr|/h[1-6])\s*>", "\n", t, flags=re.I)
    t = _TAGS.sub(" ", t)
    t = html.unescape(t)
    t = _WS.sub(" ", t)
    t = _NL.sub("\n\n", t)
    lines = [ln.strip() for ln in t.splitlines()]
    t = "\n".join(ln for ln in lines if ln)
    return t[:max_chars].strip()


def check_url(url: str, timeout: int = 12) -> int | str:
    """URL 유효성 — 상태코드(int) 또는 예외명(str). HEAD 거부(403/405) 시 GET 폴백."""
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        return "invalid"
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            if e.code in (403, 405) and method == "HEAD":
                continue                        # HEAD 거부 → GET 재시도
            return e.code
        except Exception as e:
            return type(e).__name__
    return "?"


def url_ok(url: str, timeout: int = 12) -> bool:
    st = check_url(url, timeout)
    return isinstance(st, int) and 200 <= st < 400


def validate_sources(sources: list, timeout: int = 12) -> tuple[list, list]:
    """[{title,url}] → (유효, 제거됨). 200~3xx 만 유효. 생성기가 죽은 인용을 걸러내는 용도."""
    good, dropped = [], []
    for s in sources or []:
        if url_ok(s.get("url", ""), timeout):
            good.append(s)
        else:
            dropped.append(s)
    return good, dropped


def fetch(url: str, *, timeout: int = 12, max_chars: int = 4000) -> dict:
    """단일 URL 페치 → {url, ok, status, text}. robots 금지·오류 시 ok=False, text=''."""
    out = {"url": url, "ok": False, "status": None, "text": ""}
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        out["status"] = "invalid"
        return out
    if not _robots_ok(url):
        out["status"] = "robots-disallow"
        return out
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out["status"] = resp.status
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "text" not in ctype:
                return out                      # 비HTML(이미지·PDF 등)은 스킵
            raw = resp.read(1_500_000).decode("utf-8", "replace")
        out["text"] = extract_readable(raw, max_chars)
        out["ok"] = bool(out["text"])
    except urllib.error.HTTPError as e:
        out["status"] = e.code
    except Exception as e:
        out["status"] = type(e).__name__
    return out


def gather(urls: list, *, timeout: int = 12, max_chars: int = 4000,
           max_sources: int = 6, delay: float = 0.6) -> list:
    """여러 공식 URL 페치(중복 제거·상한·rate-limit) → 성공분만 [{url,text}] 리스트."""
    seen, out = set(), []
    for u in urls or []:
        if len(out) >= max_sources:
            break
        if not u or u in seen:
            continue
        seen.add(u)
        r = fetch(u, timeout=timeout, max_chars=max_chars)
        if r["ok"]:
            out.append({"url": r["url"], "text": r["text"]})
        if delay:
            time.sleep(delay)                   # 예의상 간격(과도한 요청 방지)
    return out
