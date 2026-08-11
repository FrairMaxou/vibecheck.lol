# Overview Top-Row Squares + Capped Vibe Trend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Worktree:** All work happens in the existing worktree at
> `C:\Users\MGoss\Desktop\dev\vibecheck\.claude\worktrees\overview-polish`
> (branch `overview-polish`). Do not create a new worktree. The branch
> already has two bug-fix commits (`e5968bd`) and this plan's spec commit
> (`928b38b`) — `cd` into this worktree before running any step below.

**Goal:** Move ARAM God into a new top row next to VIBE-O-METER, both
restyled as matching square cards, and cap the vibe trend to the most
recent 20 rated games with a "Show all N games" expand link.

**Architecture:** Pure frontend, two independent changes to the same three
files (`vibecheck/web/{index.html,app.js,style.css}`): a CSS-only restyle
of the existing VIBE-O-METER markup plus a full markup rewrite of
`renderAramGodCompact()` for Task 1, and a small change to
`renderVibeTrend()`'s input slicing plus one new click handler for Task 2.
No schema or backend change — both tasks read data that's already fetched
today (`vibeMeterStats()`, `fetchAramGod()`, the existing `rated` games
array).

**Tech Stack:** Vanilla JS (existing `app.js`, no framework/build step),
plain CSS. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-overview-top-row-and-trend-cap-design.md`.
  Read it before starting.
- No inline event handlers (`onclick=`, etc.) anywhere — the dashboard's CSP
  (`vibecheck/security.py`) blocks inline script attributes. Every new
  interactive element is wired with `addEventListener` after its markup is
  inserted, exactly like every existing handler in `app.js`.
- Reuse the existing `--vc-*` CSS tokens (`style.css:470-477`) and the
  existing `--vc-gold`/`--vc-gold-hl`/`--vc-bg-surface-hover`/`--vc-border`
  tokens for ARAM God's gold pill — no new CSS variables.
- `renderVibeMeter()` (`app.js:657-690`) keeps its exact markup and class
  names (`ov-vibemeter-card`, `ov-vm-*`) — this plan restyles it with CSS
  only, no JS edits to that function.
- No JS test harness in this project — verify by hand (dev server +
  browser), exactly as every other Overview task did.
- Conventional Commits (enforced by a local hook).
- `.venv\Scripts\ruff check . --fix` and `.venv\Scripts\ruff format .` must
  be clean before each commit (touches only `.html`/`.js`/`.css`, so these
  are expected to no-op, but run them anyway per repo convention). After
  running them, check `git status --short` — a known environment quirk has
  twice reformatted unrelated `docs/superpowers/**/*.md` files; revert any
  such stray change before committing (`git checkout -- <file>`).

---

### Task 1: Top row — square VIBE-O-METER + square ARAM God

**Files:**
- Modify: `vibecheck/web/index.html:163-172` (wrap the two widgets in a new
  top-row container, drop the dead `class="ov-aram"` attribute)
- Modify: `vibecheck/web/app.js:378-410` (rewrite `renderAramGodCompact`'s
  markup; the unused `ARAM_GOD_ICON` constant goes with it)
- Modify: `vibecheck/web/style.css:562-628` (replace the old `.ov-aram-card`
  rules with the new square anatomy, restyle `.ov-vibemeter-card`/`.ov-vm-*`
  for the square layout, add the `.ov-top-row` grid container)

**Interfaces:**
- Consumes: `fetchAramGod()` (`app.js:729-732`, unchanged — returns
  `{tracked, completed, total}`), `renderVibeMeter()` (unchanged, still
  targets `#ov-vibemeter`).
- Produces: `renderAramGodCompact()` keeps its exact name and signature
  (still targets `#ov-aram`, still called with no arguments from
  `renderOverview`) — only its internal markup changes. No new exported
  interface.

- [ ] **Step 1: Move ARAM God into a new top row in `index.html`**

Change lines 163-172 from:

```html
  <div id="tab-overview" class="tab">
    <div id="ov-vibemeter"></div>
    <div id="ov-totals" class="ov-totals"></div>
    <div class="ov-section-label">Spotlight</div>
    <div id="ov-spotlight" class="ov-spotlight"></div>
    <div id="ov-aram" class="ov-aram"></div>
    <div class="panel">
      <h2>Vibe trend <span class="hint">who's been driving the swings</span></h2>
      <div id="ov-trend" class="ov-trend"></div>
    </div>
  </div>
```

to:

```html
  <div id="tab-overview" class="tab">
    <div class="ov-top-row">
      <div id="ov-vibemeter"></div>
      <div id="ov-aram"></div>
    </div>
    <div id="ov-totals" class="ov-totals"></div>
    <div class="ov-section-label">Spotlight</div>
    <div id="ov-spotlight" class="ov-spotlight"></div>
    <div class="panel">
      <h2>Vibe trend <span class="hint">who's been driving the swings</span></h2>
      <div id="ov-trend" class="ov-trend"></div>
    </div>
  </div>
```

- [ ] **Step 2: Replace the ARAM God CSS and restyle VIBE-O-METER for the square layout**

In `vibecheck/web/style.css`, delete the entire old ARAM God block (lines
562-576 — from `.ov-aram-card {` through the `.ov-aram-fill` rule) and
replace it with:

```css
.ov-top-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 320px)); gap: 14px; margin-bottom: 26px; }

.ov-aram-card {
  background: var(--vc-bg-surface); border: 1px solid var(--vc-border); border-radius: 14px;
  padding: 20px; text-align: center; aspect-ratio: 1; box-sizing: border-box;
  display: flex; flex-direction: column; justify-content: center;
}
.ov-aram-sq-label {
  font-size: 11px; letter-spacing: 2px; color: var(--vc-text-muted);
  text-transform: uppercase; margin-bottom: 10px;
}
.ov-aram-sq-number {
  font-family: "JetBrains Mono", "Consolas", monospace; font-size: 40px; font-weight: 700;
  color: var(--vc-text-main); line-height: 1; margin-bottom: 8px;
}
.ov-aram-sq-pill {
  display: inline-block; padding: 4px 12px; border-radius: 16px; font-size: 11px; font-weight: 700;
  letter-spacing: .5px; margin-bottom: 16px;
  background: rgba(229, 169, 60, .15); color: var(--vc-gold-hl); border: 1px solid rgba(229, 169, 60, .4);
}
.ov-aram-empty .ov-aram-sq-pill { background: var(--vc-bg-surface-hover); color: var(--vc-text-muted); border-color: var(--vc-border); }
.ov-aram-sq-bar { height: 10px; border-radius: 5px; background: var(--vc-bg-surface-hover); margin: 0 2px; overflow: hidden; }
.ov-aram-sq-fill { height: 100%; background: linear-gradient(90deg, var(--vc-gold), var(--vc-gold-hl)); border-radius: 5px; }
.ov-aram-sq-caption { margin-top: 14px; font-size: 11px; color: var(--vc-text-muted); }
```

Then, in the VIBE-O-METER block (currently at lines 591-628 after the
deletion above shifts nothing before it — this block comes after the
deleted one, so re-check line numbers with `grep -n ov-vibemeter-card
style.css` before editing), change:

```css
.ov-vibemeter-card {
  background: var(--vc-bg-surface); border: 1px solid var(--vc-border); border-radius: 14px;
  padding: 26px 30px 22px; text-align: center; margin-bottom: 26px;
}
.ov-vm-label {
  font-size: 12px; letter-spacing: 2.5px; color: var(--vc-text-muted);
  text-transform: uppercase; margin-bottom: 14px;
}
.ov-vm-number {
  font-family: "JetBrains Mono", "Consolas", monospace; font-size: 48px; font-weight: 700;
  color: var(--vc-text-main); line-height: 1; margin-bottom: 8px;
}
.ov-vm-pill {
  display: inline-block; padding: 5px 16px; border-radius: 20px; font-size: 13px; font-weight: 700;
  letter-spacing: .5px; margin-bottom: 22px;
}
```

to:

```css
.ov-vibemeter-card {
  background: var(--vc-bg-surface); border: 1px solid var(--vc-border); border-radius: 14px;
  padding: 20px; text-align: center; aspect-ratio: 1; box-sizing: border-box;
  display: flex; flex-direction: column; justify-content: center;
}
.ov-vm-label {
  font-size: 11px; letter-spacing: 2px; color: var(--vc-text-muted);
  text-transform: uppercase; margin-bottom: 10px;
}
.ov-vm-number {
  font-family: "JetBrains Mono", "Consolas", monospace; font-size: 40px; font-weight: 700;
  color: var(--vc-text-main); line-height: 1; margin-bottom: 8px;
}
.ov-vm-pill {
  display: inline-block; padding: 4px 12px; border-radius: 16px; font-size: 11px; font-weight: 700;
  letter-spacing: .5px; margin-bottom: 16px;
}
```

Leave `.ov-vm-empty .ov-vm-pill`, `.ov-vm-bar`, `.ov-vm-seg*`,
`.ov-vm-empty .ov-vm-seg`, `.ov-vm-marker`, `.ov-vm-ticks*`, and
`.ov-vm-caption*` exactly as they are — only the four rules replaced above
change. The card's own `margin-bottom: 26px` is removed because
`.ov-top-row`'s `gap: 14px` (and its own `margin-bottom: 26px`) now own the
spacing around the row, not the individual card.

- [ ] **Step 3: Rewrite `renderAramGodCompact` in `app.js`**

Replace lines 378-410 (from the `ARAM_GOD_ICON` constant through the end of
`renderAramGodCompact`) — currently:

```javascript
const ARAM_GOD_ICON = '<path d="M12 2l2.5 5.5L20 8l-4.5 4 1.5 6L12 15l-5 3 1.5-6L4 8l5.5-.5z"/>';

async function renderAramGodCompact() {
  const host = document.getElementById("ov-aram");
  let d;
  try {
    d = ARAM_GOD = ARAM_GOD || (await fetchAramGod());
  } catch {
    host.innerHTML = "";
    return;
  }
  const badge = `<div class="ov-aram-badge"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${ARAM_GOD_ICON}</svg></div>`;
  if (!d.tracked || !d.total) {
    host.innerHTML = `
      <div class="ov-aram-card">${badge}
        <div class="ov-aram-body">
          <div class="ov-aram-title-row"><div class="ov-aram-title">ARAM God run</div><div class="ov-aram-count">not tracked yet</div></div>
          <div class="ov-aram-hint">Open the League client once with VibeCheck running to start tracking this</div>
          <div class="ov-aram-bar"><div class="ov-aram-fill" style="width:0%"></div></div>
        </div>
      </div>`;
    return;
  }
  const pct = d.total ? Math.round((d.completed / d.total) * 100) : 0;
  host.innerHTML = `
    <div class="ov-aram-card">${badge}
      <div class="ov-aram-body">
        <div class="ov-aram-title-row"><div class="ov-aram-title">ARAM God run</div><div class="ov-aram-count">${d.completed} / ${d.total}</div></div>
        <div class="ov-aram-hint">S- or better on every ARAM champion — the long one</div>
        <div class="ov-aram-bar"><div class="ov-aram-fill" style="width:${pct}%"></div></div>
      </div>
    </div>`;
}
```

with:

```javascript
async function renderAramGodCompact() {
  const host = document.getElementById("ov-aram");
  let d;
  try {
    d = ARAM_GOD = ARAM_GOD || (await fetchAramGod());
  } catch {
    host.innerHTML = "";
    return;
  }
  // Both conditions matter and must not collapse into one: a 0 total before
  // the client has ever synced is "we don't know yet", not "zero progress".
  if (!d.tracked || !d.total) {
    host.innerHTML = `
      <div class="ov-aram-card ov-aram-empty">
        <div class="ov-aram-sq-label">ARAM god run</div>
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
      <div class="ov-aram-sq-label">ARAM god run</div>
      <div class="ov-aram-sq-number">${d.completed}/${d.total}</div>
      <div class="ov-aram-sq-pill">${pct}% complete</div>
      <div class="ov-aram-sq-bar"><div class="ov-aram-sq-fill" style="width:${pct}%"></div></div>
      <div class="ov-aram-sq-caption">S- or better on every ARAM champion</div>
    </div>`;
}
```

(`ARAM_GOD_ICON` is deleted entirely — nothing else in the file references
it; confirm with `grep -n ARAM_GOD_ICON vibecheck/web/app.js` after this
edit, which should return nothing.)

- [ ] **Step 4: Verify manually — populated state**

Run: `.venv\Scripts\python -m vibecheck` from the worktree root, open the
dashboard, land on the Overview tab.

Expected: a top row with two equal squares side by side — VIBE-O-METER on
the left (label, smaller number, tier pill, segmented bar with marker,
ticks, caption, all still correct — this must look like the same widget,
just resized) and ARAM God on the right (label "ARAM god run", a big
`completed/total` number, a gold "`N`% complete" pill, a single filled
progress bar, and the hint caption). Both cards are the same height and
width. Below the row, lifetime totals / spotlight / vibe trend render
exactly as before, just shifted down.

- [ ] **Step 5: Verify manually — ARAM God's two empty states**

With `tracked: false` or `total: 0` from `/api/aram-god` (e.g. a fresh
profile, or temporarily point `%LOCALAPPDATA%\VibeCheck` at an empty
sqlite file), the ARAM God square shows `—`, a neutral (non-gold)
"Not tracked yet" pill, an empty bar, and the "Open the League client
once..." caption — matching VIBE-O-META's own empty-state treatment
visually (both muted, no color).

- [ ] **Step 6: Verify manually — narrow window**

Resize the browser window down to roughly 400-450px wide. The two squares
must wrap to a single column (one above the other) with no horizontal
scrollbar on the page body — `repeat(auto-fit, minmax(220px, 320px))`
should collapse on its own once two 220px-minimum columns no longer fit.

- [ ] **Step 7: Run the existing test suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\ddragon_splash_test.py
.venv\Scripts\python tests\dashboard_splash_test.py
```

Expected: every script prints its `OK` line (none of them exercise the
frontend, so this only guards against an unrelated regression).

- [ ] **Step 8: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git status --short
```

If `git status --short` shows any modified file outside
`vibecheck/web/{index.html,app.js,style.css}` (a known environment quirk
has reformatted unrelated markdown files under `docs/superpowers/` during
this exact lint step before), revert it: `git checkout -- <that file>`.
Then:

```powershell
git add vibecheck/web/index.html vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): move ARAM God into a square top row beside VIBE-O-METER"
```

---

### Task 2: Cap the vibe trend to the last 20 rated games

**Files:**
- Modify: `vibecheck/web/app.js:414-445` (`renderVibeTrend`, plus a new
  module-level flag and one new line in `refresh()`)
- Modify: `vibecheck/web/style.css` (one new rule for the expand link)

**Interfaces:**
- Consumes: nothing new — same `games` parameter `renderVibeTrend` already
  receives from `renderOverview`.
- Produces: `renderVibeTrend(games)` keeps its exact name and signature.
  New module-level `let ovTrendExpanded = false;`.

- [ ] **Step 1: Add the module-level expanded flag**

In `vibecheck/web/app.js`, add directly above `function renderVibeTrend(games) {`
(currently line 414):

```javascript
// Transient UI state, not persisted: resets to collapsed whenever refresh()
// pulls new data (see refresh(), which sets this back to false alongside
// its other per-load resets), but NOT on a plain tab switch or filter
// change, so expanding doesn't get silently undone by clicking a filter.
let ovTrendExpanded = false;

```

- [ ] **Step 2: Cap the plotted points and add the expand control**

Change `renderVibeTrend` from:

```javascript
function renderVibeTrend(games) {
  const host = document.getElementById("ov-trend");
  const rated = games.filter((g) => g.rated).slice().sort((a, b) => a.date - b.date);
  if (!rated.length) {
    host.innerHTML = '<div class="ov-trend-empty">Rate a few games and your vibe trend shows up here.</div>';
    return;
  }
  const n = rated.length;
  const points = rated.map((g, i) => ({
    x: n > 1 ? (100 * i) / (n - 1) : 50,
    // Plot 1–5 into the 8–92% band, inverted (SVG y grows downward, and a
    // high score should sit near the top of the chart).
    y: 92 - ((g.fun_score - 1) / 4) * 84,
    g,
  }));
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const dots = points.map((p) => `
    <div class="ov-trend-point" style="left:${p.x.toFixed(1)}%;top:${p.y.toFixed(1)}%;--ring:${OV_TIER_HEX[p.g.fun_score]}"
         title="${escapeAttr(p.g.champion_key || "?")} — ${escapeAttr(p.g.day)} — ${GRADES[p.g.fun_score]}">
      <div class="ov-ring"></div>
      <img src="/api/champ-icon/${encodeURIComponent(p.g.champion || "")}${p.g.classic ? "?classic=1" : ""}"
           alt="" loading="lazy" data-on-error="remove">
    </div>`).join("");
  host.innerHTML = `
    <div class="ov-trend-chart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline fill="none" stroke="${OV_TIER_HEX[3]}22" stroke-width="1.2" vector-effect="non-scaling-stroke" points="${line}"/>
      </svg>
      ${dots}
    </div>
    <div class="ov-trend-legend">${[1, 2, 3, 4, 5].map((t) => `<span><i style="background:${OV_TIER_HEX[t]}"></i>${GRADES[t]}</span>`).join("")}</div>`;
}
```

to:

```javascript
function renderVibeTrend(games) {
  const host = document.getElementById("ov-trend");
  const rated = games.filter((g) => g.rated).slice().sort((a, b) => a.date - b.date);
  if (!rated.length) {
    host.innerHTML = '<div class="ov-trend-empty">Rate a few games and your vibe trend shows up here.</div>';
    return;
  }
  // "How have I been doing lately" is the point of a trend, so a cap keeps
  // the most recent games (slice(-20)), not the oldest.
  const capped = !ovTrendExpanded && rated.length > 20;
  const shown = capped ? rated.slice(-20) : rated;
  const n = shown.length;
  const points = shown.map((g, i) => ({
    x: n > 1 ? (100 * i) / (n - 1) : 50,
    // Plot 1–5 into the 8–92% band, inverted (SVG y grows downward, and a
    // high score should sit near the top of the chart).
    y: 92 - ((g.fun_score - 1) / 4) * 84,
    g,
  }));
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const dots = points.map((p) => `
    <div class="ov-trend-point" style="left:${p.x.toFixed(1)}%;top:${p.y.toFixed(1)}%;--ring:${OV_TIER_HEX[p.g.fun_score]}"
         title="${escapeAttr(p.g.champion_key || "?")} — ${escapeAttr(p.g.day)} — ${GRADES[p.g.fun_score]}">
      <div class="ov-ring"></div>
      <img src="/api/champ-icon/${encodeURIComponent(p.g.champion || "")}${p.g.classic ? "?classic=1" : ""}"
           alt="" loading="lazy" data-on-error="remove">
    </div>`).join("");
  // No "collapse back" control once expanded — nothing else on this page
  // has a collapse affordance either (e.g. the spotlight hover overlay).
  const expandHtml = capped
    ? `<button type="button" class="ov-trend-expand" id="ov-trend-expand">Show all ${rated.length} games</button>`
    : "";
  host.innerHTML = `
    <div class="ov-trend-chart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline fill="none" stroke="${OV_TIER_HEX[3]}22" stroke-width="1.2" vector-effect="non-scaling-stroke" points="${line}"/>
      </svg>
      ${dots}
    </div>
    <div class="ov-trend-legend">${[1, 2, 3, 4, 5].map((t) => `<span><i style="background:${OV_TIER_HEX[t]}"></i>${GRADES[t]}</span>`).join("")}</div>
    ${expandHtml}`;
  if (capped) {
    document.getElementById("ov-trend-expand").addEventListener("click", () => {
      ovTrendExpanded = true;
      renderVibeTrend(games);
    });
  }
}
```

- [ ] **Step 3: Reset the flag on a real data refresh**

In `refresh()` (currently `app.js:1562-1569`), change:

```javascript
async function refresh() {
  await loadData();
  ARAM_GOD = null; // a new game may have completed a champion — refetch it too
  ARAM_GOD_DRAWN = null;
  document.getElementById("offline-banner").classList.add("hidden");
  buildFilters();
  renderAll();
}
```

to:

```javascript
async function refresh() {
  await loadData();
  ARAM_GOD = null; // a new game may have completed a champion — refetch it too
  ARAM_GOD_DRAWN = null;
  ovTrendExpanded = false; // a genuinely new dataset re-earns the cap
  document.getElementById("offline-banner").classList.add("hidden");
  buildFilters();
  renderAll();
}
```

- [ ] **Step 4: Add the expand-link CSS**

Append to `vibecheck/web/style.css`:

```css
.ov-trend-expand {
  display: block; margin: 12px auto 0; padding: 6px 14px; border-radius: 8px;
  background: var(--vc-bg-surface-hover); border: 1px solid var(--vc-border);
  color: var(--vc-text-muted); font-size: 12px; cursor: pointer;
}
.ov-trend-expand:hover { color: var(--vc-text-main); border-color: var(--vc-gold); }
```

- [ ] **Step 5: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`, open the Overview tab on a
profile with more than 20 rated games.

Expected: the trend shows only the most recent 20 portraits, and a
"Show all `N` games" button appears centered below the legend (`N` is the
true total rated count, not 20). Clicking it re-renders the trend with
every rated game and the button disappears. Switch to another tab and back
to Overview (or apply a filter) — the expanded trend stays expanded (no
`refresh()` happened, so `ovTrendExpanded` is untouched). Then either wait
for a new game to be captured, or manually confirm in the browser console
that `ovTrendExpanded` is reset to `false` immediately after a call to
`refresh()`. On a profile with 20 or fewer rated games, no button ever
appears and the trend behaves exactly as it did before this task.

- [ ] **Step 6: Run the existing test suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\ddragon_splash_test.py
.venv\Scripts\python tests\dashboard_splash_test.py
```

Expected: every script prints its `OK` line.

- [ ] **Step 7: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git status --short
```

Revert any stray `docs/superpowers/**/*.md` reformat as in Task 1 Step 8,
if it recurs. Then:

```powershell
git add vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): cap the vibe trend to the last 20 games by default"
```

---

## Final check before opening the PR

- [ ] Re-read `docs/superpowers/specs/2026-08-11-overview-top-row-and-trend-cap-design.md`
  against both tasks — confirm the page order, the shared square anatomy
  table, the `tracked`/`total` empty-state distinction, and the trend's
  most-recent-20 + expand-link behavior are all covered.
- [ ] `.venv\Scripts\pre-commit run --all-files` clean.
- [ ] PR description notes this is Overview-only — the larger nav/filter/
  profile shell redesign the maintainer also requested is a separate,
  not-yet-designed follow-up (per the spec's "Follow-ups" section).
