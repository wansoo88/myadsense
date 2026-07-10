"""devto.py — 발행된 라이브 글을 dev.to 에 canonical 신디케이션 (earned backlink + 유입).

정책 안전선(docs/RESEARCH.md F3, AUTOMATION.md §0):
  - dev.to 는 **공식 발행 API**가 있고, 본인 계정에 본인 글을 canonical(원문=stack.) 걸어 올리는 것은
    ToS 허용 범위 + 스팸 아님. Reddit/HN 류 커뮤니티 자동 게시와는 전혀 다르다(그건 여전히 금지).
  - canonical 을 원문으로 → 검색 랭킹 경쟁 없이 backlink·referral 만 확보.
  - **속도 제한**(per_run, 기본 1) — 대량 동시 게시는 스팸성으로 보일 수 있어 절제.

동작: dist/site 의 라이브 글(sitemap /compare/)을 하나씩(캡만큼) dev.to 에 발행. 이미 올린 글은
  상태파일로 건너뜀(멱등). 실배포처럼 **기본 DRY-RUN** — ADSENSE_SYNDICATE=1 일 때만 실제 POST.
인증: .env 의 DEVTO_API_KEY (없으면 스킵). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import urllib.request
from html.parser import HTMLParser

SITE_DIR = "dist/site"
STATE = "engine/store/devto_state.json"
API = "https://dev.to/api/articles"
TIMEOUT = 30

# 본문에서 제거할 크롬(클래스) — 광고·breadcrumb·저자박스·관련글·메타바·모바일TOC·사이드바 등
_SKIP_CLASSES = {"ad-slot", "crumb", "authorbox", "related", "metabar",
                 "tocm", "toc", "aside", "draft", "sechead", "kicker"}
_VOID = {"br", "img", "hr", "meta", "link", "input", "source", "col", "area", "base", "wbr"}
_SKIP_TAGS = {"script", "style", "svg", "form", "button", "nav", "aside", "header", "footer", "time"}

# cluster → dev.to 태그(소문자 영숫자, 최대 4)
_TAGS_BY_CLUSTER = {
    "ai-coding-tools": ["ai", "programming", "productivity"],
    "hosting-selfhost": ["selfhosted", "devops", "webdev"],
    "dev-saas-compare": ["webdev", "devops", "programming"],
    "ai-productivity": ["ai", "productivity", "tools"],
    "vpn-security": ["security", "privacy", "tools"],
}
_DEFAULT_TAGS = ["webdev", "tools"]


# ─────────────────────────── HTML → Markdown ───────────────────────────
class _Md(HTMLParser):
    """<article> 내부만, 크롬 서브트리는 건너뛰고 마크다운으로 변환."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url.rstrip("/")
        self.md: list[str] = []
        self.inline: list[str] = []
        self.in_article = False
        self.depth = 0                 # <article> 기준 상대 깊이
        self.skipping = False
        self.skip_depth = 0
        self.lists: list[str] = []     # 'ul'|'ol'
        self.ol_counters: list[int] = []
        self.href_stack: list[str] = []
        # 표
        self.table = None              # list[row]; row=list[str]
        self.row = None
        self.cell = None               # 현재 셀 인라인 버퍼(list)
        self.cell_is_header = False
        self.row_is_header = False

    def _emit(self, s: str):
        (self.cell if self.cell is not None else self.inline).append(s)

    def _flush_block(self, prefix: str = ""):
        text = re.sub(r"[ \t]+", " ", "".join(self.inline)).strip()
        self.inline = []
        if text:
            self.md.append(prefix + text)

    def _abs(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith(("http://", "https://", "mailto:")):
            return href
        if href.startswith("#"):
            return ""            # 페이지 내 앵커 → dev.to 에서 무의미, 링크 제거
        if href.startswith("/"):
            return self.base + href
        return href

    def handle_starttag(self, tag, attrs):
        if not self.in_article:
            if tag == "article":
                self.in_article = True
                self.depth = 0
            return
        if tag in _VOID:
            if not self.skipping and tag == "br":
                self._emit("  \n")
            return
        cls = set((dict(attrs).get("class") or "").split())
        if not self.skipping and (cls & _SKIP_CLASSES or tag in _SKIP_TAGS):
            self.skipping = True
            self.skip_depth = self.depth
        self.depth += 1
        if self.skipping:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush_block();
        elif tag == "p":
            self._flush_block()
        elif tag == "blockquote":
            self._flush_block()
        elif tag in ("ul", "ol"):
            self._flush_block()
            self.lists.append(tag)
            self.ol_counters.append(0)
        elif tag == "li":
            self._flush_block()
        elif tag == "table":
            self._flush_block()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
            self.row_is_header = False
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.cell_is_header = (tag == "th")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "a":
            self.href_stack.append(self._abs(dict(attrs).get("href", "")))
            self._emit("[")

    def handle_endtag(self, tag):
        if not self.in_article or tag in _VOID:
            return
        self.depth -= 1
        if self.depth < 0:                 # </article>
            self.in_article = False
            return
        if self.skipping:
            if self.depth == self.skip_depth:
                self.skipping = False
            return
        if tag == "h1":
            self.inline = []          # dev.to 가 payload title 을 H1 으로 렌더 → 본문 중복 H1 제거
        elif tag in ("h2", "h3", "h4"):
            self._flush_block({"h2": "## ", "h3": "### ", "h4": "#### "}[tag])
        elif tag == "p":
            self._flush_block()
        elif tag == "blockquote":
            self._flush_block("> ")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
                self.ol_counters.pop()
        elif tag == "li":
            indent = "  " * max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1] == "ol":
                self.ol_counters[-1] += 1
                marker = f"{self.ol_counters[-1]}. "
            else:
                marker = "- "
            text = re.sub(r"[ \t]+", " ", "".join(self.inline)).strip()
            self.inline = []
            if text:
                self.md.append(indent + marker + text)
        elif tag in ("td", "th") and self.cell is not None:
            val = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|")
            self.row.append(val or " ")
            if self.cell_is_header:
                self.row_is_header = True
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row_is_header:
                self.row.insert(0, "__HEADER__")
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self._render_table()
            self.table = None
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "a":
            url = self.href_stack.pop() if self.href_stack else ""
            self._emit("]" + (f"({url})" if url else ""))

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.in_article and not self.skipping:
            self._emit("  \n")

    def handle_data(self, data):
        if self.in_article and not self.skipping and data:
            self._emit(data)

    def _render_table(self):
        rows = [r for r in self.table if r]
        if not rows:
            return
        header, body = None, []
        for r in rows:
            if r and r[0] == "__HEADER__":
                header = r[1:]
            else:
                body.append(r)
        if header is None:
            header = body.pop(0) if body else []
        if not header:
            return
        ncol = len(header)
        self.md.append("| " + " | ".join(header) + " |")
        self.md.append("| " + " | ".join(["---"] * ncol) + " |")
        for r in body:
            cells = (r + [" "] * ncol)[:ncol]
            self.md.append("| " + " | ".join(cells) + " |")


def html_to_markdown(article_html: str, base_url: str) -> str:
    p = _Md(base_url)
    p.feed(article_html)
    p._flush_block()
    body = "\n\n".join(b for b in p.md if b.strip())
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# ─────────────────────────── 페이지 메타 추출 ───────────────────────────
def _meta(html: str) -> dict:
    def find(pat):
        m = re.search(pat, html, re.I | re.S)
        return _html.unescape(m.group(1).strip()) if m else ""
    return {
        "title": find(r"<title>(.*?)</title>"),
        "description": find(r'<meta\s+name="description"\s+content="([^"]*)"'),
        "cluster": find(r'<meta\s+name="cluster"\s+content="([^"]*)"'),
    }


def _article_html(full_html: str) -> str:
    m = re.search(r"<article\b[^>]*>.*?</article>", full_html, re.S | re.I)
    return m.group(0) if m else ""


def _tags(cluster: str) -> list:
    return (_TAGS_BY_CLUSTER.get(cluster) or _DEFAULT_TAGS)[:4]


# ─────────────────────────── 상태 ───────────────────────────
def _load_state() -> dict:
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(d: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _sitemap_article_urls() -> list:
    p = os.path.join(SITE_DIR, "sitemap.xml")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        locs = re.findall(r"<loc>([^<]+)</loc>", f.read())
    return [u for u in locs if "/compare/" in u]   # 콘텐츠 기사만(허브·필수페이지 제외)


def _url_to_file(url: str, base: str):
    if not url.startswith(base):
        return None
    rel = url[len(base):].strip("/")
    cand = os.path.join(SITE_DIR, rel, "index.html")
    return cand if os.path.exists(cand) else None


def _post(payload: dict, api_key: str) -> tuple:
    data = json.dumps({"article": payload}).encode("utf-8")
    req = urllib.request.Request(API, data=data, method="POST", headers={
        "Content-Type": "application/json", "api-key": api_key,
        "Accept": "application/vnd.forem.api-v1+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _build_payload(url: str, file_path: str):
    with open(file_path, encoding="utf-8") as f:
        full = f.read()
    meta = _meta(full)
    art = _article_html(full)
    if not meta["title"] or not art:
        return None
    body = html_to_markdown(art, url)
    if len(body) < 400:                    # 추출 실패/빈약 → 스킵(안전)
        return None
    footer = f"\n\n---\n\n*Originally published at [{url}]({url}).*"
    return {
        "title": meta["title"][:250],
        "body_markdown": body + footer,
        "published": True,
        "canonical_url": url,
        "description": meta["description"][:250],
        "tags": _tags(meta["cluster"]),
    }


def run(cfg) -> int:
    """라이브 글을 dev.to 에 canonical 신디케이션. 반환: 신규 발행 수(0=스킵)."""
    site = cfg["sites"]["sites"][0]
    domain = site.get("domain", "stack.utilverse.info")
    base = f"https://{domain}"
    syn = (cfg["sites"].get("syndication") or {}).get("devto") or {}
    per_run = max(1, int(syn.get("per_run", 1)))
    api_key = (os.environ.get("DEVTO_API_KEY") or "").strip()
    live = os.environ.get("ADSENSE_SYNDICATE") == "1"

    if not syn.get("enabled"):
        print("  devto: syndication.devto.enabled=false → 스킵")
        return 0
    if not api_key:
        print("  devto: DEVTO_API_KEY 없음 → 스킵")
        return 0
    urls = _sitemap_article_urls()
    if not urls:
        print("  devto: dist/site/sitemap.xml 에 /compare/ 글 없음 → 스킵")
        return 0

    state = _load_state()
    todo = [u for u in urls if u not in state][:per_run]
    if not todo:
        print(f"  devto: 신규 없음(이미 {len(state)}편 신디케이션) → 스킵")
        return 0

    n = 0
    for url in todo:
        fp = _url_to_file(url, base)
        if not fp:
            print(f"  devto: 파일 없음 {url} → 스킵")
            continue
        payload = _build_payload(url, fp)
        if not payload:
            print(f"  devto: 본문 추출 실패/빈약 {url} → 스킵")
            continue
        if not live:
            print(f"  devto DRY-RUN: '{payload['title']}' tags={payload['tags']} "
                  f"body={len(payload['body_markdown'])}자 canonical={url} (실제 발행: ADSENSE_SYNDICATE=1)")
            continue
        try:
            status, resp = _post(payload, api_key)
        except Exception as e:
            print(f"  devto: 발행 실패({e}) {url} — 상태 미갱신(다음 실행 재시도)")
            continue
        if status in (200, 201):
            state[url] = {"id": resp.get("id"), "devto_url": resp.get("url"), "title": payload["title"]}
            _save_state(state)
            n += 1
            print(f"  devto: 발행 → {resp.get('url')} (canonical={url})")
        else:
            print(f"  devto: 예상외 응답 HTTP {status} {url}")
    if not live:
        print(f"  devto: DRY-RUN(실제 발행 안 함). 미신디케이션 총 {len(urls) - len(state)}편")
    return n


if __name__ == "__main__":
    import yaml
    with open("config/sites.yaml", encoding="utf-8") as f:
        run({"sites": yaml.safe_load(f)})
