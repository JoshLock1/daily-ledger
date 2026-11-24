"""Fetch RSS/Atom feeds, normalise, de-duplicate, cluster and store items.

Standard library only. Never fetches article bodies (no paywall bypassing):
only the title/summary a publisher puts in its own public feed is used.
"""
import hashlib
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

UA = "PersonalEconIntel/1.0 (personal research; contact: set-your-email)"
STOP = set("the a an of to in on for and or as at by with from is are be its it this that over after amid new says say".split())
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ocid", "cmpid", "guccounter", "taid"}
KEEP_DAYS = 14


def _strip(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def canon_url(url):
    p = urlparse((url or "").strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING]
    return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", urlencode(q), ""))


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9£$%]+", title.lower()) if w not in STOP and len(w) > 2}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed(xml_bytes, source):
    """Parse RSS 2.0 or Atom into a list of dicts."""
    root = ET.fromstring(xml_bytes)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in el:
            name = _local(c.tag)
            if name == "link":
                f.setdefault("link", c.get("href") or (c.text or "").strip())
            elif name in ("title", "description", "summary", "pubDate", "published", "updated", "date"):
                f.setdefault(name, c.text or "")
        title = _strip(f.get("title"))
        link = f.get("link", "")
        if not title or not link:
            continue
        pub = parse_date(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date"))
        out.append({
            "title": title,
            "summary": _strip(f.get("description") or f.get("summary"))[:600],
            "url": link,
            "source": source["name"],
            "tier": source.get("tier", "news"),
            "published": pub.isoformat() if pub else None,
        })
    return out


def fetch(url, timeout=20, retries=2, ua=UA):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/rss+xml, application/atom+xml, text/xml, */*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - we record and move on
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def ingest(sources, store_path, health_path, now=None, fetcher=fetch):
    now = now or datetime.now(timezone.utc)
    store = json.loads(Path(store_path).read_text()) if Path(store_path).exists() else {"items": []}
    items = store["items"]
    seen_urls = {i["canon"] for i in items}
    health = {}
    new = 0
    for src in sources:
        try:
            parsed = parse_feed(fetcher(src["url"]), src)
            health[src["name"]] = {"ok": True, "items": len(parsed), "checked": now.isoformat()}
        except Exception as e:  # noqa: BLE001
            health[src["name"]] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "checked": now.isoformat()}
            continue
        for it in parsed:
            c = canon_url(it["url"])
            if c in seen_urls:
                continue
            seen_urls.add(c)
            it["canon"] = c
            it["id"] = hashlib.sha1(c.encode()).hexdigest()[:12]
            it["first_seen"] = now.isoformat()
            items.append(it)
            new += 1
    cutoff = now - timedelta(days=KEEP_DAYS)
    items[:] = [i for i in items if (parse_date(i["published"]) or parse_date(i["first_seen"])) >= cutoff]
    store["items"] = items
    store["updated"] = now.isoformat()
    Path(store_path).write_text(json.dumps(store, indent=1))
    Path(health_path).write_text(json.dumps({"updated": now.isoformat(), "sources": health}, indent=1))
    return new, health


def cluster(items, threshold=0.5):
    """Group near-duplicate headlines. Returns clusters sorted by corroboration.

    A cluster with several *distinct sources* is cross-referenced coverage of one event.
    """
    clusters = []
    for it in sorted(items, key=lambda i: i.get("published") or ""):
        t = tokens(it["title"])
        for c in clusters:
            if jaccard(t, c["tokens"]) >= threshold:
                c["items"].append(it)
                c["tokens"] |= t
                break
        else:
            clusters.append({"tokens": set(t), "items": [it]})
    tier_rank = {"primary": 0, "news": 1, "analysis": 2}
    out = []
    for c in clusters:
        its = sorted(c["items"], key=lambda i: (tier_rank.get(i["tier"], 3), i.get("published") or ""))
        srcs = sorted({i["source"] for i in its})
        out.append({"lead": its[0]["title"], "sources": srcs, "n_sources": len(srcs),
                    "has_primary": any(i["tier"] == "primary" for i in its), "items": its})
    out.sort(key=lambda c: (-int(c["has_primary"]), -c["n_sources"]))
    return out


def recent(store_path, hours=36, now=None):
    now = now or datetime.now(timezone.utc)
    store = json.loads(Path(store_path).read_text()) if Path(store_path).exists() else {"items": []}
    cutoff = now - timedelta(hours=hours)
    return [i for i in store["items"] if (parse_date(i["published"]) or parse_date(i["first_seen"])) >= cutoff]
