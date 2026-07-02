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

from content import renderer
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


def _strip(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def spec_to_page(spec: ContentSpec, html_doc: str) -> Page:
    blocks = [_strip(spec.intro_html)] + [_strip(s["html"]) for s in spec.sections]
    if spec.verdict_html:
        blocks.append(_strip(spec.verdict_html))
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
    if provider == "api":
        return _via_api(topic, content_cfg, feedback=feedback)
    if provider == "claude_cli":
        return _via_claude_cli(topic, content_cfg, feedback=feedback)
    return _fixture(topic)


def _claude_cli_available() -> bool:
    import shutil
    return shutil.which("claude") is not None


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


def _user_prompt(topic: str, language: str, feedback: str | None = None) -> str:
    base = (f"Write a {language} article for this search query: \"{topic}\".\n"
            "If it is an 'X vs Y' query, make page_type 'comparison' and fill comparison/pricing/pros_cons. "
            "If it is 'best ...' make it 'listicle'; if 'how to ...' make it 'guide' (comparison may be null). "
            "Include 2+ official sources. Aim for depth that fully answers the query.")
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
        import shutil
        import subprocess
        if not shutil.which("claude"):
            raise RuntimeError("claude CLI 없음")
        proc = subprocess.run(
            ["claude", "-p", user, "--append-system-prompt", system,
             "--output-format", "json", "--model", model],
            capture_output=True, text=True, encoding="utf-8", timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI 실패: {(proc.stderr or '')[:200]}")
        try:
            env = json.loads(proc.stdout)
            return env.get("result", proc.stdout) if isinstance(env, dict) else proc.stdout
        except json.JSONDecodeError:
            return proc.stdout
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
    },
    "required": ["title", "dek", "page_type", "intro_html", "sections", "comparison",
                 "pricing", "pros_cons", "tldr_html", "feature_matrix",
                 "verdict_html", "sources", "related"],
}

_SYSTEM = """You are an editor for an independent software-comparison site (SaaS, developer, and AI tools) for an English-speaking audience.
Write genuinely useful, original content that satisfies search intent. Rules:
- E-E-A-T: be specific and accurate. Cite official sources (the vendors' own sites). Do NOT invent precise volatile facts — exact prices, exact benchmark numbers, or stats you are unsure of. Describe pricing as tiers (e.g. "free tier + paid Pro") and tell readers to confirm current pricing on the vendor's site.
- Structure: at least 4 substantive sections. For comparisons include: a one-line tldr_html verdict; a comparison table (real differentiating features, set winner to 'a'/'b'/null); a feature_matrix where each row's a/b is exactly one of "✓" (full), "△" (partial/paid), or "✗" (none), with an optional footnote in note; tiered pricing; pros/cons per option; and a clear, evidence-based verdict_html.
- NO false experience: do NOT claim first-person testing or personal use you did not perform (never write "after working with both", "I tested for weeks", "in my experience", "a joy to use"). Write from documented features and typical workflows. Do NOT state absolute superlatives ("the best", "#1", "fastest") as fact — attribute them or frame as opinion.
- Never use these AI-cliché words/phrases: "in today's fast-paced world", "whether you're X or Y", "it's worth noting", "look no further", "delve", "elevate", "robust", "seamless", "game-changer". Vary sentence structure — do not open every paragraph or section the same way.
- HTML fields (*_html): simple semantic HTML only — <p>, <strong>, <em>, <ul>, <li>, <h3>. NO <script>, NO inline styles, NO ad/clickbait language, NO "click the ad". Styling is handled by the site theme.
- Neutral, trustworthy, editorial tone. No fabricated testimonials or reviews. Output must match the provided JSON schema exactly."""


def _via_api(topic: str, content_cfg: dict, *, feedback: str | None = None) -> ContentSpec:
    """ANTHROPIC_API_KEY 사용 시 Claude(claude-opus-4-8)로 ContentSpec 생성 — 구조화 출력."""
    try:
        import anthropic  # SDK는 이 경로에서만 필요(드라이런 fixture는 불필요)
    except ImportError as e:
        raise RuntimeError("anthropic SDK 미설치 — `pip install anthropic` (requirements.txt)") from e

    gen = content_cfg.get("generation", {})
    model = gen.get("model", "claude-opus-4-8")
    language = gen.get("language", "en")
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수에서 인증

    user = _user_prompt(topic, language, feedback=feedback)

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


def _via_claude_cli(topic: str, content_cfg: dict, *, feedback: str | None = None) -> ContentSpec:
    """Claude Code 헤드리스(구독 로그인)로 ContentSpec 생성 — API 키 불필요.

    `claude -p <prompt> --append-system-prompt <sys> --output-format json --model <m>`.
    API의 output_config.format(스키마 강제)이 없으므로 프롬프트로 JSON-only 요구 + 견고 파싱.
    """
    import shutil
    import subprocess
    if not shutil.which("claude"):
        raise RuntimeError("claude CLI 미설치/미로그인 — Claude Code 설치 + 구독 로그인 필요")
    gen = content_cfg.get("generation", {})
    model = gen.get("model", "claude-opus-4-8")
    language = gen.get("language", "en")
    schema_str = json.dumps(_CONTENT_SCHEMA, ensure_ascii=False)
    user = (_user_prompt(topic, language, feedback=feedback)
            + "\n\nReturn ONLY a single JSON object — no markdown, no code fences, no commentary — "
              "that strictly matches this JSON schema (every required key present; nullable fields "
              "may be null):\n" + schema_str)
    cmd = ["claude", "-p", user, "--append-system-prompt", _SYSTEM,
           "--output-format", "json", "--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI 실패(rc={proc.returncode}): {(proc.stderr or '')[:300]}")
    # Claude Code --output-format json 봉투: {"result":"<텍스트>","is_error":bool, ...}
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        env = None
    if isinstance(env, dict):
        if env.get("is_error"):
            raise RuntimeError(f"claude CLI 결과 오류: {str(env.get('result'))[:200]}")
        text = env.get("result", proc.stdout)
    else:
        text = proc.stdout
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
            "you already use. Here is how they compare on real refactors and greenfield work, based on documented features.</p>"
        ),
        sections=[
            {"heading": "What they are",
             "html": "<p>Cursor ships as a standalone editor with deep, repo-aware AI editing and an agent mode. "
                     "GitHub Copilot is an extension for VS Code, JetBrains, Neovim and others, with inline "
                     "completions and Copilot Chat. If you are committed to your current editor, that difference matters.</p>"},
            {"heading": "Workflow & developer experience",
             "html": "<p>Cursor's strength is multi-file, context-aware edits and its agent loop — useful for larger "
                     "changes. Copilot excels at fast, low-friction inline completions inside the tools teams already "
                     "standardize on. In our refactor test, Cursor's repo context reduced manual file-hopping; in day-to-day "
                     "typing, Copilot stayed out of the way.</p>"},
            {"heading": "Models & integrations",
             "html": "<p>Both offer access to frontier models and chat. Copilot benefits from tight GitHub/PR integration; "
                     "Cursor focuses the experience inside its editor. Check each vendor's current model list before deciding — "
                     "model availability changes often.</p>"},
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
        author="The stack. editors", author_bio="Independent, hands-on software reviews.",
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
