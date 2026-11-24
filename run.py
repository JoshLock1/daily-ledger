"""Orchestrator.  python pipeline/run.py <mode> [--force]

modes:
  ingest   fetch feeds + markets only (run hourly)
  daily    ingest + markets + generate the briefing (run ~07:00 UK)
  refresh  alias of daily --force (manual refresh from GitHub 'Run workflow')
Weekly outlook is generated automatically inside 'daily' when the UK day is Monday.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import analyse  # noqa: E402
import ingest  # noqa: E402
import markets as mk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LONDON = ZoneInfo("Europe/London")


def load(p, default):
    return json.loads(p.read_text()) if p.exists() else default


def update_index(brief_date, brief):
    idx = load(DATA / "index.json", {"briefings": [], "concepts": [], "stories": []})
    idx["briefings"] = sorted({*idx["briefings"], brief_date}, reverse=True)
    if brief.get("concept"):
        idx["concepts"] = [c for c in idx["concepts"] if c["date"] != brief_date] + [{"date": brief_date, "name": brief["concept"]["name"]}]
    idx["stories"] = [s for s in idx["stories"] if s["date"] != brief_date] + [
        {"date": brief_date, "id": s["id"], "headline": s["headline"], "category": s["category"],
         "importance": s["importance"], "text": " ".join(str(s.get(k, "")) for k in ("what_happened", "key_takeaway"))[:900]}
        for s in brief["stories"]]
    (DATA / "index.json").write_text(json.dumps(idx))


def main(argv):
    mode = argv[1] if len(argv) > 1 else "daily"
    force = "--force" in argv or mode == "refresh"
    now_utc = datetime.now(timezone.utc)
    now_uk = now_utc.astimezone(LONDON)
    cfg = load(ROOT / "config" / "sources.json", None)
    DATA.mkdir(exist_ok=True)
    (DATA / "briefings").mkdir(exist_ok=True)

    new, health = ingest.ingest(cfg["feeds"], DATA / "items.json", DATA / "health.json", now_utc)
    print(f"ingest: {new} new items; {sum(1 for h in health.values() if h['ok'])}/{len(health)} sources ok")
    mkt = mk.refresh(cfg, DATA / "markets.json", DATA / "health.json", now_utc)
    print(f"markets: {len(mkt['markets'])} market series, {len(mkt['macro'])} macro series")
    if mode == "ingest":
        return 0

    # Scheduler fires at 06:00 and 07:00 UTC so one of them is 07:00 UK all year (GMT/BST).
    # Only generate when it is the 7 o'clock hour in London, unless forced.
    if not force and now_uk.hour != 7:
        print(f"skip: it is {now_uk:%H:%M} in London, not 07:xx")
        return 0
    date = now_uk.strftime("%Y-%m-%d")
    out = DATA / "briefings" / f"{date}.json"
    if out.exists() and not force:
        print("skip: today's briefing already exists")
        return 0

    items = ingest.recent(DATA / "items.json", hours=36, now=now_utc)
    clusters = ingest.cluster(items)
    if not clusters:
        print("no evidence available - not generating a briefing")
        return 1
    idx = load(DATA / "index.json", {"concepts": []})
    manual = load(ROOT / "config" / "calendar.json", [])
    brief = analyse.generate(clusters, mkt, now_uk, [c["name"] for c in idx.get("concepts", [])],
                             manual, now_uk.weekday() == 0)
    brief.update({"date": date, "generated": now_utc.isoformat(), "evidence_items": len(items),
                  "source_health": {k: v["ok"] for k, v in health.items()}})
    out.write_text(json.dumps(brief, indent=1))
    (DATA / "latest.json").write_text(json.dumps(brief))
    if brief.get("weekly_outlook"):
        (DATA / "weekly.json").write_text(json.dumps({"date": date, **brief["weekly_outlook"]}))
    update_index(date, brief)
    print(f"briefing written: {out.name}, {len(brief['stories'])} stories")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
