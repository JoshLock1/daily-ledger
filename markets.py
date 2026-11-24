"""Market and macro data from free, keyless endpoints.

- Stooq daily CSV (indices, FX, commodities, yields, crypto): https://stooq.com/q/d/l/?s=<sym>&i=d
- FRED public CSV (long macro history): https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>

Both are unofficial-ish public endpoints with no SLA; each series fails independently
and is reported in data/health.json. Stooq symbols in config are unverified.
"""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from ingest import fetch


def parse_csv_series(raw, value_col):
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))
    out = []
    for r in rows:
        try:
            out.append([r["Date" if "Date" in r else "observation_date" if "observation_date" in r else "DATE"], float(r[value_col])])
        except (KeyError, ValueError, TypeError):
            continue
    return out


def stooq(sym, fetcher=fetch):
    raw = fetcher(f"https://stooq.com/q/d/l/?s={sym}&i=d")
    series = parse_csv_series(raw, "Close")
    if len(series) < 2:
        raise ValueError("no data returned")
    return series


def yoy(series, lag):
    return [[series[i][0], round((series[i][1] / series[i - lag][1] - 1) * 100, 2)] for i in range(lag, len(series))]


def fred(series_id, transform="level", fetcher=fetch):
    raw = fetcher(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    first = raw.decode("utf-8", "replace").splitlines()[0].split(",")
    col = first[1] if len(first) > 1 else series_id
    s = parse_csv_series(raw, col)
    if len(s) < 2:
        raise ValueError("no data returned")
    if transform == "yoy":
        lag = 4 if series_id == "GDPC1" else 12
        s = yoy(s, lag)
    return s


def pct(a, b):
    return round((a / b - 1) * 100, 2) if b else None


def snapshot(series):
    last, prev = series[-1], series[-2]
    def back(n):
        return series[-1 - n][1] if len(series) > n else None
    year = series[-252:]
    return {"date": last[0], "last": last[1], "prev": prev[1], "chg": round(last[1] - prev[1], 4),
            "chg_pct": pct(last[1], prev[1]), "chg_5d_pct": pct(last[1], back(5)), "chg_1m_pct": pct(last[1], back(21)),
            "hi_52w": max(v for _, v in year), "lo_52w": min(v for _, v in year)}


def refresh(config, out_path, health_path, now=None, stooq_fetch=None, fred_fetch=None):
    now = now or datetime.now(timezone.utc)
    result = {"updated": now.isoformat(), "markets": [], "macro": []}
    health = json.loads(Path(health_path).read_text()) if Path(health_path).exists() else {"sources": {}}
    for m in config["markets"]:
        try:
            s = stooq(m["stooq"], **({"fetcher": stooq_fetch} if stooq_fetch else {}))
            snap = snapshot(s)
            # 'last' close is the latest *daily* close; date is shown so staleness is visible
            result["markets"].append({**m, **snap, "spark": [v for _, v in s[-60:]], "history": s[-260:]})
            health["sources"][f"Stooq {m['name']}"] = {"ok": True, "checked": now.isoformat()}
        except Exception as e:  # noqa: BLE001
            health["sources"][f"Stooq {m['name']}"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "checked": now.isoformat()}
    for f in config["fred"]:
        try:
            s = fred(f["id"], f["transform"], **({"fetcher": fred_fetch} if fred_fetch else {}))
            result["macro"].append({**f, "last": s[-1][1], "date": s[-1][0], "history": s[-720:] if len(s) > 720 else s})
            health["sources"][f"FRED {f['id']}"] = {"ok": True, "checked": now.isoformat()}
        except Exception as e:  # noqa: BLE001
            health["sources"][f"FRED {f['id']}"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "checked": now.isoformat()}
    health["updated"] = now.isoformat()
    Path(out_path).write_text(json.dumps(result))
    Path(health_path).write_text(json.dumps(health, indent=1))
    return result
