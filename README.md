# The Daily Ledger — personal economic intelligence publication

Static site + Python pipeline (standard library only, no installs). A GitHub Actions schedule fetches public feeds
and open data, asks Claude to write the briefing from that evidence, stores it in `data/`, and publishes the site.

## Set-up (about 10 minutes)
1. Create a GitHub repo and push this folder. (GitHub Pages on a *private* repo needs a paid GitHub plan; on a public
   repo your briefings are public. Alternative: connect the repo to Cloudflare Pages and publish `site/` + `data/`.)
2. Repo → Settings → Secrets and variables → Actions → add secret `ANTHROPIC_API_KEY` (from console.claude.com).
   Optional variable `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`).
3. Settings → Pages → Source: GitHub Actions.
4. Actions → "Economic briefing" → Run workflow (mode `refresh`). Check the log and the Archive → Source health table.

## How it runs
- 07:00 UK: two cron entries (06:00 and 07:00 UTC) fire daily; `run.py` only generates when it is the 7 o'clock hour in
  London, so it is correct in both GMT and BST. GitHub cron can be delayed by minutes, occasionally longer.
- Every 2 hours 08:15–22:15 UTC: ingest feeds and refresh market data only (no AI cost).
- Mondays: the daily run also produces the weekly outlook.
- Manual refresh: Actions → Run workflow → `refresh`.
- Runs on GitHub's servers, independent of your browser.

## Pipeline
`config/sources.json` (feeds, markets, FRED series) → `ingest.py` (parse, canonical-URL de-dupe, 14-day store,
headline clustering to count independent sources, per-source health) → `markets.py` (Stooq closes, FRED macro history)
→ `analyse.py` (Claude; evidence cited by id; titles/URLs/dates attached by code, unsupported stories dropped)
→ `data/briefings/DATE.json`, `latest.json`, `index.json` (search), `weekly.json` → `site/`.

## Honest limitations
- **Not yet run against live sources.** The build sandbox had no network. Offline tests (`python -m unittest discover -s tests`)
  cover parsing, de-duplication, clustering, market maths, source attachment and the full orchestrator with fake data.
  Feed URLs and Stooq symbols (especially `10usy.b`, `10uky.b`, `lco.f`, `dx.f`, `btcusd`) are unverified; the first run's
  source-health table will show what to fix.
- Reuters and AP have no stable public RSS; add a feed you are licensed to use. FT and Economist feeds give headlines/teasers
  only; article bodies are never fetched, no paywalls are touched.
- No free source gives economist consensus forecasts, so "forecast" fields are filled only when a fetched item states one.
- The calendar contains events announced in fetched items plus anything you add to `config/calendar.json`
  (`{"date","time_uk","region","event","why_matters","previous","forecast","actual","important"}`). Actual figures are not auto-filled.
- Market data is daily closes (can lag), not live prices.
- Historical comparisons mix supplied FRED data with the model's background knowledge; each is labelled `basis`. Check numbers.
- AI can still misread evidence. Treat as a study aid, not financial advice.
- Costs: feeds, Stooq, FRED and GitHub Actions/Pages are free within normal limits. Claude API: one call per day, typically
  well under a few cents to tens of cents depending on model and evidence size.
