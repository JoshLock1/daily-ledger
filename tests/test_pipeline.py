import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import analyse, ingest, markets  # noqa: E402

NOW = datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc)
RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Bank of England holds rates at 4%</title><link>https://www.bbc.co.uk/news/biz-1?utm_source=x</link><description>&lt;p&gt;MPC voted 7-2.&lt;/p&gt;</description><pubDate>Tue, 24 Nov 2026 06:00:00 GMT</pubDate></item>
<item><title>Untitled item without link</title></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Bank of England holds interest rates at 4%</title><link href="https://www.theguardian.com/business/boe"/><summary>Rates held.</summary><updated>2026-11-24T06:30:00Z</updated></entry></feed>"""
CSV_STOOQ = b"Date,Open,High,Low,Close,Volume\n2026-11-20,1,1,1,100,0\n2026-11-21,1,1,1,102,0\n2026-11-24,1,1,1,101,0\n"
CSV_FRED = b"observation_date,CPIAUCSL\n" + b"".join(f"{2024+i//12}-{i%12+1:02d}-01,{100+i}\n".encode() for i in range(30))


class T(unittest.TestCase):
    def test_parse_rss_and_atom(self):
        a = ingest.parse_feed(RSS, {"name": "BBC", "tier": "news"})
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["summary"], "MPC voted 7-2.")
        self.assertTrue(a[0]["published"].startswith("2026-11-24T06:00"))
        b = ingest.parse_feed(ATOM, {"name": "Guardian"})
        self.assertEqual(b[0]["url"], "https://www.theguardian.com/business/boe")

    def test_canon_url_strips_tracking(self):
        self.assertEqual(ingest.canon_url("https://www.bbc.co.uk/news/biz-1?utm_source=x"), "https://bbc.co.uk/news/biz-1")

    def test_dedupe_across_runs_and_cluster(self):
        with tempfile.TemporaryDirectory() as d:
            store, health = Path(d) / "i.json", Path(d) / "h.json"
            feeds = [{"name": "BBC", "url": "bbc", "tier": "news"}, {"name": "Guardian", "url": "gu", "tier": "news"}, {"name": "Dead", "url": "dead"}]
            def fake(url):
                if url == "dead": raise OSError("boom")
                return RSS if url == "bbc" else ATOM
            n1, h = ingest.ingest(feeds, store, health, NOW, fetcher=fake)
            n2, _ = ingest.ingest(feeds, store, health, NOW, fetcher=fake)
            self.assertEqual((n1, n2), (2, 0))
            self.assertFalse(h["Dead"]["ok"])
            cl = ingest.cluster(ingest.recent(store, now=NOW))
            self.assertEqual(len(cl), 1)
            self.assertEqual(cl[0]["n_sources"], 2)

    def test_markets_parse_and_snapshot(self):
        s = markets.stooq("x", fetcher=lambda u: CSV_STOOQ)
        snap = markets.snapshot(s)
        self.assertEqual(snap["last"], 101)
        self.assertAlmostEqual(snap["chg_pct"], -0.98, places=2)
        f = markets.fred("CPIAUCSL", "yoy", fetcher=lambda u: CSV_FRED)
        self.assertAlmostEqual(f[-1][1], round((129 / 117 - 1) * 100, 2))

    def test_attach_sources_drops_fabricated_ids(self):
        items = {"a1": {"title": "T", "url": "https://x.com/1", "source": "BBC", "tier": "news", "published": "2026-11-24T06:00:00+00:00"}}
        brief = {"stories": [
            {"id": "Real Story!", "category": "bogus", "headline": "h", "evidence_ids": ["a1", "zzz"], "importance": 99},
            {"id": "made-up", "headline": "h2", "evidence_ids": ["nope"], "importance": 8}],
            "calendar": [{"date": "2026-12-01", "event": "e", "evidence_ids": ["a1"]}, {"date": "soon", "evidence_ids": ["a1"]}, {"date": "2026-12-02", "evidence_ids": []}]}
        out = analyse.attach_sources(brief, items)
        self.assertEqual(len(out["stories"]), 1)
        s = out["stories"][0]
        self.assertEqual((s["importance"], s["category"], s["id"]), (10, "global-economy", "realstory"))
        self.assertEqual(len(s["sources"]), 1)
        self.assertEqual(len(out["calendar"]), 1)

    def test_generate_retries_bad_json(self):
        calls = []
        def caller(p):
            calls.append(1)
            return "not json" if len(calls) == 1 else '{"stories": [], "headline": "Quiet day"}'
        out = analyse.generate([], {"markets": [], "macro": []}, NOW, [], [], False, caller=caller)
        self.assertEqual(len(calls), 2)
        self.assertEqual(out["stories"], [])


if __name__ == "__main__":
    unittest.main()
