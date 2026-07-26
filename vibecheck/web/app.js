/* VibeCheck.lol dashboard.
   All filtering/aggregation is client-side: the dataset is small (one row per
   game) and this keeps the filter bar + explorer instant (PRD F13b/F13c). */
"use strict";

const MIN_N = 5; // PRD F21: below this, a group is "not enough data yet"
const EMOJI = { 1: "😨", 2: "🤨", 3: "😐", 4: "😎", 5: "👑" };
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
const charts = {}; // canvas id -> Chart instance
const state = {
  tab: "overview",
  from: null,
  to: null,
  sets: { queue: new Set(), champion: new Set(), role: new Set(), teammate: new Set(), result: new Set() },
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

function escapeAttr(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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
    if (s.champion.size && !s.champion.has(g.champion)) return false;
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
        [horizontal ? "x" : "y"]: { min: 1, max: 5, ticks: { callback: (v) => EMOJI[v] || v } },
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

function funScatterChart(id, rows) {
  destroyChart(id);
  rows = rows.filter((r) => r.avgFun != null && r.winrate != null);
  charts[id] = new Chart(document.getElementById(id), {
    type: "scatter",
    data: { datasets: [{
      data: rows.map((r) => ({ x: r.winrate, y: r.avgFun, r })),
      backgroundColor: rows.map((r) => (r.n < MIN_N ? MUTED : GOLD)),
      pointRadius: rows.map((r) => Math.min(4 + r.n, 14)),
      pointHoverRadius: rows.map((r) => Math.min(6 + r.n, 16)),
    }] },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: { min: 0, max: 100, title: { display: true, text: "winrate %" } },
        y: { min: 1, max: 5, title: { display: true, text: "avg vibe" }, ticks: { callback: (v) => EMOJI[v] || v } },
      },
      plugins: { tooltip: { callbacks: {
        label: (c) => {
          const r = c.raw.r;
          const tag = r.n < MIN_N ? " · not enough data yet" : "";
          return ` ${r.key}: vibe ${r.avgFun.toFixed(2)}, winrate ${r.winrate.toFixed(0)}% (${r.n} rated)${tag}`;
        },
      } } },
    },
  });
}

/* ---------------- views ---------------- */

function renderHeader(games) {
  const rated = games.filter((g) => g.rated);
  document.getElementById("header-stats").innerHTML =
    `<b>${games.length}</b> games · <b>${rated.length}</b> rated` +
    (rated.length ? ` · avg vibe <b>${(rated.reduce((s, g) => s + g.fun_score, 0) / rated.length).toFixed(2)}</b>` : "");
  const banner = document.getElementById("low-data-banner");
  const totalRated = ALL.filter((g) => g.rated).length;
  if (totalRated < MIN_N) {
    banner.textContent = `The vibes are still buffering — ${totalRated}/${MIN_N} rated games until the insights unlock. Go feed the machine. 🎮`;
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
}

function card(k, v, d, gold = false) {
  return `<div class="card${gold ? " gold" : ""}"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
}

function renderOverview(games) {
  const rated = games.filter((g) => g.rated);
  const facts = [];
  if (rated.length) {
    const avg = rated.reduce((s, g) => s + g.fun_score, 0) / rated.length;
    facts.push(card("Vibe-o-meter", `${avg.toFixed(2)} <span class="emoji">${EMOJI[Math.round(avg)]}</span>`, `${GRADES[Math.round(avg)]} · ${rated.length} rated games`, true));
  } else {
    facts.push(card("Vibe-o-meter", "—", "no rated games in this filter (rookie numbers)"));
  }
  const champs = aggregate(games, (g) => g.champion).filter((r) => r.avgFun != null);
  const bigChamps = champs.filter((r) => r.n >= MIN_N).sort((a, b) => b.avgFun - a.avgFun);
  facts.push(bigChamps.length
    ? card("Certified banger", `${bigChamps[0].key} ${EMOJI[Math.round(bigChamps[0].avgFun)]}`, `${bigChamps[0].avgFun.toFixed(2)} avg over ${bigChamps[0].n} games — this one's for the soul`, true)
    : card("Certified banger", "…", `not enough data yet (needs ${MIN_N} rated games on one champ)`));
  if (bigChamps.length > 1) {
    const w = bigChamps[bigChamps.length - 1];
    facts.push(card("Certified yikes", `${w.key} ${EMOJI[Math.round(w.avgFun)]}`, `${w.avgFun.toFixed(2)} avg over ${w.n} games — why do you keep doing this`));
  }
  const withP = rated.filter((g) => g.premades.length);
  const solo = rated.filter((g) => !g.premades.length);
  facts.push(withP.length >= MIN_N && solo.length >= MIN_N
    ? card("Squad buff",
        `${(withP.reduce((s, g) => s + g.fun_score, 0) / withP.length).toFixed(2)} vs ${(solo.reduce((s, g) => s + g.fun_score, 0) / solo.length).toFixed(2)}`,
        `with the squad vs. solo queue despair (${withP.length}/${solo.length} games)`, true)
    : card("Squad buff", "…", "not enough data yet (play more with & without the squad)"));
  const cov = games.length ? Math.round((100 * rated.length) / games.filter((g) => !g.is_remake).length) : 0;
  facts.push(card("No games left on read", `${cov}%`, "of games rated — aim for 90%, don't leave games on read"));
  document.getElementById("fun-facts").innerHTML = facts.join("");

  // trend: rolling average (window 5) over rated games in chronological order
  destroyChart("chart-trend");
  const seq = rated.slice().sort((a, b) => a.date - b.date);
  const points = seq.map((g, i) => {
    const win = seq.slice(Math.max(0, i - 4), i + 1);
    return { x: i + 1, y: win.reduce((s, x) => s + x.fun_score, 0) / win.length, g };
  });
  charts["chart-trend"] = new Chart(document.getElementById("chart-trend"), {
    type: "line",
    data: { datasets: [{
      data: points, borderColor: GOLD, borderWidth: 2, pointRadius: 3,
      pointBackgroundColor: GOLD, tension: 0.3, fill: false,
    }] },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: { type: "linear", title: { display: true, text: "rated game #" }, ticks: { stepSize: 1 } },
        y: { min: 1, max: 5, ticks: { callback: (v) => EMOJI[v] || v } },
      },
      plugins: { tooltip: { callbacks: {
        label: (c) => ` ${c.raw.g.champion || "?"} ${EMOJI[c.raw.g.fun_score]} — rolling avg ${c.raw.y.toFixed(2)}`,
        title: (items) => items[0].raw.g.day,
      } } },
    },
  });
}

function renderChampions(games) {
  funBarChart("chart-champ-fun", aggregate(games, (g) => g.champion), { horizontal: true });
  funScatterChart("chart-champ-scatter", aggregate(games, (g) => g.champion));
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
      scales: { x: { min: 1, max: 5, ticks: { callback: (v) => EMOJI[v] || v } }, y: { grid: { display: false } } },
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
  champion: (g) => g.champion,
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
  const wrap = document.querySelector("#tab-explorer .chart-wrap");
  if (type === "table") {
    destroyChart("chart-explorer");
    wrap.classList.add("hidden");
    const sorted = rows.slice().sort((a, b) => (b.avgFun ?? 0) - (a.avgFun ?? 0));
    tableDiv.innerHTML = `<table><thead><tr><th>${dim.replace("_", " ")}</th><th class="num">games</th><th class="num">rated</th><th class="num">avg vibe</th><th class="num">winrate</th></tr></thead><tbody>` +
      sorted.map((r) => `<tr${r.n < MIN_N ? ' class="low-n"' : ""}><td>${r.key}</td><td class="num">${r.games}</td><td class="num">${r.n}</td><td class="num">${r.avgFun != null ? r.avgFun.toFixed(2) + " " + EMOJI[Math.round(r.avgFun)] : "—"}${r.n < MIN_N && r.n > 0 ? " ·  n<" + MIN_N : ""}</td><td class="num">${r.winrate != null ? r.winrate.toFixed(0) + "%" : "—"}</td></tr>`).join("") +
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

  const save = async (body, label) => {
    try {
      const r = await api("/api/settings", body);
      autostart.checked = !!r.autostart;
      paused.checked = !!r.paused;
      closeAction.value = r.close_action || "ask";
      msg.textContent = label;
    } catch (e) {
      msg.textContent = "Couldn't save: " + e.message;
    }
  };
  autostart.onchange = () =>
    save({ autostart: autostart.checked }, autostart.checked ? "Will start with Windows." : "Won't start with Windows.");
  paused.onchange = () =>
    save({ paused: paused.checked }, paused.checked ? "Rating popups paused." : "Rating popups on.");
  const CLOSE_LABELS = { ask: "Will ask when you close the window.", minimize: "Closing minimizes to the tray.", quit: "Closing quits the app." };
  closeAction.onchange = () => save({ close_action: closeAction.value }, CLOSE_LABELS[closeAction.value]);
}

/* ---------------- squad online (§12) ---------------- */

let SQUAD = { status: null };

async function api(path, body) {
  const res = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "request failed");
  return data;
}

async function renderOnline() {
  const body = document.getElementById("squad-body");
  document.getElementById("squad-board-panel").classList.add("hidden");
  document.getElementById("squad-matrix-panel").classList.add("hidden");
  let st;
  try {
    st = SQUAD.status = await api("/api/squad/status");
  } catch (e) {
    body.innerHTML = `<div class="empty-note">Couldn't reach the backend: ${e.message}</div>`;
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
      ${st.error ? `<div class="squad-err">${st.error}</div>` : ""}`;
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
    ${st.error ? `<div class="squad-err">${st.error}</div>` : ""}
    <div id="sb-msg" class="squad-msg"></div>`;

  document.getElementById("sb-sync").addEventListener("click", async (e) => {
    const r = await guard(e.target, () => api("/api/squad/push"));
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
    (t) => `<button class="chip${g.tags.includes(t) ? " on" : ""}" data-tag="${escapeAttr(t)}">${t}</button>`,
  ).join("");
  return `<div class="tag-editor" data-id="${g.id}">
      <div class="chips">${chips}<input class="tag-add" placeholder="+ tag" maxlength="24"></div>
      <input class="note" placeholder="note to self…" value="${escapeAttr(g.note)}" maxlength="500">
    </div>`;
}

async function postTags(id, tags) {
  await fetch(`/api/games/${id}/tags`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags }),
  });
  await refresh();
}

function wireTagEditors(root) {
  root.querySelectorAll(".tag-editor").forEach((ed) => {
    const id = ed.dataset.id;
    const activeTags = () => [...ed.querySelectorAll(".chip.on")].map((c) => c.dataset.tag);
    ed.querySelectorAll(".chip").forEach((c) =>
      c.addEventListener("click", () => { c.classList.toggle("on"); postTags(id, activeTags()); }),
    );
    const add = ed.querySelector(".tag-add");
    add.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && add.value.trim()) postTags(id, [...activeTags(), add.value.trim()]);
    });
    const note = ed.querySelector(".note");
    note.addEventListener("change", () =>
      fetch(`/api/games/${id}/note`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note.value }),
      }),
    );
  });
}

function renderTags(games) {
  funBarChart("chart-tags", aggregate(games, (g) => g.tags), { horizontal: true });
  const list = games.slice().sort((a, b) => b.date - a.date);
  const host = document.getElementById("tags-games");
  host.innerHTML = list.length
    ? list.map((g) => `
        <div class="tag-row">
          <div class="tag-meta"><b>${g.champion || "?"}</b> · ${g.result} · ${g.queue_type || "?"}
            <span class="when">${g.day}</span> ${g.rated ? EMOJI[g.fun_score] : ""}</div>
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
  const list = document.getElementById("pending-list");
  if (!pending.length) { list.innerHTML = '<div class="empty-note">All caught up — not a single un-vibed game. Certified responsible adult. 🏆</div>'; return; }
  list.innerHTML = pending.map((g) => `
    <div class="pending-row" data-id="${g.id}">
      <div class="meta">
        <div><b>${g.champion || "?"}</b> · ${g.result} · ${g.kills ?? "?"}/${g.deaths ?? "?"}/${g.assists ?? "?"} · ${g.queue_type || "?"}</div>
        <div class="when">${g.played_at.replace("T", " ")} · ${Math.round((g.duration_seconds || 0) / 60)} min${g.premades.length ? " · with " + g.premades.map((t) => t.name).join(", ") : ""}</div>
      </div>
      <div class="rate-btns">
        ${[1, 2, 3, 4, 5].map((s) => `<button data-score="${s}" title="${GRADES[s]}">${EMOJI[s]}</button>`).join("")}
        <button class="skip" data-skip="1" title="exclude from stats">skip</button>
      </div>
      <div style="flex-basis:100%">${tagEditorHTML(g)}</div>
    </div>`).join("");
  list.querySelectorAll(".rate-btns button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.closest(".pending-row").dataset.id;
      const body = btn.dataset.skip ? { skipped: true } : { score: Number(btn.dataset.score) };
      await fetch(`/api/games/${id}/rating`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      await refresh();
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
  buildMultiselect("f-champion", "Champion", uniq((g) => g.champion).map((v) => ({ value: v, label: v })), state.sets.champion, renderAll);
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

function renderAll() {
  const games = filtered();
  document.getElementById("f-count").textContent =
    games.length === ALL.length ? "" : `${games.length} of ${ALL.length} games match`;
  renderHeader(games);
  renderPending();
  const t = state.tab;
  if (t === "overview") renderOverview(games);
  if (t === "champions") renderChampions(games);
  if (t === "squad") renderSquad(games);
  if (t === "context") renderContext(games);
  if (t === "sessions") renderSessions(games);
  if (t === "tags") renderTags(games);
  if (t === "online") renderOnline();
  if (t === "settings") renderSettings();
  if (t === "explorer") renderExplorer(games);
}

async function refresh() {
  try {
    await loadData();
  } catch (e) {
    // Graceful offline state: the tray app (our local API) isn't reachable, or
    // a fetch failed. Show a banner and keep the last-rendered data on screen,
    // then retry soon so it self-heals when the app comes back.
    const b = document.getElementById("offline-banner");
    b.textContent =
      "⚠ Can't reach VibeCheck on this PC — is the tray app still running? Retrying…";
    b.classList.remove("hidden");
    clearTimeout(window.__offlineRetry);
    window.__offlineRetry = setTimeout(refresh, 5000);
    return;
  }
  document.getElementById("offline-banner").classList.add("hidden");
  buildFilters();
  renderAll();
}

document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.tab = btn.dataset.tab;
    document.querySelectorAll(".tab").forEach((el) => el.classList.add("hidden"));
    document.getElementById(`tab-${state.tab}`).classList.remove("hidden");
    renderAll();
  });
});
document.getElementById("ex-dim").addEventListener("change", renderAll);
document.getElementById("ex-type").addEventListener("change", renderAll);

refresh();
setInterval(refresh, 60_000); // live-ish: new games appear without a manual reload
