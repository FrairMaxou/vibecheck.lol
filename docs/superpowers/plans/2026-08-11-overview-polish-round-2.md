# Overview Polish Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Center the Overview top row, title the lifetime-totals strip,
slim the spotlight tiles to the loading-screen aspect ratio, add spacing
before the vibe trend, and make the vibe trend readable (axis labels + a
hover readout) with a real filter button replacing last round's one-way
"Show all N games" link.

**Architecture:** Pure frontend, three tasks touching
`vibecheck/web/{index.html,app.js,style.css}`: one bundling four small,
independent CSS/markup tweaks (Task 1), one restructuring
`renderVibeTrend`'s chart markup to add axis labels and a hover readout
(Task 2), and one replacing that same function's capping mechanism with a
real filter menu (Task 3, built on top of Task 2's version of the
function). No schema or backend change.

**Tech Stack:** Vanilla JS (existing `app.js`, no framework/build step),
plain CSS. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-overview-polish-round-2-design.md`.
  Read it before starting.
- No inline event handlers anywhere — the dashboard's CSP
  (`vibecheck/security.py`) blocks inline script attributes. Every
  interactive element is wired with `addEventListener`.
- Reuse existing `--vc-*` CSS tokens (`style.css:470-477`) — no new CSS
  variables.
- **Task 3's outside-click-closes listener for the trend filter menu must
  be registered exactly once**, in the same top-level wiring section as
  the existing profile-menu listener (`app.js`, search for
  `document.getElementById("profile-btn")`) — never inside
  `renderVibeTrend`, which runs on every tab switch/filter change and
  would register a new `document`-level listener each time. This is a
  named, spec-called-out risk (design spec §"Risk, most severe first" #1)
  — the task reviewer must check this specifically.
- No JS test harness in this project — verify by hand (dev server +
  browser).
- Conventional Commits (enforced by a local hook).
- `.venv\Scripts\ruff check . --fix` and `.venv\Scripts\ruff format .`
  must be clean before each commit. After running them, check
  `git status --short` — a known environment quirk has repeatedly
  reformatted unrelated `docs/superpowers/**/*.md` files; revert any such
  stray change (`git checkout -- <file>`) before committing.

---

### Task 1: Quick Overview polish (center row, totals title, slimmer tiles, trend spacing)

**Files:**
- Modify: `vibecheck/web/index.html:163-175`
- Modify: `vibecheck/web/style.css:511` (`.ov-stile`), `:562` (`.ov-top-row`)
- Modify: `vibecheck/web/style.css` (append `.ov-trend-panel`)

**Interfaces:** None — pure markup/CSS, no JS functions added or changed.

- [ ] **Step 1: Edit `index.html`**

Change lines 163-175 from:

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

to:

```html
  <div id="tab-overview" class="tab">
    <div class="ov-top-row">
      <div id="ov-vibemeter"></div>
      <div id="ov-aram"></div>
    </div>
    <div class="ov-section-label">Lifetime totals <span class="hint">since recording started</span></div>
    <div id="ov-totals" class="ov-totals"></div>
    <div class="ov-section-label">Spotlight</div>
    <div id="ov-spotlight" class="ov-spotlight"></div>
    <div class="panel ov-trend-panel">
      <h2>Vibe trend <span class="hint">who's been driving the swings</span></h2>
      <div id="ov-trend" class="ov-trend"></div>
    </div>
  </div>
```

(Two changes: a new `.ov-section-label` line before `#ov-totals`, and
`ov-trend-panel` added to the Vibe trend `.panel`'s class list.)

- [ ] **Step 2: Center the top row**

In `vibecheck/web/style.css`, change:

```css
.ov-top-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 320px)); gap: 14px; margin-bottom: 26px; }
```

to:

```css
.ov-top-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 320px)); gap: 14px; margin-bottom: 26px; justify-content: center; }
```

- [ ] **Step 3: Slim the spotlight tiles to the loading-screen aspect ratio**

Change:

```css
.ov-stile {
  aspect-ratio: 3 / 4; position: relative; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--vc-border); background: var(--vc-bg-surface); cursor: default;
}
```

to:

```css
.ov-stile {
  aspect-ratio: 11 / 20; position: relative; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--vc-border); background: var(--vc-bg-surface); cursor: default;
}
```

(11:20 is Data Dragon's actual champion loading-screen crop ratio,
308×560px simplified — matches the art these tiles already display.)

- [ ] **Step 4: Add spacing before the Vibe trend panel**

Append to the end of `vibecheck/web/style.css`:

```css
.ov-trend-panel { margin-top: 26px; }
```

- [ ] **Step 5: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`, open the Overview tab.

Expected: the top row (VIBE-O-METER + ARAM God) sits centered rather than
pinned to the left on a wide window. A "LIFETIME TOTALS · SINCE RECORDING
STARTED" label appears above the four totals cards, styled like the
existing "SPOTLIGHT" label. Spotlight tiles are visibly narrower/taller
than before and still show correctly cropped champion art (no stretching
or letterboxing). There's a clear gap between the spotlight grid and the
"Vibe trend" panel below it. Then resize the window down to roughly
400-450px wide (same check the top-row spec originally called for) —
the two squares must still collapse to a single stacked column with no
horizontal scrollbar; `justify-content: center` must not change that
collapse behavior, only how the row is positioned when it doesn't need
to collapse.

- [ ] **Step 6: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git status --short
```

Revert any stray `docs/superpowers/**/*.md` reformat if it recurs. Then:

```powershell
git add vibecheck/web/index.html vibecheck/web/style.css
git commit -m "feat(web): center top row, title totals strip, slim spotlight tiles, space the trend"
```

---

### Task 2: Vibe trend axis labels + hover readout

**Files:**
- Modify: `vibecheck/web/app.js:411-466` (`renderVibeTrend` and the
  constants immediately above it)
- Modify: `vibecheck/web/style.css` (append new `.ov-trend-row`/
  `.ov-trend-yaxis`/`.ov-trend-col`/`.ov-trend-xaxis`/`.ov-trend-readout*`
  rules)

**Interfaces:**
- Consumes: `OV_TIER_HEX`, `GRADES`, `escapeAttr` (all existing, unchanged).
- Produces: `formatTrendDate(day: string) -> string` (new, e.g. `"Aug 9"`),
  `trendReadoutHtml(g: object) -> string` (new — `g` is an enriched game
  object with `champion_key`, `day`, `fun_score`), both consumed by Task 3
  too. `renderVibeTrend(games)` keeps its exact name and signature.

- [ ] **Step 1: Add the CSS**

Append to `vibecheck/web/style.css`:

```css
.ov-trend-row { display: flex; gap: 8px; }
.ov-trend-yaxis { display: flex; flex-direction: column; justify-content: space-between; padding: 2px 0; }
.ov-trend-yaxis span { font-size: 10px; color: var(--vc-text-muted); font-family: "JetBrains Mono", "Consolas", monospace; }
.ov-trend-col { flex: 1; min-width: 0; }
.ov-trend-xaxis { display: flex; justify-content: space-between; margin-top: 6px; }
.ov-trend-xaxis span { font-size: 10px; color: var(--vc-text-muted); font-family: "JetBrains Mono", "Consolas", monospace; }
.ov-trend-readout {
  display: flex; align-items: center; gap: 10px; margin-top: 12px;
  background: var(--vc-bg-surface-hover); border: 1px solid var(--vc-border); border-radius: 10px; padding: 8px 12px;
}
.ov-trend-readout-dot { width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0; }
.ov-trend-readout-meta { font-size: 11px; color: var(--vc-text-muted); }
.ov-trend-readout-meta b { display: block; color: var(--vc-text-main); font-size: 12px; margin-bottom: 1px; }
```

`.ov-trend-chart` (existing rule, unchanged: `position: relative; height:
130px; margin-top: 6px;`) now lives inside `.ov-trend-col` instead of
being the outermost element — no change needed to that existing rule,
`.ov-trend-col`'s `flex: 1` gives it the remaining row width and
`.ov-trend-chart`'s own `height: 130px` is unaffected.

- [ ] **Step 2: Add `formatTrendDate` and `trendReadoutHtml`, rewrite `renderVibeTrend`**

In `vibecheck/web/app.js`, change (currently lines 411-466):

```javascript
const OV_TIER_HEX = { 1: "#EF4444", 2: "#F97316", 3: "#EAB308", 4: "#10B981", 5: "#8B5CF6" };

// Transient UI state, not persisted: resets to collapsed whenever refresh()
// pulls new data (see refresh(), which sets this back to false alongside
// its other per-load resets), but NOT on a plain tab switch or filter
// change, so expanding doesn't get silently undone by clicking a filter.
let ovTrendExpanded = false;
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

to:

```javascript
const OV_TIER_HEX = { 1: "#EF4444", 2: "#F97316", 3: "#EAB308", 4: "#10B981", 5: "#8B5CF6" };

function formatTrendDate(day) {
  const d = new Date(day);
  return d.toLocaleString("en-US", { month: "short", day: "numeric" });
}

/* The chart's default reading when nothing is hovered, and what every
   hovered point swaps in — one function so the two states can never
   drift out of sync with each other's markup. */
function trendReadoutHtml(g) {
  return `
    <div class="ov-trend-readout-dot" style="background:${OV_TIER_HEX[g.fun_score]}"></div>
    <div class="ov-trend-readout-meta"><b>${escapeAttr(g.champion_key || "?")} — ${formatTrendDate(g.day)}</b>${GRADES[g.fun_score]} (${g.fun_score})</div>`;
}

// Transient UI state, not persisted: resets to collapsed whenever refresh()
// pulls new data (see refresh(), which sets this back to false alongside
// its other per-load resets), but NOT on a plain tab switch or filter
// change, so expanding doesn't get silently undone by clicking a filter.
let ovTrendExpanded = false;
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
  // No "collapse back" control once expanded — nothing else on this page
  // has a collapse affordance either (e.g. the spotlight hover overlay).
  const expandHtml = capped
    ? `<button type="button" class="ov-trend-expand" id="ov-trend-expand">Show all ${rated.length} games</button>`
    : "";

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
    ${expandHtml}`;

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
  if (capped) {
    document.getElementById("ov-trend-expand").addEventListener("click", () => {
      ovTrendExpanded = true;
      renderVibeTrend(games);
    });
  }
}
```

(This step deliberately keeps `ovTrendExpanded`/`capped`/the "Show all"
link exactly as they are — Task 3 replaces that mechanism. This step only
adds the y-axis, x-axis, and readout bar around the unchanged chart.)

- [ ] **Step 3: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`, open the Overview tab, on a
profile with several rated games.

Expected: a column of tier numbers (5 at top, 1 at bottom) to the left of
the chart; a row of dates below the chart, all real dates that
correspond to actual games (spot-check one against a point directly above
it); a small card below the legend showing a colored dot plus
"`Champion` — `Date`" and the tier label with its numeric score, matching
the most recent game by default. Hover a different point — the card
updates to that game's detail. Move the mouse away — it reverts to the
most recent game. With 20 or fewer rated games, `capped` never triggers
(unchanged from before) — a 2-3 game profile shows 2-3 x-axis labels, not
5 crowded ones.

- [ ] **Step 4: Run the existing test suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\ddragon_splash_test.py
.venv\Scripts\python tests\dashboard_splash_test.py
```

Expected: every script prints its `OK` line.

- [ ] **Step 5: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git status --short
```

Revert any stray `docs/superpowers/**/*.md` reformat if it recurs. Then:

```powershell
git add vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): add axis labels and a hover readout to the vibe trend"
```

---

### Task 3: Real filter button on the vibe trend

**Files:**
- Modify: `vibecheck/web/app.js` (replace the `ovTrendExpanded` mechanism
  inside `renderVibeTrend` with a `ovTrendWindow` filter menu; remove one
  line from `refresh()`; add one new top-level wiring block)
- Modify: `vibecheck/web/style.css` (remove the now-dead `.ov-trend-expand`
  rules, append new `.ov-trend-filter*` rules)

**Interfaces:**
- Consumes: `trendReadoutHtml`, `formatTrendDate` (Task 2).
- Produces: `renderVibeTrend(games)` keeps its exact name and signature.
  New module-level `let ovTrendWindow = 20;` (replaces `ovTrendExpanded`).

- [ ] **Step 1: Remove the dead `.ov-trend-expand` CSS**

In `vibecheck/web/style.css`, delete these two rules entirely (search for
`.ov-trend-expand` — nothing will reference this class after Step 3
below):

```css
.ov-trend-expand {
  display: block; margin: 12px auto 0; padding: 6px 14px; border-radius: 8px;
  background: var(--vc-bg-surface-hover); border: 1px solid var(--vc-border);
  color: var(--vc-text-muted); font-size: 12px; cursor: pointer;
}
.ov-trend-expand:hover { color: var(--vc-text-main); border-color: var(--vc-gold); }
```

- [ ] **Step 2: Add the filter button/menu CSS**

Append to `vibecheck/web/style.css`:

```css
.ov-trend-filter { position: relative; margin-top: 10px; text-align: center; }
.ov-trend-filter-btn {
  padding: 6px 14px; border-radius: 8px; background: var(--vc-bg-surface-hover); border: 1px solid var(--vc-border);
  color: var(--vc-text-muted); font-size: 12px; cursor: pointer;
}
.ov-trend-filter-btn:hover { color: var(--vc-text-main); border-color: var(--vc-gold); }
.ov-trend-filter-menu {
  position: absolute; left: 50%; transform: translateX(-50%); bottom: calc(100% + 6px);
  background: var(--vc-bg-surface); border: 1px solid var(--vc-border); border-radius: 8px; padding: 4px;
  display: flex; flex-direction: column; min-width: 140px; z-index: 5;
}
.ov-trend-filter-menu.hidden { display: none; }
.ov-trend-filter-menu button {
  background: none; border: none; color: var(--vc-text-main); font-size: 12px; text-align: left;
  padding: 6px 10px; border-radius: 6px; cursor: pointer;
}
.ov-trend-filter-menu button:hover { background: var(--vc-bg-surface-hover); }
```

- [ ] **Step 3: Replace the capping mechanism in `renderVibeTrend`**

In `vibecheck/web/app.js`, change:

```javascript
// Transient UI state, not persisted: resets to collapsed whenever refresh()
// pulls new data (see refresh(), which sets this back to false alongside
// its other per-load resets), but NOT on a plain tab switch or filter
// change, so expanding doesn't get silently undone by clicking a filter.
let ovTrendExpanded = false;
function renderVibeTrend(games) {
```

to:

```javascript
// Transient UI state, not persisted: a deliberate filter choice, so unlike
// last round's one-way "expand" it survives a real data refresh (see
// refresh() — no longer resets this) and only goes back to the default on
// a full page reload.
let ovTrendWindow = 20; // 20 | 50 | "all"
function renderVibeTrend(games) {
```

Then change:

```javascript
  // "How have I been doing lately" is the point of a trend, so a cap keeps
  // the most recent games (slice(-20)), not the oldest.
  const capped = !ovTrendExpanded && rated.length > 20;
  const shown = capped ? rated.slice(-20) : rated;
```

to:

```javascript
  // "How have I been doing lately" is the point of a trend, so a window
  // keeps the most recent games (slice(-N)), not the oldest.
  const shown = ovTrendWindow === "all" ? rated : rated.slice(-ovTrendWindow);
```

Then change:

```javascript
  // No "collapse back" control once expanded — nothing else on this page
  // has a collapse affordance either (e.g. the spotlight hover overlay).
  const expandHtml = capped
    ? `<button type="button" class="ov-trend-expand" id="ov-trend-expand">Show all ${rated.length} games</button>`
    : "";
```

to:

```javascript
  const windowLabel = ovTrendWindow === "all" ? "All" : String(ovTrendWindow);
```

Then change (the `host.innerHTML` template's final line and everything
after it):

```javascript
    <div class="ov-trend-readout" id="ov-trend-readout">${trendReadoutHtml(shown[n - 1])}</div>
    ${expandHtml}`;

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
  if (capped) {
    document.getElementById("ov-trend-expand").addEventListener("click", () => {
      ovTrendExpanded = true;
      renderVibeTrend(games);
    });
  }
}
```

to:

```javascript
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
```

`▾` is the small down-triangle character (▾) — written as an escape
so it survives copy/paste cleanly; typing the literal character directly
in the source is equally correct if your editor handles it.

- [ ] **Step 4: Remove the `ovTrendExpanded` reset from `refresh()`**

In `vibecheck/web/app.js`, change:

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

to:

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

- [ ] **Step 5: Register the outside-click-closes listener once**

In `vibecheck/web/app.js`, find the existing profile-menu wiring block
(search for `document.getElementById("profile-btn")`):

```javascript
// Profile menu (top-right): open/close, outside-click to dismiss, uninstall.
document.getElementById("profile-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  toggleProfileMenu();
});
document.addEventListener("click", (e) => {
  const menu = document.getElementById("profile-menu");
  if (!menu.classList.contains("hidden") && !e.target.closest(".profile")) menu.classList.add("hidden");
});
```

Add immediately after it:

```javascript
// Vibe trend filter menu: unlike the profile menu above, #ov-trend-filter-menu
// is rebuilt by renderVibeTrend on every render (not a static element), so this
// listener is registered exactly ONCE here rather than inside renderVibeTrend —
// doing it there would register a new document-level listener on every render.
document.addEventListener("click", (e) => {
  const menu = document.getElementById("ov-trend-filter-menu");
  if (menu && !menu.classList.contains("hidden") && !e.target.closest(".ov-trend-filter")) menu.classList.add("hidden");
});
```

(The `menu &&` guard matters: `#ov-trend-filter-menu` doesn't exist at all
when the trend is in its empty state, i.e. zero rated games.)

- [ ] **Step 6: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`, open the Overview tab on a
profile with more than 50 rated games (or temporarily lower the `20`/`50`
thresholds in the browser console to test with fewer).

Expected: a small button reading "20 ▾" below the readout card. Clicking
it opens a menu with three options; the current selection isn't
specially marked (not required by the spec) but clicking "Last 50 games"
re-renders the chart with up to 50 points and the button now reads
"50 ▾". Clicking elsewhere on the page (not the button or menu) closes an
open menu. Switch to another tab and back, or apply a filter-bar
change — the "50" selection survives (does not reset to "20"). Open the
browser devtools console and run `refresh()` manually — the selection
still survives (confirms Step 4's removal took effect). Confirm via
devtools that clicking the filter button repeatedly across many renders
does not keep adding new `click` listeners to `document` — one way to
spot-check: the menu still closes correctly on an outside click after
having opened/closed it 5-6 times in a row (a leaked-listener bug would
still "work" here, so this is a smoke check, not a rigorous one — the
task reviewer's job is verifying the listener is registered once by
reading the code, per this plan's Global Constraints).

- [ ] **Step 7: Run the existing test suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\ddragon_splash_test.py
.venv\Scripts\python tests\dashboard_splash_test.py
```

Expected: every script prints its `OK` line.

- [ ] **Step 8: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git status --short
```

Revert any stray `docs/superpowers/**/*.md` reformat if it recurs. Then:

```powershell
git add vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): replace the vibe trend's show-all link with a real filter menu"
```

---

## Final check before opening the PR

- [ ] Re-read `docs/superpowers/specs/2026-08-11-overview-polish-round-2-design.md`
  against all three tasks — confirm every numbered item (1-6) has a
  corresponding change, and that the trend filter menu's outside-click
  listener is registered exactly once (Global Constraints, Risk #1).
- [ ] `.venv\Scripts\pre-commit run --all-files` clean.
- [ ] PR description notes this is Overview-only — the lateral nav,
  collapsible top filter bar, and breadcrumbs the maintainer also
  requested remain a separate, not-yet-designed follow-up (per the
  spec's "Out of scope" section).
