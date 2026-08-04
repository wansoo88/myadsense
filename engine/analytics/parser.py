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
import ipaddress
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
    # 구글/서드파티 점검·미리보기 도구(브라우저형 UA 라 놓치기 쉬움) — GSC 실측=Google-InspectionTool
    r"inspectiontool|apis-google|feedfetcher|google-read-aloud|google favicon|"
    r"lighthouse|chrome-lighthouse|gtmetrix|pagespeed|"
    # 소유권 확인·AI 페처 — 위 토큰에 'bot' 이 없어 그대로 '사람'으로 세어지던 것들.
    # 실측(2026-08-04): Google-Site-Verification/1.0 8건이 사람으로 집계됐다(속성 확인 직후 유입).
    r"site-verification|googleother|google-extended|google-safety|google-cloudvertexbot|"
    r"claude-user|claude-searchbot|anthropic|chatgpt-user|oai-searchbot|perplexity|"
    r"cohere-ai|meta-externalagent|bytedance|timpibot|omgili|webzio|"
    r"monitor|uptime|pingdom|statuscake|site24x7|newrelic|datadog|"
    r"semrush|ahrefs|mj12|dotbot|petalbot|dataforseo|serpstat|blexbot|"
    r"censys|zgrab|masscan|nmap|nuclei|expanse|paloalto|shodan|internetmeasurement|"
    # 취약점 스캐너 — 스스로 이름을 밝히는데 'bot' 토큰이 없어 새던 것들(실측: WP-Safe-Scanner/1.0)
    r"scanner|nikto|sqlmap|dirbuster|gobuster|wpscan|acunetix|netsparker|zaproxy|nessus",
    re.I)
# 브라우저가 아닌 쓰레기 UA — 실측: `pc` 같은 두 글자 UA. 사람의 브라우저는 반드시 제품/버전을 붙인다.
_JUNK_UA_MAXLEN = 20
# 스캐너/취약점 탐침 경로(사람 콘텐츠 아님) — 백필/분류 방어선
PROBE_RE = re.compile(
    r"(?:^|/)(?:\.env|\.git|wp-|xmlrpc|phpmyadmin|\.php|\.aws|\.ssh|"
    r"vendor/|config\.|backup|shell|eval-stdin|actuator|/\.well-known/security)",
    re.I)

# 데이터센터/클라우드 IP 대역 — 콘텐츠 사이트에서 이 대역의 접속은 (브라우저형 UA 라도)
# 사실상 스크래퍼·봇·점검도구. 실제 독자는 주거/모바일 ISP 라 여기 거의 안 걸린다.
# 설정(analytics.yaml exclude.datacenter_cidrs)으로 추가 대역을 덧붙일 수 있다.
_DC_CIDRS = [
    # AWS
    "3.0.0.0/8", "13.32.0.0/12", "15.177.0.0/16", "18.32.0.0/11", "18.64.0.0/10",
    "35.71.0.0/16", "44.192.0.0/10", "52.0.0.0/8", "54.64.0.0/11", "54.144.0.0/12",
    "54.160.0.0/11", "54.224.0.0/11", "99.77.0.0/16", "100.24.0.0/13",
    # GCP
    "34.0.0.0/8", "35.184.0.0/13", "35.192.0.0/14", "35.196.0.0/15", "35.198.0.0/16",
    "35.200.0.0/13", "104.154.0.0/15", "104.196.0.0/14", "130.211.0.0/16", "146.148.0.0/17",
    # Azure
    "13.64.0.0/11", "20.0.0.0/8", "40.64.0.0/10", "40.112.0.0/13", "52.224.0.0/11",
    "104.40.0.0/13", "137.116.0.0/15", "168.61.0.0/16", "168.62.0.0/15",
    # Hetzner
    "5.9.0.0/16", "46.4.0.0/16", "49.12.0.0/15", "65.21.0.0/16", "65.108.0.0/15",
    "78.46.0.0/15", "88.198.0.0/16", "88.99.0.0/16", "91.107.0.0/16", "94.130.0.0/16",
    "95.216.0.0/15", "116.202.0.0/16", "128.140.0.0/17", "135.181.0.0/16", "136.243.0.0/16",
    "138.201.0.0/16", "144.76.0.0/16", "148.251.0.0/16", "157.90.0.0/16", "159.69.0.0/16",
    "162.55.0.0/16", "167.235.0.0/16", "168.119.0.0/16", "176.9.0.0/16", "178.63.0.0/16", "195.201.0.0/16",
    # DigitalOcean
    "45.55.0.0/16", "68.183.0.0/16", "104.131.0.0/16", "104.236.0.0/16", "134.209.0.0/16",
    "137.184.0.0/16", "138.68.0.0/16", "139.59.0.0/16", "142.93.0.0/16", "143.110.0.0/16",
    "143.198.0.0/16", "146.190.0.0/16", "157.230.0.0/16", "159.65.0.0/16", "159.89.0.0/16",
    "161.35.0.0/16", "164.90.0.0/16", "164.92.0.0/16", "165.227.0.0/16", "167.71.0.0/16",
    "167.99.0.0/16", "174.138.0.0/16", "178.62.0.0/16", "188.166.0.0/16", "206.189.0.0/16", "209.38.0.0/16",
    # OVH
    "51.68.0.0/14", "51.75.0.0/16", "51.77.0.0/16", "51.79.0.0/16", "51.83.0.0/16", "51.89.0.0/16",
    "51.91.0.0/16", "54.36.0.0/14", "91.121.0.0/16", "92.222.0.0/16", "94.23.0.0/16", "137.74.0.0/16",
    "141.94.0.0/16", "145.239.0.0/16", "147.135.0.0/16", "149.202.0.0/16", "151.80.0.0/16", "158.69.0.0/16",
    "164.132.0.0/16", "167.114.0.0/16", "176.31.0.0/16", "178.32.0.0/15", "188.165.0.0/16", "192.99.0.0/16", "213.186.32.0/19",
    # Linode/Akamai
    "45.33.0.0/16", "45.56.0.0/16", "45.79.0.0/16", "50.116.0.0/16", "139.144.0.0/16", "139.162.0.0/16",
    "172.104.0.0/15", "173.255.192.0/18", "176.58.96.0/19", "178.79.128.0/18", "198.58.96.0/19", "74.207.224.0/19",
    # Oracle Cloud
    "129.146.0.0/16", "129.153.0.0/16", "132.145.0.0/16", "138.1.0.0/16", "140.238.0.0/16", "141.144.0.0/16",
    "143.47.0.0/16", "144.24.0.0/16", "146.56.0.0/16", "150.136.0.0/16", "150.230.0.0/16", "152.67.0.0/16",
    "152.70.0.0/16", "158.101.0.0/16", "158.178.0.0/16", "168.138.0.0/16", "193.122.0.0/16", "193.123.0.0/16",
    # Cloudflare
    "103.21.244.0/22", "104.16.0.0/13", "108.162.192.0/18", "131.0.72.0/22", "141.101.64.0/18",
    "162.158.0.0/15", "172.64.0.0/13", "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20", "198.41.128.0/17",
    # Scaleway/Online.net
    "51.15.0.0/16", "51.158.0.0/16", "62.210.0.0/16", "163.172.0.0/16", "195.154.0.0/16", "212.47.224.0/19",
    # Google 크롤러·인프라 — Googlebot / Site-Verification / InspectionTool 이 나오는 대역.
    # UA 토큰으로도 잡지만 UA 는 바뀌고 대역은 잘 안 바뀐다(이중 그물).
    "66.249.64.0/19", "64.233.160.0/19", "66.102.0.0/20", "72.14.192.0/18", "74.125.0.0/16",
    "108.177.0.0/17", "142.250.0.0/15", "172.217.0.0/16", "173.194.0.0/16", "192.178.0.0/15",
    "209.85.128.0/17", "216.58.192.0/19", "216.239.32.0/19",
    # Tencent Cloud
    "43.128.0.0/10", "49.51.0.0/16", "129.28.0.0/16", "150.109.0.0/16", "170.106.0.0/16",
    # Alibaba Cloud
    "8.208.0.0/12", "47.74.0.0/15", "47.76.0.0/14", "47.88.0.0/14", "47.240.0.0/14",
    # AWS — 기존 18.32.0.0/11·18.64.0.0/10 에 안 걸리던 구간(실측 18.212.x 가 사람으로 셌다)
    "18.204.0.0/14", "18.208.0.0/13", "35.168.0.0/13", "107.20.0.0/14",
    # 실측으로 드러난 누락 대역(2026-08-04) — DigitalOcean·Tencent·Azure 의 미등재 구간
    "138.197.0.0/16", "162.62.0.0/16", "4.144.0.0/12",
    # 관측된 스캐너/호스팅 대역
    "104.252.0.0/16", "204.76.203.0/24", "141.98.0.0/16",
]

# ── 버스트 재분류 임계 (2026-08-04) ────────────────────────────────────────────
# UA·대역 목록은 본질적으로 뒤쫓는 방식이다 — 새 스크래퍼는 언제나 목록보다 먼저 온다.
# 그래서 **행동**으로 한 겹 더 친다: 사람은 1분에 서로 다른 글 8편을 열지 않는다.
# 실측(2026-08-04): 8.235.48.27 이 07:03 한 분 동안 서로 다른 콘텐츠 40페이지를 순차 요청했는데
#   UA 가 평범한 `Pixel 6 Chrome/114` 라 UA·대역 어느 그물에도 안 걸렸다(그날 '사람' 108건 중 59건).
# ⚠️ 보수적으로 잡는다 — 걸리면 그 IP 의 **모든** 요청을 봇으로 돌리므로 임계를 넉넉히 둔다.
#   놓친 봇은 다음에 목록으로 잡으면 되지만, 실제 독자를 봇으로 지우면 그 방문은 어디에도 안 남는다.
#   비대칭이 명확하므로 오탐(사람을 봇으로) 쪽으로 기울지 않는다.
_BURST_WINDOW_SEC = 60
_BURST_DISTINCT_PAGES = 8


def _build_dc_index(extra_cidrs=None):
    """CIDR 목록 → 첫 옥텟 버킷 인덱스(조회를 대역수/256 수준으로)."""
    idx = {}
    for c in list(_DC_CIDRS) + list(extra_cidrs or []):
        try:
            net = ipaddress.ip_network(c, strict=False)
        except Exception:
            continue
        if net.version == 4:
            idx.setdefault(int(net.network_address) >> 24, []).append(net)
        else:
            idx.setdefault(-1, []).append(net)
    return idx


_DC_INDEX = _build_dc_index()   # collect() 에서 설정의 추가 대역 포함해 재구성

# analytics.yaml exclude.bot_ua_extra 로 덧붙이는 UA 조각. collect() 에서 채운다.
# ⚠️ 이 설정 키는 문서에만 있고 **코드가 읽지 않던 죽은 설정**이었다(2026-08-04 발견) —
#    거기에 UA 를 적어도 아무 일이 없었다. 이제 실제로 반영된다.
_BOT_EXTRA_RE = None


def _is_datacenter(ip: str) -> bool:
    if not ip or ip == "-":
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return False
    bucket = _DC_INDEX.get(int(addr) >> 24, ()) if addr.version == 4 else _DC_INDEX.get(-1, ())
    return any(addr in net for net in bucket)


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
    elif (not ua or ua == "-" or BOT_RE.search(ua_l) or PROBE_RE.search(path)
          or (_BOT_EXTRA_RE is not None and _BOT_EXTRA_RE.search(ua_l))
          or (len(ua_l) < _JUNK_UA_MAXLEN and "mozilla" not in ua_l)   # 브라우저가 아닌 쓰레기 UA
          or _is_datacenter(ip)):     # 데이터센터/클라우드 대역 = 사실상 봇·스크래퍼·점검도구
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


def _reclassify_bursts(hits: list, window_sec: int, distinct_pages: int) -> set:
    """사람으로 분류됐지만 '읽는 속도'가 아닌 IP 를 봇으로 되돌린다. 되돌린 IP 집합 반환.

    창(window_sec) 안에서 **서로 다른** 콘텐츠 경로를 distinct_pages 개 이상 요청한 IP 가 대상.
    같은 페이지 새로고침은 세지 않는다(경로 집합으로 셈) — 사람의 재방문을 봇으로 만들지 않기 위해.
    """
    if distinct_pages <= 0 or window_sec <= 0:
        return set()
    by_ip: dict = {}
    for h in hits:
        if h.audience == "human" and h.category == "content":
            by_ip.setdefault(h.ip, []).append(h)
    burst_ips = set()
    for ip, hs in by_ip.items():
        if len({h.path for h in hs}) < distinct_pages:
            continue                                   # 전체로도 모자라면 창 검사 불필요
        hs.sort(key=lambda h: h.ts)
        lo = 0
        for hi in range(len(hs)):
            while (hs[hi].ts - hs[lo].ts).total_seconds() > window_sec:
                lo += 1
            if len({x.path for x in hs[lo:hi + 1]}) >= distinct_pages:
                burst_ips.add(ip)
                break
    if burst_ips:
        for h in hits:
            if h.audience == "human" and h.ip in burst_ips:
                h.audience = "bot"
    return burst_ips


def collect(cfg: dict) -> list:
    """analytics.yaml 설정대로 모든 로그를 읽어 Hit 리스트 반환(중복 제거)."""
    logs = cfg.get("logs", {})
    excl = cfg.get("exclude", {})
    site = cfg.get("site", {})
    exclude_ips = set(excl.get("ips") or [])
    cookie_name = excl.get("cookie_name", "noana")
    domain = site.get("domain", "utilverse.info")
    global _DC_INDEX, _BOT_EXTRA_RE               # 설정의 추가 데이터센터 대역 반영
    _DC_INDEX = _build_dc_index(excl.get("datacenter_cidrs"))
    _extra = [str(x).strip().lower() for x in (excl.get("bot_ua_extra") or []) if str(x).strip()]
    _BOT_EXTRA_RE = re.compile("|".join(re.escape(x) for x in _extra), re.I) if _extra else None

    hits = []
    # json_glob 은 문자열 또는 **목록**을 받는다(ORDER 2026-08-01-47-ops 후속).
    # 도메인 이전 후 apex 는 utilverse.access.log 에 쓰고, 이전 주소(stack)로 들어오는 유입은
    # 공개 resolver 캐시가 만료될 때까지 남는다 — 둔 로그를 함께 읽어야 추세가 끊기지 않는다.
    # 겹치는 줄은 아래 (ts,ip,full,status) 중복 제거가 이미 걱러낸다.
    _globs = logs.get("json_glob") or []
    if isinstance(_globs, str):
        _globs = [_globs]
    json_paths = sorted({p for g in _globs for p in glob.glob(g)})
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
    # 목록(UA·대역)으로 못 잡은 스크래퍼를 **행동**으로 한 번 더 친다. 목록은 늘 뒤늦다.
    burst = _reclassify_bursts(uniq,
                               int(excl.get("burst_window_sec", _BURST_WINDOW_SEC)),
                               int(excl.get("burst_distinct_pages", _BURST_DISTINCT_PAGES)))
    if burst:
        print(f"analytics: 버스트 재분류 — IP {len(burst)}개를 봇으로 되돌림"
              f"(창 {excl.get('burst_window_sec', _BURST_WINDOW_SEC)}초 안에 다른 글 "
              f"{excl.get('burst_distinct_pages', _BURST_DISTINCT_PAGES)}편 이상): "
              + ", ".join(sorted(burst)[:5]) + (" …" if len(burst) > 5 else ""))
    return uniq
