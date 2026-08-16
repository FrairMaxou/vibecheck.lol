# Overview polish, round 2

Third design pass on the Overview tab, requested directly by the
maintainer after using the shipped top-row/trend-cap work. Addendum to
`docs/superpowers/specs/2026-08-10-overview-redesign-design.md`,
`docs/superpowers/specs/2026-08-11-vibe-o-meter-design.md`, and
`docs/superpowers/specs/2026-08-11-overview-top-row-and-trend-cap-design.md`
— all shipped and merged to `main`. Mockup for item 5 iterated live in the
brainstorming visual companion; the approved layout is "Option B" (axis
labels + a live readout bar).

## Scope

**In scope:** six independent visual/UX fixes to the Overview tab, all in
`vibecheck/web/{index.html,app.js,style.css}`. No schema or backend
change.

**Out of scope:** the lateral icon nav, the collapsible top filter bar,
and breadcrumbs the maintainer also asked for in the same message — a
separate, larger design pass since it touches every tab, not just
Overview. Explicitly deferred, not forgotten.

## 1. Center the top row

`.ov-top-row`'s grid (`repeat(auto-fit, minmax(220px, 320px))`) has no
`justify-content`, so on a wide window the two square cards pack against
the left edge with unused space on the right instead of sitting centered
as a pair. Add `justify-content: center` to `.ov-top-row`. Purely a
one-line CSS fix — no markup or JS change.

## 2. Lifetime-totals section title

Add a section label above `#ov-totals`, matching the existing "Spotlight"
label's exact pattern (`.ov-section-label`, same markup shape as
`<div class="ov-section-label">Spotlight</div>`):

```html
<div class="ov-section-label">Lifetime totals <span class="hint">since recording started</span></div>
```

Reuses the existing `.hint` class (already used inside the Vibe trend
panel's `<h2>`) rather than inventing new styling. The per-card "since
⟨Mon YYYY⟩" captions on each of the four totals cards are unchanged —
this section label clarifies the general caveat once, at the section
level; the per-card captions still give the specific date.

## 3. Spotlight tiles: match the loading-screen aspect ratio

Current: `.ov-stile { aspect-ratio: 3 / 4; }` (0.75, relatively squat).
Data Dragon's champion loading-screen crop — the exact image these tiles
already display via `ovSplashImg`/`champSplashUrl` — is 308×560px, which
simplifies to **11:20** (0.55). Change to `aspect-ratio: 11 / 20`. This is
a genuinely slimmer (narrower relative to height) tile than a simple
height reduction would give, and it means the artwork's native proportions
drive the crop instead of an arbitrary ratio. No other `.ov-stile` rule
changes — `object-fit: cover` on the splash image already handles the new
box size correctly.

## 4. Space between spotlight and the vibe trend

`.panel` (the shared class the Vibe trend section uses) has
`margin-bottom: 14px` but no `margin-top`, so it currently sits flush
against `#ov-spotlight` above it. Add a dedicated modifier class
(`.ov-trend-panel`, added alongside the existing `class="panel"` on that
one element only — `.panel` itself is shared by many unrelated sections
elsewhere in the app and must not change) with `margin-top: 26px`,
matching the `26px` rhythm `.ov-section-label` and `.ov-top-row` already
use elsewhere on this page.

## 5. Vibe trend readability (approved mockup: Option B)

Today, the only way to see a point's date/champion/score is the native
`title` attribute tooltip (hover-only, browser-styled, easy to miss).
Approved design adds two things around the existing chart, without
changing the chart itself (portraits, ring colors, the SVG line, and the
tier-color legend all stay exactly as they are):

- **Axis labels.** A y-axis down the left edge showing tiers 5→1 top to
  bottom (plain text, matches the chart's existing 8–92% vertical
  plotting band), and an x-axis below showing up to 5 dates. These are
  not independently computed positions — they're the real dates of up to
  5 actual points, picked at evenly-spaced *indices* into the shown array
  (`Math.round(i * (n-1) / 4)` for `i` in `0..4`, deduped), so every label
  always corresponds to a real game's date and lines up under that game's
  actual x position. With fewer than 5 points, the deduped index list is
  simply shorter (e.g. 2 points → 2 labels, not 5 crowded ones). This
  makes the shape of the trend readable at a glance, without hovering.
- **A live readout bar** below the chart: champion name, date, and vibe
  label/score for whichever point is currently hovered. Defaults to the
  **most recent game** in the currently-shown set when nothing is
  hovered (so it's never blank), and updates on `mouseenter`/`mouseleave`
  per point. This gives exact per-point detail without needing to
  hold a hover — the axis labels give orientation, the readout gives
  precision.

The existing per-point `title` tooltip attribute stays too (cheap,
harmless, helps anyone still hovering) — this is additive, not a
replacement.

## 6. Real filter button on the trend (replaces "Show all N games")

Last round shipped a one-way "Show all N games" expand link. Replace it
with a small button that opens a menu of window-size choices, reusing the
exact open/close interaction pattern the existing profile menu already
uses in this file (`toggleProfileMenu`/`app.js:1028-1033`, and its
document-level outside-click-closes listener at `app.js:1639-1642`):

- Button shows the current window, e.g. `20 ▾`.
- Clicking opens a small menu: **Last 20 games** / **Last 50 games** /
  **All games**.
- Selecting an option re-renders the trend with that window and closes
  the menu.
- **Behavior change from last round:** because this is now a deliberate
  choice rather than a one-time "peek," the selected window **persists
  across data refreshes** in the session (a new game arriving via
  `pollRev` does not silently reset it back to 20) — it only resets to
  the default (20) on a full page reload. The `refresh()`-side reset line
  added last round is removed as part of this change.
- Since the profile-menu's outside-click listener is a *static* element
  (always present in `index.html`, just toggled hidden/visible), but the
  trend's filter button+menu are *rebuilt* every render (`renderVibeTrend`
  replaces `#ov-trend`'s `innerHTML` each time), the outside-click-closes
  listener for this new menu must be registered **once**, in the same
  top-level wiring section as the profile menu's own listener — not
  inside `renderVibeTrend` itself, which would re-register (and leak) a
  new `document`-level listener on every render. The button's own
  open/toggle click listener is fine to re-attach each render, same as
  last round's expand-link handler, since it's attached to an element that
  gets destroyed and recreated together with any old listener on it.

## Testing

No new Python tests — frontend-only, matching every prior Overview task.
Verify manually: the top row is visually centered at a wide window width;
"Lifetime totals" appears above the totals strip with the since-recording
note; spotlight tiles are visibly more slender and still show cropped
champion art correctly; there's clear breathing room before "Vibe trend";
the trend shows y-axis tier labels and x-axis date labels, and the readout
bar shows the latest game by default and updates on hover; the filter
button correctly switches between 20/50/All and the choice survives a
manual refresh (e.g. triggering `refresh()` from the console) without
resetting to 20.

## Risk, most severe first

1. **The trend filter menu's outside-click listener gets re-registered on
   every render if implementation doesn't follow the "register once"
   design above** — each accumulated listener still fires on every future
   click forever, a real (if minor) memory/performance leak that gets
   worse the longer a session runs. Explicitly called out above and must
   be checked in review.
2. **`justify-content: center` on `.ov-top-row` could interact oddly with
   the grid's `auto-fit` collapse behavior at the exact width where it
   switches between one and two columns**, if untested at that boundary.
   Low risk — `justify-content` only affects extra free space
   distribution, not the column count itself, but worth a narrow-window
   check alongside the equal-square check from the prior round's spec.
3. **Axis date labels could collide/overlap at very few data points** (a
   profile with only 2-3 rated games). Resolved by design (§5): labels
   are picked from deduped, evenly-spaced *indices* into the actual point
   array rather than independently computed percentage positions, so a
   small array simply produces fewer labels instead of crowded/duplicate
   ones.
