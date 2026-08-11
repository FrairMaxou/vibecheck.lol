# Overview: square top row + capped vibe trend

Second-round polish on the Overview redesign, requested directly by the
maintainer after using the shipped page. Addendum to
`docs/superpowers/specs/2026-08-10-overview-redesign-design.md` and
`docs/superpowers/specs/2026-08-11-vibe-o-meter-design.md`. Mockup iterated
live in the brainstorming visual companion; the approved layout is the
"both square, same anatomy" screen (`top-row-square-pair.html`).

## Problem

Two independent complaints about the shipped Overview page:

1. VIBE-O-METER and ARAM God are the two highest-signal widgets on the page
   (lifetime vibe, and progress on the long-running achievement) but they're
   visually mismatched — one is a wide horizontal card, the other a plain
   bar — and ARAM God is buried below the spotlight instead of living near
   the top with the other headline stat.
2. The vibe trend plots every rated game ever. Past a few dozen games the
   portraits overlap and the chart reads as noise instead of a trend.

## Scope

**In scope:** Overview tab only.
- Move ARAM God into a new top row, paired with VIBE-O-METER, both
  restyled as matching square cards.
- Cap the vibe trend to the most recent 20 rated games by default, with a
  way to see the rest.

**Out of scope:** everything else on the page (lifetime totals, spotlight)
is unchanged in content and position, just shifted down to make room for
the new top row. No schema or backend change — same data sources as before
(`fetchAramGod()`, `vibeMeterStats()`, the existing rated-games array).

## Page order

1. **Top row** (new): VIBE-O-METER square + ARAM God square, side by side.
2. Lifetime totals strip (unchanged).
3. Spotlight (unchanged).
4. Vibe trend (capped — see below).

ARAM God is removed from its old position (previously between spotlight and
trend) — it exists in exactly one place on the page now, the top row.

## Top row: two matching squares

Both cards share one anatomy — label, big number, pill, bar, caption — so
they read as a pair, not two unrelated widgets bolted together:

| | VIBE-O-METER | ARAM God |
|---|---|---|
| Label | "Vibe-o-meter" | "ARAM god run" |
| Big number | lifetime avg, e.g. `3.42` | `{completed}/{total}`, e.g. `17/50` |
| Pill | tier name, tier-colored (unchanged from the existing design) | `{pct}% complete`, gold-colored (new — no tier concept here) |
| Bar | existing 5-segment tier bar + continuous marker (unchanged) | single progress bar filled to `pct` (already exists as `.ov-aram-fill`, just restyled to match) |
| Caption | `{total} games · {n} rated` (unchanged) | the existing hint copy, condensed to one line: "S- or better on every ARAM champion" |

**VIBE-O-METER's square is a pure CSS change** — same markup
(`renderVibeMeter()`, `app.js:657-690`) and the same data rule (lifetime,
non-remake, filter-independent — unchanged from the 2026-08-11 spec), just
restyled from the current full-width horizontal card into a fixed-aspect
square (smaller number, tighter padding, ticks stay under the bar). No JS
changes to `renderVibeMeter()` itself.

**ARAM God needs new markup.** Its current anatomy (icon badge, title row,
hint, bar — `renderAramGodCompact()`, `app.js:380-410`) doesn't map onto
the shared square layout, so this task rewrites the function's HTML output
to the label/number/pill/bar/caption shape above. The data it reads
(`fetchAramGod()`, `tracked`/`completed`/`total`) is unchanged.

**Empty / not-tracked state** mirrors VIBE-O-METER's existing empty state
exactly, for visual consistency between the pair: number shows `—`, pill
reads "Not tracked yet" in the neutral muted style (no gold), bar renders
at 0%, caption becomes "Open the League client once with VibeCheck running
to start tracking this" (existing copy).

**Layout mechanics:** `display: grid; grid-template-columns:
repeat(auto-fit, minmax(220px, 320px))` on the row container, each card
`aspect-ratio: 1`. This self-collapses to a single column once the
container is too narrow for two 220px-minimum cards side by side (no
hardcoded breakpoint needed), the same auto-wrapping principle
`.ov-totals { flex-wrap: wrap }` already uses one row down.

## Vibe trend: cap to 20, expand on request

`renderVibeTrend(games)` (`app.js:414-445`) currently plots every rated
game. Change:

- Sort rated games chronologically (unchanged), then take the **most
  recent 20** by default (`rated.slice(-20)` after sorting ascending —
  the newest games, not the oldest, since "how have I been doing lately"
  is the point of a trend).
- If `rated.length > 20`, render a text link below the chart: `Show all
  {rated.length} games`. Clicking it re-renders the same chart with the
  full `rated` array (no cap) and the link disappears — collapsing back to
  20 is not needed (nothing else on this page has a "collapse" affordance
  either, e.g. the spotlight overlay).
- If `rated.length <= 20`, no link — behavior is identical to today.
- Expanded/collapsed is transient UI state (a module-level flag, not
  persisted) — it resets to collapsed only on a real data refresh (e.g. a
  new game arriving via `pollRev`), not on tab switch or filter change,
  consistent with how this app doesn't persist other UI toggles across
  reloads.
- The legend, ring colors, portrait rendering, and the "not squished"
  crisp-icon requirement from the original trend spec are all unchanged —
  this only changes which subset of `rated` gets passed into the existing
  point-plotting logic.

## Testing

No new Python tests — frontend-only, matching every other Overview task.
Verify manually: the top row renders as two equal squares (both populated
and both empty/not-tracked states), resizing the window narrow collapses
the row to one column without a horizontal scrollbar, the trend shows at
most 20 points by default with a working "Show all N games" expand link
that appears only when there are more than 20 rated games, and the
existing filter-bar reactivity / no-3D-transform constraints from the
original Overview spec still hold.

## Risk, most severe first

1. **ARAM God's new markup silently drops the `tracked` distinction.** The
   existing code already has a `!d.tracked || !d.total` branch — the
   rewrite must keep both conditions (a total of 0 is a different reason
   to show the empty state than never having synced), not collapse them
   into one check that happens to look right in the common case.
2. **The "Show all" link forgets to reset when the underlying game list
   changes** (e.g. a new game arrives via `pollRev`) — expanding once and
   then never seeing the cap again on a later, larger dataset. Mitigated by
   scoping the expanded flag to reset on every `renderOverview` call driven
   by a real data refresh, not just on tab switch.
3. **Square aspect-ratio cards clipping content on very narrow windows**
   before the grid's single-column breakpoint kicks in. Low risk given the
   existing page already handles a ~700px width per the original spec's
   manual-verification step; worth re-checking at that same width.

## Follow-ups (not this spec)

- The lateral nav / hamburger filter menu / profile-and-settings-in-nav
  redesign the maintainer also requested is a separate, larger design pass
  (touches every tab, not just Overview) — deliberately not folded in here.
