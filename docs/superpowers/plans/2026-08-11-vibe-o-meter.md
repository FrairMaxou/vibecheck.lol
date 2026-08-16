# VIBE-O-METER Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Worktree:** All work happens in the existing worktree at
> `C:\Users\MGoss\Desktop\dev\vibecheck\.claude\worktrees\overview-redesign`
> (branch `worktree-overview-redesign`) — the same one the Overview redesign
> was implemented in. Do not create a new worktree; `cd` into this one before
> running any step below. The working tree is clean as of this plan's
> writing (`0baaf1f chore(web): remove dead Overview code after the tile
> redesign`).

**Goal:** Add a `VIBE-O-METER` card — a lifetime-average vibe meter with a
segmented tier bar — as the first element of the Overview tab, above the
existing lifetime-totals strip.

**Architecture:** Pure frontend addition, following the exact pattern the
shipped Overview redesign already established: one data function + one
render function in `vibecheck/web/app.js`, one new markup node in
`vibecheck/web/index.html`, new scoped CSS in `vibecheck/web/style.css`
reusing the `--vc-*` tokens and `.ov-tier1..5` classes that already exist
from that redesign. No schema or backend change.

**Tech Stack:** Vanilla JS (existing `app.js`, no framework/build step),
plain CSS. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-vibe-o-meter-design.md`. Read it
  before starting — this plan implements it directly.
- This card's number is **lifetime-average, always** — it does not react to
  the filter bar, unlike every other Overview section. It must read from the
  module-level `ALL` array directly, not from the `games` parameter
  `renderOverview` receives. Precedent: `renderHeader`'s `#profile-vibe` stat
  (`app.js:613-617`) already does this for the same reason.
- Exclude remakes: `!g.is_remake`, matching the F5 rule every other
  aggregation on this page already applies (`app.js:158`).
- No new CSS variables — reuse `--vc-bg-surface`, `--vc-border`,
  `--vc-text-main`, `--vc-text-muted`, `--vc-t1`..`--vc-t5` (defined at
  `style.css:470-477`) and the existing `.ov-tier1`..`.ov-tier5` pill-color
  classes (`style.css:555-559`).
- Tier copy comes from the existing `GRADES` object (`app.js:8-14`) —
  `"FF at 15"`, `"Who Let Them Cook?"`, `"Meh"`, `"We Are So Back"`,
  `"Gigachad"`. Don't invent new copy.
- No JS test harness in this project — verify by hand (dev server +
  browser), exactly as every other Overview task did.
- Conventional Commits (enforced by a local hook).
- `.venv\Scripts\ruff check . --fix` and `.venv\Scripts\ruff format .` must
  be clean before the commit (touches only `.html`/`.js`/`.css`, so these
  are expected to no-op, but run them anyway per repo convention).

---

### Task 1: VIBE-O-METER card

**Files:**
- Modify: `vibecheck/web/index.html:163-164` (new markup node)
- Modify: `vibecheck/web/app.js:626` (two new functions before
  `renderOverview`, one new call inside it)
- Modify: `vibecheck/web/style.css` (append new rules)

**Interfaces:**
- Consumes: module-level `ALL` (existing), `GRADES`, `OV_TIER_CLASS`
  (`app.js:308` — `{1:"ov-tier1", ..., 5:"ov-tier5"}`, already defined by the
  shipped spotlight work).
- Produces: `vibeMeterStats() -> {avg: number|null, n: number, total: number}`,
  `renderVibeMeter()`, called from `renderOverview`.

- [ ] **Step 1: Add the markup node to `index.html`**

In `vibecheck/web/index.html`, change lines 163-164 from:

```html
  <div id="tab-overview" class="tab">
    <div id="ov-totals" class="ov-totals"></div>
```

to:

```html
  <div id="tab-overview" class="tab">
    <div id="ov-vibemeter"></div>
    <div id="ov-totals" class="ov-totals"></div>
```

- [ ] **Step 2: Add the CSS**

Append to the end of `vibecheck/web/style.css`:

```css
/* ---------- VIBE-O-METER: lifetime-average hero card, top of Overview.
   Deliberately not filter-reactive — see renderVibeMeter() in app.js. ---------- */
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
.ov-vm-empty .ov-vm-pill { background: var(--vc-bg-surface-hover); color: var(--vc-text-muted); }
.ov-vm-bar { position: relative; display: flex; gap: 3px; height: 14px; margin: 0 4px; }
.ov-vm-seg { flex: 1; border-radius: 3px; }
.ov-vm-seg:first-child { border-radius: 7px 3px 3px 7px; }
.ov-vm-seg:last-child { border-radius: 3px 7px 7px 3px; }
.ov-vm-empty .ov-vm-seg { opacity: .28; }
.ov-vm-marker {
  position: absolute; top: -7px; width: 0; height: 0; transform: translateX(-50%);
  border-left: 8px solid transparent; border-right: 8px solid transparent;
  border-top: 10px solid var(--vc-text-main);
  filter: drop-shadow(0 1px 2px rgba(0,0,0,.5));
}
.ov-vm-ticks { display: flex; justify-content: space-between; margin-top: 8px; padding: 0 4px; }
.ov-vm-ticks span {
  font-family: "JetBrains Mono", "Consolas", monospace; font-size: 11px; color: var(--vc-text-muted); width: 20px;
}
.ov-vm-ticks span:first-child { text-align: left; }
.ov-vm-ticks span:last-child { text-align: right; }
.ov-vm-caption { margin-top: 18px; font-size: 12px; color: var(--vc-text-muted); }
.ov-vm-caption b { font-family: "JetBrains Mono", "Consolas", monospace; color: var(--vc-text-main); font-weight: 700; }
```

- [ ] **Step 3: Add `vibeMeterStats` and `renderVibeMeter` to `app.js`**

Insert directly before `function renderOverview(games) {` (currently
`app.js:626`, right after `renderHeader`'s closing brace):

```javascript
/* Lifetime average, always — reads ALL directly rather than the filtered
   `games` renderOverview receives, same reasoning as #profile-vibe above:
   this is the one number on Overview that shouldn't move when you filter. */
function vibeMeterStats() {
  const total = ALL.filter((g) => !g.is_remake).length;
  const rated = ALL.filter((g) => g.rated && !g.is_remake);
  const avg = rated.length ? rated.reduce((s, g) => s + g.fun_score, 0) / rated.length : null;
  return { avg, n: rated.length, total };
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
```

- [ ] **Step 4: Wire it into `renderOverview`**

Change `app.js`'s `renderOverview` (currently lines 626-635) from:

```javascript
function renderOverview(games) {
  // Computed once and shared: the spotlight below needs this exact same
  // result, and championTotals()/categoryLeaders() aren't free to redo
  // twice on every filter-bar keystroke.
  const leaders = categoryLeaders(championTotals(games));
  renderLifetimeTotals(games, leaders);
  renderSpotlight(games, leaders);
  renderAramGodCompact();
  renderVibeTrend(games);
}
```

to:

```javascript
function renderOverview(games) {
  // Deliberately first and reading ALL, not `games` — the vibe-o-meter is
  // lifetime-average and does not react to the filter bar (see
  // vibeMeterStats' doc comment). Everything below it does.
  renderVibeMeter();
  // Computed once and shared: the spotlight below needs this exact same
  // result, and championTotals()/categoryLeaders() aren't free to redo
  // twice on every filter-bar keystroke.
  const leaders = categoryLeaders(championTotals(games));
  renderLifetimeTotals(games, leaders);
  renderSpotlight(games, leaders);
  renderAramGodCompact();
  renderVibeTrend(games);
}
```

- [ ] **Step 5: Verify manually — populated state**

Run: `.venv\Scripts\python -m vibecheck` from the worktree root, open the
dashboard, land on the Overview tab.

Expected: a card at the very top reading "VIBE-O-METER", a large two-decimal
number, a colored tier pill below it with the matching `GRADES` label, a
5-segment colored bar with a triangular marker sitting at the correct
continuous position (e.g. an avg of `3.42` puts the marker about 60% of the
way across, inside the 4th/green segment, not centered on it), tick labels
1-5, and a "`N` games · `N` rated" caption below.

- [ ] **Step 6: Verify manually — filter independence**

With the Overview tab open, apply a filter (e.g. pick a single champion) via
the filter bar.

Expected: the lifetime-totals strip, spotlight, ARAM God widget, and vibe
trend below all update to reflect the filter (existing behavior). The
VIBE-O-METER card's number, pill, and marker position must **not** change —
confirm the number stays identical before and after applying the filter.

- [ ] **Step 7: Verify manually — empty state**

On a fresh profile / test data folder with zero rated games (or by
temporarily pointing `%LOCALAPPDATA%\VibeCheck` at an empty sqlite file),
load the Overview tab.

Expected: the card shows `—` for the number, "No rated games yet" in a
neutral (non-tier-colored) pill, the bar segments render at reduced opacity
with no marker, and the caption reads "0 games · 0 rated" without a console
error.

- [ ] **Step 8: Run the existing test suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\ddragon_splash_test.py
.venv\Scripts\python tests\dashboard_splash_test.py
```

Expected: every script prints its `OK` line (none of them exercise the
frontend, so this only guards against an unrelated regression).

- [ ] **Step 9: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git add vibecheck/web/index.html vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): add the VIBE-O-METER card to Overview"
```

---

## Final check before opening the PR

- [ ] Re-read `docs/superpowers/specs/2026-08-11-vibe-o-meter-design.md`
  against this task — confirm the data rule (lifetime, non-remake, filter-
  independent), the visual spec (label, number, pill, segmented bar with
  continuous marker, ticks, caption), and both states (populated + empty)
  are all covered.
- [ ] `.venv\Scripts\pre-commit run --all-files` clean.
- [ ] PR description notes this card is intentionally the one Overview
  section that ignores the filter bar, and why (it's the lifetime headline
  metric, not a per-filter breakdown) — call this out explicitly so it
  doesn't read as a missed wiring bug in review.
- [ ] PR targets/updates the same branch (`worktree-overview-redesign`) as
  the rest of the Overview redesign, since this card is designed as part of
  that same page.
