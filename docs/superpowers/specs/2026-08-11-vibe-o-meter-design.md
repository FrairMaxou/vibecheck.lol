# VIBE-O-METER card

Addendum to the Overview page redesign
(`docs/superpowers/specs/2026-08-10-overview-redesign-design.md`, implemented
in the `overview-redesign` worktree — all 8 tasks of
`docs/superpowers/plans/2026-08-10-overview-redesign.md` are already
committed). This adds one thing that spec missed: a literal **VIBE-O-METER**
card at the top of Overview — BRAND.md §6 already names `VIBE-O-METER` as a
dashboard widget, but the shipped redesign never built it.

## Problem

The Overview redesign made vibe the headline of every section, but nothing on
the page answers the single question the app exists for at a glance: "how am
I vibing, overall, right now?" That's the tool's core metric, and it deserves
the top of the page, not a number buried inside a spotlight tile.

## Scope

**In scope:** one new card, `VIBE-O-METER`, at the very top of `#tab-overview`
— above the existing lifetime-totals strip. Pure frontend; no schema or
backend change.

**Out of scope:** everything else on the page (lifetime totals, spotlight,
ARAM God, vibe trend) is unchanged.

## Data

Lifetime average `fun_score` across every non-remake rated game — **always**,
ignoring the filter bar. This is the one section of Overview that doesn't
react to the filter bar; every other section already does. Precedent: the
existing `#profile-vibe` stat (`app.js:613-617`) computes an unfiltered
lifetime average from the global `ALL` array the same way. This card tightens
that pattern slightly by also excluding remakes (`!g.is_remake`), matching
the F5 rule (`app.js:158`) the rest of the page already follows — the
existing `#profile-vibe` code predates that exclusion and is out of scope to
fix here.

- `avg` = mean `fun_score` over `ALL.filter(g => g.rated && !g.is_remake)`
- `n` = that same filtered array's length ("rated")
- `total` = `ALL.filter(g => !g.is_remake).length` ("games")

## Visual design

Approved via mockup (segmented-bar option). Top to bottom, centered:

1. **Label:** "VIBE-O-METER" (exact BRAND.md §6 string), small, uppercase,
   muted.
2. **Number:** the average to two decimals (`3.42`) — matching the
   precision `GRADES`/spotlight tiles already use elsewhere on this page —
   large, `JetBrains Mono`/monospace.
3. **Tier pill:** the exact BRAND.md tier label for `Math.round(avg)`
   ("FF at 15" / "Who Let Them Cook?" / "Meh" / "We Are So Back" /
   "Gigachad"), colored with the existing `ov-tier1..5` classes (already
   defined in `style.css` from the shipped spotlight work).
4. **Segmented meter bar:** five equal segments, one per tier color
   (`--vc-t1`…`--vc-t5`, already defined), with thin gaps between segments.
   A triangular marker sits **continuously** along the bar at
   `(avg - 1) / 4 * 100%` — not snapped to a segment boundary, so a 3.42
   average sits visibly partway through the tier-4 (green) segment rather
   than centered on it.
5. **Tick labels** 1–5 under the bar.
6. **Caption:** `<b>{total}</b> games · <b>{n}</b> rated` beneath the bar.

**Empty state** (`n === 0`): number shows `—`, pill reads "No rated games
yet" in a neutral muted style (no tier color), bar segments render at reduced
opacity, no marker.

Card styling reuses the existing `--vc-*` token set and card chrome
(`background: var(--vc-bg-surface)`, `border: 1px solid var(--vc-border)`,
`border-radius: 12px`) already established by the shipped Overview cards —
no new visual language, just a new arrangement of the existing one.

## Placement

New markup `<div id="ov-vibemeter" class="ov-vibemeter-card"></div>` as the
**first** child of `#tab-overview`, immediately before `#ov-totals`.

## Implementation shape

- One new pure function in `app.js`, e.g. `vibeMeterStats()`, reading `ALL`
  directly (not the `games` parameter `renderOverview` receives) — same
  reasoning as `#profile-vibe`: this number is deliberately not
  filter-reactive.
- One new render function, `renderVibeMeter()`, called from `renderOverview`
  alongside the existing four render calls. Cheap to call on every
  filter-bar keystroke even though its output never changes with the
  filter — no memoization needed at this scale.
- New scoped CSS under `#tab-overview` for `.ov-vibemeter-card` and its
  children, reusing `--vc-*` tokens.

## Testing

No new Python tests — frontend-only, matching the rest of this epic. Verify
manually per the existing convention: start the dev server, confirm the card
renders with real data, confirm changing the filter bar does **not** change
this card's number while it does change every section below it, and confirm
the zero-rated-games empty state on a fresh profile.

## Risk, most severe first

1. **A maintainer reads "filter bar does nothing to the top card" as a bug**,
   since every other Overview section is filter-reactive. Mitigated by
   documenting the exception explicitly here and in the implementation plan,
   plus the manual-verification step above calling it out by name.
2. **Marker math drifts from the tier-pill's `Math.round(avg)`** if a future
   edit changes one without the other (e.g. the pill always shows the
   nearest tier while the marker is continuous) — cosmetic only, not a data
   bug, since both derive from the same `avg` value computed once.
