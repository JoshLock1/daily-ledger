/* Static single-page reader. All dynamic text goes through esc() or textContent. */
const NAV = [
  ["", "Today’s Briefing"], ["cat/global-economy", "Global Economy"], ["markets", "Financial Markets"],
  ["cat/central-banks", "Central Banks"], ["cat/geopolitics", "Geopolitics"], ["cat/companies", "Companies & Industries"],
  ["reports", "Economic Reports"], ["calendar", "Economic Calendar"], ["bigger", "The Bigger Picture"],
  ["telling", "What the Markets Are Telling Us"], ["week", "What to Watch This Week"], ["history", "Historical Context"],
  ["concept", "Concept of the Day"], ["archive", "Searchable Archive"]];
const CAT_TITLE = { "global-economy": "Global Economy", "central-banks": "Central Banks & Monetary Policy", geopolitics: "Geopolitics & Trade", companies: "Companies & Industries", "financial-markets": "Financial Markets", reports: "Economic Reports" };
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const paras = (s) => String(s ?? "").split(/\n\n+/).filter(Boolean).map((p) => `<p>${esc(p)}</p>`).join("");
const safeUrl = (u) => (/^https?:\/\//i.test(u) ? esc(u) : "#");
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "date n/a");
const num = (n, d = 2) => (n == null ? "–" : Number(n).toLocaleString("en-GB", { maximumFractionDigits: d }));
const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
const pctHtml = (n) => (n == null ? "–" : `<span class="${cls(n)}">${n > 0 ? "+" : ""}${n.toFixed(2)}%</span>`);
const cache = {};
async function get(path, fallback = null) {
  if (path in cache) return cache[path];
  try { const r = await fetch(path, { cache: "no-cache" }); if (!r.ok) throw 0; return (cache[path] = await r.json()); }
  catch { return (cache[path] = fallback); }
}
let charts = [];
function chart(canvas, labels, datasets, opts = {}) {
  if (!window.Chart) { canvas.replaceWith(Object.assign(document.createElement("p"), { className: "muted", textContent: "Chart library unavailable offline." })); return; }
  const css = getComputedStyle(document.documentElement);
  const col = [css.getPropertyValue("--accent"), css.getPropertyValue("--down"), css.getPropertyValue("--up"), css.getPropertyValue("--muted")];
  charts.push(new Chart(canvas, { type: "line", data: { labels, datasets: datasets.map((d, i) => ({ borderColor: col[i % 4].trim(), backgroundColor: "transparent", borderWidth: 1.6, pointRadius: 0, tension: 0.15, ...d })) },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { display: datasets.length > 1 }, title: { display: !!opts.title, text: opts.title } }, scales: { x: { ticks: { maxTicksLimit: 6, color: css.getPropertyValue("--muted").trim() } }, y: { ticks: { color: css.getPropertyValue("--muted").trim() } } } } }));
}
function mountChart(host, labels, datasets, opts) { const box = document.createElement("div"); box.className = "chartbox"; const c = document.createElement("canvas"); box.append(c); host.append(box); chart(c, labels, datasets, opts); }

function sources(list) {
  if (!list?.length) return "";
  return `<h3>Sources</h3><ul class="src">${list.map((s) => `<li><a href="${safeUrl(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a> — ${esc(s.source)}${s.tier === "primary" ? " (primary)" : ""}, ${fmtDate(s.published)}</li>`).join("")}</ul>`;
}
function storyCard(s, date) {
  const hi = s.importance >= 7;
  return `<a class="card story-link ${hi ? "imp" : ""}" href="#/story/${esc(date)}/${esc(s.id)}"><span class="chip">${esc(CAT_TITLE[s.category] || s.category)}</span><span class="chip">${esc(s.label)}</span><span class="score ${hi ? "hi" : ""}">${s.importance}/10</span><h2>${esc(s.headline)}</h2><p class="muted">${esc(s.key_takeaway)}</p></a>`;
}
function banner(b) {
  if (!b) return `<div class="warn">No briefing has been generated yet. Run the pipeline (see README) or trigger the “Daily briefing” workflow.</div>`;
  const stale = (Date.now() - new Date(b.generated)) > 36 * 3600e3;
  return stale ? `<div class="warn">This briefing is from ${esc(fmtDate(b.generated))}; the scheduled job may have failed. Check Source health in the Archive.</div>` : "";
}

const views = {
  async "" () {
    const b = await get("data/latest.json");
    if (!b) return banner(null);
    const w = b.stories.length ? b.stories.map((s) => storyCard(s, b.date)).join("") : `<p class="card">No significant developments today. Nothing has been manufactured to fill space.</p>`;
    return `${banner(b)}<p class="sans muted">${esc(new Date(b.date).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }))} · ${b.stories.length} stories · ${b.evidence_items} items reviewed</p><h1>${esc(b.headline)}</h1>${w}<p><a href="#/telling">What the markets are telling us →</a> · <a href="#/bigger">The bigger picture →</a></p>`;
  },
  async story(date, id) {
    const b = await get(`data/briefings/${date}.json`);
    const s = b?.stories.find((x) => x.id === id);
    if (!s) return `<p>Story not found.</p>`;
    const sec = (t, v) => (v ? `<h3>${t}</h3>${paras(v)}` : "");
    const gl = s.glossary?.length ? `<h3>Terms explained</h3><ul>${s.glossary.map((g) => `<li><b>${esc(g.term)}</b>: ${esc(g.meaning)}</li>`).join("")}</ul>` : "";
    const links = (s.connections || []).map((c) => b.stories.find((x) => x.id === c)).filter(Boolean).map((x) => `<a href="#/story/${esc(date)}/${esc(x.id)}">${esc(x.headline)}</a>`).join(" · ");
    return `<p class="sans"><a href="#/">← Briefing</a></p><span class="chip">${esc(CAT_TITLE[s.category])}</span><span class="chip">${esc(s.label)}</span><span class="score ${s.importance >= 7 ? "hi" : ""}">${s.importance}/10</span><h1>${esc(s.headline)}</h1><p class="sans muted">${esc(fmtDate(date))}</p>
      ${sec("What happened", s.what_happened)}${sec("Why it happened", s.why_happened)}${sec("Why it matters", s.why_matters)}${sec("What could happen next", s.what_next)}${sec("Who is affected", s.who_affected)}${s.vs_expectations ? sec("Against expectations", s.vs_expectations) : ""}
      <div class="card"><h3>Key takeaway</h3><p>${esc(s.key_takeaway)}</p></div>
      <h3>Importance: ${s.importance}/10</h3><p>${esc(s.importance_reason)}</p>${gl}${links ? `<h3>Connected stories</h3><p>${links}</p>` : ""}${sources(s.sources)}`;
  },
  async cat(id) {
    const b = await get("data/latest.json");
    const list = (b?.stories || []).filter((s) => s.category === id);
    return `<h1>${esc(CAT_TITLE[id])}</h1>${list.length ? list.map((s) => storyCard(s, b.date)).join("") : `<p class="muted">Nothing significant in this category today.</p>`}`;
  },
  async reports() {
    const b = await get("data/latest.json");
    const r = b?.reports || [];
    const f = (t, v) => (v ? `<h3>${t}</h3>${paras(v)}` : "");
    return `<h1>Economic Reports & Deep Dives</h1>${r.length ? r.map((x) => `<div class="card"><h2>${esc(x.title)}</h2>${f("What it examines", x.examines)}${f("Produced by", x.producer)}${f("Why the source is credible", x.credibility)}${f("Key findings", x.key_findings)}${f("What the statistics tell us", x.statistics_mean)}${f("Wider implications", x.implications)}${f("Limitations", x.limitations)}${f("What to monitor", x.monitor)}${sources(x.sources)}</div>`).join("") : `<p class="muted">No major reports in today’s evidence.</p>`}`;
  },
  async calendar() {
    const b = await get("data/latest.json");
    const manual = await get("config-calendar.json", []);
    const today = new Date().toISOString().slice(0, 10);
    const rows = [...(b?.calendar || []).map((c) => ({ ...c, from: "news" })), ...manual].filter((c) => c.date >= today).sort((a, c) => (a.date + (a.time_uk || "")).localeCompare(c.date + (c.time_uk || "")));
    return `<h1>Economic Calendar</h1><p class="muted sans">Times are UK time. Only events found in public announcements are listed; forecasts appear only where a source gave one.</p>${rows.length ? `<div class="card"><table><tr><th>Date</th><th>Region</th><th>Event</th><th>Prev</th><th>Fcst</th><th>Actual</th></tr>${rows.map((c) => `<tr class="${c.important ? "imp" : ""}"><td>${esc(c.date)}<br>${esc(c.time_uk || "")}</td><td>${esc(c.region)}</td><td><b>${esc(c.event)}</b><br><span class="muted">${esc(c.why_matters || "")}</span>${c.sources?.length ? `<br><a href="${safeUrl(c.sources[0].url)}" target="_blank" rel="noopener noreferrer">source</a>` : ""}</td><td>${esc(c.previous ?? "–")}</td><td>${esc(c.forecast ?? "–")}</td><td>${esc(c.actual ?? "–")}</td></tr>`).join("")}</table></div>` : `<p class="muted">No upcoming events found yet.</p>`}`;
  },
  async bigger() {
    const b = await get("data/latest.json");
    const items = b?.bigger_picture || [];
    return `<h1>The Bigger Picture</h1>${items.map((x) => `<div class="card"><h2>${esc(x.title)}</h2>${paras(x.mechanism)}${x.caveats ? `<p class="muted"><i>${esc(x.caveats)}</i></p>` : ""}<p class="sans">${(x.story_ids || []).map((i) => { const s = b.stories.find((q) => q.id === i); return s ? `<a href="#/story/${esc(b.date)}/${esc(i)}">${esc(s.headline)}</a>` : ""; }).filter(Boolean).join(" · ")}</p></div>`).join("") || `<p class="muted">No cross-story connections today.</p>`}`;
  },
  async telling() {
    const b = await get("data/latest.json");
    const m = await get("data/markets.json");
    const t = b?.markets_telling_us || [];
    return `<h1>What the Markets Are Telling Us</h1><p class="muted sans">Explanations are interpretations unless marked confirmed. Market figures are daily closes.</p>${t.map((x) => `<div class="card"><h2>${esc(x.market)}</h2>${paras(x.what_happened)}<h3>Significance</h3>${paras(x.significance)}<h3>Possible drivers</h3><ul>${(x.possible_drivers || []).map((d) => `<li>${esc(d.driver)} <span class="chip">${esc(d.status)}</span></li>`).join("")}</ul><h3>What it suggests</h3>${paras(x.what_it_suggests)}<h3>Wider economy</h3>${paras(x.wider_economy)}<h3>Watch next</h3>${paras(x.watch_next)}</div>`).join("") || `<p class="muted">No significant market moves flagged.</p>`}${b?.market_relationships ? `<h2>How the markets relate</h2>${paras(b.market_relationships)}` : ""}${m ? `<p class="muted sans">Market data updated ${esc(fmtDate(m.updated))}. <a href="#/markets">See all markets →</a></p>` : ""}`;
  },
  async week() {
    const w = await get("data/weekly.json");
    if (!w) return `<h1>What to Watch This Week</h1><p class="muted">The weekly outlook is generated on Mondays.</p>`;
    return `<h1>What to Watch This Week</h1><p class="sans muted">Week of ${esc(fmtDate(w.date))}</p>${paras(w.intro)}${w.events.map((e, i) => `<div class="card"><span class="score">#${e.rank || i + 1}</span><h2>${esc(e.event)}</h2><p class="sans muted">${esc(e.date)} ${esc(e.time_uk || "")} UK</p><h3>Why it matters</h3>${paras(e.why_matters)}<h3>What economists expect</h3>${paras(e.expectations || "No published consensus in the sources reviewed.")}<h3>What outcomes could mean</h3><ul><li><b>Stronger:</b> ${esc(e.outcomes?.stronger)}</li><li><b>In line:</b> ${esc(e.outcomes?.in_line)}</li><li><b>Weaker:</b> ${esc(e.outcomes?.weaker)}</li></ul><h3>What could be affected</h3>${paras(e.affected)}<h3>Pay attention to</h3>${paras(e.watch)}${sources(e.sources)}</div>`).join("")}`;
  },
  async history() {
    const b = await get("data/latest.json");
    const m = await get("data/markets.json");
    const html = `<h1>Historical Context</h1><div id="macro" class="grid"></div>${(b?.historical || []).map((h, i) => { const f = (t, v) => (v ? `<h3>${t}</h3>${paras(v)}` : ""); return `<div class="card"><h2>${esc(h.title)}</h2><span class="chip">${esc(h.basis)}</span>${f("What happened then", h.what_happened_then)}${f("Conditions at the time", h.conditions_then)}${f("Similarities", h.similarities)}${f("Differences", h.differences)}${f("What we can learn", h.lessons)}${f("Why this is not a prediction", h.not_a_prediction)}<div id="hc${i}"></div></div>`; }).join("")}`;
    queueMicrotask(() => {
      const host = $("#macro");
      (m?.macro || []).forEach((s) => { const d = document.createElement("div"); d.className = "card"; d.innerHTML = `<b class="sans">${esc(s.name)}</b><div class="muted sans">Latest ${esc(num(s.last))} (${esc(s.date)}). Source: FRED</div>`; host.append(d); mountChart(d, s.history.map((p) => p[0]), [{ label: s.name, data: s.history.map((p) => p[1]) }]); });
      (b?.historical || []).forEach((h, i) => (h.macro_series || []).forEach((id) => { const s = m?.macro.find((x) => x.id === id); if (s) mountChart($("#hc" + i), s.history.map((p) => p[0]), [{ label: s.name, data: s.history.map((p) => p[1]) }], { title: s.name }); }));
    });
    return html;
  },
  async concept() {
    const b = await get("data/latest.json");
    const c = b?.concept;
    if (!c) return `<h1>Concept of the Day</h1><p class="muted">No concept yet.</p>`;
    const f = (t, v) => `<h3>${t}</h3>${paras(v)}`;
    return `<h1>Concept of the Day: ${esc(c.name)}</h1><span class="chip">${esc(c.level)}</span>${f("What it means", c.meaning)}${f("How it works", c.how_it_works)}${f("Why it matters", c.why_matters)}${f("A real-world example", c.example)}${f("How it relates to today", c.relates_to_today)}`;
  },
  async archive() {
    const idx = await get("data/index.json", { briefings: [], stories: [], concepts: [] });
    const h = await get("data/health.json");
    queueMicrotask(() => {
      const input = $("#q"), out = $("#res");
      const draw = () => {
        const q = input.value.toLowerCase().trim();
        const hits = idx.stories.filter((s) => !q || (s.headline + " " + s.text + " " + s.category).toLowerCase().includes(q)).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 80);
        out.innerHTML = hits.map((s) => `<div class="card"><a href="#/story/${esc(s.date)}/${esc(s.id)}"><b>${esc(s.headline)}</b></a><div class="muted sans">${esc(s.date)} · ${esc(CAT_TITLE[s.category] || s.category)} · ${s.importance}/10</div></div>`).join("") || `<p class="muted">No matches.</p>`;
      };
      input.addEventListener("input", draw); draw();
    });
    const srcs = Object.entries(h?.sources || {});
    return `<h1>Archive</h1><input id="q" type="search" placeholder="Search all past stories…"><div id="res"></div><h2>Source health</h2><p class="muted sans">${h ? "Checked " + esc(fmtDate(h.updated)) : "No health data yet."}</p><div class="card"><table>${srcs.map(([k, v]) => `<tr><td>${v.ok ? "✓" : "✗"} ${esc(k)}</td><td class="muted">${v.ok ? "ok" : esc(v.error)}</td></tr>`).join("")}</table></div>`;
  },
  async markets() {
    const m = await get("data/markets.json");
    const b = await get("data/latest.json");
    if (!m) return `<h1>Financial Markets</h1><p class="muted">No market data yet.</p>`;
    const groups = [...new Set(m.markets.map((x) => x.group))];
    queueMicrotask(() => {
      const host = $("#mc");
      m.markets.filter((x) => ["S&P 500", "Gold (USD/oz)", "US 10-year yield (%)", "Brent crude"].includes(x.name)).forEach((x) => { const d = document.createElement("div"); d.className = "card"; d.innerHTML = `<b class="sans">${esc(x.name)}</b> <span class="muted sans">1-year close</span>`; host.append(d); mountChart(d, x.history.map((p) => p[0]), [{ label: x.name, data: x.history.map((p) => p[1]) }]); });
    });
    const stories = (b?.stories || []).filter((s) => s.category === "financial-markets");
    return `<h1>Financial Markets</h1><p class="muted sans">Daily closes from Stooq (may lag live prices). Updated ${esc(fmtDate(m.updated))}.</p>${groups.map((g) => `<div class="card"><h3>${esc(g)}</h3><table><tr><th>Market</th><th class="n">Last</th><th class="n">1d</th><th class="n">5d</th><th class="n">1m</th><th class="n">Close date</th></tr>${m.markets.filter((x) => x.group === g).map((x) => `<tr><td>${esc(x.name)}</td><td class="n">${num(x.last)}</td><td class="n">${pctHtml(x.chg_pct)}</td><td class="n">${pctHtml(x.chg_5d_pct)}</td><td class="n">${pctHtml(x.chg_1m_pct)}</td><td class="n">${esc(x.date)}</td></tr>`).join("")}</table></div>`).join("")}<div id="mc" class="grid"></div>${stories.length ? `<h2>Market stories</h2>${stories.map((s) => storyCard(s, b.date)).join("")}` : ""}`;
  },
};

async function route() {
  charts.forEach((c) => c.destroy()); charts = [];
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const key = parts[0] in views ? parts[0] : "";
  const app = $("#app");
  try { app.innerHTML = await views[key](...parts.slice(1)); } catch (e) { app.innerHTML = `<div class="warn">Could not render this page: ${esc(e.message)}</div>`; }
  const cur = location.hash.replace(/^#\/?/, "");
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#/" + cur || (cur.startsWith("story") && a.getAttribute("href") === "#/")));
  $("#nav").classList.remove("open"); window.scrollTo(0, 0);
}
$("#nav").innerHTML = NAV.map(([h, t]) => `<a href="#/${h}">${esc(t)}</a>`).join("");
$("#menu").onclick = () => $("#nav").classList.toggle("open");
$("#theme").onclick = () => { const r = document.documentElement; const dark = (r.dataset.theme || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light")) === "dark"; r.dataset.theme = dark ? "light" : "dark"; try { localStorage.setItem("theme", r.dataset.theme); } catch {} route(); };
window.addEventListener("hashchange", route);
get("data/latest.json").then((b) => { $("#stamp").textContent = b ? "Edition: " + fmtDate(b.date) : ""; });
route();
