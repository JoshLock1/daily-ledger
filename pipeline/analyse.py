"""AI analysis step. Turns ingested evidence into a structured briefing.

Anti-fabrication design:
 * The model only sees numbered evidence items and must cite them by id.
 * Source titles, URLs and dates are attached HERE from the stored items, never taken
   from model text, so a link can't be invented. Stories citing no valid id are dropped.
 * Facts that the evidence does not contain must be left null / labelled as background.
"""
import json
import os
import re
import urllib.request
from datetime import datetime

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
CATEGORIES = ["global-economy", "financial-markets", "central-banks", "geopolitics", "companies", "reports"]

SYSTEM = """You are the editor of a private economic intelligence publication for one reader who wants to
learn how the economy works. You write like a careful Financial Times / Economist journalist: precise,
sober, plain English, and you define every technical term the first time you use it.

HARD RULES
1. Use ONLY the evidence items supplied (and the supplied market data) for facts about today's events.
   Never invent statistics, quotes, reports, dates or events. If a figure is not in the evidence, do not give it.
2. Cite evidence by its id in every story. Prefer primary sources (tier "primary") and stories reported by
   several distinct sources. Say when only one source reports something.
3. Label claims: "confirmed" (stated by an official/primary source or multiple reliable outlets),
   "reported" (one outlet), "opinion", "forecast" or "speculation". Keep these distinct in the prose.
4. Historical comparisons may use well-established background knowledge, but mark them "background" and keep
   precise figures to ones you are highly confident of or that appear in supplied macro history. Always add the
   caveat that history is not a prediction.
5. Be selective. Do not manufacture stories. If fewer than 5 stories are genuinely important, return fewer;
   if nothing is significant, return an empty stories list. Importance: 1-3 minor, 4-6 noteworthy,
   7-8 significant with wide consequences, 9-10 major global development. Most stories should be 3-7.
6. Market explanations are interpretations unless an item states the cause. Offer several possible drivers
   and say which are confirmed.
7. Output ONLY valid JSON matching the requested schema. No markdown fences, no commentary."""

SCHEMA = """{
 "headline": "one-sentence summary of the day",
 "stories": [{
   "id": "short-kebab-slug",
   "category": "one of: global-economy|financial-markets|central-banks|geopolitics|companies|reports",
   "headline": "...",
   "evidence_ids": ["ids of supplied items"],
   "label": "confirmed|reported|opinion|forecast|speculation",
   "what_happened": "2-4 paragraphs with facts, figures, dates (only from evidence). Separate paragraphs with \\n\\n",
   "why_happened": "...", "why_matters": "...", "what_next": "...",
   "who_affected": "countries, industries, firms, consumers, markets",
   "key_takeaway": "...",
   "vs_expectations": "above/below/in line with expectations IF the evidence gives a forecast, else null",
   "importance": 1-10, "importance_reason": "...",
   "glossary": [{"term": "...", "meaning": "..."}],
   "connections": ["ids of other stories in this briefing that this one links to, with the mechanism in 'bigger_picture'"]
 }],
 "bigger_picture": [{"title": "...", "story_ids": ["..."], "mechanism": "explain the causal chain in plain English across stories: e.g. rates -> dollar -> gold -> equities -> UK", "caveats": "..."}],
 "markets_telling_us": [{"market": "name", "what_happened": "uses supplied market figures only", "significance": "...", "possible_drivers": [{"driver": "...", "status": "confirmed|possible"}], "what_it_suggests": "investor confidence/expectations", "wider_economy": "...", "watch_next": "..."}],
 "market_relationships": "short essay on how today's markets relate (e.g. gold vs yields, dollar, oil -> inflation) - interpretations flagged",
 "reports": [{"title": "...", "evidence_ids": ["..."], "examines": "...", "producer": "...", "credibility": "...", "key_findings": "...", "statistics_mean": "...", "implications": "...", "limitations": "...", "monitor": "..."}],
 "historical": [{"title": "...", "story_ids": ["..."], "macro_series": ["optional FRED ids from supplied macro data to chart, e.g. FEDFUNDS"], "what_happened_then": "...", "conditions_then": "...", "similarities": "...", "differences": "...", "lessons": "...", "not_a_prediction": "...", "basis": "background|supplied-data"}],
 "calendar": [{"date": "YYYY-MM-DD", "time_uk": "HH:MM or null", "region": "...", "event": "...", "why_matters": "...", "previous": "string or null", "forecast": "string or null", "actual": "string or null", "important": true, "evidence_ids": ["ids supporting this date; required"]}],
 "concept": {"name": "...", "level": "beginner|intermediate|advanced", "meaning": "...", "how_it_works": "...", "why_matters": "...", "example": "...", "relates_to_today": "..."},
 "weekly_outlook": null or {"intro": "...", "events": [{"event": "...", "date": "YYYY-MM-DD", "time_uk": "...", "why_matters": "...", "expectations": "only if present in evidence, with source id", "outcomes": {"stronger": "...", "in_line": "...", "weaker": "..."}, "affected": "...", "watch": "...", "evidence_ids": ["..."], "rank": 1}]}
}
Calendar entries and weekly events must be supported by evidence (an item announcing the date) - omit them otherwise.
Only include weekly_outlook when told it is Monday, and only list genuinely significant events (up to 5)."""


def compact_markets(markets):
    rows = []
    for m in markets.get("markets", []):
        rows.append({"name": m["name"], "group": m["group"], "close_date": m["date"], "last": m["last"],
                     "chg_pct_1d": m["chg_pct"], "chg_pct_5d": m["chg_5d_pct"], "chg_pct_1m": m["chg_1m_pct"],
                     "hi_52w": m["hi_52w"], "lo_52w": m["lo_52w"]})
    macro = [{"id": m["id"], "name": m["name"], "latest": m["last"], "as_of": m["date"]} for m in markets.get("macro", [])]
    return {"markets": rows, "macro_latest": macro}


def build_prompt(clusters, markets, now, prev_concepts, manual_calendar, is_monday, max_clusters=70):
    ev = []
    for c in clusters[:max_clusters]:
        for it in c["items"][:4]:
            ev.append({"id": it["id"], "source": it["source"], "tier": it["tier"], "published": it["published"],
                       "title": it["title"], "summary": it["summary"], "cluster_sources": c["n_sources"]})
    return (
        f"Today is {now.strftime('%A %d %B %Y')} (UK). Briefing time ~07:00 UK. Is Monday: {is_monday}.\n"
        f"Concepts already covered (do not repeat, and gradually raise difficulty): {json.dumps(prev_concepts[-40:])}\n"
        f"Reader-maintained calendar (already shown separately, do not duplicate): {json.dumps(manual_calendar)[:2000]}\n\n"
        f"MARKET DATA (daily closes, may lag the live market; cite the close_date):\n{json.dumps(compact_markets(markets))}\n\n"
        f"EVIDENCE ITEMS (clustered; items from the same event share cluster_sources>1):\n{json.dumps(ev)}\n\n"
        f"Return JSON matching this schema:\n{SCHEMA}"
    )


def call_claude(prompt, api_key=None, max_tokens=16000, timeout=600):
    """Asks for a tool call so the API returns already-parsed JSON (no stray-quote errors); falls back to text."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    body = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "system": SYSTEM,
        "tools": [{"name": "publish_briefing", "description": "Submit the finished briefing as structured data matching the schema in the prompt.",
                   "input_schema": {"type": "object", "additionalProperties": True}}],
        "messages": [{"role": "user", "content": prompt + "\n\nSubmit the finished briefing by calling the publish_briefing tool exactly once. Do not reply with plain text."}]}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude API error {e.code}: {e.read().decode()[:500]}")
    if data.get("stop_reason") == "max_tokens":
        raise RuntimeError("Claude's answer was cut off (max_tokens); reduce evidence or raise max_tokens")
    for blk in data["content"]:
        if blk.get("type") == "tool_use":
            out = blk["input"]
            if isinstance(out, dict) and len(out) == 1 and isinstance(next(iter(out.values())), (dict, str)):
                v = next(iter(out.values()))  # tolerate {"briefing": {...}} wrapping
                out = json.loads(v) if isinstance(v, str) else v
            return json.dumps(out)
    text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    if text.strip():
        return text  # fallback: model answered in plain text; parse_json will try to read it
    raise KeyError("no tool_use or text block in response")


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s == -1 or e == -1:
            raise
        return json.loads(text[s:e + 1])


def attach_sources(brief, items_by_id):
    """Resolve evidence ids to real titles/URLs/dates; drop anything unsupported."""
    def src(ids):
        out = []
        for i in ids or []:
            it = items_by_id.get(i)
            if it:
                out.append({"id": i, "title": it["title"], "url": it["url"], "source": it["source"],
                            "tier": it["tier"], "published": it["published"]})
        return out

    stories = []
    for s in brief.get("stories", []):
        s["sources"] = src(s.pop("evidence_ids", []))
        if not s["sources"]:
            continue
        try:
            s["importance"] = max(1, min(10, int(s.get("importance", 4))))
        except (TypeError, ValueError):
            s["importance"] = 4
        if s.get("category") not in CATEGORIES:
            s["category"] = "global-economy"
        s["id"] = re.sub(r"[^a-z0-9-]", "", str(s.get("id", "")).lower()) or f"story-{len(stories)+1}"
        stories.append(s)
    seen = set()
    for s in stories:  # unique slugs
        base, n = s["id"], 2
        while s["id"] in seen:
            s["id"] = f"{base}-{n}"; n += 1
        seen.add(s["id"])
    brief["stories"] = sorted(stories, key=lambda s: -s["importance"])
    for key in ("reports",):
        kept = []
        for r in brief.get(key, []):
            r["sources"] = src(r.pop("evidence_ids", []))
            if r["sources"]:
                kept.append(r)
        brief[key] = kept
    cal = []
    for c in brief.get("calendar", []):
        c["sources"] = src(c.pop("evidence_ids", []))
        if c["sources"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("date", ""))):
            cal.append(c)
    brief["calendar"] = cal
    wk = brief.get("weekly_outlook")
    if wk:
        evs = []
        for e in wk.get("events", []):
            e["sources"] = src(e.pop("evidence_ids", []))
            if e["sources"]:
                evs.append(e)
        wk["events"] = sorted(evs, key=lambda e: e.get("rank", 99))[:5]
        brief["weekly_outlook"] = wk if evs else None
    valid = {s["id"] for s in brief["stories"]}
    for b in brief.get("bigger_picture", []):
        b["story_ids"] = [i for i in b.get("story_ids", []) if i in valid]
    for h in brief.get("historical", []):
        h["story_ids"] = [i for i in h.get("story_ids", []) if i in valid]
    return brief


def generate(clusters, markets, now, prev_concepts, manual_calendar, is_monday, caller=call_claude):
    items_by_id = {it["id"]: it for c in clusters for it in c["items"]}
    prompt = build_prompt(clusters, markets, now, prev_concepts, manual_calendar, is_monday)
    last_err = None
    for _ in range(2):  # one retry on malformed JSON
        try:
            brief = parse_json(caller(prompt))
            break
        except (json.JSONDecodeError, KeyError) as e:
            last_err = e
    else:
        raise RuntimeError(f"model returned invalid JSON twice: {last_err}")
    brief = attach_sources(brief, items_by_id)
    brief["model"] = MODEL
    return brief
