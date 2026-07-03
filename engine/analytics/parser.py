"""parser.py — nginx 접속 로그 → 정규화·분류된 방문 레코드.

입력 2종:
  1) stack 전용 JSON 라인 로그(access_log ... stack_json) — 신뢰 소스(Host=stack 만 기록).
  2) (선택) 공용 combined 로그 백필 — Host 정보가 없어 stack 고유 경로 접두어만 안전 채택.

각 방문을 audience(self|bot|human) · category(content|asset|other) 로 태깅해
'나 빼고 사람' 통계와 봇 통계를 분리할 수 있게 한다. 표준 라이브러리만 사용.
"""
from __future__ import annotations

import glob
import gzip
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

# --- 분류 규칙 -------------------------------------------------------------
# 자산(집계 대상 아님): 확장자로 판별
ASSET_RE = re.compile(
    r"\.(?:css|js|mjs|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf|eot|map|"
    r"xml|txt|json|pdf|zip|gz|webmanifest|mp4|webm|wasm)(?:$|\?)", re.I)
# 봇/크롤러/스캐너 UA (소문자 부분일치)
BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|adsbot|mediapartners|feedfetch|"
    r"facebookexternalhit|whatsapp|telegrambot|discordbot|preview|"
    r"python-requests|python-urllib|curl|wget|go-http|okhttp|libwww|scrapy|httpx|aiohttp|"
    r"headless|phantom|selenium|puppeteer|playwright|"
    r"monitor|uptime|pingdom|statuscake|site24x7|newrelic|datadog|"
    r"semrush|ahrefs|mj12|dotbot|petalbot|dataforseo|serpstat|blexbot|"
    r"censys|zgrab|masscan|nmap|nuclei|expanse|paloalto|shodan|internetmeasurement",
    re.I)
# 스캐너/취약점 탐침 경로(사람 콘텐츠 아님) — 백필/분류 방어선
PROBE_RE = re.compile(
    r"(?:^|/)(?:\.env|\.git|wp-|xmlrpc|phpmyadmin|\.php|\.aws|\.ssh|"
    r"vendor/|config\.|backup|shell|eval-stdin|actuator|/\.well-known/security)",
    re.I)


@dataclass
class Hit:
    ts: datetime
    ip: str
    method: str
    path: str          # 쿼리 제외(그룹핑용)
    full: str          # 쿼리 포함(로그 표시용)
    status: int
    bytes: int
    referer: str
    ref_host: str
    ua: str
    device: str        # desktop | mobile | tablet | bot | other
    browser: str
    audience: str      # self | bot | human
    category: str      # content | asset | other
    source: str        # json | legacy

    @property
    def date(self) -> str:
        return self.ts.strftime("%Y-%m-%d")

    @property
    def hour(self) -> int:
        return self.ts.hour


def _open(path):
    return gzip.open(path, "rt", errors="replace") if path.endswith(".gz") else open(path, "rt", errors="replace")


def _device(ua_l: str) -> str:
    if not ua_l or ua_l == "-":
        return "other"
    if BOT_RE.search(ua_l):
        return "bot"
    if "ipad" in ua_l or ("tablet" in ua_l and "android" in ua_l):
        return "tablet"
    if "mobi" in ua_l or "iphone" in ua_l or "android" in ua_l:
        return "mobile"
    if any(k in ua_l for k in ("windows", "macintosh", "mac os", "x11", "linux", "cros")):
        return "desktop"
    return "other"


def _browser(ua: str) -> str:
    u = ua.lower()
    if not u or u == "-":
        return "—"
    # 순서 중요(Edg/Chrome 포함관계)
    if "edg" in u:
        return "Edge"
    if "opr" in u or "opera" in u:
        return "Opera"
    if "samsungbrowser" in u:
        return "Samsung"
    if "firefox" in u or "fxios" in u:
        return "Firefox"
    if "chrome" in u or "crios" in u or "chromium" in u:
        return "Chrome"
    if "safari" in u and "version/" in u:
        return "Safari"
    if BOT_RE.search(u):
        return "Bot"
    return "Other"


def _ref_host(referer: str, own_domain: str) -> str:
    if not referer or referer == "-":
        return "(direct)"
    try:
        host = urlsplit(referer).netloc.lower()
    except Exception:
        return "(other)"
    if not host:
        return "(direct)"
    host = host.split(":")[0]
    if host == own_domain or host.endswith("." + own_domain):
        return "(internal)"
    if host.startswith("www."):
        host = host[4:]
    return host


def _classify(path: str, method: str, status: int, ua: str, ip: str,
              cookie_val: str, exclude_ips: set, own_domain: str, source: str) -> tuple:
    ua_l = (ua or "").lower()
    # audience
    if cookie_val == "1" or ip in exclude_ips:
        audience = "self"
    elif not ua or ua == "-" or BOT_RE.search(ua_l) or PROBE_RE.search(path):
        audience = "bot"
    else:
        audience = "human"
    # category
    if path.startswith(("/_analytics", "/_ana")):
        category = "other"        # 관리자 대시보드 자기 트래픽
    elif ASSET_RE.search(path):
        category = "asset"
    elif method == "GET" and status in (200, 304) and not PROBE_RE.search(path):
        category = "content"
    else:
        category = "other"
    return audience, category, _device(ua_l), _browser(ua or "")


def _mk_hit(ts, ip, method, full, status, nbytes, referer, ua,
            cookie_val, exclude_ips, own_domain, source) -> Hit:
    path = urlsplit(full).path or full
    audience, category, device, browser = _classify(
        path, method, status, ua, ip, cookie_val, exclude_ips, own_domain, source)
    return Hit(ts=ts, ip=ip, method=method, path=path, full=full, status=status,
               bytes=nbytes, referer=referer, ref_host=_ref_host(referer, own_domain),
               ua=ua, device=device, browser=browser,
               audience=audience, category=category, source=source)


# --- JSON 전용 로그 --------------------------------------------------------
def parse_json_logs(paths, exclude_ips: set, own_domain: str, cookie_name: str):
    for p in paths:
        try:
            with _open(p) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line[0] != "{":
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    t = d.get("t")
                    if not t:
                        continue
                    try:
                        ts = datetime.fromisoformat(t)
                    except Exception:
                        continue
                    try:
                        status = int(d.get("s") or 0)
                    except Exception:
                        status = 0
                    try:
                        nbytes = int(d.get("b") or 0)
                    except Exception:
                        nbytes = 0
                    yield _mk_hit(ts, d.get("ip", "-"), (d.get("m") or "").upper(),
                                  d.get("u", "/"), status, nbytes,
                                  d.get("r", "-"), d.get("ua", "-"),
                                  str(d.get("cc") or ""), exclude_ips, own_domain, "json")
        except FileNotFoundError:
            continue


# --- 공용 combined 로그 백필(stack 고유 경로만) -----------------------------
_COMBINED_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<uri>\S+)[^"]*" (?P<status>\d{3}) (?P<bytes>\d+|-) '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"')


def parse_legacy_logs(paths, exclude_ips: set, own_domain: str, stack_prefixes):
    prefixes = tuple(stack_prefixes)
    for p in paths:
        try:
            with _open(p) as fh:
                for line in fh:
                    m = _COMBINED_RE.match(line)
                    if not m:
                        continue
                    uri = m.group("uri")
                    path = urlsplit(uri).path or uri
                    if not path.startswith(prefixes):   # stack 고유 경로만(오귀속 방지)
                        continue
                    try:
                        ts = datetime.strptime(m.group("time"), "%d/%b/%Y:%H:%M:%S %z")
                    except Exception:
                        continue
                    try:
                        status = int(m.group("status"))
                    except Exception:
                        status = 0
                    b = m.group("bytes")
                    nbytes = int(b) if b.isdigit() else 0
                    yield _mk_hit(ts, m.group("ip"), m.group("method").upper(), uri,
                                  status, nbytes, m.group("ref"), m.group("ua"),
                                  "", exclude_ips, own_domain, "legacy")
        except FileNotFoundError:
            continue


def collect(cfg: dict) -> list:
    """analytics.yaml 설정대로 모든 로그를 읽어 Hit 리스트 반환(중복 제거)."""
    logs = cfg.get("logs", {})
    excl = cfg.get("exclude", {})
    site = cfg.get("site", {})
    exclude_ips = set(excl.get("ips") or [])
    cookie_name = excl.get("cookie_name", "noana")
    domain = site.get("domain", "stack.utilverse.info")

    hits = []
    json_paths = sorted(glob.glob(logs.get("json_glob", "")))
    hits.extend(parse_json_logs(json_paths, exclude_ips, domain, cookie_name))
    if logs.get("legacy_backfill"):
        legacy_paths = sorted(glob.glob(logs.get("legacy_glob", "")))
        hits.extend(parse_legacy_logs(legacy_paths, exclude_ips, domain,
                                      logs.get("stack_only_prefixes") or []))
    # 회전본 겹침/중복 라인 제거(같은 방문이 여러 파일에 없도록): (ts,ip,full,status) 키
    seen, uniq = set(), []
    for h in hits:
        k = (h.ts.isoformat(), h.ip, h.full, h.status)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    uniq.sort(key=lambda h: h.ts)
    return uniq
