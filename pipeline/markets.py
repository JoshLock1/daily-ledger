"""Market and macro data from free, keyless endpoints.

- Yahoo Finance chart JSON (unofficial, no key; may rate-limit cloud IPs): query1.finance.yahoo.com/v8/finance/chart/<sym>
- FRED public CSV (long macro history): https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>

Each market tries Yahoo first, then falls back to the FRED series named in config.\nEach series fails independently and is reported in data/health.json.
"""
import csv
import io
import json
from urllib.parse import quote
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


BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def parse_yahoo(raw):
    res = json.loads(raw)["chart"]["result"][0]
    out = []
    for ts, close in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if close is not None:
            out.append([datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), round(float(close), 4)])
    if len(out) < 2:
        raise ValueError("no data returned")
    return out


def yahoo(sym, fetcher=None):
    fetcher = fetcher or (lambda u: fetch(u, ua=BROWSER_UA, retries=1))
    return parse_yahoo(fetcher(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}?range=2y&interval=1d"))


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


def refresh(config, out_path, health_path, now=None, yahoo_fetch=None, fred_fetch=None):
    now = now or datetime.now(timezone.utc)
    result = {"updated": now.isoformat(), "markets": [], "macro": []}
    health = json.loads(Path(health_path).read_text()) if Path(health_path).exists() else {"sources": {}}
    for m in config["markets"]:
        s, via, errs = None, None, []
        attempts = []
        if m.get("yahoo"):
            attempts.append(("Yahoo", lambda m=m: yahoo(m["yahoo"], **({"fetcher": yahoo_fetch} if yahoo_fetch else {}))))
        if m.get("fred"):
            attempts.append(("FRED", lambda m=m: fred(m["fred"], "level", **({"fetcher": fred_fetch} if fred_fetch else {}))))
        for label, fn in attempts:
            try:
                s, via = fn(), label
                break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{label}: {type(e).__name__}: {e}")
        key = f"Market {m['name']}"
        if s:
            snap = snapshot(s)
            result["markets"].append({**m, **snap, "via": via, "spark": [v for _, v in s[-60:]], "history": s[-260:]})
            health["sources"][key] = {"ok": True, "via": via, "checked": now.isoformat()}
        else:
            health["sources"][key] = {"ok": False, "error": " | ".join(errs)[:200], "checked": now.isoformat()}
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
