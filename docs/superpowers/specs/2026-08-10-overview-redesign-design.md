# Overview page redesign — vibe-first tiles

Design for the **Overview** tab content (part of #59, "rebuild Overview around
at-a-glance tiles"), inside the visual-overhaul-and-data-model epic (#63).
Mockups iterated live in a browser companion; the final approved layout is
`v10` (referenced throughout — screenshots aren't checked in, but every visual
decision below reflects it).

## Problem

The current dashboard is a stat-optimizer's spreadsheet — bar charts, a
scatter plot, a tier-list table. It buries the app's actual premise (the vibe
score, not win rate) under generic esports stats, and nothing on it currently
uses champion art. This redesign makes vibe the headline everywhere and gives
the Overview tab a single coherent visual language instead of reusing
Chart.js bar/scatter widgets.

## Scope

**In scope:** the Overview tab's content area only — layout, what data each
section shows, how it's computed, and the interaction/animation model.

**Out of scope:**
- Any schema or backend change. See "Data source" below — everything this
  page needs is already a stored column or an existing endpoint.
- The full multi-champion ranked grid (every played champion, sorted
  worst→best vibe) — that belongs on the separate **Champions** tab (#60),
  not Overview. Noted as a follow-up, not designed here.
- Item/build icons anywhere — explicitly descoped earlier in this epic's
  brainstorm; nothing on this page shows item or augment art.
- Champion art caching itself (#54 already owns fetching/caching Data Dragon
  images locally). This design assumes champion splash/icon URLs resolve to
  whatever #54 lands on — for now, mockups used live Data Dragon CDN URLs
  directly (`ddragon.leagueoflegends.com`), which is fine for prototyping but
  is exactly the network dependency #54 exists to remove before ship.

## Data source — no schema change

Every number on this page is already a stored `games` column
(`kills`, `deaths`, `assists`, `duration_seconds`, `champion`) or already
joined into `games_with_details()`/`/api/games` (`fun_score` via `ratings`).
`/api/aram-god` already exists (PRD §16) and needs no change. This page is
**pure frontend work**: new aggregation functions in `web/app.js` plus new
markup/CSS, consuming data the dashboard already fetches today.

This explicitly supersedes the schema addition discussed earlier in this
epic's brainstorm (`largest_multi_kill`/`largest_killing_spree` columns,
rescoping #50): the final design never surfaced multikill/killing-spree data,
so that scope is dropped. #50 stays unstarted; revisit only if a future page
needs it.

### Reused convention: `aggregate()` and `MIN_N`

`web/app.js` already has an `aggregate(games, keyFn)` helper (used by the
existing tier list/scatter chart) that groups by a key and returns
`{key, n (rated count), games (total count), avgFun, winrate}` per group, and
a `MIN_N = 5` threshold ("not enough data yet" below 5 rated games — PRD F21,
matches BRAND.md's "CERTIFIED BANGER (min 5 games)"). This design reuses both
rather than inventing parallel logic:

- **Best Vibe** spotlight tile = the champion `aggregate()` already computes
  as the tier-list leader, filtered to `n >= MIN_N` — the same rule that
  drives the existing "Certified Banger" fun-fact card. If no champion clears
  `MIN_N`, the tile shows a "not enough data yet" state instead of picking a
  1-game outlier.
- **Most Kills / Most Deaths / Most Assists / Most Hours Played** are raw
  per-champion sums (`SUM(kills)`, `SUM(deaths)`, `SUM(assists)`,
  `SUM(duration_seconds)` grouped by `champion`), no `MIN_N` gate — these are
  "biggest total," not an average, so a small sample isn't misleading the way
  an average would be.
- All aggregations exclude remakes (`is_remake`), matching the existing
  filter pipeline every other panel already uses (`web/app.js:158`).
- **Lifetime totals** (top strip) are the same per-champion sums rolled up
  across *all* champions — `SUM(kills)` etc. over every non-remake game.
  "Since" date = the earliest stored game's `played_at`.

## Page structure

Top to bottom, one column, in this order (confirmed order from the mockup
session):

1. **Lifetime totals strip**
2. **Spotlight** (5 category-leader tiles)
3. **ARAM God run**
4. **Vibe trend**

### 1. Lifetime totals strip

Four cards: Kills, Deaths, Assists, Time Played. Each shows the lifetime sum
and a "since `<Mon YYYY>`" caption. Background is the *category leader's*
splash art (same computation as the matching spotlight tile, e.g. the Kills
card's background is whoever leads Most Kills), blurred and darkened as a
decorative backdrop — it's not itself interactive and carries no separate
"most on X" label anymore (that detail lives one section down, in Spotlight,
where it's the actual headline rather than a caption).

### 2. Spotlight (5 tiles)

One tile per category: **Best Vibe, Most Kills, Most Deaths, Most Assists,
Most Hours Played.** Each tile:

- **Idle state:** the champion's full loading-screen splash art (Data Dragon
  `img/champion/loading/{id}_0.jpg`), portrait aspect ratio, a small category
  pill top-left (icon + label, e.g. a crossed-swords glyph + "Most kills"),
  and a bottom scrim with the champion name + that category's headline
  number.
- **Hover state:** the same splash art blurs and darkens in place
  (`filter: blur(7px) brightness(.42)`), the scrim and headline fade out, and
  a centered overlay fades in showing that champion's **full profile**:
  kills, deaths, assists, hours played, and vibe score (with its tier color)
  — every stat, not just the one that earned them the tile. No flip, no
  second face, no 3D transform.
- Vibe score anywhere on this page uses the BRAND.md tier palette (tier 1
  red → tier 5 purple) for its badge/text color, never a generic accent
  color — vibe is the one thing that should always be visually distinct from
  a plain stat.

### 3. ARAM God run

Unchanged data (`/api/aram-god`), new compact presentation: an icon, "N / total"
count, the existing "S- or better..." hint text, and a horizontal progress
bar. When `tracked` is `false`, the same widget shows "not tracked yet" and a
one-line explainer instead of a fake `0/N` — one widget, two states, never
both rendered at once.

### 4. Vibe trend

A line across rated games in chronological order (existing rolling-window
trend data, PRD's existing trend chart, re-skinned). Each point is the
champion's real portrait (small circular Data Dragon square icon,
`img/champion/{id}.png`) instead of a plain dot, with a ring around it colored
by that game's rating tier. Points are real HTML `<img>` elements absolutely
positioned over a percentage-based SVG line — deliberately *not* raster
images embedded inside a scaled SVG (`<image>` inside a `viewBox`-scaled
`<svg>`), which is what made an earlier iteration look pixelated: raster
content inside a scaled SVG stretches past its native resolution. A legend
below spells out the five tier colors.

## Animation & performance

Two iterations back, the champion tiles used a 3D flip (`rotateY` +
`preserve-3d` + `backface-visibility`) with a *live-blurred* background image
on the back face, and it was noticeably laggy. Root cause: applying
`filter: blur()` to a full-size background image, recomputed continuously
during a 3D transform, on multiple tiles at once, is expensive GPU work. The
approved design (spotlight tiles, §2) never flips — hover only transitions
`filter` and `opacity` on elements that stay flat, which is materially
cheaper and is what actually fixed the lag. **Do not reintroduce a 3D flip
anywhere on this page**; if a future page (e.g. the Champions tab) wants a
flip interaction, budget for that performance cost separately rather than
assuming this page's hover pattern generalizes.

## Testing

No new Python tests — this is frontend-only, and the project doesn't have a
JS test harness today. Verify manually per the repo's UI-change convention
(start the dev server, exercise the Overview tab, check both the
`tracked`/`not tracked` ARAM God states and the `n < MIN_N` "not enough data"
state for Best Vibe on a low-game-count profile).

## Risk, most severe first

1. **Live Data Dragon fetches on every page load** (used throughout the
   mockup) would violate the "dashboard binds localhost, offline-friendly"
   constraint if shipped as-is. Mitigated by scope: this design explicitly
   depends on #54 (champion art caching) landing first or alongside it —
   not by this spec reaching for its own caching scheme.
2. **`MIN_N` gate produces an empty Best Vibe tile on a fresh install.**
   Mitigated by an explicit "not enough data yet" state (same pattern already
   used elsewhere in `app.js`), not a hidden or broken tile.
3. **Blurred category-leader art on the lifetime totals strip re-runs the
   same aggregation as the spotlight tiles.** Low risk, but worth computing
   once and sharing rather than duplicating the `aggregate()` call — a
   performance/cleanliness note for implementation, not a product risk.

## Follow-ups (not this spec)

- Champions tab: the full ranked roster (every played champion, worst→best
  vibe) — designed informally during mockup iteration (v5–v8) but explicitly
  deferred to its own spec against #60.
- #54 (champion art caching) should land before or alongside this, per risk
  #1 above.
