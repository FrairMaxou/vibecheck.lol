/* VibeCheck.lol dashboard.
   All filtering/aggregation is client-side: the dataset is small (one row per
   game) and this keeps the filter bar + explorer instant (PRD F13b/F13c). */
"use strict";

const MIN_N = 5; // PRD F21: below this, a group is "not enough data yet"
const EMOJI = { 1: "😨", 2: "🤨", 3: "😐", 4: "😎", 5: "👑" };
// Chart Y-axis tick label for the 1-5 vibe scale (issue #90) — plain numbers,
// not the EMOJI/GRADES glyphs those stay reserved for tooltips, tables, and
// the rating popup. GRADES ("Who Let Them Cook?", etc.) was considered as a
// paired secondary label but skipped: several of those phrases are long
// enough to risk wrapping or crowding an axis at the 900px window minimum,
// which the numbers-only version doesn't risk.
const vibeAxisTick = (v) => v.toFixed(1);
const GRADES = {
  1: "FF at 15",
  2: "Who Let Them Cook?",
  3: "Meh",
  4: "We Are So Back",
  5: "Gigachad",
};
/* Chart mark colors — validated (dataviz six checks) against surface #1e2328:
   lightness band ok, chroma ok, CVD dE 19.7, normal dE 21.8, contrast 4.65:1.
   The brighter UI gold (#c8aa6e) is for text/chrome only, never chart marks. */
const GOLD = "#b28328";
const TEAL = "#2f9ac0";
const MUTED = "#4a5058";
const INK2 = "#a09b8c";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAYPARTS = ["Morning (6–12)", "Afternoon (12–18)", "Evening (18–24)", "Night (0–6)"];
const DURATIONS = ["< 20 min", "20–30 min", "30–40 min", "40+ min"];

Chart.defaults.color = INK2;
Chart.defaults.borderColor = "#3c434d";
Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
Chart.defaults.plugins.legend.display = false;
Chart.defaults.animation.duration = 250;

let ALL = []; // enriched games
let ALL_TAGS = []; // known tag labels (for suggestion chips)
let lastRev = null; // server data_rev as of the last successful full refresh
const charts = {}; // canvas id -> Chart instance
const state = {
  tab: "overview",
  from: null,
  to: null,
  sets: { queue: new Set(), mode: new Set(), champion: new Set(), role: new Set(), teammate: new Set(), result: new Set() },
};

/* ---------------- data ---------------- */

async function fetchJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function loadData() {
  const [games, tags] = await Promise.all([fetchJSON("/api/games"), fetchJSON("/api/tags")]);
  ALL = games.games.map(enrich);
  ALL_TAGS = tags.tags;
}

/* Escape anything that came from outside this file before it goes into an HTML
   string — champion and teammate names arrive from the game payload, tags and
   notes from the user, error text from the backend. This page's origin can
   reach every localhost endpoint (including quit and install-update), so an
   injected <script> here would be running with the app's own hands. The CSP in
   vibecheck/security.py is the net under this; escaping is the actual fix.

   Safe for both element text and quoted attribute values, which is why one
   helper covers every site. Numbers we computed ourselves don't need it. */
function escapeAttr(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* Champion portrait, or nothing at all. The icon is decoration served from a
   local cache that may legitimately be empty (offline, or not warmed yet), so
   onerror removes the element rather than leaving a broken-image box. alt is
   empty on purpose: the champion name is always right next to it, and a second
   copy is just noise for a screen reader. */
function champIcon(name, classic) {
  if (!name) return "";
  const q = classic ? "?classic=1" : "";
  const cls = classic ? "champ-icon is-classic" : "champ-icon";
  const tip = classic ? ' title="League Classic"' : "";
  // Wrapped in a fixed-size slot: a missing icon removes the img, and without
  // the slot holding that space the whole row shifts left, so rows with a
  // missing icon no longer line up with the rest of the column.
  return `<span class="champ-slot">` +
         `<img class="${cls}" src="/api/champ-icon/${encodeURIComponent(name)}${q}"` +
         ` alt="" loading="lazy"${tip} data-on-error="remove"></span>`;
}

/* Broken images, without inline onerror handlers — the CSP (security.py) blocks
   those, and dropping them is what lets script-src stay strict. `error` doesn't
   bubble, so this listens in the capture phase, which does see it and covers
   every icon added later by a render.

   The sweep below is not redundant: an image can fail before this file has even
   run, and a listener registered afterwards never hears about it. A decoded
   image has naturalWidth > 0, so a *complete* image with zero width failed. */
// Splash art is served from a local cache the backend fills lazily on the
// first-ever miss (see /api/champ-splash in dashboard.py) — a background
// thread that takes a few seconds. A splash <img> that fails on that very
// first request would otherwise stay broken for the rest of the session,
// since nothing else re-renders the tile until a filter/tab change or a new
// game. Retrying with backoff covers that warm-up window without polling.
const SPLASH_RETRY_DELAYS_MS = [1500, 3000, 6000, 12000, 24000];

const ON_ERROR = {
  remove: (el) => el.remove(),
  "retry-then-remove": (el) => {
    const attempt = (Number(el.dataset.retryAttempt) || 0) + 1;
    if (attempt > SPLASH_RETRY_DELAYS_MS.length) {
      el.remove();
      return;
    }
    el.dataset.retryAttempt = String(attempt);
    const src = el.src;
    setTimeout(() => {
      // A filter/tab change can rebuild #ov-totals/#ov-spotlight (and thus
      // destroy this <img>) before the retry fires — don't burn a request
      // fetching an image nothing is displaying anymore.
      if (!el.isConnected) return;
      el.src = ""; // forces a fresh request even if the browser would otherwise reuse the failed one
      el.src = src;
    }, SPLASH_RETRY_DELAYS_MS[attempt - 1]);
  },
};

function handleAssetError(el) {
  const action = ON_ERROR[el.dataset.onError];
  if (action) action(el);
}

document.addEventListener("error", (e) => {
  if (e.target instanceof HTMLImageElement) handleAssetError(e.target);
}, true);

function sweepBrokenImages() {
  document.querySelectorAll("img[data-on-error]").forEach((img) => {
    if (img.complete && img.naturalWidth === 0) handleAssetError(img);
  });
}

/* League Classic champions share a display name with the modern ones but are a
   different kit on a different map, so they're counted separately everywhere
   (tier list, scatter, filters). Suffixing always — rather than only once you
   own both — keeps the label predictable instead of silently forking a bar in
   two the day you first pick Classic Jax. */
function champKey(g) {
  if (!g.champion) return g.champion;
  return g.classic ? `${g.champion} (Classic)` : g.champion;
}

function enrich(g) {
  const d = new Date(g.played_at);
  const mins = (g.duration_seconds || 0) / 60;
  return {
    ...g,
    date: d,
    day: g.played_at.slice(0, 10),
    weekday: WEEKDAYS[(d.getDay() + 6) % 7],
    daypart: DAYPARTS[d.getHours() < 6 ? 3 : d.getHours() < 12 ? 0 : d.getHours() < 18 ? 1 : 2],
    duration_bucket: mins < 20 ? DURATIONS[0] : mins < 30 ? DURATIONS[1] : mins < 40 ? DURATIONS[2] : DURATIONS[3],
    enemy_champions: g.enemy_champions || [],
    augments: g.augments || [],
    items: g.items || [],
    tags: g.tags || [],
    month: g.played_at.slice(0, 7),
    session_index: Math.min(g.game_index_in_session || 1, 5) >= 5 ? "5+" : String(g.game_index_in_session || 1),
    result: g.win === 1 ? "Win" : g.win === 0 ? "Loss" : "?",
    // Raw `champion` stays as-is for the icon lookup; champion_key is what
    // every aggregate, filter and chart groups on.
    champion_key: champKey(g),
    mode_family: g.classic ? "League Classic" : "Modern",
    rated: g.fun_score != null && !g.skipped,
    pending: g.fun_score == null && !g.skipped && !g.is_remake,
    premades: (g.teammates || []).filter((t) => t.was_premade),
  };
}

function filtered() {
  return ALL.filter((g) => {
    if (g.is_remake) return false; // F5: remakes never count toward stats
    if (state.from && g.day < state.from) return false;
    if (state.to && g.day > state.to) return false;
    const s = state.sets;
    if (s.queue.size && !s.queue.has(g.queue_type)) return false;
    if (s.mode.size && !s.mode.has(g.mode_family)) return false;
    if (s.champion.size && !s.champion.has(g.champion_key)) return false;
    if (s.role.size && !s.role.has(g.role || "(unknown)")) return false;
    if (s.result.size && !s.result.has(g.result)) return false;
    if (s.teammate.size && !g.premades.some((t) => s.teammate.has(t.puuid))) return false;
    return true;
  });
}

/* group games by key; returns [{key, n, avgFun, winrate}] using rated games for fun */
function aggregate(games, keyFn) {
  const acc = new Map();
  for (const g of games) {
    for (const key of [].concat(keyFn(g) ?? [])) {
      if (key == null || key === "") continue;
      const a = acc.get(key) || { key, n: 0, funSum: 0, funN: 0, wins: 0, winN: 0 };
      a.n += 1;
      if (g.rated) { a.funSum += g.fun_score; a.funN += 1; }
      if (g.win === 0 || g.win === 1) { a.wins += g.win; a.winN += 1; }
      acc.set(key, a);
    }
  }
  return [...acc.values()].map((a) => ({
    key: a.key,
    n: a.funN,
    games: a.n,
    avgFun: a.funN ? a.funSum / a.funN : null,
    winrate: a.winN ? (100 * a.wins) / a.winN : null,
  }));
}

/* Per-champion career totals (raw sums, not averages) — feeds the Overview
   lifetime strip and spotlight tiles. Separate from aggregate() rather than
   extending it: aggregate() is shared by every tab's fun/winrate charts and
   deliberately stays narrow, while these sums (kills/deaths/assists/seconds)
   are Overview-specific. */
function championTotals(games) {
  const acc = new Map();
  for (const g of games) {
    const key = g.champion_key;
    if (!key) continue;
    const a = acc.get(key) || {
      key, name: g.champion, classic: g.classic, games: 0, n: 0,
      kills: 0, deaths: 0, assists: 0, seconds: 0, damage: 0, funSum: 0, funN: 0,
    };
    a.games += 1;
    a.kills += g.kills || 0;
    a.deaths += g.deaths || 0;
    a.assists += g.assists || 0;
    a.seconds += g.duration_seconds || 0;
    a.damage += g.damage_to_champs || 0; // null on games captured before this column existed
    if (g.rated) { a.funSum += g.fun_score; a.funN += 1; }
    acc.set(key, a);
  }
  return [...acc.values()].map((a) => ({
    key: a.key, name: a.name, classic: a.classic, games: a.games, n: a.funN,
    kills: a.kills, deaths: a.deaths, assists: a.assists, seconds: a.seconds, damage: a.damage,
    killsPerGame: a.kills / a.games,
    avgFun: a.funN ? a.funSum / a.funN : null,
  }));
}

/* One champion per category — used for the Lifetime totals cards, which each
   show exactly one stat's leader and so never hit the Spotlight duplication
   problem (see categoryRanked/buildSpotlightCards below). "kills"/etc. need
   no MIN_N gate (a raw total, not an average), but "vibe" does: an average
   from one lucky game isn't a career highlight, it's noise. Matches the
   MIN_N threshold the existing "Certified Banger" card already uses. */
function categoryLeaders(rows) {
  const top = (fn) => rows.length ? rows.reduce((best, r) => (fn(r) > fn(best) ? r : best)) : null;
  const vibeRows = rows.filter((r) => r.avgFun != null && r.n >= MIN_N);
  return {
    vibe: vibeRows.length ? vibeRows.reduce((best, r) => (r.avgFun > best.avgFun ? r : best)) : null,
    kills: top((r) => r.kills),
    deaths: top((r) => r.deaths),
    assists: top((r) => r.assists),
    hours: top((r) => r.seconds),
  };
}

/* Same categories, but every champion ranked best-to-worst instead of just
   the winner — Spotlight's dedup (below) needs runners-up to fill slots a
   duplicate champion would otherwise have left empty. Two categories here
   (damage, killsPerGame) exist only to widen this pool: with just kills/
   deaths/assists/hours, a small chaotic sample (a couple of wild ARAM games)
   tends to top several of them at once, which starves the fill loop of
   distinct runners-up and forces it back into a category it already used —
   more categories makes that far less likely without gating anyone out. */
function categoryRanked(rows) {
  const byStat = (fn) => rows.slice().sort((a, b) => fn(b) - fn(a));
  const vibeRows = rows.filter((r) => r.avgFun != null && r.n >= MIN_N);
  return {
    vibe: vibeRows.slice().sort((a, b) => b.avgFun - a.avgFun),
    kills: byStat((r) => r.kills),
    deaths: byStat((r) => r.deaths),
    assists: byStat((r) => r.assists),
    hours: byStat((r) => r.seconds),
    damage: byStat((r) => r.damage),
    killsPerGame: byStat((r) => r.killsPerGame),
  };
}

const SPOTLIGHT_CATS = ["vibe", "kills", "deaths", "assists", "hours", "damage", "killsPerGame"];
const SPOTLIGHT_SLOTS = 5;

/* A champion holding multiple leads (best vibe AND most kills) used to
   produce one Spotlight tile per category, so the same splash art repeated.
   Now: one card per unique champion carrying every badge it earned, and if
   that leaves fewer than SPOTLIGHT_SLOTS cards, the gap is filled with the
   next-best not-yet-featured champion in whichever category still has
   runners-up — so one dominant champion doesn't shrink the section. Each
   badge remembers whether its champion actually leads that category
   (isLeader) or is just filling a slot, so the two never look the same on
   screen — a filled-in runner-up must never read as tied with the real #1. */
function buildSpotlightCards(rows) {
  const ranked = categoryRanked(rows);
  const cards = new Map(); // champion key -> { row, cats: [{cat, isLeader}] }
  const order = [];

  const addBadge = (cat, row, isLeader) => {
    let c = cards.get(row.key);
    if (!c) { c = { row, cats: [] }; cards.set(row.key, c); order.push(row.key); }
    c.cats.push({ cat, isLeader });
  };

  // Merging a badge onto a champion that already has a card is always free
  // (no new slot spent), but a category whose leader would need a brand-new
  // card only gets one while room remains — otherwise 7 categories with 7
  // genuinely distinct leaders would produce 7 cards, blowing past the "up
  // to SPOTLIGHT_SLOTS" cap. Category priority (SPOTLIGHT_CATS order) decides
  // what gets dropped when slots run out.
  for (const cat of SPOTLIGHT_CATS) {
    const row = ranked[cat][0];
    if (!row) continue;
    if (!cards.has(row.key) && order.length >= SPOTLIGHT_SLOTS) continue;
    addBadge(cat, row, true);
  }

  // Runner-up fill: walk every category's ranking one rank deeper each pass
  // until slots are full or every category is exhausted.
  for (let depth = 1; order.length < SPOTLIGHT_SLOTS; depth++) {
    let addedThisPass = false;
    for (const cat of SPOTLIGHT_CATS) {
      if (order.length >= SPOTLIGHT_SLOTS) break;
      const row = ranked[cat][depth];
      if (row && !cards.has(row.key)) { addBadge(cat, row, false); addedThisPass = true; }
    }
    if (!addedThisPass) break; // every category's ranking is exhausted
  }

  return order.map((key) => cards.get(key));
}

/* Career sums across every champion, plus the earliest game's day for the
   "since <date>" caption. Deliberately computed from whatever `games` this
   is called with (the filtered set, same as the rest of Overview) rather
   than always ALL — consistent with how "Certified Banger" et al. already
   respond to the filter bar; only ARAM God is the documented exception. */
function lifetimeTotals(games) {
  if (!games.length) return { kills: 0, deaths: 0, assists: 0, seconds: 0, since: null };
  let kills = 0, deaths = 0, assists = 0, seconds = 0, since = games[0].day;
  for (const g of games) {
    kills += g.kills || 0;
    deaths += g.deaths || 0;
    assists += g.assists || 0;
    seconds += g.duration_seconds || 0;
    if (g.day < since) since = g.day;
  }
  return { kills, deaths, assists, seconds, since };
}

function champSplashUrl(name, classic) {
  if (!name) return null;
  return `/api/champ-splash/${encodeURIComponent(name)}${classic ? "?classic=1" : ""}`;
}

function formatHours(seconds) {
  return `${Math.round(seconds / 3600)}h`;
}

/* Average fun_score over an already-filtered list of rated games — the
   caller decides what "rated" means for its purpose (this session's
   filter, lifetime, remakes excluded or not); this just does the division
   the same way everywhere so the three "avg vibe" readouts on this page
   can't quietly drift apart. */
function avgFun(rated) {
  return rated.length ? rated.reduce((s, g) => s + g.fun_score, 0) / rated.length : null;
}

function formatSince(day) {
  if (!day) return "no games yet";
  const d = new Date(day);
  return `since ${d.toLocaleString("en-US", { month: "short", year: "numeric" })}`;
}

const OV_ICONS = {
  kills: '<path d="M4 20L14 10M14 10L11 7M14 10L17 13M20 4L10 14M10 14L13 17M10 14L7 11"/>',
  deaths: '<path d="M7 21V13a5 5 0 0110 0v8M4 21h16"/>',
  assists: '<circle cx="8" cy="12" r="4"/><circle cx="16" cy="12" r="4"/>',
  hours: '<path d="M12 3a9 9 0 100 18 9 9 0 000-18z"/><path d="M12 7v5l4 2"/>',
};

function ovIcon(kind) {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${OV_ICONS[kind]}</svg>`;
}

function ovSplashImg(leaderRow) {
  if (!leaderRow) return "";
  const url = champSplashUrl(leaderRow.name, leaderRow.classic);
  return `<img class="ov-splash-img" src="${escapeAttr(url)}" alt="" loading="lazy" data-on-error="retry-then-remove">`;
}

function renderLifetimeTotals(games, leaders) {
  const totals = lifetimeTotals(games);
  const since = formatSince(totals.since);
  const card = (kind, label, value, leaderRow) => `
    <div class="ov-tcard">
      ${ovSplashImg(leaderRow)}
      <div class="ov-scrim"></div>
      <div class="ov-content">
        <div>${ovIcon(kind)}<span class="ov-label">${label}</span></div>
        <div><div class="ov-value">${value}</div><div class="ov-since">${since}</div></div>
      </div>
    </div>`;
  document.getElementById("ov-totals").innerHTML =
    card("kills", "Kills", totals.kills.toLocaleString(), leaders.kills) +
    card("deaths", "Deaths", totals.deaths.toLocaleString(), leaders.deaths) +
    card("assists", "Assists", totals.assists.toLocaleString(), leaders.assists) +
    card("hours", "Time played", formatHours(totals.seconds), leaders.hours);
}

const OV_TIER_CLASS = { 1: "ov-tier1", 2: "ov-tier2", 3: "ov-tier3", 4: "ov-tier4", 5: "ov-tier5" };
const OV_CAT_ICON = {
  vibe: '<path d="M12 2l2.5 5.5L20 8l-4.5 4 1.5 6L12 15l-5 3 1.5-6L4 8l5.5-.5z"/>',
  kills: OV_ICONS.kills, deaths: OV_ICONS.deaths, assists: OV_ICONS.assists, hours: OV_ICONS.hours,
  damage: '<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>',
  killsPerGame: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
};
const OV_CAT_LABEL = {
  vibe: "Best vibe", kills: "Most kills", deaths: "Most deaths", assists: "Most assists", hours: "Most hours",
  damage: "Most damage", killsPerGame: "Best kill rate",
};
// Short noun form for the "Also: <noun>" runner-up phrasing below — deliberately
// not a shortened OV_CAT_LABEL, since "Also: Most kills" would still read as a
// tied #1 claim, which is exactly the confusion this pass exists to remove.
const OV_CAT_NOUN = {
  vibe: "Vibe", kills: "Kills", deaths: "Deaths", assists: "Assists", hours: "Hours",
  damage: "Damage", killsPerGame: "Kill rate",
};
const OV_CAT_HEADLINE = {
  vibe: (r) => r.avgFun.toFixed(1),
  kills: (r) => String(r.kills),
  deaths: (r) => String(r.deaths),
  assists: (r) => String(r.assists),
  hours: (r) => formatHours(r.seconds),
  damage: (r) => r.damage.toLocaleString(),
  killsPerGame: (r) => r.killsPerGame.toFixed(1),
};

function ovSpotlightTile(card) {
  if (!card) {
    return `<div class="ov-stile"><div class="ov-overlay" style="opacity:1"><div class="ov-empty-note">not enough data yet</div></div></div>`;
  }
  const { row, cats } = card;
  const tierRound = row.avgFun != null ? Math.round(row.avgFun) : null;
  const tierClass = tierRound ? OV_TIER_CLASS[tierRound] : "ov-tier3";
  const vibeLabel = tierRound ? `${row.avgFun.toFixed(2)} · ${GRADES[tierRound]}` : "not enough rated games";
  // A champion that leads several categories at once (rare, but real — a
  // dominant ARAM one-trick can lead vibe/kills/deaths/assists together)
  // stacks one pill per badge here. Left unbounded, that stack grows tall
  // enough to run into the bottom headline (name/score) on a short tile.
  // Cap what's shown and fold the rest into a "+N more" pill rather than
  // either hiding badges outright or letting them overlap the headline.
  const MAX_VISIBLE_PILLS = 3;
  const visibleCats = cats.slice(0, MAX_VISIBLE_PILLS);
  const hiddenCount = cats.length - visibleCats.length;
  const pills = visibleCats.map(({ cat, isLeader }) =>
    `<div class="ov-cat-pill${isLeader ? "" : " ov-cat-pill-runnerup"}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${OV_CAT_ICON[cat]}</svg>${isLeader ? OV_CAT_LABEL[cat] : `Also: ${OV_CAT_NOUN[cat]}`}</div>`
  ).join("") + (hiddenCount > 0 ? `<div class="ov-cat-pill ov-cat-pill-runnerup">+${hiddenCount} more</div>` : "");
  // Prefer a genuine leader for the headline number — a card built entirely
  // from runner-up fills (never led anything outright) falls back to its
  // first badge, which is still an honest reflection of why it's on screen.
  const headlineCat = (cats.find((c) => c.isLeader) || cats[0]).cat;
  return `
    <div class="ov-stile">
      ${ovSplashImg(row)}
      <div class="ov-scrim"></div>
      <div class="ov-cat-pills">${pills}</div>
      <div class="ov-headline">
        <div class="ov-champ-name">${escapeAttr(row.key)}</div>
        <div class="ov-stat-big">${OV_CAT_HEADLINE[headlineCat](row)}</div>
      </div>
      <div class="ov-overlay">
        <div class="ov-name">${escapeAttr(row.key)}</div>
        <div class="ov-games">${row.games} game${row.games === 1 ? "" : "s"}</div>
        <div class="ov-grow">
          <div class="ov-g"><b>${row.kills}</b>Kills</div>
          <div class="ov-g"><b>${row.deaths}</b>Deaths</div>
          <div class="ov-g"><b>${row.assists}</b>Assists</div>
          <div class="ov-g"><b>${formatHours(row.seconds)}</b>Played</div>
        </div>
        <div class="ov-vibe-row ${tierClass}">${vibeLabel}</div>
      </div>
    </div>`;
}

function renderSpotlight(rows) {
  const cards = buildSpotlightCards(rows);
  document.getElementById("ov-spotlight").innerHTML = cards.length
    ? cards.map((c) => ovSpotlightTile(c)).join("")
    : ovSpotlightTile(null);
}

/* Shared engine behind the compact hero-row cards (ARAM God / Arena God on
   Overview) — same markup, same "not tracked yet" guard, only the label/
   caption copy and the data source differ. One generic function instead of
   a second near-duplicate now that there are two of these (issue #103). */
async function renderAchievementCompact(hostId, fetchFn, getCached, setCached, copy) {
  const host = document.getElementById(hostId);
  let d;
  try {
    d = setCached(getCached() || (await fetchFn()));
  } catch {
    host.innerHTML = "";
    return;
  }
  // Both conditions matter and must not collapse into one: a 0 total before
  // the client has ever synced is "we don't know yet", not "zero progress".
  if (!d.tracked || !d.total) {
    host.innerHTML = `
      <div class="ov-aram-card ov-aram-empty">
        <div class="ov-aram-sq-label">${copy.label}</div>
        <div class="ov-aram-sq-number">—</div>
        <div class="ov-aram-sq-pill">Not tracked yet</div>
        <div class="ov-aram-sq-bar"><div class="ov-aram-sq-fill" style="width:0%"></div></div>
        <div class="ov-aram-sq-caption">Open the League client once with VibeCheck running to start tracking this</div>
      </div>`;
    return;
  }
  const pct = Math.round((d.completed / d.total) * 100);
  host.innerHTML = `
    <div class="ov-aram-card">
      <div class="ov-aram-sq-label">${copy.label}</div>
      <div class="ov-aram-sq-number">${d.completed}/${d.total}</div>
      <div class="ov-aram-sq-pill">${pct}% complete</div>
      <div class="ov-aram-sq-bar"><div class="ov-aram-sq-fill" style="width:${pct}%"></div></div>
      <div class="ov-aram-sq-caption">${copy.caption}</div>
    </div>`;
}

function renderAramGodCompact() {
  return renderAchievementCompact(
    "ov-aram",
    fetchAramGod,
    () => ARAM_GOD,
    (d) => (ARAM_GOD = d),
    { label: "ARAM god run", caption: "S- or better on every ARAM champion" }
  );
}

function renderArenaGodCompact() {
  return renderAchievementCompact(
    "ov-arena",
    fetchArenaGod,
    () => ARENA_GOD,
    (d) => (ARENA_GOD = d),
    { label: "Arena god run", caption: "1st place in Arena with every champion, up to Riot's own Master rank" }
  );
}

const OV_TIER_HEX = { 1: "#EF4444", 2: "#F97316", 3: "#EAB308", 4: "#10B981", 5: "#8B5CF6" };

function formatTrendDate(day) {
  const d = new Date(day);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/* The chart's default reading when nothing is hovered, and what every
   hovered point swaps in — one function so the two states can never
   drift out of sync with each other's markup. */
function trendReadoutHtml(g) {
  return `
    <div class="ov-trend-readout-dot" style="background:${OV_TIER_HEX[g.fun_score]}"></div>
    <div class="ov-trend-readout-meta"><b>${escapeAttr(g.champion_key || "?")} — ${formatTrendDate(g.day)}</b>${GRADES[g.fun_score]} (${g.fun_score})</div>`;
}

// Transient UI state, not persisted: a deliberate filter choice, so unlike
// last round's one-way "expand" it survives a real data refresh (see
// refresh() — no longer resets this) and only goes back to the default on
// a full page reload.
let ovTrendWindow = 20; // 20 | 50 | "all"
function renderVibeTrend(games) {
  const host = document.getElementById("ov-trend");
  const rated = games.filter((g) => g.rated).slice().sort((a, b) => a.date - b.date);
  if (!rated.length) {
    host.innerHTML = '<div class="ov-trend-empty">Rate a few games and your vibe trend shows up here.</div>';
    return;
  }
  // "How have I been doing lately" is the point of a trend, so a window
  // keeps the most recent games (slice(-N)), not the oldest.
  const shown = ovTrendWindow === "all" ? rated : rated.slice(-ovTrendWindow);
  const n = shown.length;
  const points = shown.map((g, i) => ({
    x: n > 1 ? (100 * i) / (n - 1) : 50,
    // Plot 1–5 into the 8–92% band, inverted (SVG y grows downward, and a
    // high score should sit near the top of the chart).
    y: 92 - ((g.fun_score - 1) / 4) * 84,
    g,
  }));
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const dots = points.map((p, i) => `
    <div class="ov-trend-point" data-idx="${i}" style="left:${p.x.toFixed(1)}%;top:${p.y.toFixed(1)}%;--ring:${OV_TIER_HEX[p.g.fun_score]}"
         title="${escapeAttr(p.g.champion_key || "?")} — ${escapeAttr(p.g.day)} — ${GRADES[p.g.fun_score]}">
      <div class="ov-ring"></div>
      <img src="/api/champ-icon/${encodeURIComponent(p.g.champion || "")}${p.g.classic ? "?classic=1" : ""}"
           alt="" loading="lazy" data-on-error="remove">
    </div>`).join("");
  // y-axis is fixed (every chart plots the same 1-5 band). x-axis labels
  // are the real dates of up to 5 actual points, picked at evenly-spaced
  // INDICES (deduped) rather than independently computed positions, so a
  // label always matches a real game and a short array just yields fewer
  // labels instead of crowded/duplicate ones.
  const yAxisHtml = [5, 4, 3, 2, 1].map((t) => `<span>${t}</span>`).join("");
  const idxCount = Math.min(5, n);
  const labelIndices = idxCount <= 1
    ? [0]
    : [...new Set(Array.from({ length: idxCount }, (_, i) => Math.round((i * (n - 1)) / (idxCount - 1))))];
  const xAxisHtml = labelIndices.map((i) => `<span>${formatTrendDate(shown[i].day)}</span>`).join("");
  const windowLabel = ovTrendWindow === "all" ? "All" : String(ovTrendWindow);

  host.innerHTML = `
    <div class="ov-trend-row">
      <div class="ov-trend-yaxis">${yAxisHtml}</div>
      <div class="ov-trend-col">
        <div class="ov-trend-chart">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline fill="none" stroke="${OV_TIER_HEX[3]}22" stroke-width="1.2" vector-effect="non-scaling-stroke" points="${line}"/>
          </svg>
          ${dots}
        </div>
        <div class="ov-trend-xaxis">${xAxisHtml}</div>
      </div>
    </div>
    <div class="ov-trend-legend">${[1, 2, 3, 4, 5].map((t) => `<span><i style="background:${OV_TIER_HEX[t]}"></i>${GRADES[t]}</span>`).join("")}</div>
    <div class="ov-trend-readout" id="ov-trend-readout">${trendReadoutHtml(shown[n - 1])}</div>
    <div class="ov-trend-filter">
      <button type="button" class="ov-trend-filter-btn" id="ov-trend-filter-btn">${windowLabel} ▾</button>
      <div class="ov-trend-filter-menu hidden" id="ov-trend-filter-menu">
        <button type="button" data-window="20">Last 20 games</button>
        <button type="button" data-window="50">Last 50 games</button>
        <button type="button" data-window="all">All games</button>
      </div>
    </div>`;

  // Hover a point -> show its exact detail; leave -> back to the most
  // recent game, so the readout is never blank.
  document.querySelectorAll("#ov-trend .ov-trend-point").forEach((el) => {
    const idx = Number(el.dataset.idx);
    el.addEventListener("mouseenter", () => {
      document.getElementById("ov-trend-readout").innerHTML = trendReadoutHtml(points[idx].g);
    });
    el.addEventListener("mouseleave", () => {
      document.getElementById("ov-trend-readout").innerHTML = trendReadoutHtml(shown[n - 1]);
    });
  });

  // The button's own toggle listener is safe to re-attach every render
  // (it's attached to an element destroyed/recreated together with any
  // old listener on it). The menu's OUTSIDE-click-closes listener is NOT
  // here — see the one-time registration near the profile-menu wiring,
  // per this plan's Global Constraints.
  document.getElementById("ov-trend-filter-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    document.getElementById("ov-trend-filter-menu").classList.toggle("hidden");
  });
  document.querySelectorAll("#ov-trend-filter-menu button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const w = btn.dataset.window;
      ovTrendWindow = w === "all" ? "all" : Number(w);
      document.getElementById("ov-trend-filter-menu").classList.add("hidden");
      renderVibeTrend(games);
    });
  });
}

/* ---------------- chart helpers ---------------- */

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function funBarChart(id, rows, { horizontal = false, fixedOrder = null } = {}) {
  destroyChart(id);
  const el = document.getElementById(id);
  rows = rows.filter((r) => r.avgFun != null);
  if (fixedOrder) {
    rows.sort((a, b) => fixedOrder.indexOf(a.key) - fixedOrder.indexOf(b.key));
  } else {
    rows.sort((a, b) => b.avgFun - a.avgFun);
  }
  charts[id] = new Chart(el, {
    type: "bar",
    data: {
      labels: rows.map((r) => r.key),
      datasets: [{
        data: rows.map((r) => r.avgFun),
        backgroundColor: rows.map((r) => (r.n < MIN_N ? MUTED : GOLD)),
        borderRadius: 4,
        maxBarThickness: 26,
        borderSkipped: "start",
      }],
    },
    options: {
      indexAxis: horizontal ? "y" : "x",
      maintainAspectRatio: false,
      scales: {
        [horizontal ? "x" : "y"]: { min: 1, max: 5, ticks: { callback: vibeAxisTick } },
        [horizontal ? "y" : "x"]: { grid: { display: false } },
      },
      plugins: { tooltip: { callbacks: {
        label: (c) => {
          const r = rows[c.dataIndex];
          const tag = r.n < MIN_N ? " · not enough data yet" : "";
          return ` avg vibe ${r.avgFun.toFixed(2)} ${EMOJI[Math.round(r.avgFun)]} · ${r.n} rated game${r.n > 1 ? "s" : ""}${tag}`;
        },
      } } },
    },
  });
  return rows.length;
}

/* Decoded <img> objects for Chart.js pointStyle, which needs elements rather
   than URLs. Cached across renders; a champion whose icon never loads simply
   stays absent from the map and falls back to a dot. */
const CHAMP_IMAGES = new Map();

function champImage(key, onLoad) {
  if (CHAMP_IMAGES.has(key)) return CHAMP_IMAGES.get(key);
  const { name, classic } = splitChampKey(key);
  const img = new Image();
  img.onload = () => onLoad && onLoad();
  img.onerror = () => CHAMP_IMAGES.set(key, null); // fall back to a plain dot
  img.src = `/api/champ-icon/${encodeURIComponent(name)}${classic ? "?classic=1" : ""}`;
  CHAMP_IMAGES.set(key, img);
  return img;
}

/* pointHoverRadius does nothing for image points — Chart.js won't rescale a
   bitmap on hover. So redraw the hovered icon on top, larger, with a gold ring
   and a dark backdrop. Drawing it last also lifts it clear of the neighbours it
   overlaps, which is the whole point when portraits stack at 0% and 100%. */
const champHoverPlugin = {
  id: "champHover",
  afterDatasetsDraw(chart) {
    const active = chart.getActiveElements();
    if (!active.length) return;
    const { datasetIndex, index } = active[0];
    const img = chart.data.datasets[datasetIndex].pointStyle[index];
    if (!(img instanceof HTMLImageElement) || !img.complete) return;
    const { x, y } = active[0].element;
    const size = Math.round(img.width * 1.45);
    const half = size / 2;
    const ctx = chart.ctx;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,.75)";
    ctx.shadowBlur = 10;
    ctx.fillStyle = "#10141a";
    ctx.fillRect(x - half - 2, y - half - 2, size + 4, size + 4);
    ctx.shadowBlur = 0;
    ctx.drawImage(img, x - half, y - half, size, size);
    ctx.strokeStyle = "#c8aa6e";
    ctx.lineWidth = 2;
    ctx.strokeRect(x - half - 1, y - half - 1, size + 2, size + 2);
    ctx.restore();
  },
};

/* Champions that land on the same or near-identical coordinates hide each
   other's portrait completely — and with small samples this is common, not
   rare (two champions at 3.00 and 50% is an ordinary Tuesday, and one at
   2.93 and 47% is visually the same dot). Height can't fix that; only
   separation can.

   Collision is proximity, not exact match: within COLLISION_PCT winrate
   points AND COLLISION_VIBE vibe points of each other. Union-find rather
   than a single pairwise check, so a chain of near-misses (A close to B,
   B close to C, but A not close to C) still fans together as one group —
   otherwise A and C could each separately collide with B while the group
   itself never gets recognized as one cluster.

   Colliding champions are fanned along the winrate axis, which is the
   secondary metric here — vibe stays exactly where it belongs on the y
   axis. The spread is a couple of percent, tooltips always report each
   champion's true value, and groups near 0% or 100% are nudged inward so
   nobody gets pushed off the plot. */
const COLLISION_PCT = 5; // winrate percentage points — matches issue #89
const COLLISION_VIBE = 0.15; // vibe points; small samples cluster on clean fractions (thirds, quarters, ...)

function fanTies(rows) {
  const parent = rows.map((_, i) => i);
  const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  for (let i = 0; i < rows.length; i++) {
    for (let j = i + 1; j < rows.length; j++) {
      if (Math.abs(rows[i].winrate - rows[j].winrate) <= COLLISION_PCT &&
          Math.abs(rows[i].avgFun - rows[j].avgFun) <= COLLISION_VIBE) {
        const ri = find(i), rj = find(j);
        if (ri !== rj) parent[ri] = rj;
      }
    }
  }
  const groups = new Map();
  rows.forEach((r, i) => {
    const root = find(i);
    (groups.get(root) || groups.set(root, []).get(root)).push(r);
  });
  // Winrate % between fanned portraits. ~3.6% clears a 36px icon on a typical
  // window; the fan tightens on narrow ones, which is the right way round.
  const STEP = 3.6;
  for (const tied of groups.values()) {
    if (tied.length < 2) continue;
    // Stable order, so a champion doesn't hop position between renders.
    tied.sort((a, b) => a.key.localeCompare(b.key));
    // The group's members aren't necessarily at the exact same winrate
    // (proximity, not equality) — center the fan on their average rather
    // than picking one member's value arbitrarily.
    const center = tied.reduce((s, r) => s + r.winrate, 0) / tied.length;
    const span = STEP * (tied.length - 1);
    let start = center - span / 2;
    start = Math.max(0, Math.min(100 - span, start)); // keep the fan on-plot
    tied.forEach((r, i) => { r.plotX = start + i * STEP; });
  }
  return rows;
}

function funScatterChart(id, rows) {
  destroyChart(id);
  rows = fanTies(rows.filter((r) => r.avgFun != null && r.winrate != null));
  // Draw now, upgrade to portraits as they decode: a cold icon cache or an
  // offline machine must never hold the chart back.
  let queued = false;
  const rerender = () => {
    if (queued) return;
    queued = true;
    setTimeout(() => { if (charts[id]) funScatterChart(id, rows); }, 120);
  };
  const sized = (r) => {
    const img = champImage(r.key, rerender);
    if (!img || !img.complete || !img.naturalWidth) return null;
    // Sample size drives icon size, exactly as it drove point radius before,
    // so "not enough data yet" still reads at a glance.
    img.width = img.height = Math.min(30 + r.n * 3, 52);
    return img;
  };
  charts[id] = new Chart(document.getElementById(id), {
    type: "scatter",
    data: { datasets: [{
      // plotX is the fanned position when this champion ties with another;
      // r.winrate (the true value) is what the tooltip reports.
      data: rows.map((r) => ({ x: r.plotX ?? r.winrate, y: r.avgFun, r })),
      backgroundColor: rows.map((r) => (r.n < MIN_N ? MUTED : GOLD)),
      pointStyle: rows.map((r) => sized(r) || "circle"),
      pointRadius: rows.map((r) => Math.min(4 + r.n, 14)),
      pointHoverRadius: rows.map((r) => Math.min(6 + r.n, 16)),
      // 0% and 100% winrate are common (small samples), and those points sit
      // exactly on the plot edge — without this the icons are cut in half.
      clip: false,
    }] },
    options: {
      maintainAspectRatio: false,
      // Room for the half-icon that now overhangs each edge, plus the enlarged
      // hover state on top of that.
      layout: { padding: { left: 34, right: 34, top: 34, bottom: 10 } },
      // Hit the nearest portrait rather than requiring a hit inside the point:
      // where icons overlap, "nearest" is what makes the top one reachable.
      interaction: { mode: "nearest", intersect: true },
      scales: {
        x: { min: 0, max: 100, title: { display: true, text: "winrate %" } },
        y: { min: 1, max: 5, title: { display: true, text: "avg vibe" }, ticks: { callback: vibeAxisTick } },
      },
      plugins: { tooltip: { callbacks: {
        label: (c) => {
          const r = c.raw.r;
          const tag = r.n < MIN_N ? " · not enough data yet" : "";
          return ` ${r.key}: vibe ${r.avgFun.toFixed(2)}, winrate ${r.winrate.toFixed(0)}% (${r.n} rated)${tag}`;
        },
      } } },
    },
    plugins: [champHoverPlugin],
  });
}

/* ---------------- views ---------------- */

function renderHeader(games) {
  const rated = games.filter((g) => g.rated);
  const avg = avgFun(rated);
  document.getElementById("pm-stats").innerHTML =
    `<b>${games.length}</b> games · <b>${rated.length}</b> rated` +
    (avg != null ? ` · avg vibe <b>${avg.toFixed(2)}</b>` : "");
  // The profile button shows the overall (unfiltered) vibe as an identity stat.
  const allRated = ALL.filter((g) => g.rated);
  const allAvg = avgFun(allRated);
  document.getElementById("profile-vibe").textContent =
    allAvg != null ? `avg vibe ${allAvg.toFixed(2)} ${EMOJI[Math.round(allAvg)]}` : "no ratings yet";
  const banner = document.getElementById("low-data-banner");
  const totalRated = allRated.length;
  if (totalRated < MIN_N) {
    banner.textContent = `The vibes are still buffering — ${totalRated}/${MIN_N} rated games until the insights unlock. Go feed the machine. 🎮`;
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
}

/* Lifetime average, always — reads ALL directly rather than the filtered
   `games` renderOverview receives, same reasoning as #profile-vibe above:
   this is the one number on Overview that shouldn't move when you filter. */
function vibeMeterStats() {
  const total = ALL.filter((g) => !g.is_remake).length;
  const rated = ALL.filter((g) => g.rated && !g.is_remake);
  return { avg: avgFun(rated), n: rated.length, total };
}

function renderVibeMeter() {
  const { avg, n, total } = vibeMeterStats();
  const host = document.getElementById("ov-vibemeter");
  const segs = [1, 2, 3, 4, 5].map((t) => `<div class="ov-vm-seg" style="background:var(--vc-t${t})"></div>`).join("");
  const ticks = [1, 2, 3, 4, 5].map((t) => `<span>${t}</span>`).join("");
  const caption = `<b>${total}</b> games · <b>${n}</b> rated`;
  if (avg == null) {
    host.innerHTML = `
      <div class="ov-vibemeter-card ov-vm-empty">
        <div class="ov-vm-label">Vibe-o-meter</div>
        <div class="ov-vm-number">—</div>
        <div class="ov-vm-pill">No rated games yet</div>
        <div class="ov-vm-bar">${segs}</div>
        <div class="ov-vm-ticks">${ticks}</div>
        <div class="ov-vm-caption">${caption}</div>
      </div>`;
    return;
  }
  const tier = Math.round(avg);
  const pct = ((avg - 1) / 4) * 100;
  host.innerHTML = `
    <div class="ov-vibemeter-card">
      <div class="ov-vm-label">Vibe-o-meter</div>
      <div class="ov-vm-number">${avg.toFixed(2)}</div>
      <div class="ov-vm-pill ${OV_TIER_CLASS[tier]}">${GRADES[tier]}</div>
      <div class="ov-vm-bar">
        <div class="ov-vm-marker" style="left:${pct.toFixed(1)}%"></div>
        ${segs}
      </div>
      <div class="ov-vm-ticks">${ticks}</div>
      <div class="ov-vm-caption">${caption}</div>
    </div>`;
}

function renderOverview(games) {
  // Deliberately first and reading ALL, not `games` — the vibe-o-meter is
  // lifetime-average and does not react to the filter bar (see
  // vibeMeterStats' doc comment). Everything below it does.
  renderVibeMeter();
  // Computed once and shared: totals and spotlight both derive from the same
  // per-champion rows, and championTotals() isn't free to redo twice on
  // every filter-bar keystroke.
  const rows = championTotals(games);
  renderLifetimeTotals(games, categoryLeaders(rows));
  renderSpotlight(rows);
  renderAramGodCompact();
  renderArenaGodCompact();
  renderVibeTrend(games);
  // Compact preview of the full regret curve on Patterns & Tags (chart-sessions)
  // — same aggregation, same funBarChart helper, just a second, smaller canvas,
  // since a Chart.js instance is bound 1:1 to its canvas element.
  funBarChart("chart-ov-regret", aggregate(games, (g) => g.session_index), { fixedOrder: ["1", "2", "3", "4", "5+"] });
}

function renderChampions(games) {
  const byChamp = aggregate(games, (g) => g.champion_key);
  renderAramGod();
  renderArenaGod();
  renderTierList(byChamp);
  funScatterChart("chart-champ-scatter", byChamp);
}

/* ---------------- ARAM God (PRD §16) ---------------- */

/* Deliberately outside the filter pipeline. Every other panel on this page
   describes the games VibeCheck captured, and re-renders when the filter bar
   changes; this one is a lifetime figure read from the League client, so a
   date filter must not appear to move it. Cached until the store's revision
   changes, because renderChampions runs on every filter keystroke and this
   would otherwise refetch on each one. */
let ARAM_GOD = null;
let ARAM_GOD_PENDING = null; // in-flight fetch, so rapid re-renders share one request
let ARAM_GOD_DRAWN = null; // what's currently on screen
let ARENA_GOD = null;
let ARENA_GOD_PENDING = null;
let ARENA_GOD_DRAWN = null;

/* Shared by the full grid (Champions tab) and the compact widget (Overview)
   — both read the same lifetime figure, so this in-flight-request guard
   must be shared too, or a render of each panel back-to-back fires two
   requests instead of one. */
function fetchAramGod() {
  ARAM_GOD_PENDING = ARAM_GOD_PENDING || fetchJSON("/api/aram-god");
  return ARAM_GOD_PENDING.finally(() => { ARAM_GOD_PENDING = null; });
}

function fetchArenaGod() {
  ARENA_GOD_PENDING = ARENA_GOD_PENDING || fetchJSON("/api/arena-god");
  return ARENA_GOD_PENDING.finally(() => { ARENA_GOD_PENDING = null; });
}

/* Shared engine behind the full champion grids (Champions tab) — same as
   renderAchievementCompact above, one generic function behind two thin,
   purpose-named callers (issue #103). `copy.notEarnedWord` is the noun the
   "every single one" congratulation refers to ("champion" for ARAM,
   "win" for Arena — Arena God's grid can't literally reach every champion,
   since its own finish line is 60, not the full roster). */
async function renderAchievementGrid(hostId, fetchFn, getCached, setCached, getDrawn, setDrawn, copy) {
  const host = document.getElementById(hostId);
  let d;
  try {
    d = getCached() || setCached(await fetchFn());
  } catch {
    host.innerHTML = `<div class="empty-note">Couldn't read your ${copy.label} progress.</div>`;
    return;
  }
  // The grid is ~173 cells and as many <img>s. Rebuilding it on every keystroke
  // in the filter bar is a visible stutter, and pointless: this panel is
  // lifetime data that no filter can change. Only redraw when it actually did.
  if (getDrawn() === d && host.firstChild) return;
  setDrawn(d);
  // Never render a confident 0/N we haven't earned: before the app has read
  // the challenge once, zero completed and "we don't know yet" look identical
  // in the data and mean completely different things to the player.
  if (!d.tracked || !d.total) {
    host.innerHTML =
      '<div class="empty-note">Open the League client once with VibeCheck running — ' +
      "we'll read your challenge progress from it. Nothing to set up.</div>";
    return;
  }
  const left = Math.max(d.total - d.completed, 0);
  const pct = d.total ? Math.round((d.completed / d.total) * 100) : 0;
  const cell = (c) =>
    `<div class="ag-cell${c.done ? " is-done" : ""}" title="${escapeAttr(c.name)}">` +
    `${champIcon(c.name, false)}<span>${escapeAttr(c.name)}</span></div>`;
  host.innerHTML =
    `<div class="ag-head">` +
    `<b class="ag-score">${d.completed} / ${d.total}</b>` +
    `<span class="ag-left">${left ? `${left} to go` : `every single ${copy.notEarnedWord}. absolute unit.`}</span>` +
    `</div>` +
    `<div class="ag-bar"><i style="width:${pct}%"></i></div>` +
    `<div class="ag-grid">${d.champions.map(cell).join("")}</div>`;
}

function renderAramGod() {
  return renderAchievementGrid(
    "aram-god",
    fetchAramGod,
    () => ARAM_GOD,
    (d) => (ARAM_GOD = d),
    () => ARAM_GOD_DRAWN,
    (d) => (ARAM_GOD_DRAWN = d),
    { label: "ARAM God", notEarnedWord: "champion" }
  );
}

function renderArenaGod() {
  return renderAchievementGrid(
    "arena-god",
    fetchArenaGod,
    () => ARENA_GOD,
    (d) => (ARENA_GOD = d),
    () => ARENA_GOD_DRAWN,
    (d) => (ARENA_GOD_DRAWN = d),
    { label: "Arena God", notEarnedWord: "win" }
  );
}

/* Aggregate keys carry the "(Classic)" suffix, so split it back out to get the
   champion name the icon endpoint expects, plus the variant flag. */
function splitChampKey(key) {
  const classic = key.endsWith(" (Classic)");
  return { name: classic ? key.slice(0, -10) : key, classic };
}

/* The tier list is HTML rather than a canvas bar chart, for two reasons:
   Chart.js has no hook for images in category tick labels, and a fixed-height
   canvas becomes unreadable once you've played a hundred champions. Rows
   scroll; bars are plain divs. Colours match the chart marks exactly. */
const TIER_TOP_N = 10; // shown by default; the rest is one click away

function renderTierList(rows) {
  const host = document.getElementById("champ-tiers");
  const list = rows.filter((r) => r.avgFun != null).sort((a, b) => b.avgFun - a.avgFun);
  if (!list.length) {
    host.innerHTML = '<div class="empty-note">No rated games match this filter.</div>';
    return;
  }
  const row = (r, i) => {
    const { name, classic } = splitChampKey(r.key);
    // Bars span the 1–5 rating range, not 0–5: at 0–5 every champion's bar
    // starts a fifth of the way along and the differences that matter get
    // squashed into the right-hand half.
    const pct = (100 * (r.avgFun - 1)) / 4;
    const thin = r.n < MIN_N;
    const tip = `avg vibe ${r.avgFun.toFixed(2)} · ${r.n} rated game${r.n === 1 ? "" : "s"}` +
                (thin ? " · not enough data yet" : "");
    return `
      <div class="tier-row${i >= TIER_TOP_N ? " extra hidden" : ""}" title="${escapeAttr(tip)}">
        ${champIcon(name, classic)}
        <div class="tier-name">${escapeAttr(r.key)}</div>
        <div class="tier-track"><div class="tier-fill${thin ? " thin" : ""}" style="width:${pct.toFixed(1)}%"></div></div>
        <div class="tier-score${thin ? " thin" : ""}">${r.avgFun.toFixed(2)}</div>
      </div>`;
  };
  const axis = `<div class="tier-axis">${[1, 2, 3, 4, 5].map((v) => `<span>${vibeAxisTick(v)}</span>`).join("")}</div>`;
  const hidden = list.length - TIER_TOP_N;
  const toggle = hidden > 0
    ? `<button class="tier-toggle" id="tier-toggle" data-open="0">▾ Show all ${list.length}</button>`
    : "";
  host.innerHTML = list.map(row).join("") + axis + toggle;

  const btn = document.getElementById("tier-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const open = btn.dataset.open === "1";
      btn.dataset.open = open ? "0" : "1";
      btn.textContent = open ? `▾ Show all ${list.length}` : "▴ Show top 10";
      host.querySelectorAll(".tier-row.extra").forEach((el) => el.classList.toggle("hidden", open));
    });
  }
}

function renderSquad(games) {
  // key premades by puuid, display latest known name
  const names = new Map();
  for (const g of games) for (const t of g.premades) names.set(t.puuid, t.name || "(unknown)");
  const rows = aggregate(games, (g) => (g.premades.length ? g.premades.map((t) => t.puuid) : ["__solo__"]));
  for (const r of rows) r.key = r.key === "__solo__" ? "Without premades" : `with ${names.get(r.key) || "?"}`;
  destroyChart("chart-squad");
  const data = rows.filter((r) => r.avgFun != null).sort((a, b) => b.avgFun - a.avgFun);
  charts["chart-squad"] = new Chart(document.getElementById("chart-squad"), {
    type: "bar",
    data: {
      labels: data.map((r) => r.key),
      datasets: [{
        data: data.map((r) => r.avgFun),
        backgroundColor: data.map((r) => (r.n < MIN_N ? MUTED : r.key === "Without premades" ? TEAL : GOLD)),
        borderRadius: 4, maxBarThickness: 26,
      }],
    },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      scales: { x: { min: 1, max: 5, ticks: { callback: vibeAxisTick } }, y: { grid: { display: false } } },
      plugins: { tooltip: { callbacks: {
        label: (c) => {
          const r = data[c.dataIndex];
          const tag = r.n < MIN_N ? " · not enough data yet" : "";
          return ` avg vibe ${r.avgFun.toFixed(2)} · ${r.n} rated games${tag}`;
        },
      } } },
    },
  });
  renderCommunityService(games);
}

/* Community Service (Charity Work): the karma you earn playing with the friend
   you keep losing with. We don't store teammates' KDA, so the "designated
   deadweight" is whoever you've eaten the most defeats alongside — the Moral
   Victory Score is how much of your vibe survived those losses. */
function renderCommunityService(games) {
  const host = document.getElementById("community-service");
  const per = new Map();
  for (const g of games) {
    for (const t of g.premades) {
      const a = per.get(t.puuid) || { name: t.name || "(unknown)", n: 0, losses: 0, funSum: 0, funN: 0 };
      a.name = t.name || a.name;
      a.n += 1;
      if (g.win === 0) a.losses += 1;
      if (g.rated) { a.funSum += g.fun_score; a.funN += 1; }
      per.set(t.puuid, a);
    }
  }
  const rows = [...per.values()]
    .filter((a) => a.n >= MIN_N)
    .map((a) => ({
      name: a.name,
      games: a.n,
      losses: a.losses,
      avgVibe: a.funN ? a.funSum / a.funN : null,
      // Moral Victory Score: how much of a perfect 5 vibe you kept, %.
      mvs: a.funN ? Math.round((a.funSum / a.funN / 5) * 100) : null,
    }))
    .sort((x, y) => y.losses - x.losses);

  if (!rows.length) {
    host.innerHTML = `<div class="empty-note">Not enough games with any one friend yet (needs ${MIN_N}). Go do some charity work. 🫡</div>`;
    return;
  }

  const dw = rows[0]; // designated deadweight = most losses together (affectionately)
  const insight = dw.avgVibe != null
    ? `You've eaten <b>${dw.losses}</b> defeat${dw.losses === 1 ? "" : "s"} alongside <b>${escapeAttr(dw.name)}</b> — and still rated those games <b>${dw.avgVibe.toFixed(2)}/5</b>. Mental resilience holding at <b>${dw.mvs}%</b>. You're practically a saint. 😇`
    : `You've eaten <b>${dw.losses}</b> defeat${dw.losses === 1 ? "" : "s"} alongside <b>${escapeAttr(dw.name)}</b> and haven't rated one. Bottling it up, are we?`;

  host.innerHTML =
    `<div class="banner">${insight}</div>` +
    `<table><thead><tr><th>Teammate</th><th class="num">games</th><th class="num">losses</th><th class="num">your avg vibe</th><th class="num">Moral Victory Score</th></tr></thead><tbody>` +
    rows.map((r) => `<tr>
      <td>${escapeAttr(r.name)}</td>
      <td class="num">${r.games}</td>
      <td class="num">${r.losses}</td>
      <td class="num">${r.avgVibe != null ? r.avgVibe.toFixed(2) + " " + EMOJI[Math.round(r.avgVibe)] : "—"}</td>
      <td class="num">${r.mvs != null ? r.mvs + "%" : "—"}</td></tr>`).join("") +
    "</tbody></table>";
}

function renderContext(games) {
  funBarChart("chart-ctx-queue", aggregate(games, (g) => g.queue_type));
  funBarChart("chart-ctx-role", aggregate(games, (g) => g.role || "(unknown)"));
  funBarChart("chart-ctx-result", aggregate(games, (g) => g.result), { fixedOrder: ["Win", "Loss", "?"] });
  funBarChart("chart-ctx-duration", aggregate(games, (g) => g.duration_bucket), { fixedOrder: DURATIONS });
  funBarChart("chart-ctx-hour", aggregate(games, (g) => g.daypart), { fixedOrder: DAYPARTS });
  funBarChart("chart-ctx-weekday", aggregate(games, (g) => g.weekday), { fixedOrder: WEEKDAYS });
}

function renderSessions(games) {
  funBarChart("chart-sessions", aggregate(games, (g) => g.session_index), { fixedOrder: ["1", "2", "3", "4", "5+"] });
}

const DIMS = {
  champion: (g) => g.champion_key,
  enemy: (g) => g.enemy_champions,
  augment: (g) => g.augments,
  item: (g) => g.items,
  tag: (g) => g.tags,
  teammate: (g) => g.premades.map((t) => t.name || "?"),
  queue_type: (g) => g.queue_type,
  role: (g) => g.role || "(unknown)",
  result: (g) => g.result,
  weekday: (g) => g.weekday,
  hour: (g) => g.daypart,
  session_index: (g) => g.session_index,
  duration_bucket: (g) => g.duration_bucket,
  month: (g) => g.month,
};
const DIM_ORDERS = { weekday: WEEKDAYS, hour: DAYPARTS, duration_bucket: DURATIONS, session_index: ["1", "2", "3", "4", "5+"], result: ["Win", "Loss", "?"] };

function renderExplorer(games) {
  const dim = document.getElementById("ex-dim").value;
  const type = document.getElementById("ex-type").value;
  const rows = aggregate(games, DIMS[dim]);
  const tableDiv = document.getElementById("explorer-table");
  const wrap = document.getElementById("explorer-wrap");
  if (type === "table") {
    destroyChart("chart-explorer");
    wrap.classList.add("hidden");
    const sorted = rows.slice().sort((a, b) => (b.avgFun ?? 0) - (a.avgFun ?? 0));
    tableDiv.innerHTML = `<table><thead><tr><th>${escapeAttr(dim.replace("_", " "))}</th><th class="num">games</th><th class="num">rated</th><th class="num">avg vibe</th><th class="num">winrate</th></tr></thead><tbody>` +
      sorted.map((r) => `<tr${r.n < MIN_N ? ' class="low-n"' : ""}><td>${escapeAttr(r.key)}</td><td class="num">${r.games}</td><td class="num">${r.n}</td><td class="num">${r.avgFun != null ? r.avgFun.toFixed(2) + " " + EMOJI[Math.round(r.avgFun)] : "—"}${r.n < MIN_N && r.n > 0 ? " ·  n<" + MIN_N : ""}</td><td class="num">${r.winrate != null ? r.winrate.toFixed(0) + "%" : "—"}</td></tr>`).join("") +
      "</tbody></table>";
  } else {
    tableDiv.innerHTML = "";
    wrap.classList.remove("hidden");
    if (type === "scatter") funScatterChart("chart-explorer", rows);
    else funBarChart("chart-explorer", rows, { horizontal: rows.length > 8, fixedOrder: DIM_ORDERS[dim] || null });
  }
}

/* ---------------- settings ---------------- */

async function renderSettings() {
  const msg = document.getElementById("settings-msg");
  const autostart = document.getElementById("set-autostart");
  const paused = document.getElementById("set-paused");
  const closeAction = document.getElementById("set-close-action");
  const tele = document.getElementById("set-telemetry");
  let s;
  try {
    s = await api("/api/settings");
  } catch (e) {
    msg.textContent = "Couldn't load settings: " + e.message;
    return;
  }
  autostart.checked = !!s.autostart;
  autostart.disabled = !s.autostart_supported;
  paused.checked = !!s.paused;
  closeAction.value = s.close_action || "ask";
  tele.checked = !!s.telemetry;

  const save = async (body, label) => {
    try {
      const r = await api("/api/settings", body);
      autostart.checked = !!r.autostart;
      paused.checked = !!r.paused;
      closeAction.value = r.close_action || "ask";
      tele.checked = !!r.telemetry;
      msg.textContent = label;
    } catch (e) {
      msg.textContent = "Couldn't save: " + e.message;
    }
  };
  tele.onchange = () =>
    save({ telemetry: tele.checked }, tele.checked ? "Usage stats on. Thanks!" : "Usage stats off.");
  autostart.onchange = () =>
    save({ autostart: autostart.checked }, autostart.checked ? "Will start with Windows." : "Won't start with Windows.");
  paused.onchange = () =>
    save({ paused: paused.checked }, paused.checked ? "Rating popups paused." : "Rating popups on.");
  const CLOSE_LABELS = { ask: "Will ask when you close the window.", minimize: "Closing minimizes to the tray.", quit: "Closing quits the app." };
  closeAction.onchange = () => save({ close_action: closeAction.value }, CLOSE_LABELS[closeAction.value]);
}

/* ---------------- profile menu (settings / update / uninstall) ---------------- */

function toggleProfileMenu(forceOpen) {
  const menu = document.getElementById("profile-menu");
  const open = forceOpen ?? menu.classList.contains("hidden");
  menu.classList.toggle("hidden", !open);
  document.getElementById("profile-btn").setAttribute("aria-expanded", open);
  document.getElementById("settings-btn").setAttribute("aria-expanded", open);
  if (open) { renderSettings(); checkUpdate(); }
}

async function loadProfile() {
  try {
    const s = await api("/api/settings");
    const name = s.summoner_name || "Summoner";
    document.getElementById("profile-name").textContent = name;
    document.getElementById("pm-name").textContent = name;
    renderFeedbackLinks(s);
  } catch { /* offline — keep the default label */ }
}

let UPDATE = null; // last /api/update result

/* Once-per-update "here's what changed" note. Deliberately tiny: a few plain
   sentences and one button — nobody opened VibeCheck to read a changelog. */
async function showWhatsNew() {
  try {
    const w = await api("/api/whats-new");
    if (!w.show || !w.notes.length) return;
    document.getElementById("whatsnew-version").textContent = `You're now on v${w.version}`;
    document.getElementById("whatsnew-list").innerHTML =
      w.notes.map((n) => `<li>${escapeAttr(n)}</li>`).join("");
    const modal = document.getElementById("whatsnew");
    modal.classList.remove("hidden");
    const dismiss = async () => {
      modal.classList.add("hidden");
      try { await api("/api/whats-new/seen", {}); } catch { /* shows again next launch */ }
    };
    document.getElementById("whatsnew-ok").addEventListener("click", dismiss);
    // Clicking the backdrop (but not the card) counts as "got it" too.
    modal.addEventListener("click", (e) => { if (e.target === modal) dismiss(); });
  } catch { /* offline — nothing to announce */ }
}

/* The links are served by the app rather than hardcoded here, so the form URL
   (and its version pre-fill) can be configured in one place. A link that isn't
   configured yet is hidden rather than shown broken. */
function renderFeedbackLinks(s) {
  const discord = document.getElementById("pm-discord");
  const feedback = document.getElementById("pm-feedback");
  discord.classList.toggle("hidden", !s.discord_url);
  if (s.discord_url) discord.href = s.discord_url;
  feedback.classList.toggle("hidden", !s.feedback_url);
  if (s.feedback_url) feedback.href = s.feedback_url;
}

async function checkUpdate() {
  const body = document.getElementById("update-body");
  const btn = document.getElementById("pm-update-btn");
  try {
    const u = await api("/api/update");
    UPDATE = u;
    renderNotifVersion();
    if (!u.update_available) {
      body.innerHTML = `You're on <b>v${escapeAttr(u.current)}</b> — up to date. 🎉`;
      btn.classList.add("hidden");
      return;
    }
    body.innerHTML =
      `New version <b>v${escapeAttr(u.latest)}</b> is out (you're on v${escapeAttr(u.current)}).`;
    if (u.can_self_update) {
      // One click: download, verify, swap, relaunch — no trip to GitHub.
      btn.classList.remove("hidden");
    } else {
      // Running from source, or a release with no published checksum: we can't
      // safely replace the binary, so fall back to the manual download.
      btn.classList.add("hidden");
      body.innerHTML +=
        ` <a class="pm-update-cta primary-btn" href="${escapeAttr(u.url)}" target="_blank" rel="noopener">Download</a>`;
    }
    if (u.job && u.job.state !== "idle") followUpdate();
  } catch {
    body.textContent = "Couldn't check for updates right now.";
  }
}

/* Passive "Status" line in the notification drawer, mirroring the same
   /api/update read the profile menu's Version section already does —
   independent read, same pattern as renderSyncStatus() above it, so the
   drawer has something to show without the user ever opening the profile
   menu first. */
function renderNotifVersion() {
  const el = document.getElementById("notif-version");
  if (!UPDATE) { el.textContent = ""; return; }
  el.innerHTML = UPDATE.update_available
    ? `<span class="notif-sync-dot is-update"></span> v${escapeAttr(UPDATE.current)} — update available`
    : `<span class="notif-sync-dot is-synced"></span> v${escapeAttr(UPDATE.current)} — up to date`;
}

const UPDATE_STATES = {
  downloading: (p) => `Downloading… ${p}%`,
  applying: () => "Installing the update…",
  restarting: () => "Restarting VibeCheck… this window will reconnect on its own.",
};

async function startUpdate() {
  const btn = document.getElementById("pm-update-btn");
  const msg = document.getElementById("update-msg");
  btn.disabled = true;
  msg.textContent = "";
  try {
    await api("/api/update/install", {});
    followUpdate();
  } catch (e) {
    btn.disabled = false;
    msg.innerHTML =
      `Couldn't install the update: ${escapeAttr(e.message)}. ` +
      `<a href="${escapeAttr((UPDATE && UPDATE.url) || "")}" target="_blank" rel="noopener">Download it manually</a>.`;
  }
}

function followUpdate() {
  const btn = document.getElementById("pm-update-btn");
  const body = document.getElementById("update-body");
  const wrap = document.getElementById("update-progress");
  const bar = document.getElementById("update-bar");
  const msg = document.getElementById("update-msg");
  btn.classList.add("hidden");
  wrap.classList.remove("hidden");
  clearInterval(window.__updatePoll);
  window.__updatePoll = setInterval(async () => {
    let job;
    try {
      job = await api("/api/update/progress");
    } catch {
      // The app is restarting — losing the connection here is the expected,
      // successful end of the process, not an error to report.
      return;
    }
    if (job.state === "error") {
      clearInterval(window.__updatePoll);
      wrap.classList.add("hidden");
      btn.classList.remove("hidden");
      btn.disabled = false;
      msg.innerHTML =
        `Update failed: ${escapeAttr(job.error || "unknown error")}. ` +
        `<a href="${escapeAttr((UPDATE && UPDATE.url) || "")}" target="_blank" rel="noopener">Download it manually</a>.`;
      return;
    }
    const label = UPDATE_STATES[job.state];
    if (label) body.textContent = label(job.percent || 0);
    bar.style.width = `${job.percent || 0}%`;
    if (job.state === "restarting") clearInterval(window.__updatePoll);
  }, 500);
}

/* Startup check: a dot on the profile button plus a banner, so an available
   update is visible without opening the menu. Dismissal is per-version, so the
   next release speaks up again. */
async function updateBadge() {
  try {
    const u = await api("/api/update");
    UPDATE = u;
    renderNotifVersion();
    if (!u.update_available) return;
    document.getElementById("profile-dot").classList.remove("hidden");
    if (localStorage.getItem("dismissedUpdate") === u.latest) return;
    const b = document.getElementById("update-banner");
    b.innerHTML =
      `✨ VibeCheck <b>v${escapeAttr(u.latest)}</b> is out — you're on v${escapeAttr(u.current)}. ` +
      `<button class="link-btn" id="update-banner-open">${u.can_self_update ? "Update now" : "Get it"}</button>` +
      `<button class="link-btn dim" id="update-banner-hide">Not now</button>`;
    b.classList.remove("hidden");
    document.getElementById("update-banner-open").addEventListener("click", () => {
      b.classList.add("hidden");
      toggleProfileMenu(true);
      if (u.can_self_update) startUpdate();
      else window.open(u.url, "_blank", "noopener");
    });
    document.getElementById("update-banner-hide").addEventListener("click", () => {
      localStorage.setItem("dismissedUpdate", u.latest);
      b.classList.add("hidden");
    });
  } catch { /* offline — no badge, no nagging */ }
}

async function doUninstall() {
  const msg = document.getElementById("uninstall-msg");
  if (!confirm("Uninstall VibeCheck?\n\nThis turns off start-with-Windows. You'll then quit from the tray and delete the app yourself.")) return;
  try {
    const r = await api("/api/uninstall", {});
    msg.innerHTML =
      `Removed from Windows startup. To finish: quit from the tray (right-click → Quit), delete ` +
      `<b>VibeCheck.exe</b>, and — if you want your history gone too — delete <code>${escapeAttr(r.data_dir)}</code>.`;
  } catch (e) {
    msg.textContent = "Couldn't complete uninstall: " + e.message;
  }
}

/* ---------------- squad online (§12) ---------------- */

let SQUAD = { status: null };

/* The `body` argument is what selects the method: omit it and this sends a GET.
   Pass `{}` to POST with no payload — every bodyless write endpoint needs that,
   and forgetting it is not a loud failure, it's a 405 surfaced as "Method Not
   Allowed" in a corner of the UI. That is exactly how the Sync now button shipped
   broken. */
async function api(path, body) {
  const res = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "request failed");
  return data;
}

/* Status line inside the notification drawer's "Status" section. Reuses the
   same /api/squad/status the Squad tab's renderOnline() calls — this is just
   a second, independent read of it on load so the drawer has something to
   show before the user ever opens that tab. Unlike the header pill this
   replaced, every state gets a line here rather than hiding — a "Status"
   section that's sometimes just blank would look broken, and the drawer is
   opened deliberately rather than sitting always-visible. */
async function renderSyncStatus() {
  const el = document.getElementById("notif-sync");
  let st;
  try {
    st = SQUAD.status = await api("/api/squad/status");
  } catch {
    el.innerHTML = `<span class="notif-sync-dot is-error"></span> Couldn't reach the backend`;
    return;
  }
  if (!st.configured) {
    el.innerHTML = `<span class="notif-sync-dot"></span> Squad Sync not configured`;
    return;
  }
  if (!st.identity_ready) {
    el.innerHTML = `<span class="notif-sync-dot"></span> Waiting for the League client…`;
    return;
  }
  if (st.error) {
    el.innerHTML = `<span class="notif-sync-dot is-error"></span> Squad Sync error`;
    return;
  }
  const mutual = st.mutual_count || 0;
  el.innerHTML = `<span class="notif-sync-dot is-synced"></span> Squad Sync active — ${mutual} friend${mutual === 1 ? "" : "s"} synced`;
}

async function renderOnline() {
  const body = document.getElementById("squad-body");
  document.getElementById("squad-board-panel").classList.add("hidden");
  document.getElementById("squad-matrix-panel").classList.add("hidden");
  let st;
  try {
    st = SQUAD.status = await api("/api/squad/status");
  } catch (e) {
    body.innerHTML = `<div class="empty-note">Couldn't reach the backend: ${escapeAttr(e.message)}</div>`;
    return;
  }

  // Advanced / self-host: no backend bundled into this build.
  if (!st.configured) {
    body.innerHTML = `
      <p class="squad-help"><b>Advanced / self-host setup.</b> Released builds already point at
        the shared backend, so this normally just works with nothing to fill in. You're seeing
        this because this build has no bundled backend (a source checkout, or your own project).<br><br>
        Create a free project at <b>supabase.com</b>, run <code>supabase/schema.sql</code> in its
        SQL editor, enable anonymous sign-ins, then paste the project URL and <b>publishable</b>
        key below (Project Settings → API). Never paste the secret / service_role key.</p>
      <div class="squad-form">
        <input id="sb-url" placeholder="https://xxxx.supabase.co">
        <input id="sb-key" placeholder="publishable / anon key">
        <button class="primary-btn" id="sb-save">Save</button>
      </div>
      <div id="sb-msg" class="squad-msg"></div>`;
    document.getElementById("sb-save").addEventListener("click", async (e) => {
      const ok = await guard(e.target, () => api("/api/squad/config", {
        url: document.getElementById("sb-url").value.trim(),
        anon_key: document.getElementById("sb-key").value.trim(),
      }));
      if (ok) renderOnline();
    });
    return;
  }

  // We need the player's in-game identity, which comes from the League client.
  if (!st.identity_ready) {
    body.innerHTML = `
      <p class="squad-help">Start the League client once while VibeCheck is running — that's how
        we learn your in-game identity and your friends list. Squad Sync then turns on
        automatically. No account, no invite codes.</p>
      ${st.error ? `<div class="squad-err">${escapeAttr(st.error)}</div>` : ""}`;
    return;
  }

  const friends = st.friend_count || 0;
  const mutual = st.mutual_count || 0;
  body.innerHTML = `
    <p class="squad-help">Your squad is simply your League friends who also run VibeCheck. Everyone
      syncs automatically — the moment a friend installs it and has you friended back, they show up
      here. Nothing to set up.</p>
    <div class="squad-bar">
      <span>Synced as <b>${escapeAttr(st.display_name || "Summoner")}</b></span>
      <span>· ${friends} League friend${friends === 1 ? "" : "s"}</span>
      <span>· <b>${mutual}</b> also on VibeCheck</span>
      <button class="ghost-btn" id="sb-sync">Sync now</button>
    </div>
    ${st.error ? `<div class="squad-err">${escapeAttr(st.error)}</div>` : ""}
    <div id="sb-msg" class="squad-msg"></div>`;

  document.getElementById("sb-sync").addEventListener("click", async (e) => {
    const r = await guard(e.target, () => api("/api/squad/push", {}));
    if (r) {
      const m = document.getElementById("sb-msg");
      if (m) m.textContent = `Synced ${r.synced} rated games.`;
      renderSquadStats();
    }
  });

  renderSquadStats();
}

async function guard(btn, fn) {
  const old = btn.textContent;
  btn.disabled = true; btn.textContent = "…";
  try {
    return await fn();
  } catch (e) {
    const m = document.getElementById("sb-msg");
    if (m) m.textContent = e.message; else alert(e.message);
    return null;
  } finally {
    btn.disabled = false; btn.textContent = old;
  }
}

async function renderSquadStats() {
  const boardPanel = document.getElementById("squad-board-panel");
  const matrixPanel = document.getElementById("squad-matrix-panel");
  let data;
  try {
    data = await api("/api/squad/data");
  } catch {
    return;
  }
  const names = data.players || {};
  const games = data.games || [];
  if (!games.length) return;
  boardPanel.classList.remove("hidden");
  matrixPanel.classList.remove("hidden");

  // leaderboard: average fun per player (keyed on puuid)
  const per = {};
  for (const g of games) {
    const a = (per[g.puuid] ||= { sum: 0, n: 0 });
    a.sum += g.fun_score; a.n += 1;
  }
  const rows = Object.entries(per).map(([id, a]) => ({
    key: names[id] || "Summoner", n: a.n, games: a.n, avgFun: a.sum / a.n, winrate: null,
  }));
  funBarChart("chart-squad-board", rows, { horizontal: true });

  // mutual vibes: games two players both played, matched on riot_match_id
  const byMatch = {};
  for (const g of games) (byMatch[g.riot_match_id] ||= []).push(g);
  const pairs = {};
  for (const group of Object.values(byMatch)) {
    if (group.length < 2) continue;
    for (let i = 0; i < group.length; i++)
      for (let j = i + 1; j < group.length; j++) {
        const [a, b] = [group[i], group[j]];
        const key = [a.puuid, b.puuid].sort().join("|");
        const p = (pairs[key] ||= { a: a.puuid, b: b.puuid, sa: 0, sb: 0, n: 0 });
        const flip = p.a !== a.puuid;
        p.sa += flip ? b.fun_score : a.fun_score;
        p.sb += flip ? a.fun_score : b.fun_score;
        p.n += 1;
      }
  }
  const list = Object.values(pairs).sort((x, y) => y.n - x.n);
  document.getElementById("squad-matrix").innerHTML = list.length
    ? `<table><thead><tr><th>Pair</th><th class="num">shared games</th><th class="num">their vibe</th><th class="num">vs</th><th class="num">their vibe</th></tr></thead><tbody>` +
      list.map((p) => `<tr${p.n < MIN_N ? ' class="low-n"' : ""}>
        <td>${escapeAttr(names[p.a] || "?")} &amp; ${escapeAttr(names[p.b] || "?")}</td>
        <td class="num">${p.n}</td>
        <td class="num">${(p.sa / p.n).toFixed(2)} ${EMOJI[Math.round(p.sa / p.n)]}</td>
        <td class="num">·</td>
        <td class="num">${(p.sb / p.n).toFixed(2)} ${EMOJI[Math.round(p.sb / p.n)]}</td></tr>`).join("") +
      "</tbody></table>"
    : '<div class="empty-note">No games played together yet — once two of you rate the same game, it shows up here.</div>';
}

/* ---------------- tags & notes ---------------- */

function tagEditorHTML(g) {
  const chips = ALL_TAGS.map(
    (t) => `<button class="chip${g.tags.includes(t) ? " on" : ""}" data-tag="${escapeAttr(t)}">${escapeAttr(t)}</button>`,
  ).join("");
  return `<div class="tag-editor" data-id="${g.id}">
      <div class="chips">${chips}<input class="tag-add" placeholder="+ tag" maxlength="24"></div>
      <input class="note" placeholder="note to self…" value="${escapeAttr(g.note)}" maxlength="500">
    </div>`;
}

async function postTags(id, tags) {
  // The chip/row UI already reflects the change (classList.toggle below), so no
  // re-render here — that would rebuild the DOM mid-edit and drop focus/typing
  // in this or any other open tag-editor. The aggregate tag chart catches up on
  // the next data_rev poll.
  const game = ALL.find((g) => g.id === Number(id));
  if (game) game.tags = tags;
  await fetch(`/api/games/${id}/tags`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags }),
  });
}

// Re-sync list views once the user is done editing a tag/note field, so a
// change made elsewhere (e.g. a game finishing) that arrived while they were
// typing gets picked up instead of staying stale indefinitely.
function scheduleCatchUpRender() {
  setTimeout(renderAll, 0);
}

function wireTagEditors(root) {
  root.querySelectorAll(".tag-editor").forEach((ed) => {
    const id = ed.dataset.id;
    const activeTags = () => [...ed.querySelectorAll(".chip.on")].map((c) => c.dataset.tag);
    ed.querySelectorAll(".chip").forEach((c) => {
      c.addEventListener("click", () => { c.classList.toggle("on"); postTags(id, activeTags()); });
      // A clicked chip keeps focus, which suppresses re-renders for this list;
      // catch up once focus leaves so the tag chart isn't left stale.
      c.addEventListener("blur", scheduleCatchUpRender);
    });
    const add = ed.querySelector(".tag-add");
    add.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && add.value.trim()) { postTags(id, [...activeTags(), add.value.trim()]); add.value = ""; }
    });
    add.addEventListener("blur", scheduleCatchUpRender);
    const note = ed.querySelector(".note");
    note.addEventListener("change", () => {
      const game = ALL.find((g) => g.id === Number(id));
      if (game) game.note = note.value;
      fetch(`/api/games/${id}/note`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note.value }),
      });
    });
    note.addEventListener("blur", scheduleCatchUpRender);
  });
}

function renderTags(games) {
  funBarChart("chart-tags", aggregate(games, (g) => g.tags), { horizontal: true });
  const list = games.slice().sort((a, b) => b.date - a.date);
  const host = document.getElementById("tags-games");
  host.innerHTML = list.length
    ? list.map((g) => `
        <div class="tag-row">
          <div class="tag-meta">${champIcon(g.champion, g.classic)}<b>${escapeAttr(g.champion_key || "?")}</b> · ${escapeAttr(g.result)} · ${escapeAttr(g.queue_type || "?")}
            <span class="when">${escapeAttr(g.day)}</span> ${g.rated ? EMOJI[g.fun_score] : ""}</div>
          ${tagEditorHTML(g)}
        </div>`).join("")
    : '<div class="empty-note">No games match this filter.</div>';
  wireTagEditors(host);
}

function renderPending() {
  const pending = ALL.filter((g) => g.pending).sort((a, b) => b.date - a.date);
  const badge = document.getElementById("pending-badge");
  if (pending.length) { badge.textContent = pending.length; badge.classList.remove("hidden"); }
  else badge.classList.add("hidden");
  // Notification drawer's "Action required" section — same count, so it can
  // never drift from the bell's own badge.
  const row = document.getElementById("notif-pending-row");
  const empty = document.getElementById("notif-pending-empty");
  row.classList.toggle("hidden", !pending.length);
  empty.classList.toggle("hidden", !!pending.length);
  if (pending.length) {
    document.getElementById("notif-pending-text").textContent =
      `${pending.length} game${pending.length === 1 ? "" : "s"} pending rating`;
  }
  const list = document.getElementById("pending-list");
  if (!pending.length) { list.innerHTML = '<div class="empty-note">All caught up — not a single un-vibed game. Certified responsible adult. 🏆</div>'; return; }
  list.innerHTML = pending.map((g) => `
    <div class="pending-row" data-id="${g.id}">
      <div class="meta">
        <div>${champIcon(g.champion, g.classic)}<b>${escapeAttr(g.champion_key || "?")}</b> · ${escapeAttr(g.result)} · ${g.kills ?? "?"}/${g.deaths ?? "?"}/${g.assists ?? "?"} · ${escapeAttr(g.queue_type || "?")}</div>
        <div class="when">${escapeAttr(g.played_at.replace("T", " "))} · ${Math.round((g.duration_seconds || 0) / 60)} min${g.premades.length ? " · with " + escapeAttr(g.premades.map((t) => t.name).join(", ")) : ""}</div>
      </div>
      <div class="rate-btns">
        ${[1, 2, 3, 4, 5].map((s) => `<button data-score="${s}" title="${escapeAttr(GRADES[s])}">${EMOJI[s]}</button>`).join("")}
        <button class="skip" data-skip="1" title="exclude from stats">skip</button>
      </div>
      <div style="flex-basis:100%">${tagEditorHTML(g)}</div>
    </div>`).join("");
  list.querySelectorAll(".rate-btns button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.closest(".pending-row").dataset.id);
      const game = ALL.find((g) => g.id === id);
      if (!game) return;
      const skipped = !!btn.dataset.skip;
      const score = skipped ? null : Number(btn.dataset.score);
      const prev = { fun_score: game.fun_score, skipped: game.skipped, rated: game.rated, pending: game.pending };
      // Optimistic: reflect the rating immediately so the row leaves To Rate
      // right away instead of waiting on the next poll tick.
      game.fun_score = score;
      game.skipped = skipped;
      game.rated = game.fun_score != null && !game.skipped;
      game.pending = game.fun_score == null && !game.skipped && !game.is_remake;
      renderAll();
      try {
        const r = await fetch(`/api/games/${id}/rating`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(skipped ? { skipped: true } : { score }),
        });
        if (!r.ok) throw new Error(`save failed (${r.status})`);
        const { rev } = await r.json();
        // Adopt the server's new rev so the next poll sees "nothing changed"
        // instead of re-fetching and re-rendering everything a second time.
        // Only when it's exactly one ahead, though: anything else means another
        // write landed too (e.g. the popup rated a game), and that one still
        // needs fetching — so leave lastRev alone and let the poll catch it.
        if (rev === lastRev + 1) lastRev = rev;
      } catch (e) {
        Object.assign(game, prev);
        renderAll();
        alert("Couldn't save that rating — try again.\n" + e.message);
      }
    });
  });
  wireTagEditors(list);
}

/* ---------------- filters UI ---------------- */

function buildMultiselect(containerId, label, options, set, onChange) {
  const host = document.getElementById(containerId);
  host.innerHTML = "";
  const div = document.createElement("div");
  div.className = "msel";
  const btn = document.createElement("button");
  btn.className = "msel-btn";
  const panel = document.createElement("div");
  panel.className = "msel-panel hidden";
  const sync = () => {
    btn.textContent = set.size ? `${label}: ${set.size} selected` : `All ${label.toLowerCase()}s`;
    btn.classList.toggle("has-selection", set.size > 0);
  };
  for (const opt of options) {
    const row = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = set.has(opt.value);
    cb.addEventListener("change", () => {
      cb.checked ? set.add(opt.value) : set.delete(opt.value);
      sync(); onChange();
    });
    row.append(cb, document.createTextNode(" " + opt.label));
    panel.append(row);
  }
  btn.addEventListener("click", (e) => { e.stopPropagation(); document.querySelectorAll(".msel-panel").forEach((p) => p !== panel && p.classList.add("hidden")); panel.classList.toggle("hidden"); });
  document.addEventListener("click", (e) => { if (!div.contains(e.target)) panel.classList.add("hidden"); });
  sync();
  div.append(btn, panel);
  host.append(div);
}

function buildFilters() {
  const uniq = (fn) => [...new Set(ALL.map(fn).flat().filter(Boolean))].sort();
  buildMultiselect("f-queue", "Queue", uniq((g) => g.queue_type).map((v) => ({ value: v, label: v })), state.sets.queue, renderAll);
  buildMultiselect("f-mode", "Mode", uniq((g) => g.mode_family).map((v) => ({ value: v, label: v })), state.sets.mode, renderAll);
  buildMultiselect("f-champion", "Champion", uniq((g) => g.champion_key).map((v) => ({ value: v, label: v })), state.sets.champion, renderAll);
  buildMultiselect("f-role", "Role", uniq((g) => g.role || "(unknown)").map((v) => ({ value: v, label: v })), state.sets.role, renderAll);
  const mates = new Map();
  for (const g of ALL) for (const t of g.premades) mates.set(t.puuid, t.name || "(unknown)");
  buildMultiselect("f-teammate", "Teammate", [...mates].map(([p, n]) => ({ value: p, label: n })), state.sets.teammate, renderAll);
  buildMultiselect("f-result", "Result", ["Win", "Loss"].map((v) => ({ value: v, label: v })), state.sets.result, renderAll);
  document.getElementById("f-from").addEventListener("change", (e) => { state.from = e.target.value || null; renderAll(); });
  document.getElementById("f-to").addEventListener("change", (e) => { state.to = e.target.value || null; renderAll(); });
  document.getElementById("f-clear").addEventListener("click", () => {
    state.from = state.to = null;
    document.getElementById("f-from").value = document.getElementById("f-to").value = "";
    Object.values(state.sets).forEach((s) => s.clear());
    buildFilters(); renderAll();
  });
}

/* ---------------- shell ---------------- */

// True while the user has an active edit (a tag-add or note field) focused
// inside the given list container — used to skip rebuilding that list's DOM
// out from under them when a background change triggers a re-render.
function isEditingWithin(containerId) {
  const el = document.activeElement;
  return !!(el && el.closest && el.closest(`#${containerId} .tag-editor`));
}

function renderAll() {
  const games = filtered();
  // Baseline excludes remakes (F5) same as filtered() does — remakes are a
  // permanent exclusion, not a user filter, so they must not make this text
  // appear when no filter chip or date range is actually selected.
  const baseline = ALL.filter((g) => !g.is_remake).length;
  document.getElementById("f-count").textContent =
    games.length === baseline ? "" : `${games.length} of ${baseline} games match`;
  renderHeader(games);
  if (!isEditingWithin("pending-list")) renderPending();
  const t = state.tab;
  if (t === "overview") renderOverview(games);
  if (t === "champions") renderChampions(games);
  if (t === "squad") { renderSquad(games); renderOnline(); } // local squad + online gang
  // "Patterns & Tags" folds the old Context, Sessions and Tags tabs into one page.
  if (t === "patterns") {
    renderContext(games); renderExplorer(games); // canned + free explore
    renderSessions(games);
    if (!isEditingWithin("tags-games")) renderTags(games);
  }
}

async function refresh() {
  await loadData();
  ARAM_GOD = null; // a new game may have completed a champion — refetch it too
  ARAM_GOD_DRAWN = null;
  ARENA_GOD = null;
  ARENA_GOD_DRAWN = null;
  document.getElementById("offline-banner").classList.add("hidden");
  buildFilters();
  renderAll();
}

// Poll a cheap revision counter instead of blindly refetching everything on a
// timer — that used to cause a visible flash every 60s (every chart destroyed
// and rebuilt, every list re-rendered) whether or not anything had actually
// changed, and left freshly-rated games sitting in "To Rate" until the next
// tick. Now: idle page = zero re-renders; a real change (a game captured, a
// rating saved anywhere, including the desktop popup) shows up within ~3s.
async function pollRev() {
  try {
    const { rev } = await fetchJSON("/api/rev");
    if (rev !== lastRev) {
      // Only record the rev once the data behind it is actually on screen —
      // otherwise a refresh that fails half-way would leave us believing we're
      // up to date and we'd never retry.
      await refresh();
      lastRev = rev;
    }
    document.getElementById("offline-banner").classList.add("hidden");
  } catch (e) {
    // Graceful offline state: the tray app (our local API) isn't reachable.
    // Keep the last-rendered data on screen and keep polling — it self-heals
    // when the app comes back, with no need for a separate retry timer.
    const b = document.getElementById("offline-banner");
    b.textContent =
      "⚠ Can't reach VibeCheck on this PC — is the tray app still running? Retrying…";
    b.classList.remove("hidden");
  }
}

// Shared by the nav rail buttons and the notification drawer's pending-games
// row — "pending" has no rail entry (it's reached from the drawer instead),
// so switching to it leaves every rail button unhighlighted, which is expected.
function switchTab(tabId) {
  document.querySelectorAll("#tabs button[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabId));
  state.tab = tabId;
  document.querySelectorAll(".tab").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`tab-${tabId}`).classList.remove("hidden");
  const activeBtn = document.querySelector(`#tabs button[data-tab="${tabId}"]`);
  if (activeBtn) document.getElementById("page-title").textContent = activeBtn.querySelector(".nav-label").textContent;
  else if (tabId === "pending") document.getElementById("page-title").textContent = "Games left on read";
  renderAll();
}
document.querySelectorAll("#tabs button[data-tab]").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// Notification drawer: open/close, outside-click to dismiss (same pattern as
// the profile menu and filters popover), and its one action — jump to To Rate.
document.getElementById("notif-bell").addEventListener("click", (e) => {
  e.stopPropagation();
  document.getElementById("notif-panel").classList.toggle("hidden");
});
document.addEventListener("click", (e) => {
  const panel = document.getElementById("notif-panel");
  if (!panel.classList.contains("hidden") && !e.target.closest(".notif")) panel.classList.add("hidden");
});
document.getElementById("notif-pending-row").addEventListener("click", () => {
  document.getElementById("notif-panel").classList.add("hidden");
  switchTab("pending");
});

// Filters popover: open/close, outside-click to dismiss (same pattern as the
// profile menu below).
document.getElementById("filters-toggle").addEventListener("click", (e) => {
  e.stopPropagation();
  document.getElementById("filters-panel").classList.toggle("hidden");
});
document.addEventListener("click", (e) => {
  const panel = document.getElementById("filters-panel");
  if (!panel.classList.contains("hidden") && !e.target.closest(".filters")) panel.classList.add("hidden");
});

// Sidebar: manual collapse persisted per-device, defaulting to collapsed
// near the 900px window minimum so the rail doesn't crowd content. Toggles
// two elements in lockstep: #sidebar (its own width) and .app-content
// (its margin-left offset) — see the CSS comment on .app-content.nav-collapsed.
(function initNavRail() {
  const sidebar = document.getElementById("sidebar");
  const content = document.querySelector(".app-content");
  const stored = localStorage.getItem("navCollapsed");
  const collapsed = stored === null ? window.innerWidth < 1000 : stored === "1";
  sidebar.classList.toggle("collapsed", collapsed);
  content.classList.toggle("nav-collapsed", collapsed);
  document.getElementById("nav-collapse-toggle").addEventListener("click", () => {
    const next = !sidebar.classList.contains("collapsed");
    sidebar.classList.toggle("collapsed", next);
    content.classList.toggle("nav-collapsed", next);
    localStorage.setItem("navCollapsed", next ? "1" : "0");
  });
})();
document.getElementById("ex-dim").addEventListener("change", renderAll);
document.getElementById("ex-type").addEventListener("change", renderAll);

// Profile menu (sidebar bottom): open/close, outside-click to dismiss, uninstall.
document.getElementById("profile-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  toggleProfileMenu();
});
document.addEventListener("click", (e) => {
  const menu = document.getElementById("profile-menu");
  if (!menu.classList.contains("hidden") && !e.target.closest(".profile")) menu.classList.add("hidden");
});

// Settings (sidebar bottom): opens the same profile-menu popover the
// Profile row does — one panel, two entry points, since Settings already
// lives inside it (pm-section "Settings") rather than needing its own.
document.getElementById("settings-btn").addEventListener("click", (e) => {
  e.stopPropagation(); // must match #profile-btn's own handler — without this,
                        // the document-level outside-click dismiss (below,
                        // checks .closest(".profile")) would immediately
                        // close the menu this same click just opened, since
                        // #settings-btn sits outside the .profile wrapper.
  toggleProfileMenu();
});

// Vibe trend filter menu: unlike the profile menu above, #ov-trend-filter-menu
// is rebuilt by renderVibeTrend on every render (not a static element), so this
// listener is registered exactly ONCE here rather than inside renderVibeTrend —
// doing it there would register a new document-level listener on every render.
document.addEventListener("click", (e) => {
  const menu = document.getElementById("ov-trend-filter-menu");
  if (menu && !menu.classList.contains("hidden") && !e.target.closest(".ov-trend-filter")) menu.classList.add("hidden");
});
document.getElementById("pm-uninstall").addEventListener("click", doUninstall);
document.getElementById("pm-update-btn").addEventListener("click", startUpdate);

/* Deep link from the tray's "Update to vX.Y.Z": open the profile menu straight
   onto the update instead of making the user hunt for it. The flag is dropped
   from the URL so a refresh doesn't reopen the menu. */
function handleUpdateDeepLink() {
  if (new URLSearchParams(location.search).get("update") !== "1") return;
  history.replaceState(null, "", location.pathname);
  toggleProfileMenu(true);
}

/* One-time welcome. A fresh install lands on empty charts with the next game
   half an hour away, which is a poor reason to close the app and not return —
   so the last few games are backfilled and offered for rating here.
   Deliberately not the F7 popup: five popups at a first-time user would be the
   opposite of a welcome. Always skippable; skipping leaves the games in To Rate,
   which is where they'd be anyway. */
async function showOnboarding() {
  let data;
  try {
    data = await api("/api/onboarding");
  } catch { return; }
  if (!data.show || !data.games.length) return;

  const host = document.getElementById("onboarding-list");
  const total = data.games.length;
  let done = 0;

  const progress = () => {
    document.getElementById("onboarding-progress").textContent =
      done ? `${done} of ${total} rated` : `${total} game${total === 1 ? "" : "s"} to rate`;
  };

  host.innerHTML = data.games.map((g) => {
    const kda = [g.kills, g.deaths, g.assists].every((v) => v != null)
      ? `${g.kills}/${g.deaths}/${g.assists}` : "";
    const result = g.win === 1 ? "Win" : g.win === 0 ? "Loss" : "";
    // Champion, result and KDA up front: these games are days old, and the
    // details are what jogs the memory of how one actually felt.
    const meta = [result, kda, g.queue_type, (g.played_at || "").slice(0, 10)]
      .filter(Boolean).map(escapeAttr).join(" · ");
    return `
      <div class="onboarding-row" data-id="${g.id}">
        ${champIcon(g.champion, g.classic)}
        <div class="onboarding-meta">
          <div class="onboarding-champ">${escapeAttr(g.champion || "Unknown")}</div>
          <div class="onboarding-sub">${meta}</div>
        </div>
        <div class="onboarding-scores">
          ${[1, 2, 3, 4, 5].map((s) =>
            `<button data-score="${s}" title="${escapeAttr(GRADES[s])}">${EMOJI[s]}</button>`).join("")}
        </div>
      </div>`;
  }).join("");
  progress();

  host.querySelectorAll(".onboarding-row").forEach((row) => {
    row.querySelectorAll("button[data-score]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(row.dataset.id);
        const score = Number(btn.dataset.score);
        row.querySelectorAll("button").forEach((b) => b.classList.remove("chosen"));
        btn.classList.add("chosen");
        if (!row.classList.contains("rated")) { row.classList.add("rated"); done += 1; progress(); }
        try {
          await api(`/api/games/${id}/rating`, { score });
        } catch {
          // Roll back the tick rather than claim a rating that didn't save.
          row.classList.remove("rated"); btn.classList.remove("chosen");
          done -= 1; progress();
          return;
        }
        // Once everything's rated the wizard has done its job; let the user see
        // the dashboard it just filled.
        if (done >= total) setTimeout(closeOnboarding, 550);
      });
    });
  });

  document.getElementById("onboarding-skip").addEventListener("click", closeOnboarding);
  document.getElementById("onboarding").classList.remove("hidden");
}

async function closeOnboarding() {
  document.getElementById("onboarding").classList.add("hidden");
  try { await api("/api/onboarding/seen", {}); } catch { /* it'll retry next launch */ }
  lastRev = null; // force a full refresh so the charts show what was just rated
  refresh();
}

sweepBrokenImages(); // catches assets that failed before this script ran
loadProfile();
updateBadge();
renderSyncStatus();
handleUpdateDeepLink();
showOnboarding();
showWhatsNew();
pollRev(); // initial load — lastRev starts null so this always does a full refresh
setInterval(pollRev, 3000);
